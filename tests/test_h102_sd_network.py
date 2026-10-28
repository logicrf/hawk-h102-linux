"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file test_h102_sd_network.py
@brief Check static-network refusal and real host ext4 personalization without an SD.
@details Root cases use only newly created sparse regular images and autoclear loops.
         They exercise production mapping/debugfs/fsck/readback; they do not qualify
         physical media or H102 cold boot. Nonroot runs explicitly skip native cases.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.0.0
@date 2026-10-28
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import h102_sd_network as net
import h102_sd_deploy as sd


def arguments(**values):
    """Build CLI-equivalent values; tests do not replace production validation."""
    return argparse.Namespace(**dict(network='static', address='172.31.102.2/24', gateway=None,dns=None,**values))

class NetworkInputTests(unittest.TestCase):
    """Reject ambiguous or malformed input before any target open."""
    def test_default_and_static_profile(self):
        self.assertEqual(net.network_plan(argparse.Namespace(network='dhcp')),dict(mode='dhcp',personalization=False))
        plan=net.network_plan(arguments())
        text=net.profile_bytes(plan)
        for value in (b'address1=172.31.102.2/24',b'never-default=true',b'may-fail=false',b'dad-timeout=3000',b'cloned-mac-address=stable',b'method=disabled'):
            self.assertIn(value,text)
        a=arguments();a.gateway='172.31.102.1';a.dns='1.1.1.1,8.8.8.8'
        text=net.profile_bytes(net.network_plan(a))
        self.assertIn(b'address1=172.31.102.2/24,172.31.102.1',text)
        self.assertIn(b'dns=1.1.1.1;8.8.8.8;',text)
        self.assertIn(b'never-default=false',text)

    def test_default_auto_profiles_have_bounded_dhcp_and_common_mac_identity(self):
        import configparser
        plan=net.network_plan(argparse.Namespace())
        self.assertEqual(plan['mode'],'auto')
        self.assertEqual(plan['address'],'10.168.1.199/24')
        profiles=net.profile_set(plan)
        self.assertEqual(set(profiles),{net.PROFILE,net.FALLBACK_PROFILE,net.MAC_HELPER,net.MAC_DROPIN,net.CARRIER_CONFIG})
        primary=configparser.ConfigParser(interpolation=None);primary.read_string(profiles[net.PROFILE].decode())
        fallback=configparser.ConfigParser(interpolation=None);fallback.read_string(profiles[net.FALLBACK_PROFILE].decode())
        self.assertEqual(primary['ipv4']['method'],'auto')
        self.assertEqual(primary['ipv4']['dhcp-timeout'],'15')
        self.assertEqual(primary['ipv4']['may-fail'],'false')
        self.assertEqual(primary['connection']['autoconnect-retries'],'1')
        self.assertEqual(primary['connection']['autoconnect'],'false')
        self.assertEqual(fallback['connection']['autoconnect'],'false')
        self.assertGreater(int(primary['connection']['autoconnect-priority']),int(fallback['connection']['autoconnect-priority']))
        self.assertNotEqual(primary['connection']['uuid'],fallback['connection']['uuid'])
        self.assertEqual(primary['connection']['stable-id'],fallback['connection']['stable-id'])
        self.assertEqual(fallback['ipv4']['address1'],'10.168.1.199/24')
        self.assertEqual(fallback['ipv4']['dad-timeout'],'3000')

    def test_invalid_addresses_gateway_dns_and_dhcp_mix(self):
        bad=[('address',v) for v in ('172.31.102.2','172.31.102.0/24','172.31.102.255/24','127.0.0.1/24','0.0.0.0/24','224.0.0.1/24','172.31.102.2/32','172.31.102.2/0','::1/64','172.31.102.2/24\n[evil]')]
        bad += [('gateway',v) for v in ('172.31.102.2','172.31.103.1','172.31.102.0','172.31.102.255','bad')]
        bad += [('dns',v) for v in ('','1.1.1.1,','localhost','1.1.1.1, 8.8.8.8','1.1.1.1,1.1.1.1','1.1.1.1;bad')]
        bad += [('network','dhcp')]
        for field,value in bad:
            a=arguments();setattr(a,field,value)
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):net.network_plan(a)

    def test_invalid_static_refuses_before_source_or_target(self):
        with tempfile.TemporaryDirectory() as d:
            a=arguments();a.address='bad';a.image=Path('/no-source');a.device='/no-device';a.report=Path(d)/'report.json';a.confirm='none'
            with mock.patch.object(sd.os,'geteuid',return_value=0),mock.patch.object(sd,'verify_image',side_effect=AssertionError('must not read image')),mock.patch.object(sd,'inspect_device',side_effect=AssertionError('must not inspect target')):
                self.assertEqual(sd.deploy(a,dict(raw_bytes=4096)),1)
            self.assertNotIn('destructive_write_started_at',a.report.read_text())

    def test_partition_layout_refuses_without_mapping(self):
        with tempfile.TemporaryFile() as f:
            f.write(bytes(512));f.flush()
            with self.assertRaisesRegex(ValueError,'STATIC_MBR_SIGNATURE'):net.root_extent(f.fileno())
            m=bytearray(512);m[510:]=b'\x55\xaa';f.seek(0);f.write(m);f.flush()
            with self.assertRaisesRegex(ValueError,'STATIC_PINNED_PARTITION_LAYOUT'):net.root_extent(f.fileno())


@unittest.skipUnless(os.geteuid()==0,'Native ext4/loop checks require explicit root run')
class NativeExt4Tests(unittest.TestCase):
    """Exercise real kernel FD-backed loops and e2fsprogs only on owned temporary files."""
    def setUp(self):
        net.check_dependencies()
        self.tmp=tempfile.TemporaryDirectory(prefix='h102-static-native-')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        fs=self.root/'root.ext4';fs.touch();os.truncate(fs,64*1024**2)
        subprocess.run(['mke2fs','-q','-t','ext4','-F',str(fs)],check=True,capture_output=True)
        self.image=self.root/'owned-sparse.img'
        with self.image.open('w+b') as target,fs.open('rb') as source:
            target.truncate((net.ROOT_START+net.ROOT_SECTORS)*512)
            mbr=bytearray(512);mbr[510:]=b'\x55\xaa'
            for i,(kind,start,count) in enumerate([(12,24576,4194304),(131,net.ROOT_START,net.ROOT_SECTORS),(162,8192,16384),(0,0,0)]):
                mbr[450+16*i]=kind;struct.pack_into('<II',mbr,454+16*i,start,count)
            target.write(mbr);target.seek(net.ROOT_START*512);shutil.copyfileobj(source,target)
        self.fd=os.open(self.image,os.O_RDWR);self.addCleanup(os.close,self.fd)
        self.base=self.root/'base-profile';self.base.write_bytes(net.BASE_PROFILE)
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            for path in ('/etc','/etc/NetworkManager','/etc/NetworkManager/system-connections','/etc/NetworkManager/conf.d','/etc/systemd','/etc/systemd/system'):
                net._debug(loop,'mkdir '+path,True)
            net._debug(loop,'write '+str(self.base)+' '+net.PROFILE,True)
            net._debug(loop,'set_inode_field '+net.PROFILE+' mode 0100600',True)

    def test_native_exact_file_fsck_permissions_and_autoclear(self):
        before=os.pread(self.fd,512,0)
        result=net.personalize(self.fd,net.network_plan(arguments()))
        self.assertEqual(result['status'],'PASS_STATIC_PROFILE_READBACK_EXT4')
        self.assertEqual(result['sha256'],hashlib.sha256(net.profile_bytes(net.network_plan(arguments()))).hexdigest())
        self.assertEqual(os.pread(self.fd,512,0),before)
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            self.assertEqual(net._debug(loop,'cat '+net.PROFILE),net.profile_bytes(net.network_plan(arguments())))
            info=os.fstat(loop);sysloop=Path('/sys/dev/block')/f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'/'loop/backing_file'
            self.assertTrue(sysloop.exists())
        self.assertFalse(sysloop.exists(),'Only this owned loop should autoclear')

    def test_native_original_mismatch_refuses_without_replacement(self):
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            net._debug(loop,'set_inode_field '+net.PROFILE+' mode 0100644',True)
        with self.assertRaisesRegex(ValueError,'STATIC_PROFILE_TYPE_MODE_OWNER_OR_LINKS'):
            net.personalize(self.fd,net.network_plan(arguments()))
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            self.assertEqual(net._debug(loop,'cat '+net.PROFILE),net.BASE_PROFILE)

    def test_native_auto_writes_both_profiles_and_refuses_preexisting_fallback(self):
        result=net.personalize(self.fd,net.network_plan(argparse.Namespace()))
        self.assertEqual(result['status'],'PASS_NETWORK_PROFILES_READBACK_EXT4')
        self.assertEqual(len(result['profile_files']),5)
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            for path,content in net.profile_set(net.network_plan(argparse.Namespace())).items():
                self.assertEqual(net._debug(loop,'cat '+path),content)
                net._stat(loop,path)
        # Restore only this fixture's primary bytes; an existing second profile
        # must still block a new personalization before the primary is replaced.
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            net._debug(loop,'rm '+net.PROFILE,True)
            net._debug(loop,'write '+str(self.base)+' '+net.PROFILE,True)
            net._debug(loop,'set_inode_field '+net.PROFILE+' mode 0100600',True)
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_EXISTING_FALLBACK_PROFILE'):
            net.personalize(self.fd,net.network_plan(argparse.Namespace()))
        with net.root_loop(self.fd,*net.root_extent(self.fd)) as loop:
            self.assertEqual(net._debug(loop,'cat '+net.PROFILE),net.BASE_PROFILE)

    def test_native_exclusive_block_fd_remains_claimed_during_personalization(self):
        """An owned whole-image loop models the exclusive SD block-FD API, not physical media."""
        size = os.fstat(self.fd).st_size
        with net.root_loop(self.fd, 0, size) as whole:
            number = os.minor(os.fstat(whole).st_rdev)
            exclusive = os.open('/dev/loop'+str(number), os.O_RDWR | os.O_EXCL)
            try:
                result = net.personalize(exclusive, net.network_plan(arguments()))
                self.assertEqual(result['status'], 'PASS_STATIC_PROFILE_READBACK_EXT4')
                self.assertTrue(result['owned_loop_cleanup_confirmed'])
            finally:
                os.close(exclusive)

if __name__=='__main__':unittest.main()
# End of file: test_h102_sd_network.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
