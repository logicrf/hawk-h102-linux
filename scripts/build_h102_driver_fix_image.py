#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       build_h102_driver_fix_image.py
@brief      Integrate verified calibration/register fixes into a new 1.1.1 image copy.
@details    Preserve first-boot identity, networking and presets; update FIT, bindings,
            metadata and matching modules only. Mount ordinary source images read-only and
            verify assets, filesystems and allowed changes; release only owned resources on failure.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-14
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess

from compact_h102_image import Builder, ROOT_SECTORS, digest, verify_geometry
from build_h102_sdk1_image import compare, destination, fat_mount
from build_h102_irq_hotfix_image import encoded, verify_files

BASE_BYTES = 11823742976
BASE_SHA = 'd5ffd1b34440219893d74d5f363915df4424336e29e5c987745490463d369088'
MANIFEST_SHA = 'e1d0d6786c2206d6289c2237fba27f8ce7e4885f7370f4d31a997017768e44d1'
ARCHIVE_SHA = '6006e83c8d3786487b5a03c6003507cc08919bf44ac6f2d05b5d3e749f7c5205'
KERNEL = '6.6.0-h102-sdk1-candidate-calfix1-regbounds1'
VERSION = '1.1.1-calfix1-regbounds1-sd-candidate'
METADATA = '/etc/h102/sdk1-image.json'
CONFIG = '/usr/local/lib/h102/sdk1/scripts/h102_profile_config.py'
FIT = '/boot/image-sdk1.ub'
"""Pin the base and assets without copying old board-specific modules or persistent identity."""


def check_firstboot(builder: Builder, root: Path) -> None:
    """Verify cleared device identity and preserve first-boot expansion and stable MAC setup."""
    if (root / 'etc/machine-id').read_bytes() != b'':
        raise RuntimeError('SHARED_MACHINE_ID')
    keys = builder.run(['find', str(root / 'etc/ssh'), '-maxdepth', '1',
                        '-name', 'ssh_host_*', '-print'], privileged=True)
    if keys.strip():
        raise RuntimeError('SHARED_SSH_KEYS')
    for name in ('secret_key', 'secret-key'):
        if os.path.lexists(root / 'var/lib/NetworkManager' / name):
            raise RuntimeError('SHARED_NM_SECRET')
    connections = builder.run(['/usr/bin/grep', '-Rl', '^cloned-mac-address=stable$',
                               str(root / 'etc/NetworkManager/system-connections')],
                              privileged=True)
    if not connections.strip():
        raise RuntimeError('STABLE_MAC_MISSING')
    if not (root / 'etc/systemd/system/multi-user.target.wants/h102-grow-rootfs.service').is_symlink():
        raise RuntimeError('FIRSTBOOT_GROW_MISSING')


def build(source: Path, stage: Path, output: Path, project: Path) -> dict:
    """Build and verify a new regular image; do not issue a success receipt on failure."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size != BASE_BYTES:
        raise ValueError('REGULAR_PINNED_BASE_REQUIRED')
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('FRESH_OUTPUT_REQUIRED')
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError('REGULAR_STAGE_REQUIRED')
    manifest = project / 'docs/receipts/20261012-network-iiod-rc2-image-candidate.json'
    if digest(manifest) != MANIFEST_SHA or digest(source) != BASE_SHA:
        raise ValueError('BASE_PIN')
    if digest(stage.parent / 'regbounds1-deploy.tar.gz') != ARCHIVE_SHA:
        raise ValueError('TESTED_ARCHIVE_PIN')
    base = json.loads(manifest.read_bytes())
    staged = json.loads((stage / METADATA.lstrip('/')).read_bytes())
    if staged['kernel'] != KERNEL:
        raise ValueError('STAGE_KERNEL')
    module_root = stage / 'usr/lib/modules' / KERNEL
    if any(p.is_symlink() for p in module_root.rglob('*')):
        raise ValueError('MODULE_SYMLINK')
    selected = [FIT, CONFIG] + ['/' + str(p.relative_to(stage)) for p in sorted(
        module_root.rglob('*')) if p.is_file()]
    if len(selected) != 26:
        raise ValueError('STAGE_FILE_COUNT')
    entries = {n: staged['assets'][n] for n in selected}
    for name, entry in entries.items():
        p = stage / name.lstrip('/')
        if (p.is_symlink() or not p.is_file() or p.stat().st_size != entry['bytes']
                or digest(p) != entry['sha256'] or entry['mode'] != 0o644):
            raise ValueError('STAGE_FILE_PIN: ' + name)
    pins = dict(base['boot_pins'], **{FIT: entries[FIT]['sha256']})
    if pins != staged['boot_pins']:
        raise ValueError('STAGE_BOOT_PINS')
    tree = ast.parse((stage / CONFIG.lstrip('/')).read_bytes(), feature_version=(3, 9))
    compiled = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'BOOT_PINS' for t in n.targets))
    if compiled != pins or KERNEL not in (stage / CONFIG.lstrip('/')).read_text():
        raise ValueError('CONFIG_BINDING')
    for p in module_root.rglob('*.ko'):
        if subprocess.check_output(['modinfo', '-F', 'vermagic', str(p)], text=True).split()[0] != KERNEL:
            raise ValueError('MODULE_VERMAGIC: ' + str(p))
    names = ('build_h102_driver_fix_image.py', 'compact_h102_image.py',
             'build_h102_sdk1_image.py', 'build_h102_irq_hotfix_image.py')
    tools = {n: digest(project / 'scripts' / n) for n in names}
    commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    mbr = verify_geometry(source, ROOT_SECTORS)
    output.mkdir(mode=0o700); (output / 'evidence').mkdir(mode=0o700)
    b = Builder(source, output, project)
    b.image = output / ('LogicRF-Hawk-H102-Kuiper-' + VERSION + '-2024.1.img')
    try:
        sl = b.attach(source, readonly=True)
        sr = b.mount(sl + 'p2', 'source-root', readonly=True)
        sb = fat_mount(b, sl + 'p1', 'source-boot', True)
        verify_files(sr, sb, base['files']); check_firstboot(b, sr)
        metadata = json.loads(destination(sr, sb, METADATA).read_bytes())
        if metadata['assets'] != {n: e for n, e in base['files'].items() if n != METADATA}:
            raise ValueError('BASE_METADATA_ASSETS')
        if metadata['boot_pins'] != base['boot_pins']:
            raise ValueError('BASE_METADATA_BOOT')
        # Rebuild metadata from the base delta, excluding old first-board modules and device state.
        metadata['assets'].update(entries)
        metadata.update(kernel=KERNEL, version=VERSION, boot_pins=pins,
                        source_commit=staged['source_commit'], image_recipe_commit=commit,
                        status='CANDIDATE_NOT_EXACT_IMAGE_BOOT_QUALIFIED',
                        hardware_qualified=False, released=False, base_image_sha256=BASE_SHA,
                        calibration_fix=staged['calibration_fix'],
                        adc_register_bounds=staged['adc_register_bounds'])
        mf = output / 'sdk1-image.json'; mf.write_bytes(encoded(metadata))
        expected = dict(base['files']); expected.update(entries)
        expected[METADATA] = dict(bytes=mf.stat().st_size, mode=0o644, sha256=digest(mf))
        b.run(['cp', '--sparse=always', '--reflink=auto', str(source), str(b.image)])
        if b.image.stat().st_ino == source.stat().st_ino:
            raise RuntimeError('SOURCE_ALIAS')
        dl = b.attach(b.image)
        root = b.mount(dl + 'p2', 'output-root', readonly=False)
        boot = fat_mount(b, dl + 'p1', 'output-boot', False)
        delta = [*selected, METADATA]
        for name in delta:
            src = mf if name == METADATA else stage / name.lstrip('/')
            b.run(['install', '-D', '-o', 'root', '-g', 'root', '-m', '0644', str(src),
                   str(destination(root, boot, name))], privileged=True)
        b.run(['sync', '-f', str(root)], privileged=True)
        b.run(['sync', '-f', str(boot)], privileged=True)
        b.unmount(boot); b.unmount(root); b.detach(dl)
        dl = b.attach(b.image, readonly=True)
        b.run(['fsck.fat', '-v', '-n', dl + 'p1'], privileged=True)
        b.run(['e2fsck', '-f', '-n', dl + 'p2'], privileged=True)
        root = b.mount(dl + 'p2', 'verified-root', readonly=True)
        boot = fat_mount(b, dl + 'p1', 'verified-boot', True)
        compare(b, sr, root, [n.lstrip('/') for n in delta if not n.startswith('/boot/')], 'root')
        compare(b, sb, boot, ['image-sdk1.ub'], 'boot')
        verify_files(root, boot, expected); check_firstboot(b, root)
        for name, link in base['links'].items():
            if os.readlink(destination(root, boot, name, allow_symlink=True)) != link:
                raise RuntimeError('BASE_LINK_CHANGED')
        for mount in list(reversed(b.mounts)): b.unmount(mount)
        for loop in list(reversed(b.loops)): b.detach(loop)
        if verify_geometry(b.image, ROOT_SECTORS) != mbr or digest(source) != BASE_SHA:
            raise RuntimeError('BASE_OR_GEOMETRY_CHANGED')
        if any(digest(project / 'scripts' / n) != sha for n, sha in tools.items()):
            raise RuntimeError('TOOL_CHANGED')
        if any(digest(stage / n.lstrip('/')) != e['sha256'] for n, e in entries.items()):
            raise RuntimeError('STAGE_CHANGED')
        result = dict(schema=1, status='PASS_OFFLINE_IMAGE_NOT_BOOT_OR_RELEASE', version=VERSION,
                      kernel=KERNEL, image=b.image.name, bytes=b.image.stat().st_size,
                      sha256=digest(b.image), base_image_sha256=BASE_SHA,
                      base_manifest_sha256=MANIFEST_SHA, stage_archive_sha256=ARCHIVE_SHA,
                      kernel_source_commit=staged['source_commit'], recipe_commit=commit,
                      tool_sources=tools, files=expected, links=base['links'], boot_pins=pins,
                      files_verified=len(expected), delta_files=delta, identity_firstboot=True,
                      FAT_ext4_checks=True, root_and_FAT_whitelist=True,
                      hardware_qualified=False, released=False)
        (output / 'candidate.json').write_bytes(encoded(result))
        return result
    finally:
        for mount in list(reversed(b.mounts)): b.unmount(mount)
        for loop in list(reversed(b.loops)): b.detach(loop)
        for empty in b.temp.iterdir(): empty.rmdir()
        b.temp.rmdir()


def main() -> None:
    """Use pinned regular inputs and a new output directory, without a block-device option."""
    p = argparse.ArgumentParser(description='Assemble an H102 driver-fix image candidate')
    p.add_argument('source', type=Path); p.add_argument('stage', type=Path)
    p.add_argument('output', type=Path); args = p.parse_args()
    result = build(args.source.absolute(), args.stage.absolute(), args.output.absolute(),
                   Path(__file__).resolve().parents[1])
    print(json.dumps({k: result[k] for k in ('status', 'version', 'bytes', 'sha256', 'files_verified')}))


if __name__ == '__main__':
    main()

# End of file: build_h102_driver_fix_image.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
