#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_rf_usb_tx_storage.py
@brief      Store TX session evidence on SD while reserving space for board recovery.
@details    Use fixed root-private paths, reject symlinks and check SD plus /run space/inodes.
            Use unique temporary JSON names so failed commits do not block later recovery.
            No RF, USB, MMIO or service access occurs here; legacy R4/digital entries do not use this adapter.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-01
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import stat
import uuid

SESSION_ROOT = Path('/var/lib/h102-rf-usb-tx-sessions')
"""Fixed root-private session root on SD; manifests cannot select arbitrary directories."""
START_BYTES, CLEANUP_BYTES, RUN_BYTES = 128 << 20, 16 << 20, 16 << 20
START_INODES, CLEANUP_INODES, RUN_INODES = 2048, 128, 128


def private_directory(path: Path) -> None:
    """Reject non-root ownership, nondirectories, symlinks and group/other directory access."""
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('PRIVATE_TX_STORAGE')


def capacity(path: Path, minimum_bytes: int, minimum_inodes: int) -> dict:
    """Reserve unprivileged available space for cleanup; reject insufficient capacity."""
    values = os.statvfs(path)
    result = dict(path=str(path), available_bytes=values.f_bavail * values.f_frsize,
                  available_inodes=values.f_favail, required_bytes=minimum_bytes,
                  required_inodes=minimum_inodes)
    if result['available_bytes'] < minimum_bytes or values.f_favail < minimum_inodes:
        raise RuntimeError('TX_EVIDENCE_CAPACITY: ' + json.dumps(result))
    return result


def create_session(session: str) -> Path:
    """Create each SD session once, checking both filesystems before RF configuration."""
    if not re.fullmatch(r'h102-rf-usb-tx-[a-z0-9-]+', session):
        raise ValueError('TX_SESSION_NAME')
    for parent in (Path('/var'), Path('/var/lib')):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('TX_STORAGE_PARENT')
    try:
        SESSION_ROOT.mkdir(mode=0o700)
    except FileExistsError:
        pass
    private_directory(SESSION_ROOT)
    if SESSION_ROOT.stat().st_dev == Path('/run').stat().st_dev:
        raise ValueError('TX_STORAGE_IS_RUN')
    if SESSION_ROOT.stat().st_dev != Path('/').stat().st_dev:
        raise ValueError('TX_STORAGE_IS_NOT_ROOT_FILESYSTEM')
    proof = dict(SD=capacity(SESSION_ROOT, START_BYTES, START_INODES),
                 runtime=capacity(Path('/run'), RUN_BYTES, RUN_INODES))
    directory = SESSION_ROOT / session
    directory.mkdir(mode=0o700)
    atomic_save(directory / 'storage-preflight.json', proof, exclusive=True)
    return directory


def validate_session(directory: Path) -> None:
    """Validate the original path before resolving, rejecting symlinks and alternate storage roots."""
    if directory.parent != SESSION_ROOT or not re.fullmatch(
            r'h102-rf-usb-tx-[a-z0-9-]+', directory.name):
        raise ValueError('TX_SESSION_DIRECTORY')
    private_directory(SESSION_ROOT)
    private_directory(directory)


def check_cleanup_reserve(directory: Path) -> dict:
    """Check recovery space before RF enable or finite IQ; never delete historical evidence."""
    return capacity(directory, CLEANUP_BYTES, CLEANUP_INODES)


def atomic_save(path: Path, value: dict, exclusive: bool = False) -> None:
    """Preserve failed temporary JSON and old state; use a new temporary name on recovery.

    The caller owns the session. Exclusive mode preserves originals; fsync contents before
    link/replace and parent fsync. Collectors can archive failed temporary files independently.
    """
    temporary = path.parent / ('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    # Create authorization/state files as 0600 immediately, regardless of the process umask.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    if exclusive:
        try:
            os.link(temporary, path)
        except FileExistsError:
            temporary.unlink()
            raise
        temporary.unlink()
    else:
        os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

# End of file: h102_rf_usb_tx_storage.py
