#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_rx_v3_config.py
@brief      Read actual IIO parameters and encode fixed or explicitly verified runtime v3 registers.
@details    Do not write RF attributes. Raw profiles come from candidate packages and
            actual metadata comes from the driver; preserve boot-default provenance, not a chip-export claim.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.2.0
@date       2026-10-08
"""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import struct
from h102_runtime_rates import validate_rate_bandwidth, verify_channels

PHY = Path('/sys/bus/iio/devices/iio:device2')


def durable(path, content):
    """Fsync new evidence and parent directory; never overwrite an existing stream record."""
    path = Path(path)
    with path.open('xb') as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    descriptor = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_applied(phy=PHY, *, expected_profile=None):
    """Read both channels' rate/bandwidth/LO/gain; runtime Fs/BW must be explicitly verified.

    Callers check bitstream, catalog, actual four channels and package hashes under three locks.
    """
    expected_rate, expected_bandwidth = validate_rate_bandwidth(
        (40000000, 20000000) if expected_profile is None else expected_profile)
    channels = []
    for index in (0, 1):
        def read(suffix):
            return (phy / f'in_voltage{index}_{suffix}').read_text().strip()
        mode = read('gain_control_mode')
        if mode not in ('spi', 'automatic'):
            raise ValueError('UNVALIDATED_GAIN_MODE: ' + mode)
        rate, bandwidth = int(read('sampling_frequency')), int(read('rf_bandwidth'))
        center = int((phy / f'out_altvoltage{index}_RX{index+1}_LO_frequency').read_text())
        gain = Decimal(read('hardwaregain').removesuffix(' dB')) * 1000 if mode == 'spi' else Decimal(0)
        if rate != expected_rate or bandwidth != expected_bandwidth or not 30000000 <= center <= 6000000000:
            raise ValueError('UNVALIDATED_FIXED_PROFILE')
        if gain != int(gain):
            raise ValueError('GAIN_NOT_EXACT_MDB')
        channels.append(dict(channel=index+1, sample_rate_num=rate, sample_rate_den=1,
                             rf_bandwidth_hz=bandwidth, center_frequency_hz=center,
                             gain_mode=1 if mode=='spi' else 2, gain_mode_iio=mode,
                             manual_gain_mdb=int(gain), manual_gain_valid=mode=='spi',
                             first_effective_sample_index=0))
    return dict(channels=channels, profile_summary=(phy/'profile_config').read_text())


def encode(applied, stream_id, configuration_id, device_id, *, expected_profile=None):
    """Encode both channels into the 424-bit layout, checking runtime Fs/BW and physical order.

    Preserve the default legacy interface; encoding neither submits registers nor qualifies USB/GNSS.
    """
    if expected_profile is not None:
        verify_channels(applied, expected_profile)
        if any(type(value) is not int for value in (stream_id, configuration_id, device_id)):
            raise ValueError('INVALID_ID')
    if not 0 < stream_id < 2**64 or not 0 < configuration_id < 2**32 or not 0 < device_id < 2**64:
        raise ValueError('INVALID_ID')
    result = bytearray()
    for channel in applied['channels']:
        flags = 0x2f | (0x10 if channel['manual_gain_valid'] else 0)
        result += struct.pack('<QIIQIiIQQB3x', channel['sample_rate_num'], channel['sample_rate_den'],
                              channel['rf_bandwidth_hz'], channel['center_frequency_hz'], configuration_id,
                              channel['manual_gain_mdb'], flags, device_id, stream_id, channel['gain_mode'])
    if len(result) != 112:
        raise AssertionError('CONFIGURATION_LAYOUT')
    return bytes(result)


def prepare(directory, applied, stream_id, configuration_id, identity, bundle):
    """Use the fixed boot-profile entry; runtime packages require exact managed loaded originals.

    This profile.json is the kernel default and must not be labeled the currently active preset.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    device_id = int(identity['board_mac'].replace(':', ''), 16)
    profile = (Path(__file__).parent/'Navassa_LVDS_profile.json').read_bytes()
    if hashlib.sha256(profile).hexdigest() != bundle['profile_sha256']:
        raise RuntimeError('PROFILE_BUNDLE_MISMATCH')
    record = dict(schema=3, stream_id=str(stream_id), configuration_id=configuration_id,
                  device_id=str(device_id), device_id_source='board_mac_eui48_zero_extended',
                  identity=identity, applied=applied, bundle=bundle,
                  profile_provenance='pinned_kernel_boot_default_plus_runtime_summary_not_exported_active_blob',
                  rf_delay_calibrated=False)
    native = encode(applied, stream_id, configuration_id, device_id)
    durable(directory/'profile.json', profile)
    durable(directory/'configuration.json', (json.dumps(record, indent=2)+'\n').encode())
    durable(directory/'configuration.bin', native)
    return record, native

# End of file: h102_rx_v3_config.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
