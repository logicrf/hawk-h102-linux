#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       build_h102_sdk1_image.py
@brief      Assemble an SDK1 candidate from a pinned base and verified assets.
@details    Create a new artifacts directory and mount the source read-only without journal
            replay. Compare full trees against allowed changes and verify hashes, modes and links.
            Preserve the partition table and first-boot setup without SD writes, deployment or release.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-11
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
from compact_h102_image import Builder, digest, verify_geometry, ROOT_SECTORS

SOURCE_SHA = '69a3599e8548813ebc4efad2160bc0adbdd4e102a94fff806d4fc553cef3a8e7'
SOURCE_BYTES = 11823742976
"""Pin the headless identity-cleared expandable base; reject actual SD block devices."""


def fat_mount(builder: Builder, device: str, name: str, readonly: bool) -> Path:
    """Mount this builder's FAT partition without ext4-specific noload options."""
    target = builder.temp / name
    target.mkdir()
    builder.run(['mount', '-o', 'ro' if readonly else 'rw', device, str(target)], privileged=True)
    builder.mounts.append(target)
    return target


def destination(root: Path, boot: Path, name: str, *, allow_symlink: bool = False) -> Path:
    """Map canonical product paths to owned mounts and reject linked-ancestor escapes."""
    path = PurePosixPath(name)
    if not path.is_absolute() or str(path) != name or '..' in path.parts:
        raise ValueError('INSTALL_PATH')
    base = boot if name.startswith('/boot/') else root
    suffix = name.removeprefix('/boot/') if base == boot else name.lstrip('/')
    target = base / suffix
    if not target.parent.resolve().is_relative_to(base.resolve()) or (
            target.is_symlink() and not allow_symlink):
        raise ValueError('INSTALL_PARENT_OR_TARGET_ESCAPE')
    return target


def compare(builder: Builder, source: Path, output: Path, excluded: list[str], label: str) -> None:
    """Compare complete trees, allowing only listed leaves and their newly required parents."""
    allowed = set()
    for name in excluded:
        path = Path(name)
        for parent in path.parents:
            if str(parent) != '.' and not (source / parent).exists():
                allowed.add('cd+++++++++ ' + str(parent) + '/')
                allowed.add('*deleting   ' + str(parent) + '/')
                allowed.add('cannot delete non-empty directory: ' + str(parent))
                info = (output / parent).lstat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or
                        stat.S_IMODE(info.st_mode) != 0o755):
                    raise RuntimeError('NEW_ASSET_PARENT_OWNER_MODE: ' + str(parent))
    result = builder.run(['rsync', '-aHAXnci', '--numeric-ids', '--delete', '--omit-dir-times',
                          *['--exclude=/' + name for name in excluded],
                          str(source) + '/', str(output) + '/'], privileged=True)
    (builder.evidence / (label + '-content-differences.txt')).write_text(result)
    unexpected = [line for line in result.splitlines() if line not in allowed]
    if unexpected:
        raise RuntimeError('UNEXPECTED_' + label.upper() + '_DIFFERENCES: ' + repr(unexpected[:10]))


def build(source: Path, assets: Path, output: Path, project: Path) -> dict:
    """Assemble and verify a new copy; finally release only this instance's loops and mounts."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size != SOURCE_BYTES:
        raise ValueError('PINNED_REGULAR_BASE_IMAGE')
    if output.parent != project / 'artifacts' or output.exists() or output.is_symlink():
        raise ValueError('FRESH_PROJECT_ARTIFACTS_OUTPUT')
    if assets.is_symlink() or not assets.is_dir():
        raise ValueError('REGULAR_ASSETS_DIRECTORY')
    manifest_path = assets / 'asset-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('REGULAR_ASSET_MANIFEST')
    manifest_raw = manifest_path.read_bytes(); manifest = json.loads(manifest_raw)
    tool_sha = digest(Path(__file__))
    tool_commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    for name, expected in manifest['tool_sources'].items():
        if digest(project / name) != expected:
            raise ValueError('ASSEMBLY_TOOL_SOURCE_CHANGED: ' + name)
    if manifest['status'] != 'PASS_OFFLINE_ASSETS_NOT_IMAGE_BOOT_OR_BOARD' or (
            manifest['profile_count'], manifest['script_count']) != (29, 107):
        raise ValueError('ASSET_MANIFEST_NOT_QUALIFIED')
    asset_paths = {}
    for name, entry in manifest['files'].items():
        path = assets / 'assets' / name.lstrip('/')
        if (not PurePosixPath(name).is_absolute() or str(PurePosixPath(name)) != name or
                '..' in PurePosixPath(name).parts or path.is_symlink() or not path.is_file() or
                path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256'] or
                entry['mode'] not in (0o644, 0o755)):
            raise ValueError('ASSET_PIN: ' + name)
        asset_paths[name] = path
    if digest(source) != SOURCE_SHA:
        raise ValueError('BASE_IMAGE_SHA')
    original_mbr = verify_geometry(source, ROOT_SECTORS)
    output.mkdir(mode=0o700); (output / 'evidence').mkdir(mode=0o700)
    (output / 'asset-manifest.json').write_bytes(manifest_raw)
    builder = Builder(source, output, project)
    builder.image = output / 'LogicRF-Hawk-H102-Kuiper-SDK1-runtime-wire-candidate.img'
    try:
        sl = builder.attach(source, readonly=True)
        sr = builder.mount(sl + 'p2', 'source-root', readonly=True)
        sb = fat_mount(builder, sl + 'p1', 'source-boot', True)
        builder.run(['cp', '--sparse=always', '--reflink=auto', str(source), str(builder.image)])
        dl = builder.attach(builder.image)
        root = builder.mount(dl + 'p2', 'output-root', readonly=False)
        boot = fat_mount(builder, dl + 'p1', 'output-boot', False)
        excluded_root = []; excluded_boot = []
        for name, src in asset_paths.items():
            target = destination(root, boot, name)
            if not name.startswith('/boot/') and os.path.lexists(target):
                raise ValueError('BASE_ALREADY_HAS_PRODUCT_ASSET: ' + name)
            builder.run(['install', '-D', '-o', 'root', '-g', 'root', '-m',
                         oct(manifest['files'][name]['mode'])[2:], str(src), str(target)], privileged=True)
            if name.startswith('/boot/'):
                excluded_boot.append(str(target.relative_to(boot)))
            else:
                excluded_root.append(str(target.resolve().relative_to(root.resolve())))
        for name, link in manifest['links'].items():
            target = destination(root, boot, name)
            if name.startswith('/boot/') or os.path.lexists(target) or not link.startswith('../'):
                raise ValueError('NEW_RELATIVE_UNIT_LINK_REQUIRED')
            resolved = (target.parent / link).resolve()
            if not resolved.is_relative_to((root / 'etc/systemd/system').resolve()) or not resolved.is_file():
                raise ValueError('UNIT_LINK_TARGET')
            builder.run(['mkdir', '-p', str(target.parent)], privileged=True)
            builder.run(['ln', '-s', link, str(target)], privileged=True)
            excluded_root.append(str(target.relative_to(root)))
        builder.run(['sync', '-f', str(root)], privileged=True)
        builder.run(['sync', '-f', str(boot)], privileged=True)
        builder.unmount(boot); builder.unmount(root); builder.detach(dl)
        dl = builder.attach(builder.image, readonly=True)
        builder.run(['fsck.fat', '-v', '-n', dl + 'p1'], privileged=True)
        builder.run(['e2fsck', '-f', '-n', dl + 'p2'], privileged=True)
        root = builder.mount(dl + 'p2', 'verified-root', readonly=True)
        boot = fat_mount(builder, dl + 'p1', 'verified-boot', True)
        compare(builder, sr, root, excluded_root, 'root')
        compare(builder, sb, boot, excluded_boot, 'boot')
        for name, entry in manifest['files'].items():
            target = destination(root, boot, name); info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or digest(target) != entry['sha256'] or info.st_size != entry['bytes']:
                raise RuntimeError('INSTALLED_ASSET_READBACK: ' + name)
            if not name.startswith('/boot/') and (info.st_uid != 0 or info.st_gid != 0 or
                    stat.S_IMODE(info.st_mode) != entry['mode']):
                raise RuntimeError('INSTALLED_ASSET_OWNER_MODE: ' + name)
            base = boot if name.startswith('/boot/') else root
            rel = target.relative_to(base)
            for component in (rel,) + tuple(rel.parents):
                item = base / component; trusted = item.lstat()
                directory = component != rel
                kind = stat.S_ISDIR if directory else stat.S_ISREG
                if trusted.st_uid != 0 or trusted.st_mode & 0o022 or not kind(trusted.st_mode):
                    raise RuntimeError('BOOTSTRAP_UNTRUSTED_ASSET_ANCESTOR: ' + name)
        for name, link in manifest['links'].items():
            target = destination(root, boot, name, allow_symlink=True)
            if os.readlink(target) != link or target.lstat().st_uid != 0:
                raise RuntimeError('INSTALLED_UNIT_LINK')
        if (root / 'etc/machine-id').read_bytes() != b'':
            raise RuntimeError('SHARED_IMAGE_MACHINE_ID_NOT_EMPTY')
        keys = builder.run(['find', str(root / 'etc/ssh'), '-maxdepth', '1', '-name', 'ssh_host_*', '-print'], privileged=True)
        if keys.strip():
            raise RuntimeError('SHARED_IMAGE_SSH_KEYS')
        for n in ('secret_key', 'secret-key'):
            if os.path.lexists(root / 'var/lib/NetworkManager' / n):
                raise RuntimeError('SHARED_IMAGE_NETWORKMANAGER_KEY')
        for mount in list(reversed(builder.mounts)):
            builder.unmount(mount)
        for loop in list(reversed(builder.loops)):
            builder.detach(loop)
        if verify_geometry(builder.image, ROOT_SECTORS) != original_mbr:
            raise RuntimeError('IMAGE_MBR_CHANGED')
        if digest(source) != SOURCE_SHA or manifest_path.read_bytes() != manifest_raw:
            raise RuntimeError('ORIGINAL_INPUT_CHANGED')
        if digest(Path(__file__)) != tool_sha:
            raise RuntimeError('BUILD_TOOL_CHANGED_DURING_EXECUTION')
        for name, src in asset_paths.items():
            if digest(src) != manifest['files'][name]['sha256']:
                raise RuntimeError('ORIGINAL_ASSET_CHANGED: ' + name)
        result = dict(schema=1, status='PASS_OFFLINE_IMG_NOT_DEFAULT_BOOT_OR_RELEASE',
                      base_image_sha256=SOURCE_SHA, asset_manifest_sha256=digest(manifest_path),
                      source_commit=manifest['source_commit'], boot_pins=manifest['boot_pins'],
                      assembly_tool_commit=tool_commit, assembly_builder_sha256=tool_sha,
                      image=builder.image.name, bytes=builder.image.stat().st_size,
                      sha256=digest(builder.image), files_verified=len(manifest['files']),
                      links_verified=len(manifest['links']), root_and_FAT_whitelist=True,
                      FAT_ext4_checks=True, hardware_qualified=False, released=False)
        (output / 'candidate.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    finally:
        for mount in list(reversed(builder.mounts)):
            builder.unmount(mount)
        for loop in list(reversed(builder.loops)):
            builder.detach(loop)
        for empty in builder.temp.iterdir():
            empty.rmdir()
        builder.temp.rmdir()


def main() -> None:
    """Accept a regular base, prepared assets and new artifacts output, never block devices."""
    parser = argparse.ArgumentParser(description='Assemble a complete H102 SDK1 image candidate')
    parser.add_argument('source', type=Path); parser.add_argument('assets', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source.absolute(), args.assets.absolute(), args.output.absolute(),
                           Path(__file__).resolve().parents[1]), indent=2))


if __name__ == '__main__':
    main()

# End of file: build_h102_sdk1_image.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
