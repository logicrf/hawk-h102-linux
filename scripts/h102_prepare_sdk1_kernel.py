#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_prepare_sdk1_kernel.py
@brief      Prepare an independent H102 kernel checkout from pinned SDK and profile inputs.
@details    Verify SDK, 141 API files, three profile/stream sets and patch hashes.
            Preserve ADI licenses and import only into the exact clean independent kernel checkout.
            Do not compile, deploy, reboot, write SD or control devices; reject inputs before source writes.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-07
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / 'manifests/h102-sdk1-linux-source-pins.json'
PATCH = ROOT / 'patches/h102-sdk1-linux-iio.patch'


def digest(path):
    """Stream archive hashing without loading the full SDK into memory."""
    hasher = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def verified_payloads(archive, profiles, pins):
    """Validate all inputs and return bytes without writing files or executing SDK code."""
    if (digest(archive) != pins['sdk_zip_sha256'] or digest(PATCH) != pins['patch_sha256'] or
            digest(ROOT / 'manifests/h102-sdk1-kernel.config') != pins['kernel_config_sha256']):
        raise ValueError('SDK_OR_PATCH_SHA_MISMATCH')
    payloads = {}
    with zipfile.ZipFile(archive) as sdk:
        prefix = 'adrv9001-sdk.1.0.0-ga/adrv9001-sdk/'
        for entry in pins['files']:
            raw = sdk.read(prefix + 'pkg/production/c_src/' + entry['path'])
            normalized = raw.replace(b'\r\n', b'\n')
            if (hashlib.sha256(raw).hexdigest() != entry['sdk_sha256'] or
                    hashlib.sha256(normalized).hexdigest() != entry['import_sha256']):
                raise ValueError('VENDOR_SHA_MISMATCH: ' + entry['path'])
            payloads[entry['path']] = normalized
        payloads['SDK1-LICENSE.md'] = sdk.read(prefix + 'pkg/LICENSE.md')
        payloads['SDK1-SLA-20260801.pdf'] = sdk.read(prefix +
            'license/2026-08-01-adrv9002-sdk-1.0.0-ga-click-thru-SLA.pdf')
        fw = sdk.read(prefix + 'pkg/prototype/resources/Adi.Adrv9001.Firmware/'
                      'Navassa_EvaluationFw_C0_1.0.2.bin')
        if hashlib.sha256(fw).hexdigest() != pins['firmware_sha256']:
            raise ValueError('C0_FIRMWARE_SHA_MISMATCH')
    configs = {}
    for entry in pins['profiles']:
        for name in ('profile.json', 'stream.bin'):
            path = profiles / entry['id'] / name
            if path.is_symlink() or digest(path) != entry['sha256'][name]:
                raise ValueError('GENERATED_CONFIG_SHA_MISMATCH: ' + str(path))
        configs[entry['id']] = profiles / entry['id']
    return payloads, fw, configs


def main():
    """Import only after preflight; preserve failed directories and return nonzero."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-zip', type=Path, required=True)
    parser.add_argument('--profiles-root', type=Path, required=True)
    parser.add_argument('--kernel-source', type=Path)
    parser.add_argument('--kernel-build', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    pins = json.loads(PINS.read_text())
    payloads, fw, configs = verified_payloads(args.sdk_zip, args.profiles_root, pins)
    if args.check_only:
        print(json.dumps({'input_verification': 'passed', 'vendor_files': len(pins['files']),
                          'profiles': list(configs),
                          'license_files': [p for p in payloads if p.startswith('SDK1-')],
                          'hardware_access': False}))
        return
    if not args.kernel_source or not args.kernel_build:
        parser.error('An independent kernel-source and new kernel-build directory are required')
    source, build = args.kernel_source.resolve(), args.kernel_build.resolve()
    if source.is_relative_to(ROOT) or build.exists():
        raise ValueError('INDEPENDENT_CHECKOUT_AND_FRESH_BUILD_REQUIRED')
    base = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True)
    if base != pins['kernel_base'] or dirty:
        raise ValueError('KERNEL_BASE_OR_CLEAN_CHECKOUT_MISMATCH')
    subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=source, check=True)
    navassa = source / 'drivers/iio/adc/navassa'
    for relative, data in payloads.items():
        destination = navassa / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    subprocess.run(['git', 'apply', str(PATCH)], cwd=source, check=True)
    override = source / 'firmware/h102_override'
    override.mkdir()
    replacements = {'Navassa_EvaluationFw.bin', 'Navassa_Stream.bin', 'Navassa_LVDS_profile.json'}
    for existing in (source / 'firmware').iterdir():
        if existing.is_file() and existing.name not in replacements:
            (override / existing.name).symlink_to('../' + existing.name)
    (override / 'Navassa_EvaluationFw.bin').write_bytes(fw)
    shutil.copyfile(configs['40msps-20mhz'] / 'stream.bin', override / 'Navassa_Stream.bin')
    shutil.copyfile(configs['40msps-20mhz'] / 'profile.json', override / 'Navassa_LVDS_profile.json')
    build.mkdir(parents=True)
    shutil.copyfile(ROOT / 'manifests/h102-sdk1-kernel.config', build / '.config')
    print(json.dumps({'prepared': str(source), 'kernel_build': str(build),
                      'api': pins['api_version'], 'board_qualified': False}))


if __name__ == '__main__':
    main()

# End of file: h102_prepare_sdk1_kernel.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
