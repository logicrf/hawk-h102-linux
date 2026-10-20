#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_profile_config.py
@brief      Validate H102 presets and perform bounded profile switching and rollback.
@details    Record configuration and driver hashes separately. Use same-boot state and
            existing locks, loading stream before profile. Independent systemd post restores on failure.
            FDD initialization can briefly enable RF; call only in an authorized RF environment.
            The manifest's generator version is supplier metadata, not a binary ABI proof.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""
from __future__ import annotations

import argparse
import errno
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
import uuid

import h102_rf_owner as rf
from h102_bit_identity import selected_bit_sha256
from h102_rf_usb_tx_storage import atomic_save

CATALOG = Path('/usr/local/lib/h102-config/profiles')
STATE = Path('/run/h102-profile-config.json')
API = '68.13.7'
FIRMWARE_VERSION = '0.22.30'
STREAM_VERSION = '0.7.11.0'
STACK = 'formal'
ACTIVE_BIT_RECORD = None
"""Do not read a load receipt by default; candidates explicitly bind root-owned UART evidence."""
KERNEL = '6.6.0adi-v2024.1-24444-gc8daf49830b2'
BOOT_PINS = {
    '/boot/BOOT.BIN': '44b478bc7f38538f99d084551151639bef8ca5fbfc6378b26a564140d147a4b4',
    '/boot/image.ub': '689d3a342b1c425e13adfc9f67492e3d41507ebdfecef653a018782b72925fe4',
    '/boot/uEnv.txt': '688a87447aeb3bc8637e8209661ba5de9d1633bdfef681994e7ed5fd5e82926b',
    '/boot/h102_logicrf_master_tx_v3_lab.bit': '89075d421883390a06269d8950f93e4656470260124a713bc501f73e69b44893',
}


def configure_stack(name):
    """Select a matching fixed stack; SDK1 also verifies kernel and boot-package hashes."""
    global STACK, API, FIRMWARE_VERSION, STREAM_VERSION, KERNEL, CATALOG, STATE, BOOT_PINS
    if name == 'sdk1-candidate':
        API, FIRMWARE_VERSION, STREAM_VERSION = '68.21.6', '1.0.2', '0.7.22.0'
        KERNEL = '6.6.0-h102-sdk1-candidate+'
        CATALOG = Path('/usr/local/lib/h102-config-sdk1/profiles')
        STATE = Path('/run/h102-profile-config-sdk1.json')
        BOOT_PINS = dict(BOOT_PINS, **{
            '/boot/image-sdk1.ub': 'a504c57e3c2e0d3883c57e007087977f22609397b8cdd7ba089fc4265ee001f1'})
    elif name != 'formal' or STACK != 'formal':
        raise ValueError('STACK_SELECTION_REQUIRES_FRESH_PROCESS')
    STACK = name


def read_json(path):
    """Read a JSON object and propagate parse errors."""
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError('JSON_OBJECT_REQUIRED')
    return value


def private(path, directory=False):
    """Verify trusted paths and ancestors; root must not load user-writable configuration."""
    path = Path(path).absolute()
    for item in (path,) + tuple(path.parents):
        info = item.lstat()
        is_dir = item != path or directory
        kind = stat.S_ISDIR if is_dir else stat.S_ISREG
        if info.st_uid != 0 or info.st_mode & 0o022 or not kind(info.st_mode):
            raise ValueError('UNTRUSTED_PATH: ' + str(item))


def profile_parameters(value):
    """Extract supported channel parameters and reject unsupported SSI, FH or MCS modes."""
    syscfg = value['sysConfig']
    if (value['clocks']['deviceClock_kHz'] != 300000 or
            syscfg['duplexMode'] != 1 or syscfg['fhModeOn'] or
            syscfg['mcsMode'] or syscfg['warmBootEnable'] or
            value['rx']['rxInitChannelMask'] != 195 or
            value['tx']['txInitChannelMask'] != 12):
        raise ValueError('UNSUPPORTED_CLOCK_OR_CHANNEL_MODE')
    result = {}
    for direction in ('rx', 'tx'):
        entries = value['rx']['rxChannelCfg'] if direction == 'rx' else value['tx']['txProfile']
        if len(entries) != (8 if direction == 'rx' else 2):
            raise ValueError('TWO_CHANNELS_REQUIRED')
        result[direction] = []
        for index, entry in enumerate(entries[:2]):
            cfg = entry['profile'] if direction == 'rx' else entry
            ssi = cfg[direction + 'SsiConfig']
            # ADI numLaneSel=1 means two lanes, not one physical lane.
            if (ssi['ssiType'] != 2 or ssi['ssiDataFormatSel'] != 4 or
                    ssi['numLaneSel'] != 1 or ssi['ddrEn'] is not True or
                    ssi['lsbFirst'] or ssi['qFirst'] or ssi['strobeType'] or
                    any(ssi.get(k, False) for k in ('lvdsIBitInversion',
                        'lvdsQBitInversion', 'lvdsStrobeBitInversion', 'lvdsRxClkInversionEn'))):
                raise ValueError('UNSUPPORTED_SSI')
            rate_key = 'rxOutputRate_Hz' if direction == 'rx' else 'txInputRate_Hz'
            rate, bw = cfg[rate_key], cfg['primarySigBandwidth_Hz']
            if (type(rate) is not int or type(bw) is not int or
                    not 0 < bw <= rate <= 61440000 or bw > 40000000 or
                    cfg[direction + 'InterfaceSampleRate_Hz'] != rate):
                raise ValueError('INVALID_RATE_OR_BANDWIDTH')
            result[direction].append(dict(channel=index + 1,
                sample_rate_hz=rate, rf_bandwidth_hz=bw))
    if len({c['sample_rate_hz'] for rows in result.values() for c in rows}) != 1:
        raise ValueError('INDEPENDENT_RATES_NOT_SUPPORTED_YET')
    return result


def load_package(catalog, profile_id, trusted=False):
    """Read and verify exact package bytes, hashes, versions and parameters without device changes."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', profile_id):
        raise ValueError('INVALID_PROFILE_ID')
    directory = Path(catalog).absolute() / profile_id
    if trusted:
        private(directory, directory=True)
    blobs = {}
    for name in ('manifest.json', 'profile.json', 'stream.bin'):
        if trusted:
            private(directory / name)
        if (directory / name).is_symlink():
            raise ValueError('PACKAGE_SYMLINK')
        blobs[name] = (directory / name).read_bytes()
    manifest = json.loads(blobs['manifest.json'])
    if (manifest['schema'] != 1 or manifest['id'] != profile_id or
            manifest['api_version'] != API or manifest['firmware_version'] != FIRMWARE_VERSION or
            manifest['stream_version'] != STREAM_VERSION):
        raise ValueError('PACKAGE_VERSION_MISMATCH')
    if not isinstance(manifest.get('provenance'), dict) or not manifest['provenance']:
        raise ValueError('GENERATOR_PROVENANCE_REQUIRED')
    for name in ('profile.json', 'stream.bin'):
        if hashlib.sha256(blobs[name]).hexdigest() != manifest['sha256'][name]:
            raise ValueError('PACKAGE_DIGEST_MISMATCH: ' + name)
    if len(blobs['stream.bin']) != 32768 or not 0 < len(blobs['profile.json']) <= 73728:
        raise ValueError('PACKAGE_LENGTH')
    # The driver expects a newline closing brace; compact or prematurely closed JSON is invalid.
    profile = blobs['profile.json'].replace(b'\r\n', b'\n')
    if profile.count(b'\n}') != 1 or not profile.rstrip().endswith(b'\n}'):
        raise ValueError('DRIVER_PROFILE_TERMINATOR')
    parameters = profile_parameters(json.loads(blobs['profile.json']))
    if parameters != manifest['parameters']:
        raise ValueError('MANIFEST_PARAMETER_MISMATCH')
    return dict(id=profile_id, manifest=manifest, parameters=parameters, blobs=blobs)


def identity():
    """Read local identity and an optional trusted load receipt; Hardware.verify checks boot files.

    Reject missing, cross-boot or mismatched candidate receipts rather than inferring loaded FPGA state.
    Preserve the released identity format and share the frozen stack across actor and managed state.
    """
    if os.uname().release != KERNEL:
        raise ValueError('KERNEL_API_BINDING')
    value = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        machine_id=Path('/etc/machine-id').read_text().strip(),
        MAC=Path('/sys/class/net/eth0/address').read_text().strip(), boot_pins=BOOT_PINS)
    if ACTIVE_BIT_RECORD is not None:
        private(ACTIVE_BIT_RECORD)
        value['loaded_bit'] = read_json(ACTIVE_BIT_RECORD)
        selected_bit_sha256(value)
    return value


def snapshot(hw):
    """Save actual rates/bandwidths and digests, without claiming a full profile or port readback."""
    result = {}
    for direction, prefix in (('rx', 'in'), ('tx', 'out')):
        result[direction] = [dict(channel=i + 1,
            sample_rate_hz=int(hw.read(hw.phy / f'{prefix}_voltage{i}_sampling_frequency')),
            rf_bandwidth_hz=int(hw.read(hw.phy / f'{prefix}_voltage{i}_rf_bandwidth')))
            for i in range(2)]
    return dict(parameters=result, summary=hw.read(hw.phy / 'profile_config'))


def verify_snapshot(actual, package):
    """Cross-check actual IIO parameters against pinned SSI and reference-clock metadata."""
    if actual['parameters'] != package['parameters']:
        raise ValueError('ACTUAL_PARAMETER_MISMATCH')
    fields = dict(line.split(': ', 1) for line in actual['summary'].splitlines() if ': ' in line)
    for name, expected in {'Device clk(Hz)': '300000000', 'SSI interface': 'LVDS',
            'Duplex Mode': 'FDD', 'RX Channel Mask': '0xc3', 'TX Channel Mask': '0xc'}.items():
        if fields.get(name) != expected:
            raise ValueError('ACTUAL_PROFILE_SUMMARY_MISMATCH: ' + name)


def write_binary(path, payload):
    """Write binary sysfs data sequentially, advancing offsets and rejecting errors or short writes."""
    with Path(path).open('wb', buffering=0) as target:
        offset = 0
        while offset < len(payload):
            size = target.write(payload[offset:offset + 4096])
            if not size:
                raise OSError('SYSFS_SHORT_WRITE')
            offset += size


def quiet(hw):
    """Disable TX/DDS and verify idle; mute DDS during FDD initialization."""
    errors = hw.stop()
    if errors:
        raise RuntimeError('RF_STOP_FAILED: ' + repr(errors))
    for name in rf.DDS_NAMES:
        for i in range(4):
            hw.write(hw.alt(name, i, 'scale'), '0', 0)
    hw.idle()


def recovery_quiet(hw):
    """On PHY initialization ENODEV, disable independent DDS and permit trusted rollback reload.

    Only independent post uses this path; reject other PHY errors or active DDS/DMA/USB.
    An unreadable PHY is not confirmed off; repeat complete checks after successful reload.
    """
    unavailable = []
    for index in (0, 1):
        path = hw.phy / f'out_voltage{index}_en'
        try:
            hw.write(path, '0')
        except OSError as error:
            if error.errno != errno.ENODEV:
                raise
            unavailable.append(str(path))
            hw.record_write(dict(path=str(path), requested='0', write_error=repr(error),
                readback_ok=False, recovery_phy_unavailable=True))
    for name in rf.DDS_NAMES:
        for index in range(4):
            hw.write(hw.alt(name, index, 'raw'), '0')
            hw.write(hw.alt(name, index, 'scale'), '0', 0)
    hw.idle(phy_available=not unavailable)


def program(hw, package, recovering=False):
    """Load stream then profile, disable sources and read back; post may recover PHY ENODEV."""
    recovery_quiet(hw) if recovering else quiet(hw)
    try:
        write_binary(hw.phy / 'stream_config', package['blobs']['stream.bin'])
        write_binary(hw.phy / 'profile_config', package['blobs']['profile.json'])
    finally:
        quiet(hw)
    actual = snapshot(hw)
    verify_snapshot(actual, package)
    return actual


def dds_quantized_hz(nominal, clock):
    """Check exact ADI 16-bit odd DDS quantization, rejecting invalid or above-Nyquist requests."""
    if (type(nominal) is not int or type(clock) is not int or
            clock <= 0 or not 0 <= nominal <= clock // 2):
        raise ValueError('DDS_FREQUENCY_OUT_OF_RANGE')
    return (((nominal * 65535 // clock) | 1) * clock) // 65535


def dds_restore_plan(hw, original, managed, target):
    """Keep nominal Hz; park disabled DDS at zero beyond new Nyquist and reject active DDS first."""
    result = {}
    saved = (managed or {}).get('dds_frequencies', {})
    for channel, name in enumerate(rf.DDS_NAMES):
        clock = int(hw.read(hw.devices[name] / 'out_altvoltage_sampling_frequency'))
        target_clock = target['parameters']['tx'][channel]['sample_rate_hz']
        for index in range(4):
            path = str(hw.alt(name, index, 'frequency'))
            nominal = int(original[path])
            old = saved.get(path)
            if old and old['actual_hz'] == nominal and old['clock_hz'] == clock:
                nominal = old['nominal_hz']
            # A parked nominal value may exceed current Nyquist; actual frequency must remain valid.
            dds_quantized_hz(int(original[path]), clock)
            parked = nominal > target_clock // 2
            if parked and hw.read(hw.alt(name, index, 'raw')) != '0':
                raise ValueError('DDS_ACTIVE_OUT_OF_RANGE')
            requested = 0 if parked else nominal
            result[path] = dict(nominal_hz=nominal, write_hz=requested, parked=parked,
                clock_hz=target_clock, actual_hz=dds_quantized_hz(requested, target_clock))
    return result


class DDSRestoreHardware:
    """Borrow locked Hardware and restore nominal DDS requests with exact driver-formula readback."""
    def __init__(self, hardware, plan):
        self.hardware, self.plan = hardware, plan

    def __getattr__(self, name):
        """Preserve existing restoration behavior for all other attributes and operations."""
        return getattr(self.hardware, name)

    def write(self, path, value, tolerance=None):
        """Log DDS request, clock, expected and actual values; cleanup collects every error."""
        item = self.plan.get(str(path))
        if item is None:
            return self.hardware.write(path, value, tolerance)
        clock = int(self.hardware.read(path.parent / 'out_altvoltage_sampling_frequency'))
        if clock != item['clock_hz']:
            raise RuntimeError('DDS_CLOCK_CHANGED')
        record = dict(monotonic=time.monotonic(), path=str(path),
            requested=str(item.get('write_hz', item['nominal_hz'])), nominal_hz=item['nominal_hz'],
            parked=item.get('parked', False), original_readback=value,
            clock_hz=clock, expected=str(item['actual_hz']))
        try:
            path.write_text(record['requested'] + '\n')
            actual = self.hardware.read(path)
        except Exception as error:
            self.hardware.record_write(dict(record, write_error=repr(error), readback_ok=False))
            raise
        good = actual == record['expected']
        self.hardware.record_write(dict(record, actual=actual, readback_ok=good))
        if not good:
            raise RuntimeError('DDS_QUANTIZED_READBACK_MISMATCH: ' + str(path))
        return actual


def verify_dds(hw, plan):
    """Recheck actual DDS clock/frequency in post before committing the main result."""
    for path, item in plan.items():
        if (int(hw.read(Path(path).parent / 'out_altvoltage_sampling_frequency')) != item['clock_hz'] or
                hw.read(Path(path)) != str(item['actual_hz'])):
            raise RuntimeError('POST_DDS_READBACK_MISMATCH: ' + path)


def record_active(package, actual, board, previous, configuration_id):
    """Save same-boot managed configuration; source hashes are not chip-memory exports."""
    return dict(schema=1, profile_id=package['id'], sha256=package['manifest']['sha256'],
        actual=actual, identity=board, previous_id=previous,
        configuration_id=configuration_id, active_blob_exported=False,
        physical_port_register_readback=False, data_started=False)


def target_settings(hw, original, target):
    """Follow the original RX carrier explicitly for new SDK shared-LO packages.

    Preserve independent originals for rollback and retain legacy independent-LO behavior.
    Reject unequal RX carriers and require the manifest topology to match the actual profile.
    """
    result=dict(original)
    if target['manifest'].get('rf_lo_topology')!='shared-lo2':
        return result
    clocks=json.loads(target['blobs']['profile.json'])['clocks']
    if any(clocks[f'{port}{ch}LoSelect']!=2 for port in ('rx','tx') for ch in (1,2)):
        raise ValueError('TARGET_SHARED_LO_MAPPING_MISMATCH')
    frequencies={original[str(hw.alt('adrv9002-phy',i,'frequency'))] for i in (0,1)}
    if len(frequencies)!=1:
        raise ValueError('TARGET_SHARED_RX_FREQUENCIES_DIFFER')
    frequency=frequencies.pop()
    for i in (2,3):result[str(hw.alt('adrv9002-phy',i,'frequency'))]=frequency
    return result


def verify_target_carriers(hw, target, settings):
    """Verify all four actual carriers before shared-LO commit, catching cross-channel overrides."""
    if target['manifest'].get('rf_lo_topology')=='shared-lo2':
        for i in range(4):
            path=hw.alt('adrv9002-phy',i,'frequency')
            if hw.read(path)!=settings[str(path)]:
                raise RuntimeError('TARGET_SHARED_CARRIER_READBACK')


def transact(hw, target, previous, board, state_path, journal_path, configuration_id):
    """Run the locked transaction; independent post uses its prewritten rollback journal."""
    hw.idle()
    before = snapshot(hw)
    verify_snapshot(before, previous)
    original = hw.settings()
    restored = target_settings(hw, original, target)
    managed = None
    if Path(state_path).exists():
        private(state_path)
        candidate = read_json(state_path)
        if candidate['identity'] == board and candidate['actual'] == before:
            managed = candidate
    dds = dds_restore_plan(hw, original, managed, target) if STACK == 'sdk1-candidate' else {}
    state = dict(schema=1, identity=board, target_id=target['id'], previous_id=previous['id'],
        target_sha256=target['manifest']['sha256'], previous_sha256=previous['manifest']['sha256'],
        before=before, original=original, configuration_id=configuration_id, phase='prepared',
        dds_frequencies=dds, target_settings=restored)
    atomic_save(journal_path, state, exclusive=True)
    if Path(state_path).exists():
        Path(state_path).unlink()  # Consumers must not use an old profile ID during reinitialization.
    actual = program(hw, target)
    # Reuse tested parameter restoration after initialization; always leave TX/DDS disabled.
    if not rf.cleanup(DDSRestoreHardware(hw, dds) if dds else hw, dict(state, original=restored))['cleanup_passed']:
        raise RuntimeError('PARAMETER_RESTORE_FAILED')
    verify_target_carriers(hw, target, restored)
    actual = snapshot(hw)
    verify_snapshot(actual, target)
    state['phase'] = 'programmed'
    state['actual'] = actual
    atomic_save(journal_path, state)
    # Publish active only after post confirms idle, not before main exits.


def finish(hw, catalog, state_path, journal_path, service_ok):
    """Commit or restore independently, recording actual outcomes without false rollback success."""
    journal = read_json(journal_path)
    current = journal['identity']
    wanted = load_package(catalog, journal['target_id'], trusted=True)
    previous = load_package(catalog, journal['previous_id'], trusted=True)
    if (wanted['manifest']['sha256'] != journal['target_sha256'] or
            previous['manifest']['sha256'] != journal['previous_sha256']):
        raise ValueError('RECOVERY_PACKAGE_CHANGED')
    success = service_ok and journal['phase'] == 'programmed'
    if success:
        try:
            if hw.stop():
                raise RuntimeError('POST_STOP_FAILED')
            hw.idle()
            actual = snapshot(hw)
            verify_snapshot(actual, wanted)
            verify_target_carriers(hw, wanted, journal.get('target_settings', journal['original']))
            verify_dds(hw, journal.get('dds_frequencies', {}))
        except Exception:
            success = False
    if not success:
        if Path(state_path).exists():
            Path(state_path).unlink()
        actual = program(hw, previous, recovering=True)
        if not rf.cleanup(hw, journal)['cleanup_passed']:
            raise RuntimeError('ROLLBACK_PARAMETER_RESTORE_FAILED')
        actual = snapshot(hw)
        verify_snapshot(actual, previous)
    package = wanted if success else previous
    result = record_active(package, actual, current,
        previous['id'] if success else None, journal['configuration_id'])
    result['transaction_status'] = 'applied' if success else 'rolled_back'
    if success:
        result['dds_frequencies'] = journal.get('dds_frequencies', {})
    else:
        # Restore original Hz while preserving nominal targets to avoid accumulated quantization drift.
        result['dds_frequencies'] = {}
        for path, item in journal.get('dds_frequencies', {}).items():
            channel = next(i for i, name in enumerate(rf.DDS_NAMES)
                if Path(path).parent == hw.devices[name])
            clock = previous['parameters']['tx'][channel]['sample_rate_hz']
            parked = item['nominal_hz'] > clock // 2
            result['dds_frequencies'][path] = dict(nominal_hz=item['nominal_hz'],
                actual_hz=int(journal['original'][path]), clock_hz=clock, parked=parked,
                write_hz=0 if parked else item['nominal_hz'])
    atomic_save(state_path, result)
    atomic_save(Path(journal_path).parent / 'result.json', result, exclusive=True)
    return result


def hardware_context(stack, directory, expected):
    """Hold RX/GNSS in order and verify identity; do not write during lock contention."""
    for name in ('h102-rx-session.lock', 'h102-gnss-g0.lock'):
        descriptor = stack.enter_context(open('/run/lock/' + name, 'a+b'))
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    hw = rf.Hardware(directory, expected, None)
    api_path = Path('/sys/kernel/debug/iio') / hw.phy.name / 'api_version'
    if api_path.read_text().strip() != API:
        raise ValueError('ACTUAL_DRIVER_API_MISMATCH')
    return hw


def status(catalog):
    """Compare actual configuration with same-boot managed records and identify unknown originals."""
    board = identity()
    with ExitStack() as stack:
        hw = hardware_context(stack, Path('/run'), board)
        actual = snapshot(hw)
        hw.idle()
        managed = None
        if STATE.exists():
            private(STATE)
            value = read_json(STATE)
            if value['identity'] == board:
                package = load_package(catalog, value['profile_id'], trusted=True)
                verify_snapshot(actual, package)
                if value['sha256'] == package['manifest']['sha256'] and actual == value['actual']:
                    managed = value
        return dict(identity=board, actual=actual, managed=managed, data_idle=True,
            blob_provenance='managed_inputs_not_device_export' if managed else 'unknown')


def actor(action, directory, catalog):
    """Use bounded systemd main/post; post can read the complete journal after main is killed."""
    private(directory, directory=True)
    private(Path(__file__))
    private(directory / 'request.json')
    request = read_json(directory / 'request.json')
    if identity() != request['identity']:
        raise RuntimeError('BOOT_CHANGED')
    with ExitStack() as stack:
        hw = hardware_context(stack, directory, request['identity'])
        journal = directory / 'journal.json'
        if action == 'post':
            if not journal.exists():
                return  # Main rejected the request before any device write.
            private(journal)
            try:
                finish(hw, catalog, STATE, journal, os.environ.get('SERVICE_RESULT') == 'success')
            except Exception as error:
                hw.stop()
                if STATE.exists():
                    STATE.unlink()
                atomic_save(directory / 'recovery-error.json', dict(error=repr(error)), exclusive=True)
                raise
        else:
            target = load_package(catalog, request['target_id'], trusted=True)
            previous = load_package(catalog, request['previous_id'], trusted=True)
            if (target['manifest']['sha256'] != request['target_sha256'] or
                    previous['manifest']['sha256'] != request['previous_sha256']):
                raise ValueError('PACKAGE_CHANGED_AFTER_PREFLIGHT')
            if snapshot(hw) != request['before']:
                raise ValueError('ACTUAL_CONFIG_CHANGED_AFTER_PREFLIGHT')
            transact(hw, target, previous, request['identity'], STATE,
                journal, request['configuration_id'])


def apply_locked(catalog, target_id, previous_id=None):
    """Start one bounded transaction and succeed only after post and independent readback agree."""
    private(Path(__file__))
    target = load_package(catalog, target_id, trusted=True)
    before = status(catalog)
    managed = before['managed']
    if previous_id is None:
        if managed is None:
            raise ValueError('EXPLICIT_PREVIOUS_PACKAGE_REQUIRED')
        previous_id = managed['profile_id']
    previous = load_package(catalog, previous_id, trusted=True)
    verify_snapshot(before['actual'], previous)
    session = 'h102-rf-config-' + uuid.uuid4().hex
    directory = Path('/run') / session
    directory.mkdir(mode=0o700)
    counter = Path('/run/h102-profile-config-counter.json')
    number = 1
    if counter.exists():
        private(counter)
        sequence = read_json(counter)
        if sequence['boot_id'] == before['identity']['boot_id']:
            number = sequence['last_id'] + 1
    if not 0 < number < 2**32:
        raise ValueError('CONFIGURATION_ID_OVERFLOW')
    atomic_save(counter, dict(boot_id=before['identity']['boot_id'], last_id=number))
    atomic_save(directory / 'request.json', dict(identity=before['identity'], target_id=target_id,
        previous_id=previous_id, target_sha256=target['manifest']['sha256'],
        previous_sha256=previous['manifest']['sha256'], configuration_id=number,
        before=before['actual']), exclusive=True)
    command = ['/usr/bin/python3', '-B', str(Path(__file__).absolute()),
        '--stack', STACK, '--catalog', str(Path(catalog).absolute())]
    unit = session + '.service'
    post = shlex.join(command + ['post', '--directory', str(directory)])
    process = subprocess.run(['systemd-run', '--unit=' + unit, '--property=Type=exec',
        '--property=Restart=no', '--property=UMask=0077', '--property=KillMode=control-group',
        '--property=RuntimeMaxSec=90', '--property=TimeoutStopSec=90',
        '--property=ExecStopPost=' + post, '--wait'] + command +
        ['run', '--directory', str(directory)], check=False, timeout=200,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    atomic_save(directory / 'manager-result.json', dict(returncode=process.returncode,
        stdout=process.stdout.decode(errors='replace'), stderr=process.stderr.decode(errors='replace')),
        exclusive=True)
    result_path = directory / 'result.json'
    result = read_json(result_path) if result_path.exists() else dict(transaction_status='failed',
        evidence=str(directory), recovery_confirmed=False)
    result['evidence'] = str(directory)
    if result['transaction_status'] != 'applied':
        raise RuntimeError(json.dumps(result))
    if process.returncode != 0:
        raise RuntimeError('SYSTEMD_MAIN_POST_FAILED: ' + str(directory))
    after = status(catalog)
    if after['managed'] is None or after['managed']['configuration_id'] != number:
        raise RuntimeError('FINAL_ACTIVE_READBACK_FAILED')
    return result


def apply(catalog, target_id, previous_id=None):
    """Hold one configuration-lock FD through main/post; failure does not reuse a profile ID."""
    with open('/run/lock/h102-profile-config.lock', 'a+b') as descriptor:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return apply_locked(catalog, target_id, previous_id)


def main():
    """Return JSON; list/validate work offline while device operations require root."""
    parser = argparse.ArgumentParser(description='Manage H102 profile/stream configuration')
    parser.add_argument('--stack', choices=('formal', 'sdk1-candidate'), default='formal')
    parser.add_argument('--catalog', type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    p = sub.add_parser('validate'); p.add_argument('profile_id')
    sub.add_parser('status')
    p = sub.add_parser('apply'); p.add_argument('profile_id'); p.add_argument('--previous')
    sub.add_parser('restore')
    for action in ('run', 'post'):
        p = sub.add_parser(action); p.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    configure_stack(args.stack)
    if args.catalog is None:
        args.catalog = CATALOG
    if args.action in ('list', 'validate'):
        ids = [args.profile_id] if args.action == 'validate' else sorted(
            p.name for p in args.catalog.iterdir() if p.is_dir())
        result = [load_package(args.catalog, name)['manifest'] for name in ids]
    else:
        if os.geteuid() != 0:
            raise PermissionError('ROOT_REQUIRED')
        if args.action in ('run', 'post'):
            if args.directory.parent != Path('/run') or not args.directory.name.startswith('h102-rf-config-'):
                raise ValueError('PRIVATE_SESSION_DIRECTORY')
            actor(args.action, args.directory, args.catalog)
            return
        if args.action == 'status':
            result = status(args.catalog)
        elif args.action == 'apply':
            result = apply(args.catalog, args.profile_id, args.previous)
        else:
            value = status(args.catalog)['managed']
            if value is None or not value['previous_id']:
                raise ValueError('NO_MANAGED_PREVIOUS_CONFIGURATION')
            result = apply(args.catalog, value['previous_id'])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

# End of file: h102_profile_config.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
