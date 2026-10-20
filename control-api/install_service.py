#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file install_service.py
@brief Install an explicitly hashed H102 control service without changing login authentication.
@details Run explicitly as root; verify the complete package, firmware and idle state first.
         Reject an existing version or service. Installation does not qualify a new image or RTL release.
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
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys


def main():
    """Verify source and firmware before installing only this service."""
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--assets-sha256',required=True);parser.add_argument('--upgrade-from-assets-sha256');args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('ROOT_ADMIN_INSTALL_REQUIRED')
    os.umask(0o077);source=args.bundle.resolve()
    filesystem=os.statvfs('/run')
    if filesystem.f_bavail*filesystem.f_frsize<20*1024*1024:raise OSError('CONTROL_API_INSTALL_REQUIRES_20M_FREE_RUN')
    assets_path=source/'assets.json'
    if hashlib.sha256(assets_path.read_bytes()).hexdigest()!=args.assets_sha256:raise ValueError('ASSETS_MANIFEST_SHA')
    assets=json.loads(assets_path.read_text())
    actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
    if actual!=set(assets)|{'assets.json'}:raise ValueError('ASSETS_SET')
    for relative,digest in assets.items():
        path=source/relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not stat.S_ISREG(path.lstat().st_mode) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('ASSET_HASH_OR_PATH')
    manifest=json.loads((source/'manifest.json').read_text())
    pins=manifest['firmware']
    if (hashlib.sha256(Path('/etc/h102/sdk1-image.json').read_bytes()).hexdigest()!=pins['metadata_sha256'] or
            os.uname().release!=pins['kernel']):raise ValueError('TARGET_FIRMWARE_IDENTITY')
    for path,digest in pins['boot_pins'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('TARGET_BOOT_PIN')
    version=manifest['service_version']
    import re
    if not re.fullmatch(r'0\.1\.0-ip[0-9]+',version):raise ValueError('SERVICE_VERSION')
    destination=Path('/usr/local/lib/h102/control-api')/version
    unit=Path('/etc/systemd/system/h102-control-api.service')
    if destination.exists():raise FileExistsError('CONTROL_API_VERSION_EXISTS')
    previous=None
    if unit.exists():
        if not args.upgrade_from_assets_sha256:raise FileExistsError('CONTROL_API_UPGRADE_IDENTITY_REQUIRED')
        previous=unit.read_text()
        match=re.search(r'WorkingDirectory=(/usr/local/lib/h102/control-api/0\.1\.0-ip[0-9]+)',previous)
        if not match or hashlib.sha256((Path(match[1])/'assets.json').read_bytes()).hexdigest()!=args.upgrade_from_assets_sha256:
            raise ValueError('CONTROL_API_PREVIOUS_ASSETS_MISMATCH')
    else:
        with socket.socket() as probe:probe.bind(('0.0.0.0',30432))
    sys.path.insert(0,str(source));from h102_control.native import NativeDevice
    device=NativeDevice(source);device.status()  # Validate all three locks and actual idle state first.
    destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    shutil.copytree(source,destination)
    for path in (destination,*destination.rglob('*')):
        os.chown(path,0,0);path.chmod(0o700 if path.is_dir() else 0o600)
    if previous:
        (destination/'previous-unit.service').write_text(previous)
        subprocess.run(['systemctl','stop',unit.name],check=True,timeout=165)
    unit.write_text('''[Unit]
Description=LogicRF H102 fixed device control API
After=network-online.target h102-sdk1-bootstrap.service
Wants=network-online.target
[Service]
Type=simple
User=root
UMask=0077
Environment=PYTHONNOUSERSITE=1
Environment=PYTHONPATH=/usr/local/lib/h102/control-api/0.1.0-ip1
WorkingDirectory=/usr/local/lib/h102/control-api/0.1.0-ip1
ExecStart=/usr/bin/python3 -B -m h102_control --root /usr/local/lib/h102/control-api/0.1.0-ip1
KillMode=process
TimeoutStopSec=160
Restart=no
[Install]
WantedBy=multi-user.target
'''.replace('0.1.0-ip1',version))
    try:
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
        subprocess.run(['systemctl','enable','--now',unit.name],check=True,timeout=30)
    except Exception:
        if previous:
            unit.write_text(previous)
            subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=30)
            subprocess.run(['systemctl','start',unit.name],capture_output=True,timeout=30)
        raise
    print(json.dumps(dict(status='INSTALLED',service=unit.name,version=manifest['service_version'],assets_sha256=args.assets_sha256)))

if __name__=='__main__':main()
# End of file: install_service.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
