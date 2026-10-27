#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file install_panel_addon.py
@brief Install or restore the matched five-file panel update on the exact EFA baseline.
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
from contextlib import ExitStack,contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

import panel_transaction as tx

STATE = Path('/var/lib/h102/panel-status-1')
SDK = Path('/usr/local/lib/h102/sdk1/scripts')
UNIT = Path('/etc/systemd/system/h102-control-api.service')
API = Path('/usr/local/lib/h102/control-api/0.1.0-ip36-panel1')
"""Fixed product directories; packages contain no credentials or pre-bound device/boot identity."""


def private(path, *, directory=False):
    """Require root-owned regular objects and ancestors, rejecting symlinks."""
    path=Path(path)
    for p in (path,*path.parents):
        value=p.lstat();kind=stat.S_ISDIR if p!=path or directory else stat.S_ISREG
        if value.st_uid!=0 or value.st_mode&0o022 or not kind(value.st_mode):
            raise PermissionError('ADDON_UNTRUSTED_PATH:'+str(p))


def verify_package(root, expected):
    """Verify exact package membership and every hash; reject extra files and symlinks."""
    root=Path(root);private(root,directory=True)
    if tx.digest(root/'package.json')!=expected:raise ValueError('ADDON_PACKAGE_SHA')
    manifest=json.loads((root/'package.json').read_text())
    for p in root.rglob('*'):
        mode=p.lstat().st_mode
        if p.is_symlink() or not(stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('ADDON_PACKAGE_NONREGULAR_MEMBER')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual!=set(manifest['files'])|{'package.json'}:raise ValueError('ADDON_PACKAGE_MEMBERS')
    for name,digest in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('ADDON_PACKAGE_PATH')
        p=root/name;private(p)
        if tx.digest(p)!=digest:raise ValueError('ADDON_PACKAGE_FILE_SHA:'+name)
    if manifest['version']!='1.2.0-panel-1' or set(manifest['changes'])!=tx.TARGETS:
        raise ValueError('ADDON_PACKAGE_VERSION_OR_TARGETS')
    return manifest


def systemctl(*arguments):
    """Run only required systemd actions; callers stop subsequent commits on failure."""
    return subprocess.run(['systemctl',*arguments],check=True,capture_output=True,text=True,timeout=180)


def unit_text(package_sha):
    """Create the fixed systemd unit; do not bind it to a device identity."""
    return f'''[Unit]
Description=LogicRF H102 panel status paired control API
After=network-online.target h102-sdk1-bootstrap.service
Wants=network-online.target
Requires=h102-sdk1-bootstrap.service
[Service]
Type=simple
User=root
UMask=0077
Environment=PYTHONNOUSERSITE=1
Environment=PYTHONPATH={API}
WorkingDirectory={API}
ExecStartPre=/usr/bin/python3 -B {STATE}/package/panel_preflight.py --package-sha256 {package_sha}
ExecStart=/usr/bin/python3 -B -m h102_control --root {API}
Restart=no
TimeoutStopSec=160
KillMode=process
[Install]
WantedBy=multi-user.target
'''


def validate_identity(manifest):
    """Verify the original SDK, boot files, metadata and kernel before writing or importing."""
    if os.uname().release!=manifest['base_kernel']:raise ValueError('ADDON_KERNEL')
    if {p.name:tx.digest(p) for p in SDK.glob('*.py')}!=manifest['original_sdk']:
        raise ValueError('ADDON_BASE_SDK')
    for name,digest in manifest['base_boot_pins'].items():
        if tx.digest(name)!=digest:raise ValueError('ADDON_BASE_BOOT')
    if tx.digest('/etc/h102/sdk1-image.json')!=manifest['changes']['/etc/h102/sdk1-image.json']['before']:
        raise ValueError('ADDON_BASE_METADATA')
    if os.path.ismount(SDK):raise ValueError('ADDON_REFUSES_TEMPORARY_SDK_MOUNT')
    old_api=Path('/usr/local/lib/h102/control-api/0.1.0-ip36')
    verify_api(old_api,manifest['original_api_files'])
    if tx.digest(UNIT)!=manifest['original_unit_sha256']:
        raise ValueError('PANEL_BASE_UNIT_CHANGED')
    return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                machine_id=Path('/etc/machine-id').read_text().strip(),
                MAC=Path('/sys/class/net/eth0/address').read_text().strip())


def verify_api(root, expected):
    """Check every installed API file and reject added or changed sources."""
    actual={str(p.relative_to(root)):tx.digest(p) for p in root.rglob('*') if p.is_file()}
    if actual!=expected:raise ValueError('ADDON_API_TREE')


def restore_unit(record):
    """Verify backup identity and restore the unit without starting an unmatched API."""
    if record['present']:
        saved=STATE/'previous-unit.service'
        if tx.digest(saved)!=record['sha256']:raise ValueError('ADDON_PREVIOUS_UNIT_BACKUP_CHANGED')
        tx.durable_replace(UNIT,saved.read_bytes(),0o644)
    elif UNIT.exists():
        systemctl('disable',UNIT.name);UNIT.unlink()
    systemctl('daemon-reload')
    if record.get('enabled') is False and record['present']:systemctl('disable',UNIT.name)


@contextmanager
def sdk_idle_context(config, configuration_lock, directory):
    """Hold the configuration lock here; the reviewed SDK factory acquires RX/GNSS locks once."""
    with configuration_lock(timeout=3),ExitStack() as scope:
        hw=config.hardware_context(scope,directory,config.identity());hw.idle()
        yield hw


def install(package, package_sha, manifest):
    """Install one persistent transaction per device; do not resume or overwrite an existing one."""
    if STATE.exists():raise FileExistsError('ADDON_TRANSACTION_EXISTS_USE_EXPLICIT_REAPPLY_AFTER_ROLLBACK')
    if API.exists():verify_api(API,manifest['api_files'])
    identity=validate_identity(manifest)
    sys.path.insert(0,str(SDK));import h102_profile_config as config
    from h102_iio_owner_lock import configuration_lock
    config.configure_stack('sdk1-candidate')
    probe=Path('/run/h102-panel-addon-install-'+uuid.uuid4().hex);probe.mkdir(mode=0o700,exist_ok=False)
    with sdk_idle_context(config,configuration_lock,probe):
        # The SDK factory verifies actual identity/sources and holds RX/GNSS locks; do not acquire the same flock again.
        import mmap,struct
        fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
        try:
            with mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=0x43c50000) as words:
                if struct.unpack_from('<I',words,0x424)[0]!=3:raise ValueError('ADDON_INSTALL_REQUIRES_ORIGINAL_CAP3')
        finally:os.close(fd)
        STATE.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        previous=dict(present=UNIT.exists(),sha256=None)
        if previous['present']:
            private(UNIT);previous['sha256']=tx.digest(UNIT)
            enabled=subprocess.run(['systemctl','is-enabled',UNIT.name],capture_output=True,text=True,timeout=10).stdout.strip()
            if enabled not in ('enabled','disabled'):raise ValueError('ADDON_PREVIOUS_UNIT_ENABLE_STATE')
            previous['enabled']=enabled=='enabled'
        else:
            import socket
            with socket.socket() as available:available.bind(('0.0.0.0',30432))
        for volume,needed in (('/boot',(package/'overlay/boot/h102_logicrf_master.bit').stat().st_size+1048576),
                              ('/var/lib',sum(p.stat().st_size for p in package.rglob('*') if p.is_file())*3+8388608)):
            capacity=os.statvfs(volume)
            if capacity.f_bavail*capacity.f_frsize<needed:raise OSError('ADDON_INSUFFICIENT_SPACE:'+volume)
        tx.prepare('/',package/'overlay',manifest['changes'],STATE,identity=identity)
        shutil.copytree(package,STATE/'package')
        verify_package(STATE/'package',package_sha)
        if previous['present']:tx.durable_replace(STATE/'previous-unit.service',UNIT.read_bytes())
        tx.save_json(STATE/'service-backup.json',previous)
        tx.save_json(STATE/'deployment.json',dict(package_sha256=package_sha,identity=identity,api=str(API)))
        stopped=False
        try:
            if previous['present']:systemctl('stop',UNIT.name);stopped=True
            API.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            if not API.exists():shutil.copytree(package/'api',API)
            verify_api(API,manifest['api_files'])
            tx.apply('/',package/'overlay',STATE)
            raw=unit_text(package_sha).encode();tx.durable_replace(UNIT,raw,0o644)
            systemctl('daemon-reload');systemctl('enable',UNIT.name)
            tx.save_json(STATE/'new-unit.json',dict(sha256=hashlib.sha256(raw).hexdigest()))
        except BaseException as error:
            failures=[repr(error)]
            try:tx.rollback('/',STATE)
            except BaseException as restore_error:failures.append('files:'+repr(restore_error))
            try:restore_unit(previous)
            except BaseException as restore_error:failures.append('unit:'+repr(restore_error))
            tx.save_json(STATE/'install-failure.json',dict(errors=failures,old_service_stopped=stopped))
            raise
    return dict(status='INSTALLED_REBOOT_REQUIRED',identity=identity,api_started=False,transaction=str(STATE))


def same_payload(old, new):
    """Migrate maintenance tools only; reject any bitstream, SDK, metadata or API payload change."""
    for key in ('version','changes','original_sdk','candidate_sdk','base_kernel','base_boot_pins','api_files'):
        if old[key]!=new[key]:raise ValueError('ADDON_MAINTENANCE_PAYLOAD_CHANGED:'+key)


def rollback(package_sha):
    """Hold all three locks and verify idle before complete rollback, then require reboot."""
    private(STATE,directory=True);deployment=json.loads((STATE/'deployment.json').read_text())
    if deployment['package_sha256']!=package_sha:raise ValueError('ADDON_ROLLBACK_PACKAGE')
    if (deployment['identity']['machine_id']!=Path('/etc/machine-id').read_text().strip() or
            deployment['identity']['MAC']!=Path('/sys/class/net/eth0/address').read_text().strip()):
        raise ValueError('ADDON_ROLLBACK_MACHINE')
    manifest=verify_package(STATE/'package',package_sha)
    tx.verify_backup(STATE)
    expected=json.loads((STATE/'new-unit.json').read_text())['sha256']
    if tx.digest(UNIT)!=expected:raise ValueError('ADDON_ROLLBACK_UNIT_CHANGED')
    if {p.name:tx.digest(p) for p in SDK.glob('*.py')}!=manifest['candidate_sdk']:
        raise ValueError('ADDON_ROLLBACK_REQUIRES_COHERENT_INSTALLED_SDK')
    sys.path.insert(0,str(SDK));import h102_profile_config as config
    from h102_iio_owner_lock import configuration_lock
    config.configure_stack('sdk1-candidate')
    probe=Path('/run/h102-panel-addon-rollback-'+uuid.uuid4().hex);probe.mkdir(mode=0o700)
    with sdk_idle_context(config,configuration_lock,probe):
        import mmap,struct
        fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
        try:
            with mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=0x43c50000) as memory:
                words={hex(n):struct.unpack_from('<I',memory,n)[0] for n in (0x200,0x404,0x424,0x42c,0x604)}
        finally:os.close(fd)
        if words!={'0x200':0,'0x404':0,'0x424':3,'0x42c':0,'0x604':0}:
            raise ValueError('ADDON_ROLLBACK_ACTUAL_IDLE_REQUIRED')
        systemctl('stop',UNIT.name)
        record=tx.rollback('/',STATE);restore_unit(json.loads((STATE/'service-backup.json').read_text()))
        record['rollback_boot_id']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        tx.save_json(STATE/'transaction.json',record)
    return dict(status='ROLLED_BACK_REBOOT_REQUIRED',api_started=False,transaction=str(STATE),idle_words=words)


def reapply(package_sha, source_package, new_sha, new_manifest):
    """Reinstall after exact rollback and a normal old boot; preserve the old transaction."""
    private(STATE,directory=True)
    deployment=json.loads((STATE/'deployment.json').read_text())
    if deployment['package_sha256']!=package_sha:raise ValueError('ADDON_REAPPLY_PACKAGE')
    record=tx.verify_backup(STATE)
    if record['state']!='ROLLED_BACK_FILES_REBOOT_REQUIRED':raise ValueError('ADDON_REAPPLY_REQUIRES_ROLLBACK')
    package=STATE/'package';manifest=verify_package(package,package_sha);same_payload(manifest,new_manifest)
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()==record.get('rollback_boot_id') or not record.get('rollback_boot_id'):
        raise ValueError('ADDON_REAPPLY_REQUIRES_NORMAL_REBOOT')
    identity=validate_identity(new_manifest)
    if identity['machine_id']!=record['identity']['machine_id']:raise ValueError('ADDON_REAPPLY_MACHINE')
    previous=json.loads((STATE/'service-backup.json').read_text())
    if previous['present'] and tx.digest(UNIT)!=previous['sha256']:raise ValueError('ADDON_REAPPLY_UNIT')
    if not previous['present'] and UNIT.exists():raise ValueError('ADDON_REAPPLY_UNEXPECTED_UNIT')
    verify_api(API,manifest['api_files'])
    history=STATE.parent/'panel-status-1-history';history.mkdir(mode=0o700,exist_ok=True)
    relative=source_package.relative_to(STATE) if source_package.is_relative_to(STATE) else None
    target=history/uuid.uuid4().hex;STATE.rename(target)
    source_package=target/relative if relative is not None else source_package
    return install(source_package,new_sha,new_manifest)


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser=argparse.ArgumentParser();parser.add_argument('--package-sha256',required=True)
    parser.add_argument('--existing-package-sha256',help='Explicit old-package identity for maintenance-only migration with unchanged payloads')
    action=parser.add_mutually_exclusive_group();action.add_argument('--rollback',action='store_true');action.add_argument('--reapply',action='store_true');args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('ROOT_ADMIN_INSTALL_REQUIRED')
    os.umask(0o077);package=Path(__file__).resolve().parent
    manifest=verify_package(package,args.package_sha256)
    existing=args.existing_package_sha256 or args.package_sha256
    if args.existing_package_sha256:
        if not(args.rollback or args.reapply):raise ValueError('ADDON_EXISTING_PACKAGE_ONLY_FOR_MAINTENANCE')
        same_payload(verify_package(STATE/'package',existing),manifest)
    result=(rollback(existing) if args.rollback else
            reapply(existing,package,args.package_sha256,manifest) if args.reapply else install(package,args.package_sha256,manifest))
    print(json.dumps(result))


if __name__=='__main__':main()
# End of file: install_panel_addon.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
