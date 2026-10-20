"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file usb_worker.py
@brief Start one typed USB session from an installation-pinned native dependency set.
@details Read only a root-private request and verify SDK/generator hashes. Network input
         contains no Python code; the existing bridge and independent PID1 recovery own the lease.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-17
"""
import argparse
import json
import math
from pathlib import Path
import sys

from .protocol import ProtocolError

USB_SOURCES=('usb_runtime_candidate.py','gr_usb_radio.py','board_tx.py','board_radio.py','tx_cyclic.py')
USB_REUSE_SOURCES=USB_SOURCES+('usb_rx_reuse_candidate.py','gr_usb_reuse.py')


def validate_request(args, manifest):
    """Restrict fields, modes, units and source identity; reject paths, code and commands."""
    fields={'profile','boot_id','rx_mask','tx_mask','seconds','transmit','arbitrary','radio_plan','sources'}
    if not isinstance(args,dict) or set(args) not in (fields,fields|{'reusable'}):raise ProtocolError('CONTROL_API_USB_FIELDS')
    if 'reusable' in args and (args['reusable'] is not True or args['tx_mask']!=0 or
            args['seconds']!=0 or args['arbitrary'] is not True or not args['radio_plan']):
        raise ProtocolError('CONTROL_API_USB_REUSE_RX_ONLY')
    if args['profile'] not in [p['id'] for p in manifest['profiles']]:raise ProtocolError('CONTROL_API_PROFILE_UNAPPROVED')
    rx,tx=args['rx_mask'],args['tx_mask']
    if (type(rx) is not int or type(tx) is not int or (rx,tx) not in
            ((1,0),(2,0),(3,0),(0,1),(0,2),(0,3),(1,1),(1,2),(2,1),(2,2))):
        raise ProtocolError('CONTROL_API_USB_MASKS')
    if type(args['seconds']) is not int or args['seconds'] not in (0,10,300):raise ProtocolError('CONTROL_API_USB_DURATION')
    if type(args['transmit']) is not bool or type(args['arbitrary']) is not bool:raise ProtocolError('CONTROL_API_USB_BOOLEAN')
    if args['transmit'] != bool(tx):raise ProtocolError('CONTROL_API_USB_DIRECTION')
    if not args['arbitrary'] and args['seconds']==0:raise ProtocolError('CONTROL_API_USB_UNBOUNDED_NATIVE_MODE')
    plan=args['radio_plan']
    if plan is not None:
        expected={'configuration','rf_enabled','rx_channels','tx_channels','rx_frequency','tx_frequency','attenuation_db','rx_gain_db'}
        if not isinstance(plan,dict) or set(plan)!=expected or plan['configuration']!=args['profile']:
            raise ProtocolError('CONTROL_API_USB_RADIO_FIELDS')
        if plan['rx_channels']!=[c for c in (1,2) if rx&(1<<(c-1))] or plan['tx_channels']!=[c for c in (1,2) if tx&(1<<(c-1))]:
            raise ProtocolError('CONTROL_API_USB_RADIO_CHANNELS')
        if type(plan['rf_enabled']) is not bool or plan['rf_enabled'] and not tx:raise ProtocolError('CONTROL_API_USB_RF_BOOLEAN')
        for key in ('rx_frequency','tx_frequency'):
            if type(plan[key]) is not int or not 50_000_000<=plan[key]<=5_800_000_000:raise ProtocolError('CONTROL_API_USB_RF_FREQUENCY')
        value=plan['attenuation_db']
        if type(value) not in (float,int) or not math.isfinite(value) or not 20<=value<=40 or abs(value*20-round(value*20))>1e-6:
            raise ProtocolError('CONTROL_API_USB_ATTENUATION')
        if not isinstance(plan['rx_gain_db'],dict) or any(ch not in ('1','2') or type(v) not in (int,float) or not math.isfinite(v) or not -3<=v<=30 for ch,v in plan['rx_gain_db'].items()):
            raise ProtocolError('CONTROL_API_USB_RX_GAIN')
        if not args['arbitrary']:raise ProtocolError('CONTROL_API_USB_RADIO_REQUIRES_FIXED_BUILDER')


def main():
    """Run the installed generator and bridge without renewing client leases."""
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();root=args.root;directory=args.directory
    request=json.loads((directory/'usb-request.json').read_text())
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=request['boot_id']:raise RuntimeError('CONTROL_API_BOOT_CHANGED')
    bundle=root/'bundle'
    if request['arbitrary']:
        sys.path.insert(0,str(bundle))
        import usb_runtime_candidate as candidate
        manifest=json.loads((root/'manifest.json').read_text())
        plan=request['radio_plan']
        extras={name:(bundle/name).read_text() for name in ('gr_usb_radio.py','board_tx.py','board_radio.py','tx_cyclic.py')} if plan is not None else None
        if request.get('reusable'):
            import usb_rx_reuse_candidate as reusable
            reusable.build(Path(request['code_root']),dict(files=manifest['sdk_sources']),radio_plan=plan,
                extra_sources=extras,reuse_source=(bundle/'gr_usb_reuse.py').read_text())
        else:candidate.build(Path(request['code_root']),dict(files=manifest['sdk_sources']),radio_plan=plan,extra_sources=extras)
        sys.path.insert(0,request['code_root'])
    else:sys.path.insert(0,'/usr/local/lib/h102/sdk1/scripts')
    import h102_runtime_usb_rx as native
    target=Path(request['board_directory'])
    native.launch(target,request['profile'],request['rx_mask'],request['seconds'],'data',request['tx_mask'])
    def emit(value,**kwargs):
        value=json.loads(value)
        if value.get('ready') is True:
            for prefix in ('rx','tx'):value[prefix+'_configuration_hex']=(target/('planned-'+prefix+'.bin')).read_bytes().hex()
            value['configuration_hex']=value[('tx' if request['transmit'] else 'rx')+'_configuration_hex']
        print(json.dumps(value),flush=True)
    native.print=emit
    native.bridge(target)

if __name__=='__main__':main()
# End of file: usb_worker.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
