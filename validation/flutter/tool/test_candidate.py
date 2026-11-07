import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
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

    def test_reference_rejects_existing_target_and_bad_archive_without_overwrite(self):
        shim = candidate.terminal_view_ime
        target = self.app / 'candidate/reference_terminal_view'
        target.mkdir(parents=True)
        (target / 'keep').write_text('unchanged')
        with patch.object(shim.urllib.request, 'urlopen') as fetch, self.assertRaises(ValueError):
            shim.prepare_reference(self.app, candidate.SOURCE)
        fetch.assert_not_called()
        self.assertEqual((target / 'keep').read_text(), 'unchanged')
        (target / 'keep').unlink(); target.rmdir()
        with patch.object(shim.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')), self.assertRaises(ValueError):
            shim.prepare_reference(self.app, candidate.SOURCE)
        self.assertFalse(target.exists())
        self.assertFalse((self.app / 'reference-terminal-manifest.json').exists())

    def test_reference_rejects_archive_links_and_duplicate_members(self):
        shim = candidate.terminal_view_ime
        for kind in ('link', 'duplicate'):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
                item = tarfile.TarInfo('a'); item.size = 1
                archive.addfile(item, io.BytesIO(b'x'))
                second = tarfile.TarInfo('b' if kind == 'link' else 'a')
                if kind == 'link':
                    second.type = tarfile.SYMTYPE; second.linkname = '../outside'
                    archive.addfile(second)
                else:
                    second.size = 1; archive.addfile(second, io.BytesIO(b'y'))
            blob = buffer.getvalue()
            info = {'archiveUrl': 'https://example.invalid/archive', 'archiveSha256': shim.digest(blob)}
            with self.subTest(kind=kind), patch.object(shim, 'metadata', return_value=(info, {'files': {}})), \
                    patch.object(shim.urllib.request, 'urlopen', return_value=io.BytesIO(blob)), self.assertRaises(ValueError):
                shim.prepare_reference(self.app, candidate.SOURCE)
            self.assertFalse((self.app / 'candidate/reference_terminal_view').exists())
            self.assertFalse((self.app / 'reference-terminal-manifest.json').exists())

    def test_ime_manifest_rejects_changed_patch_and_overlapping_renderer(self):
        shim = candidate.terminal_view_ime
        source = self.base / 'tampered'; (source / 'patches').mkdir(parents=True)
        real = candidate.SOURCE / 'patches'
        for name in ('manifest.json', 'ime-observation-manifest.json', 'terminal_view-0.5.0-ime-observation.patch'):
            (source / 'patches' / name).write_bytes((real / name).read_bytes())
        (source / 'patches/terminal_view-0.5.0-ime-observation.patch').write_text('tampered')
        with self.assertRaises(ValueError): shim.metadata(source)
        (source / 'patches/terminal_view-0.5.0-ime-observation.patch').write_bytes((real / 'terminal_view-0.5.0-ime-observation.patch').read_bytes())
        m = json.loads((source / 'patches/manifest.json').read_text())
        m['files']['lib/src/terminal_view.dart'] = {}
        (source / 'patches/manifest.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError): shim.metadata(source)

    @unittest.skipUnless(os.environ.get('HERDR_TEST_TERMINAL_ARCHIVE'), 'optional pinned public archive not supplied')
    def test_real_pinned_archive_installs_reference_and_candidate_without_pub_cache(self):
        shim = candidate.terminal_view_ime
        blob = Path(os.environ['HERDR_TEST_TERMINAL_ARCHIVE']).read_bytes()
        before = dict(os.environ)
        with patch.object(shim.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(blob)):
            reference = shim.prepare_reference(self.app, candidate.SOURCE)
            candidate.apply(self.app)
        ime, combining = shim.metadata(candidate.SOURCE)
        self.assertEqual(reference['imeObservation'], ime)
        for name, hashes in ime['files'].items():
            for package in ('reference_terminal_view', 'terminal_view'):
                self.assertEqual(shim.digest((self.app / 'candidate' / package / name).read_bytes()), hashes['afterSha256'])
        for name, hashes in combining['files'].items():
            self.assertEqual(shim.digest((self.app / 'candidate/reference_terminal_view' / name).read_bytes()), hashes['beforeSha256'])
            self.assertEqual(shim.digest((self.app / 'candidate/terminal_view' / name).read_bytes()), hashes['afterSha256'])
        self.assertEqual(json.loads((self.app / 'candidate-manifest.json').read_text())['imeObservation'], ime)
        self.assertEqual(dict(os.environ), before)

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

    def test_patch_keeps_lf_even_with_inherited_git_autocrlf(self):
        source = self.base / 'source'
        patches = source / 'patches'
        patches.mkdir(parents=True)
        before, after = b'base\n', b'fixed\n'
        patch_bytes = b'--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-base\n+fixed\n'
        (patches / 'probe.patch').write_bytes(patch_bytes)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
            entry = tarfile.TarInfo('source.txt')
            entry.size = len(before)
            bundle.addfile(entry, io.BytesIO(before))
        blob = archive.getvalue()
        (source / 'pubspec.lock').write_text(self.baseline)
        (patches / 'manifest.json').write_text(json.dumps({
            'patch': 'probe.patch', 'patchSha256': candidate.digest(patch_bytes),
            'archiveUrl': 'https://invalid.example/fixture', 'archiveSha256': candidate.digest(blob),
            'files': {'source.txt': {'beforeSha256': candidate.digest(before), 'afterSha256': candidate.digest(after)}},
        }))
        git_env = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.autocrlf', 'GIT_CONFIG_VALUE_0': 'true'}
        with patch.object(candidate, 'SOURCE', source), patch.dict(os.environ, git_env), \
                patch.object(candidate.urllib.request, 'urlopen', return_value=io.BytesIO(blob)), \
                patch.object(candidate.terminal_view_ime, 'apply_shim', return_value={'fixture': True}):
            candidate.apply(self.app)
        self.assertEqual((self.app / 'candidate/terminal_view/source.txt').read_bytes(), after)


if __name__ == '__main__':
    unittest.main()
