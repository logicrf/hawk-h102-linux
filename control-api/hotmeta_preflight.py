#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file hotmeta_preflight.py
@brief Check persistent add-on files, reboot identity and actual cap3 idle state.
@details Called by systemd ExecStartPre; never load a bitstream, change sources or retry.
         A pass permits API startup only and does not qualify data or RF operation.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
import argparse
import json
import mmap
import os
from pathlib import Path
import struct
import sys
import uuid
from install_hotmeta_addon import STATE,SDK,API,private,verify_package,verify_api,sdk_idle_context
import hotmeta_transaction as tx


def preflight(package_sha):
    """Require a new default boot and complete files; reject partial or same-boot installs."""
    if os.geteuid()!=0:raise PermissionError('ROOT_REQUIRED')
    os.umask(0o077);private(STATE,directory=True)
    package=STATE/'package';manifest=verify_package(package,package_sha)
    record=tx.verify_backup(STATE)
    if record['state'] not in ('FILES_INSTALLED_REBOOT_REQUIRED','ACTIVE_READY_FOR_API'):
        raise ValueError('ADDON_NOT_INSTALLED')
    identity=dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  machine_id=Path('/etc/machine-id').read_text().strip(),
                  MAC=Path('/sys/class/net/eth0/address').read_text().strip())
    old=record['identity']
    if identity['boot_id']==old['boot_id'] or any(identity[k]!=old[k] for k in ('machine_id','MAC')):
        raise ValueError('ADDON_NEW_BOOT_SAME_MACHINE_REQUIRED')
    if any('systemd.mask='+name in Path('/proc/cmdline').read_text() for name in
           ('h102-control-api.service','h102-profile-control.service')):
        raise ValueError('ADDON_DEFAULT_BOOT_REQUIRED')
    for name,row in manifest['changes'].items():
        if tx.digest(name)!=row['after']:raise ValueError('ADDON_ACTIVE_FILE_CHANGED:'+name)
    if os.uname().release!=manifest['base_kernel']:raise ValueError('ADDON_ACTIVE_KERNEL')
    if os.path.ismount(SDK):raise ValueError('ADDON_TEMPORARY_SDK_MOUNT')
    if {p.name:tx.digest(p) for p in SDK.glob('*.py')}!=manifest['candidate_sdk']:
        raise ValueError('ADDON_ACTIVE_SDK_SOURCE_SET')
    verify_api(API,manifest['api_files'])
    sys.path.insert(0,str(SDK));import h102_profile_config as config
    from h102_iio_owner_lock import configuration_lock
    config.configure_stack('sdk1-candidate')
    if 'loaded_bit' in config.identity():raise ValueError('ADDON_ONE_BOOT_LOADING_RECORD_FORBIDDEN')
    work=Path('/run/h102-grc-addon-preflight-'+uuid.uuid4().hex);work.mkdir(mode=0o700)
    with sdk_idle_context(config,configuration_lock,work):
        fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
        try:
            with mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=0x43c50000) as memory:
                words={hex(n):struct.unpack_from('<I',memory,n)[0] for n in (0x200,0x404,0x424,0x42c,0x604)}
        finally:os.close(fd)
        if words!={'0x200':0,'0x404':0,'0x424':3,'0x42c':0,'0x604':0}:
            raise ValueError('ADDON_ACTUAL_CAP3_IDLE_REQUIRED:'+repr(words))
    result=dict(status='PASS_PERSISTENT_DEFAULT_BOOT_API_PRECHECK',identity=identity,
                words=words,package_sha256=package_sha,API_started=False,RF_TX=False)
    tx.save_json(STATE/'activation.json',result)
    record['state']='ACTIVE_READY_FOR_API';record['activated_boot_id']=identity['boot_id']
    tx.save_json(STATE/'transaction.json',record)
    return result


def main():
    """Run the fixed service preflight and exit nonzero on error without reconnecting."""
    parser=argparse.ArgumentParser();parser.add_argument('--package-sha256',required=True)
    args=parser.parse_args();print(json.dumps(preflight(args.package_sha256)))


if __name__=='__main__':main()
# End of file: hotmeta_preflight.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
