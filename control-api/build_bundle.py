#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file build_bundle.py
@brief Build a pinned control-service add-on from explicit H102 source and SDK inputs.
@details Create a new local directory, record source hashes and reject incomplete SDK inputs.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-17
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).parent))
from h102_control.native import ENTRY_SOURCES


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """Use explicit input paths and record board-helper and GUI/GNU Radio source identities."""
    parser=argparse.ArgumentParser();parser.add_argument('--version',default='0.1.0-ip5')
    for name in ('gui','gr','sdk','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output
    sdk=json.loads((args.gr/'docs/h102-usb-sdk.lock.json').read_text())['files']
    if {p.name:digest(p) for p in args.sdk.glob('*.py')}!=sdk:raise ValueError('SDK_PIN_MISMATCH')
    root.mkdir(mode=0o700,parents=False,exist_ok=False);(root/'bundle').mkdir(mode=0o700)
    shutil.copytree(Path(__file__).parent/'h102_control',root/'h102_control',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    names=set().union(*map(set,ENTRY_SOURCES.values()))|{'usb_runtime_candidate.py','gr_usb_radio.py','runtime_archive.py','iio_runtime_archive.py','usb_rx_reuse_candidate.py','gr_usb_reuse.py'}
    sources={}
    for name in sorted(names):
        source=(args.gr/'python/logicrf'/('board_usb_radio.py' if name=='gr_usb_radio.py' else name)
                if (args.gr/'python/logicrf'/('board_usb_radio.py' if name=='gr_usb_radio.py' else name)).is_file()
                else args.gui/'h102_iio_demo'/name)
        shutil.copyfile(source,root/'bundle'/name);sources[name]=digest(source)
    provenance={}
    for name,path in (('linux',Path(__file__).resolve().parents[1]),('gui',args.gui),('gr',args.gr)):
        provenance[name]=dict(base_commit=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip(),
                              source_tree=str(path.resolve()),worktree_dirty=bool(subprocess.check_output(['git','-C',str(path),'status','--porcelain'],text=True)))
    manifest=dict(schema=1,service_version=args.version,sources=sources,sdk_sources=sdk,
                  profiles=json.loads((args.gr/'docs/h102-profiles.json').read_text())['profiles'],
                  firmware=json.loads((args.gr/'docs/h102-firmware.lock.json').read_text()),provenance=provenance)
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    assets={str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'assets.json').write_text(json.dumps(assets,indent=2)+'\n')
    for path in (root,*root.rglob('*')):path.chmod(0o700 if path.is_dir() else 0o600)
    print(json.dumps(dict(directory=str(root),assets=len(assets),assets_sha256=digest(root/'assets.json'))))

if __name__=='__main__':main()
# End of file: build_bundle.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
