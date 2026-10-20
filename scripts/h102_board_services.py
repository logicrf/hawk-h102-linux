#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_board_services.py
@brief      Verify and stage the fixed H102 device-service delivery without installing it.
@details    Pin the original firmware archives and inner manifests. Reject unsafe members,
            links and existing outputs; read back every staged file. This tool never runs
            device code, SSH, systemctl, reboot, RF operations or SD-card writes.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-20
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import tarfile

VERSION = '1.0.0-en-r1'
BASE_IMAGE_SHA256 = '5a09380de3cea3219cc2ffb2cff2a2281e03b5e1c2fee2070c4e77aa9cd170a7'
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
"""Bound memory and staging to this small, fixed service package, never a full SD image."""
PINS = {
    'hotmeta': {
        'filename': 'h102-grc-hotmeta-addon-1-r5-20261018.tar.xz',
        'sha256': 'b83bcff35b6a6a4fa1bb34a1713caae75f0f881f922e2dd7f27de667d5090bc8',
        'bytes': 1642660,
        'root': 'h102-grc-hotmeta-addon-1-r5-20261018',
        'manifest': 'package.json',
        'manifest_sha256': '03eada3019d48414fb15dd4f4ca1030a88fc2fcd7122d3fa094c49280e60c5cf',
    },
    'network': {
        'filename': 'h102-network-performance-1.0.0.tar.gz',
        'sha256': 'b934fca7de24647e9a7bf301ea50d2a6c1805097ebd98deba48db1a503233a47',
        'bytes': 7764,
        'root': 'h102-network-performance-1.0.0',
        'manifest': 'manifest.json',
        'manifest_sha256': '5e8c1616f786e606fd9fadf265f4e1b03fca66152117a6d8b7d33d45bd829aac',
    },
}
"""Approved immutable archives; editing a sidecar cannot authorize another payload."""


def digest(data: bytes) -> str:
    """Return SHA-256 of complete bytes already read within the package size bound."""
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, limit=MAX_ARCHIVE) -> bytes:
    """Read a bounded regular file without following its final symlink.

    Reject source replacement during reading. Parent directories are checked by
    verify_bundle; payload hashes independently identify the accepted bytes.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('BOUNDED_REGULAR_FILE_REQUIRED: ' + str(path))
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                                  value.st_ctime_ns)
        if identity(before) != identity(after) or len(data) != before.st_size:
            raise ValueError('SOURCE_CHANGED_DURING_READ: ' + str(path))
    return data


def plain_path(path: Path) -> Path:
    """Preserve the supplied path while rejecting traversal and existing symlink ancestors."""
    path = path.absolute()
    if '..' in path.parts or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('PLAIN_PATH_REQUIRED: ' + str(path))
    return path


def archive_files(data: bytes, root: str) -> dict[str, bytes]:
    """Read bounded regular members from one exact root without filesystem extraction.

    Validate all headers before reading data. Reject aliases, duplicates, links,
    special nodes and a file used as a parent directory.
    """
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        members = archive.getmembers()
        if len(members) > 256 or sum(member.size for member in members) > MAX_EXPANDED:
            raise ValueError('ARCHIVE_LIMIT')
        seen = set()
        regular = {}
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != root
                    or str(path) != member.name.rstrip('/') or '\\' in member.name
                    or not (member.isdir() or member.isfile()) or str(path) in seen
                    or member.size < 0):
                raise ValueError('UNSAFE_ARCHIVE_MEMBER: ' + member.name)
            seen.add(str(path))
            if member.isfile():
                if len(path.parts) < 2:
                    raise ValueError('ARCHIVE_ROOT_MUST_BE_DIRECTORY')
                regular[str(path.relative_to(root))] = member
        for name in regular:
            if any(str(parent) in regular for parent in PurePosixPath(name).parents):
                raise ValueError('ARCHIVE_FILE_PARENT')
        result = {}
        for name, member in regular.items():
            with archive.extractfile(member) as stream:
                raw = stream.read(MAX_EXPANDED + 1)
            if len(raw) != member.size:
                raise ValueError('ARCHIVE_MEMBER_SIZE: ' + name)
            result[name] = raw
    return result


def verify_bundle(bundle: Path) -> tuple[dict, dict]:
    """Verify exact outer archives and every inner file; perform no device operation.

    Return the approved sidecar and bounded in-memory trees used by stage(), so
    source archives are never reopened between verification and staging.
    """
    bundle = plain_path(Path(bundle))
    manifest = json.loads(read_regular(bundle / 'BOARD-SERVICES.json', 256 * 1024))
    if (manifest.get('schema') != 1 or manifest.get('version') != VERSION
            or manifest.get('base_image_sha256') != BASE_IMAGE_SHA256
            or manifest.get('components') != PINS):
        raise ValueError('UNAPPROVED_SERVICE_DELIVERY')
    payloads = {}
    for component, entry in PINS.items():
        data = read_regular(bundle / entry['filename'])
        if len(data) != entry['bytes'] or digest(data) != entry['sha256']:
            raise ValueError('ARCHIVE_SHA_MISMATCH: ' + component)
        files = archive_files(data, entry['root'])
        inner_name = entry['manifest']
        if digest(files[inner_name]) != entry['manifest_sha256']:
            raise ValueError('INNER_MANIFEST_SHA: ' + component)
        inner = json.loads(files[inner_name])
        extra = {'install_network_performance.py'} if component == 'network' else set()
        if set(files) != set(inner['files']) | {inner_name} | extra:
            raise ValueError('INNER_MEMBER_SET: ' + component)
        for name, expected in inner['files'].items():
            if digest(files[name]) != expected:
                raise ValueError('INNER_FILE_SHA: ' + name)
        payloads[component] = files
    return manifest, payloads


def commands(output: Path) -> dict:
    """Describe fixed administrator commands in order; never execute or infer a reboot."""
    hotmeta = output / PINS['hotmeta']['root']
    network = output / PINS['network']['root']
    command = lambda *parts: shlex.join(str(part) for part in parts)
    return {
        'first_on_idle_device': command('sudo', 'python3', '-B', hotmeta / 'install_hotmeta_addon.py',
                                        '--package-sha256', PINS['hotmeta']['manifest_sha256']),
        'then': 'Perform a normal device reboot; wait for the matching control service to become ready.',
        'after_reboot': command('sudo', 'python3', '-B', network / 'install_network_performance.py', 'install'),
        'check': 'systemctl is-active h102-control-api.service h102-network-performance.service',
        'optional_boot_profile': 'Append --prepare-grc-profile only to the network install command '
                                'to select 4 MSPS / 2 MHz shared LO at boot. Omit to preserve the base default.',
    }


def stage(bundle: Path, output: Path) -> dict:
    """Create a new private staging directory and read back all files before success.

    Failure preserves its incomplete directory for inspection. A successful
    receipt means files were staged only, never installed or hardware-qualified.
    """
    _, payloads = verify_bundle(bundle)
    output = plain_path(Path(output))
    output.mkdir(mode=0o700, exist_ok=False)
    hashes = {}
    for component, files in payloads.items():
        for name, raw in files.items():
            relative = PINS[component]['root'] + '/' + name
            target = output / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if read_regular(target, MAX_EXPANDED) != raw:
                raise ValueError('STAGED_FILE_READBACK: ' + relative)
            hashes[relative] = digest(raw)
    result = {'status': 'PASS_STAGED_NOT_INSTALLED', 'version': VERSION, 'files': hashes,
              'administrator_commands': commands(output), 'hardware': 'NOT_RUN'}
    (output / 'STAGED.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'STAGED.json').chmod(0o600)
    return result


def main() -> int:
    """Verify or stage Linux service files; fail nonzero and report no installation success."""
    parser = argparse.ArgumentParser(description='Verify or stage approved H102 service files; never install them.')
    parser.add_argument('action', choices=('verify', 'stage'))
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='New directory; required for stage only')
    args = parser.parse_args()
    if (args.action == 'stage') != (args.output is not None):
        parser.error('--output is required only for stage')
    try:
        if args.action == 'stage':
            result = stage(args.bundle, args.output)
        else:
            _, trees = verify_bundle(args.bundle)
            result = {'status': 'PASS_VERIFIED_NOT_INSTALLED', 'version': VERSION,
                      'files': {key: len(value) for key, value in trees.items()}, 'hardware': 'NOT_RUN'}
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

# End of file: h102_board_services.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
