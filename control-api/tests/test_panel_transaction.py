"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_panel_transaction.py
@brief Exercise exact rollback, interruption and rejection on real temporary files.
@details Use fixed source and payload identities; keep backups and failure evidence.
         Image preparation is offline. Device installation requires an administrator;
         normal applications require only the device IP. Do not widen qualification.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.0.0
@date 2026-10-27
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import panel_transaction as tx


class PanelTransactionTests(unittest.TestCase):
    """Use isolated real files to check interruption, corruption and rollback without device access."""
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.work=Path(self.temporary.name);self.root=self.work/'root';self.overlay=self.work/'overlay'
        self.root.mkdir();self.overlay.mkdir();self.changes={};self.original={}
        for index,name in enumerate(sorted(tx.TARGETS)):
            before=(f'old-{index}-'+'a'*500).encode();after=(f'new-{index}-'+'b'*700).encode()
            for root,raw in ((self.root,before),(self.overlay,after)):
                p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);p.chmod(0o644)
            self.original[name]=before
            self.changes[name]=dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest())
        self.backup=self.work/'backup';self.identity=dict(boot_id='model-install-boot',machine_id='model-machine')
        (self.root/'untouched').write_bytes(b'not-in-transaction')

    def prepare(self):
        return tx.prepare(self.root,self.overlay,self.changes,self.backup,identity=self.identity)

    def assert_original(self):
        for name,raw in self.original.items():
            p=self.root/name.lstrip('/');self.assertEqual(p.read_bytes(),raw);self.assertEqual(p.stat().st_mode&0o777,0o644)
        self.assertEqual((self.root/'untouched').read_bytes(),b'not-in-transaction')

    def test_success_and_real_rollback(self):
        self.prepare();result=tx.apply(self.root,self.overlay,self.backup)
        self.assertEqual(result['committed'][-1],'/boot/h102_logicrf_master.bit')
        self.assertEqual(result['state'],'FILES_INSTALLED_REBOOT_REQUIRED')
        for name,row in self.changes.items():self.assertEqual(tx.digest(self.root/name.lstrip('/')),row['after'])
        self.assertEqual(tx.rollback(self.root,self.backup)['state'],'ROLLED_BACK_FILES_REBOOT_REQUIRED')
        self.assert_original()

    def test_failure_after_each_write_restores_actual_originals(self):
        for count in range(1,6):
            with self.subTest(committed=count):
                backup=self.work/f'interrupted-{count}'
                tx.prepare(self.root,self.overlay,self.changes,backup,identity=self.identity)
                def interrupt(name,written):
                    if written==count:raise OSError('model abrupt write interruption')
                with self.assertRaisesRegex(OSError,'model abrupt'):tx.apply(self.root,self.overlay,backup,after_write=interrupt)
                self.assertEqual(len(json.loads((backup/'transaction.json').read_text())['committed']),count)
                tx.rollback(self.root,backup);self.assert_original()

    def test_corrupt_payload_or_wrong_original_never_writes(self):
        target=self.overlay/'boot/h102_logicrf_master.bit';raw=target.read_bytes();target.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'PAYLOAD_MISMATCH'):self.prepare()
        self.assertFalse(self.backup.exists());self.assert_original();target.write_bytes(raw)
        self.changes['/boot/h102_logicrf_master.bit']['before']='0'*64
        with self.assertRaisesRegex(ValueError,'BASE_MISMATCH'):self.prepare()
        self.assertFalse(self.backup.exists());self.assert_original()

    def test_foreign_drift_and_corrupt_backup_refuse_before_restore(self):
        self.prepare();tx.apply(self.root,self.overlay,self.backup)
        drift=self.root/'etc/h102/sdk1-image.json';drift.write_bytes(b'foreign-admin-edit')
        before={n:(self.root/n.lstrip('/')).read_bytes() for n in tx.TARGETS}
        with self.assertRaisesRegex(ValueError,'FOREIGN_CHANGE'):tx.rollback(self.root,self.backup)
        self.assertEqual({n:(self.root/n.lstrip('/')).read_bytes() for n in tx.TARGETS},before)
        drift.write_bytes((self.overlay/'etc/h102/sdk1-image.json').read_bytes())
        original=self.backup/'original/boot/h102_logicrf_master.bit';original.write_bytes(b'bad-backup')
        with self.assertRaisesRegex(ValueError,'BACKUP_CHANGED'):tx.rollback(self.root,self.backup)

    def test_target_extension_and_symlink_are_rejected(self):
        changes=dict(self.changes,**{'/etc/shadow':dict(before='0'*64,after='1'*64)})
        with self.assertRaisesRegex(ValueError,'EXACT_FIVE'):tx.prepare(self.root,self.overlay,changes,self.backup,identity=self.identity)
        target=self.root/'boot/h102_logicrf_master.bit';raw=target.read_bytes();target.unlink();other=self.work/'other';other.write_bytes(raw);target.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):self.prepare()
        self.assertFalse(self.backup.exists())


if __name__=='__main__':unittest.main()
# End of file: test_panel_transaction.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
