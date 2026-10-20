#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       managed_iq.py
@brief      Run Python or native C++ IQ examples under the released finite board owner.
@details    Transfer data over IIO; use SSH for same-boot authorization and recovery only.
            Credentials stay in memory; preserve partial files on failure and publish after recovery.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-16
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import select
import shlex
import socket
import struct
import subprocess
import sys
import time
import uuid

from h102_api import Context, SAMPLES

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE_ROOT if (EXAMPLE_ROOT/'scripts/run_h102_sdk1_iio_rx.py').is_file() else Path(__file__).resolve().parents[3]
LOCK = json.loads((EXAMPLE_ROOT/'runtime.lock.json').read_text())
for name,digest in LOCK['linux_helpers'].items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
        raise RuntimeError('Example support source mismatch: '+name)
sys.path.insert(0,str(ROOT/'scripts'))
from run_h102_sdk1_iio_rx import Board


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def tone():
    """Build period-64 IQ16 bytes with digital amplitude 8192, without controlling RF."""
    return b''.join(struct.pack('<hh',round(8192*math.cos(2*math.pi*n/64)),
                               round(8192*math.sin(2*math.pi*n/64))) for n in range(SAMPLES))


def cpp_transfer(tool, uri, operation, channel, file, permit):
    """Request real authorization over a private socket; never substitute an always-true permit."""
    parent, child=socket.socketpair()
    process=None
    try:
        process=subprocess.Popen([str(tool),uri,operation,str(channel),str(file),str(child.fileno())],
                                 pass_fds=(child.fileno(),),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        child.close();deadline=time.monotonic()+25
        while process.poll() is None:
            if time.monotonic()>=deadline:raise TimeoutError('C++ finite IO deadline')
            readable,_,_=select.select([parent],[],[],.1)
            if readable:
                value=parent.recv(1)
                if not value:break
                if value!=b'?':raise RuntimeError('Unknown owner request')
                parent.sendall(b'Y' if permit() else b'N')
        out,err=process.communicate(timeout=5)
        if process.returncode:raise RuntimeError('C++ IO failed: '+err.decode(errors='replace')[-1000:])
        return dict(returncode=process.returncode,stdout=out.decode(errors='replace'))
    finally:
        parent.close();child.close()
        if process is not None and process.poll() is None:
            # Close the guard socket to trigger C++ cleanup; bound waiting after the 1500 ms IIO timeout.
            try:process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.communicate(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.communicate()


def run(args, password):
    """Use installed scripts only, without uploads, service changes, profile selection or RF."""
    if len(set(args.channel))!=len(args.channel):raise ValueError('Duplicate channel')
    if args.operation=='tx' and len(args.channel)!=1:raise ValueError('TX finite example requires one channel')
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    uri='ip:'+args.host
    with Context(uri) as client:info=client.snapshot()
    board=Board(args.host,args.username,password,args.known_hosts)
    lease=f'/usr/local/lib/h102/sdk1/scripts/h102_iio_{args.operation}_lease.py'
    directory=f'/run/h102-iio-{args.operation}-'+uuid.uuid4().hex
    command=shlex.join(['python3','-B',lease,'manager','--directory',directory,
                       '--catalog','/usr/local/lib/h102-config-sdk1/profiles']+
                      (['--channel',str(args.channel[0])] if args.operation=='tx' else []))
    report=dict(status='RUNNING',backend=args.backend,operation=args.operation,configuration=info,
                channels=args.channel,board_directory=directory,RF_TX=False,continuity_proven=False,files=[])
    started=False;failure=None;count=0;outputs=[]
    with ThreadPoolExecutor(max_workers=1) as pool:
        manager=pool.submit(board.run,command)
        try:
            until=time.monotonic()+15
            while True:
                found=board.run('cat '+shlex.quote(directory+'/ready.json'),timeout=8)
                if found['exit']==0:break
                if manager.done():raise RuntimeError('Manager failed before ready: '+manager.result()['stderr'][-700:])
                if time.monotonic()>=until:raise TimeoutError('Manager ready deadline')
                time.sleep(.1)
            started=True;save(args.output/'ready.json',json.loads(found['stdout']))
            frozen=board.run('cat '+shlex.quote(directory+'/request.json'),timeout=8)
            if frozen['exit']:raise RuntimeError('Missing immutable request')
            request=json.loads(frozen['stdout']);save(args.output/'request.json',request)
            if request['identity']['boot_id']!=info['boot_id'] or request['configuration_id']!=info['configuration_id']:
                raise RuntimeError('Owner identity mismatch')
            def permit():
                nonlocal count
                count+=1
                value=board.run(shlex.join(['python3','-B',lease,'permit','--directory',directory]),timeout=8)
                if value['exit']:return False
                parsed=json.loads(value['stdout'])
                return bool(parsed['permitted'] and parsed['configuration_id']==info['configuration_id'])
            for channel in args.channel:
                path=args.output/f'{args.operation}{channel}.iq.partial'
                if args.operation=='tx':
                    raw=tone()
                    if args.iq:
                        with args.iq.open('rb') as source:raw=source.read(SAMPLES*4+1)
                    if len(raw)!=SAMPLES*4:raise ValueError('TX IQ file must have exactly 65536 complex samples')
                    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                if args.backend=='cpp':
                    report['cpp']=cpp_transfer(args.cpp,uri,args.operation,channel,path,permit)
                else:
                    with Context(uri) as client:
                        raw=client.transfer(args.operation,channel,permit,raw if args.operation=='tx' else None)
                    if args.operation=='rx':
                        with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                if path.stat().st_size!=SAMPLES*4:raise RuntimeError('IQ file length')
                outputs.append(path)
                report['files'].append(dict(file=path.name,bytes=path.stat().st_size,
                                           sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        except BaseException as error:
            failure=error;report.update(status='FAIL',error=str(error))
        finally:
            try:
                if started:
                    stop=board.run(shlex.join(['python3','-B',lease,'stop','--directory',directory]),timeout=8)
                    report['stop_exit']=stop['exit']
                result=manager.result(timeout=80);save(args.output/'manager.json',result)
                post=board.run('cat '+shlex.quote(directory+'/post.json'),timeout=8)
                if post['exit']:raise RuntimeError('Independent post missing')
                recovery=json.loads(post['stdout']);save(args.output/'post.json',recovery)
                if result['exit'] or not recovery.get('passed') or not recovery.get('configuration_unchanged'):
                    raise RuntimeError('Independent recovery failed')
                report['recovery_confirmed']=True
                if failure is None:
                    for path in outputs:path.rename(path.with_suffix(''))
                    for item in report['files']:item['file']=item['file'].removesuffix('.partial')
                    report['status']='PASS_FINITE_IO_AND_RECOVERY'
            except BaseException as error:
                report.update(status='FAIL',recovery_error=str(error))
                if failure is None:failure=error
            report['permit_checks']=count;save(args.output/'result.json',report);board.password=None
    if failure is not None:raise failure
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('rx','tx'))
    parser.add_argument('--host',required=True);parser.add_argument('--username',default='logicrf')
    parser.add_argument('--known-hosts',type=Path,required=True)
    parser.add_argument('--channel',type=int,choices=(1,2),nargs='+',default=[1])
    parser.add_argument('--backend',choices=('python','cpp'),default='python')
    parser.add_argument('--cpp',type=Path);parser.add_argument('--iq',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.backend=='cpp' and (args.cpp is None or not args.cpp.is_file()):parser.error('--cpp executable required')
    if not args.known_hosts.is_file():parser.error('Existing verified known_hosts required')
    password=getpass.getpass('H102 SSH/sudo password: ')
    print(json.dumps(run(args,password),ensure_ascii=False,indent=2))


if __name__=='__main__':main()

# End of file: managed_iq.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
