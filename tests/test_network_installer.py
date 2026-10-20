"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_network_installer.py
@brief      Test reinstall audit preservation and rejection of incomplete installs or linked receipts.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-19
"""
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'scripts/install_network_performance.py'
SPEC=importlib.util.spec_from_file_location('network_installer',SOURCE)
INSTALLER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class ReceiptHistoryTests(unittest.TestCase):
    """Run file models only without sudo, systemd or device interfaces."""
    def test_completed_remove_preserves_exact_first_receipt_before_reinstall(self):
        """Preserve removed receipt bytes and SHA across retries instead of replacing provenance."""
        with TemporaryDirectory() as directory:
            path=Path(directory)/'install.json'
            raw=json.dumps(dict(status='REMOVED',manifest={'version':'1.0.0','source_commit':'old'},
                restored={'status':'RESTORED'})).encode()
            path.write_bytes(raw)
            with patch.object(INSTALLER,'RECEIPT',path),patch.object(INSTALLER,'private_parents',
                    side_effect=lambda p:p.parent.mkdir(parents=True,exist_ok=True)):
                INSTALLER.preserve_removed_receipt()
                INSTALLER.preserve_removed_receipt()
            history=path.parent/'history'/('removed-'+hashlib.sha256(raw).hexdigest()+'.json')
            self.assertEqual(history.read_bytes(),raw)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(len(list(history.parent.iterdir())),1)

    def test_unfinished_or_unknown_receipt_is_never_overwritten(self):
        """Reject failed, active and unknown state without deleting receipts to force success."""
        for status in ('INSTALLED','INSTALL_FAILED','UNKNOWN'):
            with self.subTest(status=status),TemporaryDirectory() as directory:
                path=Path(directory)/'install.json';raw=json.dumps({'status':status}).encode();path.write_bytes(raw)
                with patch.object(INSTALLER,'RECEIPT',path):
                    with self.assertRaisesRegex(ValueError,'UNKNOWN_RECEIPT'):
                        INSTALLER.preserve_removed_receipt()
                self.assertEqual(path.read_bytes(),raw)
                self.assertFalse((path.parent/'history').exists())

    def test_symlink_receipt_is_rejected(self):
        """Reject an external file masquerading as a removal receipt."""
        with TemporaryDirectory() as directory:
            original=Path(directory)/'outside';original.write_text('{}')
            path=Path(directory)/'install.json';path.symlink_to(original)
            with patch.object(INSTALLER,'RECEIPT',path):
                with self.assertRaisesRegex(ValueError,'REGULAR_PAYLOAD'):
                    INSTALLER.preserve_removed_receipt()
            self.assertEqual(original.read_text(),'{}')


if __name__=='__main__':unittest.main()
# End of file: test_network_installer.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
