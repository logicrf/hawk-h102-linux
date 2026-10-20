"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file session_evidence.py
@brief Archive recovered RX sessions and retire their data after verified client download.
@details Accept neither network paths nor code. Use the installed archiver after recovery;
         retirement requires host extraction and hash verification, with repeatable receipts.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
import base64
import hashlib
import io
import json
import subprocess
import tarfile

from .protocol import ProtocolError


def evidence(device, identifier, action, index=None, archive_sha256=None):
    """Serialize session transactions; failed validation never deletes session data."""
    with device.lock:
        session = device.sessions.get(identifier)
    if session is None or session.public_info.get('entrypoint') not in ('board_rx_stream.py', 'board_rx_batch_stream.py', 'board_fm_scan_stream.py'):
        raise ProtocolError('CONTROL_API_RX_ARCHIVE_SESSION_UNKNOWN')
    if session.process.poll() is None:
        # Wait for worker exit after the manager's terminal frame; do not force termination.
        try:session.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            raise ProtocolError('CONTROL_API_RX_ARCHIVE_WORKER_NOT_TERMINAL') from None
    device._verify()
    with session.evidence_lock:
        if action == 'retire' and hasattr(session, 'retire_receipt'):
            if archive_sha256 != session.retire_receipt['archive_sha256']:
                raise ProtocolError('CONTROL_API_RX_ARCHIVE_RECEIPT')
            return session.retire_receipt
        cache = device.runtime_root/(identifier+'-archive')
        archive = cache/'runtime.tar.gz'
        if action == 'open':
            if hasattr(session, 'retire_receipt'):
                raise ProtocolError('CONTROL_API_RX_ARCHIVE_ALREADY_RETIRED')
            if not archive.exists():
                records = device.records(identifier)
                request = records.get('request.json', {})
                identity = device.config.identity()
                if request.get('identity') != identity:
                    raise ProtocolError('CONTROL_API_RX_ARCHIVE_IDENTITY')
                params = dict(directory=str(session.directory), boot_id=identity['boot_id'],
                              machine_id=identity['machine_id'])
                value = _run(params)
                raw = base64.b64decode(value['archive_base64'], validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if len(raw) > 8*1024*1024 or digest != value['archive_sha256']:
                    raise ProtocolError('CONTROL_API_RX_ARCHIVE_SHA')
                with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as packed:
                    session.archive_manifest = json.load(packed.extractfile('manifest.json'))
                session.archive_params = params
                session.final_iio_records = records
                cache.mkdir(mode=0o700)
                archive.write_bytes(raw)
            return dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                        bytes=archive.stat().st_size, chunk_size=65536)
        if not archive.exists():
            raise ProtocolError('CONTROL_API_RX_ARCHIVE_NOT_PREPARED')
        if action == 'chunk':
            if type(index) is not int or index < 0 or index*65536 >= archive.stat().st_size:
                raise ProtocolError('CONTROL_API_RX_ARCHIVE_CHUNK')
            with archive.open('rb') as stream:
                stream.seek(index*65536);raw = stream.read(65536)
            return dict(index=index, data=base64.b64encode(raw).decode())
        if action != 'retire' or archive_sha256 != hashlib.sha256(archive.read_bytes()).hexdigest():
            raise ProtocolError('CONTROL_API_RX_ARCHIVE_RECEIPT')
        receipt = dict(_run(dict(session.archive_params, expected=session.archive_manifest)),
                       archive_sha256=archive_sha256, host_restore_verified_receipt=True)
        # Persist a repeatable receipt before releasing cache; the host keeps the full archive.
        (cache/'retire.json').write_text(json.dumps(receipt))
        session.retire_receipt = receipt
        archive.unlink()
        return receipt


def _run(parameters):
    """Invoke only the pinned installed archiver, passing parameters through stdin."""
    from iio_runtime_archive import ROOT_CODE
    reply = subprocess.run(['/usr/bin/python3', '-B', '-c',
        'import sys\n'+ROOT_CODE.replace('PARAMETERS', 'json.load(sys.stdin)')],
        input=json.dumps(parameters), capture_output=True, text=True, timeout=45)
    if reply.returncode:
        # CalledProcessError may contain the entire -c program and obscure the actual assertion.
        # Return only a bounded diagnostic tail, without source or archive contents.
        raise ProtocolError('CONTROL_API_RX_ARCHIVE_CHECK_FAILED:'+reply.stderr[-700:])
    return json.loads(reply.stdout)

# End of file: session_evidence.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
