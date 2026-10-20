"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_bit_identity.py
@brief      Select the GNSS source digest from a unique bitstream or same-boot load receipt.
@details    Validate an in-memory identity only. Multiple bitstreams require an explicit
            load record; an invalid record must not fall back to a single-file assumption.
            Callers verify root-owned originals and boot hashes; file presence does not prove loading.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-09
"""
from pathlib import PurePosixPath
import re


def selected_bit_sha256(expected: dict) -> str:
    """Return a digest only if an explicit load receipt matches identity and boot pins.

    Preserve legacy single-bitstream behavior; reject missing or invalid multi-file records
    without choosing the first dictionary entry or authorizing MMIO, time or RF operations.
    """
    pins = expected['boot_pins']
    bits = {path: sha for path, sha in pins.items() if path.endswith('.bit')}
    if 'loaded_bit' not in expected:
        if len(bits) != 1:
            raise RuntimeError('GNSS_BIT_PIN')
        return next(iter(bits.values()))
    record = expected['loaded_bit']
    fields = {'schema', 'boot_id', 'machine_id', 'MAC', 'bit_path',
              'bit_sha256', 'uart_raw_sha256'}
    if not isinstance(record, dict) or set(record) != fields or (
            type(record['schema']) is not int or record['schema'] != 1):
        raise RuntimeError('LOADED_BIT_RECORD_SCHEMA')
    if any(record[key] != expected[key] for key in ('boot_id', 'machine_id', 'MAC')):
        raise RuntimeError('LOADED_BIT_RECORD_IDENTITY')
    path = record['bit_path']
    if not isinstance(path, str) or PurePosixPath(path).parent != PurePosixPath('/boot') or (
            str(PurePosixPath(path)) != path or not path.endswith('.bit')):
        raise RuntimeError('LOADED_BIT_RECORD_PATH')
    for key in ('bit_sha256', 'uart_raw_sha256'):
        if not isinstance(record[key], str) or not re.fullmatch('[0-9a-f]{64}', record[key]):
            raise RuntimeError('LOADED_BIT_RECORD_DIGEST')
    if bits.get(path) != record['bit_sha256']:
        raise RuntimeError('LOADED_BIT_RECORD_PIN')
    return record['bit_sha256']

# End of file: h102_bit_identity.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
