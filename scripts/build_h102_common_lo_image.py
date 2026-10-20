#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       build_h102_common_lo_image.py
@brief      Install verified shared-LO assets into a copy of the exact 1.1.1 image.
@details    Keep inputs read-only and verify hashes, module versions, boot bindings,
            first-boot identity, filesystem health and allowed changes; preserve failure evidence.
            No SD or live-card access occurs; offline completion is not board qualification or release.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
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
from build_h102_driver_fix_image import check_firstboot
from prepare_h102_common_lo_assets import KERNEL, VERSION, METADATA, DELTA_FILE_COUNT

BASE_BYTES=11823742976
BASE_SHA='d5ffd1b34440219893d74d5f363915df4424336e29e5c987745490463d369088'
BASE_MANIFEST='docs/receipts/20261012-network-iiod-rc2-image-candidate.json'
BASE_MANIFEST_SHA='e1d0d6786c2206d6289c2237fba27f8ce7e4885f7370f4d31a997017768e44d1'
"""Pin the base IMG and 360 assets; writable loop devices belong only to a new copy."""


def build(source: Path, stage: Path, output: Path, project: Path) -> dict:
    """Validate all inputs before output creation and independently verify after unmounting."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size!=BASE_BYTES:
        raise ValueError('REGULAR_PINNED_BASE_IMAGE_REQUIRED')
    if stage.is_symlink() or not stage.is_dir() or output.exists() or output.is_symlink():
        raise ValueError('REGULAR_STAGE_AND_FRESH_OUTPUT_REQUIRED')
    if not output.parent.is_dir():raise ValueError('OUTPUT_PARENT_REQUIRED')
    manifest=project/BASE_MANIFEST
    if digest(manifest)!=BASE_MANIFEST_SHA or digest(source)!=BASE_SHA:raise ValueError('BASE_PIN')
    raw=(stage/'asset-delta.json').read_bytes();delta=json.loads(raw);base=json.loads(manifest.read_bytes())
    if (delta['status']!='PASS_OFFLINE_COMMON_LO_ASSETS_NOT_IMAGE_OR_BOARD' or
        delta['kernel']!=KERNEL or delta['base_image_sha256']!=BASE_SHA or
        len(delta['delta_files'])!=DELTA_FILE_COUNT or len(delta['files'])!=587):
        raise ValueError('EXACT_COMMON_ASSET_MANIFEST_REQUIRED')
    if digest(stage/'qualification.json')!=delta['qualification_sha256']:raise ValueError('QUALIFICATION_PIN')
    for name,sha in delta['tool_sources'].items():
        if digest(project/'scripts'/name)!=sha:raise ValueError('TOOL_SOURCE_CHANGED: '+name)
    for name,e in delta['delta_files'].items():
        if not name.startswith('/') or '..' in Path(name).parts:raise ValueError('DELTA_PATH')
        p=stage/'assets'/name.lstrip('/')
        if (not p.resolve().is_relative_to((stage/'assets').resolve()) or p.is_symlink() or
            not p.is_file() or p.stat().st_size!=e['bytes'] or digest(p)!=e['sha256'] or
            e['mode']!=0o644):raise ValueError('DELTA_PIN: '+name)
    metadata=json.loads((stage/'assets'/METADATA.lstrip('/')).read_bytes())
    if metadata['assets']!={n:e for n,e in delta['files'].items() if n!=METADATA}:
        raise ValueError('FINAL_METADATA_ASSETS')
    if metadata['kernel']!=KERNEL or metadata['boot_pins']!=delta['boot_pins']:
        raise ValueError('KERNEL_AND_BOOT_BINDINGS')
    config=stage/'assets/usr/local/lib/h102/sdk1/scripts/h102_profile_config.py'
    tree=ast.parse(config.read_bytes(),feature_version=(3,9))
    pins=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='BOOT_PINS' for t in n.targets))
    if pins!=delta['boot_pins'] or KERNEL not in config.read_text():raise ValueError('CONFIG_BINDING')
    modules=stage/'assets/usr/lib/modules'/KERNEL
    if len(list(modules.rglob('*.ko')))!=11:raise ValueError('ELEVEN_MODULES_REQUIRED')
    for p in modules.rglob('*.ko'):
        if subprocess.check_output(['modinfo','-F','vermagic',str(p)],text=True).split()[0]!=KERNEL:
            raise ValueError('MODULE_VERMAGIC: '+str(p))
    expected=dict(base['files']);expected.update(delta['delta_files'])
    if expected!=delta['files'] or delta['links']!=base['links']:
        raise ValueError('EXACT_BASE_PLUS_DELTA_REQUIRED')
    commit=subprocess.check_output(['git','-C',str(project),'rev-parse','HEAD'],text=True).strip()
    mbr=verify_geometry(source,ROOT_SECTORS)
    output.mkdir(mode=0o700);(output/'evidence').mkdir(mode=0o700)
    (output/'asset-delta.json').write_bytes(raw)
    b=Builder(source,output,project)
    b.image=output/('LogicRF-Hawk-H102-Kuiper-'+VERSION+'-2024.1.img')
    try:
        sl=b.attach(source,readonly=True)
        sr=b.mount(sl+'p2','source-root',readonly=True)
        sb=fat_mount(b,sl+'p1','source-boot',True)
        verify_files(sr,sb,base['files']);check_firstboot(b,sr)
        b.run(['cp','--sparse=always','--reflink=auto',str(source),str(b.image)])
        if source.stat().st_ino==b.image.stat().st_ino:raise RuntimeError('SOURCE_ALIAS')
        dl=b.attach(b.image);root=b.mount(dl+'p2','output-root',readonly=False)
        boot=fat_mount(b,dl+'p1','output-boot',False)
        for name,e in delta['delta_files'].items():
            p=stage/'assets'/name.lstrip('/')
            b.run(['install','-D','-o','root','-g','root','-m',format(e['mode'],'o'),str(p),
                   str(destination(root,boot,name))],privileged=True)
        for mount in (root,boot):b.run(['sync','-f',str(mount)],privileged=True)
        b.unmount(boot);b.unmount(root);b.detach(dl)
        dl=b.attach(b.image,readonly=True)
        b.run(['fsck.fat','-v','-n',dl+'p1'],privileged=True)
        b.run(['e2fsck','-f','-n',dl+'p2'],privileged=True)
        root=b.mount(dl+'p2','verified-root',readonly=True)
        boot=fat_mount(b,dl+'p1','verified-boot',True)
        changed=delta['delta_files']
        compare(b,sr,root,[n.lstrip('/') for n in changed if not n.startswith('/boot/')],'root')
        compare(b,sb,boot,[n.removeprefix('/boot/') for n in changed if n.startswith('/boot/')],'boot')
        verify_files(root,boot,expected);check_firstboot(b,root)
        for name,target in base['links'].items():
            if os.readlink(destination(root,boot,name,allow_symlink=True))!=target:
                raise RuntimeError('BASE_LINK_CHANGED: '+name)
        for mount in list(reversed(b.mounts)):b.unmount(mount)
        for loop in list(reversed(b.loops)):b.detach(loop)
        if verify_geometry(b.image,ROOT_SECTORS)!=mbr or digest(source)!=BASE_SHA:
            raise RuntimeError('SOURCE_OR_GEOMETRY_CHANGED')
        if (stage/'asset-delta.json').read_bytes()!=raw:raise RuntimeError('STAGE_MANIFEST_CHANGED')
        for name,e in changed.items():
            if digest(stage/'assets'/name.lstrip('/'))!=e['sha256']:raise RuntimeError('STAGE_CHANGED')
        for name,sha in delta['tool_sources'].items():
            if digest(project/'scripts'/name)!=sha:raise RuntimeError('TOOL_CHANGED')
        result=dict(schema=1,status='PASS_OFFLINE_IMAGE_NOT_BOOT_OR_RELEASE',version=VERSION,
            kernel=KERNEL,image=b.image.name,bytes=b.image.stat().st_size,sha256=digest(b.image),
            base_image_sha256=BASE_SHA,base_manifest_sha256=BASE_MANIFEST_SHA,
            recipe_commit=commit,asset_source_commit=delta['source_commit'],files=expected,
            delta_files=list(changed),links=base['links'],boot_pins=delta['boot_pins'],
            files_verified=len(expected),identity_firstboot=True,FAT_ext4_checks=True,
            root_and_FAT_whitelist=True,qualification_sha256=delta['qualification_sha256'],
            hardware_qualified=False,released=False)
        (output/'candidate.json').write_bytes(encoded(result));return result
    finally:
        for mount in list(reversed(b.mounts)):b.unmount(mount)
        for loop in list(reversed(b.loops)):b.detach(loop)
        for empty in b.temp.iterdir():empty.rmdir()
        b.temp.rmdir()


def main() -> None:
    """Accept regular source images and assets plus a new output directory, never block devices."""
    p=argparse.ArgumentParser(description='Build an H102 candidate with 29 presets and two LO modes')
    p.add_argument('source',type=Path);p.add_argument('stage',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();result=build(a.source.absolute(),a.stage.absolute(),a.output.absolute(),
                                 Path(__file__).resolve().parents[1])
    print(json.dumps({k:result[k] for k in ('status','version','bytes','sha256','files_verified')}))


if __name__=='__main__':main()

# End of file: build_h102_common_lo_image.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
