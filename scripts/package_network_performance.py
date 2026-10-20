#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       package_network_performance.py
@brief      Package standalone network-performance tools and exact payloads from a clean commit.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-19
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile


def main():
    """Write a new package and checksum without device access; reject dirty source identity."""
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*arguments):
        return subprocess.check_output(['git','-C',str(root),*arguments],text=True).strip()
    if git('status','--porcelain'):
        raise ValueError('CLEAN_SOURCE_REQUIRED')
    paths = ('scripts/h102_network_performance.py',
             'overlays/h102/etc/systemd/system/h102-network-performance.service',
             'overlays/h102/etc/systemd/system/iiod.service.d/50-h102-network-performance.conf',
             'overlays/h102/etc/systemd/system/iiod_ffs.service.d/51-h102-network-performance-ffs.conf',
             'overlays/h102/etc/systemd/system/h102-grc-ready-profile.service')
    manifest = dict(version='1.0.0', source_commit=git('rev-parse','HEAD'),
        files={Path(p).name:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})
    with tempfile.TemporaryDirectory(prefix='h102-network-package-') as temporary:
        directory = Path(temporary)/'h102-network-performance-1.0.0'
        directory.mkdir()
        for relative in (*paths, 'scripts/install_network_performance.py'):
            (directory/Path(relative).name).write_bytes((root/relative).read_bytes())
        (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        with args.output.open('xb') as stream:
            with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                archive.add(directory,arcname=directory.name)
    sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix+'.sha256').write_text(sha+'  '+args.output.name+'\n')
    print(json.dumps(dict(package=str(args.output),sha256=sha,manifest=manifest),indent=2))


if __name__=='__main__':
    main()
# End of file: package_network_performance.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
