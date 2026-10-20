#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_gnss_uart_baseline.py
@brief      Set the idle GNSS UART1 to 38400 baud without echo under both locks.
@details    Correct the Linux 9600/canonical/echo baseline for the 38400-baud GNSS link.
            Change only ttyPS1 termios and clear local queues; do not send UBX commands or
            modify GNSS flash/RAM, RF, data control or UART0. Keep the corrected baseline on success;
            later sessions restore it. On error restore the original termios captured by this call.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-05
"""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import subprocess
import termios
import time


def raw_settings(original):
    """Build 38400/8N1/no-echo settings, copying control characters rather than mutating inputs."""
    configured = list(original)
    configured[0] = configured[1] = configured[3] = 0
    configured[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | termios.B38400
    configured[4] = configured[5] = termios.B38400
    configured[6] = list(original[6])
    configured[6][termios.VMIN] = configured[6][termios.VTIME] = 0
    return configured


def serializable(value):
    """Encode termios control bytes in hex for exact archival and comparison."""
    return value[:6] + [[{'hex': x.hex()} if isinstance(x, bytes) else x
                        for x in value[6]]]


def configure(fd):
    """Set an exclusively owned FD idle baseline; restore old settings on failure only."""
    original = termios.tcgetattr(fd)
    configured = raw_settings(original)
    try:
        # Disable echo and fix baud before flushing queues; do not forward GNSS location messages.
        termios.tcsetattr(fd, termios.TCSANOW, configured)
        termios.tcflush(fd, termios.TCIOFLUSH)
        actual = termios.tcgetattr(fd)
        if actual != configured:
            raise RuntimeError('GNSS_UART_BASELINE_READBACK')
        return dict(original=serializable(original), actual=serializable(actual),
                    changed=actual != original, UART='/dev/ttyPS1', baud=38400,
                    echo=False, GNSS_protocol_write=False)
    except BaseException:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        raise


def establish():
    """Use fixed UART1 under root RX/GNSS locks; reject active users or lock contention."""
    if os.geteuid() != 0:
        raise PermissionError('GNSS_UART_BASELINE_REQUIRES_ROOT')
    if Path('/sys/class/tty/ttyPS1/device').resolve().name != 'e0001000.serial':
        raise RuntimeError('GNSS_UART_IDENTITY')
    with ExitStack() as stack:
        for name in ('h102-rx-session.lock', 'h102-gnss-g0.lock'):
            descriptor = os.open('/run/lock/' + name,
                                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
            lock = stack.enter_context(os.fdopen(descriptor, 'r+b'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = subprocess.run(['fuser', '/dev/ttyPS1'], capture_output=True, timeout=3)
        if busy.returncode != 1 or busy.stdout.strip():
            raise RuntimeError('GNSS_UART_BUSY')
        fd = os.open('/dev/ttyPS1', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL)
            result = configure(fd)
            result.update(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                          completed_monotonic=time.monotonic(),
                          persistent_Linux_idle_baseline=True)
            return result
        finally:
            try:
                fcntl.ioctl(fd, termios.TIOCNXCL)
            finally:
                os.close(fd)


def main():
    """Run explicit maintenance/boot setup with an optional root-owned report and no RF changes."""
    parser = argparse.ArgumentParser(description='Set the H102 GNSS UART1 Linux idle baseline')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = establish()
    raw = (json.dumps(result, indent=2) + '\n').encode()
    if args.report:
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    print(raw.decode(), end='')


if __name__ == '__main__':
    main()

# End of file: h102_gnss_uart_baseline.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
