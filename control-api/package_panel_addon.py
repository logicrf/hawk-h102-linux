#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file package_panel_addon.py
@brief Package the matched panel inputs and API, then extract and verify every file.
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
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from panel_transaction import TARGETS


def sha(path):
    """Return the full SHA-256 of an ordinary input; reject symlinks and missing files."""
    if path.is_symlink() or not path.is_file():raise ValueError('PACKAGE_REGULAR_FILE_REQUIRED')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    """Return the exact ordinary-file hash map; reject symlinks and special files."""
    result={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError('PACKAGE_SYMLINK')
        if p.is_file():result[str(p.relative_to(root))]=sha(p)
    return result


def build(inputs,api,output):
    """Validate fixed ordinary inputs, generate a new output, and independently verify the result.

    Preserve failures and release only resources created by this invocation. This does not qualify a physical SD boot."""
    info=json.loads((inputs/'inputs.json').read_text());sdk=json.loads((inputs/'h102-usb-sdk.lock.json').read_text())
    firmware=json.loads((inputs/'h102-firmware.lock.json').read_text())
    api_manifest=json.loads((api/'manifest.json').read_text());assets=json.loads((api/'assets.json').read_text())
    if tree(api)!={**assets,'assets.json':sha(api/'assets.json')}:raise ValueError('PACKAGE_API_ASSETS')
    if api_manifest['sdk_sources']!=sdk['files'] or api_manifest['firmware']!=firmware:
        raise ValueError('PACKAGE_API_SDK_FIRMWARE_PAIR')
    if api_manifest['service_version']!='0.1.0-ip36-panel1' or set(info['changes'])!=TARGETS:
        raise ValueError('PACKAGE_API_VERSION_OR_TARGETS')
    for name,row in info['changes'].items():
        if sha(inputs/'overlay'/name.lstrip('/'))!=row['after']:raise ValueError('PACKAGE_OVERLAY_SHA')
    source=Path(__file__).parent;repo=source.parent
    tracked=subprocess.check_output(['git','-C',str(repo),'ls-files','-z'],text=True).split('\0')
    provenance=dict(commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),
        dirty=bool(subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True)),
        api_manifest_sha256=sha(api/'manifest.json'))
    if provenance['dirty']:raise ValueError('PACKAGE_REQUIRES_COMMITTED_LINUX_SOURCE')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(inputs/'overlay',output/'overlay');shutil.copytree(api,output/'api')
    for name in ('install_panel_addon.py','panel_transaction.py','panel_preflight.py'):
        shutil.copyfile(source/name,output/name)
    baseline=json.loads((source/'panel-base-sdk.lock.json').read_text())
    manifest=dict(schema=1,version=info['version'],qualification='INCREMENTAL_ADDON_NOT_COMPLETE_IMAGE_RELEASE',
        files=tree(output),changes=info['changes'],original_sdk=baseline['files'],candidate_sdk=sdk['files'],
        base_kernel=firmware['kernel'],base_boot_pins=dict(firmware['boot_pins'],**{
            '/boot/h102_logicrf_master.bit':info['changes']['/boot/h102_logicrf_master.bit']['before']}),
        api_files=tree(api),original_api_files=info['original_api_files'],
        original_unit_sha256=info['original_unit_sha256'],provenance=provenance)
    (output/'package.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=output.parent/(output.name+'.tar.xz')
    with tarfile.open(archive,'x:xz',preset=6) as tar:tar.add(output,arcname=output.name)
    restore=output.parent/(output.name+'-restored');restore.mkdir(exist_ok=False)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if Path(member.name).is_absolute() or '..' in Path(member.name).parts or not(member.isfile() or member.isdir()):
                raise ValueError('PACKAGE_UNSAFE_ARCHIVE_MEMBER')
        tar.extractall(restore)
    if tree(restore/output.name)!=tree(output):raise ValueError('PACKAGE_RESTORED_FULL_SHA')
    receipt=dict(status='PASS_PACKAGE_REAL_RESTORE_FULL_SHA_NOT_HARDWARE',files=len(manifest['files']),
        package_sha256=sha(output/'package.json'),archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,
        provenance=provenance)
    (output.parent/(output.name+'-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser=argparse.ArgumentParser()
    for name in ('inputs','api','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.inputs,args.api,args.output)))


if __name__=='__main__':main()
# End of file: package_panel_addon.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
