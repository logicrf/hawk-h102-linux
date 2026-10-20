#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_gnss_ubx.py
@brief      Build bounded GNSS queries and parse UBX responses from contiguous G0 byte segments.
@details    Verify lengths/checksums and never join frames across missing G0 records.
            MON-VER reports raw text; association between TIM-TP and RX samples is checked separately.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-09-28
"""
import struct

POLL_IDS = {'mon-ver': (0x0a, 0x04), 'nav-pvt': (0x01, 0x07),
            'nav-timeutc': (0x01, 0x21), 'tim-tp': (0x0d, 0x01), 'time-config': (0x06, 0x8b)}
# UBX-21035062 R03: read known timing/message configuration from the RAM layer only.
TIME_KEYS = {
    0x30210001: 'rate_meas_ms', 0x30210002: 'rate_nav',
    0x2091017e: 'tim_tp_uart1_rate', 0x2091005c: 'timeutc_uart1_rate',
    0x20050023: 'tp_pulse_def', 0x20050030: 'tp_length_def',
    0x40050002: 'tp_period_us', 0x40050003: 'tp_locked_period_us',
    0x40050024: 'tp_frequency_hz', 0x40050025: 'tp_locked_frequency_hz',
    0x40050004: 'tp_length_us', 0x40050005: 'tp_locked_length_us',
    0x10050007: 'tp_enabled', 0x10050008: 'tp_sync_gnss',
    0x10050009: 'tp_use_locked', 0x1005000a: 'tp_align_tow',
    0x1005000b: 'tp_rising_polarity', 0x2005000c: 'tp_timegrid',
}


def checksum(data):
    """Compute UBX Fletcher checksum over class, ID, length and payload, excluding sync."""
    a = b = 0
    for value in data:
        a = (a + value) & 255
        b = (b + a) & 255
    return bytes((a, b))


def poll(name):
    """Build listed empty-payload queries only, never arbitrary CFG or RESET messages."""
    cls, msg = POLL_IDS[name]
    payload = b'\0\0\0\0' + b''.join(struct.pack('<I', key) for key in TIME_KEYS) if name == 'time-config' else b''
    body = struct.pack('<BBH', cls, msg, len(payload)) + payload
    return b'\xb5\x62' + body + checksum(body)


def timing_rates_ram(tp_rate, utc_rate):
    """Set two RAM-only message rates to 0/1 without changing PPS or writing BBR/flash."""
    if any(type(value) is not int or value not in (0, 1) for value in (tp_rate, utc_rate)):
        raise ValueError('Only timing output rates 0/1 are supported')
    payload = b'\0\x01\0\0' + struct.pack('<IBIB', 0x2091017e, tp_rate, 0x2091005c, utc_rate)
    body = struct.pack('<BBH', 6, 0x8a, len(payload)) + payload
    return b'\xb5\x62' + body + checksum(body)


def decode_payload(cls, msg, payload):
    """Decode bounded official fields; preserve unknown messages as hex without valid-time claims."""
    if (cls, msg) == (1, 0x21):
        if len(payload) != 20:
            raise ValueError('TIMEUTC_LENGTH')
        tow, accuracy, nano, year, month, day, hour, minute, second, flags = struct.unpack('<IIiHBBBBBB', payload)
        return dict(tow_ms=tow, accuracy_ns=accuracy, nano=nano, year=year, month=month, day=day,
                    hour=hour, minute=minute, second=second, flags=flags,
                    utc_valid=(flags & 7) == 7, absolute_time_valid=False)
    if (cls, msg) == POLL_IDS['time-config']:
        if len(payload) < 4 or payload[:4] != b'\x01\0\0\0':
            raise ValueError('VALGET_HEADER')
        values, position = {}, 4
        while position < len(payload):
            if position+4 > len(payload):
                raise ValueError('VALGET_TRUNCATED_KEY')
            key = struct.unpack_from('<I', payload, position)[0]
            if key not in TIME_KEYS or TIME_KEYS[key] in values:
                raise ValueError('VALGET_UNKNOWN_OR_DUPLICATE_KEY')
            size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}[(key >> 28) & 7]
            if position+4+size > len(payload):
                raise ValueError('VALGET_TRUNCATED_VALUE')
            values[TIME_KEYS[key]] = int.from_bytes(payload[position+4:position+4+size], 'little')
            position += 4+size
        return dict(layer='RAM', values=values, complete=len(values) == len(TIME_KEYS))
    if (cls, msg) == POLL_IDS['mon-ver']:
        if len(payload) < 40 or (len(payload)-40) % 30:
            raise ValueError('MON_VER_LENGTH')
        def text(value):
            """Decode fixed ASCII MON-VER strings, rejecting invalid encoding and retaining whitespace."""
            return value.split(b'\0', 1)[0].decode('ascii')
        return dict(software=text(payload[:30]), hardware=text(payload[30:40]),
                    extensions=[text(payload[i:i+30]) for i in range(40, len(payload), 30)])
    if (cls, msg) == POLL_IDS['tim-tp']:
        if len(payload) != 16:
            raise ValueError('TIM_TP_LENGTH')
        tow, sub, qerr, week, flags, ref = struct.unpack('<IIiHBB', payload)
        return dict(tow_ms=tow, tow_sub_ms_raw=sub, qerr_ps=qerr, week=week, flags=flags, ref_info=ref,
                    time_base='utc' if flags & 1 else 'gnss', utc_available=bool(flags & 2),
                    qerr_valid=not bool(flags & 16), locked_to_gnss=not bool(flags & 32),
                    absolute_time_valid=False)
    return {'payload_hex': payload.hex()}


def decode_segments(segments):
    """Scan contiguous segments, recording checksum/truncation errors without resync inside payload."""
    messages, errors = [], []
    for number, segment in enumerate(segments):
        data = bytes.fromhex(segment) if isinstance(segment, str) else bytes(segment)
        position = 0
        while True:
            start = data.find(b'\xb5\x62', position)
            if start < 0:
                break
            if len(data)-start < 6:
                errors.append(dict(segment=number, offset=start, reason='truncated_header'))
                break
            cls, msg, length = struct.unpack_from('<BBH', data, start+2)
            if length > 4096:
                errors.append(dict(segment=number, offset=start, reason='oversize'))
                position = start+2
                continue
            end = start+8+length
            if end > len(data):
                errors.append(dict(segment=number, offset=start, reason='truncated_payload'))
                break
            raw = data[start:end]
            if checksum(raw[2:-2]) != raw[-2:]:
                errors.append(dict(segment=number, offset=start, reason='checksum'))
                position = start+2
                continue
            result = dict(segment=number, offset=start, cls=cls, msg=msg, frame_hex=raw.hex())
            try:
                result['decoded'] = decode_payload(cls, msg, raw[6:-2])
            except (ValueError, UnicodeError) as error:
                result['decode_error'] = str(error)
            messages.append(result)
            position = end
    return dict(messages=messages, errors=errors, absolute_time_valid=False)

# End of file: h102_gnss_ubx.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
