#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file prepare_hotmeta_inputs.py
@brief Prepare a persistent add-on from the exact 1.2.0 SDK, metadata and reviewed bitstream.
@details Create the full SDK dependency set, six delta files and locks in a new directory.
         Do not modify device state, the original bitstream path, STATE or normal boot identity.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

BASE_METADATA = 'bb8fcb03fdc2afad42b890217d0408240b61bcc19cbd9d442378440fd7d6e95b'
BASE_BIT = 'd81b6988b5f52b2fe1e03a86ba23508d7096560a9a60e011fd17c71c199974aa'
NEW_BIT = 'efa68686339a902c5aa6ffcd36db9f4e769b9dd5c796dcea75b6928f66fa33a2'
VERSION = '1.2.0-grc-hotmeta-1'
COMPILED = '709b2d882728e820da51221a3a4aaf81eedf570d'
ROUTED = 'f3309e8b1211629fcb88ab5e18699aac66eb978ed2e0f4b09b92a28c73ba67b1'


def sha(path):
    """Hash the fixed SDK, bitstream and metadata input files completely."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace(text, old, new):
    """Allow exactly one source anchor; reject changed inputs."""
    if text.count(old) != 1:
        raise ValueError('HOTMETA_INPUT_ANCHOR:'+old[:80])
    return text.replace(old, new)


def write_json(path, value):
    """Write reproducible JSON into a caller-created output directory."""
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def prepare(sdk, metadata, bit, firmware, output):
    """Verify old inputs before generating the six-file delta; leave inputs unchanged."""
    baseline = json.loads((Path(__file__).parent/'hotmeta-base-sdk.lock.json').read_text())
    actual = {p.name: sha(p) for p in sdk.glob('*.py')}
    if actual != baseline['files'] or sha(metadata) != BASE_METADATA or sha(bit) != NEW_BIT:
        raise ValueError('HOTMETA_BASE_INPUT_MISMATCH')
    pins = json.loads(firmware.read_text())
    if pins['boot_pins']['/boot/h102_logicrf_master.bit'] != BASE_BIT or pins['metadata_sha256'] != BASE_METADATA:
        raise ValueError('HOTMETA_BASE_FIRMWARE_LOCK')
    original = json.loads(metadata.read_text())
    if original['boot_pins'] != pins['boot_pins']:
        raise ValueError('HOTMETA_METADATA_BOOT_PINS')
    output.mkdir(parents=True, exist_ok=False)
    full = output/'sdk';shutil.copytree(sdk, full, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    overlay = output/'overlay';overlay.mkdir()
    changes = {}
    for name in ('h102_profile_config.py','h102_runtime_profile.py','h102_runtime_usb_prepare.py','h102_runtime_usb_rx.py'):
        text = (sdk/name).read_text()
        if name == 'h102_profile_config.py':
            text = replace(text, BASE_BIT, NEW_BIT)
            assert 'ACTIVE_BIT_RECORD = None' in text
        elif name == 'h102_runtime_profile.py':
            text = replace(text, 'self._board.read(0x424) != 1', 'self._board.read(0x424) not in (1, 3)')
            text = replace(text, 'board.read(0x424) != 1', 'board.read(0x424) not in (1, 3)')
        else:
            text = replace(text, BASE_BIT, NEW_BIT)
            if name == 'h102_runtime_usb_prepare.py':
                text = replace(text, 'board.read(0x424)!=1', 'board.read(0x424) not in (1,3)')
        compile(text, name, 'exec');(full/name).write_text(text)
        target = '/usr/local/lib/h102/sdk1/scripts/'+name
        staged = overlay/target.lstrip('/');staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(text)
        changes[target] = dict(before=actual[name],after=sha(staged))
    boot = overlay/'boot/h102_logicrf_master.bit';boot.parent.mkdir();shutil.copyfile(bit,boot)
    changes['/boot/h102_logicrf_master.bit'] = dict(before=BASE_BIT,after=NEW_BIT)
    updated = json.loads(metadata.read_text());updated['boot_pins']['/boot/h102_logicrf_master.bit'] = NEW_BIT
    for target, change in changes.items():
        if target.startswith('/usr/local/lib/h102/sdk1/scripts/') and target not in updated['assets']:
            raise ValueError('HOTMETA_REQUIRED_SDK_ASSET_MISSING:'+target)
        if target in updated['assets']:
            row = updated['assets'][target]
            if row['sha256'] != change['before']:
                raise ValueError('HOTMETA_BASE_ASSET_SHA:'+target)
            row['sha256'] = change['after'];row['bytes'] = (overlay/target.lstrip('/')).stat().st_size
    updated['grc_addon'] = dict(version=VERSION,base_release='1.2.0',compiled_commit=COMPILED,
        routed_sha256=ROUTED,bit_sha256=NEW_BIT,qualification='CANDIDATE_PERSISTENT_INSTALL_NOT_YET_BOARD_TESTED')
    meta = overlay/'etc/h102/sdk1-image.json';meta.parent.mkdir(parents=True);write_json(meta, updated)
    changes['/etc/h102/sdk1-image.json'] = dict(before=BASE_METADATA,after=sha(meta))
    new_lock = dict(baseline,firmware_release=VERSION,input_directory=VERSION,
                    files={p.name:sha(p) for p in full.glob('*.py')})
    write_json(output/'h102-usb-sdk.lock.json',new_lock)
    new_pins = dict(pins,version='1.2.0+grc-hotmeta-1',base_release='1.2.0',
        metadata_sha256=sha(meta),boot_pins=updated['boot_pins'],
        addon=dict(version=VERSION,compiled_commit=COMPILED,routed_sha256=ROUTED,changes=changes))
    # Raw/XZ identity belongs to the unchanged base image, not to a newly built image.
    new_pins['base_image']={key:new_pins.pop(key) for key in ('raw_bytes','raw_sha256','compressed_bytes','compressed_sha256','image_filename')}
    write_json(output/'h102-firmware.lock.json',new_pins)
    result=dict(status='PREPARED_PERSISTENT_INPUTS_NOT_BOARD_QUALIFIED',version=VERSION,
                base_metadata_sha256=BASE_METADATA,changes=changes,sdk_files=len(actual),
                compiled_commit=COMPILED,routed_sha256=ROUTED)
    write_json(output/'inputs.json',result)
    return result


def main():
    """Write a new local directory without network or device access."""
    parser=argparse.ArgumentParser()
    for name in ('sdk','metadata','bit','firmware','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.sdk,args.metadata,args.bit,args.firmware,args.output)))


if __name__ == '__main__':main()
# End of file: prepare_hotmeta_inputs.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
