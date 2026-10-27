#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file prepare_panel_inputs.py
@brief Prepare the exact panel SDK, bitstream and independent API installation.
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
from pathlib import Path
import shutil

from prepare_hotmeta_inputs import sha, replace, write_json
from panel_transaction import TARGETS

BASE_BIT = 'efa68686339a902c5aa6ffcd36db9f4e769b9dd5c796dcea75b6928f66fa33a2'
NEW_BIT = 'd6a2412cd32c767b29f08b077f9ee3eae159a5bf1188417db243e55ab33e3eff'
BASE_METADATA = 'b7938d4b25fd141855da005c6f6bd3746ed39a5d022550e4e6f96704429d411c'
BASE_API = 'ec268dd35016b1c5876077f6550e34dbc88da99cc00034b4118eb4afbc4ce66b'
VERSION = '1.2.0-panel-1'
COMPILED = '134a61febce9d9ddf831609c252a017d033ddaf3'
ROUTED = '9ea7a88949116fd2124b0701a9974e1467cfd57cac2aeb291c6f3c5353980912'
"""Fixed reviewed design/output identities; never infer compatibility from arbitrary inputs."""


def tree(root):
    """Return the exact ordinary-file hash map; reject symlinks and special files."""
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError('PANEL_NONREGULAR_INPUT')
        if p.is_file():
            result[str(p.relative_to(root))] = sha(p)
    return result


def prepare(sdk, metadata, bit, firmware, api, unit, output):
    """Validate all fixed input identities before preparing a new stage.

    Preserve production state paths and exact SDK/API checks. Never modify input files or operate a device."""
    baseline = json.loads((Path(__file__).parent/'panel-base-sdk.lock.json').read_text())
    actual = {p.name: sha(p) for p in sdk.glob('*.py')}
    pins = json.loads(firmware.read_text())
    original = json.loads(metadata.read_text())
    api_manifest = json.loads((api/'manifest.json').read_text())
    assets = json.loads((api/'assets.json').read_text())
    original_api = tree(api)
    if (actual != baseline['files'] or sha(metadata) != BASE_METADATA or sha(bit) != NEW_BIT
            or sha(api/'manifest.json') != BASE_API):
        raise ValueError('PANEL_BASE_INPUT_MISMATCH')
    if original_api != dict(assets, **{'assets.json': sha(api/'assets.json')}):
        raise ValueError('PANEL_API_ASSET_MISMATCH')
    if (pins != api_manifest['firmware'] or pins['metadata_sha256'] != BASE_METADATA
            or pins['boot_pins'] != original['boot_pins']
            or pins['boot_pins']['/boot/h102_logicrf_master.bit'] != BASE_BIT
            or api_manifest['sdk_sources'] != actual):
        raise ValueError('PANEL_BASE_PAIR_MISMATCH')
    config = (sdk/'h102_profile_config.py').read_text()
    if 'ACTIVE_BIT_RECORD = None' not in config:
        raise ValueError('PANEL_TEMPORARY_LOADING_RECORD_FORBIDDEN')
    unit_raw = unit.read_text()
    if ('WorkingDirectory=/usr/local/lib/h102/control-api/0.1.0-ip36\n' not in unit_raw
            or '/var/lib/h102/grc-hotmeta-1/package/hotmeta_preflight.py' not in unit_raw):
        raise ValueError('PANEL_BASE_UNIT')
    output.mkdir(parents=True, exist_ok=False)
    full = output/'sdk'
    shutil.copytree(sdk, full, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    overlay = output/'overlay'
    changes = {}
    for name in ('h102_profile_config.py', 'h102_runtime_usb_prepare.py', 'h102_runtime_usb_rx.py'):
        text = replace((sdk/name).read_text(), BASE_BIT, NEW_BIT)
        compile(text, name, 'exec')
        (full/name).write_text(text)
        target = '/usr/local/lib/h102/sdk1/scripts/'+name
        staged = overlay/target.lstrip('/')
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(text)
        changes[target] = dict(before=actual[name], after=sha(staged))
    boot = overlay/'boot/h102_logicrf_master.bit'
    boot.parent.mkdir()
    shutil.copyfile(bit, boot)
    changes['/boot/h102_logicrf_master.bit'] = dict(before=BASE_BIT, after=NEW_BIT)
    updated = json.loads(metadata.read_text())
    updated['boot_pins']['/boot/h102_logicrf_master.bit'] = NEW_BIT
    for target, change in changes.items():
        row = updated['assets'][target]
        if row['sha256'] != change['before']:
            raise ValueError('PANEL_BASE_ASSET_SHA:'+target)
        row.update(sha256=change['after'], bytes=(overlay/target.lstrip('/')).stat().st_size)
    updated['panel_addon'] = dict(version=VERSION, compiled_commit=COMPILED,
        routed_sha256=ROUTED, bit_sha256=NEW_BIT,
        mapping=dict(S0='XS4.LED3/AD24 heartbeat 1Hz', S1='XS4.LED2/AF25 IQ activity 4Hz'),
        qualification='TEMPORARY_BIT_VALIDATED; DEFAULT_SD_UPGRADE_NOT_YET_VALIDATED')
    meta = overlay/'etc/h102/sdk1-image.json'
    meta.parent.mkdir(parents=True)
    write_json(meta, updated)
    changes['/etc/h102/sdk1-image.json'] = dict(before=BASE_METADATA, after=sha(meta))
    assert set(changes) == TARGETS
    new_sdk = dict(baseline, firmware_release=VERSION, input_directory=VERSION,
                   files={p.name: sha(p) for p in full.glob('*.py')})
    new_pins = dict(pins, version='1.2.0+panel-1', metadata_sha256=sha(meta),
        boot_pins=updated['boot_pins'], panel_addon=dict(version=VERSION,
        compiled_commit=COMPILED, routed_sha256=ROUTED, bit_sha256=NEW_BIT))
    write_json(output/'h102-usb-sdk.lock.json', new_sdk)
    write_json(output/'h102-firmware.lock.json', new_pins)
    new_api = output/'api'
    shutil.copytree(api, new_api)
    capture = new_api/'bundle/board_capture.py'
    capture.write_text(replace(capture.read_text(), 'SUPPORTED_BIT_SHA256 = frozenset((BIT_SHA256,',
                              "SUPPORTED_BIT_SHA256 = frozenset((BIT_SHA256,\n    '"+NEW_BIT+"',"))
    capture.write_text(capture.read_text().replace('\u53ea\u63a5\u53d7\u539fD81\u53ca\u5df2\u6838\u5bf9\u540c\u4e00ADI ADC\u5730\u5740/\u7248\u672c/\u6ea2\u51faABI\u7684cap3\u4f4d\u6d41\u3002',
        '\u53ea\u63a5\u53d7D81/EFA\u53ca\u5df2\u6838\u5bf9\u76f8\u540cADC\u5730\u5740\u3001\u7248\u672c\u3001\u6ea2\u51faABI\u7684\u9762\u677fd6\u4f4d\u6d41\u3002'))
    compile(capture.read_text(), str(capture), 'exec')
    api_manifest.update(service_version='0.1.0-ip36-panel1', sdk_sources=new_sdk['files'],
                        firmware=new_pins)
    api_manifest['sources']['board_capture.py'] = sha(capture)
    api_manifest['panel_provenance'] = dict(base_api_sha256=BASE_API, compiled_commit=COMPILED)
    write_json(new_api/'manifest.json', api_manifest)
    assets = {k: sha(new_api/k) for k in assets}
    write_json(new_api/'assets.json', assets)
    result = dict(status='PREPARED_PANEL_INPUTS_DEFAULT_BOOT_NOT_YET_VALIDATED',
        version=VERSION, changes=changes, sdk_files=len(actual), compiled_commit=COMPILED,
        routed_sha256=ROUTED, original_api_files=original_api, original_unit_sha256=sha(unit))
    write_json(output/'inputs.json', result)
    return result


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser = argparse.ArgumentParser()
    for name in ('sdk', 'metadata', 'bit', 'firmware', 'api', 'unit', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(**vars(args))))


if __name__ == '__main__':
    main()
# End of file: prepare_panel_inputs.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
