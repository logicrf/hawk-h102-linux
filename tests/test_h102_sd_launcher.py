"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file test_h102_sd_launcher.py
@brief Run the real POSIX launcher against an explicit non-hardware CLI model.
@details The model never opens a block device. Check static argument quoting and
         ejection-only refusal handling without replacing deployment backend tests.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.0.0
@date 2026-10-28
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

class LauncherTests(unittest.TestCase):
    """Temporary CLI model proves shell protocol only, never physical writing."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='h102-launcher-model-')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/h102_write_sd.sh',self.root/'h102_write_sd.sh')
        (self.root/'h102_sd_deploy.py').write_text('''import json,os,sys
from pathlib import Path
if sys.argv[1]=='inspect':
 print(json.dumps(dict(identity=dict(device='/dev/model-only',bytes=32000000000,model='MODEL',serial='TEST',diskseq=1),blockers=[],confirm='model-token')))
else:
 Path(os.environ['MODEL_ARGS']).write_text(json.dumps(sys.argv[1:]))
 sys.exit(int(os.environ.get('MODEL_EXIT','0')))
''')
        tools=self.root/'bin';tools.mkdir();fakeid=tools/'id';fakeid.write_text('#!/bin/sh\nprintf "0\\n"\n');fakeid.chmod(0o755)
        self.image=self.root/'image with spaces.img.xz';self.image.write_bytes(b'model-only')
        self.env=dict(os.environ,PATH=str(tools)+':'+os.environ['PATH'],MODEL_ARGS=str(self.root/'args.json'))

    def run_model(self,extra=(),exit_code=0):
        """Use actual sh parsing with safely separated arguments and a model-only token."""
        self.env['MODEL_EXIT']=str(exit_code)
        return subprocess.run(['sh',str(self.root/'h102_write_sd.sh'),'--image',str(self.image),'--device','/dev/model-only','--report',str(self.root/'new.json'),*extra],input='model-token\n',text=True,capture_output=True,env=self.env,timeout=10)

    def test_static_forwarding_and_literal_shell_metacharacters(self):
        address='172.31.102.2/24;$(touch NEVER_CREATED)'
        result=self.run_model(['--network','static','--address',address,'--gateway','172.31.102.1','--dns','1.1.1.1,8.8.8.8'])
        self.assertEqual(result.returncode,0,result.stderr)
        args=json.loads((self.root/'args.json').read_text())
        for option,value in [('--image',str(self.image)),('--network','static'),('--address',address),('--gateway','172.31.102.1'),('--dns','1.1.1.1,8.8.8.8')]:
            self.assertEqual(args[args.index(option)+1],value)
        self.assertFalse((Path.cwd()/'NEVER_CREATED').exists())

    def test_default_auto_and_ejection_only_exit(self):
        result=self.run_model(exit_code=3)
        self.assertEqual(result.returncode,3)
        self.assertIn('Do not repeat the image write',result.stderr)
        args=json.loads((self.root/'args.json').read_text())
        self.assertEqual(args[args.index('--network')+1],'auto')
        self.assertEqual(args[args.index('--address')+1],'10.168.1.199/24')

if __name__=='__main__':unittest.main()
# End of file: test_h102_sd_launcher.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
