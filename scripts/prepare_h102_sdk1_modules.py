#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       prepare_h102_sdk1_modules.py
@brief      Merge pinned SDK1 kernel modules and three H102 modules into a reproducible input archive.
@details    Verify regular-file hashes and reject links, duplicates and path traversal.
            Check ARMv7 ELF and vermagic before depmod in a new directory; use fixed archive metadata.
            Read back every member and preserve input hashes. This offline step never mounts images,
            loads modules or operates devices; keep failed output for diagnosis and inputs read-only.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-11
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile

KERNEL = '6.6.0-h102-sdk1-candidate+'
"""Package only the verified SDK1 candidate kernel version."""
EXTRA_NAMES = {'h102_axi_reg.ko', 'h102_axi_trig.ko', 'h102_profile_control.ko'}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
"""Bound total extracted bytes including all archive entries."""


def sha256(raw: bytes) -> str:
    """Return complete SHA-256 of input bytes."""
    return hashlib.sha256(raw).hexdigest()


def pinned_file(record: dict) -> bytes:
    """Read manifest-pinned regular files; reject type, size or hash mismatch before creating output."""
    if set(record) != {'path', 'bytes', 'sha256'} or not re.fullmatch(
            '[0-9a-f]{64}', record['sha256']):
        raise ValueError('INVALID_FILE_PIN')
    path = Path(record['path'])
    if not path.is_absolute() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('INPUT_MUST_BE_REGULAR_FILE')
    if type(record['bytes']) is not int or not 0 < record['bytes'] <= MAX_ARCHIVE_BYTES:
        raise ValueError('INVALID_INPUT_SIZE')
    if path.stat().st_size != record['bytes']:
        raise ValueError('INPUT_SIZE_MISMATCH')
    raw = path.read_bytes()
    if len(raw) != record['bytes'] or sha256(raw) != record['sha256']:
        raise ValueError('INPUT_SHA_MISMATCH')
    return raw


def module_identity(raw: bytes) -> str:
    """Verify ARM32 little-endian ELF and unique vermagic, without loaded-memory claims."""
    if raw[:6] != b'\x7fELF\x01\x01' or raw[18:20] != b'\x28\x00':
        raise ValueError('MODULE_NOT_ARM32_LE_ELF')
    values = [part.decode('ascii') for part in raw.split(b'\0') if part.startswith(b'vermagic=')]
    if len(values) != 1 or not values[0].startswith('vermagic=' + KERNEL + ' '):
        raise ValueError('MODULE_KERNEL_MISMATCH')
    return values[0]


def archive_members(source: Path | bytes) -> dict[str, bytes | None]:
    """Read a bounded module archive containing unique canonical regular files/directories only."""
    prefix = PurePosixPath('lib/modules') / KERNEL
    entries = {}
    total = 0
    options = {'fileobj': io.BytesIO(source)} if isinstance(source, bytes) else {'name': source}
    with tarfile.open(mode='r:gz', **options) as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            total += member.size
            if (name.is_absolute() or '..' in name.parts or str(name) != member.name or
                    member.name in entries or len(entries) >= 10000 or
                    not (name == PurePosixPath('lib/modules') or name == prefix or
                         prefix in name.parents) or total > MAX_ARCHIVE_BYTES):
                raise ValueError('UNSAFE_ARCHIVE_MEMBER')
            if member.isdir():
                if member.size != 0:
                    raise ValueError('INVALID_DIRECTORY_SIZE')
                entries[member.name] = None
            elif member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError('MISSING_ARCHIVE_MEMBER')
                raw = stream.read(member.size + 1)
                if len(raw) != member.size:
                    raise ValueError('TRUNCATED_ARCHIVE_MEMBER')
                if name.suffix == '.ko':
                    module_identity(raw)
                entries[member.name] = raw
            else:
                raise ValueError('ARCHIVE_LINK_OR_SPECIAL_MEMBER')
    if not entries:
        raise ValueError('EMPTY_MODULE_ARCHIVE')
    return entries


def prepare(manifest: Path, output: Path) -> dict:
    """Merge modules in a new directory, raising on failure and retaining stage evidence.

    Do not overwrite or concurrently reuse output. depmod writes only the caller-owned directory;
    this function never uses sudo or modifies host modules or image release state.
    """
    raw_manifest = manifest.read_bytes()
    pins = json.loads(raw_manifest)
    if (set(pins) != {'schema', 'kernel', 'modules_archive', 'extras'} or
            type(pins['schema']) is not int or pins['schema'] != 1 or
            pins['kernel'] != KERNEL or set(pins['extras']) != EXTRA_NAMES):
        raise ValueError('INVALID_H102_MODULE_INPUT_MANIFEST')
    original = pinned_file(pins['modules_archive'])
    extras = {name: pinned_file(pin) for name, pin in pins['extras'].items()}
    identities = {name: module_identity(raw) for name, raw in extras.items()}
    # Parse verified byte snapshots rather than reopening paths that may have changed.
    entries = archive_members(original)
    for name in extras:
        if any(PurePosixPath(item).name == name for item in entries):
            raise ValueError('EXTERNAL_MODULE_ALREADY_PACKAGED')
    depmod = shutil.which('depmod')
    if depmod is None:
        raise RuntimeError('DEPMOD_REQUIRED')
    output = output.absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('OUTPUT_REQUIRES_NEW_DIRECTORY')
    output.mkdir(mode=0o700)
    (output / 'inputs.json').write_bytes(raw_manifest)
    root = output / 'root'
    root.mkdir()
    for name, raw in entries.items():
        target = root / name
        if raw is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o644)
    updates = root / 'lib/modules' / KERNEL / 'updates'
    updates.mkdir(parents=True, exist_ok=True)
    for name, raw in extras.items():
        (updates / name).write_bytes(raw)
        (updates / name).chmod(0o644)
    result = subprocess.run([depmod, '-b', str(root), '-a', KERNEL], capture_output=True,
                            text=True, timeout=30)
    (output / 'depmod.json').write_text(json.dumps(dict(
        exit=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2) + '\n')
    if result.returncode or result.stderr:
        raise RuntimeError('DEPMOD_FAILED_OR_WARNING')
    dependencies = (root / 'lib/modules' / KERNEL / 'modules.dep').read_text()
    for name in extras:
        if 'updates/' + name + ':' not in dependencies:
            raise RuntimeError('EXTERNAL_MODULE_MISSING_IN_DEPMOD')
    archive = output / 'h102-sdk1-complete-modules.tar.gz'
    inventory = {}
    with archive.open('xb') as wire:
        with gzip.GzipFile(filename='', mode='wb', fileobj=wire, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as tar:
                for path in sorted(root.rglob('*')):
                    relative = str(path.relative_to(root))
                    if relative == 'lib':
                        continue
                    info = tar.gettarinfo(str(path), arcname=relative)
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = 'root'
                    info.mode = 0o755 if path.is_dir() else 0o644
                    if path.is_file():
                        inventory[relative] = dict(bytes=path.stat().st_size,
                                                   sha256=sha256(path.read_bytes()))
                        with path.open('rb') as stream:
                            tar.addfile(info, stream)
                    else:
                        tar.addfile(info)
    decoded = archive_members(archive)
    actual = {name: dict(bytes=len(raw), sha256=sha256(raw))
              for name, raw in decoded.items() if raw is not None}
    if actual != inventory or pinned_file(pins['modules_archive']) != original:
        raise RuntimeError('OUTPUT_READBACK_OR_SOURCE_CHANGED')
    for name, raw in extras.items():
        if pinned_file(pins['extras'][name]) != raw:
            raise RuntimeError('EXTERNAL_MODULE_SOURCE_CHANGED')
    receipt = dict(schema=1, status='PASS_OFFLINE_MODULE_PACKAGE_NOT_IMAGE_OR_BOARD_RELEASE',
                   kernel=KERNEL, input_manifest_sha256=sha256(raw_manifest),
                   archive=archive.name, bytes=archive.stat().st_size,
                   sha256=sha256(archive.read_bytes()), files=inventory, extra_vermagic=identities,
                   depmod_passed=True, all_members_readback_passed=True,
                   hardware_qualified=False, released=False)
    (output / 'candidate.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main() -> None:
    """Use an exact manifest and new output without device-write or release options."""
    parser = argparse.ArgumentParser(description='Prepare complete H102 SDK1 module image inputs')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    receipt = prepare(args.manifest, args.output)
    print(json.dumps({key: value for key, value in receipt.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()

# End of file: prepare_h102_sdk1_modules.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
