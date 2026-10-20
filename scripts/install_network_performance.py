#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       install_network_performance.py
@brief      Install or remove an H102 network-performance add-on from hashed payloads.
@details    Offline administration rejects unknown existing files without changing RF or authentication.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-19
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

VERSION = '1.0.0'
SERVICE = 'h102-network-performance.service'
READY_SERVICE = 'h102-grc-ready-profile.service'
HELPER = '/usr/local/lib/h102/network-performance/1.0.0/h102_network_performance.py'
FILES = {
    'h102_network_performance.py': HELPER,
    'h102-network-performance.service': '/etc/systemd/system/'+SERVICE,
    '50-h102-network-performance.conf': '/etc/systemd/system/iiod.service.d/50-h102-network-performance.conf',
    '51-h102-network-performance-ffs.conf': '/etc/systemd/system/iiod_ffs.service.d/51-h102-network-performance-ffs.conf',
    'h102-grc-ready-profile.service': '/etc/systemd/system/'+READY_SERVICE,
}
RECEIPT = Path('/var/lib/h102/network-performance/1.0.0/install.json')


def digest(path):
    """Accept regular nonlinked payloads and bind installed bytes to complete hashes."""
    if path.is_symlink() or not path.is_file():
        raise ValueError('REGULAR_PAYLOAD_REQUIRED:'+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*arguments):
    """Preserve native management-command errors rather than treating skipped actions as applied."""
    return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout


def private_parents(path):
    """Reject installation parents replaceable by ordinary users."""
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for item in [parent, *parent.parents]:
        info = item.lstat()
        if item.is_symlink() or info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('ROOT_CONTROLLED_PARENT_REQUIRED:'+str(item))
    for item in reversed(missing):
        item.mkdir(mode=0o755)


def record(value):
    """Persist exact terminal state without claiming completion after failure."""
    private_parents(RECEIPT)
    with tempfile.NamedTemporaryFile(mode='w', dir=RECEIPT.parent, delete=False) as stream:
        path = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(path, RECEIPT)


def preserve_removed_receipt():
    """Reinstall only after completed removal, preserving original receipts by their full hashes."""
    if not RECEIPT.exists() and not RECEIPT.is_symlink():
        return
    digest(RECEIPT)
    previous=json.loads(RECEIPT.read_text())
    if (previous.get('status')!='REMOVED' or previous.get('manifest',{}).get('version')!=VERSION or
            previous.get('restored',{}).get('status')!='RESTORED'):
        raise ValueError('EXISTING_INSTALL_OR_UNKNOWN_RECEIPT_NO_OVERWRITE')
    history=RECEIPT.parent/'history'/('removed-'+digest(RECEIPT)+'.json')
    private_parents(history)
    if history.exists() or history.is_symlink():
        if digest(history)!=digest(RECEIPT):
            raise ValueError('REMOVAL_HISTORY_CHANGED')
    else:
        with history.open('xb') as stream:
            stream.write(RECEIPT.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        history.chmod(0o600)


def main():
    """Local root install/remove only; ordinary GNU Radio users do not run this or supply passwords."""
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check','install','remove'))
    parser.add_argument('--prepare-grc-profile', action='store_true',
                        help='Explicitly enable independent boot-time 4-MSPS preparation; disabled by default')
    args = parser.parse_args()
    if args.prepare_grc_profile and args.action!='install':
        parser.error('--prepare-grc-profile only applies to install')
    source = Path(__file__).resolve().parent
    manifest = json.loads((source/'manifest.json').read_text())
    if (manifest['version']!=VERSION or set(manifest['files'])!=set(FILES) or
            any(digest(source/name)!=sha for name,sha in manifest['files'].items())):
        raise ValueError('PAYLOAD_MANIFEST_MISMATCH')
    if args.action=='check':
        print(json.dumps(dict(status='PAYLOAD_SHA_VERIFIED', manifest=manifest)))
        return
    if os.geteuid()!=0:
        raise ValueError('ADMIN_INSTALL_REQUIRED')
    before = json.loads(command('/usr/bin/python3','-B',str(source/'h102_network_performance.py'),'available'))
    destinations = {Path(target):manifest['files'][name] for name,target in FILES.items()}
    if args.action=='remove':
        installed = json.loads(RECEIPT.read_text())
        if installed.get('status')!='INSTALLED' or installed['manifest']!=manifest:
            raise ValueError('EXACT_INSTALL_RECEIPT_REQUIRED')
        if any(digest(path)!=sha for path,sha in destinations.items()):
            raise ValueError('INSTALLED_FILE_DRIFT_NO_REMOVAL')
        command('systemctl','stop',SERVICE)
        restored = json.loads(command('/usr/bin/python3','-B',HELPER,'restore'))
        if restored['status']!='RESTORED':
            raise ValueError('RESTORE_NOT_CONFIRMED_NO_REMOVAL')
        command('systemctl','disable',SERVICE)
        command('systemctl','stop',READY_SERVICE)
        command('systemctl','disable',READY_SERVICE)
        for path in destinations:
            path.unlink()
        command('systemctl','daemon-reload')
        record(dict(status='REMOVED', manifest=manifest, restored=restored))
        print(json.dumps(dict(status='REMOVED', restored=restored)))
        return
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise ValueError('EXISTING_INSTALL_OR_UNKNOWN_TARGET_NO_OVERWRITE')
    preserve_removed_receipt()
    # Preflight read-only first; apply still requires three locks and four idle DMA channels.
    written = []
    try:
        for name,target in FILES.items():
            path = Path(target)
            private_parents(path)
            with path.open('xb') as stream:
                written.append(path)
                stream.write((source/name).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o644)
        command('systemctl','daemon-reload')
        if args.prepare_grc_profile:
            command('systemctl','enable','--now',READY_SERVICE)
        command('systemctl','enable','--now',SERVICE)
        actual = json.loads(command('/usr/bin/python3','-B',HELPER,'status'))
        if not actual['applied']:
            raise ValueError('SERVICE_POLICY_NOT_APPLIED')
        receipt = dict(status='INSTALLED', manifest=manifest, before=before, actual=actual,
                       grc_boot_profile_enabled=args.prepare_grc_profile)
        record(receipt)
        print(json.dumps(receipt))
    except Exception as error:
        # Keep payloads after failed installation for independent restoration and diagnosis.
        recovery = None
        try:
            command('systemctl','stop',SERVICE)
            if Path(HELPER) in written:
                recovery = json.loads(command('/usr/bin/python3','-B',HELPER,'restore'))
        except Exception as failure:
            recovery = dict(status='UNCONFIRMED', error=repr(failure))
        record(dict(status='INSTALL_FAILED', manifest=manifest, before=before,
                    error=repr(error), recovery=recovery, written=[str(p) for p in written]))
        raise


if __name__=='__main__':
    main()
# End of file: install_network_performance.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
