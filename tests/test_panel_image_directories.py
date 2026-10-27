"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_panel_image_directories.py
@brief Verify private API permissions and complete-tree exclusions using real directories and rsync.
@details Use root-owned temporary directories without mounting images or accessing devices.
         Cover 0755 rejection, explicit 0700 acceptance and rejection of unrelated changes.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-27
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_h102_panel_image import verify_api_directories
from build_h102_sdk1_image import compare
from prepare_h102_panel_image import API_DIRECTORY_MODES, API_TARGET


class RealTree:
    """Run real rsync and preserve failed exit codes without simulating differences."""
    def __init__(self, evidence):
        self.evidence = evidence

    def run(self, argv, privileged=False):
        """Execute ordinary-directory comparison in the root-owned test model."""
        return subprocess.check_output(argv, text=True)


@unittest.skipUnless(os.geteuid() == 0, 'root owner model required')
class DirectoryContract(unittest.TestCase):
    """Use isolated real directories for each permission case."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'root'
        self.root.mkdir()
        self.boot = base / 'boot'
        self.boot.mkdir()
        self.source = base / 'source'
        self.source.mkdir()
        self.evidence = base / 'evidence'
        self.evidence.mkdir()
        self.builder = RealTree(self.evidence)
        for name in API_DIRECTORY_MODES:
            path = self.root / name.lstrip('/')
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o755)

    def secure(self):
        """Restrict only the explicitly approved API directories."""
        for name, mode in API_DIRECTORY_MODES.items():
            (self.root / name.lstrip('/')).chmod(mode)

    def compare(self, private=True):
        """Compare approved leaves with private overrides limited to API directories."""
        leaves = []
        for suffix in ('manifest.json', 'bundle/actor.py', 'h102_control/native.py'):
            name = API_TARGET.lstrip('/') + '/' + suffix
            (self.root / name).write_text('unchanged payload')
            leaves.append(name)
        modes = {name.lstrip('/'): mode for name, mode in API_DIRECTORY_MODES.items()}
        compare(self.builder, self.source, self.root, leaves, 'root',
                directory_modes=modes if private else None)

    def test_api_0755_rejected(self):
        """Reproduce the first-boot failure: correct files do not establish correct directory permissions."""
        with self.assertRaisesRegex(ValueError, 'DIRECTORY_OWNER_MODE'):
            verify_api_directories(self.root, self.boot, API_DIRECTORY_MODES)

    def test_private_tree_and_explicit_compare_pass(self):
        """Verify real 0700 directories and the complete tree outside approved files."""
        self.secure()
        verify_api_directories(self.root, self.boot, API_DIRECTORY_MODES)
        self.compare()

    def test_legacy_compare_still_rejects_unapproved_0700(self):
        """Preserve the legacy 0755 default without globally relaxing directory checks."""
        self.secure()
        with self.assertRaisesRegex(RuntimeError, 'NEW_ASSET_PARENT_OWNER_MODE'):
            self.compare(private=False)

    def test_unrelated_file_still_rejected(self):
        """Private-directory approval must not admit unrelated payloads."""
        self.secure()
        (self.root / 'unapproved.txt').write_text('unexpected')
        with self.assertRaisesRegex(RuntimeError, 'UNEXPECTED_ROOT_DIFFERENCES'):
            self.compare()

    def test_non_api_parent_mode_still_rejected(self):
        """New parents outside the API scope must still use 0755."""
        self.secure()
        (self.root / 'usr').chmod(0o700)
        with self.assertRaisesRegex(RuntimeError, 'NEW_ASSET_PARENT_OWNER_MODE'):
            self.compare()


if __name__ == '__main__':
    unittest.main()

# End of file: test_panel_image_directories.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
