"""Test real protocol frames without device access or authentication changes."""
import io
import math
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h102_control.protocol import (MAX_DEPTH, MAX_FRAME_BYTES, ProtocolError,
                                   decode_frame, encode_frame, receive_frame)


class ProtocolTest(unittest.TestCase):
    """Cover encoding ambiguity, truncation, memory limits and numeric errors."""

    def test_status_roundtrip_and_multiframe(self):
        value = {'version': 1, 'operation': 'status', 'note': 'Device status'}
        wire = encode_frame(value)
        reader = io.BytesIO(wire + wire)
        self.assertEqual(receive_frame(reader), value)
        self.assertEqual(receive_frame(reader), value)
        with self.assertRaises(EOFError):
            receive_frame(reader)

    def test_duplicate_or_nonfinite_rejected(self):
        for wire in [b'{"a":1,"a":2}\n', b'{"v":NaN}\n',
                     b'{"v":1e999}\n', b'{"v":Infinity}\n']:
            with self.subTest(wire=wire), self.assertRaises(ProtocolError):
                decode_frame(wire)
        for number in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ProtocolError):
                encode_frame({'v': number})

    def test_truncated_multiple_or_invalid_utf8_rejected(self):
        for wire in [b'{}', b'{}\n{}\n', b'{}\r\n', b'{"x":"\xff"}\n',
                     b'[]\n', b'{}x\n']:
            with self.subTest(wire=wire), self.assertRaises(ProtocolError):
                decode_frame(wire)

    def test_depth_and_size_limits(self):
        value = {}
        for _ in range(MAX_DEPTH + 1):
            value = {'nested': value}
        with self.assertRaises(ProtocolError):
            encode_frame(value)
        with self.assertRaises(ProtocolError):
            receive_frame(io.BytesIO(b'x' * (MAX_FRAME_BYTES + 1)))
        with self.assertRaises(ProtocolError):
            encode_frame({'x': 'x' * MAX_FRAME_BYTES})


if __name__ == '__main__':
    unittest.main()
