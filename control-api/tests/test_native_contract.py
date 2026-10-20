"""Reject invalid entry names and typed USB parameters before filesystem or process effects."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from h102_control.native import NativeDevice, ENTRY_SOURCES
from h102_control.protocol import ProtocolError
from h102_control.usb_worker import validate_request


class NativeContractTests(unittest.TestCase):
    def test_unknown_entry_and_source_mismatch_before_mutation(self):
        device=NativeDevice.__new__(NativeDevice)
        device.manifest={'sources':{name:'a'*64 for name in ENTRY_SOURCES['board_session.py']}}
        device._verify=Mock(side_effect=AssertionError('must reject before installed-source read'))
        for name,sources in [('/tmp/anything.py',{}),('board_session.py',{}),('board_session.py',{'code':'x'})]:
            with self.assertRaises(ProtocolError):device.open_session(name,sources)
        device._verify.assert_not_called()
    def test_index_expiry_preserves_active_and_post_in_progress(self):
        import time
        from types import SimpleNamespace
        device=NativeDevice.__new__(NativeDevice);now=time.monotonic()
        device.sessions={
            'active':SimpleNamespace(closed_at=None,process=Mock()),
            'post':SimpleNamespace(closed_at=now-200,process=Mock(poll=lambda:None)),
            'recent':SimpleNamespace(closed_at=now,process=Mock(poll=lambda:0)),
            'old':SimpleNamespace(closed_at=now-200,process=Mock(poll=lambda:0))}
        device._expire_sessions_locked()
        self.assertEqual(set(device.sessions),{'active','post','recent'})

    def test_usb_fixed_shape(self):
        manifest={'profiles':[{'id':'4msps-2mhz'}]}
        value=dict(profile='4msps-2mhz',boot_id='b'*36,rx_mask=1,tx_mask=0,seconds=10,
                   transmit=False,arbitrary=False,radio_plan=None,sources={})
        validate_request(value,manifest)
        for changes in ({'code':'exec'}, {'rx_mask':True}, {'tx_mask':3}, {'seconds':-1},
                        {'profile':'unknown'}, {'transmit':True},{'radio_plan':{'code':'x'}}):
            with self.subTest(changes=changes),self.assertRaises(ProtocolError):validate_request(dict(value,**changes),manifest)

if __name__=='__main__':unittest.main()
