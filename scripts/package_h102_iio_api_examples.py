#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       package_h102_iio_api_examples.py
@brief      Package IIO API documentation, C++/Python examples and a pinned non-Qt backend.
@details    Pin runtime.lock Git objects and file hashes; exclude images, SDK binaries,
            credentials and logs. Require new output; extraction/startup verification runs separately.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-16
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import re
import posixpath
import zipfile


def main():
    """Read local Git objects into a new ZIP and hash list without device or repository changes."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-repository',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    lock=json.loads((root/'examples/iio/runtime.lock.json').read_text())
    members={}
    for p in (root/'examples/iio').rglob('*'):
        if p.is_file() and p.suffix in ('.py','.cpp','.txt','.json','.md') and '__pycache__' not in p.parts:
            members[str(p.relative_to(root))]=p.read_bytes()
    docs=['docs/h102-iio-api-1.2.0.md','docs/h102-iio-api-validation-20261016.md',
          'docs/api/h102-iio-1.2.0-reference.md','docs/api/h102-iio-1.2.0.json',
          'docs/api/images/h102-iio-architecture.svg','docs/api/images/h102-iio-lifecycle.svg']
    for name in docs:members[name]=(root/name).read_bytes()
    for name,digest in lock['linux_helpers'].items():
        raw=(root/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('Support source drift: '+name)
        members[name]=raw
    for name,digest in lock['runtime_files'].items():
        raw=subprocess.check_output(['git','-C',str(args.runtime_repository),'show',lock['gui_commit']+':'+name])
        if hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('Runtime source mismatch: '+name)
        members['examples/iio/runtime/'+name]=raw
    # Preserve bundled relative links; external references use the original source branch.
    for name,raw in list(members.items()):
        if not name.endswith('.md'):continue
        def fix_link(match):
            target=match.group(2)
            if target.startswith(('#','/')) or ':' in target:return match.group(0)
            dest=posixpath.normpath(posixpath.join(posixpath.dirname(name),target.split('#')[0]))
            if dest in members:return match.group(0)
            if dest=='releases/H102-IIO-API-Examples-1.2.0-r1.zip':
                return '['+match.group(1)+'](http://10.168.1.2:9443/files/H102-IIO-API-Examples-1.2.0-r1.zip)'
            return '['+match.group(1)+'](http://10.168.1.2:3000/logicrf/hawk-h102-linux/src/commit/f2f19a341cb677452416439400e249811d8d67a1/'+dest+')'
        members[name]=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',fix_link,raw.decode()).encode()
    members['README.md']='H102 IIO API and examples\n\nStart with examples/iio/README.md and run commands from this package root.\nUse the listed Python requirements and system libiio; images, compilers and SDK binaries are not included.\n'.encode()
    sums={name:hashlib.sha256(raw).hexdigest() for name,raw in members.items()}
    members['SHA256SUMS']=''.join(h+'  '+name+'\n' for name,h in sorted(sums.items())).encode()
    prefix='H102-IIO-API-Examples-1.2.0-r1/'
    with zipfile.ZipFile(args.output,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,raw in sorted(members.items()):
            item=zipfile.ZipInfo(prefix+name,(2026,10,16,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
            item.external_attr=0o100644<<16;z.writestr(item,raw)
    with zipfile.ZipFile(args.output) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP CRC failed')
        for name,raw in members.items():
            if z.read(prefix+name)!=raw:raise RuntimeError('ZIP member mismatch: '+name)
    result=dict(file=args.output.name,bytes=args.output.stat().st_size,
                sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),members=len(members),
                runtime_commit=lock['gui_commit'],runtime_files=len(lock['runtime_files']))
    args.output.with_suffix('.zip.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()

# End of file: package_h102_iio_api_examples.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
