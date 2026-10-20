#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       managed_session.py
@brief      Reuse fixed native tuning, recording, sweep and cyclic TX without a Qt window.
@details    Share the GUI owner and recovery backend rather than copying algorithms.
            Verify source identity first; keep credentials in memory and require explicit TX commands.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-16
"""
import argparse
import getpass
import json
from pathlib import Path
import signal
import hashlib
import sys

PIN = 'f782657cc911834d31bf136da5b19260e25aeea8'


def load_backend(root):
    """Require reviewed local sources, without downloads, a GUI or modified production code."""
    root=root.resolve()
    lock=json.loads((Path(__file__).resolve().parents[1]/'runtime.lock.json').read_text())
    if lock['gui_commit']!=PIN:raise RuntimeError('Runtime lock version mismatch')
    for name,digest in lock['runtime_files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Pinned runtime source mismatch: '+name)
    sys.path.insert(0,str(root))
    from h102_iio_demo import backend
    from h102_iio_demo.tx_backend import TxSession
    from h102_iio_demo.tx_model import TxPlan
    from h102_iio_demo.sweep import SweepSession,SweepPlan
    return backend,TxSession,TxPlan,SweepSession,SweepPlan


def main():
    """Share transactions across Python/C++ callers; stop signals use the original recovery path."""
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('info','tune','receive','record','tx','sweep'))
    p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--host',required=True);p.add_argument('--username',default='logicrf')
    p.add_argument('--known-hosts',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--channels',type=int,choices=(1,2),nargs='+',default=[1])
    p.add_argument('--rx-channels',type=int,choices=(1,2),nargs='*',default=[])
    p.add_argument('--frequency-hz',type=int)
    p.add_argument('--seconds',type=int,default=10)
    p.add_argument('--attenuation-db',type=float,default=40)
    p.add_argument('--offset-hz',type=float,default=250000)
    p.add_argument('--iq',type=Path)
    p.add_argument('--start-hz',type=int,default=50_000_000);p.add_argument('--stop-hz',type=int,default=5_800_000_000)
    args=p.parse_args()
    if not args.known_hosts.is_file():p.error('Existing verified known_hosts required')
    if not 1<=args.seconds<=300:p.error('seconds must be 1..300')
    if len(set(args.channels))!=len(args.channels) or args.channels!=sorted(args.channels):p.error('channels must be 1, 2, or 1 2')
    if tuple(args.rx_channels) not in ((),(1,),(2,),(1,2)):p.error('rx-channels must be empty, 1, 2, or 1 2')
    if args.action in ('tx','tune') and args.frequency_hz is None:p.error('--frequency-hz required')
    backend,TxSession,TxPlan,SweepSession,SweepPlan=load_backend(args.runtime)
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    connection=backend.Connection(args.host,args.username,getpass.getpass('H102 SSH/sudo password: '),args.known_hosts)
    state=backend.inspect(connection)
    (args.output/'identity.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    if args.action=='info':return 0
    if args.action=='tune':
        channels=next(g['channels'] for g in state['info']['radio']['groups'] if args.channels[0] in g['channels'])
        backend.tune_rx_idle(connection,state,channels,args.frequency_hz,args.output/'tune')
        return 0
    if args.action=='tx':
        plan=TxPlan(tuple(args.channels),args.frequency_hz,args.attenuation_db,args.seconds,args.offset_hz,4096,args.iq)
        session=TxSession(connection,state['info'],tuple(args.rx_channels),plan,args.output/'session')
    elif args.action=='sweep':
        if len(args.channels)!=1:p.error('sweep requires one channel')
        params=next(v for v in state['info']['parameters']['rx'] if v['channel']==args.channels[0])
        plan=SweepPlan(args.start_hz,args.stop_hz,params['sample_rate_hz'],params['rf_bandwidth_hz'],2048,1,2,False)
        session=SweepSession(connection,state['info'],args.channels[0],plan,args.output/'session')
    else:
        session=backend.RxSession(connection,state['info'],tuple(args.channels),'continuous','normal',
                                  args.seconds,args.output/'session',recording=args.action=='record')
    old={sig:signal.signal(sig,lambda *_:session.stop()) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:result=session.run()
    finally:
        for sig,handler in old.items():signal.signal(sig,handler)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status'].startswith('PASS_') and result.get('recovery_confirmed') else 1


if __name__=='__main__':raise SystemExit(main())

# End of file: managed_session.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
