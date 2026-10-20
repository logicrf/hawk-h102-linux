#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       prepare_h102_common_lo_assets.py
@brief      Assemble auditable image delta assets from pinned kernel and shared-LO inputs.
@details    Do not access boards or SD. Verify kernel, profile/stream and tested source hashes,
            adapt fixed boot bindings and generate the complete asset and delta manifests.
            Asset preparation remains a candidate and does not replace exact-image boot qualification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from build_h102_irq_hotfix_image import encoded

ROOT=Path(__file__).resolve().parents[1]
BASE_META='docs/receipts/20261015-common-lo-baseline-sdk1-metadata.json'
BASE_META_SHA='4654fab97e0898548c8e1aaf3e2b0211ebc928cfc314cbc5999896a19f6a3b4d'
DRIVER_MANIFEST='docs/receipts/20261014-second-h102-image-candidate.json'
KERNEL_ARCHIVE='build-inputs/h102-sharedlo1-bbcdf343.tar.gz'
KERNEL_ARCHIVE_SHA='bbcdf3431838dd000cfa48be65fa64d19655686b386a42339f9998ba32b0ef84'
KERNEL='6.6.0-h102-sdk1-candidate-calfix1-regbounds1-sharedlo1'
SCRIPTS='/usr/local/lib/h102/sdk1/scripts'
CATALOG='/usr/local/lib/h102-config-sdk1/profiles'
APPROVED='/etc/h102/h102-built-in-sdk1-presets.json'
METADATA='/etc/h102/sdk1-image.json'
VERSION='1.2.0-rc2'
DELTA_FILE_COUNT=234
"""Shared assembler layout: 25 kernel files, four scripts, 203 profile files, catalog and metadata."""
"""Pin tested kernel and paths; adapt regular files without copying live-card state."""


def sha(raw):
    """Hash complete input bytes with SHA-256."""
    return hashlib.sha256(raw).hexdigest()


def prepare(qualification,output):
    """Validate every input before creating a new directory, retaining originals and adapted hashes."""
    if output.exists() or output.is_symlink():raise ValueError('FRESH_OUTPUT_REQUIRED')
    qraw=qualification.read_bytes();q=json.loads(qraw)
    if q.get('status')!='PASS_SCOPED_29_COMMON_NATIVE_CONTROL_FINITE_RF_AND_RECOVERY':
        raise ValueError('COMMON_BOARD_QUALIFICATION_REQUIRED')
    if q.get('kernel')!=KERNEL:raise ValueError('EXACT_SHARED_KERNEL_QUALIFICATION')
    requested=json.loads((ROOT/'profiles/requests/h102-common-lo-sdk1-presets.json').read_bytes())
    ids=[p['id'] for p in requested['profiles']]
    if len(ids)!=29 or set(q['qualified_profile_sha256'])!=set(ids):raise ValueError('EXACT_29_COMMON_QUALIFICATION')
    scripts=('h102_profile_config.py','h102_profile_iio_broker.py','h102_rf_owner.py')
    for name in scripts:
        if sha((ROOT/'scripts'/name).read_bytes())!=q['source_sha256']['scripts/'+name]:
            raise ValueError('SOURCE_CHANGED_SINCE_NATIVE_STACK_FREEZE: '+name)
    metadata_raw=(ROOT/BASE_META).read_bytes()
    if sha(metadata_raw)!=BASE_META_SHA:raise ValueError('BASE_METADATA_PIN')
    metadata=json.loads(metadata_raw);driver=json.loads((ROOT/DRIVER_MANIFEST).read_bytes())
    if driver['sha256']!='be006c211d1300a24529e15de8d3f10e5561ca662c35f3abe08bec50c4b68167':
        raise ValueError('BASE_DRIVER_MANIFEST_PIN')
    archive=ROOT/KERNEL_ARCHIVE
    if archive.is_symlink() or sha(archive.read_bytes())!=KERNEL_ARCHIVE_SHA:raise ValueError('KERNEL_ARCHIVE_PIN')
    new_driver=json.loads((ROOT/'manifests/h102-sdk1-sharedlo1-candidate.json').read_bytes())
    fit=new_driver['artifacts']['boot-candidate/image-sdk1-sharedlo1.ub']
    wanted={'/boot/image-sdk1.ub':dict(fit,mode=0o644)}
    for name,e in new_driver['modules'].items():
        if not name.startswith('modules-stage/lib/modules/'+KERNEL+'/'):raise ValueError('NEW_MODULE_KERNEL')
        wanted['/usr/'+name.removeprefix('modules-stage/')]=dict(e,mode=0o644)
    if len(wanted)!=25:raise ValueError('EXACT_25_KERNEL_ARTIFACTS')
    # The base is 1.1.1, not the hot-updated card containing the previous 24 regbounds1 modules.
    old_prefix='/usr/lib/modules/6.6.0-h102-sdk1-candidate-calfix1-regbounds1/'
    metadata['assets']={n:e for n,e in metadata['assets'].items() if not n.startswith(old_prefix)}
    metadata.update(kernel=KERNEL,
        fdd_shared_lo=dict(status='PASS_SCOPED_PRIVATE_NATIVE_CONTROL_FINITE_RF',
            patch_sha256=new_driver['driver']['patch_sha256'],
            driver_sha256=new_driver['driver']['after_sha256'],qualification_sha256=sha(qraw)))
    metadata['boot_pins']['/boot/image-sdk1.ub']=fit['sha256']
    assets={};modes={};adaptations={}
    def add(name,raw,mode=0o644):
        """Reject duplicates and path traversal; use canonical absolute product paths."""
        p=Path(name)
        if not p.is_absolute() or '..' in p.parts or str(p)!=name or name in assets:
            raise ValueError('ASSET_PATH_OR_DUPLICATE: '+name)
        assets[name]=raw;modes[name]=mode
    with tarfile.open(archive,'r:gz') as tar:
        members={m.name:m for m in tar.getmembers()}
        for name,expected in wanted.items():
            member=members[name.lstrip('/')]
            if not member.isfile():raise ValueError('KERNEL_MEMBER_KIND')
            stream=tar.extractfile(member);raw=stream.read()
            if len(raw)!=expected['bytes'] or sha(raw)!=expected['sha256']:raise ValueError('KERNEL_MEMBER_SHA')
            add(name,raw,expected['mode'])
    pins=metadata['boot_pins']
    for name in scripts+('h102_runtime_profile.py',):
        original=(ROOT/'scripts'/name).read_bytes();raw=original
        if name=='h102_profile_config.py':
            text=raw.decode();start=text.index('BOOT_PINS = {\n');end=text.index('\n}\n',start)+3
            text=text[:start]+'BOOT_PINS = '+repr(pins)+text[end:]
            for before,after in {"KERNEL = '6.6.0-h102-sdk1-candidate+'":'KERNEL = '+repr(KERNEL),
                    'a504c57e3c2e0d3883c57e007087977f22609397b8cdd7ba089fc4265ee001f1':pins['/boot/image-sdk1.ub']}.items():
                if text.count(before)!=1:raise ValueError('CONFIG_ADAPTATION_COUNT')
                text=text.replace(before,after)
            raw=text.encode()
        ast.parse(raw,feature_version=(3,9));add(SCRIPTS+'/'+name,raw)
        adaptations[name]=dict(source_sha256=sha(original),product_sha256=sha(raw))
    for profile_id in ids:
        folder=ROOT/'profiles/sdk1-common-candidate'/profile_id
        manifest=json.loads((folder/'manifest.json').read_bytes())
        if manifest['sha256']!=q['qualified_profile_sha256'][profile_id]:raise ValueError('QUALIFIED_PROFILE_CHANGED')
        for name in ('profile.json','stream.bin'):
            if sha((folder/name).read_bytes())!=manifest['sha256'][name]:raise ValueError('PROFILE_SOURCE_SHA')
        manifest['qualification'].update(configuration_load='passed_h102_sdk1_common_mode_matrix_20261015',
            iio='passed_finite_1ghz_two_rx_iq_not_continuous',rf='passed_finite_1ghz_fixed_loop_not_absolute',
            board_qualified=False,qualification_receipt_sha256=sha(qraw))
        for p in folder.iterdir():
            if p.is_file():add(CATALOG+'/'+profile_id+'/'+p.name,encoded(manifest) if p.name=='manifest.json' else p.read_bytes())
    approved=(ROOT/'profiles/requests/h102-built-in-dual-lo-mode-sdk1-presets.json').read_bytes()
    if len(json.loads(approved)['profiles'])!=58:raise ValueError('EXACT_58_PHYSICAL_PACKAGES')
    add(APPROVED,approved)
    for name,raw in assets.items():metadata['assets'][name]=dict(bytes=len(raw),sha256=sha(raw),mode=modes[name])
    commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    metadata.update(base_metadata_image_recipe_commit=metadata.get('image_recipe_commit','unknown'),
        base_metadata_source_commit=metadata.get('source_commit','unknown'),
        image_recipe_commit=commit,
        version=VERSION,status='CANDIDATE_COMMON_LO_NOT_EXACT_IMAGE_BOOT_QUALIFIED',
        hardware_qualified=False,released=False,source_commit=commit,mode_integration_source_commit=commit,
        logical_profile_count=29,profile_package_count=58,rf_lo_modes=['independent','shared-lo2'],
        common_mode_qualification_sha256=sha(qraw),common_mode_source_adaptations=adaptations)
    add(METADATA,encoded(metadata))
    final_files={n:e for n,e in driver['files'].items() if not n.startswith(old_prefix)}
    for name,raw in assets.items():final_files[name]=dict(bytes=len(raw),sha256=sha(raw),mode=modes[name])
    if len(assets)!=DELTA_FILE_COUNT or len(final_files)!=587 or len(metadata['assets'])!=586:
        raise ValueError('EXACT_DELTA_AND_FINAL_ASSET_COUNT')
    result=dict(schema=1,status='PASS_OFFLINE_COMMON_LO_ASSETS_NOT_IMAGE_OR_BOARD',version=VERSION,
        kernel=KERNEL,source_commit=commit,base_image_sha256=driver['base_image_sha256'],
        qualification_sha256=sha(qraw),baseline_metadata_sha256=BASE_META_SHA,
        kernel_archive_sha256=KERNEL_ARCHIVE_SHA,files=final_files,
        delta_files={n:final_files[n] for n in assets},links=driver['links'],boot_pins=pins,
        source_adaptations=adaptations,logical_profile_count=29,profile_package_count=58,
        tool_sources={n:sha((ROOT/'scripts'/n).read_bytes()) for n in ('prepare_h102_common_lo_assets.py',
            'build_h102_common_lo_image.py','compact_h102_image.py','build_h102_sdk1_image.py',
            'build_h102_irq_hotfix_image.py','build_h102_driver_fix_image.py')})
    output.mkdir(parents=True)
    for name,raw in assets.items():
        dest=output/'assets'/name.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    (output/'asset-delta.json').write_bytes(encoded(result));(output/'qualification.json').write_bytes(qraw)
    return result


def main():
    """Build a new directory from an explicit qualification receipt, not live device identity."""
    p=argparse.ArgumentParser();p.add_argument('--qualification',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=prepare(args.qualification,args.output)
    print(json.dumps({k:result[k] for k in ('status','version','logical_profile_count','profile_package_count')}))


if __name__=='__main__':main()

# End of file: prepare_h102_common_lo_assets.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
