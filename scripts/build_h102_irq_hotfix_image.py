#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       build_h102_irq_hotfix_image.py
@brief      Install the network IRQ and IIO CPU policy into an exact 1.1.0 image copy.
@details    Pin the RAW image and 353 assets, mounting the source read-only without journal
            replay. Update only the listed eight files and service link, then verify the complete trees.
            Release owned loops/mounts in finally; exact board boot is required for a new release.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.1
@date       2026-10-12
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from compact_h102_image import Builder, ROOT_SECTORS, digest, verify_geometry
from build_h102_sdk1_image import compare, destination, fat_mount

BASE_SHA = '05a1c8ab6926ac3c6bd29f513472cc7fff05d92518057cdf9b6c14c1ef3c9b09'
BASE_BYTES = 11823742976
BASE_MANIFEST_SHA = '44d29d50ed3c11f27c0f807992a43e760aadae0684bfa07d7da0f67789c0caac'
VERSION = '1.1.1-rc2'
METADATA = '/etc/h102/sdk1-image.json'
"""Pin original and candidate identities; never substitute hashes from a running board."""


def encoded(value):
    """Encode deterministic JSON with a trailing newline for files and receipts."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def verify_files(root, boot, entries):
    """Verify regular file length, hash and root ownership, respecting FAT mount semantics."""
    for name, entry in entries.items():
        path = destination(root, boot, name)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size != entry['bytes']
                or digest(path) != entry['sha256']):
            raise RuntimeError('ASSET_READBACK: ' + name)
        if not name.startswith('/boot/') and (
                info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != entry['mode']):
            raise RuntimeError('ASSET_OWNER_MODE: ' + name)


def build(source, output, project):
    """Verify a pinned base, isolated copy, explicit file delta and read-only output readback."""
    if (source.is_symlink() or not source.is_file() or source.stat().st_size != BASE_BYTES
            or digest(source) != BASE_SHA):
        raise ValueError('EXACT_REGULAR_1_1_0_IMAGE_REQUIRED')
    if output.parent != project / 'artifacts' or output.exists():
        raise ValueError('FRESH_PROJECT_ARTIFACTS_OUTPUT_REQUIRED')
    base_manifest_path = project / 'docs/receipts/20261012-sdk1-rc2-assets-manifest.json'
    if digest(base_manifest_path) != BASE_MANIFEST_SHA:
        raise ValueError('BASE_MANIFEST_PIN')
    base = json.loads(base_manifest_path.read_bytes())
    if len(base['files']) != 353 or len(base['links']) != 3:
        raise ValueError('BASE_ASSET_COUNTS')
    sources = {
        '/usr/local/lib/h102/sdk1/scripts/h102_network_affinity.py':
            ('scripts/h102_network_affinity.py', 0o644),
        '/etc/systemd/system/h102-network-affinity.service':
            ('overlays/h102/etc/systemd/system/h102-network-affinity.service', 0o644),
        '/etc/NetworkManager/dispatcher.d/25-h102-network-affinity':
            ('overlays/h102/etc/NetworkManager/dispatcher.d/25-h102-network-affinity', 0o755),
    }
    source_files = {path: digest(project / path) for path, _ in sources.values()}
    source_files.update({path: digest(project / path) for path in (
        'scripts/build_h102_irq_hotfix_image.py', 'scripts/build_h102_sdk1_image.py',
        'scripts/compact_h102_image.py')})
    commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    delta = {name: (project / path).read_bytes() for name, (path, _) in sources.items()}
    modes = {name: mode for name, (_, mode) in sources.items()}
    ast.parse(delta['/usr/local/lib/h102/sdk1/scripts/h102_network_affinity.py'], feature_version=(3, 9))
    for unit in ('iiod', 'iiod_ffs', 'h102-profile-control'):
        name = '/etc/systemd/system/' + unit + '.service.d/40-h102-network-affinity.conf'
        delta[name] = b'[Unit]\nWants=h102-network-affinity.service\nAfter=h102-network-affinity.service\n'
        # Keep IIO threads on CPU0, separate from CPU1 network IRQs and softirqs.
        # systemd sets affinity at startup and threads inherit it; the broker preserves the mask.
        if unit in ('iiod', 'iiod_ffs'):
            delta[name] += b'\n[Service]\nCPUAffinity=0\n'
        modes[name] = 0o644
    patch_info = dict(schema=1, version=VERSION, status='CANDIDATE_NOT_EXACT_IMAGE_BOOT_QUALIFIED',
                      base_image_sha256=BASE_SHA, source_commit=commit, target_cpu=1,
                      iiod_cpu=0, iiod_units=['iiod.service', 'iiod_ffs.service'],
                      no_network_boot='ExecCondition skip; NetworkManager up starts policy',
                      hardware_qualified=False, released=False)
    delta['/etc/h102/network-irq-hotfix.json'] = encoded(patch_info)
    modes['/etc/h102/network-irq-hotfix.json'] = 0o644
    output.mkdir(mode=0o700)
    (output / 'evidence').mkdir(mode=0o700)
    builder = Builder(source, output, project)
    builder.image = output / ('LogicRF-Hawk-H102-Kuiper-' + VERSION + '-2024.1.img')
    original_mbr = verify_geometry(source, ROOT_SECTORS)
    try:
        sl = builder.attach(source, readonly=True)
        sr = builder.mount(sl + 'p2', 'source-root', readonly=True)
        sb = fat_mount(builder, sl + 'p1', 'source-boot', True)
        verify_files(sr, sb, base['files'])
        metadata = json.loads(destination(sr, sb, METADATA).read_bytes())
        old_entries = {n: e for n, e in base['files'].items() if n != METADATA}
        if metadata['assets'] != old_entries or metadata['boot_pins'] != base['boot_pins']:
            raise ValueError('BASE_BOOTSTRAP_METADATA_MISMATCH')
        additions = {n: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                             mode=modes[n]) for n, raw in delta.items()}
        metadata['assets'].update(additions)
        metadata.update(version=VERSION, network_irq_policy=patch_info,
                        hardware_qualified=False, released=False)
        delta[METADATA] = encoded(metadata)
        modes[METADATA] = 0o644
        builder.run(['cp', '--sparse=always', '--reflink=auto', str(source), str(builder.image)])
        if builder.image.stat().st_ino == source.stat().st_ino:
            raise RuntimeError('SOURCE_ALIAS')
        dl = builder.attach(builder.image)
        root = builder.mount(dl + 'p2', 'output-root', readonly=False)
        boot = fat_mount(builder, dl + 'p1', 'output-boot', True)
        assets = output / 'delta-assets'
        assets.mkdir()
        for name, raw in delta.items():
            target = destination(root, boot, name)
            if name != METADATA and os.path.lexists(target):
                raise RuntimeError('UNEXPECTED_EXISTING_DELTA_FILE: ' + name)
            src = assets / name.lstrip('/')
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(raw)
            builder.run(['install', '-D', '-o', 'root', '-g', 'root', '-m',
                         oct(modes[name])[2:], str(src), str(target)], privileged=True)
        link_name = '/etc/systemd/system/multi-user.target.wants/h102-network-affinity.service'
        link_value = '../h102-network-affinity.service'
        target = destination(root, boot, link_name)
        if os.path.lexists(target):
            raise RuntimeError('UNEXPECTED_EXISTING_UNIT_LINK')
        builder.run(['ln', '-s', link_value, str(target)], privileged=True)
        builder.run(['sync', '-f', str(root)], privileged=True)
        builder.unmount(boot)
        builder.unmount(root)
        builder.detach(dl)
        dl = builder.attach(builder.image, readonly=True)
        builder.run(['fsck.fat', '-v', '-n', dl + 'p1'], privileged=True)
        builder.run(['e2fsck', '-f', '-n', dl + 'p2'], privileged=True)
        root = builder.mount(dl + 'p2', 'verified-root', readonly=True)
        boot = fat_mount(builder, dl + 'p1', 'verified-boot', True)
        compare(builder, sr, root, [n.lstrip('/') for n in delta] + [link_name.lstrip('/')], 'root')
        compare(builder, sb, boot, [], 'boot')
        expected = dict(base['files'])
        expected.update({n: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                mode=modes[n]) for n, raw in delta.items()})
        verify_files(root, boot, expected)
        links = dict(base['links'], **{link_name: link_value})
        for name, value in links.items():
            path = destination(root, boot, name, allow_symlink=True)
            if not path.is_symlink() or os.readlink(path) != value:
                raise RuntimeError('UNIT_LINK_READBACK: ' + name)
        if (root / 'etc/machine-id').read_bytes() != b'':
            raise RuntimeError('SHARED_MACHINE_ID')
        keys = builder.run(['find', str(root / 'etc/ssh'), '-maxdepth', '1', '-name', 'ssh_host_*', '-print'], privileged=True)
        if keys.strip():
            raise RuntimeError('SHARED_SSH_KEYS')
        if verify_geometry(builder.image, ROOT_SECTORS) != original_mbr:
            raise RuntimeError('MBR_CHANGED')
        result = dict(schema=1, status='PASS_OFFLINE_HOTFIX_IMAGE_NOT_BOOT_OR_RELEASE',
                      version=VERSION, base_image_sha256=BASE_SHA,
                      base_manifest_sha256=BASE_MANIFEST_SHA, source_commit=commit,
                      tool_sources=source_files, image=builder.image.name,
                      bytes=builder.image.stat().st_size, sha256=digest(builder.image),
                      files=expected, links=links, files_verified=len(expected), links_verified=len(links),
                      delta_files=list(delta), boot_pins=base['boot_pins'],
                      FAT_ext4_checks=True, root_and_FAT_whitelist=True,
                      hardware_qualified=False, released=False)
        for name, expected_sha in source_files.items():
            if digest(project / name) != expected_sha:
                raise RuntimeError('TOOL_SOURCE_CHANGED: ' + name)
        if digest(source) != BASE_SHA:
            raise RuntimeError('ORIGINAL_IMAGE_CHANGED')
        (output / 'candidate.json').write_bytes(encoded(result))
        return result
    finally:
        for mount in list(reversed(builder.mounts)):
            builder.unmount(mount)
        for loop in list(reversed(builder.loops)):
            builder.detach(loop)
        for empty in builder.temp.iterdir():
            empty.rmdir()
        builder.temp.rmdir()


def main():
    """Accept a pinned regular IMG and fresh project output, without device-write or release options."""
    parser = argparse.ArgumentParser(description='Build an H102 network IRQ image candidate')
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = build(args.source.absolute(), args.output.absolute(), Path(__file__).resolve().parents[1])
    print(json.dumps({key: result[key] for key in ('status', 'version', 'bytes', 'sha256', 'files_verified')}))


if __name__ == '__main__':
    main()
# End of file: build_h102_irq_hotfix_image.py
