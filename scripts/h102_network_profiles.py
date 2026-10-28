#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file h102_network_profiles.py
@brief Generate fixed-path DHCP, manual and ordered DHCP-first boot settings.
@details Accepts a validated SD plan. Auto mode establishes a unique installation
         MAC, then uses one startup selector for bounded DHCP and static fallback.
         No credentials or background daemon are required; explicit DHCP/static
         modes preserve their earlier one-profile behavior.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-28
"""
PROFILE = '/etc/NetworkManager/system-connections/NetworkManager-USRP'
"""Only this existing NM profile may be changed; never accept caller-supplied paths."""
BASE_PROFILE = b'''[connection]
id=USRP
uuid=f6a7696d-4958-48f4-b1eb-c2ab9de0a838
type=802-3-ethernet
autoconnect=true

[802-3-ethernet]
auto-negotiate=true
cloned-mac-address=stable

[ipv4]
method=auto

[ipv6]
method=auto
'''

FALLBACK_PROFILE = '/etc/NetworkManager/system-connections/NetworkManager-H102-Fallback'
MAC_HELPER = '/etc/NetworkManager/h102-stable-mac.py'
MAC_DROPIN = '/etc/systemd/system/NetworkManager.service.d/20-h102-stable-mac.conf'
CARRIER_CONFIG = '/etc/NetworkManager/conf.d/90-h102-fallback-carrier.conf'
CARRIER_CONFIG_BYTES = b'''[device-h102-eth0]
match-device=interface-name:eth0
ignore-carrier=true
'''
MAC_DROPIN_BYTES = b'''[Service]
ExecStartPre=/usr/bin/python3 /etc/NetworkManager/h102-stable-mac.py
ExecStartPost=/usr/bin/python3 /etc/NetworkManager/h102-stable-mac.py --select
TimeoutStartSec=100
'''
MAC_HELPER_BYTES = b'''"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file h102-stable-mac.py
@brief Set eth0 MAC and select DHCP-first or static fallback during NM startup.
@details U-Boot supplies a random MAC; use a unique per-installation address.
         Explicit ordered selection prevents static activation before DHCP while
         tolerating NM link cycling. Identity/link/selection failure aborts startup.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.0.0
@date 2026-10-28
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    """Set MAC before NM; after its bus is ready, select DHCP once then fallback.

    Both profiles disable autoconnect. Explicit selection prevents static activation
    before initial PHY readiness, while carrier tolerance survives NM's own link
    down/up during fallback. No polling process remains after startup selection.
    """
    if sys.argv[1:]==['--select']:
        deadline=time.monotonic()+30
        while Path('/sys/class/net/eth0/carrier').read_text().strip()!='1':
            if time.monotonic()>=deadline:break
            time.sleep(.2)
        if Path('/sys/class/net/eth0/carrier').read_text().strip()=='1':
            result=subprocess.run(['/usr/bin/nmcli','-w','25','con','up','uuid','f6a7696d-4958-48f4-b1eb-c2ab9de0a838'],timeout=28)
            if result.returncode==0:
                print('H102_NETWORK_BOOT=DHCP',flush=True)
                return
        subprocess.run(['/usr/bin/nmcli','-w','20','con','up','uuid','64701a9a-2a28-5f24-a4c1-26236959da16'],check=True,timeout=23)
        print('H102_NETWORK_BOOT=STATIC_FALLBACK',flush=True)
        return
    if sys.argv[1:]:raise ValueError('H102_NETWORK_BOOT_ARGUMENTS')
    identity=Path('/etc/machine-id').read_text().strip()
    if not re.fullmatch('[0-9a-f]{32}',identity) or int(identity,16)==0:
        raise ValueError('H102_VALID_MACHINE_ID_REQUIRED')
    value=bytearray(hashlib.sha256(b'LogicRF H102 eth0 v1:'+identity.encode()).digest()[:6])
    value[0]=(value[0]|2)&254
    address=':'.join(format(v,'02x') for v in value)
    current=Path('/sys/class/net/eth0/address').read_text().strip()
    if current!=address:
        subprocess.run(['/usr/sbin/ip','link','set','dev','eth0','down'],check=True)
        subprocess.run(['/usr/sbin/ip','link','set','dev','eth0','address',address],check=True)
    subprocess.run(['/usr/sbin/ip','link','set','dev','eth0','up'],check=True)
    if Path('/sys/class/net/eth0/address').read_text().strip()!=address:
        raise RuntimeError('H102_STABLE_MAC_READBACK_MISMATCH')


if __name__=='__main__':main()
# End of file: h102-stable-mac.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
'''
DEFAULT_ADDRESS = '10.168.1.199/24'
DHCP_TIMEOUT = 15
SHARED_STABLE_ID = 'logicrf-h102-eth0'
FALLBACK_UUID = '64701a9a-2a28-5f24-a4c1-26236959da16'


def static_profile(plan):
    """Use only validated literal addresses; retain the original manual-mode UUID."""
    values = ['method=manual', 'address1='+plan['address']+
              (','+plan['gateway'] if plan['gateway'] else ''),
              'never-default='+('false' if plan['gateway'] else 'true'),
              'may-fail=false', 'dad-timeout=3000']
    if plan['dns']:
        values.append('dns='+';'.join(plan['dns'])+';')
    return BASE_PROFILE.replace(b'[ipv4]\nmethod=auto', ('[ipv4]\n'+'\n'.join(values)).encode()).replace(
        b'[ipv6]\nmethod=auto', b'[ipv6]\nmethod=disabled')


def profile_set(plan):
    """Return fixed files for deterministic boot selection and stable local MAC."""
    mode=plan['mode']
    if mode=='dhcp':
        return {PROFILE:BASE_PROFILE}
    if mode=='static':
        return {PROFILE:static_profile(plan)}
    if mode!='auto':
        raise ValueError('NETWORK_MODE_REQUIRED')
    shared=('\ninterface-name=eth0\nstable-id='+SHARED_STABLE_ID).encode()
    primary=BASE_PROFILE.replace(b'autoconnect=true',b'autoconnect=true\nautoconnect-priority=100\nautoconnect-retries=1'+shared)
    primary=primary.replace(b'[ipv4]\nmethod=auto',('[ipv4]\nmethod=auto\ndhcp-timeout='+str(DHCP_TIMEOUT)+'\nmay-fail=false\ndad-timeout=3000').encode())
    primary=primary.replace(b'[ipv6]\nmethod=auto',b'[ipv6]\nmethod=disabled')
    fallback=static_profile(plan).replace(b'id=USRP\n',b'id=USRP-fallback\n').replace(
        b'uuid=f6a7696d-4958-48f4-b1eb-c2ab9de0a838',('uuid='+FALLBACK_UUID).encode())
    fallback=fallback.replace(b'autoconnect=true',b'autoconnect=true\nautoconnect-priority=-100\nautoconnect-retries=1'+shared)
    primary=primary.replace(b'cloned-mac-address=stable',b'cloned-mac-address=preserve')
    fallback=fallback.replace(b'cloned-mac-address=stable',b'cloned-mac-address=preserve')
    primary=primary.replace(b'autoconnect=true',b'autoconnect=false')
    fallback=fallback.replace(b'autoconnect=true',b'autoconnect=false')
    return {PROFILE:primary,FALLBACK_PROFILE:fallback,MAC_HELPER:MAC_HELPER_BYTES,
            MAC_DROPIN:MAC_DROPIN_BYTES,CARRIER_CONFIG:CARRIER_CONFIG_BYTES}

# End of file: h102_network_profiles.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
