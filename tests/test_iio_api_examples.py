"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_iio_api_examples.py
@brief      Test API example conflicts, short I/O, authorization and exception resource cleanup.
@details    Use offline data substitutes without inferring host-library, Qt or hardware qualification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-16
"""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples/iio/python'
sys.path.insert(0,str(EXAMPLE))
from h102_api import Context,SAMPLES
import managed_iq


def test_profile_conflict_rollback_and_snapshot_change():
    """Reject writer conflicts, failed rollback and crossed configuration snapshots."""
    class Control(Context):
        def __init__(self, fault):
            self.fault=fault;self.active='40msps-20mhz';self.ticket=0;self.version=1
            self.lib=type('Lib',(),{'iio_device_attr_write':lambda *args:self.write()})()
        def device(self,*_):return 1
        def write(self):
            self.active='8msps-4mhz';self.ticket+=2 if self.fault=='concurrent' else 1;self.version+=1;return 1
        def profile_read(self,key):
            data=dict(available='40msps-20mhz 8msps-4mhz',active=self.active,request_id=str(self.ticket),
                      configuration_id=str(self.version),status='rolled_back' if self.fault=='rollback' and self.ticket else 'applied',
                      error='injected',active_info=json.dumps(dict(active=self.active,configuration_id=self.version,boot_id='offline')))
            return data[key]
    assert Control('normal').select('8msps-4mhz')['configuration_id']==2
    for fault in ('concurrent','rollback'):
        with pytest.raises(RuntimeError):Control(fault).select('8msps-4mhz')
    with pytest.raises(ValueError):Control('normal').select('unknown')


def test_tone_length_iq_phase_and_peak():
    raw=managed_iq.tone()
    import struct
    pairs=list(struct.iter_unpack('<hh',raw))
    assert len(raw)==SAMPLES*4 and pairs[0]==(8192,0) and pairs[16]==(0,8192)
    assert pairs[:64]==pairs[64:128]


@pytest.fixture(scope='module')
def native_tools(tmp_path_factory):
    """Use supplied header paths without downloading libraries or connecting to a network."""
    build=tmp_path_factory.mktemp('iio-api-build')
    header=os.environ.get('H102_TEST_IIO_INCLUDE')
    if not header:pytest.skip('H102_TEST_IIO_INCLUDE must point to libiio0.x headers')
    binary=build/'h102_iio';fake=build/'fake_iio.so'
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I'+header,
                    str(ROOT/'examples/iio/cpp/h102_iio.cpp'),'/lib/x86_64-linux-gnu/libiio.so.0','-o',str(binary)],check=True)
    subprocess.run(['c++','-std=c++17','-shared','-fPIC','-Wl,-soname,libiio.so.0','-I'+header,
                    str(ROOT/'tests/fixtures/iio-api/fake_iio.cpp'),'-o',str(fake)],check=True)
    return binary,fake


@pytest.mark.parametrize('operation,fault',[
 ('rx','none'),('tx','none'),('rx','short_refill'),('rx','refill_errno'),
 ('rx','format'),('rx','missing_q'),('rx','offset'),('tx','short_push'),('tx','push_errno')])
def test_native_and_python_finite_fault_cleanup(native_tools,tmp_path,operation,fault):
    """Run both data cores with the same substitute and check actual buffer/context destruction."""
    binary,fake=native_tools
    for language in ('cpp','python'):
        audit=tmp_path/(language+'-audit.txt');file=tmp_path/(language+'.iq.partial')
        if operation=='tx':file.write_bytes(managed_iq.tone())
        env=dict(os.environ,LD_PRELOAD=str(fake),H102_FAKE_IIO_FAULT=fault,H102_FAKE_IIO_AUDIT=str(audit))
        if language=='cpp':
            code='''import os,sys
sys.path.insert(0,sys.argv[1]);import managed_iq
from pathlib import Path
managed_iq.cpp_transfer(Path(sys.argv[2]),'ip:offline',sys.argv[3],1,Path(sys.argv[4]),lambda:True)
'''
            args=[sys.executable,'-c',code,str(EXAMPLE),str(binary),operation,str(file)]
        else:
            code='''import sys
sys.path.insert(0,sys.argv[1]);from h102_api import Context
from pathlib import Path
p=Path(sys.argv[3]);raw=p.read_bytes() if sys.argv[2]=='tx' else None
with Context('ip:offline') as ctx:
 result=ctx.transfer(sys.argv[2],1,lambda:True,raw)
if sys.argv[2]=='rx':p.write_bytes(result)
'''
            args=[sys.executable,'-c',code,str(EXAMPLE),operation,str(file)]
        result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=20)
        assert (result.returncode==0)==(fault=='none'),(language,fault,result.stderr)
        events=audit.read_text().splitlines()
        assert events.count('buffer_create')==events.count('buffer_destroy')
        assert events.count('context_destroy')==1
        if fault=='none':assert file.stat().st_size==SAMPLES*4


def test_native_permission_denial_and_output_collision(native_tools,tmp_path,monkeypatch):
    binary,fake=native_tools
    monkeypatch.setenv('LD_PRELOAD',str(fake))
    monkeypatch.setenv('H102_FAKE_IIO_FAULT','none')
    file=tmp_path/'existing';file.write_bytes(b'keep')
    with pytest.raises(RuntimeError):managed_iq.cpp_transfer(binary,'ip:offline','rx',1,file,lambda:False)
    with pytest.raises(RuntimeError):managed_iq.cpp_transfer(binary,'ip:offline','rx',1,file,lambda:True)
    assert file.read_bytes()==b'keep'


@pytest.mark.parametrize('fault',[None,'io','post'])
def test_owner_wrapper_preserves_partial_until_independent_recovery(tmp_path,monkeypatch,fault):
    from threading import Event
    from types import SimpleNamespace
    done=Event();calls=[]
    info=dict(active='8msps-4mhz',configuration_id=2,boot_id='offline')
    class FakeContext:
        def __init__(self,*_):pass
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def snapshot(self):return info
        def transfer(self,direction,channel,permit,raw):
            assert permit()
            if fault=='io':raise RuntimeError('injected IO failure')
            return bytes(SAMPLES*4)
    class FakeBoard:
        password=None
        def __init__(self,*_):pass
        def run(self,command,timeout=80):
            calls.append(command)
            value={}
            if ' manager ' in command:
                assert done.wait(3);return dict(exit=0,stdout='',stderr='')
            if '/ready.json' in command:value={'configuration_id':2}
            elif '/request.json' in command:value={'identity':{'boot_id':'offline'},'configuration_id':2}
            elif ' permit ' in command:value={'permitted':True,'configuration_id':2}
            elif ' stop ' in command:done.set()
            elif '/post.json' in command:value={'passed':fault!='post','configuration_unchanged':True}
            return dict(exit=0,stdout=json.dumps(value),stderr='')
    monkeypatch.setattr(managed_iq,'Context',FakeContext);monkeypatch.setattr(managed_iq,'Board',FakeBoard)
    args=SimpleNamespace(operation='rx',channel=[1],backend='python',host='offline',username='fixture',
                         known_hosts=tmp_path/'keys',output=tmp_path/'out',iq=None)
    if fault:
        with pytest.raises(RuntimeError):managed_iq.run(args,'fixture-only')
        assert not (args.output/'rx1.iq').exists()
        if fault=='post':assert (args.output/'rx1.iq.partial').exists()
    else:
        report=managed_iq.run(args,'fixture-only')
        assert report['status']=='PASS_FINITE_IO_AND_RECOVERY'
        assert (args.output/'rx1.iq').stat().st_size==SAMPLES*4
    assert done.is_set() and any(' stop ' in c for c in calls)


def test_pinned_advanced_runtime_loads_without_qt(tmp_path):
    import managed_session
    supplied=os.environ.get('H102_TEST_GUI_RUNTIME')
    root=Path(supplied) if supplied else tmp_path/'external-runtime-not-supplied'
    if not root.is_dir():pytest.skip('Pinned runtime source checkout not supplied')
    backend,*_=managed_session.load_backend(root)
    assert backend.RxSession and not any(n.startswith('PySide6') for n in sys.modules)
    with pytest.raises(FileNotFoundError):managed_session.load_backend(tmp_path)


def test_cpp_config_transaction_and_workflow_entry(native_tools):
    binary,fake=native_tools
    for fault in ('none','concurrent','rollback'):
        result=subprocess.run([str(binary),'ip:offline','select','8msps-4mhz'],
            env=dict(os.environ,LD_PRELOAD=str(fake),H102_FAKE_IIO_FAULT=fault),capture_output=True,text=True,timeout=5)
        assert (result.returncode==0)==(fault=='none'),result.stderr
    result=subprocess.run([str(binary),'workflow',str(EXAMPLE/'managed_session.py'),'--help'],capture_output=True,text=True,timeout=5)
    assert result.returncode==0 and '--frequency-hz' in result.stdout

# End of file: test_iio_api_examples.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
