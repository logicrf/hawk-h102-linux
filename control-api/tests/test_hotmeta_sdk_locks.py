"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_hotmeta_sdk_locks.py
@brief Check unique three-lock ownership using the original SDK factory and real flock.
@details Model hardware readback only; let the operating system acquire and release locks.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
from contextlib import contextmanager,ExitStack
import fcntl
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from install_hotmeta_addon import sdk_idle_context


class SdkLockTests(unittest.TestCase):
    """Execute the real SDK two-lock factory rather than a copied implementation."""
    def test_real_sdk_factory_has_one_config_rx_gnss_owner(self):
        project=Path(os.environ.get('LOGICRF_PROJECT_ROOT','/data/logicrf/hawk-h102'))
        sdk=project/'envs/h102-sdk-runtime-input/1.2.0-grc-hotmeta-1'
        if not sdk.is_dir():self.skipTest('external pinned SDK fixture not installed')
        sys.path.insert(0,str(sdk));self.addCleanup(lambda:sys.path.remove(str(sdk)))
        spec=importlib.util.spec_from_file_location('h102_addon_sdk_lock_fixture',sdk/'h102_profile_config.py')
        config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);paths={name:root/name for name in ('h102-profile-config.lock','h102-rx-session.lock','h102-gnss-g0.lock')}
            original_open=open
            def model_open(path,*args,**kwargs):
                return original_open(paths[Path(path).name] if str(path).startswith('/run/lock/') else path,*args,**kwargs)
            @contextmanager
            def configuration_lock(timeout):
                with original_open(paths['h102-profile-config.lock'],'a+b') as file:
                    fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB);yield file
            hw=SimpleNamespace(phy=Path('model-phy'),idle=Mock())
            with patch('builtins.open',side_effect=model_open),patch.object(config,'identity',return_value={}),patch.object(config.rf,'Hardware',return_value=hw),patch.object(Path,'read_text',return_value=config.API):
                with sdk_idle_context(config,configuration_lock,root) as actual:
                    self.assertIs(actual,hw)
                    for name,path in paths.items():
                        with original_open(path,'a+b') as duplicate,self.assertRaises(BlockingIOError):
                            fcntl.flock(duplicate,fcntl.LOCK_EX|fcntl.LOCK_NB)
                hw.idle.assert_called_once()
                for path in paths.values():
                    with original_open(path,'a+b') as released:fcntl.flock(released,fcntl.LOCK_EX|fcntl.LOCK_NB)
                # Regression: the outer layer previously acquired locks before calling the same SDK factory.
                with configuration_lock(timeout=3),ExitStack() as scope:
                    for name in ('h102-rx-session.lock','h102-gnss-g0.lock'):
                        file=scope.enter_context(original_open(paths[name],'a+b'));fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaises(BlockingIOError):config.hardware_context(scope,root,{})


if __name__=='__main__':unittest.main()
# End of file: test_hotmeta_sdk_locks.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
