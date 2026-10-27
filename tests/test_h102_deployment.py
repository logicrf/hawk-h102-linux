"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_h102_deployment.py
@brief      Test deployment rejection, real transfer/direct readback and read-only report boundaries.
@details    Use owned temporary regular files for the O_DIRECT transfer core, never physical SD.
            Model inventory, process and SSH inputs; do not claim full production block-device deployment.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.1
@date       2026-10-27
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import h102_sd_deploy as sd
import h102_check_new_board as check


class DeploymentTests(unittest.TestCase):
    """Use real small files to test destructive-entry rejection and actual I/O stage semantics."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='h102-deploy-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = bytes(range(256)) * 16384
        self.xz = lzma.compress(self.raw)
        self.pins = dict(raw_bytes=len(self.raw), raw_sha256=hashlib.sha256(self.raw).hexdigest(),
                         compressed_bytes=len(self.xz), compressed_sha256=hashlib.sha256(self.xz).hexdigest())

    def source(self, compressed=False):
        """Create owned fixed inputs; callers manage their opened lifecycle."""
        path = self.root / ('test.img.xz' if compressed else 'test.img')
        path.write_bytes(self.xz if compressed else self.raw)
        return path

    def test_preflight_raw_xz_and_corruption(self):
        """Verify both formats completely and reject same-length corruption and LFS pointers."""
        for compressed in (False, True):
            path = self.source(compressed)
            with path.open('rb') as source:
                self.assertEqual(sd.verify_image(source, self.pins)['compressed'], compressed)
            blob = bytearray(path.read_bytes())
            blob[len(blob) // 2] ^= 1
            path.write_bytes(blob)
            with path.open('rb') as source, self.assertRaisesRegex(ValueError, 'SHA256'):
                sd.verify_image(source, self.pins)
        path.write_text('version https://git-lfs.github.com/spec/v1\n')
        with path.open('rb') as source, self.assertRaisesRegex(ValueError, 'LFS_POINTER'):
            sd.verify_image(source, self.pins)

    def test_policy_rejects_partition_readonly_mounted_fixed_small_and_huge(self):
        """Reject every independent unsafe condition while accepting an idle removable whole disk."""
        good = dict(name='/dev/test', type='disk', rm=True, tran='usb', size=32_000_000_000,
                    ro=False, mountpoints=[None])
        self.assertEqual(sd.policy_blockers(good, 12_000_000_000), [])
        for change in [dict(type='part'), dict(type='loop'), dict(ro=True),
                       dict(rm=False, tran='nvme'), dict(size=8_000_000_000),
                       dict(size=4_000_000_000_000), dict(mountpoints=['/'])]:
            with self.subTest(change=change):
                self.assertTrue(sd.policy_blockers(dict(good, **change), 12_000_000_000))
        child = dict(good, name='/dev/test1', type='part', mountpoints=['/media/card'])
        self.assertTrue(sd.policy_blockers(dict(good, children=[child]), 12_000_000_000))

    def test_confirmation_changes_with_diskseq_capacity_or_path(self):
        identity = dict(device='/dev/test', major_minor='8:48', bytes=32_000_000_000,
                        diskseq=123, sysfs_path='/sys/fixed', model='reader', serial='same')
        original = sd.identity_token(identity)
        for change in [dict(diskseq=124), dict(bytes=31_000_000_000), dict(sysfs_path='/sys/other')]:
            self.assertNotEqual(original, sd.identity_token(dict(identity, **change)))

    def test_regular_target_is_rejected_by_production_inspector(self):
        with self.assertRaisesRegex(ValueError, 'BLOCK_DEVICE_REQUIRED'):
            sd.inspect_device(str(self.source()), 1)

    def test_exclusive_report_and_failure_before_target_open(self):
        """Reject bad sources before opening targets; preserve old reports and create no target file."""
        source = self.source()
        source.write_bytes(b'bad')
        report = self.root / 'result.json'
        args = argparse.Namespace(image=source, device='/dev/never-open', confirm='invalid', report=report)
        with mock.patch.object(sd.os, 'geteuid', return_value=0), mock.patch.object(sd, 'inspect_device', side_effect=AssertionError('must not inspect target')):
            self.assertEqual(sd.deploy(args, self.pins), 1)
        result = json.loads(report.read_text())
        self.assertEqual(result['phase'], 'verify_source')
        self.assertNotIn('destructive_write_started_at', result)
        before = report.read_bytes()
        with self.assertRaises(FileExistsError):
            sd.Report(report)
        self.assertEqual(report.read_bytes(), before)

    def test_native_short_writes_xz_direct_readback_and_corruption(self):
        """Use the same Linux FD for actual copy/fsync/O_DIRECT; corrupted readback must fail."""
        target = self.root / 'owned-target.img'
        with self.source(True).open('rb') as source, target.open('w+b', buffering=0) as dest:
            original_write = os.write
            with mock.patch.object(sd.os, 'write', side_effect=lambda fd, data: original_write(fd, data[:131072])):
                result = sd.copy_image(source, True, dest.fileno(), self.pins)
            self.assertEqual(result['bytes'], len(self.raw))
            self.assertTrue(sd.direct_readback(dest.fileno(), self.pins)['same_fd'])
            os.pwrite(dest.fileno(), b'X', 512)
            with self.assertRaisesRegex(ValueError, 'DIRECT_READBACK_SHA256_MISMATCH'):
                sd.direct_readback(dest.fileno(), self.pins)

    def test_zero_write_and_readback_no_silent_fallback(self):
        path = self.root / 'owned-failure.img'
        with self.source().open('rb') as source, path.open('w+b', buffering=0) as dest:
            with mock.patch.object(sd.os, 'write', return_value=0), self.assertRaisesRegex(OSError, 'ZERO_LENGTH_WRITE'):
                sd.copy_image(source, False, dest.fileno(), self.pins)
            dest.truncate(len(self.raw))
            with mock.patch.object(sd.os, 'readv', side_effect=OSError('direct not supported')):
                with self.assertRaisesRegex(OSError, 'direct not supported'):
                    sd.direct_readback(dest.fileno(), self.pins)

    def test_missing_eject_tool_is_explicit_not_ejected(self):
        device = dict(identity=dict(device='/dev/test'), blockers=[])
        with mock.patch.object(sd, 'inspect_device', return_value=device), mock.patch.object(sd, 'check_kernel_users'), mock.patch.object(sd.shutil, 'which', return_value=None):
            self.assertEqual(sd.eject_device(device, 1)['status'], 'NOT_EJECTED')


    def test_eject_failure_preserves_actual_write_readback_without_rewrite(self):
        """After real temporary-file I/O, model ejection refusal and require no rewrite."""
        target = self.root / 'owned-card.img'
        target.write_bytes(b'\0' * len(self.raw))
        device = dict(identity=dict(device=str(target)), blockers=[], confirm='test-only')
        args = argparse.Namespace(image=self.source(True), device=str(target),
                                  confirm='test-only', report=self.root / 'eject-busy.json')
        with mock.patch.object(sd.os, 'geteuid', return_value=0), \
                mock.patch.object(sd.shutil, 'which', return_value='/usr/bin/udisksctl'), \
                mock.patch.object(sd, 'inspect_device', return_value=device), \
                mock.patch.object(sd, 'check_kernel_users'), \
                mock.patch.object(sd, 'verify_open_device'), \
                mock.patch.object(sd, 'copy_image', wraps=sd.copy_image) as copy, \
                mock.patch.object(sd, 'eject_device', side_effect=ValueError('BLOCK_FD_IN_USE:123')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sd.deploy(args, self.pins | dict(version='1.2.1')), 3)
            self.assertEqual(copy.call_count, 1)
        report = json.loads(args.report.read_text())
        self.assertEqual(report['status'], 'WRITE_VERIFIED_NOT_EJECTED')
        self.assertEqual(report['write_readback'], 'PASS')
        self.assertTrue(report['readback']['direct'] and report['readback']['same_fd'])
        self.assertIn('BLOCK_FD_IN_USE', report['eject']['reason'])
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), self.pins['raw_sha256'])

    def test_eject_waits_for_transient_fd_but_never_ignores_live_user(self):
        """Model transient and persistent block FDs; never eject while an owner remains."""
        device = dict(identity=dict(device='/dev/test-only', major_minor='0:987654'), blockers=[])
        ok = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with mock.patch.object(sd, 'inspect_device', return_value=device) as inspect, \
                mock.patch.object(sd, 'check_kernel_users', side_effect=[ValueError('BLOCK_FD_IN_USE:1'), None]), \
                mock.patch.object(sd.time, 'sleep'), mock.patch.object(sd.shutil, 'which', return_value='udisksctl'), \
                mock.patch.object(sd.subprocess, 'run', return_value=ok) as eject:
            result = sd.eject_device(device, 1)
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(len(result['transient_block_fd_observations']), 1)
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual(eject.call_count, 1)
        with mock.patch.object(sd, 'inspect_device', return_value=device), \
                mock.patch.object(sd, 'check_kernel_users', side_effect=ValueError('BLOCK_FD_IN_USE:1')) as users, \
                mock.patch.object(sd.time, 'sleep'), mock.patch.object(sd.subprocess, 'run') as eject:
            with self.assertRaisesRegex(ValueError, 'BLOCK_FD_IN_USE'):
                sd.eject_device(device, 1)
            self.assertEqual(users.call_count, 6)
            eject.assert_not_called()

    def test_eject_identity_change_during_wait_never_touches_replacement(self):
        """Reject a replacement diskseq observed during the bounded idle wait."""
        device = dict(identity=dict(device='/dev/test-only', diskseq=1), blockers=[])
        changed = dict(identity=dict(device='/dev/test-only', diskseq=2), blockers=[])
        with mock.patch.object(sd, 'inspect_device', side_effect=[device, changed]), \
                mock.patch.object(sd, 'check_kernel_users', side_effect=ValueError('BLOCK_FD_IN_USE:1')), \
                mock.patch.object(sd.time, 'sleep'), mock.patch.object(sd.subprocess, 'run') as eject:
            with self.assertRaisesRegex(ValueError, 'DEVICE_CHANGED_OR_BUSY'):
                sd.eject_device(device, 1)
            eject.assert_not_called()


class BoardCheckTests(unittest.TestCase):
    """Test cloned identities, basic/untested scope and fixed read-only SSH transport."""
    def identity(self, machine='1' * 32, mac='02:12:34:56:78:90', fingerprint='SHA256:a'):
        return dict(machine_id=machine, boot_id='a' * 36, MAC=mac,
                    ssh_public_fingerprints={'ssh-ed25519': fingerprint})

    def test_duplicate_identity_and_distinct_new_device(self):
        old = dict(tool='h102_check_new_board', identity=self.identity())
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_DEVICE_IDENTITY'):
            check.compare_identity(dict(identity=self.identity()), old)
        current = self.identity(machine='2' * 32, mac='02:12:34:56:78:91', fingerprint='SHA256:b')
        self.assertTrue(check.compare_identity(dict(identity=current), old)['unique_machine_id'])

    def test_real_public_key_only_identity_reads(self):
        with tempfile.TemporaryDirectory(prefix='h102-readonly-') as tmp:
            root = Path(tmp)
            fields = {'/etc/machine-id': '1' * 32, '/proc/sys/kernel/random/boot_id': '12345678-1234-1234-1234-123456789abc',
                      '/sys/class/net/eth0/address': '02:12:34:56:78:90',
                      '/etc/ssh/ssh_host_ed25519_key.pub': 'ssh-ed25519 ' + base64.b64encode(b'public-key-fixture').decode()}
            for name, value in fields.items():
                path = root / name.lstrip('/')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            private = root / 'etc/ssh/ssh_host_ed25519_key'
            private.write_text('private-fixture-never-read')
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = check.Board({}, root=root).identity()
            self.assertEqual(result['machine_id'], '1' * 32)
            self.assertTrue(result['ssh_public_fingerprints']['ssh-ed25519'].startswith('SHA256:'))
            self.assertNotIn('private-fixture', json.dumps(result))
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_metadata_sha_precedes_asset_paths_and_checks_do_not_mask_failure(self):
        with tempfile.TemporaryDirectory(prefix='h102-metadata-') as tmp:
            root = Path(tmp)
            path = root / 'etc/h102/sdk1-image.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"assets":{"/etc/ssh/private-key":{}}}')
            board = check.Board(dict(metadata_path='/etc/h102/sdk1-image.json', metadata_sha256='0' * 64), root=root)
            with self.assertRaisesRegex(ValueError, 'METADATA_SHA256_MISMATCH'):
                board.verify_metadata()
            self.assertIsNone(board.metadata)
            result = check.finalize(dict(checks=[dict(status='FAIL'), dict(status='PASS'), dict(status='NOT_RUN')]))
            self.assertEqual(result['status'], 'FAIL_BASIC_CHECKS')
            self.assertEqual(check.finalize(dict(checks=[dict(status='PASS'), dict(status='NOT_RUN')]))['status'], 'PASS_BASIC_CHECKS_ONLY')

    def test_ssh_strict_trust_readonly_probe_and_no_iq(self):
        args = argparse.Namespace(host='10.1.2.3', user='logicrf', known_hosts=None, identity_file=None)
        value = dict(tool='h102_check_new_board', read_only=True, checks=[], not_run=['IQ_capture'])
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps(value).encode(), stderr=b'')
        with mock.patch.object(check.subprocess, 'run', return_value=response) as run, mock.patch.object(check.socket, 'create_connection'):
            with mock.patch.object(check.shutil, 'which', return_value=None):
                result = check.remote_probe(args, dict(schema=1))
        argv = run.call_args.args[0]
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('python3 - --probe', argv[-1])
        self.assertNotIn('sudo', argv[-1])
        self.assertIn('IQ_capture', result['not_run'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        args.host = '-oProxyCommand=bad'
        with self.assertRaisesRegex(ValueError, 'INVALID_SSH_HOST'):
            check.remote_probe(args, {})

    def test_duplicate_unrelated_iio_sensors_do_not_block_sdr_discovery(self):
        """Require uniqueness only for SDR devices, excluding unrelated sensors with matching names."""
        with tempfile.TemporaryDirectory(prefix='h102-iio-names-') as tmp:
            root = Path(tmp)
            for i in range(2):
                folder = root / f'sys/bus/iio/devices/iio:device{i}'
                folder.mkdir(parents=True)
                (folder / 'name').write_text('same-unrelated-sensor')
            board = check.Board({}, root=root)
            with self.assertRaisesRegex(ValueError, 'MISSING_REQUIRED_IIO_DEVICE'):
                board.iio_idle()


if __name__ == '__main__':
    unittest.main()

# End of file: test_h102_deployment.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
