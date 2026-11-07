import base64
import importlib.util
import json
import os
from pathlib import Path
import types
import unittest

spec = importlib.util.spec_from_file_location(
    "observer_mode_probe", Path(__file__).with_name("observer_mode_probe.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ModeEvidenceTests(unittest.TestCase):
    def test_strict_capability_types_and_fields(self):
        expected = {"version": 1, "enabled": True}
        self.assertTrue(probe.same_typed(expected, expected))
        self.assertFalse(probe.same_typed({"version": True, "enabled": True}, expected))
        self.assertFalse(probe.same_typed({**expected, "extra": 1}, expected))

    def test_rejects_stale_delta_and_wrong_mode(self):
        data = probe.mode_bytes(True, False)
        self.assertFalse(probe.mode_frame_seen([(4, True, data)], 4, (True, False)))
        self.assertFalse(probe.mode_frame_seen([(5, False, data)], 4, (True, False)))
        self.assertFalse(probe.mode_frame_seen([(5, True, data)], 4, (False, False)))
        self.assertFalse(
            probe.mode_frame_seen([(5, True, data + b"junk")], 4, (True, False))
        )
        self.assertTrue(probe.mode_frame_seen([(5, True, data)], 4, (True, False)))
        self.assertFalse(
            probe.fresh_visual_seen([(4, True, b"HPVIS01")], 4, b"HPVIS01")
        )
        self.assertFalse(
            probe.fresh_visual_seen([(5, True, b"HPVIS02")], 4, b"HPVIS01")
        )
        self.assertTrue(
            probe.fresh_visual_seen([(5, False, b"HPVIS01")], 4, b"HPVIS01")
        )

    def test_mode_detection(self):
        self.assertFalse(probe.has_mode_bytes([(1, True, b"visible only")]))
        self.assertTrue(probe.has_mode_bytes([(1, True, b"\x1b[?2004h")]))


class FrameValidationTests(unittest.TestCase):
    def setUp(self):
        read_fd, self.write_fd = os.pipe()
        self.stream = os.fdopen(read_fd, "rb", buffering=0)
        self.reader = probe.Frames(types.SimpleNamespace(stdout=self.stream), 120, 40)

    def tearDown(self):
        self.reader.close()
        self.stream.close()
        os.close(self.write_fd)

    def frame(self, **changes):
        value = {
            "type": "terminal.frame",
            "encoding": "ansi",
            "seq": 1,
            "full": True,
            "width": 120,
            "height": 40,
            "bytes": base64.b64encode(b"hello").decode(),
        }
        value.update(changes)
        os.write(self.write_fd, json.dumps(value).encode() + b"\n")

    def test_accepts_contiguous_full_delta(self):
        self.frame()
        self.frame(seq=2, full=False)
        self.assertEqual(
            self.reader.read_for(0.02), [(1, True, b"hello"), (2, False, b"hello")]
        )

    def test_rejects_invalid_first_or_geometry_or_encoding(self):
        for change in (
            {"full": False},
            {"width": 80},
            {"seq": True},
            {"full": 1},
            {"bytes": "!!!"},
        ):
            with self.subTest(change=change):
                read_fd, write_fd = os.pipe()
                stream = os.fdopen(read_fd, "rb", buffering=0)
                reader = probe.Frames(types.SimpleNamespace(stdout=stream), 120, 40)
                value = {
                    "type": "terminal.frame",
                    "encoding": "ansi",
                    "seq": 1,
                    "full": True,
                    "width": 120,
                    "height": 40,
                    "bytes": "aGVsbG8=",
                }
                value.update(change)
                try:
                    os.write(write_fd, json.dumps(value).encode() + b"\n")
                    with self.assertRaises(RuntimeError):
                        reader.read_for(0.02)
                finally:
                    reader.close()
                    stream.close()
                    os.close(write_fd)

    def test_rejects_sequence_gap(self):
        self.frame()
        self.frame(seq=3, full=False)
        with self.assertRaises(RuntimeError):
            self.reader.read_for(0.02)


if __name__ == "__main__":
    unittest.main()
