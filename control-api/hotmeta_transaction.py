"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file hotmeta_transaction.py
@brief Verify, back up, commit and restore the six fixed H102 add-on files.
@details Persist and fsync backups before modifying targets. Recovery accepts only known
         original/new hashes and rejects external drift. Cross-filesystem commit is not atomic;
         the caller stops the service and requires a normal reboot. No hardware access occurs here.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

TARGETS = frozenset(('/boot/h102_logicrf_master.bit','/etc/h102/sdk1-image.json',
    *('/usr/local/lib/h102/sdk1/scripts/'+n for n in ('h102_profile_config.py',
      'h102_runtime_profile.py','h102_runtime_usb_prepare.py','h102_runtime_usb_rx.py'))))
"""Only these six files are managed; the caller backs up and restores the service unit."""


def digest(path):
    """Hash a regular file completely and reject symlinks."""
    path=Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('TRANSACTION_REGULAR_FILE_REQUIRED')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rooted(root, absolute):
    """Map fixed product paths to the target root; reject arbitrary paths and linked ancestors."""
    if absolute not in TARGETS:raise ValueError('TRANSACTION_TARGET_SET')
    root=Path(root).resolve();p=root/absolute.lstrip('/')
    if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('TRANSACTION_SYMLINK')
    return p


def durable_replace(path, raw, mode=0o600):
    """Exclusively create, fsync and rename a local temporary file, then fsync its directory."""
    path=Path(path);temporary=path.with_name('.'+path.name+'.h102-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary.exists():temporary.unlink()


def save_json(path,value):
    """Persist transaction state and retain committed entries for interruption diagnosis."""
    durable_replace(path,(json.dumps(value,indent=2)+'\n').encode())


def prepare(root, overlay, changes, backup, *, identity):
    """Verify all inputs and create durable backups and a PREPARED ledger without target writes."""
    root,overlay,backup=Path(root),Path(overlay),Path(backup)
    if set(changes)!=TARGETS:raise ValueError('TRANSACTION_EXACT_SIX_FILES_REQUIRED')
    for name,row in changes.items():
        if set(row)!={'before','after'} or digest(rooted(root,name))!=row['before']:
            raise ValueError('TRANSACTION_BASE_MISMATCH:'+name)
        if digest(rooted(overlay,name))!=row['after']:raise ValueError('TRANSACTION_PAYLOAD_MISMATCH:'+name)
    backup.mkdir(mode=0o700,parents=False,exist_ok=False)
    originals=backup/'original';originals.mkdir(mode=0o700)
    modes={}
    for name,row in changes.items():
        source=rooted(root,name);target=originals/name.lstrip('/');target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        durable_replace(target,source.read_bytes());modes[name]=stat.S_IMODE(source.stat().st_mode)
        if digest(target)!=row['before']:raise RuntimeError('TRANSACTION_BACKUP_SHA')
    record=dict(schema=1,state='PREPARED',identity=identity,changes=changes,modes=modes,committed=[])
    save_json(backup/'transaction.json',record)
    return record


def verify_backup(backup):
    """Recheck backups before any write; reject incomplete state or damaged originals."""
    backup=Path(backup);record=json.loads((backup/'transaction.json').read_text())
    if set(record['changes'])!=TARGETS:raise ValueError('TRANSACTION_BACKUP_TARGET_SET')
    for name,row in record['changes'].items():
        if digest(backup/'original'/name.lstrip('/'))!=row['before']:
            raise ValueError('TRANSACTION_BACKUP_CHANGED:'+name)
    return record


def apply(root, overlay, backup, *, after_write=None):
    """Commit the six backed-up files; the hook supports model fault injection only.

    Do not report rollback on failure: the caller stops the service and explicitly restores.
    Unknown state is not resumed automatically, preserving administrator modifications.
    """
    record=verify_backup(backup)
    if record['state']!='PREPARED':raise ValueError('TRANSACTION_NOT_PREPARED')
    for name,row in record['changes'].items():
        if digest(rooted(root,name))!=row['before'] or digest(rooted(overlay,name))!=row['after']:
            raise ValueError('TRANSACTION_RECHECK_MISMATCH:'+name)
    record['state']='WRITING';save_json(Path(backup)/'transaction.json',record)
    # Commit the bitstream last while the service is stopped; preflight rejects partial state.
    order=sorted(TARGETS-{'/boot/h102_logicrf_master.bit'})+['/boot/h102_logicrf_master.bit']
    for name in order:
        durable_replace(rooted(root,name),rooted(overlay,name).read_bytes(),record['modes'][name])
        if digest(rooted(root,name))!=record['changes'][name]['after']:raise RuntimeError('TRANSACTION_WRITE_SHA')
        record['committed'].append(name);save_json(Path(backup)/'transaction.json',record)
        if after_write:after_write(name,len(record['committed']))
    record['state']='FILES_INSTALLED_REBOOT_REQUIRED';save_json(Path(backup)/'transaction.json',record)
    return record


def rollback(root, backup):
    """Verify backups and targets, then restore six files; reject unknown external changes."""
    record=verify_backup(backup)
    for name,row in record['changes'].items():
        if digest(rooted(root,name)) not in (row['before'],row['after']):
            raise ValueError('TRANSACTION_FOREIGN_CHANGE:'+name)
    record['state']='ROLLING_BACK';save_json(Path(backup)/'transaction.json',record)
    for name,row in record['changes'].items():
        durable_replace(rooted(root,name),(Path(backup)/'original'/name.lstrip('/')).read_bytes(),record['modes'][name])
        if digest(rooted(root,name))!=row['before']:raise RuntimeError('TRANSACTION_ROLLBACK_SHA')
    record['state']='ROLLED_BACK_FILES_REBOOT_REQUIRED';save_json(Path(backup)/'transaction.json',record)
    return record

# End of file: hotmeta_transaction.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
