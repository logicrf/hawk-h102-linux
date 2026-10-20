#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_tx_v3_config.py
@brief      Read actual TX configuration and encode two immediate-TX 128-byte header templates.
@details    The outer guard requires RF/DMA off; read IIO only without changing LO/gain/enables.
            TX hardware gain is already negative dB and must not be negated to positive gain.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.2.0
@date       2026-10-08
"""
from decimal import Decimal
from pathlib import Path
import struct
from h102_runtime_rates import validate_rate_bandwidth, verify_channels

PHY = Path('/sys/bus/iio/devices/iio:device2')


def read_applied(phy=PHY, *, expected_profile=None):
    """Read actual LO/Fs/BW/negative gain on both channels; runtime Fs/BW must be verified.

    Callers check bitstream, catalog, all four channels and package hashes under three locks.
    """
    expected_rate, expected_bandwidth = validate_rate_bandwidth(
        (40000000, 20000000) if expected_profile is None else expected_profile)
    channels = []
    for index in range(2):
        def read(suffix):
            return (phy / f'out_voltage{index}_{suffix}').read_text().strip()
        mode = read('atten_control_mode')
        rate, bandwidth = int(read('sampling_frequency')), int(read('rf_bandwidth'))
        center = int((phy / f'out_altvoltage{index+2}_TX{index+1}_LO_frequency').read_text())
        raw_gain = read('hardwaregain')
        gain = Decimal(raw_gain.removesuffix(' dB')) * 1000
        if mode != 'spi' or rate != expected_rate or bandwidth != expected_bandwidth:
            raise ValueError('UNVALIDATED_TX_PROFILE_OR_ATTENUATION_MODE')
        if not 30000000 <= center <= 6000000000 or gain != int(gain) or not -(2**31) <= gain <= 0:
            raise ValueError('INVALID_TX_LO_OR_GAIN')
        channels.append(dict(channel=index+1, sample_rate_num=rate, sample_rate_den=1,
            rf_bandwidth_hz=bandwidth, center_frequency_hz=center, gain_mode=1,
            gain_mode_iio=mode, signed_gain_mdb=int(gain), attenuation_mdb=-int(gain),
            hardwaregain_iio=raw_gain))
    return dict(channels=channels, profile_summary=(phy/'profile_config').read_text())


def encode(applied, stream_id, configuration_id, device_id, *, expected_profile=None):
    """Preserve the 128-byte format and require runtime channel settings to match the requested profile.

    Dynamic time/sequence fields are zero; encoding does not prove bitstream or chip support.
    """
    expected_rate, expected_bandwidth = validate_rate_bandwidth(
        (40000000, 20000000) if expected_profile is None else expected_profile)
    if expected_profile is not None:
        verify_channels(applied, expected_profile)
    if (type(stream_id) is not int or not 0 < stream_id < 2**64 or
        type(configuration_id) is not int or not 0 < configuration_id < 2**32 or
        type(device_id) is not int or not 0 < device_id < 2**64):
        raise ValueError('INVALID_ID')
    result = bytearray()
    if [c['channel'] for c in applied['channels']] != [1, 2]:
        raise ValueError('PHYSICAL_CHANNEL_ORDER')
    for channel in applied['channels']:
        if (channel['sample_rate_num'] != expected_rate or channel['sample_rate_den'] != 1 or
            channel['rf_bandwidth_hz'] != expected_bandwidth or channel['gain_mode'] != 1):
            raise ValueError('UNVALIDATED_FIXED_PROFILE')
        h = bytearray(128)
        h[:8] = b'H102' + bytes([3, 2, channel['channel'], 1])
        struct.pack_into('<H', h, 8, 128)
        struct.pack_into('<I', h, 16, 8192)
        struct.pack_into('<QI', h, 32, stream_id, configuration_id)
        struct.pack_into('<QIIQIi', h, 48, channel['sample_rate_num'], channel['sample_rate_den'],
            2048, channel['center_frequency_hz'], channel['rf_bandwidth_hz'], channel['signed_gain_mdb'])
        struct.pack_into('<Q', h, 96, device_id)
        h[104:110] = bytes([1]*6)
        result += h
    return bytes(result)

# End of file: h102_tx_v3_config.py
