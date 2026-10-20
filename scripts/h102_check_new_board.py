#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_check_new_board.py
@brief      Read-only verification of H102 release assets, identity, services and idle state.
@details    Run locally on the board or over existing SSH with strict host-key checking.
            Do not install, import controllers, configure, stream or transmit. On the host create only
            a new report; basic checks do not qualify IQ, RF, USB or continuous streaming.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys

PINS = Path(__file__).resolve().parents[1] / 'manifests/h102-deployment-1.2.0.json'
DMA_NAMES = ('axi-adrv9002-rx-lpc', 'axi-adrv9002-rx2-lpc',
             'axi-adrv9002-tx-lpc', 'axi-adrv9002-tx2-lpc')
"""Use stable sampling-device names rather than variable iio:device indices."""


def utc_now() -> str:
    """Record the actual observation time instead of reusing a historical receipt time."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def require(condition: bool, error: str) -> None:
    """Use checks that remain active under python -O."""
    if not condition:
        raise ValueError(error)


def digest(path: Path) -> str:
    """Hash regular files with bounded memory; device private keys are never inputs."""
    sha = hashlib.sha256()
    with path.open('rb') as source:
        while True:
            raw = source.read(4 * 1024 * 1024)
            if not raw:
                break
            sha.update(raw)
    return sha.hexdigest()


class Board:
    """Read one board's status; root/runner injection is reserved for offline fixtures.

    CLI callers cannot redirect the hardware root. All commands are queries, avoiding the
    configuration manager's lock-file effects. One failed diagnostic does not suppress others.
    """
    def __init__(self, pins: dict, root=Path('/'), runner=None):
        self.pins, self.root = pins, root
        self.runner = runner or self.command
        self.metadata = None
        self.devices = {}
        self.checks = []

    def path(self, name: str) -> Path:
        """Map fixed absolute paths to the board or fixture root, rejecting parent traversal."""
        path = Path(name)
        require(path.is_absolute() and '..' not in path.parts, 'INVALID_FIXED_PATH')
        return self.root / name.lstrip('/')

    def text(self, name: str) -> str:
        """Read fixed text attributes and preserve missing-file or permission failures."""
        return self.path(name).read_text().strip('\0\n ')

    @staticmethod
    def command(argv: list[str]) -> str:
        """Bound query execution and retain nonzero exit status."""
        result = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=30)
        return result.stdout.strip()

    def check(self, name: str, function) -> None:
        """Record actual observations; callers explicitly mark missing trusted prerequisites NOT_RUN."""
        try:
            detail = function()
            self.checks.append(dict(name=name, status='PASS', detail=detail))
        except Exception as error:
            self.checks.append(dict(name=name, status='FAIL', error=f'{type(error).__name__}: {error}'))

    def identity(self) -> dict:
        """Read per-device identity and public-key fingerprints, never private keys."""
        machine = self.text('/etc/machine-id')
        boot = self.text('/proc/sys/kernel/random/boot_id')
        mac = self.text('/sys/class/net/eth0/address').lower()
        require(bool(re.fullmatch('[0-9a-f]{32}', machine)) and int(machine, 16) != 0, 'INVALID_MACHINE_ID')
        require(bool(re.fullmatch('[0-9a-f-]{36}', boot)), 'INVALID_BOOT_ID')
        require(bool(re.fullmatch('(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac))
                and mac not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff')
                and not int(mac[:2], 16) & 1, 'INVALID_ETHERNET_MAC')
        public = {}
        for path in sorted(self.path('/etc/ssh').glob('ssh_host_*_key.pub')):
            fields = path.read_text().split()
            require(len(fields) >= 2, 'INVALID_SSH_PUBLIC_KEY')
            raw = base64.b64decode(fields[1], validate=True)
            require(bool(raw), 'EMPTY_SSH_PUBLIC_KEY')
            public[fields[0]] = 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        require(bool(public), 'NO_SSH_HOST_PUBLIC_KEY')
        return dict(machine_id=machine, boot_id=boot, MAC=mac, ssh_public_fingerprints=public)

    def model_kernel(self) -> dict:
        """Check actual FDT board identity and running kernel, not installed filenames alone."""
        model = self.text('/proc/device-tree/model')
        kernel = self.text('/proc/sys/kernel/osrelease')
        require('LogicRF H102' in model, 'NOT_H102_DEVICE_TREE')
        require(kernel == self.pins['kernel'], 'RUNNING_KERNEL_MISMATCH')
        return dict(model=model, kernel=kernel)

    def verify_metadata(self) -> dict:
        """Verify metadata hash before using assets; the released RC2 build marker remains valid."""
        path = self.path(self.pins['metadata_path'])
        require(path.is_file() and not path.is_symlink(), 'METADATA_NOT_REGULAR')
        require(digest(path) == self.pins['metadata_sha256'], 'METADATA_SHA256_MISMATCH')
        value = json.loads(path.read_text())
        require(value['schema'] == 1 and value['kernel'] == self.pins['kernel'], 'METADATA_STACK_MISMATCH')
        require(value['boot_pins'] == self.pins['boot_pins'], 'METADATA_BOOT_PINS_MISMATCH')
        require(len(value['assets']) == self.pins['assets_count'], 'METADATA_ASSET_COUNT')
        self.metadata = value
        return dict(sha256=self.pins['metadata_sha256'], internal_version=value['version'],
                    distribution_version=self.pins['version'], assets_count=len(value['assets']))

    def assets(self) -> dict:
        """Verify 586 assets, metadata and four links without changing installed files."""
        errors = []
        for name, wanted in self.metadata['assets'].items():
            try:
                path = self.path(name)
                info = path.lstat()
                require(stat.S_ISREG(info.st_mode), 'NOT_REGULAR')
                require(info.st_size == wanted['bytes'] and digest(path) == wanted['sha256'], 'DIGEST_OR_SIZE')
                require(info.st_uid == 0 and not info.st_mode & 0o022, 'UNTRUSTED_WRITABLE_ASSET')
            except Exception as error:
                errors.append(dict(path=name, error=str(error)))
        for name, wanted in self.pins['links'].items():
            try:
                path = self.path(name)
                require(path.is_symlink() and os.readlink(path) == wanted, 'LINK_TARGET')
            except Exception as error:
                errors.append(dict(path=name, error=str(error)))
        if errors:
            raise ValueError(json.dumps(errors, ensure_ascii=False))
        return dict(files_verified=self.pins['files_count'], links_verified=len(self.pins['links']),
                    boot_files_sha256=self.pins['boot_pins'], scope='installed_bytes_not_FPGA_readback')

    def profiles(self) -> dict:
        """Verify exactly 58 packages and 29 presets in two LO modes, without claiming data tests."""
        root = self.path('/usr/local/lib/h102-config-sdk1/profiles')
        manifests = list(root.glob('*/manifest.json'))
        ids, logical, modes = [], set(), set()
        for path in manifests:
            value = json.loads(path.read_text())
            profile = value['id']
            require(path.parent.name == profile, 'PROFILE_DIRECTORY_ID_MISMATCH')
            require((value['api_version'], value['firmware_version'], value['stream_version']) ==
                    (self.pins['api_version'], self.pins['firmware_version'], self.pins['stream_version']),
                    'PROFILE_SOFTWARE_STACK_MISMATCH')
            ids.append(profile)
            logical.add(value.get('logical_profile_id', profile.removesuffix('-common')))
            modes.add(value.get('rf_lo_topology', 'independent'))
        require(sorted(ids) == self.pins['profiles'] and len(logical) == 29
                and modes == {'independent', 'shared-lo2'}, 'PROFILE_58_29_OR_LO_MODE_MISMATCH')
        return dict(packages=len(ids), logical=len(logical), modes=sorted(modes))

    def iio_idle(self) -> dict:
        """Read four-channel rate/bandwidth and source enables without stopping existing work."""
        names = ('adrv9002-phy', 'h102-profile-control') + DMA_NAMES
        for path in self.path('/sys/bus/iio/devices').glob('iio:device*'):
            if (path / 'name').is_file():
                name = (path / 'name').read_text().strip()
                if name not in names:
                    continue
                require(name not in self.devices, 'DUPLICATE_IIO_DEVICE_NAME')
                self.devices[name] = path
        require(all(name in self.devices for name in names), 'MISSING_REQUIRED_IIO_DEVICE')
        phy = self.devices['adrv9002-phy']
        settings = {}
        for direction in ('in', 'out'):
            for channel in (0, 1):
                for suffix, wanted in [('sampling_frequency', 40000000), ('rf_bandwidth', 20000000)]:
                    key = f'{direction}_voltage{channel}_{suffix}'
                    actual = int((phy / key).read_text())
                    require(actual == wanted, 'NOT_FIRSTBOOT_DEFAULT:' + key)
                    settings[key] = actual
        for channel in (0, 1):
            require((phy / f'out_voltage{channel}_en').read_text().strip() == '0', 'TX_NOT_OFF')
        for name in DMA_NAMES:
            require((self.devices[name] / 'buffer/enable').read_text().strip() == '0', 'DMA_NOT_IDLE:' + name)
        for name in DMA_NAMES[2:]:
            raw = list(self.devices[name].glob('out_altvoltage*_raw'))
            require(len(raw) == 4 and all(x.read_text().strip() == '0' for x in raw), 'DDS_NOT_OFF:' + name)
        require(self.text('/proc/sys/kernel/random/boot_id') == self.initial_identity['boot_id'], 'BOOT_CHANGED')
        # Read broker-published IIO attributes without accessing private transaction files or sudo.
        state = json.loads((self.devices['h102-profile-control'] / 'active_info').read_text())
        require(state['active'] == self.pins['default_profile']
                and state['boot_id'] == self.initial_identity['boot_id'], 'DEFAULT_MANAGED_STATE_MISMATCH')
        return dict(devices=list(names), default_profile=state['active'], settings=settings,
                    sources_off=True, scope='readback_only_no_buffers_created')

    def root_expansion(self) -> dict:
        """Check that the SD partition and ext4 filesystem use remaining capacity; do not resize."""
        info = self.path('/').stat()
        block = self.path(f'/sys/dev/block/{os.major(info.st_dev)}:{os.minor(info.st_dev)}').resolve()
        require(block.name == 'mmcblk0p2', 'ROOT_NOT_H102_SD_PARTITION')
        start = int((block / 'start').read_text())
        size = int((block / 'size').read_text())
        total = int((block.parent / 'size').read_text())
        require(start == 4218880 and 0 <= total - start - size <= 7, 'ROOT_PARTITION_NOT_EXPANDED')
        fs = os.statvfs(self.path('/'))
        fs_bytes = fs.f_blocks * fs.f_frsize
        require(size * 512 * 0.9 <= fs_bytes <= size * 512, 'ROOT_FILESYSTEM_NOT_EXPANDED')
        return dict(partition_bytes=size * 512, card_bytes=total * 512, filesystem_bytes=fs_bytes)

    def services(self) -> dict:
        """Query actual systemd state without starting, restarting or resetting services."""
        units = ('h102-sdk1-bootstrap.service', 'h102-profile-control.service',
                 'iiod_ffs.service', 'h102-network-affinity.service')
        raw = self.runner(['systemctl', 'show', '--property=Id,ActiveState,SubState,Result', *units])
        rows = [dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                for block in raw.split('\n\n') if block.strip()]
        require({x['Id'] for x in rows} == set(units), 'SYSTEMD_UNIT_INVENTORY')
        require(all(x['ActiveState'] == 'active' and x['Result'] == 'success'
                    and x['SubState'] == ('running' if x['Id'] in units[1:3] else 'exited')
                    for x in rows), 'CORE_SERVICE_NOT_READY')
        failed = self.runner(['systemctl', '--failed', '--no-legend', '--plain', '--no-pager'])
        require(not failed.strip(), 'FAILED_SERVICES:' + failed)
        return dict(units=rows, failed_services=[])

    def network(self) -> dict:
        """Check Gigabit link, address and port 30431 without requesting IIO sample data."""
        require(self.text('/sys/class/net/eth0/carrier') == '1', 'ETHERNET_LINK_DOWN')
        speed = int(self.text('/sys/class/net/eth0/speed'))
        require(speed == 1000, 'GIGABIT_LINK_REQUIRED')
        rows = json.loads(self.runner(['ip', '-j', '-4', 'address', 'show', 'dev', 'eth0']))
        addresses = [a['local'] for row in rows for a in row.get('addr_info', []) if a.get('scope') == 'global']
        require(bool(addresses), 'NO_ETHERNET_IPV4')
        listen = False
        for filename in ('/proc/net/tcp', '/proc/net/tcp6'):
            if self.path(filename).exists():
                listen |= any(row.split()[1].endswith(f':{30431:04X}') and row.split()[3] == '0A'
                              for row in self.text(filename).splitlines()[1:])
        require(listen, 'IIOD_30431_NOT_LISTENING')
        return dict(speed_mbps=speed, ipv4=addresses, iiod_port=30431)

    def collect(self) -> dict:
        """Return a dated identity-bound report and list data/RF checks that did not run."""
        self.initial_identity = {}
        self.check('identity', self.identity)
        if self.checks[-1]['status'] == 'PASS':
            self.initial_identity = self.checks[-1]['detail']
        self.check('model_and_running_kernel', self.model_kernel)
        self.check('fixed_release_metadata', self.verify_metadata)
        if self.metadata is not None:
            self.check('installed_assets_and_links', self.assets)
            self.check('profile_catalog', self.profiles)
        else:
            for name in ('installed_assets_and_links', 'profile_catalog'):
                self.checks.append(dict(name=name, status='NOT_RUN', reason='UNTRUSTED_OR_MISSING_METADATA'))
        self.check('iio_default_idle', self.iio_idle)
        self.check('root_expansion', self.root_expansion)
        self.check('services', self.services)
        self.check('network', self.network)
        self.check('identity_unchanged_during_check', lambda: self.identity_stable())
        result = dict(schema=1, tool='h102_check_new_board', checked_at=utc_now(),
                      release_version=self.pins['version'], identity=self.initial_identity,
                      checks=self.checks, read_only=True,
                      not_run=['IQ_capture', 'RF_TX', 'RF_loopback', 'USB_data', 'continuous_stream',
                               'GNSS_UTC_precision', 'full_profile_matrix'])
        return finalize(result)

    def identity_stable(self) -> dict:
        """Fail if boot or device identity changes during inspection; never combine two boots."""
        after = self.identity()
        require(bool(self.initial_identity) and after == self.initial_identity, 'DEVICE_IDENTITY_CHANGED')
        return dict(unchanged=True)


def finalize(report: dict) -> dict:
    """Any basic FAIL fails the result; NOT_RUN is not successful data transfer."""
    report['status'] = 'FAIL_BASIC_CHECKS' if any(x['status'] == 'FAIL' for x in report['checks']) else 'PASS_BASIC_CHECKS_ONLY'
    return report


def compare_identity(report: dict, previous: dict) -> dict:
    """Compare complete identities from two distinct boards, not reruns of the same board."""
    require(previous.get('tool') == 'h102_check_new_board' and previous.get('identity'), 'PREVIOUS_REPORT_HAS_NO_IDENTITY')
    current, old = report['identity'], previous['identity']
    require(bool(current), 'CURRENT_IDENTITY_NOT_AVAILABLE')
    repeated = [key for key in ('machine_id', 'MAC') if current[key] == old[key]]
    shared = set(current['ssh_public_fingerprints']) & set(old['ssh_public_fingerprints'])
    require(bool(shared), 'NO_COMMON_SSH_KEY_ALGORITHM_FOR_COMPARISON')
    repeated += ['ssh:' + key for key in shared
                 if current['ssh_public_fingerprints'][key] == old['ssh_public_fingerprints'][key]]
    require(not repeated, 'DUPLICATE_DEVICE_IDENTITY:' + ','.join(repeated))
    return dict(unique_machine_id=True, unique_MAC=True, unique_SSH_public_keys=True)


def remote_probe(args, pins: dict) -> dict:
    """Run this source in RAM over existing strict-key SSH without passwords or installation."""
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', args.host)), 'INVALID_SSH_HOST')
    require(bool(re.fullmatch(r'[a-z_][a-z0-9_-]*', args.user)), 'INVALID_SSH_USERNAME')
    payload = base64.b64encode(json.dumps(pins).encode()).decode()
    command = ['ssh', '-T', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10']
    if args.known_hosts:
        require(args.known_hosts.is_file(), 'KNOWN_HOSTS_FILE_MISSING')
        command += ['-o', 'UserKnownHostsFile=' + str(args.known_hosts.resolve())]
    if args.identity_file:
        command += ['-i', str(args.identity_file)]
    probe = 'python3 - --probe --pins-base64 ' + shlex.quote(payload)
    command += [args.user + '@' + args.host, probe]
    result = subprocess.run(command, input=Path(__file__).read_bytes(), capture_output=True, timeout=180)
    if result.returncode not in (0, 1) or not result.stdout.strip():
        raise RuntimeError('SSH_OR_PROBE_FAILED: ' + result.stderr.decode(errors='replace')[-1500:])
    try:
        report = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError('REMOTE_PROBE_DID_NOT_RETURN_JSON: ' + result.stderr.decode(errors='replace')[-1500:]) from error
    require(report.get('tool') == 'h102_check_new_board' and report.get('read_only') is True, 'INVALID_REMOTE_PROBE_RESPONSE')
    try:
        with socket.create_connection((args.host, 30431), timeout=5):
            pass
        report['checks'].append(dict(name='PC_to_IIOD_TCP', status='PASS', detail=dict(host=args.host, port=30431)))
    except OSError as error:
        report['checks'].append(dict(name='PC_to_IIOD_TCP', status='FAIL', error=str(error)))
    if shutil.which('iio_info'):
        query = subprocess.run(['iio_info', '-u', 'ip:' + args.host], capture_output=True, timeout=20)
        names = ('h102-profile-control', 'adrv9002-phy') + DMA_NAMES
        passed = query.returncode == 0 and all(x.encode() in query.stdout for x in names)
        report['checks'].append(dict(name='network_IIO_enumeration', status='PASS' if passed else 'FAIL',
                                     detail=dict(returncode=query.returncode, required_devices=list(names))))
    else:
        report['checks'].append(dict(name='network_IIO_enumeration', status='NOT_RUN', reason='PC_iio_info_not_installed_use_GUI_for_client_check'))
    return report


def main(argv=None) -> int:
    """Run on board or host SSH, creating a new report without device or service changes."""
    parser = argparse.ArgumentParser(description='Read-only H102 1.2.0 first-boot checks; no IQ or TX start')
    parser.add_argument('--host', help='Board IP/hostname for host-side checks; omit to run on the H102')
    parser.add_argument('--user', default='logicrf')
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--identity-file', type=Path, help='Existing SSH key path; passed only to SSH, never read into the report')
    parser.add_argument('--compare-with', type=Path, action='append', default=[])
    parser.add_argument('--report', type=Path, help='New JSON report path with an existing parent directory')
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--pins-base64', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        pins = json.loads(base64.b64decode(args.pins_base64, validate=True))
        report = Board(pins).collect()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status'].startswith('PASS') else 1
    require(args.report is not None, 'NEW_REPORT_PATH_REQUIRED')
    # Reserve the report path exclusively before running checks.
    fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            pins = json.loads(PINS.read_text())
            require(pins['schema'] == 1 and pins['version'] == '1.2.0', 'INVALID_RELEASE_PINS')
            if args.host:
                report = remote_probe(args, pins)
            else:
                report = Board(pins).collect()
                report['checks'].append(dict(name='network_IIO_enumeration', status='NOT_RUN', reason='LOCAL_BOARD_ONLY_USE_PC_OR_GUI'))
            for previous in args.compare_with:
                try:
                    detail = compare_identity(report, json.loads(previous.read_text()))
                    report['checks'].append(dict(name='identity_unique_vs:' + previous.name, status='PASS', detail=detail))
                except Exception as error:
                    report['checks'].append(dict(name='identity_unique_vs:' + previous.name, status='FAIL', error=str(error)))
            if not args.compare_with:
                report['checks'].append(dict(name='cross_device_identity_uniqueness', status='NOT_RUN', reason='NO_PREVIOUS_BOARD_REPORT_SUPPLIED'))
            finalize(report)
        except Exception as error:
            report = dict(schema=1, tool='h102_check_new_board', status='FAIL_BASIC_CHECKS', read_only=True,
                          checked_at=utc_now(), error=f'{type(error).__name__}: {error}')
        with os.fdopen(fd, 'w') as target:
            fd = None
            json.dump(report, target, ensure_ascii=False, indent=2)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        print(json.dumps(dict(status=report['status'], report=str(args.report), read_only=True), ensure_ascii=False))
        return 0 if report['status'].startswith('PASS') else 1
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps(dict(status='FAIL', error=f'{type(exc).__name__}: {exc}'), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

# End of file: h102_check_new_board.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
