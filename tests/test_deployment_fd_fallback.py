"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_deployment_fd_fallback.py
@brief      Check owner-scoped FD classification and fail-closed permission handling.
@details    Mock only denied process descriptors and the isolated read-only probe;
            no SD, mount, device write or permission change is performed.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-21
"""
import errno
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import h102_sd_deploy as sd


class ProcessFdTests(unittest.TestCase):
    """Prove readable classifications survive the fallback; uncertainty still refuses."""

    def probe(self, value, links=('same', 'same'), uid=1000):
        """Return a denied-FD fixture and patches for one privilege-dropping probe."""
        fd = mock.Mock()
        fd.stat.side_effect = PermissionError(errno.EACCES, 'FUSE root denial')
        fd.parent.parent.stat.return_value = SimpleNamespace(st_uid=uid, st_gid=1000)
        patches = (mock.patch.object(sd.os, 'geteuid', return_value=0),
                   mock.patch.object(sd.os, 'readlink', side_effect=links),
                   mock.patch.object(sd.subprocess, 'run', return_value=
                                     subprocess.CompletedProcess([], 0, json.dumps(value), '')))
        return fd, patches

    def test_owner_classification_preserves_block_device(self):
        """A real target block FD must remain identifiable, never skipped on EACCES."""
        mode, rdev = stat.S_IFBLK | 0o600, sd.os.makedev(8, 32)
        fd, patches = self.probe([mode, rdev])
        with patches[0], patches[1], patches[2] as run:
            self.assertEqual(sd.process_fd_kind(fd), (mode, rdev))
            self.assertEqual(run.call_args.kwargs['user'], 1000)
            self.assertEqual(run.call_args.kwargs['extra_groups'], [])
            self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_owner_denial_refuses(self):
        """If the owner cannot inspect the FD either, no classification is invented."""
        fd, patches = self.probe({'errno': errno.EACCES})
        with patches[0], patches[1], patches[2], self.assertRaises(PermissionError):
            sd.process_fd_kind(fd)

    def test_changed_descriptor_refuses(self):
        """A descriptor changed during the probe must be rechecked in a new run."""
        fd, patches = self.probe([stat.S_IFDIR | 0o700, 0], links=('before', 'after'))
        with patches[0], patches[1], patches[2], self.assertRaisesRegex(OSError, 'CHANGED'):
            sd.process_fd_kind(fd)

    def test_root_owner_denial_has_no_equal_privilege_retry(self):
        """A root-owned inaccessible FD remains an error rather than a skipped FD."""
        fd, patches = self.probe([stat.S_IFDIR, 0], uid=0)
        with patches[0], patches[1], patches[2] as run, self.assertRaises(PermissionError):
            sd.process_fd_kind(fd)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

# End of file: test_deployment_fd_fallback.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
