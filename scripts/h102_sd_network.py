#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file h102_sd_network.py
@brief Apply explicit DHCP, manual or DHCP-first fallback settings to a verified H102 SD.
@details Retains the caller's exclusive whole-card FD. A bounded autoclear loop
         maps only the pinned root partition via LOOP_CONFIGURE using that FD.
         Host debugfs/e2fsck inspect and write fixed NM files; no mount or
         target executable is used. Failures leave the card explicitly unfinished.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.2.0
@date 2026-10-28
"""
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

from h102_network_profiles import BASE_PROFILE, PROFILE, FALLBACK_PROFILE, MAC_HELPER, MAC_DROPIN, CARRIER_CONFIG, DEFAULT_ADDRESS, profile_set

ROOT_START, ROOT_SECTORS = 4218880, 18874368
"""Exact unexpanded Kuiper 1.2.1 MBR root extent, in 512-byte sectors."""
LOOP_CTL_GET_FREE, LOOP_CONFIGURE, LOOP_GET_STATUS64 = 0x4C82, 0x4C0A, 0x4C05
LO_FLAGS_AUTOCLEAR, BLKFLSBUF = 4, 0x1261


def _unicast(value):
    """Parse one literal IPv4 address; reject local-host, multicast or unspecified use."""
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or int(address) == 0xffffffff:
        raise ValueError('STATIC_IPV4_UNICAST_REQUIRED')
    return address


def network_plan(args):
    """Validate explicit static arguments before source/target I/O; default to DHCP-first fallback.

    Gateway must be a distinct host in the chosen subnet. DNS is an optional
    comma-separated list of at most three literal IPv4 servers, without whitespace.
    """
    mode = getattr(args, 'network', 'auto')
    address = getattr(args, 'address', None)
    gateway = getattr(args, 'gateway', None)
    dns = getattr(args, 'dns', None)
    if mode == 'dhcp':
        if any(v is not None for v in (address, gateway, dns)):
            raise ValueError('STATIC_ARGUMENTS_REQUIRE_NETWORK_STATIC')
        return dict(mode='dhcp', personalization=False)
    if mode not in ('static','auto'):
        raise ValueError('NETWORK_MODE_REQUIRED')
    address = address or DEFAULT_ADDRESS
    if '/' not in address:
        raise ValueError('STATIC_IPV4_ADDRESS_PREFIX_REQUIRED')
    interface = ipaddress.IPv4Interface(address)
    _unicast(str(interface.ip))
    network = interface.network
    if not 1 <= network.prefixlen <= 30 or interface.ip in (network.network_address, network.broadcast_address):
        raise ValueError('STATIC_IPV4_HOST_PREFIX_REQUIRED')
    result = dict(mode=mode, personalization=True, address=str(interface), gateway=None, dns=[])
    if gateway is not None:
        g = _unicast(gateway)
        if g not in network or g in (interface.ip, network.network_address, network.broadcast_address):
            raise ValueError('STATIC_GATEWAY_MUST_BE_ANOTHER_SUBNET_HOST')
        result['gateway'] = str(g)
    if dns is not None:
        values = dns.split(',')
        if not 1 <= len(values) <= 3 or len(set(values)) != len(values):
            raise ValueError('STATIC_DNS_LIST_REQUIRED')
        result['dns'] = [str(_unicast(v)) for v in values]
    return result


def profile_bytes(plan):
    """Generate only validated values; preserve connection UUID and stable-MAC policy."""
    return profile_set(plan)[PROFILE]


def check_dependencies():
    """Static-only dependencies must exist before opening a destructive write target."""
    for name in ('debugfs', 'e2fsck'):
        if not shutil.which(name):
            raise RuntimeError('STATIC_DEPENDENCY_REQUIRED:' + name)
    if not Path('/dev/loop-control').exists() or not hasattr(os, 'memfd_create'):
        raise RuntimeError('STATIC_LOOP_CONFIGURE_AND_MEMFD_REQUIRED')


def root_extent(fd):
    """Reject any MBR/root layout except the pinned image before mapping its root partition."""
    mbr = os.pread(fd, 512, 0)
    if len(mbr) != 512 or mbr[510:] != b'\x55\xaa':
        raise ValueError('STATIC_MBR_SIGNATURE')
    expected = [(12,24576,4194304),(131,ROOT_START,ROOT_SECTORS),(162,8192,16384),(0,0,0)]
    actual = [(mbr[450+i*16], *struct.unpack_from('<II',mbr,454+i*16)) for i in range(4)]
    if actual != expected:
        raise ValueError('STATIC_PINNED_PARTITION_LAYOUT')
    offset, length = ROOT_START*512, ROOT_SECTORS*512
    superblock = os.pread(fd, 1024, offset+1024)
    if len(superblock) != 1024 or superblock[56:58] != b'\x53\xef':
        raise ValueError('STATIC_EXT4_REQUIRED')
    return offset, length


@contextmanager
def root_loop(backing_fd, offset, length):
    """Bind one newly allocated autoclear loop to the already verified open FD.

    Never detach an existing loop. A concurrent claimant makes LOOP_CONFIGURE fail;
    this function then closes its handle without issuing destructive detach commands.
    """
    control = os.open('/dev/loop-control', os.O_RDWR | os.O_CLOEXEC)
    try:
        number = fcntl.ioctl(control, LOOP_CTL_GET_FREE)
    finally:
        os.close(control)
    loop_fd = os.open('/dev/loop'+str(number), os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    backing_path = Path('/sys/block/loop'+str(number)+'/loop/backing_file')
    configured_backing = None
    try:
        config = bytearray(304)
        struct.pack_into('=II', config, 0, backing_fd, 512)
        struct.pack_into('=QQ', config, 8+24, offset, length)
        struct.pack_into('=I', config, 8+52, LO_FLAGS_AUTOCLEAR)
        fcntl.ioctl(loop_fd, LOOP_CONFIGURE, config)
        configured_backing = backing_path.read_text()
        info = bytearray(232)
        fcntl.ioctl(loop_fd, LOOP_GET_STATUS64, info)
        if struct.unpack_from('=QQ', info,24) != (offset,length) or not struct.unpack_from('=I',info,52)[0]&LO_FLAGS_AUTOCLEAR:
            raise RuntimeError('STATIC_LOOP_BINDING_MISMATCH')
        yield loop_fd
    finally:
        os.close(loop_fd)
        # Autoclear runs asynchronously in the kernel. Observe only our backing
        # identity; never detach a mapping that another client may already reuse.
        if configured_backing is not None:
            deadline = time.monotonic() + 3
            while True:
                try:
                    still_ours = backing_path.read_text() == configured_backing
                except FileNotFoundError:
                    still_ours = False
                if not still_ours:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('STATIC_LOOP_CLEANUP_UNCONFIRMED')
                time.sleep(.02)


def _debug(loop_fd, command, write=False, extra_fds=()):
    """Run fixed host debugfs commands against our inherited loop FD, never a device-path reopen."""
    args = ['debugfs'] + (['-w'] if write else []) + ['-R', command, '/proc/self/fd/'+str(loop_fd)]
    result = subprocess.run(args, pass_fds=(loop_fd,*extra_fds), capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('STATIC_DEBUGFS_FAILED:'+result.stderr.decode(errors='replace')[-700:])
    return result.stdout


def _stat(loop_fd, path=PROFILE):
    """Validate regular root-owned single-link 0600 profile; parse only fixed debugfs fields."""
    if path not in (PROFILE,FALLBACK_PROFILE,MAC_HELPER,MAC_DROPIN,CARRIER_CONFIG):
        raise ValueError('FIXED_NETWORK_PATH_REQUIRED')
    value = _debug(loop_fd, 'stat '+path).decode(errors='strict')
    if (not re.search(r'Type:\s+regular\s+Mode:\s+0600\b',value) or
        not re.search(r'User:\s+0\s+Group:\s+0\b',value) or
        not re.search(r'Links:\s+1\b',value)):
        raise ValueError('STATIC_PROFILE_TYPE_MODE_OWNER_OR_LINKS')
    return value


def _fsck(loop_fd):
    """Require native read-only ext4 consistency; never repair or replay an unknown filesystem."""
    result = subprocess.run(['e2fsck','-f','-n','/proc/self/fd/'+str(loop_fd)],
        pass_fds=(loop_fd,),capture_output=True,timeout=120)
    if result.returncode != 0:
        raise RuntimeError('STATIC_EXT4_CHECK_FAILED:'+result.stdout.decode(errors='replace')[-700:])
    return dict(returncode=0, report=(result.stdout+result.stderr).decode(errors='replace')[-1600:])


def personalize(fd, plan):
    """Write only fixed network paths after base direct-readback, retaining the disk claim.

    On failure the original SD has already been overwritten and must remain marked
    unfinished. No automatic eject, fs repair, mount, retry or whole-image rewrite occurs.
    """
    offset,length = root_extent(fd)
    desired = profile_set(plan)
    expected = desired[PROFILE]
    with root_loop(fd, offset, length) as loop_fd:
        before_fs = _fsck(loop_fd)
        _stat(loop_fd)
        original = _debug(loop_fd, 'cat '+PROFILE)
        if original != BASE_PROFILE:
            raise ValueError('STATIC_ORIGINAL_USRP_PROFILE_MISMATCH')
        if FALLBACK_PROFILE in desired and _debug(loop_fd,'stat '+FALLBACK_PROFILE).strip():
            raise ValueError('UNEXPECTED_EXISTING_FALLBACK_PROFILE')
        for path in (MAC_HELPER,MAC_DROPIN,CARRIER_CONFIG):
            if path in desired and _debug(loop_fd,'stat '+path).strip():
                raise ValueError('UNEXPECTED_EXISTING_MAC_SETUP:'+path)
        if MAC_DROPIN in desired:
            if not re.search(r'Type:\s+directory\b',_debug(loop_fd,'stat /etc/NetworkManager/conf.d').decode()):
                raise ValueError('NETWORK_CONFIG_DIRECTORY_REQUIRED')
            parent='/etc/systemd/system/NetworkManager.service.d'
            state=_debug(loop_fd,'stat '+parent).decode()
            if not state.strip():
                # Only this fixed empty systemd drop-in directory may be created.
                _debug(loop_fd,'mkdir '+parent,True)
            elif not re.search(r'Type:\s+directory\b',state):
                raise ValueError('NETWORK_DROPIN_DIRECTORY_REQUIRED')
        profiles={}
        for path,content in desired.items():
            source_fd = os.memfd_create('h102-nm-profile', os.MFD_CLOEXEC)
            try:
                if os.write(source_fd,content) != len(content):
                    raise OSError('STATIC_PROFILE_SHORT_WRITE')
                if path==PROFILE:
                    _debug(loop_fd, 'rm '+path, True)
                _debug(loop_fd, 'write /proc/self/fd/'+str(source_fd)+' '+path, True, (source_fd,))
                for field,value in [('uid','0'),('gid','0'),('mode','0100600')]:
                    _debug(loop_fd, 'set_inode_field '+path+' '+field+' '+value, True)
            finally:
                os.close(source_fd)
        os.fsync(loop_fd)
        fcntl.ioctl(loop_fd, BLKFLSBUF)
        for path,content in desired.items():
            metadata = _stat(loop_fd,path)
            if _debug(loop_fd, 'cat '+path) != content:
                raise ValueError('STATIC_PROFILE_FULL_READBACK_MISMATCH:'+path)
            profiles[path]=dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),inode_stat=metadata)
        after_fs = _fsck(loop_fd)
    os.fsync(fd)
    return dict(status=('PASS_NETWORK_PROFILES_READBACK_EXT4' if plan['mode']=='auto' else 'PASS_STATIC_PROFILE_READBACK_EXT4'), network=plan, path=PROFILE,profile_files=profiles,
        bytes=len(expected), sha256=hashlib.sha256(expected).hexdigest(), original_sha256=hashlib.sha256(original).hexdigest(),
        inode_stat=metadata, filesystem_before=before_fs, filesystem_after=after_fs,
        root_offset=offset,root_bytes=length, base_raw_identity_retained=False,
        owned_loop_cleanup_confirmed=True,
        physical_static_boot='NOT_RUN')

# End of file: h102_sd_network.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
