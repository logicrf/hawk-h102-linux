#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_profile_iio_broker.py
@brief      Delegate asynchronous IIO preset requests to the verified SDK1 manager.
@details    A root-owned character device serves one worker while the main thread sends
            heartbeats. Publish active only after actual queries and managed records agree.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-15
@note Configuration uses the existing hardware scope; the service does not start data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import struct
import threading
import time
import uuid

import h102_profile_config as config
from h102_iio_owner_lock import configuration_lock
from h102_rf_usb_tx_storage import atomic_save

# Match the kernel's little-endian ABI: request/status sizes are 80/4504 bytes.
REQUEST = struct.Struct('<IIQ64s')
UPDATE = struct.Struct('<IIQII64s64s256s2048s2048s')
UNAVAILABLE, READY, APPLYING, APPLIED, ROLLED_BACK, REJECTED = range(6)
ID_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
HEARTBEAT_SECONDS = 5
VERIFY_SECONDS = 10


def text_field(value: str, size: int) -> bytes:
    """Encode strictly NUL-terminated fields without silently truncating IDs or metadata."""
    encoded = value.encode('utf-8')
    if b'\0' in encoded or len(encoded) >= size:
        raise ValueError('ABI_STRING_LENGTH_OR_NUL')
    return encoded + b'\0' * (size - len(encoded))


def decode_request(payload: bytes) -> tuple[int, str]:
    """Check request version, reserved fields and ID before calling the hardware manager."""
    version, reserved, ticket, field = REQUEST.unpack(payload)
    if version != 1 or reserved or not ticket or b'\0' not in field:
        raise ValueError('INVALID_REQUEST_ABI')
    name = field.split(b'\0', 1)[0].decode('ascii')
    if not ID_PATTERN.fullmatch(name):
        raise ValueError('INVALID_REQUEST_ID')
    return ticket, name


def encode_update(ticket: int, phase: int, snapshot: dict | None,
                  available: str, error: str = '') -> bytes:
    """Encode verified or explicitly unknown state with a bounded error summary."""
    value = snapshot or {}
    return UPDATE.pack(1, phase, ticket, value.get('configuration_id', 0), 0,
        text_field(value.get('active', ''), 64), text_field(value.get('previous', ''), 64),
        text_field(error.replace('\0', '?').encode('utf-8')[:240].decode('utf-8', 'ignore'), 256),
        text_field(json.dumps(value.get('info', {}), separators=(',', ':')) if value else '', 2048),
        text_field(available, 2048))


def verified_snapshot(catalog: Path, packages: dict) -> dict:
    """Independently verify four channels, boot and source hashes; never adopt unknown profiles."""
    # Hold configuration before status acquires RX/GNSS, preventing partial lock-group contention.
    with configuration_lock():
        status = config.status(catalog)
    managed = status['managed']
    if not managed or managed['profile_id'] not in packages:
        raise ValueError('ACTIVE_MANAGED_PACKAGE_UNKNOWN')
    package = packages[managed['profile_id']]
    if managed['sha256'] != package['manifest']['sha256']:
        raise ValueError('ACTIVE_PACKAGE_DIGEST_MISMATCH')
    info = dict(schema=1, active=managed['profile_id'],
        configuration_id=managed['configuration_id'], boot_id=status['identity']['boot_id'],
        parameters=status['actual']['parameters'], clock=package['manifest']['clock'],
        ssi='LVDS-2lane-DDR-16bit', api=config.API, sha256=managed['sha256'],
        provenance=status['blob_provenance'], verified_monotonic_ns=time.monotonic_ns(),
        qualification='configuration_only; data/rf/gnss_not_qualified')
    previous = managed.get('previous_id') or ''
    if previous and previous not in packages:
        # Preserve historical managed state; ABI previous may name only a currently selectable preset.
        # An obsolete previous ID must not invalidate the current valid profile page.
        info['previous_unavailable_in_catalog'] = previous
        previous = ''
    return dict(active=managed['profile_id'], previous=previous,
        configuration_id=managed['configuration_id'], info=info)


def execute(catalog: Path, packages: dict, ticket: int, name: str,
            logdir: Path, instance: str) -> tuple[int, dict | None, str]:
    """Execute one worker and query independently; claim rollback only with an explicit post record."""
    record = dict(ticket=ticket, target=name, started_monotonic_ns=time.monotonic_ns())
    phase, error = APPLIED, ''
    try:
        record['result'] = config.apply(catalog, name)
    except Exception as exc:
        record['exception'] = str(exc)
        phase, error = REJECTED, 'MANAGER_REJECTED: ' + str(exc)
        try:
            result = json.loads(str(exc))
            record['result'] = result
            if result.get('transaction_status') == 'rolled_back':
                phase, error = ROLLED_BACK, 'TARGET_FAILED_RECOVERY_CONFIRMED'
        except (ValueError, AttributeError):
            pass
    try:
        snapshot = verified_snapshot(catalog, packages)
        if phase == APPLIED and snapshot['active'] != name:
            raise ValueError('APPLIED_TARGET_READBACK_MISMATCH')
        result = record.get('result', {})
        if phase in (APPLIED, ROLLED_BACK) and (
                result.get('profile_id') != snapshot['active'] or
                result.get('configuration_id') != snapshot['configuration_id'] or
                result.get('sha256') != snapshot['info']['sha256']):
            raise ValueError('TRANSACTION_RESULT_READBACK_MISMATCH')
    except Exception as exc:
        snapshot = None
        phase, error = UNAVAILABLE, 'FINAL_VERIFY_FAILED: ' + str(exc)
    record.update(phase=phase, error=error, snapshot=snapshot,
        completed_monotonic_ns=time.monotonic_ns())
    atomic_save(logdir / f'{instance}-{ticket}.json', record, exclusive=True)
    return phase, snapshot, error


def run(catalog: Path, approved: Path, node: Path, logdir: Path) -> None:
    """Maintain heartbeats while busy; service restart queries without changing configuration."""
    if os.geteuid() != 0:
        raise PermissionError('ROOT_REQUIRED')
    for path in (Path(__file__), approved):
        config.private(path)
    for name in ('h102_profile_config.py', 'h102_rf_owner.py', 'h102_rf_usb_tx_storage.py', 'h102_iio_owner_lock.py'):
        config.private(Path(__file__).parent / name)
    config.private(catalog, directory=True)
    ids = [p['id'] for p in config.read_json(approved)['profiles']]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError('INVALID_APPROVED_CATALOG')
    packages = {name: config.load_package(catalog, name, trusted=True) for name in ids}
    if any(not p['manifest']['qualification']['configuration_load'].startswith('passed_h102_sdk1_')
           for p in packages.values()):
        raise ValueError('CONFIGURATION_QUALIFICATION_REQUIRED')
    available = ' '.join(ids)
    text_field(available, 2048)
    logdir.mkdir(mode=0o700, parents=False, exist_ok=True)
    config.private(logdir, directory=True)
    info = node.lstat()
    if not stat.S_ISCHR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('UNTRUSTED_BACKEND_DEVICE')
    matches = [p for p in Path('/sys/bus/iio/devices').glob('iio:device*')
               if (p / 'name').read_text().strip() == 'h102-profile-control']
    if len(matches) != 1:
        raise ValueError('UNIQUE_CONTROL_DEVICE_REQUIRED')
    ticket = int((matches[0] / 'request_id').read_text())
    startup_error = 'BACKEND_RECONNECTED_REQUEST_OUTCOME_UNKNOWN' if ticket else ''
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    instance = uuid.uuid4().hex
    phase, snapshot, error = UNAVAILABLE, None, 'INITIAL_VERIFY_PENDING'
    future = None
    next_verify = next_heartbeat = 0.0
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            poll = select.poll()
            poll.register(fd, select.POLLIN)
            while not stop.is_set() or future is not None:
                now = time.monotonic()
                if future is not None and future.done():
                    phase, snapshot, error = future.result()
                    future = None
                    next_heartbeat = 0
                    next_verify = now + VERIFY_SECONDS
                if future is None and now >= next_verify:
                    try:
                        snapshot = verified_snapshot(catalog, packages)
                        if phase in (UNAVAILABLE, APPLYING):
                            phase, error = READY, startup_error
                    except Exception as exc:
                        phase, snapshot, error = UNAVAILABLE, None, 'VERIFY_UNAVAILABLE: ' + str(exc)
                    next_verify = now + VERIFY_SECONDS
                if now >= next_heartbeat:
                    try:
                        os.write(fd, encode_update(ticket, phase, snapshot, available, error))
                    except OSError as exc:
                        if exc.errno != errno.ESTALE:
                            raise
                    next_heartbeat = now + HEARTBEAT_SECONDS
                if future is None and poll.poll(200):
                    ticket, name = decode_request(os.read(fd, REQUEST.size))
                    if name not in packages:
                        raise ValueError('UNAPPROVED_KERNEL_REQUEST')
                    phase, error = APPLYING, ''
                    os.write(fd, encode_update(ticket, phase, snapshot, available))
                    future = worker.submit(execute, catalog, packages, ticket, name, logdir, instance)
                    next_heartbeat = 0
                elif future is not None:
                    time.sleep(0.2)
    finally:
        os.close(fd)


def main() -> None:
    """Resolve deployment paths; systemd restarts uncaught failures and the kernel hides active state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--approved', type=Path, required=True)
    parser.add_argument('--device', type=Path, default=Path('/dev/h102-profile-control'))
    parser.add_argument('--log-directory', type=Path, required=True)
    args = parser.parse_args()
    config.configure_stack('sdk1-candidate')
    os.umask(0o077)
    run(args.catalog, args.approved, args.device, args.log_directory)


if __name__ == '__main__':
    main()
# End of file: h102_profile_iio_broker.py
