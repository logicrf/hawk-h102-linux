#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file build_h102_panel_image.py
@brief Build and independently verify a full panel image from the pinned 1.2.0 base.
@details Use fixed source and payload identities; keep backups and failure evidence.
         Image preparation is offline. Device installation requires an administrator;
         normal applications require only the device IP. Do not widen qualification.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.0.0
@date 2026-10-27
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import stat

from compact_h102_image import Builder, ROOT_SECTORS, digest, verify_geometry
from build_h102_sdk1_image import compare, destination, fat_mount
from build_h102_irq_hotfix_image import verify_files, encoded
from build_h102_driver_fix_image import check_firstboot
from prepare_h102_panel_image import BASE_SHA, BASE_MANIFEST_SHA, METADATA, VERSION, API_DIRECTORY_MODES

BASE_BYTES = 11823742976
"""Keep the fixed 9 GiB root partition and DOS geometry; do not derive them from a running card."""


def source_tools(project, expected):
    """Verify every pinned tool before and after image generation."""
    for name, sha in expected.items():
        if digest(project/name) != sha:
            raise ValueError('PANEL_IMAGE_TOOL_CHANGED:'+name)


def firstboot(builder, root):
    """Check the shared first-boot identity policy and reject baked-in device transactions."""
    check_firstboot(builder, root)
    for name in ('var/lib/h102/panel-status-1', 'var/lib/h102/grc-hotmeta-1',
                 'run/h102-profile-config-sdk1.json', 'run/h102-image-api-ready.json'):
        if os.path.lexists(root/name):
            raise ValueError('PANEL_IMAGE_DEVICE_STATE_FORBIDDEN:'+name)


def verify_api_directories(root, boot, expected):
    """Check exact API directories, root ownership and 0700 independently of file hashes."""
    if expected != API_DIRECTORY_MODES:
        raise ValueError('PANEL_IMAGE_EXACT_API_DIRECTORY_MODES')
    for name, mode in expected.items():
        path = destination(root, boot, name)
        value = path.lstat()
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_gid != 0
                or stat.S_IMODE(value.st_mode) != mode):
            raise ValueError('PANEL_IMAGE_API_DIRECTORY_OWNER_MODE:'+name)


def build(source, stage, output, project):
    """Validate fixed ordinary inputs, generate a new output, and independently verify the result.

    Preserve failures and release only resources created by this invocation. This does not qualify a physical SD boot."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size != BASE_BYTES:
        raise ValueError('PANEL_IMAGE_EXACT_REGULAR_BASE_REQUIRED')
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('PANEL_IMAGE_FRESH_OUTPUT_REQUIRED')
    base_path = project/'docs/receipts/20261015-common-lo-rc2-image-candidate.json'
    if digest(base_path) != BASE_MANIFEST_SHA or digest(source) != BASE_SHA:
        raise ValueError('PANEL_IMAGE_BASE_PIN')
    raw = (stage/'asset-delta.json').read_bytes()
    delta = json.loads(raw)
    base = json.loads(base_path.read_text())
    if (delta['status'] != 'PREPARED_FULL_IMAGE_ASSETS_NOT_COLD_BOOT_QUALIFIED'
            or delta['version'] != VERSION or delta['base_raw_sha256'] != BASE_SHA
            or delta['base_manifest_sha256'] != BASE_MANIFEST_SHA):
        raise ValueError('PANEL_IMAGE_STAGE_IDENTITY')
    source_tools(project, delta['tools'])
    if delta.get('directories') != API_DIRECTORY_MODES:
        raise ValueError('PANEL_IMAGE_REQUIRED_PRIVATE_DIRECTORIES')
    expected = dict(base['files'])
    expected.update(delta['delta_files'])
    if expected != delta['files']:
        raise ValueError('PANEL_IMAGE_EXACT_BASE_PLUS_DELTA')
    actual = {str(p.relative_to(stage/'assets')) for p in (stage/'assets').rglob('*') if p.is_file()}
    if actual != {n.lstrip('/') for n in delta['delta_files']}:
        raise ValueError('PANEL_IMAGE_STAGE_FILE_SET')
    for name, row in delta['delta_files'].items():
        path = stage/'assets'/name.lstrip('/')
        if (path.is_symlink() or not path.is_file() or digest(path) != row['sha256']
                or path.stat().st_size != row['bytes'] or row['mode'] not in (0o600, 0o644)):
            raise ValueError('PANEL_IMAGE_STAGE_ASSET:'+name)
    metadata = json.loads((stage/'assets'/METADATA.lstrip('/')).read_text())
    if metadata['boot_pins'] != delta['boot_pins'] or metadata['kernel'] != delta['kernel']:
        raise ValueError('PANEL_IMAGE_METADATA_BOOT_KERNEL')
    commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != delta['source_commit'] or subprocess.check_output(
            ['git', '-C', str(project), 'status', '--porcelain'], text=True):
        raise ValueError('PANEL_IMAGE_FROZEN_SOURCE_REQUIRED')
    mbr = verify_geometry(source, ROOT_SECTORS)
    output.mkdir(mode=0o700)
    (output/'evidence').mkdir(mode=0o700)
    (output/'asset-delta.json').write_bytes(raw)
    builder = Builder(source, output, project)
    builder.image = output/('LogicRF-Hawk-H102-Kuiper-'+VERSION+'-2024.1.img')
    try:
        sl = builder.attach(source, readonly=True)
        source_root = builder.mount(sl+'p2', 'source-root', readonly=True)
        source_boot = fat_mount(builder, sl+'p1', 'source-boot', True)
        verify_files(source_root, source_boot, base['files'])
        firstboot(builder, source_root)
        if (source_root/'etc/systemd/system/h102-control-api.service').exists():
            raise ValueError('PANEL_IMAGE_BASE_ALREADY_HAS_API')
        builder.run(['cp', '--sparse=always', '--reflink=auto', str(source), str(builder.image)])
        if source.stat().st_ino == builder.image.stat().st_ino:
            raise ValueError('PANEL_IMAGE_SOURCE_ALIAS')
        dl = builder.attach(builder.image)
        root = builder.mount(dl+'p2', 'output-root', readonly=False)
        boot = fat_mount(builder, dl+'p1', 'output-boot', False)
        for name, row in delta['delta_files'].items():
            src = stage/'assets'/name.lstrip('/')
            builder.run(['install', '-D', '-o', 'root', '-g', 'root', '-m', format(row['mode'], 'o'),
                         str(src), str(destination(root, boot, name))], privileged=True)
        for name, mode in delta['directories'].items():
            builder.run(['chmod', format(mode, 'o'), str(destination(root, boot, name))], privileged=True)
        verify_api_directories(root, boot, delta['directories'])
        new_link = '/etc/systemd/system/multi-user.target.wants/h102-control-api.service'
        target = destination(root, boot, new_link, allow_symlink=True)
        if os.path.lexists(target):
            raise ValueError('PANEL_IMAGE_NEW_LINK_EXISTS')
        builder.run(['ln', '-s', delta['links'][new_link], str(target)], privileged=True)
        for mount in (root, boot):
            builder.run(['sync', '-f', str(mount)], privileged=True)
        builder.unmount(boot)
        builder.unmount(root)
        builder.detach(dl)
        dl = builder.attach(builder.image, readonly=True)
        builder.run(['fsck.fat', '-v', '-n', dl+'p1'], privileged=True)
        builder.run(['e2fsck', '-f', '-n', dl+'p2'], privileged=True)
        root = builder.mount(dl+'p2', 'verified-root', readonly=True)
        boot = fat_mount(builder, dl+'p1', 'verified-boot', True)
        changes = delta['delta_files']
        compare(builder, source_root, root,
                [n.lstrip('/') for n in changes if not n.startswith('/boot/')]+[new_link.lstrip('/')], 'root',
                directory_modes={name.lstrip('/'): mode for name, mode in delta['directories'].items()})
        compare(builder, source_boot, boot,
                [n.removeprefix('/boot/') for n in changes if n.startswith('/boot/')], 'boot')
        verify_files(root, boot, expected)
        verify_api_directories(root, boot, delta['directories'])
        firstboot(builder, root)
        for name, target in delta['links'].items():
            path = destination(root, boot, name, allow_symlink=True)
            if not path.is_symlink() or os.readlink(path) != target:
                raise ValueError('PANEL_IMAGE_LINK_CHANGED:'+name)
        for mount in list(reversed(builder.mounts)):
            builder.unmount(mount)
        for loop in list(reversed(builder.loops)):
            builder.detach(loop)
        if (verify_geometry(builder.image, ROOT_SECTORS) != mbr or digest(source) != BASE_SHA
                or digest(source, 0, 24576*512) != digest(builder.image, 0, 24576*512)):
            raise ValueError('PANEL_IMAGE_SOURCE_GEOMETRY_OR_BOOT_PREFIX')
        if (stage/'asset-delta.json').read_bytes() != raw:
            raise ValueError('PANEL_IMAGE_STAGE_CHANGED')
        for name, row in changes.items():
            if digest(stage/'assets'/name.lstrip('/')) != row['sha256']:
                raise ValueError('PANEL_IMAGE_STAGE_CHANGED:'+name)
        source_tools(project, delta['tools'])
        result = dict(schema=1, status='PASS_OFFLINE_PANEL_FULL_IMAGE_NOT_COLD_BOOT_OR_RELEASE',
            version=VERSION, image=builder.image.name, bytes=builder.image.stat().st_size,
            sha256=digest(builder.image), base_image_sha256=BASE_SHA,
            source_commit=commit, files=expected, directories=delta['directories'], links=delta['links'], boot_pins=delta['boot_pins'],
            files_verified=len(expected), sdk_sources=108, profile_packages=58,
            identity_firstboot=True, FAT_ext4_checks=True, root_and_FAT_whitelist=True,
            no_device_install_transaction=True, hardware_qualified=False, released=False)
        (output/'candidate.json').write_bytes(encoded(result))
        return result
    finally:
        for mount in list(reversed(builder.mounts)):
            builder.unmount(mount)
        for loop in list(reversed(builder.loops)):
            builder.detach(loop)
        for path in builder.temp.iterdir():
            path.rmdir()
        builder.temp.rmdir()


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('stage', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = build(args.source.resolve(), args.stage.resolve(), args.output.resolve(),
                   Path(__file__).resolve().parents[1])
    print(json.dumps({k: result[k] for k in ('status', 'version', 'bytes', 'sha256', 'files_verified')}))


if __name__ == '__main__':
    main()
# End of file: build_h102_panel_image.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
