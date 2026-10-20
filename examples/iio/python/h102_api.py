#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_api.py
@brief      Demonstrate libiio 0.x queries, asynchronous configuration and finite IQ I/O.
@details    Bind the public C ABI with ctypes. Connecting does not start streaming; buffer
            operations require a real session permit. Destroy all resources on exit without enabling RF.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-16
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.util
import json
import re
import time

SAMPLES = 65536
"""Finite complex samples per channel; 262144 bytes in IQ16 format."""


class Format(C.Structure):
    """Public libiio 0.x data format with native alignment; do not set _pack_."""
    _fields_ = [('length', C.c_uint), ('bits', C.c_uint), ('shift', C.c_uint),
                ('is_signed', C.c_bool), ('is_fully_defined', C.c_bool),
                ('is_be', C.c_bool), ('with_scale', C.c_bool), ('scale', C.c_double),
                ('repeat', C.c_uint)]


class Context:
    """Own a single-threaded context; close on with exit and reject libiio 1.x ABI."""
    def __init__(self, uri):
        self.ctx = None
        self.lib = C.CDLL(ctypes.util.find_library('iio') or 'libiio.so.0', use_errno=True)
        signatures = {
            'iio_library_get_version': (None, [C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.c_char_p]),
            'iio_create_context_from_uri': (C.c_void_p, [C.c_char_p]),
            'iio_context_destroy': (None, [C.c_void_p]),
            'iio_context_set_timeout': (C.c_int, [C.c_void_p, C.c_uint]),
            'iio_context_get_xml': (C.c_char_p, [C.c_void_p]),
            'iio_context_find_device': (C.c_void_p, [C.c_void_p, C.c_char_p]),
            'iio_device_find_channel': (C.c_void_p, [C.c_void_p, C.c_char_p, C.c_bool]),
            'iio_device_attr_read': (C.c_ssize_t, [C.c_void_p, C.c_char_p, C.c_void_p, C.c_size_t]),
            'iio_device_attr_write': (C.c_ssize_t, [C.c_void_p, C.c_char_p, C.c_char_p]),
            'iio_channel_attr_read': (C.c_ssize_t, [C.c_void_p, C.c_char_p, C.c_void_p, C.c_size_t]),
            'iio_device_get_channels_count': (C.c_uint, [C.c_void_p]),
            'iio_device_get_channel': (C.c_void_p, [C.c_void_p, C.c_uint]),
            'iio_channel_disable': (None, [C.c_void_p]),
            'iio_channel_enable': (None, [C.c_void_p]),
            'iio_channel_get_index': (C.c_long, [C.c_void_p]),
            'iio_channel_get_data_format': (C.POINTER(Format), [C.c_void_p]),
            'iio_device_get_sample_size': (C.c_ssize_t, [C.c_void_p]),
            'iio_device_create_buffer': (C.c_void_p, [C.c_void_p, C.c_size_t, C.c_bool]),
            'iio_buffer_destroy': (None, [C.c_void_p]),
            'iio_buffer_refill': (C.c_ssize_t, [C.c_void_p]),
            'iio_buffer_push': (C.c_ssize_t, [C.c_void_p]),
            'iio_buffer_start': (C.c_void_p, [C.c_void_p]),
            'iio_buffer_end': (C.c_void_p, [C.c_void_p]),
            'iio_buffer_first': (C.c_void_p, [C.c_void_p, C.c_void_p]),
            'iio_buffer_step': (C.c_ssize_t, [C.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            method = getattr(self.lib, name); method.restype = result; method.argtypes = args
        major, minor, tag = C.c_uint(), C.c_uint(), C.create_string_buffer(8)
        self.lib.iio_library_get_version(C.byref(major), C.byref(minor), tag)
        if major.value != 0 or minor.value < 23:
            raise RuntimeError('This example requires libiio 0.x >= 0.23')
        self.ctx = self.lib.iio_create_context_from_uri(uri.encode())
        if not self.ctx:
            raise OSError(C.get_errno(), 'create context')
        try:
            self.check(self.lib.iio_context_set_timeout(self.ctx, 1500), 'set timeout')
            self.device('h102-profile-control'); self.device('adrv9002-phy')
        except BaseException:
            self.close(); raise

    @staticmethod
    def check(result, operation):
        """Preserve negative errno instead of reporting a zero-byte success."""
        if result < 0: raise OSError(-result, operation)
        return result

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def close(self):
        """Destroy buffers first; repeated close is harmless."""
        if self.ctx:
            self.lib.iio_context_destroy(self.ctx); self.ctx = None

    def device(self, name):
        """Find a stable device name; use an explicit ID if names are ambiguous."""
        value = self.lib.iio_context_find_device(self.ctx, name.encode())
        if not value: raise ValueError('Device not found: '+name)
        return value

    def read(self, device, attribute, channel=None, output=False):
        """Read public text attributes; output distinguishes PHY channels with the same ID."""
        obj = self.device(device); buffer = C.create_string_buffer(16384)
        method = self.lib.iio_device_attr_read
        if channel is not None:
            obj = self.lib.iio_device_find_channel(obj, channel.encode(), output)
            if not obj: raise ValueError('Channel not found: '+channel)
            method = self.lib.iio_channel_attr_read
        size = self.check(method(obj, attribute.encode(), buffer, len(buffer)), 'attribute '+attribute)
        if size >= len(buffer): raise RuntimeError('Attribute response truncated')
        return buffer.raw[:size].decode().rstrip('\0\r\n')

    def profile_read(self, name): return self.read('h102-profile-control', name)

    def snapshot(self):
        """Double-read transaction state and sequence to reject switching or crossed snapshots."""
        stamp = tuple(self.profile_read(k) for k in ('status','request_id','configuration_id'))
        if stamp[0] in ('unavailable','queued','applying'): raise RuntimeError('Profile busy: '+stamp[0])
        result = json.loads(self.profile_read('active_info'))
        if stamp != tuple(self.profile_read(k) for k in ('status','request_id','configuration_id')):
            raise RuntimeError('Profile changed while reading')
        return result

    def select(self, profile, timeout=240):
        """Verify the request ticket, terminal state and profile ID without automatic retries."""
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}', profile): raise ValueError('Profile ID syntax')
        if profile not in self.profile_read('available').split(): raise ValueError('Profile unavailable')
        before = self.snapshot()
        if before['active'] == profile: return before
        ticket = int(self.profile_read('request_id')) + 1
        self.check(self.lib.iio_device_attr_write(self.device('h102-profile-control'), b'select', profile.encode()), 'select')
        deadline = time.monotonic()+timeout
        while True:
            current = int(self.profile_read('request_id')); status = self.profile_read('status')
            if current != ticket: raise RuntimeError('Concurrent writer: request outcome unknown')
            if status not in ('queued','applying'):
                if status != 'applied': raise RuntimeError(status+': '+self.profile_read('error'))
                result = self.snapshot()
                if (result['active'] != profile or result['boot_id'] != before['boot_id']
                        or int(result['configuration_id']) <= int(before['configuration_id'])):
                    raise RuntimeError('Selected profile identity mismatch')
                return result
            if time.monotonic() >= deadline: raise TimeoutError('Profile deadline; inspect state before retry')
            time.sleep(.1)

    def transfer(self, direction, channel, permit, raw=None):
        """Perform finite RX refill or RF-off TX push under an existing real board session.

        Return only complete IQ16; this does not establish continuous operation or RF output.
        """
        def guard():
            if not permit(): raise RuntimeError('Managed session permission lost')
        guard()
        if direction not in ('rx','tx') or type(channel) is not int or channel not in (1,2): raise ValueError('Direction/channel')
        tx = direction == 'tx'; name = f'axi-adrv9002-{direction}{"2" if channel==2 else ""}-lpc'
        dev = self.device(name)
        for i in range(self.lib.iio_device_get_channels_count(dev)):
            self.lib.iio_channel_disable(self.lib.iio_device_get_channel(dev, i))
        names = ('voltage0','voltage1') if tx else ('voltage0_i','voltage0_q')
        channels = [self.lib.iio_device_find_channel(dev, n.encode(), tx) for n in names]
        for i, ch in enumerate(channels):
            if not ch or self.lib.iio_channel_get_index(ch) != i: raise RuntimeError('Scan index')
            f = self.lib.iio_channel_get_data_format(ch).contents
            if (f.length,f.bits,f.shift,f.is_signed,f.is_be,f.repeat)!=(16,16,0,True,False,1):
                raise RuntimeError('Scan format is not little-endian signed IQ16')
            self.lib.iio_channel_enable(ch)
        if self.lib.iio_device_get_sample_size(dev) != 4: raise RuntimeError('Scan size')
        if tx and (raw is None or len(raw) != SAMPLES*4): raise ValueError('TX requires 262144 bytes')
        guard();buffer = self.lib.iio_device_create_buffer(dev, SAMPLES, False)
        if not buffer: raise OSError(C.get_errno(), 'create buffer')
        try:
            if not tx and self.check(self.lib.iio_buffer_refill(buffer), 'refill') != SAMPLES*4:
                raise RuntimeError('Short RX refill')
            base, end = self.lib.iio_buffer_start(buffer), self.lib.iio_buffer_end(buffer)
            offsets = [self.lib.iio_buffer_first(buffer,c)-base for c in channels]
            if self.lib.iio_buffer_step(buffer)!=4 or offsets!=[0,2] or end-base!=SAMPLES*4:
                raise RuntimeError('Buffer layout/length')
            guard()
            if tx:
                C.memmove(base, raw, len(raw))
                if self.check(self.lib.iio_buffer_push(buffer),'push') != len(raw): raise RuntimeError('Short TX push')
                result = raw
            else: result = C.string_at(base,SAMPLES*4)
            guard();return result
        finally: self.lib.iio_buffer_destroy(buffer)


def main():
    """Query by default; select explicitly writes configuration, without arbitrary registers."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri',required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('xml');sub.add_parser('status');sub.add_parser('profiles')
    select=sub.add_parser('select');select.add_argument('profile')
    read=sub.add_parser('read');read.add_argument('device');read.add_argument('attribute')
    read.add_argument('--channel');read.add_argument('--output',action='store_true')
    args=parser.parse_args()
    with Context(args.uri) as ctx:
        if args.action=='xml': print(ctx.lib.iio_context_get_xml(ctx.ctx).decode())
        elif args.action=='status': print(json.dumps(ctx.snapshot(),ensure_ascii=False,indent=2))
        elif args.action=='profiles': print(ctx.profile_read('available'))
        elif args.action=='select': print(json.dumps(ctx.select(args.profile),ensure_ascii=False,indent=2))
        else: print(ctx.read(args.device,args.attribute,args.channel,args.output))


if __name__=='__main__':main()

# End of file: h102_api.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
