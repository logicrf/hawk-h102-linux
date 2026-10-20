"""Test TCP and subprocess failures without device access or hardware qualification."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h102_control.client import Client, Connection, DeviceError
from h102_control.channel import SessionChannel
from h102_control.protocol import encode_frame, receive_frame
from h102_control.server import ApiServer


class Session:
    def __init__(self):
        self.public_info = {'session_id': 'a'*32, 'sources': {}, 'entrypoint': 'fixture.py'}
        self.closed = threading.Event()
        code = '''import sys,json
print(json.dumps({'type':'warm'}),flush=True)
for line in sys.stdin:
 v=json.loads(line)
 print(json.dumps({'received':v}),flush=True)
 if v.get('action')=='stop':break
print('fixture stderr',file=sys.stderr,flush=True)
'''
        self.process = subprocess.Popen([sys.executable, '-u', '-c', code], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    def close(self):
        self.process.stdin.close()
        self.process.stdin = None
        self.process.communicate(timeout=3)
        self.closed.set()


class Device:
    def __init__(self):
        self.calls = []
        self.session = None
    def status(self):
        self.calls.append('status')
        return {'available': ['4msps-2mhz'], 'actual': {'identity': {'fixture': True}}}
    def open_session(self, entrypoint, sources):
        if entrypoint != 'fixture.py' or sources != {}:
            raise ValueError('BAD_SOURCE')
        self.calls.append('open')
        self.session = Session()
        return self.session


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.server = ApiServer(('127.0.0.1', 0), self.device)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.connection = Connection('127.0.0.1', self.server.server_address[1])
        self.client = Client(self.connection)
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)
    def wait_for(self, check):
        deadline = time.monotonic()+3
        while not check():
            if time.monotonic()>deadline:self.fail('fixture deadline')
            time.sleep(.01)
    def test_status_and_no_credentials(self):
        self.assertTrue(self.client.status()['actual']['identity']['fixture'])
        self.assertEqual(set(self.connection.__dict__), {'host', 'port'})
    def test_reject_before_device_side_effect(self):
        for operation, arguments in [('exec', {'code': 'anything'}), ('status', {'path': '/etc/passwd'}),
                                     ('session.open', {'entrypoint': 'fixture.py', 'sources': {}, 'code':'x'})]:
            with self.assertRaises(DeviceError):self.client.request(operation, arguments)
        self.assertEqual(self.device.calls, [])
    def test_bad_version_and_fragmented_request(self):
        for version in (True, 2):
            with socket.create_connection((self.connection.host,self.connection.port)) as peer:
                wire=encode_frame(dict(version=version,request_id='b'*32,operation='status',arguments={}))
                for byte in wire:peer.sendall(bytes((byte,)))
                with peer.makefile('rb') as reader:self.assertFalse(receive_frame(reader)['ok'])
        self.assertEqual(self.device.calls, [])
    def test_native_session_duplex_and_exit(self):
        peer,reader,info=self.client.open_session('fixture.py', {})
        channel=SessionChannel(peer, reader)
        try:
            self.wait_for(channel.recv_ready)
            self.assertIn(b'warm', channel.recv(65536))
            channel.sendall(json.dumps({'action':'pulse'})+'\n')
            self.wait_for(channel.recv_ready)
            self.assertEqual(json.loads(channel.recv(65536))['received'], {'action':'pulse'})
            channel.sendall(json.dumps({'action':'stop'})+'\n')
            self.wait_for(channel.exit_status_ready)
            self.assertEqual(channel.recv_exit_status(), 0)
            self.assertIn(b'fixture stderr',channel.recv_stderr(65536))
        finally:channel.close()
        self.assertTrue(self.device.session.closed.wait(3))
    def test_disconnect_closes_native_stdin(self):
        peer,reader,info=self.client.open_session('fixture.py', {})
        channel=SessionChannel(peer,reader)
        self.wait_for(channel.recv_ready)
        channel.close()
        self.assertTrue(self.device.session.closed.wait(3))
        self.assertIsNotNone(self.device.session.process.poll())
    def test_unsupported_session_action_revokes(self):
        peer,reader,info=self.client.open_session('fixture.py', {})
        channel=SessionChannel(peer,reader)
        try:
            channel.sendall(json.dumps({'action':'exec','code':'untrusted'})+'\n')
            self.assertTrue(self.device.session.closed.wait(3))
        finally:channel.close()

if __name__ == '__main__':unittest.main()
