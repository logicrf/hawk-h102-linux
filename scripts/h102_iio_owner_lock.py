"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_iio_owner_lock.py
@brief      Share the first lock domain and bounded acquisition across IIO queries and owners.
@details    Acquire configuration before RX/GNSS locks to avoid partial lock-group contention.
            Data owners wait at most three seconds for short queries, without renewal or inode replacement.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-08
"""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import time

LOCK = Path('/run/lock/h102-profile-config.lock')
"""Existing first lock; continue in RX then GNSS order without replacing its inode."""


@contextmanager
def configuration_lock(timeout: float = 0, path: Path = LOCK):
    """Keep the same FD until exit, with nonblocking or at most three-second preflight waiting.

    Raise BlockingIOError on timeout; do not write devices before holding the entire lock group.
    The path argument supports regular-file tests; production uses the fixed default path.
    """
    if type(timeout) not in (int,float) or not 0<=timeout<=3:
        raise ValueError('CONFIGURATION_LOCK_WAIT_LIMIT')
    end=time.monotonic()+timeout
    with open(path,'a+b') as descriptor:
        while True:
            try:
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=end:raise
                time.sleep(min(.02,max(0,end-time.monotonic())))
        yield descriptor

# End of file: h102_iio_owner_lock.py
