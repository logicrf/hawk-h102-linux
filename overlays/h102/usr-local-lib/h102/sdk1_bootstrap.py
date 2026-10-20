#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       sdk1_bootstrap.py
@brief      Disable sources and initialize the managed default configuration at SDK1 boot.
@details    Verify identity and all pinned product files before loading local code.
            Configuration, RX and GNSS locks protect initial shutdown; release RX/GNSS before
            the bounded configuration transaction. On failure, do not start the broker or retry.
            Validate actual RF shutdown and default boot against the exact assembled image separately.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-11
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

SCRIPTS = Path('/usr/local/lib/h102/sdk1/scripts')
METADATA = Path('/etc/h102/sdk1-image.json')
DEFAULT_PROFILE = '40msps-20mhz'
"""Match the kernel's compiled first-boot profile; repeated calls do not force this preset."""


def private(path: Path, directory: bool = False) -> None:
    """Require root-trusted regular assets and ancestors before any device access."""
    for item in (path,) + tuple(path.parents):
        info = item.lstat()
        kind = stat.S_ISDIR if item != path or directory else stat.S_ISREG
        if info.st_uid != 0 or info.st_mode & 0o022 or not kind(info.st_mode):
            raise ValueError('UNTRUSTED_BOOTSTRAP_ASSET: ' + str(item))


def verify_assets(metadata: dict) -> None:
    """Verify metadata and installed files; file hashes do not identify loaded FPGA memory."""
    if metadata['schema'] != 1 or metadata['kernel'] != os.uname().release:
        raise ValueError('BOOTSTRAP_KERNEL_OR_SCHEMA')
    for name, entry in metadata['assets'].items():
        path = Path(name)
        if not path.is_absolute() or '..' in path.parts or str(path) != name:
            raise ValueError('BOOTSTRAP_ASSET_PATH')
        private(path)
        raw = path.read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('BOOTSTRAP_ASSET_DIGEST: ' + name)
    for name in ('h102_axi_reg', 'h102_axi_trig', 'h102_profile_control'):
        if not (Path('/sys/module') / name).is_dir():
            raise ValueError('BOOTSTRAP_MODULE_NOT_LOADED: ' + name)


def stop_sources(config, hw) -> None:
    """Disable all DMA/TX/DDS sources, attempting every source and rejecting any error.

    The caller owns the three locks and matching identity. Write only disable/zero values;
    do not enable USB, RF or DMA or change user LO, gain or sample rate.
    """
    errors = []
    for name in config.rf.DMA_NAMES:
        try:
            hw.write(hw.devices[name] / 'buffer/enable', '0')
        except Exception as exc:
            errors.append(str(exc))
    try:
        config.quiet(hw)
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        raise RuntimeError('BOOTSTRAP_SOURCE_STOP_FAILED: ' + repr(errors))
    hw.idle()


def ensure_time_epoch(config, path=Path('/var/lib/h102-rx/time-epoch.json')) -> dict:
    """Create persistent timestamp epochs under the first-boot locks; verify existing state.

    A missing file means unallocated epoch zero; later sessions advance hardware/config epochs.
    Require root-trusted objects and reject invalid JSON, integers and symlinks.
    Exclusive link and fsync in atomic_save preserve concurrent originals.
    """
    private(path.parent.parent, directory=True)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    private(path.parent, directory=True)
    created = False
    try:
        path.lstat()
    except FileNotFoundError:
        config.atomic_save(path, {'last_epoch': 0}, exclusive=True)
        created = True
    private(path)
    value = json.loads(path.read_bytes())
    if (not isinstance(value, dict) or set(value) != {'last_epoch'} or
            type(value['last_epoch']) is not int or
            not 0 <= value['last_epoch'] <= 0xffffffff):
        raise ValueError('BOOTSTRAP_INVALID_PERSISTENT_TIME_EPOCH')
    return dict(path=str(path), created=created, last_epoch=value['last_epoch'])


def initialize(config, lock_factory, directory: Path) -> dict:
    """Hold one configuration lock throughout initialization; query an already-managed boot.

    For first boot require the real default 40/20 profile and explicit previous state;
    release RX/GNSS before the transaction and reject missing inputs or incomplete recovery.
    """
    with lock_factory():
        if config.STATE.exists():
            current = config.status(config.CATALOG)
            if current['managed'] is None:
                raise ValueError('BOOTSTRAP_EXISTING_STATE_NOT_MANAGED')
            return dict(status='PASS_BOOTSTRAP_EXISTING_MANAGED_READONLY', current=current)
        package = config.load_package(config.CATALOG, DEFAULT_PROFILE, trusted=True)
        identity = config.identity()
        with ExitStack() as scope:
            hw = config.hardware_context(scope, directory, identity)
            config.verify_snapshot(config.snapshot(hw), package)
            stop_sources(config, hw)
            time_epoch = ensure_time_epoch(config)
        # apply_locked acquires RX/GNSS itself; release the outer two locks first.
        applied = config.apply_locked(config.CATALOG, DEFAULT_PROFILE,
                                      previous_id=DEFAULT_PROFILE)
        current = config.status(config.CATALOG)
        managed = current['managed']
        if not managed or managed['profile_id'] != DEFAULT_PROFILE or (
                managed['configuration_id'] != applied['configuration_id']):
            raise RuntimeError('BOOTSTRAP_FINAL_MANAGED_READBACK')
        with ExitStack() as scope:
            hw = config.hardware_context(scope, directory, identity)
            hw.idle()
            # Full source readback includes DDS raw, which Hardware.idle does not inspect.
            paths = [hw.devices[n] / 'buffer/enable' for n in config.rf.DMA_NAMES]
            paths += [hw.phy / ('out_voltage%d_en' % i) for i in (0, 1)]
            paths += [hw.alt(n, i, 'raw') for n in config.rf.DDS_NAMES for i in range(4)]
            if any(hw.read(p) != '0' for p in paths):
                raise RuntimeError('BOOTSTRAP_FINAL_SOURCE_NOT_ZERO')
        return dict(status='PASS_BOOTSTRAP_INITIALIZED_MAIN_POST_READBACK',
                    identity=identity, applied=applied, current=current,
                    time_epoch=time_epoch, RF_TX=False)


def main() -> None:
    """Verify root, metadata and sources before importing board-control modules."""
    if os.geteuid() != 0:
        raise PermissionError('ROOT_REQUIRED')
    private(Path(__file__).absolute())
    private(METADATA)
    metadata = json.loads(METADATA.read_bytes())
    verify_assets(metadata)
    private(SCRIPTS, directory=True)
    sys.path.insert(0, str(SCRIPTS))
    import h102_profile_config as config
    from h102_iio_owner_lock import configuration_lock
    config.configure_stack('sdk1-candidate')
    if config.BOOT_PINS != metadata['boot_pins']:
        raise ValueError('BOOTSTRAP_COMPILED_BOOT_PINS_MISMATCH')
    directory = Path('/run') / ('h102-sdk1-bootstrap-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    try:
        result = initialize(config, configuration_lock, directory)
    except BaseException as exc:
        config.atomic_save(directory / 'failure.json', dict(status='FAIL_BOOTSTRAP',
                           error=repr(exc), hardware_cleanup_not_assumed=True), exclusive=True)
        raise
    config.atomic_save(directory / 'result.json', result, exclusive=True)
    print(json.dumps(dict(status=result['status'], evidence=str(directory))))


if __name__ == '__main__':
    main()

# End of file: sdk1_bootstrap.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
