"""Negative checks for the opt-in, same-source iOS SSH acceptance batch."""
from pathlib import Path
import hashlib
import io
import json
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import ios_direct_ssh_batch as batch


class WorkflowRoutingTests(unittest.TestCase):
    def test_branch_routes_both_clients_or_a_single_requested_client(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/direct-ssh-ios.yml').read_text()
        routes = {}
        for client in ('flutter', 'tauri'):
            job = re.search(rf'(?ms)^  {client}-ordinary-ssh-ios:\n    if: (.*?)^    runs-on:', workflow)
            self.assertIsNotNone(job)
            routes[client] = []
            for clause in job[1].removeprefix('>-\n').split('&&'):
                match = re.fullmatch(r"(!?)startsWith\(github\.ref, '([^']+)'\)", clause.strip())
                self.assertIsNotNone(match, 'expected a branch-prefix condition')
                routes[client].append(match.groups())

        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-'
        for ref, expected in (
            (prefix + 'both-r1', {'flutter', 'tauri'}),
            (prefix + 'flutter-only-r1', {'flutter'}),
            (prefix + 'tauri-only-r1', {'tauri'}),
            ('refs/heads/main', set()),
            ('refs/tags/codex/acceptance/direct-ssh-ios-r1', set()),
        ):
            with self.subTest(ref=ref):
                selected = {client for client, clauses in routes.items()
                            if all(ref.startswith(branch) != bool(negated) for negated, branch in clauses)}
                self.assertEqual(selected, expected)


class PublicEvidenceTests(unittest.TestCase):
    source_sha = 'a' * 40

    def evidence(self, root, *, status='passed'):
        from PIL import Image
        artifacts = {}
        for index, name in enumerate(sorted(batch.REQUIRED_IMAGES)):
            stream = io.BytesIO()
            Image.new('RGB', (8, 8), (index * 30, 40, 60)).save(stream, format='PNG')
            data = stream.getvalue()
            (root / name).write_bytes(data)
            artifacts[name] = hashlib.sha256(data).hexdigest()
            if name in batch.TERMINAL_PROOFS:
                (root / batch.TERMINAL_PROOFS[name]).write_text(json.dumps({
                    'imageSha256': artifacts[name], 'markerVisible': True,
                    'tokenVisible': True, 'proofSequenceVisible': True}))
        report = {'sourceSHA': self.source_sha, 'status': status, 'artifacts': artifacts}
        (root / 'result.json').write_text(json.dumps(report))
        return report

    def publish(self, root, destination):
        return batch.publish_evidence(root, destination, shell='tauri', source_sha=self.source_sha)

    def test_success_requires_and_exports_exactly_the_six_final_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.evidence(root)
            (root / 'private-key').write_text('not public')
            (root / 'unreviewed.log').write_text('not public')
            destination = root / 'public'
            expected = {'result.json', *batch.REQUIRED_IMAGES, *batch.TERMINAL_PROOFS.values()}
            self.assertEqual(self.publish(root, destination), expected)
            self.assertEqual({path.name for path in destination.iterdir()}, expected)

    def test_wrong_source_cannot_export_even_a_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.evidence(root)
            with self.assertRaisesRegex(batch.BatchFailure, 'source_or_status'):
                batch.publish_evidence(root, root / 'public', shell='tauri', source_sha='b' * 40)
            self.assertFalse((root / 'public').exists())

    def test_missing_scenario_in_passed_result_is_a_failure_but_retains_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.evidence(root)
            del report['artifacts']['key-change-review.png']
            (root / 'result.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(batch.BatchFailure, 'required_images_missing'):
                self.publish(root, root / 'public')
            self.assertEqual({path.name for path in (root / 'public').iterdir()}, {'result.json'})

    def test_success_rejects_changed_png_or_unrelated_ocr_hash(self):
        for corrupt in ('image', 'proof'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.evidence(root)
                if corrupt == 'image':
                    (root / 'ordinary-terminal.png').write_bytes(b'not the captured PNG')
                else:
                    path = root / 'ordinary-terminal-ocr.json'
                    proof = json.loads(path.read_text())
                    proof['imageSha256'] = 'f' * 64
                    path.write_text(json.dumps(proof))
                with self.assertRaisesRegex(batch.BatchFailure, 'hash_mismatch'):
                    self.publish(root, root / 'public')
                self.assertFalse((root / 'public/ordinary-terminal.png').exists())

    def test_failed_run_retains_only_completed_bound_scenes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.evidence(root, status='failed')
            (root / 'key-change-terminal-ocr.json').unlink()
            (root / 'key-change-review.png').write_bytes(b'unbound image')
            self.assertEqual(self.publish(root, root / 'public'),
                             {'result.json', 'ordinary-terminal.png', 'ordinary-terminal-ocr.json'})

    def test_failed_run_with_only_sanitized_result_remains_publishable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'result.json').write_text(json.dumps({'status': 'failed', 'sourceSHA': self.source_sha}))
            self.assertEqual(self.publish(root, root / 'public'), {'result.json'})

    def test_cli_retains_failure_after_exporting_a_sanitized_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'result.json').write_text(json.dumps({'status': 'failed', 'sourceSHA': self.source_sha}))
            result = subprocess.run([sys.executable, str(Path(batch.__file__)), 'publish',
                                     '--root', str(root), '--destination', str(root / 'public'),
                                     '--shell', 'tauri', '--source-sha', self.source_sha],
                                    capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ios_batch_runner_reported_failure', result.stderr)
            self.assertEqual({path.name for path in (root / 'public').iterdir()}, {'result.json'})

    def test_legacy_masked_preconnect_is_optional_and_requires_its_own_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.evidence(root)
            data = (root / 'key-change-review.png').read_bytes()
            (root / 'preconnect.png').write_bytes(data)
            destination = root / 'without-legacy'
            batch.publish_evidence(root, destination, shell='flutter', source_sha=self.source_sha)
            self.assertFalse((destination / 'preconnect.png').exists())
            report['artifacts']['preconnect.png'] = hashlib.sha256(data).hexdigest()
            (root / 'result.json').write_text(json.dumps(report))
            destination = root / 'with-legacy'
            batch.publish_evidence(root, destination, shell='flutter', source_sha=self.source_sha)
            self.assertEqual((destination / 'preconnect.png').read_bytes(), data)

    def test_success_rejects_ocr_failure_and_non_png_bytes(self):
        for corrupt in ('proof', 'format'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                report = self.evidence(root)
                if corrupt == 'proof':
                    path = root / 'ordinary-terminal-ocr.json'
                    proof = json.loads(path.read_text())
                    proof['proofSequenceVisible'] = False
                    path.write_text(json.dumps(proof))
                else:
                    data = b'not a PNG, even though its digest is bound'
                    (root / 'ordinary-terminal.png').write_bytes(data)
                    report['artifacts']['ordinary-terminal.png'] = hashlib.sha256(data).hexdigest()
                    (root / 'result.json').write_text(json.dumps(report))
                with self.assertRaises(batch.BatchFailure):
                    self.publish(root, root / 'public')
                self.assertFalse((root / 'public/ordinary-terminal.png').exists())

    def test_symlinked_capture_is_never_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.evidence(root)
            target = root / 'ordinary-terminal.png'
            other = root / 'external.png'
            target.rename(other)
            target.symlink_to(other)
            with self.assertRaisesRegex(batch.BatchFailure, 'file_invalid'):
                self.publish(root, root / 'public')


class SimulatorPackageTests(unittest.TestCase):
    def make_app(self, root, archive='ordinary.xcarchive', **changes):
        app = root / archive / 'Products/Applications/Pocket.app'
        app.mkdir(parents=True)
        info = {'CFBundleIdentifier': 'dev.herdrpocket.tauriprobe',
                'CFBundleExecutable': 'Pocket', 'CFBundlePackageType': 'APPL',
                'CFBundleSupportedPlatforms': ['iPhoneSimulator']}
        info.update(changes)
        (app / 'Info.plist').write_bytes(plistlib.dumps(info))
        (app / 'Pocket').write_bytes(b'isolated executable fixture')
        (app / 'Pocket').chmod(0o755)
        return app

    def command(self, arch='arm64', platform='IOSSIMULATOR'):
        return Mock(side_effect=[subprocess.CompletedProcess([], 0, arch + '\n', ''),
                                 subprocess.CompletedProcess([], 0, f'  platform {platform}\n', '')])

    def test_selects_the_archive_application_and_checks_the_actual_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = self.make_app(root).resolve()
            command = self.command()
            self.assertEqual(batch.select_simulator_app(root, command=command), app)
            self.assertEqual(command.call_args_list[0].args[0], ['xcrun', 'lipo', '-archs', str(app / 'Pocket')])
            self.assertEqual(command.call_args_list[1].args[0], ['xcrun', 'vtool', '-show-build', str(app / 'Pocket')])

    def test_rejects_device_archive_even_when_its_executable_is_arm64(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_app(root, CFBundleSupportedPlatforms=['iPhoneOS'])
            command = self.command()
            with self.assertRaisesRegex(batch.BatchFailure, 'not_simulator'):
                batch.select_simulator_app(root, command=command)
            command.assert_not_called()

    def test_rejects_duplicate_archives_instead_of_picking_the_first(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_app(root)
            self.make_app(root, 'stale.xcarchive')
            with self.assertRaisesRegex(batch.BatchFailure, 'not_unique'):
                batch.select_simulator_app(root, command=self.command())

    def test_rejects_mislabeled_platform_or_architecture_in_the_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_app(root)
            for command in [self.command(platform='IOS'), self.command(arch='x86_64')]:
                with self.subTest(command=command):
                    with self.assertRaisesRegex(batch.BatchFailure, 'not_arm64_simulator'):
                        batch.select_simulator_app(root, command=command)

    def test_rejects_missing_or_symlinked_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = self.make_app(root)
            binary = app / 'Pocket'
            binary.unlink()
            with self.assertRaisesRegex(batch.BatchFailure, 'executable_missing'):
                batch.select_simulator_app(root, command=self.command())
            other = root / 'other'
            other.write_bytes(b'other')
            binary.symlink_to(other)
            with self.assertRaisesRegex(batch.BatchFailure, 'executable_missing'):
                batch.select_simulator_app(root, command=self.command())


if __name__ == '__main__':
    unittest.main()
