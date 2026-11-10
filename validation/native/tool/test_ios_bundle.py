import json
import stat
import tempfile
import unittest
from pathlib import Path

import ios_bundle


def synth_bundle(root: Path, tamper: str | None = None):
    root.mkdir(parents=True)
    (root / 'libheeler_easytier.a').write_bytes(b'fixture-archive')
    (root / 'candidate-provenance.json').write_text('{}', encoding='utf-8')
    (root / 'upstream-sources.lock').write_text('', encoding='utf-8')
    (root / 'Heeler-Cargo.lock').write_text('', encoding='utf-8')
    (root / 'build-details.json').write_text('{}', encoding='utf-8')
    files = {p.relative_to(root).as_posix(): ios_bundle.sha(p)
             for p in sorted(root.rglob('*')) if p.is_file()}
    if tamper:
        files[tamper] = '0' * 64
    manifest = {'schemaVersion': 1, 'target': ios_bundle.TARGET, 'sourceCommit': 'a' * 40,
                'rust': '1.95.0', 'profile': 'release', 'files': files,
                'staticInspection': 'passed'}
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    stub = root.parent / 'nm-stub'
    lines = ''.join(f'0000000000000000 T _{name}\n' for name in ios_bundle.SYMBOLS)
    stub.write_text('#!/bin/sh\nprintf \'' + lines.replace('\\', '\\\\') + '\'\n', encoding='utf-8')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


class IosBundleTests(unittest.TestCase):
    def test_nm_parser_takes_global_text_symbols_and_strips_underscores(self):
        output = ('                 U _malloc\n'
                  '0000000000000000 T _heeler_et_stream_close\n'
                  '0000000000000000 W _heeler_et_node_status\n'
                  '0000000000000000 t _local_helper\n')
        self.assertEqual(ios_bundle.symbols_from_nm(output),
                         {'heeler_et_stream_close', 'heeler_et_node_status'})

    def test_verify_rejects_tampered_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'bundle'
            stub = synth_bundle(root, tamper='libheeler_easytier.a')
            with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
                ios_bundle.verify(root, 'a' * 40, nm=str(stub))

    def test_verify_accepts_synthetic_bundle_and_rejects_missing_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'bundle'
            stub = synth_bundle(root)
            manifest = ios_bundle.verify(root, 'a' * 40, nm=str(stub))
            self.assertEqual(manifest['target'], ios_bundle.TARGET)
            empty = root.parent / 'nm-empty'
            empty.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            empty.chmod(empty.stat().st_mode | stat.S_IEXEC)
            with self.assertRaisesRegex(ValueError, 'required exported symbols missing'):
                ios_bundle.verify(root, 'a' * 40, nm=str(empty))


if __name__ == '__main__':
    unittest.main()
