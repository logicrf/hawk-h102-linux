#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_network_performance.py
@brief      Apply and independently restore fixed Ethernet NAPI settings while the H102 is idle.
@details    Write only two eth0 attributes under three locks and actual idle checks.
            Persist same-boot originals first; ordinary failure and independent post restore them.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-19
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time

VERSION = '1.0.0'
DESIRED = {'gro_flush_timeout': '500000', 'napi_defer_hard_irqs': '2'}
"""Repoll at 500 microseconds and return to IRQ after two empty polls; not a sample-rate setting."""
LOCKS = ('h102-profile-config.lock', 'h102-rx-session.lock', 'h102-gnss-g0.lock')
DEVICES = frozenset(('axi-adrv9002-rx-lpc', 'axi-adrv9002-rx2-lpc',
                     'axi-adrv9002-tx-lpc', 'axi-adrv9002-tx2-lpc'))


class NetworkPerformance:
    """Run one root command; a substituted root is available only to explicit offline fixtures.

    Hold three locks for apply/restore without stopping another session. Preserve original.json;
    latest.json records the current result, while callers archive independent evidence.
    """
    def __init__(self, directory, root=Path('/'), require_root=True):
        self.directory = Path(directory)
        self.root = Path(root)
        self.require_root = require_root

    def path(self, absolute):
        """Map fixed absolute paths without accepting paths from the network."""
        return self.root/str(absolute).lstrip('/')

    def identity(self):
        """Bind restoration to boot, machine, MAC and the current interface instance."""
        return {name:self.path(path).read_text().strip() for name,path in {
            'boot_id':'/proc/sys/kernel/random/boot_id', 'machine_id':'/etc/machine-id',
            'MAC':'/sys/class/net/eth0/address', 'ifindex':'/sys/class/net/eth0/ifindex',
        }.items()}

    def current(self):
        """Read the two attributes and reject uninterpretable original values."""
        values = {name:self.path('/sys/class/net/eth0')/name for name in DESIRED}
        result = {name:path.read_text().strip() for name,path in values.items()}
        if any(not value.isdigit() or int(value)>1_000_000_000 for value in result.values()):
            raise ValueError('NETWORK_ATTRIBUTE_VALUE')
        return result

    def available(self):
        """Check actual H102/macb identity without creating state or programming hardware."""
        model = self.path('/proc/device-tree/model').read_bytes().decode().rstrip('\0')
        if 'LogicRF H102' not in model:
            raise ValueError('H102_MODEL_REQUIRED')
        driver = self.path('/sys/class/net/eth0/device/driver').resolve().name
        if driver != 'macb':
            raise ValueError('H102_MACB_REQUIRED')
        irqs = [int(line.split(':',1)[0]) for line in
                self.path('/proc/interrupts').read_text().splitlines()
                if line.strip().endswith('eth0')]
        if len(irqs)!=1 or self.path('/proc/irq').joinpath(str(irqs[0]),'effective_affinity_list').read_text().strip()!='1':
            raise ValueError('H102_ETH_IRQ_CPU1_REQUIRED')
        return dict(version=VERSION, identity=self.identity(), current=self.current(), desired=DESIRED)

    def _private(self, create):
        """Require a root-private /run directory and regular files; tests inject their own root."""
        if self.require_root and (os.geteuid()!=0 or self.directory.parent!=Path('/run')):
            raise ValueError('ROOT_PRIVATE_RUN_REQUIRED')
        if create:
            self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = self.directory.lstat()
        owner = 0 if self.require_root else os.geteuid()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner or info.st_mode & 0o077:
            raise ValueError('PRIVATE_DIRECTORY_REQUIRED')
        original = self.directory/'original.json'
        if original.exists() or original.is_symlink():
            info = original.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_mode & 0o077:
                raise ValueError('PRIVATE_ORIGINAL_REQUIRED')

    @contextmanager
    def _locked_idle(self):
        """Acquire three locks without waiting and require four idle DMA channels."""
        files = []
        try:
            for name in LOCKS:
                path = self.path('/run/lock')/name
                descriptor = os.open(path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
                stream = os.fdopen(descriptor, 'a+b')
                files.append(stream)
                fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            found = {}
            for path in self.path('/sys/bus/iio/devices').glob('iio:device*'):
                name = path/'name'
                if not name.is_file():
                    continue
                value = name.read_text().strip()
                if value in DEVICES:
                    if value in found:
                        raise ValueError('DUPLICATE_IIO_DEVICE')
                    found[value] = (path/'buffer/enable').read_text().strip()
            if set(found)!=DEVICES or any(value!='0' for value in found.values()):
                raise RuntimeError('IIO_DATA_BUSY_OR_DEVICE_SET_CHANGED_NO_WRITES')
            yield
        finally:
            for stream in reversed(files):
                stream.close()

    def _write(self, name, value):
        """Write one fixed sysfs attribute within the locked identity window."""
        (self.path('/sys/class/net/eth0')/name).write_text(value)

    def _original(self):
        """Require saved originals and current identity to match; reject arbitrary targets or old boots."""
        original = json.loads((self.directory/'original.json').read_text())
        if (set(original)!= {'schema', 'version', 'identity', 'original', 'desired'} or
                original['schema']!=1 or original['version']!=VERSION or
                original['desired']!=DESIRED or original['identity']!=self.identity() or
                set(original['original'])!=set(DESIRED)):
            raise ValueError('NETWORK_ORIGINAL_IDENTITY_OR_SCHEMA')
        if any(not isinstance(v,str) or not v.isdigit() or int(v)>1_000_000_000
               for v in original['original'].values()):
            raise ValueError('NETWORK_ORIGINAL_VALUES')
        return original

    def _record(self, result):
        """Atomically save terminal state and fsync its directory without replacing original values."""
        result = dict(result, version=VERSION, identity=self.identity(), monotonic_ns=time.monotonic_ns())
        with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, prefix='.latest-', delete=False) as stream:
            name = Path(stream.name)
            json.dump(result, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, self.directory/'latest.json')
        descriptor = os.open(self.directory, os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return result

    def _restore_values(self, original):
        """Restore only original or owned target values; do not silently overwrite external drift."""
        current = self.current()
        if any(current[name] not in (original['original'][name], desired)
               for name,desired in DESIRED.items()):
            raise RuntimeError('NETWORK_EXTERNAL_CHANGE_NO_WRITES')
        for name in reversed(list(DESIRED)):
            self._write(name, original['original'][name])
        actual = self.current()
        if actual!=original['original']:
            raise RuntimeError('NETWORK_RESTORE_READBACK')
        return self._record(dict(status='RESTORED', actual=actual, original=original))

    def apply(self):
        """Freeze originals before writing both attributes; independently recover partial failures."""
        self._private(create=True)
        self.available()
        with self._locked_idle():
            path = self.directory/'original.json'
            if not path.exists():
                value = dict(schema=1, version=VERSION, identity=self.identity(),
                             original=self.current(), desired=DESIRED)
                descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor,'w') as stream:
                    json.dump(value, stream, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                descriptor = os.open(self.directory, os.O_RDONLY|os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            original = self._original()
            current = self.current()
            if any(current[name] not in (original['original'][name], desired)
                   for name,desired in DESIRED.items()):
                raise RuntimeError('NETWORK_EXTERNAL_CHANGE_NO_WRITES')
            try:
                for name,value in DESIRED.items():
                    self._write(name,value)
                actual = self.current()
                if actual!=DESIRED:
                    raise RuntimeError('NETWORK_APPLY_READBACK')
                return self._record(dict(status='APPLIED', actual=actual, original=original))
            except Exception as error:
                try:
                    self._restore_values(original)
                except Exception as recovery:
                    raise RuntimeError('NETWORK_APPLY_FAILED_AND_RESTORE_UNCONFIRMED:'+repr(error)+';'+repr(recovery)) from error
                raise

    def restore(self):
        """Run systemd post restoration with the same boot, locks and idle DMA constraints."""
        if not self.directory.exists():
            return dict(status='NO_ORIGINAL_STATE_NO_WRITES')
        self._private(create=False)
        if not (self.directory/'original.json').exists():
            return dict(status='NO_ORIGINAL_STATE_NO_WRITES')
        with self._locked_idle():
            return self._restore_values(self._original())

    def status(self):
        """Report actual and saved state without treating intended settings as applied."""
        result = self.available()
        result['applied'] = result['current']==DESIRED
        if self.directory.exists():
            self._private(create=False)
            if (self.directory/'original.json').exists():
                result['original'] = self._original()
        return result


def main():
    """Use the actual local root for administration, without device connections or credentials."""
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('available','apply','restore','status'))
    parser.add_argument('--directory', type=Path, default=Path('/run/h102-network-performance'))
    args = parser.parse_args()
    policy = NetworkPerformance(args.directory)
    print(json.dumps(getattr(policy,args.action)(), indent=2))


if __name__=='__main__':
    main()
# End of file: h102_network_performance.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
