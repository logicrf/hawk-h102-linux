#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_rf_owner.py
@brief      Run bounded board DDS loopback sessions with disconnect stop and independent cleanup.
@details    Run as systemd Type=simple with ExecStopPost invoking cleanup again.
            Do not install services, switch power, change USB/GNSS registers or create IIO buffers.
            R1 is one-channel/one-second; R2/R3 are dual-channel 10/300-second stages with host locks.
            Manager cleanup after SIGKILL cannot replace a hardware watchdog or bound blocked SPI latency.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.3
@date       2026-10-15
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import select
import signal
import stat
import struct
import time

from h102_rf_usb_tx_storage import atomic_save

LEASE_SECONDS = 3.0
SESSION_SECONDS = 60.0
STAGES = {'R1': (1, (1, 2), 60.0), 'R2': (10, (3,), 60.0),
          'R3': (300, (3,), 360.0)}
"""Fixed stages, channel masks and absolute session limits; RF duration cannot be extended."""
PROFILE_SHA = 'ce64b92cacc6f3caedd155787f813d24df5f13c88861ae4b9b9f39a2f7f75021'
TX_GAIN_DB = '-40'
"""Prepare attenuation with DDS off; reapply active -20 dB after arming before claiming output."""
RX_GAIN_DB = '30'
"""The fixed loop uses 30 dB RX gain with active TX -20 dB and DDS scale 0.25."""
PHY_NAME = 'adrv9002-phy'
DDS_NAMES = ('axi-adrv9002-tx-lpc', 'axi-adrv9002-tx2-lpc')
DMA_NAMES = ('axi-adrv9002-rx-lpc', 'axi-adrv9002-rx2-lpc') + DDS_NAMES


def save(path: Path, value: dict, exclusive: bool = False) -> None:
    """Use unique temporary files for atomic commit, allowing recovery after interrupted writes.

    Fsync contents, link exclusively or atomically replace, then fsync the parent; retain failures.
    Do not change services, permissions or deadlines; callers own their private session directory.
    """
    atomic_save(path, value, exclusive=exclusive)


class Lease:
    """Use a single-threaded monotonic state machine; replay, disconnect or deadline stops RF."""
    def __init__(self, now: float, stage: str = 'R1'):
        self.seconds, self.channels, session = STAGES[stage]
        self.absolute = now + session
        self.expires = now + LEASE_SECONDS
        self.rf_deadline = None
        self.sequence = 0
        self.armed_once = False

    def command(self, value: dict, now: float) -> str:
        """Validate sequence and the initial one-second single-channel scope; cleanup handles errors."""
        if not isinstance(value, dict):
            raise ValueError('COMMAND_OBJECT')
        if self.expired(now):
            raise ValueError('LEASE_EXPIRED')
        if type(value.get('sequence')) is not int or value['sequence'] != self.sequence + 1:
            raise ValueError('COMMAND_SEQUENCE')
        op = value.get('op')
        if op not in ('heartbeat', 'arm', 'stop'):
            raise ValueError('COMMAND_OPERATION')
        if op == 'arm':
            if (self.armed_once or type(value.get('channel')) is not int
                    or value['channel'] not in self.channels
                    or type(value.get('seconds')) is not int or value['seconds'] != self.seconds):
                raise ValueError('FIRST_RF_WINDOW_LIMIT')
            self.rf_deadline = now + self.seconds
            self.armed_once = True
        self.sequence = value['sequence']
        self.expires = min(now + LEASE_SECONDS, self.absolute)
        return op

    def expired(self, now: float) -> bool:
        """RF expiry ends the session; heartbeats never extend RF or the absolute session deadline."""
        return now >= min(self.absolute, self.expires, self.rf_deadline or self.absolute)


class Hardware:
    """Borrow fixed board IIO attributes under main's identity/locks and log every write/readback."""
    def __init__(self, directory: Path, expected: dict, fixture: Path | None):
        self.directory, self.expected, self.fixture = directory, expected, fixture
        self.verify()
        root = fixture if fixture else Path('/sys/bus/iio/devices')
        self.devices = {}
        for path in root.glob('iio:device*'):
            if (path / 'name').exists():
                name = (path / 'name').read_text().strip()
                if name in (PHY_NAME,) + DMA_NAMES:
                    if name in self.devices:
                        raise RuntimeError('DUPLICATE_IIO_NAME')
                    self.devices[name] = path
        if set(self.devices) != set((PHY_NAME,) + DMA_NAMES):
            raise RuntimeError('IIO_DEVICE_SET')
        self.phy = self.devices[PHY_NAME]
        self.alt_attributes = {}
        for name in (PHY_NAME,) + DDS_NAMES:
            attrs = ('frequency',) if name == PHY_NAME else ('frequency', 'phase', 'scale', 'raw')
            for i in range(4):
                for attr in attrs:
                    prefix = f'out_altvoltage{i}_'
                    candidates = [p for p in self.devices[name].iterdir()
                        if p.name.startswith(prefix) and (p.name == prefix + attr
                            or p.name.endswith('_' + attr)) and p.is_file()]
                    if len(candidates) != 1:
                        raise RuntimeError('AMBIGUOUS_ALT_ATTRIBUTE: ' + name + '/' + prefix + attr)
                    self.alt_attributes[name, i, attr] = candidates[0]

    def alt(self, name: str, index: int, attr: str) -> Path:
        """Discover unique actual LO/DDS filenames, including IIO extend_name rather than guessed paths."""
        return self.alt_attributes[name, index, attr]

    def verify(self, complete: bool = True) -> None:
        """Hash boot inputs initially; before stop check live identity only to avoid shutdown delay."""
        if self.fixture:
            if not self.fixture.is_dir() or self.fixture.is_symlink():
                raise RuntimeError('FIXTURE_DIRECTORY')
            return
        values = {
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'machine_id': Path('/etc/machine-id').read_text().strip(),
            'MAC': Path('/sys/class/net/eth0/address').read_text().strip(),
        }
        if any(values[k] != self.expected[k] for k in values):
            raise RuntimeError('BOARD_IDENTITY')
        if complete:
            for path, wanted in self.expected['boot_pins'].items():
                if hashlib.sha256(Path(path).read_bytes()).hexdigest() != wanted:
                    raise RuntimeError('BOOT_PIN')
        if 'LogicRF H102' not in Path('/proc/device-tree/model').read_bytes().decode():
            raise RuntimeError('BOARD_MODEL')

    def read(self, path: Path) -> str:
        """Read attributes discovered from fixed device and attribute names."""
        return path.read_text().strip()

    @contextmanager
    def defer_write_audit(self, records, limit=5):
        """Temporarily log nonauthorizing writes/readbacks in caller-owned RAM without delaying I/O.

        This single-threaded scope cannot nest; reject overflow before writing and restore logging on exit.
        Callers persist records after sources stop; lost RAM after process death is not proof of no writes.
        """
        if type(records) is not list or records or type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('WRITE_AUDIT_BUFFER')
        if getattr(self, '_deferred_audit', None) is not None:
            raise RuntimeError('WRITE_AUDIT_NESTED')
        self._deferred_audit = (records, limit)
        try:
            yield
        finally:
            self._deferred_audit = None

    def record_write(self, record):
        """Persist each record by default; explicit short scopes retain original timestamps in RAM."""
        deferred = getattr(self, '_deferred_audit', None)
        if deferred is not None:
            records, limit = deferred
            if len(records) >= limit:raise RuntimeError('WRITE_AUDIT_LIMIT')
            records.append(record)
            return
        with (self.directory / 'writes.jsonl').open('a') as log:
            log.write(json.dumps(record) + '\n')
            log.flush(); os.fsync(log.fileno())

    def write(self, path: Path, value: str, tolerance: float | None = None) -> str:
        """Write and read back; use hardware numeric tolerances but exact enum/enable matching."""
        deferred = getattr(self, '_deferred_audit', None)
        if deferred is not None and len(deferred[0]) >= deferred[1]:
            raise RuntimeError('WRITE_AUDIT_LIMIT')
        try:
            path.write_text(value + '\n')
        except Exception as error:
            self.record_write(dict(monotonic=time.monotonic(), path=str(path),
                requested=value, write_error=repr(error), readback_ok=False))
            raise
        actual = self.read(path)
        if tolerance is None:
            good = actual == value
        else:
            good = abs(float(actual.split()[0]) - float(value)) <= tolerance
        self.record_write(dict(monotonic=time.monotonic(), path=str(path),
            requested=value, actual=actual, readback_ok=good))
        if not good:
            raise RuntimeError('ATTRIBUTE_READBACK: ' + str(path))
        return actual

    def idle(self, phy_available: bool = True) -> None:
        """Require RF/DMA/USB idle; PHY-unavailable recovery checks independent data controls only.

        Normally check all sources. phy_available=False is restricted to trusted rollback reload;
        callers disable DDS, record unknown PHY state and repeat full checks after reinitialization.
        """
        self._idle_sources(phy_available, calibrated_tx=False)

    def calibration_idle(self) -> None:
        """Allow powered CALIBRATED TX only for bounded shared-LO tuning, with DDS/DMA/USB off.

        This is neither powered-off TX nor RF/data permission. Callers hold three locks,
        power down both TX channels on transaction exit and then use the normal idle check.
        """
        self._idle_sources(phy_available=True, calibrated_tx=True)

    def _idle_sources(self, phy_available: bool, calibrated_tx: bool) -> None:
        """Share complete DMA/USB checks; check calibration state separately from normal power-off."""
        if calibrated_tx:
            for i in (0,1):
                power=self.read(self.phy/f'out_voltage{i}_en')
                if power not in ('0','1') or (power=='1' and self.read(self.phy/f'out_voltage{i}_ensm_mode')!='calibrated'):
                    raise RuntimeError('CALIBRATED_TX_REQUIRED')
            paths=[self.alt(n,i,'raw') for n in DDS_NAMES for i in range(4)]
        else:
            paths = [self.phy / f'out_voltage{i}_en' for i in (0, 1)] if phy_available else []
        paths += [self.devices[n] / 'buffer/enable' for n in DMA_NAMES]
        if any(self.read(p) != '0' for p in paths):
            raise RuntimeError('RF_OR_DMA_BUSY')
        if self.fixture:
            return
        base = 0x43c50000
        resource = Path('/sys/bus/platform/devices/43c50000.axi_reg/of_node/reg')
        if resource.read_bytes() != struct.pack('>II', base, 0x10000):
            raise RuntimeError('MMIO_RESOURCE')
        with open('/dev/mem', 'rb', buffering=0) as descriptor:
            with mmap.mmap(descriptor.fileno(), 0x10000, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ, offset=base) as memory:
                values = {x: struct.unpack_from('<I', memory, x)[0] for x in
                    (0, 0x208, 0x218, 0x400, 0x200, 0x20c, 0x30c, 0x404, 0x40c, 0x604, 0x60c, 0x620)}
        for offset, wanted in ((0, 0x23070101), (0x208, 0x42535548),
                               (0x218, 0x33474244), (0x400, 0x33565852)):
            if values[offset] != wanted:
                raise RuntimeError('MMIO_ABI')
        if any(values[x] for x in (0x200, 0x20c, 0x404, 0x40c, 0x604, 0x60c, 0x620)) or values[0x30c] & 9:
            raise RuntimeError('CUSTOM_CAPTURE_BUSY')

    def stop(self) -> list[str]:
        """Attempt shutdown for every TX/DDS source even if another shutdown action fails."""
        errors = []
        paths = [self.phy / f'out_voltage{i}_en' for i in (0, 1)]
        paths += [self.alt(n, i, 'raw') for n in DDS_NAMES for i in range(4)]
        for path in paths:
            try:
                self.write(path, '0')
            except Exception as error:
                errors.append(str(error))
        return errors

    def settings(self) -> dict:
        """Save permitted non-enable settings; restoration always keeps enables off."""
        # Save first so reverse cleanup restores auto/off policy after LO restoration and calibration.
        paths = [self.phy / 'initial_calibrations']
        paths += [self.phy / f'in_voltage{i}_ensm_mode' for i in (0, 1)]
        for i in (0, 1):
            paths += [self.phy / f'in_voltage{i}_{a}' for a in ('gain_control_mode', 'hardwaregain')]
            paths += [self.phy / f'out_voltage{i}_{a}' for a in ('atten_control_mode', 'hardwaregain')]
        paths += [self.phy / f'in_voltage{i}_quadrature_fic_tracking_en' for i in (0,1)]
        paths += [self.alt(PHY_NAME, i, 'frequency') for i in range(4)]
        paths += [self.alt(n, i, a) for n in DDS_NAMES
                  for i in range(4) for a in ('frequency', 'phase', 'scale')]
        return {str(p): self.read(p) for p in paths}

    def configure(self) -> dict:
        """Configure fixed DDS/RX and bounded calibration with DDS off; verify actual 40M/20M."""
        if self.stop():
            raise RuntimeError('INITIAL_RF_STOP')
        for i in (0, 1):
            self.write(self.phy / f'in_voltage{i}_ensm_mode', 'rf_enabled')
            self.write(self.phy / f'in_voltage{i}_gain_control_mode', 'spi')
            self.write(self.phy / f'in_voltage{i}_hardwaregain', RX_GAIN_DB, 0.001)
            # With en=0 the channel is powered down and attenuation readback may remain stale.
            # SPI caches CALIBRATED; power-up restores CALIBRATED, then PRIMED, with RF still disabled.
            self.write(self.phy / f'out_voltage{i}_ensm_mode', 'calibrated')
            self.write(self.phy / f'out_voltage{i}_atten_control_mode', 'spi')
            self.write(self.phy / f'out_voltage{i}_en', '1')
            if self.read(self.phy / f'out_voltage{i}_ensm_mode') != 'calibrated':
                raise RuntimeError('TX_PREPARE_NOT_CALIBRATED')
            self.write(self.phy / f'out_voltage{i}_ensm_mode', 'primed')
            self.write(self.phy / f'out_voltage{i}_hardwaregain', TX_GAIN_DB, 0.001)
        for i in (0,1):
            if self.read(self.phy / f'in_voltage{i}_quadrature_fic_tracking_en') != '1':
                raise RuntimeError('MATCHED_FIC_INITIAL_NOT_ON')
        self.write(self.phy / 'initial_calibrations', 'auto')
        for i in range(4):
            self.write(self.alt(PHY_NAME, i, 'frequency'), '1000000000', 0)
        for i in (0, 1):
            # Calibration may alter state; verify actual RX state/gain and TX PRIMED explicitly.
            self.write(self.phy / f'in_voltage{i}_ensm_mode', 'rf_enabled')
            self.write(self.phy / f'in_voltage{i}_hardwaregain', RX_GAIN_DB, 0.001)
            self.write(self.phy / f'out_voltage{i}_ensm_mode', 'primed')
            self.write(self.phy / f'out_voltage{i}_hardwaregain', TX_GAIN_DB, 0.001)
        for channel, name in enumerate(DDS_NAMES):
            device = self.devices[name]
            freq = (1000000, 1500000)[channel]
            for i in range(4):
                self.write(self.alt(name, i, 'scale'), '0.25' if i in (0, 2) else '0', 0.00001)
                self.write(self.alt(name, i, 'frequency'), str(freq), 700)
                phase = (90000 if channel == 0 else 270000) if i == 0 else 0
                self.write(self.alt(name, i, 'phase'), str(phase), 0)
        config = {}
        for i in (0, 1):
            for direction in ('in', 'out'):
                for attr, wanted in (('sampling_frequency', '40000000'), ('rf_bandwidth', '20000000')):
                    p = self.phy / f'{direction}_voltage{i}_{attr}'
                    if self.read(p) != wanted:
                        raise RuntimeError('RATE_OR_BANDWIDTH')
                    config[p.name] = wanted
            for attr in ('hardwaregain', 'gain_control_mode', 'en', 'ensm_mode'):
                p = self.phy / f'in_voltage{i}_{attr}'; config[p.name] = self.read(p)
        config.update(self.settings())
        return config


    def activate(self, channels: tuple) -> dict:
        """Enable RF with DDS off, reapply active -20 dB attenuation, then enable DDS."""
        if any(self.read(self.alt(n,i,'raw'))!='0' for n in DDS_NAMES for i in range(4)):
            raise RuntimeError('ACTIVE_GAIN_DDS_BUSY')
        for channel in channels:
            self.write(self.phy / f'out_voltage{channel}_ensm_mode','rf_enabled')
            self.write(self.phy / f'out_voltage{channel}_hardwaregain','-20',.001)
        for channel in channels:
            for i in range(4):self.write(self.alt(DDS_NAMES[channel],i,'raw'),'1')
        return self.settings()


def cleanup(hw: Hardware, state: dict) -> dict:
    """Disable DDS, restore attenuation only if RF is already active, then stop RF and restore settings."""
    hw.verify(complete=False)
    pre_errors=[]
    # After interrupted active attenuation, never re-enable RF merely to restore attenuation.
    for name in DDS_NAMES:
        for i in range(4):
            try:hw.write(hw.alt(name,i,'raw'),'0')
            except Exception as error:pre_errors.append(str(error))
    for i in (0,1):
        try:
            path=hw.phy / f'out_voltage{i}_hardwaregain'
            if hw.read(hw.phy / f'out_voltage{i}_ensm_mode')=='rf_enabled' and hw.read(hw.phy / f'out_voltage{i}_en')=='1':
                hw.write(path,state['original'][str(path)].split()[0],.001)
        except Exception as error:pre_errors.append(str(error))
    errors = pre_errors + hw.stop()
    allowed = set(state['original'])
    allowed_roots = {hw.phy} | {hw.devices[n] for n in DDS_NAMES}
    lo_paths = {hw.alt(PHY_NAME, i, 'frequency') for i in range(4)}
    lo_ready = True
    if hw.read(hw.phy / 'initial_calibrations') == 'auto' and any(
            hw.read(p) != state['original'].get(str(p)) for p in lo_paths):
        try:
            # Driver calibration covers all channels and initially returns EFAULT for powered-down TX.
            # Keep DDS off and power TX only to CALIBRATED for LO restoration calibration.
            for i in (0, 1):
                hw.write(hw.phy / f'out_voltage{i}_ensm_mode', 'calibrated')
                hw.write(hw.phy / f'out_voltage{i}_atten_control_mode', 'spi')
                hw.write(hw.phy / f'out_voltage{i}_en', '1')
                if hw.read(hw.phy / f'out_voltage{i}_ensm_mode') != 'calibrated':
                    raise RuntimeError('RESTORE_TX_NOT_CALIBRATED')
        except Exception as error:
            errors.append(str(error)); lo_ready = False
    for path, value in reversed(list(state['original'].items())):
        try:
            candidate = Path(path)
            if path not in allowed or candidate.parent not in allowed_roots or candidate.is_symlink():
                raise RuntimeError('RESTORE_PATH')
            if candidate in lo_paths and not lo_ready:
                raise RuntimeError('RESTORE_LO_PREPARATION_FAILED')
            if candidate.name.endswith('_quadrature_fic_tracking_en') and hw.read(candidate) == value:
                continue
            # Gain readback may include dB units; write its numeric value and preserve enum matching.
            if candidate.name in ('in_voltage0_hardwaregain', 'in_voltage1_hardwaregain'):
                # The API writes manual gain index but reads active gain index, unchanged in CALIBRATED.
                channel = candidate.name[len('in_voltage')]
                hw.write(hw.phy / f'in_voltage{channel}_ensm_mode', 'rf_enabled')
                hw.write(hw.phy / f'in_voltage{channel}_gain_control_mode', 'spi')
            write_value = value.split()[0] if path.endswith('_hardwaregain') else value
            tolerance = 0.001 if path.endswith(('_hardwaregain', '_scale')) else None
            if candidate.name in ('out_voltage0_hardwaregain', 'out_voltage1_hardwaregain'):
                # Do not repeat a powered register write when powered-down TX attenuation already matches.
                if abs(float(hw.read(candidate).split()[0]) - float(write_value)) <= 0.001:
                    continue
            hw.write(Path(path), write_value, tolerance)
        except Exception as error:
            errors.append(str(error))
    errors.extend(hw.stop())
    try:
        hw.idle()
    except Exception as error:
        errors.append(str(error))
    result = dict(cleanup_passed=not errors, errors=errors, RF_DDS_disabled=not errors,
                  fixture_only=bool(hw.fixture), monotonic=time.monotonic())
    with (hw.directory / 'cleanup-history.jsonl').open('a') as log:
        log.write(json.dumps(result) + '\n'); log.flush(); os.fsync(log.fileno())
    save(hw.directory / 'cleanup.json', result)
    return result


def serve(hw: Hardware, state: dict, stage: str = 'R1') -> None:
    """Read ordered FIFO commands; stop after three seconds without heartbeat or RF deadline."""
    fifo = hw.directory / 'control.fifo'; os.mkfifo(fifo, 0o600)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    lease = Lease(time.monotonic(), stage)
    pending = b''

    save(hw.directory / 'ready.json', dict(ready=True, fixture_only=bool(hw.fixture),
         configuration=state['configuration']), exclusive=True)
    try:
        while not lease.expired(time.monotonic()):
            readable, _, _ = select.select([fd], [], [], 0.01)
            if not readable:
                continue
            pending += os.read(fd, 4096)
            if len(pending) > 8192:
                raise ValueError('COMMAND_SIZE')
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                command = json.loads(line)
                now = time.monotonic()
                # select/read may cross the deadline; use finally cleanup rather than consuming a late renewal.
                if lease.expired(now):
                    return
                op = lease.command(command, now)
                if op == 'stop':
                    return
                if op == 'arm':
                    channels = (0, 1) if command['channel'] == 3 else (command['channel'] - 1,)
                    actual = hw.activate(channels)
                    save(hw.directory / 'armed.json', dict(channel=command['channel'], stage=stage,
                        channels=[x + 1 for x in channels], actual=actual, active_TX_gain='-20', DDS_scale='0.25',
                        deadline=lease.rf_deadline, at=time.monotonic(), fixture_only=bool(hw.fixture)), exclusive=True)
                    if lease.expired(time.monotonic()):
                        raise TimeoutError('ARM_WRITE_OVERRAN_WINDOW')
    finally:
        os.close(fd)


def main() -> None:
    """Use a fixed session directory and identity; hold board locks through main and reacquire for post."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'profile', 'cleanup'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--stage', choices=tuple(STAGES), default='R1')
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.parent != Path('/run') or not directory.name.startswith('h102-rf-'):
        raise ValueError('SESSION_DIRECTORY')
    if args.fixture and args.fixture.resolve() != directory / 'fixture':
        raise ValueError('FIXTURE_PATH')
    expected = json.loads((directory / 'identity.json').read_text())
    for filename in ('identity.json',):
        info = (directory / filename).stat()
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise ValueError('PRIVATE_ROOT_INPUT')
    with ExitStack() as stack:
        for name in ('h102-rx-session.lock', 'h102-gnss-g0.lock'):
            lock = stack.enter_context(open('/run/lock/' + name, 'a+b'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hw = Hardware(directory, expected, args.fixture)
        state_path = directory / 'state.json'
        if args.action == 'cleanup':
            if state_path.exists():
                if not cleanup(hw, json.loads(state_path.read_text()))['cleanup_passed']:
                    raise RuntimeError('POST_CLEANUP_FAILED')
            return
        hw.idle()
        state = dict(original=hw.settings(), action=args.action, stage=args.stage,
                     fixture_only=bool(args.fixture))
        save(state_path, state, exclusive=True)
        def interrupted(signum, frame):
            """Convert ordinary signals into finally cleanup; independent post handles SIGKILL."""
            raise TimeoutError('SIGNAL_' + str(signum))
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, interrupted)
        try:
            if args.action == 'profile':
                payload = (directory / 'profile.json').read_bytes()
                if hashlib.sha256(payload).hexdigest() != PROFILE_SHA:
                    raise RuntimeError('PROFILE_PIN')
                if hw.stop():
                    raise RuntimeError('PROFILE_INITIAL_STOP')
                for name in DDS_NAMES:
                    for i in range(4):
                        hw.write(hw.alt(name, i, 'scale'), '0', 0)
                # FDD initialization can enable RF; this configuration step is not an RF-off digital test.
                with (hw.phy / 'profile_config').open('wb', buffering=0) as target:
                    position = 0
                    while position < len(payload):
                        size = target.write(payload[position:position + 4096])
                        if not size:
                            raise RuntimeError('PROFILE_SHORT_WRITE')
                        position += size
                if hw.stop():
                    raise RuntimeError('PROFILE_FINAL_STOP')
                save(directory / 'profile-applied.json', dict(sha256=PROFILE_SHA,
                     summary=hw.read(hw.phy / 'profile_config'), register_port_readback=False,
                     fixture_only=bool(args.fixture)), exclusive=True)
            else:
                state['configuration'] = hw.configure(); save(state_path, state)
                serve(hw, state, args.stage)
        finally:
            if not cleanup(hw, state)['cleanup_passed']:
                raise RuntimeError('CLEANUP_FAILED')


if __name__ == '__main__':
    main()

# End of file: h102_rf_owner.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
