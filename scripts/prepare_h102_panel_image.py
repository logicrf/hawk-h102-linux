#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file prepare_h102_panel_image.py
@brief Prepare device-independent full-image assets from the reviewed panel inputs.
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
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

VERSION = '1.2.1-rc2'
BASE_SHA = '22b21bf4deb2a66b7bfc2c57cca34797e475252c7d6c7a14b28a981c536f978d'
BASE_MANIFEST_SHA = '98acca70039c8119b5cada0f8a561c70b931960fda364f0de38922e28cd11b11'
PANEL_METADATA = '4341109181b16f9f84611af9d592ea54acf5d3356fbad9e76030b5a3cc178bc8'
PANEL_API_MANIFEST = '031024c436a52b3c6eb1a0b4a2fd6b1293fce9c176f7292bc85dd6ea42452b63'
BIT_SHA = 'd6a2412cd32c767b29f08b077f9ee3eae159a5bf1188417db243e55ab33e3eff'
API_TARGET = '/usr/local/lib/h102/control-api/0.1.0-ip36-panel1'
METADATA = '/etc/h102/sdk1-image.json'
API_DIRECTORY_MODES = {API_TARGET+suffix: 0o700 for suffix in ('', '/bundle', '/h102_control')}
"""Accept only the reviewed panel inputs and exact 1.2.0 base; filenames do not establish identity."""


def sha(path):
    """Return the full SHA-256 of an ordinary input; reject symlinks and missing files."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('PANEL_IMAGE_REGULAR_FILE_REQUIRED:'+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    """Write deterministic JSON inside the new output tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')


def unit_text(assets_sha):
    """Create the fixed systemd unit; do not bind it to a device identity."""
    return f'''[Unit]
Description=LogicRF H102 device control API
After=network-online.target h102-sdk1-bootstrap.service
Wants=network-online.target
Requires=h102-sdk1-bootstrap.service
[Service]
Type=simple
User=root
UMask=0077
Environment=PYTHONNOUSERSITE=1
Environment=PYTHONPATH={API_TARGET}
WorkingDirectory={API_TARGET}
ExecStartPre=/usr/bin/python3 -B {API_TARGET}/image_api_preflight.py --assets-sha256 {assets_sha}
ExecStart=/usr/bin/python3 -B -m h102_control --root {API_TARGET}
Restart=no
TimeoutStopSec=160
KillMode=process
[Install]
WantedBy=multi-user.target
'''


def prepare(inputs, output, project):
    """Validate all fixed input identities before preparing a new stage.

    Preserve production state paths and exact SDK/API checks. Never modify input files or operate a device."""
    base_path = project/'docs/receipts/20261015-common-lo-rc2-image-candidate.json'
    if (sha(base_path) != BASE_MANIFEST_SHA
            or sha(inputs/'overlay/etc/h102/sdk1-image.json') != PANEL_METADATA
            or sha(inputs/'overlay/boot/h102_logicrf_master.bit') != BIT_SHA
            or sha(inputs/'api/manifest.json') != PANEL_API_MANIFEST):
        raise ValueError('PANEL_IMAGE_INPUT_PINS')
    base = json.loads(base_path.read_text())
    sdk = json.loads((inputs/'h102-usb-sdk.lock.json').read_text())
    if {p.name: sha(p) for p in (inputs/'sdk').glob('*.py')} != sdk['files'] or len(sdk['files']) != 108:
        raise ValueError('PANEL_IMAGE_COMPLETE_SDK')
    api_assets = json.loads((inputs/'api/assets.json').read_text())
    if {str(p.relative_to(inputs/'api')): sha(p) for p in (inputs/'api').rglob('*') if p.is_file()} != dict(
            api_assets, **{'assets.json': sha(inputs/'api/assets.json')}):
        raise ValueError('PANEL_IMAGE_API_ASSETS')
    commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(project), 'status', '--porcelain'], text=True):
        raise ValueError('PANEL_IMAGE_COMMITTED_SOURCE_REQUIRED')
    output.mkdir(parents=True, exist_ok=False)
    assets = output/'assets'
    assets.mkdir()
    files = dict(base['files'])
    delta = {}

    def add(target, raw, mode=0o644):
        """Stage one canonical ordinary file and check Python 3.9 syntax where applicable."""
        if not target.startswith('/') or '..' in Path(target).parts:
            raise ValueError('PANEL_IMAGE_ASSET_PATH')
        if target.endswith('.py'):
            ast.parse(raw, filename=target, feature_version=(3, 9))
        path = assets/target.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        row = dict(bytes=len(raw), sha256=sha(path), mode=mode)
        files[target] = delta[target] = row

    add('/boot/h102_logicrf_master.bit', (inputs/'overlay/boot/h102_logicrf_master.bit').read_bytes())
    changed_sdk = []
    for name, digest in sdk['files'].items():
        target = '/usr/local/lib/h102/sdk1/scripts/'+name
        if base['files'][target]['sha256'] != digest:
            add(target, (inputs/'sdk'/name).read_bytes())
            changed_sdk.append(name)
    if set(changed_sdk) != {'h102_profile_config.py', 'h102_runtime_profile.py',
                            'h102_runtime_usb_prepare.py', 'h102_runtime_usb_rx.py'}:
        raise ValueError('PANEL_IMAGE_EXACT_FOUR_SDK_DELTA')
    metadata = json.loads((inputs/'overlay/etc/h102/sdk1-image.json').read_text())
    metadata.update(version=VERSION, status='CANDIDATE_PANEL_FULL_IMAGE_NOT_COLD_BOOT_QUALIFIED',
                    source_commit=commit, image_recipe_commit=commit, base_image_sha256=BASE_SHA)
    metadata['panel_addon']['qualification'] = 'PERSISTENT_UPGRADE_VALIDATED; NEW_FULL_IMAGE_COLD_BOOT_PENDING'
    metadata['image_integration'] = dict(version=VERSION, device_control_api='0.1.0-ip36-panel1',
        base_release='1.2.0', no_per_device_install_transaction=True)
    if metadata['assets'] != {k: v for k, v in files.items() if k != METADATA}:
        raise ValueError('PANEL_IMAGE_SDK_METADATA_ASSETS')
    add(METADATA, (json.dumps(metadata, indent=2)+'\n').encode())
    firmware = json.loads((inputs/'h102-firmware.lock.json').read_text())
    firmware.update(version=VERSION, metadata_sha256=delta[METADATA]['sha256'])
    firmware['image_integration'] = metadata['image_integration']
    write_json(output/'h102-firmware.lock.json', firmware)
    sdk.update(firmware_release=VERSION, input_directory=VERSION)
    write_json(output/'h102-usb-sdk.lock.json', sdk)
    api = output/'api'
    shutil.copytree(inputs/'api', api)
    shutil.copyfile(project/'control-api/image_api_preflight.py', api/'image_api_preflight.py')
    manifest = json.loads((api/'manifest.json').read_text())
    manifest['firmware'] = firmware
    manifest['image_provenance'] = dict(version=VERSION, source_commit=commit, base_raw_sha256=BASE_SHA)
    write_json(api/'manifest.json', manifest)
    write_json(api/'assets.json', {str(p.relative_to(api)): sha(p) for p in sorted(api.rglob('*'))
        if p.is_file() and p.name != 'assets.json'})
    for p in sorted(api.rglob('*')):
        if p.is_file():
            add(API_TARGET+'/'+str(p.relative_to(api)), p.read_bytes(), 0o600)
    add('/etc/systemd/system/h102-control-api.service', unit_text(sha(api/'assets.json')).encode())
    links = dict(base['links'], **{
        '/etc/systemd/system/multi-user.target.wants/h102-control-api.service': '../h102-control-api.service'})
    result = dict(schema=1, status='PREPARED_FULL_IMAGE_ASSETS_NOT_COLD_BOOT_QUALIFIED',
        version=VERSION, source_commit=commit, base_raw_sha256=BASE_SHA,
        base_manifest_sha256=BASE_MANIFEST_SHA, kernel=base['kernel'], files=files,
        delta_files=delta, directories=API_DIRECTORY_MODES, links=links, boot_pins=firmware['boot_pins'],
        sdk_changes=sorted(changed_sdk), api_assets_sha256=sha(api/'assets.json'),
        tools={name: sha(project/name) for name in ('scripts/prepare_h102_panel_image.py',
            'scripts/build_h102_panel_image.py', 'control-api/image_api_preflight.py',
            'scripts/compact_h102_image.py', 'scripts/build_h102_sdk1_image.py',
            'scripts/build_h102_irq_hotfix_image.py', 'scripts/build_h102_driver_fix_image.py')})
    write_json(output/'asset-delta.json', result)
    return result


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--panel-inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.panel_inputs.resolve(), args.output.resolve(), Path(__file__).resolve().parents[1])
    print(json.dumps({k: result[k] for k in ('status', 'version', 'source_commit', 'sdk_changes')}))


if __name__ == '__main__':
    main()
# End of file: prepare_h102_panel_image.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
