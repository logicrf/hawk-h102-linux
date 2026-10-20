#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_network_affinity.py
@brief      Route the H102 eth0 IRQ to CPU1 and restore its same-boot original state.
@details    Save root-owned /run state before changing IRQ routing, without changing
            clocks, DMA, sampling or the image. systemd ExecStopPost restores on stop or startup failure.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.1
@date       2026-10-12
"""
import argparse
import json
import os
from pathlib import Path
import stat


def identity():
    """Read boot, machine and MAC identities; reject state from another boot or device."""
    return {key: Path(path).read_text().strip() for key, path in {
        'boot_id': '/proc/sys/kernel/random/boot_id',
        'machine_id': '/etc/machine-id',
        'MAC': '/sys/class/net/eth0/address',
    }.items()}


def registered_irqs():
    """List registered eth0 IRQs; an interface that is down may have none."""
    return [int(line.split(':', 1)[0]) for line in
            Path('/proc/interrupts').read_text().splitlines()
            if line.strip().endswith('eth0')]


def eth_irq():
    """Discover the unique eth0 IRQ from the live table rather than pinning a Linux IRQ number."""
    values = registered_irqs()
    if len(values) != 1:
        raise RuntimeError('UNIQUE_ETH0_IRQ_REQUIRED')
    return values[0]


def read_state(irq):
    """Read requested affinity and effective hardware routing independently."""
    return {key: (Path('/proc/irq') / str(irq) / key).read_text().strip()
            for key in ('smp_affinity_list', 'effective_affinity_list')}


def private(directory):
    """Require a root-owned /run directory and regular state file, preserving the original."""
    if os.geteuid() != 0 or directory.parent != Path('/run'):
        raise ValueError('ROOT_RUN_DIRECTORY_REQUIRED')
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('PRIVATE_DIRECTORY_REQUIRED')


def apply(directory):
    """Freeze same-boot state before changing only the NIC IRQ after checking both CPUs."""
    if Path('/sys/devices/system/cpu/online').read_text().strip() != '0-1':
        raise RuntimeError('H102_TWO_ONLINE_CPUS_REQUIRED')
    irq = eth_irq()
    original = dict(schema=1, identity=identity(), irq=irq, state=read_state(irq))
    path = directory / 'original.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(original, stream)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    (Path('/proc/irq') / str(irq) / 'smp_affinity_list').write_text('1')
    actual = read_state(irq)
    if actual != {'smp_affinity_list': '1', 'effective_affinity_list': '1'}:
        raise RuntimeError('IRQ_APPLY_READBACK')
    return dict(status='APPLIED', original=original, actual=actual)


def restore(directory):
    """Restore only matching identity and IRQ; preserve records and never write without them."""
    path = directory / 'original.json'
    if not path.exists():
        return dict(status='NOT_APPLIED')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('PRIVATE_STATE_REQUIRED')
    original = json.loads(path.read_text())
    if (original['identity']['boot_id'] !=
            Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
        raise RuntimeError('IRQ_RESTORE_IDENTITY_MISMATCH')
    if original['irq'] not in registered_irqs():
        # A down interface releases its IRQ; do not write a missing or reassigned IRQ number.
        return dict(status='ORIGINAL_IRQ_RELEASED', original=original)
    if original['identity'] != identity() or original['irq'] != eth_irq():
        raise RuntimeError('IRQ_RESTORE_IDENTITY_MISMATCH')
    requested = original['state']['smp_affinity_list']
    if requested not in ('0', '1', '0-1'):
        raise ValueError('UNEXPECTED_ORIGINAL_MASK')
    (Path('/proc/irq') / str(original['irq']) / 'smp_affinity_list').write_text(requested)
    actual = read_state(original['irq'])
    if actual != original['state']:
        raise RuntimeError('IRQ_RESTORE_READBACK')
    return dict(status='RESTORED', original=original, actual=actual)


def main():
    """Use a fresh state directory and report original/actual routing with nonzero failure exit."""
    parser = argparse.ArgumentParser(description='Set H102 NIC IRQ affinity or restore original routing')
    parser.add_argument('operation', choices=('available', 'apply', 'restore'))
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'available':
        try:
            ready = (Path('/sys/devices/system/cpu/online').read_text().strip() == '0-1'
                     and len(registered_irqs()) == 1)
        except OSError:
            ready = False
        print(json.dumps(dict(status='AVAILABLE' if ready else 'SKIPPED_NO_ETH0_IRQ_OR_CPU')))
        raise SystemExit(0 if ready else 1)
    private(args.directory)
    result = (apply if args.operation == 'apply' else restore)(args.directory)
    (args.directory / (args.operation + '.json')).write_text(
        json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
# End of file: h102_network_affinity.py
