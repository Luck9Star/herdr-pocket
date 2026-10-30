import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('candidate', Path(__file__).with_name('candidate.py'))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='herdr-candidate-tool-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app = self.base / 'generated-app'
        self.app.mkdir()
        (self.app / '.herdr-generated-probe.json').write_text(json.dumps({'kind': 'herdr-flutter-validation'}))
        (self.app / 'analysis_options.yaml').write_text('analyzer:\n  errors:\n    todo: ignore\n')
        self.baseline = (candidate.SOURCE / 'pubspec.lock').read_text()
        (self.app / 'pubspec.lock').write_text(self.baseline)
        self.env = patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': str(self.base)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rejects_non_ci_and_non_generated_or_outside_paths(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), self.assertRaises(ValueError):
            candidate.generated_app(self.app)
        for directory in [self.base, candidate.SOURCE]:
            with self.assertRaises(ValueError):
                candidate.generated_app(directory)
        (self.app / '.herdr-generated-probe.json').unlink()
        with self.assertRaises(ValueError):
            candidate.generated_app(self.app)

    def test_refuses_existing_overrides_before_fetch(self):
        (self.app / 'pubspec_overrides.yaml').write_text('keep')
        with patch.object(candidate.urllib.request, 'urlopen') as request, self.assertRaises(ValueError):
            candidate.apply(self.app)
        request.assert_not_called()
        self.assertEqual((self.app / 'pubspec_overrides.yaml').read_text(), 'keep')

    def test_archive_hash_failure_never_writes_override(self):
        with patch.object(candidate.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')), self.assertRaises(ValueError):
            candidate.apply(self.app)
        self.assertFalse((self.app / 'pubspec_overrides.yaml').exists())
        self.assertEqual((self.app / 'pubspec.lock').read_text(), self.baseline)

    def test_lock_requires_exact_other_dependency_blocks(self):
        blocks = candidate.lock_packages(self.baseline)
        replacement = '\n'.join([
            '    dependency: "direct overridden"', '    description:',
            '      path: "candidate/terminal_view"', '      relative: true',
            '    source: path', '    version: "0.5.0"',
        ])
        resolved = self.baseline.replace(blocks['terminal_view'], replacement)
        (self.app / 'pubspec.lock').write_text(resolved)
        (self.app / 'candidate-manifest.json').write_text('{}')
        candidate.verify_lock(self.app)
        drift = resolved.replace('    source: hosted', '    source: unexpected', 1)
        (self.app / 'pubspec.lock').write_text(drift)
        with self.assertRaises(ValueError):
            candidate.verify_lock(self.app)


if __name__ == '__main__':
    unittest.main()
