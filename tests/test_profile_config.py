#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_profile_config.py
@brief      Test profile-source verification and commit/rollback after main failure.
@details    Execute real JSON/stream and transaction checks with modeled devices/systemd.
            Numeric edits construct negative tests only, never hardware-ready new profiles.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-07
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import h102_profile_config as tool


class FakeHardware:
    """Store modeled parameters and active state without presenting them as board results."""
    def __init__(self, package):
        self.actual = dict(parameters=package['parameters'], summary=(
            'Device clk(Hz): 300000000\nSSI interface: LVDS\nDuplex Mode: FDD\n'
            'RX Channel Mask: 0xc3\nTX Channel Mask: 0xc\n'))
        self.busy = False

    def idle(self):
        """Reject transactions when the model is busy."""
        if self.busy:
            raise RuntimeError('BUSY')

    def settings(self):
        """Model non-enable settings."""
        return {'gain': '30'}

    def stop(self):
        """Model source shutdown without device effects."""
        return []


class Cases(unittest.TestCase):
    """Exercise real package rejection and production transaction state changes offline."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = self.root / 'catalog'
        shutil.copytree(ROOT / 'profiles/presets', self.catalog)
        self.previous = tool.load_package(self.catalog, '40msps-20mhz-boot-default')
        self.target = tool.load_package(self.catalog, '40msps-20mhz-rx-a')

    def edit(self, name, transform, rehash=False):
        """Modify real files and optionally resign hashes to test independent parameter checks."""
        directory = self.catalog / self.target['id']
        path = directory / name
        value = json.loads(path.read_bytes())
        transform(value)
        path.write_text(json.dumps(value, indent=2) + '\n')
        if rehash:
            manifest = tool.read_json(directory / 'manifest.json')
            manifest['sha256'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
            (directory / 'manifest.json').write_text(json.dumps(manifest))

    def test_catalog_preserves_exact_baseline_bytes(self):
        self.assertEqual(self.target['blobs']['profile.json'],
            (ROOT / 'profiles/h102-lvds-40m-rx-a.json').read_bytes())
        self.assertFalse(self.target['manifest']['online_generation'])

    def test_shared_target_separates_commit_settings_from_rollback(self):
        """Run real transaction/finish logic; aligned model carriers retain original TX targets on failure."""
        class Radio(FakeHardware):
            def __init__(self,package):
                super().__init__(package)
                self.values={str(self.alt('',i,'')):str(2400000000 if i<2 else 2450000000) for i in range(4)}
            def alt(self,name,index,attribute):return Path('/model/frequency'+str(index))
            def settings(self):return dict(self.values)
            def read(self,path):return self.values[str(path)]
        target=copy.deepcopy(self.target);target['manifest']['rf_lo_topology']='shared-lo2'
        profile=json.loads(target['blobs']['profile.json'])
        profile['clocks'].update({f'{p}{c}LoSelect':2 for p in ('rx','tx') for c in (1,2)})
        target['blobs']['profile.json']=json.dumps(profile).encode()
        for failed in (False,True):
            directory=self.root/('shared-'+str(failed));directory.mkdir()
            hw=Radio(self.previous);original=hw.settings();state=directory/'active';journal=directory/'journal'
            def program(device,package,**kwargs):
                if failed and package['id']==target['id']:raise OSError('SHARED_INIT_FAILED')
                device.actual['parameters']=package['parameters'];return copy.deepcopy(device.actual)
            def cleanup(device,record):
                device.values=dict(record['original']);return dict(cleanup_passed=True)
            with patch.object(tool,'snapshot',side_effect=lambda h:copy.deepcopy(h.actual)), \
                 patch.object(tool,'program',side_effect=program), \
                 patch.object(tool.rf,'cleanup',side_effect=cleanup), \
                 patch.object(tool,'load_package',side_effect=lambda c,n,trusted=False:target if n==target['id'] else self.previous):
                if failed:
                    with self.assertRaisesRegex(OSError,'SHARED_INIT_FAILED'):
                        tool.transact(hw,target,self.previous,{},state,journal,90)
                else:tool.transact(hw,target,self.previous,{},state,journal,90)
                stored=tool.read_json(journal)
                self.assertEqual(stored['original'],original)
                self.assertEqual(set(stored['target_settings'].values()),{'2400000000'})
                result=tool.finish(hw,self.catalog,state,journal,not failed)
            self.assertEqual(result['transaction_status'],'rolled_back' if failed else 'applied')
            self.assertEqual(hw.settings(),original if failed else stored['target_settings'])
        hw=Radio(self.previous);different=hw.settings();different['/model/frequency1']='2300000000'
        with self.assertRaisesRegex(ValueError,'FREQUENCIES_DIFFER'):tool.target_settings(hw,different,target)
        profile['clocks']['tx1LoSelect']=1;target['blobs']['profile.json']=json.dumps(profile).encode()
        with self.assertRaisesRegex(ValueError,'MAPPING_MISMATCH'):tool.target_settings(hw,hw.settings(),target)

    def test_corrupt_stream_rejected(self):
        (self.catalog / self.target['id'] / 'stream.bin').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'DIGEST'):
            tool.load_package(self.catalog, self.target['id'])

    def test_wrong_version_rejected(self):
        self.edit('manifest.json', lambda d: d.update(api_version='68.21.6'))
        with self.assertRaisesRegex(ValueError, 'VERSION'):
            tool.load_package(self.catalog, self.target['id'])

    def test_changed_rate_not_hidden_by_rehash(self):
        self.edit('profile.json', lambda d: d['rx']['rxChannelCfg'][0]['profile'].update(
            rxOutputRate_Hz=20000000, rxInterfaceSampleRate_Hz=20000000), rehash=True)
        with self.assertRaisesRegex(ValueError, 'INDEPENDENT_RATES'):
            tool.load_package(self.catalog, self.target['id'])

    def test_bad_ssi_and_parameter_manifest_rejected(self):
        self.edit('profile.json', lambda d: d['tx']['txProfile'][0]['txSsiConfig'].update(
            numLaneSel=0), rehash=True)
        with self.assertRaisesRegex(ValueError, 'SSI'):
            tool.load_package(self.catalog, self.target['id'])
        self.setUp()
        self.edit('manifest.json', lambda d: d['parameters']['tx'][0].update(sample_rate_hz=10000000))
        with self.assertRaisesRegex(ValueError, 'PARAMETER_MISMATCH'):
            tool.load_package(self.catalog, self.target['id'])

    def test_compact_json_and_path_traversal_rejected(self):
        directory = self.catalog / self.target['id']
        path = directory / 'profile.json'
        path.write_text(json.dumps(json.loads(path.read_bytes())))
        manifest = tool.read_json(directory / 'manifest.json')
        manifest['sha256']['profile.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'TERMINATOR'):
            tool.load_package(self.catalog, self.target['id'])
        with self.assertRaisesRegex(ValueError, 'INVALID_PROFILE_ID'):
            tool.load_package(self.catalog, '../profile')

    def test_post_commits_and_failure_rolls_back(self):
        """Do not publish failed targets; execute and verify rollback while retaining profile identity."""
        real_load = tool.load_package
        for fail in (False, True):
            with self.subTest(main_failed=fail):
                directory = self.root / str(fail); directory.mkdir()
                state = directory / 'active.json'; journal = directory / 'journal.json'
                hw = FakeHardware(self.previous)
                calls = []
                def program(device, package, **kwargs):
                    calls.append(package['id'])
                    if fail and package['id'] == self.target['id']:
                        raise OSError('INIT_FAILED')
                    device.actual['parameters'] = package['parameters']
                    return copy.deepcopy(device.actual)
                with patch.object(tool, 'snapshot', side_effect=lambda h: copy.deepcopy(h.actual)), \
                     patch.object(tool, 'program', side_effect=program), \
                     patch.object(tool, 'quiet'), \
                     patch.object(tool.rf, 'cleanup', return_value={'cleanup_passed': True}), \
                     patch.object(tool, 'load_package', side_effect=lambda c, n, trusted=False: real_load(c, n)):
                    if fail:
                        with self.assertRaisesRegex(OSError, 'INIT_FAILED'):
                            tool.transact(hw, self.target, self.previous, {}, state, journal, 7)
                    else:
                        tool.transact(hw, self.target, self.previous, {}, state, journal, 7)
                    self.assertFalse(state.exists())
                    result = tool.finish(hw, self.catalog, state, journal, not fail)
                self.assertEqual(result['transaction_status'], 'rolled_back' if fail else 'applied')
                self.assertEqual(result['profile_id'], self.previous['id'] if fail else self.target['id'])
                self.assertEqual(result['configuration_id'], 7)
                self.assertEqual(calls[-1], self.previous['id'] if fail else self.target['id'])

    def test_rollback_failure_does_not_publish_active(self):
        hw = FakeHardware(self.previous); state = self.root / 'active.json'; journal = self.root / 'journal.json'
        real_load = tool.load_package
        with patch.object(tool, 'snapshot', side_effect=lambda h: h.actual), \
             patch.object(tool, 'program', side_effect=OSError('SPI_FAILED')), \
             patch.object(tool, 'load_package', side_effect=lambda c, n, trusted=False: real_load(c, n)):
            with self.assertRaises(OSError):
                tool.transact(hw, self.target, self.previous, {}, state, journal, 8)
            with self.assertRaises(OSError):
                tool.finish(hw, self.catalog, state, journal, False)
        self.assertFalse(state.exists())

    def test_busy_board_rejected_before_journal_or_write(self):
        hw = FakeHardware(self.previous); hw.busy = True
        with patch.object(tool, 'program') as program:
            with self.assertRaisesRegex(RuntimeError, 'BUSY'):
                tool.transact(hw, self.target, self.previous, {}, self.root / 'active', self.root / 'journal', 1)
            program.assert_not_called()
        self.assertFalse((self.root / 'journal').exists())

    def test_binary_offset_and_order(self):
        """Verify stream/profile chunk writes on regular files; sysfs behavior needs separate board tests."""
        for name in ('stream.bin', 'profile.json'):
            path = self.root / name
            tool.write_binary(path, self.target['blobs'][name])
            self.assertEqual(path.read_bytes(), self.target['blobs'][name])

    def test_dds_quantization_and_roundtrip_nominal(self):
        """Check fixed DDS quantization references and nominal Hz without granting board qualification."""
        self.assertEqual([tool.dds_quantized_hz(2000152, c) for c in (40000000, 20000000, 8000000)],
                         [2000152, 1999847, 2000152])
        hw = type('DDSModel', (), {})()
        hw.devices = {n: self.root / str(i) for i, n in enumerate(tool.rf.DDS_NAMES)}
        hw.alt = lambda name, i, attr: hw.devices[name] / ('dds' + str(i) + '_' + attr)
        hw.read = lambda path: '0' if path.name.endswith('_raw') else path.read_text().strip()
        for directory in hw.devices.values():
            directory.mkdir()
            (directory / 'out_altvoltage_sampling_frequency').write_text('40000000')
        original = {str(hw.alt(n, i, 'frequency')): '2000152' for n in tool.rf.DDS_NAMES for i in range(4)}
        target = copy.deepcopy(self.target)
        def plan(rate, saved):
            for channel in target['parameters']['tx']:
                channel['sample_rate_hz'] = rate
            return tool.dds_restore_plan(hw, original, saved, target)
        managed = None
        for rate in (20000000, 2000000, 4000000, 8000000, 40000000):
            current = plan(rate, managed)
            self.assertTrue(all(v['nominal_hz'] == 2000152 for v in current.values()))
            self.assertTrue(all(v['parked'] == (rate < 4000304) for v in current.values()))
            self.assertTrue(all(v['write_hz'] == (0 if v['parked'] else 2000152) for v in current.values()))
            original = {p: str(v['actual_hz']) for p, v in current.items()}
            for directory in hw.devices.values():
                (directory / 'out_altvoltage_sampling_frequency').write_text(str(rate))
            managed = {'dds_frequencies': current}
        self.assertEqual(set(original.values()), {'2000152'})
        key = next(iter(original)); original[key] = '1000000'
        self.assertEqual(plan(8000000, managed)[key]['nominal_hz'], 1000000)
        original[key] = '5000000'
        self.assertTrue(plan(8000000, managed)[key]['parked'])
        hw.read = lambda path: '1' if path.name.endswith('_raw') else path.read_text().strip()
        with self.assertRaisesRegex(ValueError, 'DDS_ACTIVE_OUT_OF_RANGE'):
            plan(8000000, managed)

    def test_dds_wrong_readback_clock_and_boundary_rejected(self):
        """Require exact DDS quantization; retain strict Hardware checks on all other attributes."""
        for hz in (-1, 4000001):
            with self.assertRaisesRegex(ValueError, 'OUT_OF_RANGE'):
                tool.dds_quantized_hz(hz, 8000000)
        self.assertEqual(tool.dds_quantized_hz(0, 8000000), 122)
        path = self.root / 'dds_frequency'
        clock = self.root / 'out_altvoltage_sampling_frequency'; clock.write_text('20000000')
        records = []
        hw = type('DDSModel', (), {})()
        hw.read = lambda p: '1999847' if p == path else p.read_text().strip()
        hw.record_write = records.append
        proxy = tool.DDSRestoreHardware(hw, {str(path): dict(nominal_hz=2000152,
            actual_hz=1999847, clock_hz=20000000)})
        self.assertEqual(proxy.write(path, '2000152'), '1999847')
        self.assertEqual(path.read_text().strip(), '2000152')
        self.assertTrue(records[-1]['readback_ok'])
        tool.verify_dds(hw, proxy.plan)
        hw.read = lambda p: '1999848' if p == path else p.read_text().strip()
        with self.assertRaisesRegex(RuntimeError, 'QUANTIZED_READBACK'):
            proxy.write(path, '2000152')
        self.assertFalse(records[-1]['readback_ok'])
        with self.assertRaisesRegex(RuntimeError, 'POST_DDS'):
            tool.verify_dds(hw, proxy.plan)
        clock.write_text('8000000')
        with self.assertRaisesRegex(RuntimeError, 'CLOCK_CHANGED'):
            proxy.write(path, '2000152')

    def test_reset_phy_recovery_requires_independent_sources_idle(self):
        """Do not claim PHY-off after ENODEV; require DDS zero and reject reload with active DMA."""
        hw = object.__new__(tool.rf.Hardware)
        hw.phy = self.root / 'unavailable-phy'
        hw.fixture = self.root
        hw.devices = {n: self.root / ('recovery-' + str(i)) for i, n in enumerate(tool.rf.DMA_NAMES)}
        for directory in hw.devices.values():
            (directory / 'buffer').mkdir(parents=True)
            (directory / 'buffer/enable').write_text('0')
        hw.alt = lambda name, i, attr: hw.devices[name] / ('dds' + str(i) + '_' + attr)
        for name in tool.rf.DDS_NAMES:
            for i in range(4):
                for attr in ('raw', 'scale'):
                    hw.alt(name, i, attr).write_text('1')
        records = []
        hw.record_write = records.append
        def write(path, value, tolerance=None):
            if path.parent == hw.phy:
                raise OSError(19, 'No such device')
            path.write_text(value)
        hw.write = write
        tool.recovery_quiet(hw)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(not r['readback_ok'] and r['recovery_phy_unavailable'] for r in records))
        self.assertTrue(all(hw.read(hw.alt(n, i, a)) == '0' for n in tool.rf.DDS_NAMES
                            for i in range(4) for a in ('raw', 'scale')))
        (hw.devices[tool.rf.DMA_NAMES[0]] / 'buffer/enable').write_text('1')
        with self.assertRaisesRegex(RuntimeError, 'RF_OR_DMA_BUSY'):
            tool.recovery_quiet(hw)
        hw.write = lambda *args: (_ for _ in ()).throw(OSError(5, 'I/O error'))
        with self.assertRaises(OSError) as error:
            tool.recovery_quiet(hw)
        self.assertEqual(error.exception.errno, 5)

    def test_post_dds_change_rolls_back_and_preserves_nominal(self):
        """Post detects DDS drift after main success and restores cross-rate nominal targets."""
        hw = FakeHardware(self.target)
        hw.devices = {tool.rf.DDS_NAMES[0]: self.root / 'dds0'}
        path = str(hw.devices[tool.rf.DDS_NAMES[0]] / 'frequency')
        journal = self.root / 'dds-journal.json'; active = self.root / 'dds-active.json'
        tool.atomic_save(journal, dict(identity={}, target_id=self.target['id'],
            previous_id=self.previous['id'], target_sha256=self.target['manifest']['sha256'],
            previous_sha256=self.previous['manifest']['sha256'], phase='programmed',
            configuration_id=9, original={path: '2000152'}, dds_frequencies={path:
                dict(nominal_hz=2000152, actual_hz=1999847, clock_hz=20000000)}))
        real_load = tool.load_package
        def restore(device, package, **kwargs):
            device.actual['parameters'] = package['parameters']
        with patch.object(tool, 'snapshot', side_effect=lambda h: h.actual), \
             patch.object(tool, 'verify_dds', side_effect=RuntimeError('POST_DDS_READBACK_MISMATCH')), \
             patch.object(tool, 'program', side_effect=restore) as program, \
             patch.object(tool.rf, 'cleanup', return_value={'cleanup_passed': True}), \
             patch.object(tool, 'load_package', side_effect=lambda c, n, trusted=False: real_load(c, n)):
            result = tool.finish(hw, self.catalog, active, journal, True)
        self.assertEqual(result['transaction_status'], 'rolled_back')
        self.assertEqual(result['profile_id'], self.previous['id'])
        self.assertEqual(result['dds_frequencies'][path],
            dict(nominal_hz=2000152, actual_hz=2000152, clock_hz=40000000, write_hz=2000152, parked=False))
        program.assert_called_once()


if __name__ == '__main__':
    unittest.main()

# End of file: test_profile_config.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
