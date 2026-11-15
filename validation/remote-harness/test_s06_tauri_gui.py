import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    from s06_tauri_gui import SplitDriver, observed_tick, peer_connection_evidence, GuiFailure
except ModuleNotFoundError as missing:
    if missing.name != 'cryptography':
        raise
    observed_tick = None


@unittest.skipIf(observed_tick is None, 'pairing requirements are installed in the native GUI workflow')
class TauriSplitEvidenceTests(unittest.TestCase):
    def test_stale_read_relocates_before_the_only_native_click(self):
        for read in ('textContent', 'displayed', 'enabled'):
            calls, lookups = [], []
            def call(method, path, data=None):
                calls.append((method, path))
                if path.endswith('/elements'):
                    lookups.append(1)
                    return [{'element-6066-11e4-a52e-4f735466cecf': 'old' if len(lookups) == 1 else 'new'}]
                if '/old/' in path and path.endswith('/' + read):
                    raise GuiFailure('webdriver_' + read + '_stale_element_reference')
                if path.endswith('/property/textContent'):
                    return '管理'
                return True
            SplitDriver(SimpleNamespace(session='/session/test', call=call)).named('管理')
            self.assertEqual([p for m, p in calls if p.endswith('/click')], ['/session/test/element/new/click'])
            self.assertEqual(len(lookups), 2)

    def test_native_click_failure_is_never_replayed(self):
        clicks = []
        def call(method, path, data=None):
            if path.endswith('/elements'):
                return [{'element-6066-11e4-a52e-4f735466cecf': 'one'}]
            if path.endswith('/property/textContent'):
                return '管理'
            if path.endswith('/click'):
                clicks.append(path)
                raise GuiFailure('webdriver_click_stale_element_reference')
            return True
        with self.assertRaises(GuiFailure):
            SplitDriver(SimpleNamespace(session='/session/test', call=call)).named('管理')
        self.assertEqual(len(clicks), 1)

    def test_visible_snapshots_require_the_correct_independent_peer_marker(self):
        self.assertEqual(observed_tick('Synthetic observe tick 000123', 0), 123)
        self.assertEqual(observed_tick('S06 B tick 000124', 1), 124)
        for text, side in [('S06 B tick 000124', 0), ('Synthetic observe tick 000123', 1),
                           ('Synthetic observe tick 1', 0), ('', 1),
                           ('S06 B tick 000001 S06 B tick 000002', 1), ('x' * 65537, 0)]:
            with self.subTest(side=side):
                with self.assertRaises(GuiFailure):
                    observed_tick(text, side)

    def test_authentication_and_close_are_for_the_reviewed_key_and_same_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            approval = SimpleNamespace(root=root, config={'username': 'fixture'}, fingerprint='SHA256:reviewed')
            accepted = 'Accepted publickey for fixture from 127.0.0.1 port 40123 ssh2: ED25519 SHA256:reviewed\n'
            other = 'Accepted publickey for fixture from 127.0.0.1 port 40124 ssh2: ED25519 SHA256:other\n'
            closed = 'Received disconnect from 127.0.0.1 port 40123:11: explicit close\n'
            for log, count, done in [(other, 0, False), (accepted, 1, False),
                    (closed + accepted, 1, False), (accepted + closed.replace('40123', '40124'), 1, False),
                    (accepted + closed, 1, True), (accepted + 'Connection closed by 127.0.0.1 port 40123\n', 1, True),
                    (accepted + accepted, 2, False)]:
                (root / 'sshd.log').write_text(log)
                self.assertEqual(peer_connection_evidence(approval), {'authenticationCount': count, 'closed': done})


if __name__ == '__main__':
    unittest.main()
