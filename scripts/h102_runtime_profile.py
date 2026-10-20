"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_runtime_profile.py
@brief      Verify an active SDK1 profile and bitstream capability before generating USB templates.
@details    Hold configuration, RX and GNSS locks while reading managed inputs and registers.
            Verify the exact approved 29/58 catalog, same-boot records, hashes, channels and SSI NORMAL.
            Do not switch profiles, allocate persistent epochs, write MMIO or enable RF/DMA/time.
            The actual owner saves inputs before its bounded transaction and fresh PPS qualification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.1.0
@date       2026-10-15
"""
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import struct

import h102_profile_config as profiles
import h102_rf_owner as rf
import h102_rx_v3_config as rx
import h102_tx_v3_config as tx
from h102_iio_owner_lock import configuration_lock
from h102_runtime_rates import validate_rate_bandwidth, qualify_native_time
from h102_bit_identity import selected_bit_sha256

APPROVED_SHA256 = '91c85ab2d70d3f147cdd915d6969a1d636bf1613af5f0283b810c934d23cb979'
"""Pin the approved 29-preset catalog; additions require regeneration and source review."""
APPROVED_CATALOG_COUNTS = {
    APPROVED_SHA256: 29,
    'a0ed0ef7993e3afb40321e7f70723ed3e7cda756339f30f22fea4ea9782d8521': 58,
}
"""Accept only original 29-package or frozen dual-LO 58-package catalogs."""
BASELINE_BIT_SHA256 = '89075d421883390a06269d8950f93e4656470260124a713bc501f73e69b44893'
"""Reject the old fixed-40/20 bitstream even if a boot file with the same name was replaced."""
CONFIG_OFFSETS = tuple(range(0x440, 0x478, 4)) + tuple(range(0x480, 0x4b8, 4))
TX_OFFSETS = tuple(range(0x640, 0x740, 4))
"""Read both 112-byte RX and 256-byte TX register images without changing owner registers."""


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)+'\n').encode()


def _ssi_normal(hw):
    """Check four driver test caches NORMAL and TX loopback zero; not independent chip inspection."""
    debug = Path('/sys/kernel/debug/iio')/hw.phy.name
    if any(hw.read(debug/f'{direction}{i}_ssi_test_mode_data') != 'TESTMODE_DATA_NORMAL'
           for direction in ('rx','tx') for i in (0,1)) or any(
            hw.read(debug/f'tx{i}_ssi_test_mode_loopback_en') != '0' for i in (0,1)):
        raise RuntimeError('RUNTIME_SSI_NOT_NORMAL')


class RuntimeProfile:
    """Hold a read-only profile snapshot inside the locked context; reject use after exit.

    Profile/stream bytes are managed inputs, not chip exports. Freeze internal JSON as bytes;
    returned copies cannot change validation conditions or authorize RUN/time enable.
    """
    def __init__(self, hw, board, state_path, state_raw, package, actual_rx, actual_tx):
        """Called by an already-locked factory; freeze inputs and registers without hardware changes."""
        self._hw, self._board, self._state_path = hw, board, state_path
        self._state_raw = state_raw
        self._rx, self._tx = _json_bytes(actual_rx), _json_bytes(actual_tx)
        self.profile_id = package['id']
        self.expected_profile = validate_rate_bandwidth(tuple(
            package['parameters']['rx'][0][key] for key in ('sample_rate_hz', 'rf_bandwidth_hz')))
        self._blobs = {name: bytes(raw) for name, raw in package['blobs'].items()}
        self._identity = _json_bytes(hw.expected)
        self.original_rx = struct.pack('<28I', *(board.read(offset) for offset in CONFIG_OFFSETS))
        self.original_tx = struct.pack('<64I', *(board.read(offset) for offset in TX_OFFSETS))
        self.previous_rx_epoch, self.previous_time_epoch = board.read(0x204), board.read(0x408)
        self._active = True

    def check(self):
        """Before reuse verify boot, records and all four channels without rehashing large boot files.

        Changed inputs raise RuntimeError and require stopping and independent recovery, not renewal.
        This checks static configuration only; owners still check enables, deadlines and templates.
        """
        if not self._active:
            raise RuntimeError('RUNTIME_PROFILE_CONTEXT_CLOSED')
        self._hw.verify(complete=False)
        self._board.validate()
        _ssi_normal(self._hw)
        if self._board.read(0x424) != 1 or _json_bytes(self._hw.expected) != self._identity:
            raise RuntimeError('RUNTIME_BIT_OR_IDENTITY_CHANGED')
        profiles.private(self._state_path)
        if self._state_path.read_bytes() != self._state_raw:
            raise RuntimeError('RUNTIME_ACTIVE_PROFILE_CHANGED')
        if (_json_bytes(rx.read_applied(self._hw.phy, expected_profile=self.expected_profile)) != self._rx or
                _json_bytes(tx.read_applied(self._hw.phy, expected_profile=self.expected_profile)) != self._tx):
            raise RuntimeError('RUNTIME_ACTUAL_CONFIGURATION_CHANGED')

    def templates(self, rx_stream_id, tx_stream_id, configuration_id, device_id):
        """Return RX112/TX256 bytes using distinct stream IDs, a fresh USB configuration ID and MAC ID.

        Do not allocate or persist IDs; callers use the existing allocator before submission.
        The configuration ID must exceed captured RX and time epochs; encoding is not domain commit.
        """
        self.check()
        if (type(configuration_id) is not int or
                not max(self.previous_rx_epoch, self.previous_time_epoch) < configuration_id < 2**32 or
                type(rx_stream_id) is not int or type(tx_stream_id) is not int or
                not 0 < rx_stream_id < 2**64 or not 0 < tx_stream_id < 2**64 or rx_stream_id == tx_stream_id or
                type(device_id) is not int or device_id != int(self._hw.expected['MAC'].replace(':', ''), 16)):
            raise ValueError('RUNTIME_NEW_EPOCH_STREAM_OR_DEVICE_REQUIRED')
        return (rx.encode(json.loads(self._rx), rx_stream_id, configuration_id, device_id,
                          expected_profile=self.expected_profile),
                tx.encode(json.loads(self._tx), tx_stream_id, configuration_id, device_id,
                          expected_profile=self.expected_profile))

    def save_inputs(self, directory):
        """Exclusively save exact inputs, parameters and registers in a new directory without device writes.

        Callers retain partial output and errors; partial saving is not completed preparation.
        """
        self.check()
        directory = Path(directory)
        directory.mkdir(mode=0o700)
        for name, raw in self._blobs.items():
            rx.durable(directory/name, raw)
        rx.durable(directory/'managed-state.json', self._state_raw)
        rx.durable(directory/'original-rx.bin', self.original_rx)
        rx.durable(directory/'original-tx.bin', self.original_tx)
        rx.durable(directory/'runtime-profile.json', _json_bytes(dict(
            schema=1, profile_id=self.profile_id, identity=json.loads(self._identity),
            expected_profile=list(self.expected_profile), RX_actual=json.loads(self._rx),
            TX_actual=json.loads(self._tx), previous_rx_epoch=self.previous_rx_epoch,
            previous_time_epoch=self.previous_time_epoch, active_blob_exported=False,
            provenance='same_boot_managed_package_and_four_channel_actual_parameters',
            qualification='read_only_preparation_not_data_or_time_acceptance')))
        self.check()

    def qualify_time(self, snapshot, mask, epoch, *, cadence_baseline=None):
        """Validate fresh epochs and matching sample rates for the existing GNSS qualification callback.

        The owner saves original message rates and commits a fresh time epoch before this read-only check.
        Existing GNSS recovery handles errors; an initially invalid timestamp must not start streaming.
        An optional baseline is captured under locks with stable configuration and time disabled;
        bind it to these inputs, retaining cumulative cadence counts and rejecting new errors.
        """
        self.check()
        if type(epoch) is not int or not max(self.previous_rx_epoch, self.previous_time_epoch) < epoch < 2**32:
            raise ValueError('RUNTIME_NEW_TIME_EPOCH_REQUIRED')
        return qualify_native_time(snapshot, mask, self.expected_profile, epoch,
                                   cadence_baseline=cadence_baseline)


@contextmanager
def runtime_profile(hw, board, catalog, state_path, approved_path, *, bit_path, bit_sha256):
    """Acquire configuration/RX/GNSS locks, verify managed SDK1 inputs and yield a read-only profile.

    Use existing identity/MMIO backends and explicitly select the SDK1 stack before calling.
    Require pinned bitstream identity, complete boot-file verification and runtime capability 0x424;
    file hashes do not export FPGA memory, so retain the actual boot/load receipt provenance.
    Reject contention, invalid inputs, old bitstreams, busy sources or mismatched readback without writes.
    """
    if (profiles.STACK != 'sdk1-candidate' or os.uname().release != profiles.KERNEL or
            not isinstance(bit_sha256, str) or not re.fullmatch('[0-9a-f]{64}', bit_sha256) or
            bit_sha256 == BASELINE_BIT_SHA256 or hw.expected['boot_pins'].get(str(bit_path)) != bit_sha256):
        raise ValueError('RUNTIME_EXACT_SDK1_AND_NEW_BIT_REQUIRED')
    if (selected_bit_sha256(hw.expected) != bit_sha256 or
            'loaded_bit' in hw.expected and hw.expected['loaded_bit']['bit_path'] != str(bit_path)):
        raise ValueError('RUNTIME_LOADED_BIT_DOES_NOT_MATCH_REQUEST')
    value = None
    with ExitStack() as scope:
        scope.enter_context(configuration_lock(timeout=3))
        for name in ('h102-rx-session.lock', 'h102-gnss-g0.lock'):
            descriptor = scope.enter_context(open('/run/lock/'+name, 'a+b'))
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hw.verify();board.validate();hw.idle()
        if board.read(0x424) != 1:
            raise ValueError('RUNTIME_CAPABILITY_REQUIRED')
        if any(board.read(offset) for offset in (0x200,0x20c,0x404,0x40c,0x604,0x60c,0x620)):
            raise RuntimeError('RUNTIME_USB_TIME_NOT_IDLE')
        if any(hw.read(hw.alt(name, i, 'raw')) != '0' for name in rf.DDS_NAMES for i in range(4)):
            raise RuntimeError('RUNTIME_DDS_NOT_OFF')
        _ssi_normal(hw)
        state_path, approved_path = Path(state_path), Path(approved_path)
        profiles.private(state_path);profiles.private(approved_path)
        state_raw, approved_raw = state_path.read_bytes(), approved_path.read_bytes()
        expected_count = APPROVED_CATALOG_COUNTS.get(hashlib.sha256(approved_raw).hexdigest())
        if expected_count is None:
            raise ValueError('RUNTIME_APPROVED_CATALOG_CHANGED')
        approved = json.loads(approved_raw)['profiles'];state = json.loads(state_raw)
        if len(approved) != expected_count or len({item['id'] for item in approved}) != expected_count:
            raise ValueError('RUNTIME_APPROVED_CATALOG_CHANGED')
        selected = [item for item in approved if item['id'] == state['profile_id']]
        if len(selected) != 1 or state['identity'] != hw.expected or state.get('transaction_status') != 'applied':
            raise ValueError('RUNTIME_SAME_BOOT_APPLIED_PROFILE_REQUIRED')
        package = profiles.load_package(catalog, state['profile_id'], trusted=True)
        actual = profiles.snapshot(hw);profiles.verify_snapshot(actual, package)
        expected = validate_rate_bandwidth((selected[0]['sample_rate_hz'], selected[0]['rf_bandwidth_hz']))
        if (state['sha256'] != package['manifest']['sha256'] or state['actual'] != actual or
                any((row['sample_rate_hz'],row['rf_bandwidth_hz']) != expected
                    for rows in package['parameters'].values() for row in rows)):
            raise ValueError('RUNTIME_PACKAGE_STATE_OR_PARAMETERS_MISMATCH')
        value = RuntimeProfile(hw, board, state_path, state_raw, package,
            rx.read_applied(hw.phy, expected_profile=expected), tx.read_applied(hw.phy, expected_profile=expected))
        try:
            value.check()
            yield value
        finally:
            value._active = False

# End of file: h102_runtime_profile.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
