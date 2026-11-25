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
    @staticmethod
    def job(workflow, client):
        start = workflow.index(f'  {client}-ordinary-ssh-ios:')
        end = workflow.find('\n  tauri-ordinary-ssh-ios:', start + 1)
        return workflow[start:end if end != -1 else len(workflow)]

    def test_flutter_encrypted_key_ref_exclusively_guards_two_commands_and_one_new_test(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/direct-ssh-ios.yml').read_text()
        flutter, tauri = self.job(workflow, 'flutter'), self.job(workflow, 'tauri')
        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-flutter-only-encrypted-key-'
        self.assertIn(f"FLUTTER_INCLUDE_ENCRYPTED_KEY: ${{{{ startsWith(github.ref, '{prefix}') }}}}", flutter)
        self.assertEqual(flutter.count('options+=(--include-encrypted-key)'), 2)
        self.assertIn('flutter_direct_ssh_ios.py', flutter)
        self.assertIn('ios_direct_ssh_batch.py publish', flutter)
        self.assertIn("-p 'test_flutter_ios_encrypted_key.py'", flutter)
        self.assertIn('encrypted-key-terminal.png', flutter)
        self.assertIn('encrypted-key-terminal-ocr.json', flutter)
        self.assertNotIn('FLUTTER_INCLUDE_ENCRYPTED_KEY', tauri)
        self.assertNotIn('test_flutter_ios_encrypted_key.py', tauri)
        self.assertNotIn('--include-encrypted-key', tauri)
        self.assertNotIn('encrypted-key-terminal', tauri)

    def test_flutter_encrypted_rotation_option_is_not_shared_with_tauri(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/direct-ssh-ios.yml').read_text()
        flutter, tauri = self.job(workflow, 'flutter'), self.job(workflow, 'tauri')
        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-flutter-only-encrypted-rotation-'
        self.assertIn(f"FLUTTER_ENCRYPTED_ROTATION: ${{{{ startsWith(github.ref, '{prefix}') }}}}", flutter)
        self.assertEqual(flutter.count('options+=(--encrypted-key-rotation)'), 2)
        for name in (batch.ENCRYPTED_ROTATION_REVIEW, *batch.ENCRYPTED_ROTATION_PROOF,
                     *batch.ENCRYPTED_ROTATION_PROOF.values()):
            self.assertIn(name, flutter)
            self.assertNotIn(name, tauri)

    def test_branch_routes_both_clients_or_a_single_requested_client(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/direct-ssh-ios.yml').read_text()
        routes = {}
        manual = {}
        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-'
        combo = prefix + 'flutter-only-encrypted-rotation-'
        tauri_key = prefix + 'tauri-only-encrypted-manual-'
        for client in ('flutter', 'tauri'):
            job = re.search(rf'(?ms)^  {client}-ordinary-ssh-ios:\n    if: (.*?)^    runs-on:', workflow)
            self.assertIsNotNone(job)
            routes[client] = []
            for clause in job[1].removeprefix('>-\n').split('&&'):
                gated = next((branch for branch in (combo, tauri_key) if clause.strip() ==
                              f"(!startsWith(github.ref, '{branch}') || github.event_name == 'workflow_dispatch')"), None)
                if gated:
                    manual[client] = gated
                    continue
                match = re.fullmatch(r"(!?)startsWith\(github\.ref, '([^']+)'\)", clause.strip())
                self.assertIsNotNone(match, 'expected a branch-prefix condition')
                routes[client].append(match.groups())

        for ref, event, expected in (
            (prefix + 'both-r1', 'push', {'flutter', 'tauri'}),
            (prefix + 'flutter-only-r1', 'push', {'flutter'}),
            (prefix + 'tauri-only-r1', 'push', {'tauri'}),
            (prefix + 'flutter-only-encrypted-key-r1', 'push', {'flutter'}),
            (combo + 'r1', 'push', set()),
            (combo + 'r1', 'workflow_dispatch', {'flutter'}),
            (tauri_key + 'r1', 'push', set()),
            (tauri_key + 'r1', 'workflow_dispatch', {'tauri'}),
            ('refs/heads/main', 'workflow_dispatch', set()),
            ('refs/tags/codex/acceptance/direct-ssh-ios-r1', 'workflow_dispatch', set()),
        ):
            with self.subTest(ref=ref):
                selected = {client for client, clauses in routes.items()
                            if all(ref.startswith(branch) != bool(negated) for negated, branch in clauses)
                            and (client not in manual or not ref.startswith(manual[client]) or event == 'workflow_dispatch')}
                self.assertEqual(selected, expected)

    def test_tauri_manual_key_ref_routes_the_runner_and_publisher_together(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/direct-ssh-ios.yml').read_text()
        flutter, tauri = self.job(workflow, 'flutter'), self.job(workflow, 'tauri')
        prefix = 'refs/heads/codex/acceptance/direct-ssh-ios-tauri-only-encrypted-manual-'
        self.assertIn(f"TAURI_ENCRYPTED_KEY_MANUAL: ${{{{ startsWith(github.ref, '{prefix}') }}}}", tauri)
        self.assertEqual(tauri.count('options+=(--encrypted-key-manual-only)'), 2)
        self.assertNotIn('--encrypted-key-manual-only', flutter)
        for name in (*batch.TAURI_MANUAL_KEY_PROOF, *batch.TAURI_MANUAL_KEY_PROOF.values()):
            self.assertIn(name, tauri)
            self.assertNotIn(name, flutter)


class PublicEvidenceTests(unittest.TestCase):
    source_sha = 'a' * 40

    @staticmethod
    def encrypted_key_case():
        attempts = dict.fromkeys(('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests',
                                  'inputBytes', 'outputBytes'), 0)
        return {'status': 'passed', 'fingerprintReviewed': True, 'terminalInputReceived': True,
                'disconnected': True, 'returnedHome': True,
                'wrongPassphrase': {'rejected': True, 'peer': {'id': 1, 'hostKey': 'A',
                    'closed': True, 'handshakeCompleted': True, **attempts}},
                'modeSwitch': {'passwordToKeyCleared': True, 'keyToPasswordCleared': True, 'sameTrust': True},
                'acceptedSession': {'id': 2, 'hostKey': 'A', 'authAttempts': 1, 'authSuccesses': 1,
                    'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9, 'outputBytes': 12,
                    'markerReceived': True, 'singleMarkerLineExact': True, 'sessionClosed': True, 'closed': True},
                'authenticationMethod': 'publickey', 'peerClosedBeforeDriverExit': True}

    def evidence(self, root, *, status='passed', encrypted_rotation=False, tauri_manual_key=False):
        from PIL import Image
        artifacts = {}
        if tauri_manual_key:
            proofs = batch.TAURI_MANUAL_KEY_PROOF
            names = set(proofs) | {batch.TAURI_MANUAL_KEY_HOME}
        elif encrypted_rotation:
            proofs = batch.ENCRYPTED_ROTATION_PROOF
            names = {batch.ENCRYPTED_ROTATION_REVIEW, *proofs}
        else:
            proofs = batch.TERMINAL_PROOFS
            names = batch.REQUIRED_IMAGES
        for index, name in enumerate(sorted(names)):
            stream = io.BytesIO()
            Image.new('RGB', (8, 8), (index * 30, 40, 60)).save(stream, format='PNG')
            data = stream.getvalue()
            (root / name).write_bytes(data)
            artifacts[name] = hashlib.sha256(data).hexdigest()
            if name in proofs:
                (root / proofs[name]).write_text(json.dumps({
                    'imageSha256': artifacts[name], 'markerVisible': True,
                    'tokenVisible': True, 'proofSequenceVisible': True}))
        report = {'sourceSHA': self.source_sha, 'status': status, 'artifacts': artifacts}
        (root / 'result.json').write_text(json.dumps(report))
        return report

    def tauri_manual_key_report(self, root):
        report = self.evidence(root, tauri_manual_key=True)
        case = self.encrypted_key_case()
        del case['modeSwitch']
        case.update(credentialEntry='nativeTypeText', wrongPemExact=True, correctPemExact=True,
                    wrongPemReopened=True, correctPemReopened=True, wrongPassphraseObscured=True,
                    correctPassphraseObscured=True, credentialsCleared=True)
        probe = {**case['wrongPassphrase']['peer'], 'markerReceived': False, 'authAccepted': False,
                 'sessionClosed': False, 'handshakeCompleted': False}
        case['initialProbe'] = probe
        case['wrongPassphrase'].update(peer={**probe, 'id': 2, 'handshakeCompleted': True}, credentialsCleared=True)
        case['acceptedSession'].update(id=3, authAttempts=2, authAccepted=True, handshakeCompleted=True)
        terminal, criteria = next(iter(batch.TAURI_MANUAL_KEY_PROOF.items()))
        case['terminalScreenshot'] = {'imageFile': terminal, 'imageSha256': report['artifacts'][terminal],
            'criteriaFile': criteria, 'criteriaSha256': hashlib.sha256((root / criteria).read_bytes()).hexdigest(),
            'systemCapture': 'XCUIScreen.main', 'targetVisible': True, 'noCredentialsVisible': True}
        report.update(scope='owned_loopback_ordinary_ssh_encrypted_key_manual', client='tauri', platform='ios-simulator',
                      lastCompletedStage='encrypted_key_returned_home', homeEntry={'encryptedKey': {}},
                      cases={'ordinary': {'status': 'not_run'}, 'keyChange': {'status': 'not_run'}, 'encryptedKey': case},
                      cleanup={'simulatorDeleted': True, 'fixturesClosed': True, 'privateFilesRemoved': True,
                               'encryptedSecretsCleared': True, 'rawLogsUploaded': False})
        home = batch.TAURI_MANUAL_KEY_HOME
        report['shortcutCapture'] = {'imageFile': home, 'imageSha256': report['artifacts'][home],
            'systemCapture': 'XCUIScreen.main', 'peerConnections': 0, 'screenPixels': [8, 8]}
        (root / 'result.json').write_text(json.dumps(report))
        return report

    def test_tauri_manual_key_requires_distinct_preauth_phases_and_bound_private_safe_terminal_proof(self):
        mutations = (
            lambda report, case: case.update(credentialEntry='systemEditMenu'),
            lambda report, case: case['initialProbe'].update(authAttempts=1),
            lambda report, case: case['wrongPassphrase']['peer'].update(authAttempts=1),
            lambda report, case: case['wrongPassphrase']['peer'].update(handshakeCompleted=False),
            lambda report, case: case['acceptedSession'].update(authSuccesses=2),
            lambda report, case: case.update(peerClosedBeforeDriverExit=False),
            lambda report, case: case.update(wrongPemExact=False),
            lambda report, case: case.update(correctPemReopened=False),
            lambda report, case: report['cases']['ordinary'].update(status='passed'),
            lambda report, case: report['cleanup'].update(encryptedSecretsCleared=False),
            lambda report, case: case['terminalScreenshot'].update(noCredentialsVisible=False),
            lambda report, case: case['terminalScreenshot'].update(criteriaSha256='b' * 64),
            lambda report, case: report['shortcutCapture'].update(peerConnections=1),
            lambda report, case: report['artifacts'].pop(batch.TAURI_MANUAL_KEY_HOME),
        )
        for mutation in (None, *mutations):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'source'
                root.mkdir()
                report = self.tauri_manual_key_report(root)
                destination = Path(directory) / 'published'
                options = {'shell': 'tauri', 'source_sha': self.source_sha, 'encrypted_key_manual_only': True}
                if mutation:
                    mutation(report, report['cases']['encryptedKey'])
                    (root / 'result.json').write_text(json.dumps(report))
                    with self.assertRaises(batch.BatchFailure):
                        batch.publish_evidence(root, destination, **options)
                    self.assertEqual({p.name for p in destination.iterdir()}, {'result.json'})
                else:
                    published = batch.publish_evidence(root, destination, **options)
                    self.assertEqual(published, {'result.json', batch.TAURI_MANUAL_KEY_HOME,
                                                 *batch.TAURI_MANUAL_KEY_PROOF, *batch.TAURI_MANUAL_KEY_PROOF.values()})

    def test_tauri_manual_key_failure_can_publish_only_the_bound_preinput_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            report = self.tauri_manual_key_report(root)
            home = batch.TAURI_MANUAL_KEY_HOME
            report.update(status='failed', artifacts={home: report['artifacts'][home]})
            (root / 'result.json').write_text(json.dumps(report))
            options = {'shell': 'tauri', 'source_sha': self.source_sha, 'encrypted_key_manual_only': True}
            self.assertEqual(batch.publish_evidence(root, Path(directory) / 'safe', **options), {'result.json', home})
            report['shortcutCapture']['screenPixels'] = [9, 8]
            (root / 'result.json').write_text(json.dumps(report))
            self.assertEqual(batch.publish_evidence(root, Path(directory) / 'mismatch', **options), {'result.json'})

    def encrypted_rotation_report(self, root):
        report = self.evidence(root, encrypted_rotation=True)
        case = self.encrypted_key_case()
        probe = {**case.pop('wrongPassphrase')['peer'], 'markerReceived': False,
                 'authAccepted': False, 'sessionClosed': False}
        case['acceptedSession'].update(id=4, hostKey='B')
        case['protocolRef'] = 'encryptedRotationProtocol'
        case['checkpoints'] = {'review': probe, 'rejected': {'stage': 2, 'connections': 2, 'connectionsClosed': True},
            'cancelled': {'stage': 2, 'connections': 2, 'connectionsClosed': True},
            'reprobed': {'stage': 3, 'connections': 3, 'connectionsClosed': True}}
        case['device'] = dict.fromkeys(('sameTarget', 'oldFingerprintMatchedIndependentA',
            'changedFingerprintMatchedIndependentB', 'rejectedBeforeAuthentication', 'reviewNavigationBlocked',
            'cancelKeepsOldTrust', 'credentialsLockedBeforeApproval', 'noAutomaticConnection',
            'freshProbeMatchedIndependentB', 'explicitRotatedTrustRequired', 'privateKeyPasted',
            'passphraseObscured', 'privateInputRemoved', 'clipboardCleared', 'credentialsCleared'), True)
        image, proof = next(iter(batch.ENCRYPTED_ROTATION_PROOF.items()))
        case['terminalScreenshot'] = {'imageFile': image, 'imageSha256': report['artifacts'][image],
            'criteriaFile': proof, 'criteriaSha256': hashlib.sha256((root / proof).read_bytes()).hexdigest()}
        review = batch.ENCRYPTED_ROTATION_REVIEW
        case['reviewScreenshot'] = {'imageFile': review, 'imageSha256': report['artifacts'][review],
                                    'purpose': 'design-review-no-ocr'}
        events = [probe, {**probe, 'id': 2, 'hostKey': 'B'}, {**probe, 'id': 3, 'hostKey': 'B'},
                  {**case['acceptedSession'], 'authAccepted': True}]
        cleanup = dict.fromkeys(('simulatorDeleted', 'fixtureClosed', 'flutterToolStopped', 'appRemoved',
                                 'privateRemoved', 'encryptedFixtureClosed', 'encryptedSecretsCleared'), True)
        report.update(kind='flutter-ios-simulator-encrypted-key-rotation', cases={'encryptedKeyRotation': case},
            encryptedRotationProtocol={'connections': 4, 'connectionsClosed': True, 'connectionEvents': events},
            cleanup={**cleanup, 'rawLogsUploaded': False},
            screens={'encrypted-rotation': {'accepted': True, 'targetEvidence': {'targetVisible': True}}})
        (root / 'result.json').write_text(json.dumps(report))
        return report

    def test_encrypted_rotation_publication_requires_exact_combination_and_separate_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.encrypted_rotation_report(root)
            def publish(name, *, mode=True):
                return batch.publish_evidence(root, root / name, shell='flutter', source_sha=self.source_sha,
                                              encrypted_rotation=mode)
            self.assertEqual(publish('verified'), {'result.json', *report['artifacts'], *batch.ENCRYPTED_ROTATION_PROOF.values()})
            with self.assertRaisesRegex(batch.BatchFailure, 'artifact_manifest_invalid'):
                publish('normal-mode', mode=False)
            for key, bad, code in ((('encryptedRotationProtocol', 'connectionEvents', 1, 'authAttempts'), 1, 'case_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'checkpoints', 'cancelled', 'connections'), 3, 'case_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'acceptedSession', 'inputBytes'), 18, 'case_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'acceptedSession', 'singleMarkerLineExact'), False, 'case_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'protocolRef'), 'encryptedProtocol', 'case_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'terminalScreenshot', 'imageFile'), 'encrypted-key-terminal.png', 'artifact_ref_invalid'),
                                   (('cases', 'encryptedKeyRotation', 'terminalScreenshot', 'criteriaSha256'), '0' * 64, 'criteria_hash_mismatch'),
                                   (('cleanup', 'encryptedSecretsCleared'), False, 'case_invalid')):
                parent = report
                for part in key[:-1]:
                    parent = parent[part]
                old = parent[key[-1]]
                parent[key[-1]] = bad
                (root / 'result.json').write_text(json.dumps(report))
                with self.subTest(key=key), self.assertRaisesRegex(batch.BatchFailure, code):
                    publish(code + '-' + key[-1])
                parent[key[-1]] = old

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

    def test_encrypted_key_publication_is_opt_in_and_requires_completed_case_and_bound_ocr(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.evidence(root)
            def publish(name, *, include=True, shell='flutter'):
                return batch.publish_evidence(root, root / name, shell=shell, source_sha=self.source_sha,
                                              include_encrypted_key=include)

            with self.assertRaisesRegex(batch.BatchFailure, 'required_images_missing'):
                publish('missing-image')
            png, proof = next(iter(batch.ENCRYPTED_KEY_PROOF.items()))
            report['artifacts'][png] = report['artifacts']['ordinary-terminal.png']
            (root / 'result.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(batch.BatchFailure, 'encrypted_key_image_reused'):
                publish('password-image-replay')
            Image.new('RGB', (8, 8), (170, 40, 60)).save(root / png, format='PNG')
            data = (root / png).read_bytes()
            report['artifacts'][png] = hashlib.sha256(data).hexdigest()
            criteria = json.loads((root / 'ordinary-terminal-ocr.json').read_text()) | {'imageSha256': report['artifacts'][png]}
            (root / proof).write_text(json.dumps(criteria))
            (root / 'result.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(batch.BatchFailure, 'artifact_manifest_invalid'):
                publish('unexpected', include=False)
            with self.assertRaisesRegex(batch.BatchFailure, 'encrypted_key_case_missing'):
                publish('missing-case')
            with self.assertRaisesRegex(batch.BatchFailure, 'source_invalid'):
                publish('tauri-opt-in', shell='tauri')

            report['cases'] = {'encryptedKey': self.encrypted_key_case()}
            (root / 'result.json').write_text(json.dumps(report))
            expected = {'result.json', *report['artifacts'], *batch.TERMINAL_PROOFS.values(), proof}
            self.assertEqual(publish('completed'), expected)
            (root / 'preconnect.png').write_bytes(data)
            report['artifacts']['preconnect.png'] = report['artifacts'][png]
            (root / 'result.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(batch.BatchFailure, 'ios_batch_encrypted_key_image_reused'):
                publish('preconnect-image-replay')
            del report['artifacts']['preconnect.png']
            (root / 'preconnect.png').unlink()
            (root / 'result.json').write_text(json.dumps(report))
            (root / proof).unlink()
            with self.assertRaisesRegex(batch.BatchFailure, 'file_invalid'):
                publish('missing-ocr')

    def test_flutter_publication_rejects_missing_trust_cleanup_and_replayed_actions(self):
        missing = object()
        for path, value in ((('modeSwitch', 'sameTrust'), 1), (('modeSwitch', 'keyToPasswordCleared'), False),
                (('wrongPassphrase', 'peer', 'authAttempts'), 1), (('wrongPassphrase', 'peer', 'id'), True),
                (('wrongPassphrase', 'peer', 'handshakeCompleted'), False),
                (('wrongPassphrase', 'peer', 'handshakeCompleted'), missing),
                (('acceptedSession', 'id'), 3), (('acceptedSession', 'hostKey'), 'B'),
                (('acceptedSession', 'authSuccesses'), True), (('acceptedSession', 'ptyRequests'), 2),
                (('acceptedSession', 'shellRequests'), 2), (('acceptedSession', 'inputBytes'), 18),
                (('acceptedSession', 'singleMarkerLineExact'), False), (('acceptedSession', 'outputBytes'), 0),
                (('peerClosedBeforeDriverExit',), False), (('returnedHome',), False)):
            with self.subTest(path=path, value=value):
                case = self.encrypted_key_case()
                target = case
                for key in path[:-1]:
                    target = target[key]
                if value is missing:
                    del target[path[-1]]
                else:
                    target[path[-1]] = value
                self.assertFalse(batch.encrypted_key_case_valid(case))

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
