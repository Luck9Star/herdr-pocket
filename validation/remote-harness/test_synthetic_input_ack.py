"""Fixed QA responses on owned PTYs; no credentials or external processes."""
import os
import select
import unittest

from test_pty_size import fixture, owned_capture, wait_until


@unittest.skipIf(fixture is None, 'POSIX PTY is required')
class SyntheticInputAckTests(unittest.TestCase):
    def test_fixed_prefixes_only_and_no_duplicate_response(self):
        for role, short in (('et', b'E'), ('ts', b'T')):
            ack = fixture.SyntheticInputAck(role)
            for incoming in (b'', b'unknown', b'ET-', b'TS-', b'not-a-secret'):
                self.assertEqual(ack.response(incoming), b'')
            first = ack.response(short)
            self.assertIn(('Synthetic ' + role.upper() + ' ACK ONE').encode(), first)
            self.assertEqual(ack.response(short), b'')
            self.assertIn(b'ACK TWO', ack.response(short + short.lower()))
            self.assertEqual(ack.response(short + short.lower()), b'')
            self.assertEqual(ack.response(short + b'unknown'), b'')

    def test_real_pty_fixed_byte_inputs(self):
        for role, short in (('et', b'E'), ('ts', b'T')):
            for first, second in ((short, short.lower()),):
                with self.subTest(role=role, first=first), owned_capture(ack_role=role) as (root, master, _slave, proc, _attrs):
                    output = bytearray()
                    def contains(marker):
                        if select.select([master], [], [], 0)[0]:
                            output.extend(os.read(master, 65536))
                        return marker in output
                    for value in first:
                        os.write(master, bytes([value]))
                    one = ('Synthetic ' + role.upper() + ' ACK ONE').encode()
                    wait_until(lambda: contains(one))
                    self.assertEqual((root / 'received.bin').read_bytes(), first)
                    os.write(master, second)
                    two = ('Synthetic ' + role.upper() + ' ACK TWO').encode()
                    wait_until(lambda: contains(two))
                    self.assertEqual((root / 'received.bin').read_bytes(), first + second)
                    self.assertEqual(output.count(one), 1)
                    self.assertEqual(output.count(two), 1)
                    (root / 'stop-capture').touch()
                    self.assertEqual(proc.wait(timeout=2), 0)

    def test_default_and_wrong_role_never_ack_or_echo(self):
        for role, incoming in ((None, b'ET-ONE'), ('et', b'TS-ONE'), ('ts', b'ET-ONE')):
            with self.subTest(role=role), owned_capture(ack_role=role) as (root, master, _slave, proc, _attrs):
                os.write(master, incoming)
                wait_until(lambda: (root / 'received.bin').read_bytes() == incoming)
                (root / 'stop-capture').touch()
                self.assertEqual(proc.wait(timeout=2), 0)
                output = bytearray()
                while select.select([master], [], [], 0)[0]:
                    output.extend(os.read(master, 65536))
                self.assertNotIn(b' ACK ', output)
                self.assertNotIn(incoming, output)


if __name__ == '__main__':
    unittest.main()
