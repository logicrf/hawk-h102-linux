"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file server.py
@brief Dispatch fixed H102 operations and relay installed native session control.
@details Each connection carries one RPC or persistent session, without arbitrary exec,
         source uploads or file paths. Disconnect closes child input and triggers native recovery.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-17
"""
import base64
import os
import re
import selectors
import socket
import socketserver
import threading

from . import PROTOCOL_VERSION
from .protocol import ProtocolError, decode_frame, encode_frame, receive_frame

_IDENTIFIER = re.compile(r'[a-f0-9]{32}')
_PROFILE = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
_ACTIONS = frozenset(('pulse', 'start', 'stop', 'tune', 'activate_rx',
                      'guard_begin', 'guard_arm', 'guard_end', 'tx_end',
                      'sweep_setup', 'sweep_batch'))


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise ProtocolError('CONTROL_API_OPERATION_FIELDS')


class ApiServer(socketserver.ThreadingTCPServer):
    """Inject reviewed device operations with bounded concurrency and a fixed device version."""
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, device, max_connections=8):
        self.device = device
        self.slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, ApiHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class ApiHandler(socketserver.BaseRequestHandler):
    """Dispatch only listed operations; invalid requests must not invoke device operations."""
    def _reply(self, identifier, result=None, error=None):
        value = dict(version=PROTOCOL_VERSION, request_id=identifier, ok=error is None)
        value['error' if error else 'result'] = error if error else result
        self.request.sendall(encode_frame(value))

    def handle(self):
        identifier = 'invalid'
        reader = self.request.makefile('rb', buffering=0)
        self.request.settimeout(8)
        try:
            value = receive_frame(reader)
            _fields(value, ('version', 'request_id', 'operation', 'arguments'))
            if type(value['version']) is not int or value['version'] != PROTOCOL_VERSION:
                raise ProtocolError('CONTROL_API_VERSION_UNSUPPORTED')
            if not isinstance(value['request_id'], str) or not _IDENTIFIER.fullmatch(value['request_id']):
                raise ProtocolError('CONTROL_API_REQUEST_ID')
            identifier = value['request_id']
            operation, args = value['operation'], value['arguments']
            if operation == 'status':
                _fields(args, ())
                self._reply(identifier, self.server.device.status())
            elif operation == 'metadata':
                _fields(args, ())
                self._reply(identifier, self.server.device.metadata())
            elif operation == 'profile.select':
                _fields(args, ('profile', 'boot_id'))
                if not isinstance(args['profile'], str) or not _PROFILE.fullmatch(args['profile']):
                    raise ProtocolError('CONTROL_API_PROFILE_ID')
                if not isinstance(args['boot_id'], str) or len(args['boot_id']) != 36:
                    raise ProtocolError('CONTROL_API_BOOT_ID')
                self._reply(identifier, self.server.device.select(args['profile'], args['boot_id']))
            elif operation == 'session.records':
                _fields(args, ('session_id',))
                if not isinstance(args['session_id'], str) or not _IDENTIFIER.fullmatch(args['session_id']):
                    raise ProtocolError('CONTROL_API_SESSION_ID')
                self._reply(identifier, self.server.device.records(args['session_id']))
            elif operation in ('session.evidence.open','session.evidence.chunk','session.evidence.retire'):
                from .session_evidence import evidence
                action=operation.rsplit('.',1)[1]
                extra=('index',) if action=='chunk' else ('archive_sha256',) if action=='retire' else ()
                _fields(args,('session_id',)+extra)
                if not isinstance(args['session_id'],str) or not _IDENTIFIER.fullmatch(args['session_id']):
                    raise ProtocolError('CONTROL_API_SESSION_ID')
                self._reply(identifier,evidence(self.server.device,args['session_id'],action,
                    index=args.get('index'),archive_sha256=args.get('archive_sha256')))
            elif operation == 'session.open':
                _fields(args, ('entrypoint', 'sources'))
                session = self.server.device.open_session(args['entrypoint'], args['sources'])
                try:
                    self._reply(identifier, session.public_info)
                    self.request.settimeout(None)
                    self._relay(session)
                finally:
                    # Relay failures close stdin; never renew a client heartbeat in the background.
                    session.close()
            elif operation == 'usb.open':
                session = self.server.device.open_usb(args)
                try:
                    self._reply(identifier, session.public_info)
                    self.request.settimeout(None)
                    self._relay(session)
                finally:
                    session.close()
            elif operation == 'usb.records':
                _fields(args, ('session_id',))
                if not isinstance(args['session_id'], str) or not _IDENTIFIER.fullmatch(args['session_id']):
                    raise ProtocolError('CONTROL_API_SESSION_ID')
                self._reply(identifier, self.server.device.usb_records(args['session_id']))
            elif operation in ('usb.evidence.open','usb.evidence.chunk','usb.evidence.retire'):
                action=operation.rsplit('.',1)[1]
                extra=('index',) if action=='chunk' else ('archive_sha256',) if action=='retire' else ()
                _fields(args,('session_id',)+extra)
                if not isinstance(args['session_id'],str) or not _IDENTIFIER.fullmatch(args['session_id']):raise ProtocolError('CONTROL_API_SESSION_ID')
                self._reply(identifier,self.server.device.usb_evidence(args['session_id'],action,
                    index=args.get('index'),archive_sha256=args.get('archive_sha256')))
            else:
                raise ProtocolError('CONTROL_API_OPERATION_UNSUPPORTED')
        except Exception as error:
            # Keep complete diagnostics on the device; do not echo request text or traceback.
            code = str(error) if isinstance(error, ProtocolError) else ('CONTROL_API_DEVICE_BUSY' if isinstance(error, BlockingIOError) else 'CONTROL_API_DEVICE_OPERATION_FAILED')
            try:
                self._reply(identifier, error=dict(code=code, detail=(type(error).__name__+': '+str(error))[:1000]))
            except OSError:
                pass
        finally:
            reader.close()

    def _relay(self, session):
        """Relay native stdout, stderr and exit status, accepting only known control actions.

        Nonblocking input prevents an incomplete network frame from blocking output draining.
        The native heartbeat enforces timeouts; the relay does not execute client text.
        """
        from .protocol import MAX_FRAME_BYTES
        process = session.process
        pending = bytearray()
        pending_input = bytearray()
        selector = selectors.DefaultSelector()
        self.request.setblocking(False)
        os.set_blocking(process.stdin.fileno(), False)
        for pipe in (process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
        selector.register(self.request, selectors.EVENT_READ, 'network')
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        output_open = {'stdout', 'stderr'}

        def send(value):
            # Bound large response delivery so an unread client cannot retain a root worker forever.
            self.request.settimeout(8)
            try:
                self.request.sendall(encode_frame(value))
            finally:
                self.request.setblocking(False)

        try:
            while output_open or process.poll() is None:
                for key, _ in selector.select(0.1):
                    if key.data == 'network':
                        chunk = self.request.recv(65536)
                        if not chunk:
                            return
                        pending.extend(chunk)
                        if len(pending) > MAX_FRAME_BYTES:
                            raise ProtocolError('CONTROL_API_SESSION_COMMAND_LIMIT')
                        while b'\n' in pending:
                            line, _, tail = pending.partition(b'\n')
                            pending = bytearray(tail)
                            value = decode_frame(bytes(line) + b'\n')
                            _fields(value, ('control',))
                            control = value['control']
                            allowed = (control.get('op') in ('renew', 'receiver_ready', 'sender_ready', 'start', 'stop', 'close',
                                       'arm', 'drain', 'finish_drain') or
                                       (control.get('op') in ('prepare_epoch','audit_open','audit_chunk','audit_retire','receiver_ready_start') and session.public_info.get('reusable') is True)
                                       if getattr(session, 'kind', None) == 'usb' else (control.get('action') in _ACTIONS or
                                             (control.get('action')=='sweep_finish' and session.public_info.get('entrypoint')=='board_fm_scan_stream.py') or
                                             (control.get('action') in ('guard_end_all','guard_reset') and
                                              session.public_info.get('entrypoint') in ('board_rx_stream.py','board_rx_batch_stream.py','board_fm_scan_stream.py')) or
                                             (control.get('action') in ('guard_begin_all','guard_arm_all') and
                                              session.public_info.get('entrypoint') in ('board_rx_batch_stream.py','board_fm_scan_stream.py')))) if isinstance(control, dict) else False
                            if not allowed:
                                raise ProtocolError('CONTROL_API_SESSION_ACTION')
                            pending_input.extend(encode_frame(control))
                            if len(pending_input) > MAX_FRAME_BYTES:
                                raise ProtocolError('CONTROL_API_SESSION_INPUT_LIMIT')
                            try:
                                selector.get_key(process.stdin)
                            except KeyError:
                                selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
                    elif key.data == 'stdin':
                        try:
                            written = os.write(process.stdin.fileno(), pending_input[:65536])
                            del pending_input[:written]
                        except BlockingIOError:
                            pass
                        if not pending_input:
                            selector.unregister(process.stdin)
                    else:
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            output_open.discard(key.data)
                        else:
                            send(dict(stream=key.data, data=base64.b64encode(data).decode('ascii')))
            send(dict(stream='exit', status=process.wait()))
        finally:
            selector.close()

# End of file: server.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
