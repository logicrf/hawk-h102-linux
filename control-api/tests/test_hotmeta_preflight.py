"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_hotmeta_preflight.py
@brief Reject partial, same-boot or foreign-device add-ons before MMIO access.
@details Model file and device readbacks without invoking systemd or hardware operations.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hotmeta_preflight as check


class PreflightRefusalTests(unittest.TestCase):
    """Test the real preflight rejection order using explicit file/package/device models."""
    def test_partial_same_boot_and_foreign_machine_never_map_mmio(self):
        actual=dict(boot_id='next-boot',machine_id='model-machine',MAC='02:00:00:00:00:01')
        paths={'/proc/sys/kernel/random/boot_id':actual['boot_id'],'/etc/machine-id':actual['machine_id'],
               '/sys/class/net/eth0/address':actual['MAC']}
        for state,identity,message in [
            ('WRITING',dict(actual,boot_id='install-boot'),'ADDON_NOT_INSTALLED'),
            ('FILES_INSTALLED_REBOOT_REQUIRED',actual.copy(),'NEW_BOOT_SAME_MACHINE'),
            ('FILES_INSTALLED_REBOOT_REQUIRED',dict(actual,boot_id='install-boot',machine_id='foreign'),'NEW_BOOT_SAME_MACHINE'),
            ('FILES_INSTALLED_REBOOT_REQUIRED',dict(actual,boot_id='install-boot',MAC='02:00:00:00:00:99'),'NEW_BOOT_SAME_MACHINE')]:
            with self.subTest(state=state,identity=identity),ExitStack() as scope:
                scope.enter_context(patch.object(check.os,'geteuid',return_value=0))
                scope.enter_context(patch.object(check,'private'))
                scope.enter_context(patch.object(check,'verify_package',return_value={}))
                scope.enter_context(patch.object(check.tx,'verify_backup',return_value=dict(state=state,identity=identity)))
                scope.enter_context(patch.object(Path,'read_text',lambda path,*a,**k:paths[str(path)]))
                mmio=scope.enter_context(patch.object(check.mmap,'mmap'))
                with self.assertRaisesRegex(ValueError,message):check.preflight('a'*64)
                mmio.assert_not_called()


if __name__=='__main__':unittest.main()
# End of file: test_hotmeta_preflight.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
