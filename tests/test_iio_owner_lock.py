"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_iio_owner_lock.py
@brief      Test first-lock contention and release using real regular-file flock.
@details    No board access; test short-query waiting, busy rejection and exception cleanup.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-08
"""
import fcntl
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from h102_iio_owner_lock import configuration_lock
import h102_profile_iio_broker as broker


class Cases(unittest.TestCase):
    """Use real lock semantics rather than always-true mock authorization."""
    def test_query_blocked_before_rx_gnss_status(self):
        """Queries must not enter RX/GNSS while a data owner holds the first lock."""
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock'
            with configuration_lock(path=path), \
                 patch.object(broker,'configuration_lock',side_effect=lambda:configuration_lock(path=path)), \
                 patch.object(broker.config,'status') as query:
                with self.assertRaises(BlockingIOError):broker.verified_snapshot(Path('/model'),{})
                query.assert_not_called()

    def test_owner_waits_for_short_query_then_holds_same_fd(self):
        """Acquire after a short query exits and verify actual release after the protected operation."""
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock'
            with open(path,'a+b') as foreign,open(path,'a+b') as probe:
                fcntl.flock(foreign,fcntl.LOCK_EX|fcntl.LOCK_NB)
                timer=threading.Timer(.05,lambda:fcntl.flock(foreign,fcntl.LOCK_UN));timer.start()
                try:
                    with configuration_lock(timeout=.5,path=path) as own:
                        with self.assertRaises(BlockingIOError):fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:timer.join()

    def test_query_exception_releases_first_lock(self):
        """Failed queries cannot leak the first lock or prevent the next data owner acquiring it."""
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock'
            with patch.object(broker,'configuration_lock',side_effect=lambda:configuration_lock(path=path)), \
                 patch.object(broker.config,'status',side_effect=ValueError('MODEL_QUERY_FAILURE')):
                with self.assertRaises(ValueError):broker.verified_snapshot(Path('/model'),{})
            with configuration_lock(path=path):pass


if __name__=='__main__':unittest.main()
# End of file: test_iio_owner_lock.py
