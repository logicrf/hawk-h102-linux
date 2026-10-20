#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_profile_iio_broker.py
@brief      Test control ABI validation and rollback classification from actual manager results.
@details    Model hardware queries; qualify only protocol and error classification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-08
"""
import json
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import h102_profile_iio_broker as tool


class Cases(unittest.TestCase):
    """Test write ABI, unknown originals, post results and independent-query disagreements."""
    def test_abi_and_request_validation(self):
        """Fix cross-platform sizes and reject invalid version, sequence or paths before dispatch."""
        self.assertEqual((tool.REQUEST.size, tool.UPDATE.size), (80, 4504))
        good = tool.REQUEST.pack(1, 0, 1, b'20msps-10mhz')
        self.assertEqual(tool.decode_request(good), (1, '20msps-10mhz'))
        for payload in (tool.REQUEST.pack(2, 0, 1, b'a'),
                        tool.REQUEST.pack(1, 1, 1, b'a'),
                        tool.REQUEST.pack(1, 0, 0, b'a'),
                        tool.REQUEST.pack(1, 0, 1, b'../a'),
                        tool.REQUEST.pack(1, 0, 1, b'a' * 64)):
            with self.assertRaises(ValueError):
                tool.decode_request(payload)

    def test_text_not_silently_truncated(self):
        """Reject truncation and embedded NUL in active metadata."""
        for text in ('a' * 64, 'a\0b'):
            with self.assertRaises(ValueError):
                tool.text_field(text, 64)

    def test_unknown_managed_snapshot(self):
        """Never automatically adopt unknown managed originals."""
        with patch.object(tool.config, 'status', return_value={'managed': None}), \
                patch.object(tool, 'configuration_lock', return_value=nullcontext()):
            with self.assertRaisesRegex(ValueError, 'UNKNOWN'):
                tool.verified_snapshot(Path('/model'), {})

    def test_previous_outside_current_catalog_is_explicitly_unavailable(self):
        """Preserve historical IDs while encoding only selectable previous IDs in the ABI."""
        managed=dict(profile_id='a',previous_id='old-common',sha256={'profile.json':'abc'},configuration_id=5)
        status=dict(managed=managed,identity=dict(boot_id='model'),actual=dict(parameters={}),blob_provenance='model')
        packages={'a':dict(manifest=dict(sha256=managed['sha256'],clock={}))}
        with patch.object(tool.config,'status',return_value=status), \
             patch.object(tool,'configuration_lock',return_value=nullcontext()):
            snapshot=tool.verified_snapshot(Path('/model'),packages)
        self.assertEqual(snapshot['previous'],'')
        self.assertEqual(snapshot['info']['previous_unavailable_in_catalog'],'old-common')
        self.assertEqual(managed['previous_id'],'old-common')
        self.assertEqual(tool.UPDATE.unpack(tool.encode_update(0,tool.READY,snapshot,'a'))[6].rstrip(b'\0'),b'')

    def result_case(self, phase, mismatch=False):
        """Classify modeled service results while preserving complete output evidence."""
        result = dict(transaction_status=phase, profile_id='a', configuration_id=5,
                      sha256={'profile.json': 'abc', 'stream.bin': 'def'})
        snapshot = dict(active='a', configuration_id=6 if mismatch else 5,
                        info={'sha256': result['sha256']})
        if phase == 'rolled_back':
            invocation = patch.object(tool.config, 'apply', side_effect=RuntimeError(json.dumps(result)))
        elif phase == 'busy':
            invocation = patch.object(tool.config, 'apply', side_effect=BlockingIOError('LOCK_BUSY'))
        else:
            invocation = patch.object(tool.config, 'apply', return_value=result)
        with tempfile.TemporaryDirectory() as directory, invocation, \
                patch.object(tool, 'verified_snapshot', return_value=snapshot):
            outcome = tool.execute(Path('/model'), {}, 1, 'a', Path(directory), 'instance')
            self.assertTrue((Path(directory) / 'instance-1.json').exists())
        return outcome

    def test_success_requires_result_and_readback(self):
        """Require successful application, independent readback and matching configuration sequence."""
        self.assertEqual(self.result_case('applied')[0], tool.APPLIED)
        self.assertEqual(self.result_case('applied', mismatch=True)[0], tool.UNAVAILABLE)

    def test_post_rollback_record(self):
        """Use the real manager post schema, not a nonexistent recovery_confirmed field."""
        self.assertEqual(self.result_case('rolled_back')[0], tool.ROLLED_BACK)
        self.assertEqual(self.result_case('rolled_back', mismatch=True)[0], tool.UNAVAILABLE)

    def test_busy_is_not_rollback(self):
        """Prewrite rejection must not claim that recovery executed."""
        self.assertEqual(self.result_case('busy')[0], tool.REJECTED)


if __name__ == '__main__':
    unittest.main()
# End of file: test_profile_iio_broker.py
