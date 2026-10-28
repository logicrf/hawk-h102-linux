#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_sd_deploy.py
@brief      Select an explicit Linux SD disk, verify the image, write exclusively and read back directly.
@details    list/inspect are read-only. write requires root and a current diskseq confirmation.
            Verify complete RAW/XZ hashes before writing, fsync and O_DIRECT readback through one device FD.
            Reject mounted, swap, held or busy devices and identity drift; never unmount automatically.
            Preserve staged failures without write retries. Eject only the verified original device on success.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.3.0
@date       2026-10-28
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime
import errno
import fcntl
import hashlib
import json
import lzma
import mmap
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import time

import h102_sd_network as network

CHUNK = 4 * 1024 * 1024
"""Bound stream memory and page-align direct reads; released RAW size is 4-KiB aligned."""
PINS = Path(__file__).resolve().parents[1] / 'manifests/h102-deployment-1.2.1.json'
BLKGETSIZE64, BLKROGET, BLKFLSBUF = 0x80081272, 0x125e, 0x1261
"""Use Linux block ioctls; reject unsupported direct readback instead of cached fallback."""


def utc_now() -> str:
    """Return the actual check time with its timezone."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_pins() -> dict:
    """Load the bundled release manifest without arbitrary hash overrides or downloads."""
    pins = json.loads(PINS.read_text())
    if pins['schema'] != 1 or pins['version'] != '1.2.1' or pins['raw_bytes'] % 4096:
        raise ValueError('INVALID_RELEASE_PINS')
    return pins


def write_all(fd: int, data) -> None:
    """Handle partial writes; propagate zero writes and device errors."""
    view = memoryview(data)
    try:
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError('ZERO_LENGTH_WRITE')
            view = view[count:]
    finally:
        view.release()


class Report:
    """Exclusively create a staged report that callers close; never overwrite existing files.

    Write only an explicit regular report path and fsync each stage, retaining the latest error.
    """
    def __init__(self, path: Path):
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.data = dict(schema=1, tool='h102_sd_deploy', started_at=utc_now(),
                         status='IN_PROGRESS', phase='preflight', physical_boot='NOT_RUN')
        self.update()

    def update(self, **values) -> None:
        """Record actual write, readback and ejection stages separately."""
        self.data.update(values)
        raw = (json.dumps(self.data, ensure_ascii=False, indent=2) + '\n').encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        write_all(self.fd, raw)
        os.ftruncate(self.fd, len(raw))
        os.fsync(self.fd)

    def close(self) -> None:
        """Close the report FD without deleting successful or failed evidence."""
        os.close(self.fd)


def run_json(command: list[str]) -> dict:
    """Bound read-only inventory commands and preserve nonzero preflight failures."""
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def block_inventory() -> list[dict]:
    """Return the complete lsblk disk/partition graph, including mounts, read-only flags and device IDs."""
    return run_json(['lsblk', '--json', '--bytes', '--paths', '--output',
                     'NAME,KNAME,TYPE,SIZE,RO,RM,TRAN,MODEL,SERIAL,MAJ:MIN,MOUNTPOINTS'])['blockdevices']


def descendants(entry: dict):
    """Walk all selected disk children so mounted partitions cannot be overlooked."""
    yield entry
    for child in entry.get('children', []):
        yield from descendants(child)


def identity_token(identity: dict) -> str:
    """Bind capacity, physical path and diskseq; inspect again after reinsertion or card changes."""
    keys = ('device', 'major_minor', 'bytes', 'diskseq', 'sysfs_path', 'model', 'serial')
    raw = json.dumps({key: identity[key] for key in keys}, sort_keys=True).encode()
    return 'h102sd-' + hashlib.sha256(raw).hexdigest()[:24]


def policy_blockers(entry: dict, required_bytes: int) -> list[str]:
    """Accept removable/USB whole disks only, with no force override."""
    errors = []
    if entry['type'] != 'disk':
        errors.append('WHOLE_PHYSICAL_DISK_REQUIRED')
    if not entry.get('rm') and entry.get('tran') != 'usb':
        errors.append('REMOVABLE_OR_USB_DISK_REQUIRED')
    if int(entry['size']) < required_bytes:
        errors.append('CAPACITY_TOO_SMALL')
    if int(entry['size']) >= 2**32 * 512:
        errors.append('CAPACITY_EXCEEDS_DOS_LAYOUT')
    for node in descendants(entry):
        if node.get('ro'):
            errors.append('READ_ONLY:' + node['name'])
        if any(node.get('mountpoints') or []):
            errors.append('MOUNTED:' + node['name'])
    return errors


def inspect_device(device: str, required_bytes: int) -> dict:
    """Inspect disk/kernel identity read-only and report the confirmation code and blockers."""
    path = Path(device).resolve(strict=True)
    info = path.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError('BLOCK_DEVICE_REQUIRED')
    major_minor = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    found = [node for root in block_inventory() for node in descendants(root)
             if node['maj:min'] == major_minor]
    if len(found) != 1:
        raise ValueError('AMBIGUOUS_OR_MISSING_BLOCK_DEVICE')
    node = found[0]
    sysfs = Path('/sys/dev/block') / major_minor
    diskseq = int((sysfs / 'diskseq').read_text()) if (sysfs / 'diskseq').exists() else None
    blockers = policy_blockers(node, required_bytes)
    if not diskseq:
        blockers.append('KERNEL_DISKSEQ_REQUIRED')
    for child in descendants(node):
        holders = Path('/sys/dev/block') / child['maj:min'] / 'holders'
        if not holders.is_dir() or any(holders.iterdir()):
            blockers.append('BLOCK_HOLDER_OR_UNKNOWN:' + child['name'])
    identity = dict(device=str(path), major_minor=major_minor, bytes=int(node['size']),
                    diskseq=diskseq, sysfs_path=str(sysfs.resolve()),
                    model=(node.get('model') or '').strip(), serial=(node.get('serial') or '').strip())
    return dict(identity=identity, confirm=identity_token(identity), blockers=blockers,
                nodes=[dict(device=x['name'], major_minor=x['maj:min']) for x in descendants(node)])


def process_fd_kind(fd: Path) -> tuple[int, int]:
    """Read a process FD's type/rdev, dropping privileges for root-denying FUSE.

    Retry EACCES only as the process owner in an isolated, bounded read-only
    Python child. Preserve denial and process/FD races; never infer that an
    unreadable descriptor is safe. No mount permissions or target FDs change.
    """
    try:
        info = fd.stat()
        return info.st_mode, info.st_rdev
    except PermissionError:
        owner = fd.parent.parent.stat()
        if os.geteuid() != 0 or owner.st_uid == 0:
            raise
        before = os.readlink(fd)
        probe = (
            'import json,os,sys\n'
            'try:\n'
            ' s=os.stat(sys.argv[1]); print(json.dumps([s.st_mode,s.st_rdev]))\n'
            'except OSError as e:\n'
            ' print(json.dumps({"errno":e.errno}))\n'
        )
        result = subprocess.run(
            [sys.executable, '-I', '-S', '-c', probe, str(fd)],
            user=owner.st_uid, group=owner.st_gid, extra_groups=[],
            capture_output=True, text=True, check=True, timeout=5,
        )
        value = json.loads(result.stdout)
        if isinstance(value, dict) and 'errno' in value:
            raise OSError(value['errno'], 'PROCESS_FD_OWNER_PROBE_FAILED', str(fd))
        if (not isinstance(value, list) or len(value) != 2 or
                any(type(item) is not int or item < 0 for item in value)):
            raise ValueError('INVALID_PROCESS_FD_OWNER_PROBE')
        if fd.parent.parent.stat().st_uid != owner.st_uid or os.readlink(fd) != before:
            raise OSError(errno.EAGAIN, 'PROCESS_FD_CHANGED_DURING_PROBE', str(fd))
        return tuple(value)


def check_kernel_users(device: dict, owned_fd: int | None = None) -> None:
    """Require complete root preflight over mount namespaces, swap and block FDs.

    A vanished process is an expected race; preserve other errors. Match only the selected
    disk and partitions' rdev values, without claiming unrelated processes or files.
    """
    numbers = {node['major_minor'] for node in device['nodes']}
    rdevs = {os.makedev(*map(int, number.split(':'))) for number in numbers}
    for row in Path('/proc/swaps').read_text().splitlines()[1:]:
        swap = Path(row.split()[0])
        info = swap.stat()
        number = info.st_rdev if stat.S_ISBLK(info.st_mode) else info.st_dev
        if number in rdevs:
            raise ValueError('ACTIVE_SWAP_ON_TARGET')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for line in (process / 'mountinfo').read_text().splitlines():
                if line.split()[2] in numbers:
                    raise ValueError('MOUNTED_IN_PROCESS_NAMESPACE:' + process.name)
            for fd in (process / 'fd').iterdir():
                try:
                    mode, rdev = process_fd_kind(fd)
                except FileNotFoundError:
                    continue
                if stat.S_ISBLK(mode) and rdev in rdevs:
                    if process.name == str(os.getpid()) and owned_fd is not None and fd.name == str(owned_fd):
                        continue  # Only the verified descriptor owned by this write; reject other handles.
                    raise ValueError('BLOCK_FD_IN_USE:' + process.name)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as error:
            # Dead zombies have no FDs/namespaces; Linux mountinfo may return EINVAL.
            # Skip only after confirming actual Z/X process state; reject other unreadable processes.
            if error.errno == errno.EINVAL:
                try:
                    state = next(line.split()[1] for line in (process / 'status').read_text().splitlines()
                                 if line.startswith('State:'))
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if state in ('Z', 'X'):
                    continue
            raise


@contextmanager
def image_stream(source, compressed: bool):
    """Read RAW bytes again from the held source FD rather than reopening a changed pathname."""
    source.seek(0)
    if compressed:
        with lzma.LZMAFile(source, 'rb') as stream:
            yield stream
    else:
        yield source


def source_identity(source) -> tuple:
    """Pin source inode, size, mtime and ctime; reject source changes during writing."""
    info = os.fstat(source.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def verify_image(source, pins: dict) -> dict:
    """Verify complete compressed/expanded hashes before target access; reject LFS pointers or bad streams."""
    info = os.fstat(source.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('REGULAR_IMAGE_FILE_REQUIRED')
    before = source_identity(source)
    source.seek(0)
    compressed = source.read(6) == b'\xfd7zXZ\x00'
    size = pins['compressed_bytes'] if compressed else pins['raw_bytes']
    digest = pins['compressed_sha256'] if compressed else pins['raw_sha256']
    if info.st_size != size:
        raise ValueError('IMAGE_SIZE_MISMATCH_OR_LFS_POINTER')
    source.seek(0)
    sha = hashlib.sha256()
    while True:
        block = source.read(CHUNK)
        if not block:
            break
        sha.update(block)
    if sha.hexdigest() != digest:
        raise ValueError('IMAGE_SHA256_MISMATCH')
    raw_sha, count = hashlib.sha256(), 0
    with image_stream(source, compressed) as stream:
        while True:
            block = stream.read(CHUNK)
            if not block:
                break
            count += len(block)
            if count > pins['raw_bytes']:
                raise ValueError('DECOMPRESSED_IMAGE_TOO_LARGE')
            raw_sha.update(block)
    if count != pins['raw_bytes'] or raw_sha.hexdigest() != pins['raw_sha256']:
        raise ValueError('RAW_IMAGE_SHA256_OR_SIZE_MISMATCH')
    if source_identity(source) != before:
        raise ValueError('SOURCE_CHANGED_DURING_PREFLIGHT')
    return dict(compressed=compressed, input_sha256=digest, raw_sha256=raw_sha.hexdigest(),
                raw_bytes=count, fd_identity=before)


def copy_image(source, compressed: bool, fd: int, pins: dict, notify=None) -> dict:
    """Stream into the caller's verified FD, checking partial writes, fsync and source digest.

    This function selects no target; production CLI first verifies whole-disk policy and O_EXCL.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    sha, count, last = hashlib.sha256(), 0, time.monotonic()
    with image_stream(source, compressed) as stream:
        while True:
            block = stream.read(CHUNK)
            if not block:
                break
            if count + len(block) > pins['raw_bytes']:
                raise ValueError('SOURCE_EXPANDED_DURING_WRITE')
            write_all(fd, block)
            sha.update(block)
            count += len(block)
            if notify and time.monotonic() - last >= 15:
                notify(count)
                last = time.monotonic()
    os.fsync(fd)
    if count != pins['raw_bytes'] or sha.hexdigest() != pins['raw_sha256']:
        raise ValueError('SOURCE_CHANGED_DURING_WRITE')
    return dict(bytes=count, sha256=sha.hexdigest(), fsync=True)


def direct_readback(fd: int, pins: dict) -> dict:
    """Switch the original FD to O_DIRECT and read back with page-aligned mmap buffers.

    The regular-file path tests this transfer core; production rejects regular/loop targets.
    """
    os.fsync(fd)
    if stat.S_ISBLK(os.fstat(fd).st_mode):
        fcntl.ioctl(fd, BLKFLSBUF)
    else:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_DIRECT)
    if not fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_DIRECT:
        raise OSError('DIRECT_READBACK_NOT_ENABLED')
    os.lseek(fd, 0, os.SEEK_SET)
    count, sha = 0, hashlib.sha256()
    try:
        with mmap.mmap(-1, CHUNK) as aligned:
            view = memoryview(aligned)
            try:
                while count < pins['raw_bytes']:
                    size = min(CHUNK, pins['raw_bytes'] - count)
                    part = view[:size]
                    try:
                        got = os.readv(fd, [part])
                    finally:
                        # Tracebacks may retain a sliced buffer; explicitly release it so mmap close
                        # cannot obscure the original read error.
                        part.release()
                    if got <= 0 or got % 512:
                        raise OSError('SHORT_OR_UNALIGNED_DIRECT_READ')
                    sha.update(view[:got])
                    count += got
            finally:
                view.release()
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
    if sha.hexdigest() != pins['raw_sha256']:
        raise ValueError('FULL_DIRECT_READBACK_SHA256_MISMATCH')
    return dict(bytes=count, sha256=sha.hexdigest(), direct=True, same_fd=True)


def verify_open_device(fd: int, device: dict) -> None:
    """Check held FD type, rdev, size and read-only state, then recheck diskseq."""
    info, expected = os.fstat(fd), device['identity']
    number = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    if not stat.S_ISBLK(info.st_mode) or number != expected['major_minor']:
        raise ValueError('OPENED_DEVICE_IDENTITY_MISMATCH')
    capacity = struct.unpack('Q', fcntl.ioctl(fd, BLKGETSIZE64, b'\0' * 8))[0]
    readonly = struct.unpack('I', fcntl.ioctl(fd, BLKROGET, b'\0' * 4))[0]
    seq = int((Path('/sys/dev/block') / number / 'diskseq').read_text())
    if capacity != expected['bytes'] or readonly or seq != expected['diskseq']:
        raise ValueError('DEVICE_CHANGED_OR_READ_ONLY')


def eject_device(device: dict, required_bytes: int) -> dict:
    """Eject only the original device; wait at most five seconds for transient block FDs.

    Every observation rechecks identity and use. Never rewrite, unmount, kill an
    owner, or ignore a persistent user, changed disk, mount or inspection error.
    """
    busy = []
    for attempt in range(6):
        current = inspect_device(device['identity']['device'], required_bytes)
        if current['identity'] != device['identity'] or current['blockers']:
            raise ValueError('DEVICE_CHANGED_OR_BUSY_BEFORE_EJECT')
        try:
            check_kernel_users(current)
            break
        except ValueError as error:
            if not str(error).startswith('BLOCK_FD_IN_USE:') or attempt == 5:
                raise
            busy.append(dict(check=attempt + 1, reason=str(error)))
            time.sleep(1)
    if not shutil.which('udisksctl'):
        return dict(status='NOT_EJECTED', reason='UDISKSCTL_NOT_INSTALLED')
    result = subprocess.run(['udisksctl', 'power-off', '-b', current['identity']['device']],
                            capture_output=True, text=True, timeout=30)
    gone = not (Path('/sys/dev/block') / current['identity']['major_minor']).exists()
    passed = result.returncode == 0 and gone
    return dict(status='PASS' if passed else 'NOT_EJECTED', returncode=result.returncode,
                target_absent=gone, message=result.stderr.strip() or result.stdout.strip(),
                transient_block_fd_observations=busy)



def deploy(args, pins: dict) -> int:
    """Run the production lifecycle, retaining failure reports and closing FDs without write retries."""
    report = Report(args.report)
    try:
        if os.geteuid() != 0:
            raise PermissionError('ROOT_REQUIRED_FOR_WRITE')
        plan = network.network_plan(args)
        report.update(network_plan=plan)
        if plan['personalization']:
            network.check_dependencies()
        if not shutil.which('udisksctl'):
            raise RuntimeError('UDISKSCTL_REQUIRED_FOR_SAFE_EJECT')
        source_fd = os.open(args.image, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(source_fd, 'rb') as source:
            report.update(phase='verify_source', source=str(args.image))
            verified = verify_image(source, pins)
            report.update(source_verification=verified, phase='verify_target')
            device = inspect_device(args.device, pins['raw_bytes'])
            report.update(target=device)
            if device['blockers']:
                raise ValueError('TARGET_BLOCKED:' + ','.join(device['blockers']))
            if args.confirm != device['confirm']:
                raise ValueError('CONFIRMATION_DOES_NOT_MATCH_CURRENT_DISKSEQ')
            check_kernel_users(device)
            fd = os.open(device['identity']['device'], os.O_RDWR | os.O_EXCL | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                verify_open_device(fd, device)
                again = inspect_device(args.device, pins['raw_bytes'])
                if again['identity'] != device['identity'] or again['blockers']:
                    raise ValueError('TARGET_CHANGED_AFTER_EXCLUSIVE_OPEN')
                if source_identity(source) != tuple(verified['fd_identity']):
                    raise ValueError('SOURCE_CHANGED_BEFORE_WRITE')
                report.update(phase='write', destructive_write_started_at=utc_now())
                progress = lambda count: print(f'Writing {count}/{pins["raw_bytes"]} bytes', file=sys.stderr, flush=True)
                copied = copy_image(source, verified['compressed'], fd, pins, progress)
                if source_identity(source) != tuple(verified['fd_identity']):
                    raise ValueError('SOURCE_CHANGED_DURING_WRITE')
                report.update(write=copied, phase='direct_readback')
                print('Write/fsync complete; starting full O_DIRECT readback.', file=sys.stderr, flush=True)
                checked = direct_readback(fd, pins)
                verify_open_device(fd, device)
                report.update(readback=checked, phase='safe_eject', write_readback='PASS')
                if plan['personalization']:
                    report.update(phase='network_personalization')
                    check_kernel_users(device, owned_fd=fd)
                    current = inspect_device(args.device, pins['raw_bytes'])
                    if current['identity'] != device['identity'] or current['blockers']:
                        raise ValueError('DEVICE_CHANGED_OR_BUSY_BEFORE_NETWORK')
                    verify_open_device(fd, device)
                    personalized = network.personalize(fd, plan)
                    verify_open_device(fd, device)
                    report.update(network_personalization=personalized, phase='safe_eject')
            finally:
                os.close(fd)
        try:
            ejected = eject_device(device, pins['raw_bytes'])
        except (Exception, KeyboardInterrupt) as error:
            # Completed write/readback must not be relabeled as requiring a rewrite.
            # Retain the ejection refusal without retrying writes or bypassing checks.
            ejected = dict(status='NOT_EJECTED', reason=f'{type(error).__name__}: {error}')
        passed = ejected['status'] == 'PASS'
        report.update(status='PASS_WRITE_DIRECT_READBACK_EJECT' if passed else 'WRITE_VERIFIED_NOT_EJECTED',
                      phase='complete', eject=ejected, finished_at=utc_now(), version=pins['version'])
        print(json.dumps(report.data, ensure_ascii=False))
        return 0 if passed else 3
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='FAIL', error=f'{type(error).__name__}: {error}', finished_at=utc_now())
        print(json.dumps(report.data, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        report.close()


def main(argv=None) -> int:
    """Require an explicit disk target; list/inspect are read-only and write overwrites the disk."""
    parser = argparse.ArgumentParser(description='H102 1.2.1 Linux SD deployment with complete direct readback')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='List removable/USB disk candidates read-only without selecting one')
    inspect = sub.add_parser('inspect', help='Inspect disk identity, confirmation code and blockers read-only')
    inspect.add_argument('--device', required=True)
    write = sub.add_parser('write', help='Overwrite the explicit SD disk, verify readback and eject safely')
    write.add_argument('--device', required=True)
    write.add_argument('--image', type=Path, required=True)
    write.add_argument('--confirm', required=True, help='Current device confirmation code from inspect')
    write.add_argument('--report', type=Path, required=True, help='New JSON report with an existing parent directory')
    write.add_argument('--network', choices=['auto', 'dhcp', 'static'], default='auto',
                       help='DHCP first with 10.168.1.199 fallback; or DHCP-only/manual mode')
    write.add_argument('--address', help='Fallback/manual IPv4 with prefix, e.g. 10.168.1.199/24')
    write.add_argument('--gateway', help='Optional gateway in the selected static subnet')
    write.add_argument('--dns', help='Optional comma-separated IPv4 DNS servers, up to three')
    args = parser.parse_args(argv)
    pins = load_pins()
    if args.command == 'write':
        return deploy(args, pins)
    if args.command == 'list':
        nodes = [x for x in block_inventory() if x['type'] == 'disk' and (x.get('rm') or x.get('tran') == 'usb')]
        result = dict(status='READ_ONLY_CANDIDATES_NOT_SELECTED',
                      devices=[dict(x, blockers=policy_blockers(x, pins['raw_bytes'])) for x in nodes])
    else:
        result = inspect_device(args.device, pins['raw_bytes'])
        result['status'] = 'BLOCKED' if result['blockers'] else 'INSPECTED_NOT_WRITTEN'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('blockers') else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps(dict(status='FAIL', error=f'{type(exc).__name__}: {exc}'), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

# End of file: h102_sd_deploy.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
