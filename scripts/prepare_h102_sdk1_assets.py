#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       prepare_h102_sdk1_assets.py
@brief      Prepare SDK1 image assets from pinned Git/boot inputs and an optional host package.
@details    Pin 107 board sources and 29 packages; record product-path and boot-file adaptations.
            Read inputs and create a new regular directory without image mounts or deployment.
            Reject bad hashes, object types or packages; asset checks do not qualify boot, USB or RF.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.2.0
@date       2026-10-12
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile

SOURCE_COMMIT = '8a0fa24c8653c550527b0b58e7bfb2a632889579'
KERNEL = '6.6.0-h102-sdk1-candidate+'
SCRIPTS = '/usr/local/lib/h102/sdk1/scripts'
CATALOG = '/usr/local/lib/h102-config-sdk1/profiles'
APPROVED = '/etc/h102/h102-built-in-sdk1-presets.json'
PINS = {
    'boot_bin': '44b478bc7f38538f99d084551151639bef8ca5fbfc6378b26a564140d147a4b4',
    'fit': 'a504c57e3c2e0d3883c57e007087977f22609397b8cdd7ba089fc4265ee001f1',
    'bit': 'd81b6988b5f52b2fe1e03a86ba23508d7096560a9a60e011fd17c71c199974aa',
    'modules': 'd29a9523969460b7e53c3ae99f05cccdc80934d2199b214b34e8619247959fec',
}
"""Exact candidate inputs; never auto-update from HEAD, live state or arbitrary new hashes."""
UENV = b'''# LogicRF Hawk H102 SDK1 runtime-wire candidate; exact boot qualification pending.
bootargs=console=ttyPS0,115200 root=/dev/mmcblk0p2 rw earlycon rootfstype=ext4 rootwait clk_ignore_unused cpuidle.off=1
loadbit_addr=0x100000
bitstream_image=h102_logicrf_master.bit
fit_addr=0x10000000
uenvcmd=echo H102-LOGICRF-SDK1-RUNTIME-WIRE && run mmc_loadbit && echo H102-BIT-LOAD-DONE && load mmc 0 ${fit_addr} image-sdk1.ub && echo H102-FIT-LOAD-DONE && bootm ${fit_addr}
mmc_loadbit=mmcinfo && load mmc 0 ${loadbit_addr} ${bitstream_image} && fpga loadb 0 ${loadbit_addr} ${filesize}
'''


def sha(raw: bytes) -> str:
    """Return SHA-256 of all input bytes."""
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: dict) -> bytes:
    """Use deterministic readable JSON encoding."""
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def prepare(inputs: Path, output: Path, project: Path) -> dict:
    """Verify all inputs before creating assets; preserve failed output without hardware access."""
    if output.exists() or output.is_symlink() or not inputs.is_file() or inputs.is_symlink():
        raise ValueError('FRESH_OUTPUT_AND_REGULAR_INPUT_REQUIRED')
    request = json.loads(inputs.read_bytes())
    if (set(request) not in ({'schema', 'boot_bin', 'fit', 'bit', 'modules'},
                            {'schema', 'boot_bin', 'fit', 'bit', 'modules', 'portable_host'}) or request['schema'] != 1):
        raise ValueError('INPUT_SCHEMA')
    # Freeze recipe/documentation hashes so assembly detects changes after asset preparation.
    tool_names = ['scripts/prepare_h102_sdk1_assets.py', 'scripts/build_h102_sdk1_image.py',
                  'scripts/compact_h102_image.py',
                  'overlays/h102/usr-local-lib/h102/sdk1_bootstrap.py']
    if 'portable_host' in request:
        tool_names += ['manifests/h102-portable-host-pins.json',
                       'docs/h102-image-host-tools-zh.md', 'tools/runtime-wire-host/README.md',
                       'docs/receipts/20261012-portable-host-board.json']
    tool_sources = {name: sha((project / name).read_bytes()) for name in tool_names}
    raw_inputs = {}
    for name, pinned in PINS.items():
        entry = request[name]
        if set(entry) != {'path', 'bytes', 'sha256'} or entry['sha256'] != pinned:
            raise ValueError('INPUT_PIN: ' + name)
        path = Path(entry['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('REGULAR_INPUT: ' + name)
        raw = path.read_bytes()
        if len(raw) != entry['bytes'] or sha(raw) != pinned:
            raise ValueError('INPUT_BYTES_OR_DIGEST: ' + name)
        raw_inputs[name] = raw
    git = lambda *args: subprocess.check_output(['git', '-C', str(project), *args])
    if git('rev-parse', SOURCE_COMMIT + '^{commit}').decode().strip() != SOURCE_COMMIT:
        raise ValueError('SOURCE_COMMIT')
    blob = lambda name: git('show', SOURCE_COMMIT + ':' + name)
    approved = blob('profiles/requests/h102-built-in-sdk1-presets.json')
    if sha(approved) != '91c85ab2d70d3f147cdd915d6969a1d636bf1613af5f0283b810c934d23cb979':
        raise ValueError('APPROVED_CATALOG_PIN')
    ids = [row['id'] for row in json.loads(approved)['profiles']]
    if len(ids) != 29 or len(set(ids)) != 29:
        raise ValueError('APPROVED_29_UNIQUE')
    assets = {}; modes = {}; adaptations = {}

    def add(name, raw, mode=0o644):
        """Require canonical regular-file destinations and reject conflicting sources."""
        path = PurePosixPath(name)
        if not path.is_absolute() or '..' in path.parts or str(path) != name or name in assets:
            raise ValueError('DUPLICATE_OR_UNSAFE_ASSET')
        assets[name] = raw; modes[name] = mode

    boot_pins = {'/boot/BOOT.BIN': PINS['boot_bin'], '/boot/image-sdk1.ub': PINS['fit'],
                 '/boot/h102_logicrf_master.bit': PINS['bit'], '/boot/uEnv.txt': sha(UENV)}
    for name, raw in [('BOOT.BIN', raw_inputs['boot_bin']), ('image-sdk1.ub', raw_inputs['fit']),
                      ('h102_logicrf_master.bit', raw_inputs['bit']), ('uEnv.txt', UENV)]:
        add('/boot/' + name, raw)
    names = [n for n in git('ls-tree', '-r', '--name-only', SOURCE_COMMIT, 'scripts').decode().splitlines()
             if n.endswith('.py') and n != 'scripts/h102_runtime_ft601_mixed.py']
    if len(names) != 107:
        raise ValueError('EXPECTED_107_BOARD_SOURCES')
    for name in names:
        original = blob(name); raw = original; substitutions = []

        def replace(old, new):
            """Require each original anchor exactly once; reject upstream drift rather than adapting silently."""
            nonlocal raw
            before = old.encode(); after = new.encode()
            if raw.count(before) != 1:
                raise ValueError('ADAPTATION_COUNT: ' + name)
            raw = raw.replace(before, after); substitutions.append([old, new])

        if name == 'scripts/h102_profile_config.py':
            start = original.index(b'BOOT_PINS = {\n'); end = original.index(b'\n}\n', start) + 3
            replace(original[start:end].decode(), 'BOOT_PINS = ' + repr(boot_pins))
        if name in ('scripts/h102_runtime_usb_prepare.py', 'scripts/h102_runtime_usb_rx.py'):
            replace('/opt/h102-sdk1-presets-20261008/profiles', CATALOG)
            replace('/opt/h102-iio-config-candidate-20261008/h102-built-in-sdk1-presets.json', APPROVED)
            replace('/boot/h102_logicrf_candidate16.bit', '/boot/h102_logicrf_master.bit')
            replace('1e1f9c6fa85000fc5133ee80d34a42a9a00dbd27e445ef139b75f83e00d491b9', PINS['bit'])
        if name == 'scripts/h102_sdk1_rf_r1.py':
            replace('/opt/h102-sdk1-presets-20261008/profiles', CATALOG)
        ast.parse(raw, feature_version=(3, 9))
        add(SCRIPTS + '/' + Path(name).name, raw)
        adaptations[Path(name).name] = dict(git_sha256=sha(original), product_sha256=sha(raw),
                                           substitutions=substitutions)
    profile_names = git('ls-tree', '-r', '--name-only', SOURCE_COMMIT,
                        'profiles/sdk1-candidate').decode().splitlines()
    if len(profile_names) != 203:
        raise ValueError('EXPECTED_29_TIMES_7_PROFILE_ASSETS')
    for name in profile_names:
        suffix = name.removeprefix('profiles/sdk1-candidate/')
        if suffix.split('/')[0] not in ids:
            raise ValueError('FOREIGN_PROFILE_DIRECTORY')
        add(CATALOG + '/' + suffix, blob(name))
    add(APPROVED, approved)
    with tarfile.open(fileobj=io.BytesIO(raw_inputs['modules']), mode='r:gz') as archive:
        members = archive.getmembers()
        if sum(m.isfile() for m in members) != 24:
            raise ValueError('MODULE_MEMBER_COUNT')
        allowed_dirs = {str(parent) for m in members if m.isfile()
                        for parent in PurePosixPath(m.name).parents if str(parent) != '.'}
        for member in members:
            name = member.name; path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name:
                raise ValueError('MODULE_MEMBER_PATH_OR_KIND')
            if member.isdir() and name in allowed_dirs:
                continue
            if not member.isfile() or not name.startswith('lib/modules/' + KERNEL + '/'):
                raise ValueError('MODULE_MEMBER_PATH_OR_KIND')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError('MODULE_MEMBER_UNREADABLE')
            # The pinned base has root-owned /lib -> usr/lib; use the real directory for assets
            # so trusted-ancestor checks agree while kernel module lookup follows the original link.
            add('/usr/' + name, stream.read())
    bootstrap = (project / 'overlays/h102/usr-local-lib/h102/sdk1_bootstrap.py').read_bytes()
    ast.parse(bootstrap, feature_version=(3, 9))
    add('/usr/local/lib/h102/bootstrap/sdk1_bootstrap.py', bootstrap)
    add('/etc/modules-load.d/h102-sdk1.conf', b'h102_axi_reg\nh102_axi_trig\nh102_profile_control\n')
    baseline = blob('overlays/h102/etc/systemd/system/h102-gnss-uart-baseline.service')
    baseline = baseline.replace(b'/usr/local/lib/h102/scripts/', (SCRIPTS + '/').encode())
    add('/etc/systemd/system/h102-gnss-uart-baseline.service', baseline)
    bootstrap_unit = '''[Unit]
Description=LogicRF H102 SDK1 managed default and source-off baseline
Requires=h102-lab-disable-tx.service h102-gnss-uart-baseline.service
Wants=network-online.target
After=local-fs.target network-online.target NetworkManager.service systemd-modules-load.service systemd-udev-settle.service h102-lab-disable-tx.service h102-gnss-uart-baseline.service
Before=iiod.service iiod_ffs.service h102-profile-control.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -B /usr/local/lib/h102/bootstrap/sdk1_bootstrap.py
TimeoutStartSec=260
RemainAfterExit=yes
Restart=no
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    add('/etc/systemd/system/h102-sdk1-bootstrap.service', bootstrap_unit.encode())
    broker = '''[Unit]
Description=LogicRF H102 SDK1 IIO preset broker
Requires=h102-sdk1-bootstrap.service
After=h102-sdk1-bootstrap.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -B SCRIPT/h102_profile_iio_broker.py --catalog CATALOG --approved APPROVED --log-directory /run/h102-profile-broker
Restart=on-failure
RestartSec=3
TimeoutStopSec=220
KillMode=control-group
UMask=0077

[Install]
WantedBy=multi-user.target
'''.replace('SCRIPT', SCRIPTS).replace('CATALOG', CATALOG).replace('APPROVED', APPROVED)
    add('/etc/systemd/system/h102-profile-control.service', broker.encode())
    for service in ('iiod', 'iiod_ffs'):
        add('/etc/systemd/system/' + service + '.service.d/30-h102-sdk1.conf',
            b'[Unit]\nRequires=h102-sdk1-bootstrap.service\nAfter=h102-sdk1-bootstrap.service\n')
    cli = '#!/bin/sh\nset -eu\nexec /usr/bin/python3 -B ' + SCRIPTS + '/h102_profile_config.py --stack sdk1-candidate --catalog ' + CATALOG + ' "$@"\n'
    add('/usr/local/bin/h102-config-sdk1', cli.encode(), 0o755)
    links = {'/etc/systemd/system/multi-user.target.wants/' + n: '../' + n for n in
             ('h102-gnss-uart-baseline.service', 'h102-sdk1-bootstrap.service', 'h102-profile-control.service')}
    if 'portable_host' in request:
        entry = request['portable_host']; path = Path(entry['path'])
        if (set(entry) != {'path', 'bytes', 'sha256'} or not path.is_absolute() or
                path.is_symlink() or not path.is_file()):
            raise ValueError('HOST_ARCHIVE_INPUT')
        host_raw = path.read_bytes()
        if len(host_raw) != entry['bytes'] or sha(host_raw) != entry['sha256']:
            raise ValueError('HOST_ARCHIVE_BYTES_OR_SHA')
        host_pins_raw = (project / 'manifests/h102-portable-host-pins.json').read_bytes()
        host_pins = json.loads(host_pins_raw)['source_files']
        if len(host_pins) != 10:
            raise ValueError('HOST_EXACT_TEN_FILES')
        with tarfile.open(fileobj=io.BytesIO(host_raw), mode='r:gz') as archive:
            members = archive.getmembers()
            if len(members) != 10 or {m.name for m in members} != set(host_pins):
                raise ValueError('HOST_ARCHIVE_MEMBER_SET')
            for member in members:
                if not member.isfile() or Path(member.name).name != member.name:
                    raise ValueError('HOST_ARCHIVE_MEMBER_KIND')
                raw = archive.extractfile(member).read()
                if len(raw) != member.size or sha(raw) != host_pins[member.name]:
                    raise ValueError('HOST_ARCHIVE_MEMBER_SHA: ' + member.name)
        add('/usr/share/h102/host-tools/linux-x86_64/runtime-wire-portable-p1.tar.gz', host_raw)
        add('/usr/share/h102/host-tools/linux-x86_64/manifest.json', host_pins_raw)
        add('/usr/share/h102/host-tools/linux-x86_64/README-zh.md',
            (project / 'docs/h102-image-host-tools-zh.md').read_bytes())
        add('/usr/share/h102/host-tools/linux-x86_64/portable-host-installation.md',
            (project / 'tools/runtime-wire-host/README.md').read_bytes())
        add('/usr/share/h102/host-tools/linux-x86_64/qualification.json',
            (project / 'docs/receipts/20261012-portable-host-board.json').read_bytes())
    entries = {n: dict(bytes=len(raw), sha256=sha(raw), mode=modes[n]) for n, raw in assets.items()}
    metadata = dict(schema=1, kernel=KERNEL, source_commit=SOURCE_COMMIT, boot_pins=boot_pins,
                    assets=entries, hardware_qualified=False, released=False)
    add('/etc/h102/sdk1-image.json', json_bytes(metadata))
    output.mkdir(mode=0o700)
    for name, raw in assets.items():
        destination = output / 'assets' / name.lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw); destination.chmod(modes[name])
    # The pinned Git validator is offline; invoke only load_package(trusted=False).
    sys.path.insert(0, str(output / 'assets' / SCRIPTS.lstrip('/')))
    import h102_profile_config as config
    config.configure_stack('sdk1-candidate')
    for name in ids:
        config.load_package(output / 'assets' / CATALOG.lstrip('/'), name, trusted=False)
    for name, entry in request.items():
        if name != 'schema' and sha(Path(entry['path']).read_bytes()) != (PINS.get(name) or entry['sha256']):
            raise ValueError('INPUT_CHANGED_DURING_PREPARATION')
    for name, expected in tool_sources.items():
        if sha((project / name).read_bytes()) != expected:
            raise ValueError('TOOL_INPUT_CHANGED_DURING_PREPARATION: ' + name)
    result = dict(schema=1, status='PASS_OFFLINE_ASSETS_NOT_IMAGE_BOOT_OR_BOARD',
                  source_commit=SOURCE_COMMIT, inputs=request, boot_pins=boot_pins,
                  tool_sources=tool_sources,
                  files={n: dict(bytes=len(raw), sha256=sha(raw), mode=modes[n]) for n, raw in assets.items()},
                  links=links, source_adaptations=adaptations, profile_count=29, script_count=107,
                  portable_host_present='portable_host' in request,
                  hardware_qualified=False, released=False)
    (output / 'asset-manifest.json').write_bytes(json_bytes(result))
    return result


def main() -> None:
    """Require exact input manifests and new output, without deployment or release options."""
    parser = argparse.ArgumentParser(description='Prepare H102 SDK1 installation assets')
    parser.add_argument('inputs', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = prepare(args.inputs.absolute(), args.output.absolute(), Path(__file__).resolve().parents[1])
    print(json.dumps({k: result[k] for k in ('status', 'source_commit', 'profile_count', 'script_count')}))


if __name__ == '__main__':
    main()

# End of file: prepare_h102_sdk1_assets.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
