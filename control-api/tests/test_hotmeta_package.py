"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_hotmeta_package.py
@brief Check package hashes, exact membership and rejection of special filesystem objects.
@details Model root permission boundaries explicitly; execute real file/hash checks only.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import install_hotmeta_addon as install
import hotmeta_transaction as tx


class PackageTests(unittest.TestCase):
    """Use real hashes and membership checks, modeling only root ancestor ownership."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'payload.py').write_bytes(b'payload')
        self.manifest=dict(version='1.2.0-grc-hotmeta-1',files={'payload.py':tx.digest(self.root/'payload.py')},
            changes={p:dict(before='0'*64,after='1'*64) for p in tx.TARGETS})
        (self.root/'package.json').write_text(json.dumps(self.manifest));self.sha=tx.digest(self.root/'package.json')
        scope=patch.object(install,'private');scope.start();self.addCleanup(scope.stop)

    def test_valid_and_corrupt_payload(self):
        self.assertEqual(install.verify_package(self.root,self.sha),self.manifest)
        (self.root/'payload.py').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'FILE_SHA'):install.verify_package(self.root,self.sha)

    def test_bad_manifest_digest_and_unknown_file(self):
        with self.assertRaisesRegex(ValueError,'PACKAGE_SHA'):install.verify_package(self.root,'f'*64)
        (self.root/'unknown').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError,'PACKAGE_MEMBERS'):install.verify_package(self.root,self.sha)

    def test_maintenance_migration_cannot_change_any_payload_binding(self):
        """Allow tool-only migration; reject payload or identity changes."""
        keys=('version','changes','original_sdk','candidate_sdk','base_kernel','base_boot_pins','api_files')
        old={key:{'fixed':key} for key in keys};new=deepcopy(old)
        install.same_payload(old,new)
        for key in keys:
            changed=deepcopy(new);changed[key]={'altered':key}
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'PAYLOAD_CHANGED:'+key):
                install.same_payload(old,changed)

    def test_unlisted_symlink_directory_and_fifo(self):
        extra=self.root/'extra';extra.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'NONREGULAR'):install.verify_package(self.root,self.sha)
        extra.unlink();os.mkfifo(extra)
        with self.assertRaisesRegex(ValueError,'NONREGULAR'):install.verify_package(self.root,self.sha)


if __name__=='__main__':unittest.main()
# End of file: test_hotmeta_package.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
