#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file image_api_preflight.py
@brief Verify the complete-image API, SDK and actual idle hardware after bootstrap.
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
from contextlib import ExitStack
import hashlib
import json
import mmap
import os
from pathlib import Path
import stat
import struct
import sys
import uuid


def digest(path):
    """Return the full SHA-256 and reject objects outside the required ownership/type policy."""
    path = Path(path)
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
        raise PermissionError('IMAGE_API_UNTRUSTED_FILE:'+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(expected):
    """Verify this normal SD boot before API startup; never load a bitstream or enable RF."""
    if os.geteuid() != 0:
        raise PermissionError('IMAGE_API_ROOT_REQUIRED')
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    for p in (root, *root.parents):
        value = p.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise PermissionError('IMAGE_API_UNTRUSTED_DIRECTORY')
    if digest(root/'assets.json') != expected:
        raise ValueError('IMAGE_API_ASSETS_SHA')
    assets = json.loads((root/'assets.json').read_text())
    actual = {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}
    if actual != dict(assets, **{'assets.json': expected}):
        raise ValueError('IMAGE_API_ASSET_SET')
    sys.path.insert(0, str(root))
    from h102_control.native import NativeDevice
    native = NativeDevice(str(root))
    config = native.config
    sdk = Path('/usr/local/lib/h102/sdk1/scripts')
    if (os.path.ismount(sdk) or config.ACTIVE_BIT_RECORD is not None
            or {p.name: digest(p) for p in sdk.glob('*.py')} != native.manifest['sdk_sources']):
        raise ValueError('IMAGE_API_COMPLETE_NORMAL_SDK_REQUIRED')
    pins = native.manifest['firmware']['boot_pins']
    if {p: digest(p) for p in pins} != pins:
        raise ValueError('IMAGE_API_BOOT_PINS')
    if 'loaded_bit' in config.identity() or 'systemd.mask=' in Path('/proc/cmdline').read_text():
        raise ValueError('IMAGE_API_NORMAL_SD_BOOT_REQUIRED')
    from h102_iio_owner_lock import configuration_lock
    work = Path('/run/h102-image-api-preflight-'+uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    with configuration_lock(timeout=3), ExitStack() as scope:
        hardware = config.hardware_context(scope, work, config.identity())
        hardware.verify(complete=True)
        hardware.idle()
        fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
        try:
            with mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ,
                           offset=0x43c50000) as memory:
                words = {hex(n): struct.unpack_from('<I', memory, n)[0]
                         for n in (0x200, 0x404, 0x424, 0x42c, 0x604)}
        finally:
            os.close(fd)
        if words != {'0x200': 0, '0x404': 0, '0x424': 3, '0x42c': 0, '0x604': 0}:
            raise ValueError('IMAGE_API_CAP3_IDLE_REQUIRED:'+repr(words))
    result = dict(status='PASS_IMAGE_API_DEFAULT_BOOT_PRECHECK', identity=config.identity(),
                  words=words, API_started=False, RF_TX=False)
    config.atomic_save(work/'result.json', result, exclusive=True)
    return result


def main():
    """Parse explicit arguments and report failure without implicit retries or device discovery."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(preflight(args.assets_sha256)))


if __name__ == '__main__':
    main()
# End of file: image_api_preflight.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
