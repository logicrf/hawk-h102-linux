"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file native.py
@brief Run fixed SDK queries and configuration operations on the H102.
@details A root-owned installation manifest pins helper and SDK source files. Requests
         can select only registered entries and parameters; PID1 handles independent recovery.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-17
"""
from contextlib import ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from threading import Lock
import time
import uuid

from . import PROTOCOL_VERSION, __version__
from .protocol import ProtocolError

# Entry dependencies are fixed by this service, not expanded by network requests.
ENTRY_SOURCES = {
    'board_fm_scan_stream.py': ('board_fm_scan_stream.py', 'board_tx.py', 'board_radio.py',
                               'tx_cyclic.py', 'board_capture.py'),
    'board_rx_batch_stream.py': ('board_rx_batch_stream.py', 'board_tx.py', 'board_radio.py',
                                 'tx_cyclic.py', 'board_capture.py'),
    'board_rx_stream.py': ('board_rx_stream.py', 'board_tx.py', 'board_radio.py',
                           'tx_cyclic.py', 'board_capture.py'),
    'board_session.py': ('board_session.py', 'board_radio.py', 'board_capture.py'),
    'board_tx.py': ('board_tx.py', 'board_radio.py', 'tx_cyclic.py'),
    'board_iio_tx.py': ('board_iio_tx.py', 'board_tx.py', 'board_radio.py', 'tx_cyclic.py'),
    'board_fm_stream.py': ('board_fm_stream.py', 'board_tx.py', 'board_radio.py',
                           'tx_cyclic.py', 'board_capture.py'),
    'board_iio_stream.py': ('board_iio_stream.py', 'board_tx.py', 'board_radio.py',
                            'tx_cyclic.py', 'board_capture.py'),
}


def _private(path, directory=False):
    info = path.lstat()
    if (info.st_uid != 0 or info.st_mode & 0o077 or
            (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))):
        raise PermissionError('CONTROL_API_INSTALL_NOT_ROOT_PRIVATE')


class NativeSession:
    """Own a private root worker; close its input before waiting for actual recovery."""
    def __init__(self, directory, entrypoint, source_sha, manifest_sha):
        self.evidence_lock = Lock()
        self.directory = directory
        self.closed = False
        self.closed_at = None
        self.created = time.monotonic()
        self.public_info = dict(session_id=directory.name.removeprefix('h102-gui-session-'), directory=str(directory),
                                entrypoint=entrypoint, sources=source_sha,
                                service_manifest_sha256=manifest_sha)
        self.process = subprocess.Popen(
            ['/usr/bin/python3', '-B', str(directory / entrypoint), 'warm', '--directory', str(directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, cwd=directory, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                                         'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1'})

    def close(self):
        """EOF stops the source and runs recovery; preserve unknown state if the deadline expires."""
        if self.closed:
            return
        self.closed = True
        try:self.process.stdin.close()
        except BrokenPipeError:pass
        self.process.stdin = None
        try:
            # Drain bounded native output after disconnect so recovery cannot deadlock on a full pipe.
            self.process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate(timeout=10)
        finally:
            self.closed_at=time.monotonic()


class NativeDevice:
    """Validate all pinned installation inputs; ordinary API calls never supply source or paths."""
    def __init__(self, root, runtime_root=Path('/run/h102-control-api')):
        if os.geteuid() != 0:
            raise PermissionError('CONTROL_API_ROOT_SERVICE_REQUIRED')
        self.root = Path(root).resolve()
        _private(self.root, directory=True)
        manifest_path = self.root / 'manifest.json'
        _private(manifest_path)
        self.manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        self.manifest = json.loads(manifest_path.read_text())
        os.umask(0o077)
        self.bundle = self.root / 'bundle'
        _private(self.bundle, directory=True)
        names = set().union(*map(set, ENTRY_SOURCES.values())) | {'usb_runtime_candidate.py', 'gr_usb_radio.py', 'runtime_archive.py', 'iio_runtime_archive.py', 'usb_rx_reuse_candidate.py', 'gr_usb_reuse.py'}
        if set(self.manifest['sources']) != names:
            raise ProtocolError('CONTROL_API_INSTALL_SOURCE_SET')
        self._verify()
        self.runtime_root = Path(runtime_root)
        self.runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private(self.runtime_root, directory=True)
        self.sessions = {}
        self.lock = Lock()
        sys.path.insert(0, str(self.bundle))
        self.radio = importlib.import_module('board_radio')
        self.config, self.rx, self.configuration_lock = self.radio.modules()

    def _verify(self):
        pins=self.manifest['firmware']
        if (os.uname().release!=pins['kernel'] or
                hashlib.sha256(Path('/etc/h102/sdk1-image.json').read_bytes()).hexdigest()!=pins['metadata_sha256']):
            raise ProtocolError('CONTROL_API_TARGET_FIRMWARE_CHANGED')
        for name, digest in self.manifest['sources'].items():
            path = self.bundle / name
            _private(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ProtocolError('CONTROL_API_INSTALLED_SOURCE_CHANGED')
        for name, digest in self.manifest['sdk_sources'].items():
            if not re.fullmatch(r'[A-Za-z0-9_]+\.py', name):
                raise ProtocolError('CONTROL_API_SDK_SOURCE_NAME')
            path = Path('/usr/local/lib/h102/sdk1/scripts') / name
            # Released SDK files may be root-readable but must not be writable by group or others.
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
                raise PermissionError('CONTROL_API_SDK_SOURCE_PERMISSIONS')
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ProtocolError('CONTROL_API_SDK_SOURCE_CHANGED')

    def metadata(self):
        """Read fixed firmware metadata; do not provide arbitrary file downloads."""
        path = Path('/etc/h102/sdk1-image.json')
        return dict(api_version=PROTOCOL_VERSION, service_version=__version__,
                    service_manifest_sha256=self.manifest_sha, installation_version=self.manifest['service_version'],
                    metadata_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())

    def status(self):
        """Allow brief query lock contention, then report BUSY if a real owner remains active."""
        deadline=time.monotonic()+3
        while True:
            try:return self._status_once()
            except BlockingIOError:
                if time.monotonic()>=deadline:raise
                time.sleep(.1)

    def _status_once(self):
        """Hold the configuration lock across the snapshot and LO readback."""
        self._verify()
        c = self.config
        with self.configuration_lock():
            snapshot = c.status(c.CATALOG)
            if snapshot['identity']['boot_pins']!=self.manifest['firmware']['boot_pins']:
                raise ProtocolError('CONTROL_API_TARGET_BOOT_PINS_CHANGED')
            state = snapshot['managed']
            if not state:
                raise RuntimeError('CONTROL_API_ACTIVE_PACKAGE_UNKNOWN')
            package = c.load_package(c.CATALOG, state['profile_id'], trusted=True)
            available = [v['id'] for v in self.manifest['profiles']]
            if state['profile_id'] not in available:
                raise RuntimeError('CONTROL_API_ACTIVE_PROFILE_UNAPPROVED')
            with ExitStack() as stack:
                hardware = c.hardware_context(stack, self.runtime_root, snapshot['identity'])
                hardware.idle()
                radio = self.radio.describe(hardware, state, c.CATALOG)
            info = dict(schema=1, active=state['profile_id'],
                        configuration_id=state['configuration_id'], boot_id=snapshot['identity']['boot_id'],
                        parameters=snapshot['actual']['parameters'], clock=package['manifest']['clock'],
                        ssi='LVDS-2lane-DDR-16bit', api=c.API, sha256=state['sha256'],
                        provenance=snapshot['blob_provenance'], verified_monotonic_ns=time.monotonic_ns(),
                        qualification='configuration_only; data/rf/gnss_not_qualified', radio=radio)
            actual = dict(identity=snapshot['identity'], parameters=snapshot['actual']['parameters'],
                          radio=radio, data_idle=True, kernel=os.uname().release,
                          image=json.loads(Path('/etc/h102/sdk1-image.json').read_bytes()))
            actual.update(self.metadata())
            return dict(available=available, info=info, actual=actual)

    def select(self, profile, boot_id):
        """Check boot and approved profile identity before invoking native managed configuration."""
        if boot_id != self.metadata()['boot_id']:
            raise ValueError('CONTROL_API_BOOT_CHANGED')
        if profile not in {p['id'] for p in self.manifest['profiles']}:
            raise ValueError('CONTROL_API_PROFILE_UNAPPROVED')
        self.config.apply(self.config.CATALOG, profile)
        result = self.status()
        if result['info']['active'] != profile or result['info']['boot_id'] != boot_id:
            raise RuntimeError('CONTROL_API_SELECT_READBACK_MISMATCH')
        return result

    def _expire_sessions_locked(self):
        """Retire only terminal in-memory records closed for over three minutes."""
        now=time.monotonic()
        expired=[key for key,value in self.sessions.items() if value.closed_at is not None
                 and value.process.poll() is not None and now-value.closed_at>180]
        for key in expired:
            session = self.sessions[key]
            if hasattr(session, 'final_iio_records') and hasattr(session, 'retire_receipt'):
                # Evict only this session's completed receipt cache; preserve unfinished downloads.
                cache = self.runtime_root/(key+'-archive')
                if cache.exists():
                    _private(cache, directory=True)
                    if {p.name for p in cache.iterdir()} != {'retire.json'}:
                        raise ProtocolError('CONTROL_API_RX_ARCHIVE_CACHE_CHANGED')
                    receipt = cache/'retire.json'
                    _private(receipt)
                    if json.loads(receipt.read_bytes()) != session.retire_receipt:
                        raise ProtocolError('CONTROL_API_RX_ARCHIVE_CACHE_CHANGED')
                    receipt.unlink();cache.rmdir()
            if (getattr(session,'kind',None)=='usb' and hasattr(session,'final_usb_records') and
                    hasattr(session,'retire_receipt')):
                # Original session data has already been retired after verified host archival.
                directory=self.runtime_root/key
                if directory!=session.directory:
                    raise ProtocolError('CONTROL_API_USB_CACHE_IDENTITY')
                if directory.exists():
                    _private(directory,directory=True)
                    if {p.name for p in directory.iterdir()}!={'usb-request.json','retire.json'}:
                        raise ProtocolError('CONTROL_API_USB_CACHE_CHANGED')
                    for name,expected in (('usb-request.json',session.usb_request),('retire.json',session.retire_receipt)):
                        path=directory/name;_private(path)
                        if json.loads(path.read_bytes())!=expected:
                            raise ProtocolError('CONTROL_API_USB_CACHE_CHANGED')
                    (directory/'usb-request.json').unlink();(directory/'retire.json').unlink();directory.rmdir()
            del self.sessions[key]

    def open_session(self, entrypoint, sources):
        """Check installed file hashes before creating a session; requests contain no source text."""
        if not isinstance(entrypoint, str) or entrypoint not in ENTRY_SOURCES:
            raise ProtocolError('CONTROL_API_ENTRYPOINT_UNSUPPORTED')
        wanted = {name: self.manifest['sources'][name] for name in ENTRY_SOURCES[entrypoint]}
        if sources != wanted:
            raise ProtocolError('CONTROL_API_CLIENT_NATIVE_SOURCE_MISMATCH')
        self._verify()
        with self.lock:
            # Retain disk evidence while allowing completed sessions to leave the bounded memory index.
            self._expire_sessions_locked()
            if len(self.sessions) >= 128:
                raise RuntimeError('CONTROL_API_SESSION_INDEX_LIMIT')
            identifier=uuid.uuid4().hex
            directory = Path('/run') / ('h102-gui-session-'+identifier)
            directory.mkdir(mode=0o700)
            for name in wanted:
                shutil.copyfile(self.bundle / name, directory / name)
                (directory / name).chmod(0o600)
            session = NativeSession(directory, entrypoint, wanted, self.manifest_sha)
            self.sessions[identifier] = session
            return session

    def open_usb(self, args):
        """Validate USB mode and parameters before creating an owned private directory."""
        from .usb_worker import validate_request, USB_SOURCES, USB_REUSE_SOURCES
        validate_request(args, self.manifest)
        if args['boot_id'] != self.metadata()['boot_id']:
            raise ProtocolError('CONTROL_API_BOOT_CHANGED')
        names=USB_REUSE_SOURCES if args.get('reusable') else USB_SOURCES
        if args['sources'] != {name:self.manifest['sources'][name] for name in names}:
            raise ProtocolError('CONTROL_API_CLIENT_NATIVE_SOURCE_MISMATCH')
        self._verify()
        with self.lock:
            self._expire_sessions_locked()
            if len(self.sessions) >= 128:raise RuntimeError('CONTROL_API_SESSION_INDEX_LIMIT')
            identifier=uuid.uuid4().hex
            directory=self.runtime_root/identifier
            directory.mkdir(mode=0o700)
            request=dict(args,board_directory='/run/h102-runtime-usb-data-c16-gr-'+identifier,
                         code_root='/run/h102-gr-usb-code-'+identifier)
            (directory/'usb-request.json').write_text(json.dumps(request))
            session=NativeSession.__new__(NativeSession)
            session.evidence_lock=Lock()
            session.kind='usb';session.directory=directory;session.closed=False;session.closed_at=None;session.created=time.monotonic()
            session.usb_request=request
            session.public_info=dict(session_id=identifier,directory=request['board_directory'],
                                     code_root=request['code_root'],sources=args['sources'],reusable=bool(args.get('reusable')))
            session.process=subprocess.Popen(
                ['/usr/bin/python3','-u','-B','-m','h102_control.usb_worker','--root',str(self.root),
                 '--directory',str(directory)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                bufsize=0,cwd=self.root,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8',
                                          'PYTHONPATH':str(self.root),'PYTHONNOUSERSITE':'1'})
            self.sessions[identifier]=session
            return session

    def usb_records(self, identifier):
        """Collect terminal results only for issued USB sessions, without caller-supplied paths."""
        with self.lock:session=self.sessions.get(identifier)
        if session is None or getattr(session,'kind',None)!='usb':
            raise ProtocolError('CONTROL_API_USB_SESSION_UNKNOWN')
        if hasattr(session,'retire_receipt'):return session.final_usb_records
        directory=Path(session.usb_request['board_directory'])
        result={}
        for name in ('summary.json','post.json','outer-post.json','manager-result.json','main-error.json','manager-error.json'):
            path=directory/name
            if path.exists():
                _private(path)
                if path.stat().st_size>1024*1024:raise ProtocolError('CONTROL_API_RECORD_SIZE_LIMIT')
                result[name]=json.loads(path.read_bytes())
            else:result[name]=None
        return result

    def usb_evidence(self, identifier, action, index=None, archive_sha256=None):
        """Archive only the service-owned USB directories and retire after verified download."""
        import base64
        import io
        import tarfile
        with self.lock:session=self.sessions.get(identifier)
        if session is None or getattr(session,'kind',None)!='usb':raise ProtocolError('CONTROL_API_USB_SESSION_UNKNOWN')
        if session.process.poll() is None:raise ProtocolError('CONTROL_API_USB_BRIDGE_NOT_TERMINAL')
        # Serialize archive transactions for each session, including download and retirement.
        with session.evidence_lock:
            archive=session.directory/'runtime.tar.gz'
            if action=='open':
                if not archive.exists():
                    from runtime_archive import ROOT_CODE
                    params=dict(paths=[session.usb_request['board_directory'],session.usb_request['code_root']],
                                boot_id=session.usb_request['boot_id'],machine_id=self.config.identity()['machine_id'])
                    reply=subprocess.run(['/usr/bin/python3','-B','-c','import sys\n'+ROOT_CODE.replace('PARAMETERS','json.load(sys.stdin)')],
                                         input=json.dumps(params),capture_output=True,text=True,timeout=65,check=True)
                    value=json.loads(reply.stdout);raw=base64.b64decode(value['archive_base64'],validate=True)
                    digest=hashlib.sha256(raw).hexdigest()
                    if len(raw)>8*1024*1024 or digest!=value['archive_sha256']:raise ProtocolError('CONTROL_API_USB_ARCHIVE_SHA')
                    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as packed:
                        session.archive_manifest=json.load(packed.extractfile('manifest.json'))
                    session.archive_params=params
                    session.final_usb_records=self.usb_records(identifier)
                    archive.write_bytes(raw)
                raw_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
                return dict(archive_sha256=raw_sha,bytes=archive.stat().st_size,chunk_size=65536)
            if action=='retire' and hasattr(session,'retire_receipt'):
                if archive_sha256!=session.retire_receipt['archive_sha256']:raise ProtocolError('CONTROL_API_USB_ARCHIVE_RECEIPT')
                return session.retire_receipt
            if not archive.exists():raise ProtocolError('CONTROL_API_USB_ARCHIVE_NOT_PREPARED')
            if action=='chunk':
                if type(index) is not int or index<0 or index*65536>=archive.stat().st_size:raise ProtocolError('CONTROL_API_USB_ARCHIVE_CHUNK')
                with archive.open('rb') as stream:stream.seek(index*65536);raw=stream.read(65536)
                return dict(index=index,data=base64.b64encode(raw).decode())
            if action!='retire' or archive_sha256!=hashlib.sha256(archive.read_bytes()).hexdigest():
                raise ProtocolError('CONTROL_API_USB_ARCHIVE_RECEIPT')
            if hasattr(session,'retire_receipt'):return session.retire_receipt
            from runtime_archive import ROOT_CODE
            params=dict(session.archive_params,expected=session.archive_manifest)
            reply=subprocess.run(['/usr/bin/python3','-B','-c','import sys\n'+ROOT_CODE.replace('PARAMETERS','json.load(sys.stdin)')],
                                 input=json.dumps(params),capture_output=True,text=True,timeout=65,check=True)
            receipt=dict(json.loads(reply.stdout),archive_sha256=archive_sha256,host_restore_verified_receipt=True)
            (session.directory/'retire.json').write_text(json.dumps(receipt))
            session.retire_receipt=receipt
            archive.unlink()  # Release download cache after the client verifies extraction and hashes.
            return receipt

    def records(self, session_id):
        """Return fixed JSON and systemd state for issued sessions; reject arbitrary paths."""
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ValueError('CONTROL_API_SESSION_UNKNOWN')
        if hasattr(session, 'retire_receipt') and hasattr(session, 'final_iio_records'):
            return session.final_iio_records
        directory = session.directory
        _private(directory, directory=True)
        result = {}
        for name in ('request.json', 'ready.json', 'main.json', 'post.json', 'manager.json'):
            path = directory / name
            if path.exists():
                _private(path)
                if path.stat().st_size > 1024 * 1024:
                    raise ProtocolError('CONTROL_API_RECORD_SIZE_LIMIT')
                result[name] = json.loads(path.read_bytes())
        request = result.get('request.json') or {}
        unit = request.get('unit')
        if unit:
            if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,200}', unit):
                raise ProtocolError('CONTROL_API_RECORDED_UNIT_INVALID')
            result['_unit_properties'] = subprocess.run(
                ['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'Result', '-p', 'ExecMainStatus'],
                capture_output=True, text=True, timeout=10, check=True).stdout
        return result

# End of file: native.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
