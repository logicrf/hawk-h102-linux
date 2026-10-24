#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_export_source_materials.py
@brief      Verify and export indexed H102 rootfs source materials with original names.
@details    Use the pinned repository manifests and an external source-review cache.
            This offline tool never downloads, extracts or executes archives and has
            no device access. Verify every distinct object before creating a new
            output. Copy by default; optional hardlinks require read-only inputs on
            the same filesystem. Fail on unsafe paths, collisions or bad hashes;
            retain any incomplete export for diagnosis. Export status describes
            material integrity, never complete corresponding-source availability.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-21
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys


MANIFEST_NAMES = (
    'h102-rootfs-source-availability-1.2.0.json',
    'h102-manual-source-provenance-1.2.0.json',
    'h102-copyright-materials-1.2.0.json',
    'h102-kuiper-1.2.0-copyright-index.json',
    'h102-rootfs-source-supplement-1.2.0.json',
    'h102-package-provenance-review-1.2.0.json',
)
"""Fixed input documents copied into each export with their exact file hashes."""


def component(value: str) -> str:
    """Validate one filename/path segment; raise ValueError before filesystem writes."""
    if (not isinstance(value, str) or not value or value in {'.', '..'}
            or any(c in value for c in '/\\\0\r\n\t')
            or value.startswith('-')):
        raise ValueError('UNSAFE_PATH_COMPONENT: ' + repr(value))
    return value


def digest(path: Path) -> str:
    """Read a regular file fully with bounded memory and return its SHA-256."""
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def plan(manifests: Path) -> tuple[list[dict], dict]:
    """Build original-name destinations from trusted-format manifests, without I/O writes.

    Reject conflicting destinations or object lengths. Debian candidates keep a
    separate directory and provenance field; unresolved entries remain explicit.
    """
    rootfs = json.loads((manifests / MANIFEST_NAMES[0]).read_text())
    manual = json.loads((manifests / MANIFEST_NAMES[1]).read_text())
    notices = json.loads((manifests / MANIFEST_NAMES[2]).read_text())
    rows = []

    def add(file: dict, cache: str, destination: str, provenance: str) -> None:
        """Append one validated material row, retaining filename and origin metadata."""
        filename = component(file['file'])
        sha = file['sha256']
        size = file['bytes']
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('INVALID_SHA256: ' + filename)
        if type(size) is not int or size < 0:
            raise ValueError('INVALID_SIZE: ' + filename)
        rows.append({'path': destination + '/' + filename, 'sha256': sha,
                     'bytes': size, 'cache': cache, 'provenance': provenance,
                     'url': file.get('url')})

    for item in rootfs['packages']:
        source, version = component(item['source']), component(item['version'])
        candidate = item['provenance'].startswith('EXACT_DEBIAN_VERSION')
        directory = ('candidates/debian/' if candidate else 'rootfs/') + source + '/' + version
        for file in item['files']:
            add(file, '1.2.0-rootfs-20261021/objects/' + file['sha256'],
                directory, item['provenance'])
    for item in rootfs['manual_components']['python_source_candidates']:
        for file in item.get('files', []):
            directory = 'candidates/python/' + component(item['name']) + '/' + component(item['version'])
            add(file, '1.2.0-rootfs-20261021/objects/' + file['sha256'], directory,
                'PYPI_SDIST_CANDIDATE_NOT_ORIGINAL_BUILD_PROOF')
    for file in manual['supplementary_inputs']['files']:
        add(file, '1.2.0-manual-20261021/' + component(file['file']), 'manual',
            'SEE_MANUAL_SOURCE_PROVENANCE_MANIFEST')
    add(notices, '1.2.0-notices-20261021/' + component(notices['file']), 'notices',
        'INDEXED_INSTALLED_COPYRIGHT_CONTENT_NOT_COMPLETE_LICENSE_AUDIT')
    destinations, objects = {}, {}
    for row in rows:
        identity = (row['sha256'], row['bytes'])
        if row['path'] in destinations and destinations[row['path']] != identity:
            raise ValueError('DESTINATION_COLLISION: ' + row['path'])
        destinations[row['path']] = identity
        if row['sha256'] in objects and objects[row['sha256']] != row['bytes']:
            raise ValueError('OBJECT_SIZE_CONFLICT: ' + row['sha256'])
        objects[row['sha256']] = row['bytes']
    rows = list({row['path']: row for row in rows}.values())
    gaps = {'missing_packaged_sources': [
        {'source': x['source'], 'version': x['version']}
        for x in rootfs['packages'] if not x['files']],
        'debian_candidate_original_raspbian_provenance_open': sum(
            x['provenance'].startswith('EXACT_DEBIAN_VERSION') for x in rootfs['packages']),
        'manual_open_items': manual['open_items']}
    return sorted(rows, key=lambda x: x['path']), gaps


def regular_input(base: Path, relative: str) -> Path:
    """Require a regular cache member with no symlink in its relative path."""
    parts = relative.split('/')
    path = base
    for part in parts:
        path = path / component(part)
        if path.is_symlink():
            raise ValueError('SYMLINK_INPUT: ' + relative)
    if not path.is_file():
        raise ValueError('MISSING_REGULAR_INPUT: ' + relative)
    return path


def export_materials(cache: Path, manifests: Path, output: Path | None,
                     hardlink: bool = False) -> dict:
    """Verify all indexed inputs, optionally write a new export and hash its copies.

    Existing output is always rejected. Hardlink mode never chmods input inodes;
    it requires read-only regular inputs. The caller must not mutate inputs while
    this single-process operation runs. Partial output is retained on failure.
    """
    rows, gaps = plan(manifests)
    if output is not None and (output.exists() or output.is_symlink()):
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    if hardlink and output is None:
        raise ValueError('HARDLINK_REQUIRES_OUTPUT')
    objects = {}
    verified_paths = set()
    for number, row in enumerate(rows, 1):
        path = regular_input(cache, row['cache'])
        if path.stat().st_size != row['bytes']:
            raise ValueError('INPUT_SIZE_MISMATCH: ' + row['cache'])
        if hardlink and path.stat().st_mode & 0o222:
            raise ValueError('HARDLINK_REQUIRES_READONLY_INPUT: ' + row['cache'])
        if path not in verified_paths:
            if digest(path) != row['sha256']:
                raise ValueError('INPUT_SHA256_MISMATCH: ' + row['cache'])
            verified_paths.add(path)
        objects[row['sha256']] = row['bytes']
        if number % 500 == 0:
            print('Verified material paths:', number, file=sys.stderr)
    report = {'schema': 1, 'status': 'PASS_INDEXED_MATERIAL_INTEGRITY_ONLY',
              'image_version': '1.2.0', 'unique_objects': len(objects),
              'unique_bytes': sum(objects.values()), 'material_paths': len(rows),
              'mode': 'verify-only' if output is None else ('readonly-hardlinks' if hardlink else 'copies'),
              'complete_system_corresponding_source': False, 'gaps': gaps,
              'files': [{k: v for k, v in row.items() if k != 'cache'} for row in rows],
              'input_manifests': {name: digest(manifests / name) for name in MANIFEST_NAMES}}
    if output is None:
        return report
    output.mkdir(parents=False, exist_ok=False)
    checksums = []
    for row in rows:
        source, target = regular_input(cache, row['cache']), output / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        if hardlink:
            os.link(source, target)
            if not os.path.samestat(source.stat(), target.stat()):
                raise ValueError('HARDLINK_IDENTITY_MISMATCH: ' + row['path'])
        else:
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            if digest(target) != row['sha256']:
                raise ValueError('OUTPUT_SHA256_MISMATCH: ' + row['path'])
            target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        checksums.append(row['sha256'] + '  ' + row['path'])
    metadata = {'SOURCE-MATERIALS.json': json.dumps(report, indent=2) + '\n',
                'README.txt': ('H102 Kuiper 1.2.0 indexed source materials\n\n'
                    'Verify: sha256sum -c SHA256SUMS\n'
                    'rootfs/: archived package source records and adjacent original-name inputs.\n'
                    'candidates/: Debian or PyPI candidates; retain their stated provenance limits.\n'
                    'manual/: retained sources and upstream candidates, described by the manual manifest.\n'
                    'notices/: installed copyright content matching the archived copyright index.\n'
                    'Nine packaged source records and further dependencies remain unresolved.\n'
                    'This collection is not complete system corresponding source or a license grant.\n'
                    'Preserve original notices in component archives. SDK, boot kit and RTL are separate.\n'
                    'Hardlink exports share read-only cache files. Copy before editing any material.\n')}
    for name in MANIFEST_NAMES:
        metadata['manifests/' + name] = (manifests / name).read_text()
    for name, text in metadata.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream:
            stream.write(text)
        checksums.append(digest(path) + '  ' + name)
    with (output / 'SHA256SUMS').open('x') as stream:
        stream.write('\n'.join(sorted(checksums)) + '\n')
    return report


def main() -> int:
    """Run offline verification/export; report validation errors without deleting evidence."""
    parser = argparse.ArgumentParser(description=__doc__.split('@brief', 1)[1].split('\n')[0].strip())
    parser.add_argument('cache', type=Path, help='source-review cache root')
    parser.add_argument('--output', type=Path, help='new export directory; omit for verification only')
    parser.add_argument('--hardlink', action='store_true', help='share read-only input inodes; same filesystem only')
    parser.add_argument('--manifests', type=Path, default=Path(__file__).resolve().parents[1] / 'manifests')
    args = parser.parse_args()
    try:
        result = export_materials(args.cache.resolve(), args.manifests.resolve(), args.output, args.hardlink)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error)}))
        return 1
    print(json.dumps({key: value for key, value in result.items() if key not in {'files', 'gaps'}}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

# End of file: h102_export_source_materials.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
