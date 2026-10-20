"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file __main__.py
@brief Start the pinned H102 control service and close owned worker input on SIGTERM.
@details Do not reconnect or renew leases; existing PID1 recovery handles terminated sessions.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-17
"""
import argparse
from pathlib import Path
import signal
from threading import Thread

from . import DEFAULT_PORT
from .native import NativeDevice
from .server import ApiServer


def main():
    """Serve one fixed-port instance; send EOF to owned sessions when stopping."""
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--listen',default='0.0.0.0');parser.add_argument('--port',type=int,default=DEFAULT_PORT)
    args=parser.parse_args();device=NativeDevice(args.root)
    with ApiServer((args.listen,args.port),device) as server:
        def stop(signum, frame):Thread(target=server.shutdown,daemon=True).start()
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:server.serve_forever()
        finally:
            with device.lock:sessions=list(device.sessions.values())
            workers=[Thread(target=session.close) for session in sessions]
            for worker in workers:worker.start()
            for worker in workers:worker.join(140)

if __name__=='__main__':main()
# End of file: __main__.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
