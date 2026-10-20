"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_network_performance.py
@brief      Test network add-on prerequisites and recovery using real files and flock.
@details    Model the filesystem root explicitly; production CLI exposes no alternate root.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-19
"""
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'scripts/h102_network_performance.py'
spec = importlib.util.spec_from_file_location('h102_network_performance', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NetworkPerformanceTests(unittest.TestCase):
    """Check immutable originals, busy rejection, identity/drift handling and partial-write recovery."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='h102-netperf-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        values = {
            'proc/device-tree/model':'LogicRF H102\0',
            'proc/sys/kernel/random/boot_id':'test-boot', 'etc/machine-id':'test-machine',
            'sys/class/net/eth0/address':'02:00:00:00:00:01', 'sys/class/net/eth0/ifindex':'2',
            'sys/class/net/eth0/gro_flush_timeout':'0', 'sys/class/net/eth0/napi_defer_hard_irqs':'0',
            'proc/interrupts':'47: 10 20 GIC eth0\n', 'proc/irq/47/effective_affinity_list':'1',
        }
        for name,value in values.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        driver = self.root/'drivers/macb'
        driver.mkdir(parents=True)
        link = self.root/'sys/class/net/eth0/device/driver'
        link.parent.mkdir(parents=True)
        link.symlink_to(driver, target_is_directory=True)
        for index,name in enumerate(sorted(module.DEVICES)):
            path = self.root/'sys/bus/iio/devices'/('iio:device'+str(index))
            path.joinpath('buffer').mkdir(parents=True)
            (path/'name').write_text(name)
            (path/'buffer/enable').write_text('0')
        self.root.joinpath('run/lock').mkdir(parents=True)
        self.directory = self.root/'run/h102-network-performance'
        self.policy = module.NetworkPerformance(self.directory, self.root, require_root=False)

    def test_apply_repeat_stop_and_restart_keep_first_original(self):
        """Repeated normal lifecycles restore the first original, never save the target as original."""
        self.assertEqual(self.policy.apply()['status'],'APPLIED')
        original = self.directory/'original.json'
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        self.assertEqual(self.policy.current(),module.DESIRED)
        self.policy.apply()
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),digest)
        self.assertEqual(self.policy.restore()['actual'],{'gro_flush_timeout':'0','napi_defer_hard_irqs':'0'})
        self.policy.apply()
        self.policy.restore()
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),digest)

    def test_partial_write_failure_restores_and_independent_post_is_repeatable(self):
        """A failed second write restores the first attribute; repeated post preserves originals."""
        original_write = self.policy._write
        def fail_second(name,value):
            if name=='napi_defer_hard_irqs' and value=='2':
                raise OSError('second sysfs write failed')
            original_write(name,value)
        self.policy._write = fail_second
        with self.assertRaisesRegex(OSError,'second sysfs'):
            self.policy.apply()
        self.assertEqual(self.policy.current(),{'gro_flush_timeout':'0','napi_defer_hard_irqs':'0'})
        self.assertEqual(self.policy.restore()['status'],'RESTORED')

    def test_boot_change_does_not_restore_another_instance(self):
        """Reject old-boot writes even if current attributes equal the tool's targets."""
        self.policy.apply()
        self.root.joinpath('proc/sys/kernel/random/boot_id').write_text('another-boot')
        with self.assertRaisesRegex(ValueError,'IDENTITY'):
            self.policy.restore()
        self.assertEqual(self.policy.current(),module.DESIRED)

    def test_external_parameter_change_is_not_overwritten(self):
        """Reject unexplained administrator drift instead of overwriting it as apparent success."""
        self.policy.apply()
        self.root.joinpath('sys/class/net/eth0/gro_flush_timeout').write_text('12345')
        with self.assertRaisesRegex(RuntimeError,'EXTERNAL_CHANGE'):
            self.policy.restore()
        self.assertEqual(self.policy.current()['gro_flush_timeout'],'12345')

    def test_active_dma_refuses_before_original_or_network_write(self):
        """Any active DMA prevents recording misleading originals or changing network attributes."""
        next(self.root.joinpath('sys/bus/iio/devices').glob('*/buffer/enable')).write_text('1')
        with self.assertRaisesRegex(RuntimeError,'IIO_DATA_BUSY'):
            self.policy.apply()
        self.assertFalse((self.directory/'original.json').exists())
        self.assertEqual(self.policy.current(),{'gro_flush_timeout':'0','napi_defer_hard_irqs':'0'})

    def test_existing_owner_lock_refuses_without_network_writes(self):
        """Reject another legitimate lock owner without stopping its session or retrying hardware."""
        with (self.root/'run/lock'/module.LOCKS[0]).open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.policy.apply()
        self.assertEqual(self.policy.current(),{'gro_flush_timeout':'0','napi_defer_hard_irqs':'0'})

    def test_wrong_irq_distribution_refuses_before_writes(self):
        """Preserve the verified CPU1 IRQ prerequisite; performance tools do not change routing."""
        self.root.joinpath('proc/irq/47/effective_affinity_list').write_text('0')
        with self.assertRaisesRegex(ValueError,'IRQ_CPU1'):
            self.policy.apply()
        self.assertEqual(self.policy.current(),{'gro_flush_timeout':'0','napi_defer_hard_irqs':'0'})

    def test_symlink_original_is_rejected(self):
        """Reject linked replacement state instead of restoring from an external target."""
        self.policy.apply()
        path = self.directory/'original.json'
        copy = self.root/'external.json'
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        with self.assertRaisesRegex(ValueError,'PRIVATE_ORIGINAL'):
            self.policy.restore()


if __name__=='__main__':
    unittest.main()
# End of file: test_network_performance.py
