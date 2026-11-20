#!/usr/bin/env python3
"""CI-only package/evidence checks for the two-shell iOS acceptance batch.

This does not drive SSH, evaluate terminal pixels, or establish device support.
The corresponding simulator runners own those checks and their sanitization.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess


class BatchFailure(RuntimeError):
    pass


TERMINAL_PROOFS = {'ordinary-terminal.png': 'ordinary-terminal-ocr.json',
                   'key-change-terminal.png': 'key-change-terminal-ocr.json'}
TAURI_MANUAL_KEY_PROOF = {'tauri-manual-key-terminal.png': 'tauri-manual-key-terminal-ocr.json'}
TAURI_MANUAL_KEY_HOME = 'tauri-manual-key-empty-home.png'
ENCRYPTED_KEY_PROOF = {'encrypted-key-terminal.png': 'encrypted-key-terminal-ocr.json'}
ENCRYPTED_ROTATION_PROOF = {'encrypted-rotation-terminal.png': 'encrypted-rotation-terminal-ocr.json'}
ENCRYPTED_ROTATION_REVIEW = 'encrypted-rotation-review.png'
REQUIRED_IMAGES = {*TERMINAL_PROOFS, 'key-change-review.png'}


def read_public_file(root, name, limit):
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise BatchFailure('ios_batch_public_file_invalid')
    return path.read_bytes()


def read_public_json(root, name):
    data = read_public_file(root, name, 1_000_000)
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
    except (UnicodeError, ValueError):
        raise BatchFailure('ios_batch_public_json_invalid') from None
    return data, value


def encrypted_key_case_valid(case):
    if (not isinstance(case, dict) or case.get('status') != 'passed'
            or not all(case.get(key) is True for key in
                       ('fingerprintReviewed', 'terminalInputReceived', 'disconnected', 'returnedHome'))):
        return False
    wrong = case.get('wrongPassphrase')
    peer = wrong.get('peer') if isinstance(wrong, dict) else None
    if (not isinstance(wrong, dict) or wrong.get('rejected') is not True or not isinstance(peer, dict)
            or peer.get('closed') is not True
            or any(type(peer.get(key)) is not int or peer[key] != 0 for key in
                   ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes'))):
        return False
    # Flutter rejects the wrong passphrase locally: the only peer event is the original host-key probe.
    accepted = case.get('acceptedSession')
    counts = {'id': 2, 'authAttempts': 1, 'authSuccesses': 1, 'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9}
    return (type(peer.get('id')) is int and peer['id'] == 1 and peer.get('hostKey') == 'A'
            and isinstance(case.get('modeSwitch'), dict) and all(case['modeSwitch'].get(key) is True for key in
                ('passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'))
            and isinstance(accepted, dict) and accepted.get('hostKey') == 'A'
            and all(type(accepted.get(key)) is int and accepted[key] == count for key, count in counts.items())
            and type(accepted.get('outputBytes')) is int and accepted['outputBytes'] > 0
            and all(accepted.get(key) is True for key in ('markerReceived', 'singleMarkerLineExact', 'sessionClosed', 'closed'))
            and case.get('authenticationMethod') == 'publickey' and case.get('peerClosedBeforeDriverExit') is True)


def encrypted_rotation_case_valid(report):
    cases = report.get('cases')
    case = cases.get('encryptedKeyRotation') if isinstance(cases, dict) else None
    peer = report.get('encryptedRotationProtocol')
    if (report.get('kind') != 'flutter-ios-simulator-encrypted-key-rotation' or
            not isinstance(case, dict) or set(cases) != {'encryptedKeyRotation'} or case.get('status') != 'passed'
            or case.get('protocolRef') != 'encryptedRotationProtocol'
            or case.get('authenticationMethod') != 'publickey' or 'wrongPassphrase' in case
            or not all(case.get(key) is True for key in ('fingerprintReviewed', 'terminalInputReceived',
                        'disconnected', 'returnedHome', 'peerClosedBeforeDriverExit'))
            or not isinstance(peer, dict) or type(peer.get('connections')) is not int or peer['connections'] != 4
            or peer.get('connectionsClosed') is not True):
        return False
    checkpoints = case.get('checkpoints')
    modes = case.get('modeSwitch')
    device = case.get('device')
    cleanup = report.get('cleanup')
    screens = report.get('screens')
    screen = screens.get('encrypted-rotation') if isinstance(screens, dict) else None
    if (not isinstance(checkpoints, dict) or tuple(checkpoints) != ('review', 'rejected', 'cancelled', 'reprobed')
            or not isinstance(modes, dict) or not all(modes.get(key) is True for key in
                ('passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'))
            or not isinstance(device, dict) or not all(device.get(key) is True for key in
                ('sameTarget', 'oldFingerprintMatchedIndependentA', 'changedFingerprintMatchedIndependentB',
                 'rejectedBeforeAuthentication', 'reviewNavigationBlocked', 'cancelKeepsOldTrust',
                 'credentialsLockedBeforeApproval', 'noAutomaticConnection', 'freshProbeMatchedIndependentB',
                 'explicitRotatedTrustRequired', 'privateKeyPasted', 'passphraseObscured',
                 'privateInputRemoved', 'clipboardCleared', 'credentialsCleared'))
            or not isinstance(cleanup, dict) or not all(cleanup.get(key) is True for key in
                ('simulatorDeleted', 'fixtureClosed', 'flutterToolStopped', 'appRemoved', 'privateRemoved',
                 'encryptedFixtureClosed', 'encryptedSecretsCleared')) or cleanup.get('rawLogsUploaded') is not False
            or not isinstance(screen, dict) or set(screens) != {'encrypted-rotation'} or screen.get('accepted') is not True
            or not isinstance(screen.get('targetEvidence'), dict) or screen['targetEvidence'].get('targetVisible') is not True):
        return False
    events = peer.get('connectionEvents')
    if not isinstance(events, list) or len(events) != 4:
        return False
    zero = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')
    for index, (event, key) in enumerate(zip(events, 'ABBB'), 1):
        if (not isinstance(event, dict) or type(event.get('id')) is not int or event['id'] != index
                or event.get('hostKey') != key or event.get('closed') is not True):
            return False
        if index < 4 and (any(type(event.get(name)) is not int or event[name] != 0 for name in zero)
                          or any(event.get(name) is not False for name in ('authAccepted', 'markerReceived', 'sessionClosed'))):
            return False
    probe = checkpoints['review']
    probe_fields = {'id', 'hostKey', 'closed', 'authAccepted', 'markerReceived', 'sessionClosed', *zero}
    if (not isinstance(probe, dict) or set(probe) != probe_fields or
            any(type(probe[name]) is not type(events[0][name]) or probe[name] != events[0][name] for name in probe_fields)
            or checkpoints['rejected'] != checkpoints['cancelled']):
        return False
    for phase, count in (('rejected', 2), ('cancelled', 2), ('reprobed', 3)):
        checkpoint = checkpoints[phase]
        if (not isinstance(checkpoint, dict) or type(checkpoint.get('stage')) is not int or checkpoint['stage'] != count
                or type(checkpoint.get('connections')) is not int or checkpoint['connections'] != count
                or checkpoint.get('connectionsClosed') is not True):
            return False
    accepted = case.get('acceptedSession')
    counts = {'id': 4, 'authAttempts': 1, 'authSuccesses': 1, 'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9}
    return (isinstance(accepted, dict) and accepted.get('hostKey') == 'B'
            and all(type(accepted.get(name)) is int and accepted[name] == expected for name, expected in counts.items())
            and type(accepted.get('outputBytes')) is int and accepted['outputBytes'] > 0
            and all(accepted.get(name) is True for name in ('markerReceived', 'singleMarkerLineExact', 'sessionClosed', 'closed'))
            and events[3].get('authAccepted') is True
            and all(type(events[3].get(name)) is type(value) and events[3][name] == value
                    for name, value in accepted.items()))


def tauri_manual_key_valid(report):
    cases = report.get('cases')
    cleanup = report.get('cleanup')
    home = report.get('homeEntry')
    if (report.get('scope') != 'owned_loopback_ordinary_ssh_encrypted_key_manual'
            or report.get('client') != 'tauri' or report.get('platform') != 'ios-simulator'
            or report.get('lastCompletedStage') != 'encrypted_key_returned_home'
            or not isinstance(cases, dict) or set(cases) != {'ordinary', 'keyChange', 'encryptedKey'}
            or any(cases[name] != {'status': 'not_run'} for name in ('ordinary', 'keyChange'))
            or not isinstance(home, dict) or set(home) != {'encryptedKey'}
            or not isinstance(cleanup, dict) or cleanup.get('rawLogsUploaded') is not False
            or any(cleanup.get(name) is not True for name in
                   ('simulatorDeleted', 'fixturesClosed', 'privateFilesRemoved', 'encryptedSecretsCleared'))):
        return False
    case = cases['encryptedKey']
    if (not isinstance(case, dict) or case.get('credentialEntry') != 'nativeTypeText'
            or case.get('status') != 'passed' or case.get('authenticationMethod') != 'publickey'
            or any(case.get(name) is not True for name in ('fingerprintReviewed', 'wrongPemExact', 'correctPemExact',
                   'wrongPemReopened', 'correctPemReopened', 'wrongPassphraseObscured', 'correctPassphraseObscured',
                   'terminalInputReceived', 'disconnected',
                   'credentialsCleared', 'peerClosedBeforeDriverExit', 'returnedHome'))):
        return False
    wrong = case.get('wrongPassphrase')
    if (not isinstance(wrong, dict) or wrong.get('rejected') is not True or wrong.get('credentialsCleared') is not True):
        return False
    empty_counters = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')
    for index, event in enumerate((case.get('initialProbe'), wrong.get('peer')), 1):
        if (not isinstance(event, dict) or type(event.get('id')) is not int or event['id'] != index
                or event.get('hostKey') != 'A' or event.get('closed') is not True
                or (index == 2 and event.get('handshakeCompleted') is not True)
                or any(type(event.get(name)) is not int or event[name] != 0 for name in empty_counters)
                or any(event.get(name) is not False for name in ('authAccepted', 'sessionClosed', 'markerReceived'))):
            return False
    final = case.get('acceptedSession')
    counters = {'id': 3, 'authAttempts': 2, 'authSuccesses': 1, 'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9}
    return (isinstance(final, dict) and final.get('hostKey') == 'A'
            and all(type(final.get(name)) is int and final[name] == count for name, count in counters.items())
            and type(final.get('outputBytes')) is int and final['outputBytes'] > 0
            and all(final.get(name) is True for name in ('handshakeCompleted', 'authAccepted', 'closed',
                                                         'sessionClosed', 'markerReceived', 'singleMarkerLineExact')))


def publish_evidence(root, destination, *, shell, source_sha, include_encrypted_key=False,
                     encrypted_rotation=False, encrypted_key_manual_only=False):
    """Copy only this run's bound public files; leave SSH/OCR to the runners.

    Failed runs may retain an already completed scene. A passed result must
    supply its selected scenario's system captures and accepted OCR reports.
    Independent encrypted authentication extends the standard batch; encrypted
    rotation publishes its own review and terminal evidence.
    Even an incomplete passed result retains its sanitized result for diagnosis.
    """
    from PIL import Image
    root, destination = Path(root), Path(destination)
    if root.is_symlink() or not root.is_dir() or destination.exists() or destination.is_symlink():
        raise BatchFailure('ios_batch_public_directory_invalid')
    if (shell not in ('flutter', 'tauri') or ((include_encrypted_key or encrypted_rotation) and shell != 'flutter')
            or (encrypted_key_manual_only and shell != 'tauri')
            or sum((include_encrypted_key, encrypted_rotation, encrypted_key_manual_only)) > 1
            or not re.fullmatch(r'[0-9a-f]{40}', source_sha)):
        raise BatchFailure('ios_batch_source_invalid')
    raw, report = read_public_json(root, 'result.json')
    if report.get('sourceSHA') != source_sha or report.get('status') not in ('passed', 'failed'):
        raise BatchFailure('ios_batch_result_source_or_status_invalid')
    destination.mkdir(parents=True)
    (destination / 'result.json').write_bytes(raw)
    passed = report['status'] == 'passed'
    artifacts = report.get('artifacts', {})
    if encrypted_key_manual_only:
        terminal_proofs = TAURI_MANUAL_KEY_PROOF
        required = allowed = set(terminal_proofs) | {TAURI_MANUAL_KEY_HOME}
    elif encrypted_rotation:
        terminal_proofs = ENCRYPTED_ROTATION_PROOF
        required = allowed = {ENCRYPTED_ROTATION_REVIEW, *terminal_proofs}
    else:
        terminal_proofs = TERMINAL_PROOFS | (ENCRYPTED_KEY_PROOF if include_encrypted_key else {})
        required = REQUIRED_IMAGES | terminal_proofs.keys()
        allowed = required | ({'preconnect.png'} if shell == 'flutter' else set())
    if (not isinstance(artifacts, dict) or set(artifacts) - allowed or
            any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                for value in artifacts.values())):
        raise BatchFailure('ios_batch_artifact_manifest_invalid')
    if encrypted_key_manual_only and TAURI_MANUAL_KEY_HOME in artifacts:
        home_capture = report.get('shortcutCapture')
        if (report.get('scope') != 'owned_loopback_ordinary_ssh_encrypted_key_manual'
                or report.get('client') != 'tauri' or report.get('platform') != 'ios-simulator'
                or not isinstance(home_capture, dict)
                or home_capture.get('imageFile') != TAURI_MANUAL_KEY_HOME
                or home_capture.get('imageSha256') != artifacts[TAURI_MANUAL_KEY_HOME]
                or home_capture.get('systemCapture') != 'XCUIScreen.main'
                or type(home_capture.get('peerConnections')) is not int or home_capture['peerConnections'] != 0):
            raise BatchFailure('ios_batch_tauri_manual_key_home_ref_invalid')
    if passed and not required.issubset(artifacts):
        raise BatchFailure('ios_batch_required_images_missing')
    if passed and encrypted_key_manual_only:
        if not tauri_manual_key_valid(report):
            raise BatchFailure('ios_batch_tauri_manual_key_case_invalid')
        terminal, criteria = next(iter(terminal_proofs.items()))
        capture = report['cases']['encryptedKey'].get('terminalScreenshot')
        if (not isinstance(capture, dict) or capture.get('imageFile') != terminal
                or capture.get('imageSha256') != artifacts[terminal] or capture.get('criteriaFile') != criteria
                or capture.get('systemCapture') != 'XCUIScreen.main' or capture.get('targetVisible') is not True
                or capture.get('noCredentialsVisible') is not True):
            raise BatchFailure('ios_batch_tauri_manual_key_artifact_ref_invalid')
    if passed and encrypted_rotation:
        if not encrypted_rotation_case_valid(report):
            raise BatchFailure('ios_batch_encrypted_rotation_case_invalid')
        if len(set(artifacts.values())) != len(required):
            raise BatchFailure('ios_batch_encrypted_rotation_image_reused')
        case = report['cases']['encryptedKeyRotation']
        terminal, criteria = next(iter(ENCRYPTED_ROTATION_PROOF.items()))
        capture = case.get('terminalScreenshot')
        if (not isinstance(capture, dict) or capture.get('imageFile') != terminal or
                capture.get('imageSha256') != artifacts[terminal] or capture.get('criteriaFile') != criteria or
                case.get('reviewScreenshot') != {'imageFile': ENCRYPTED_ROTATION_REVIEW,
                    'imageSha256': artifacts[ENCRYPTED_ROTATION_REVIEW], 'purpose': 'design-review-no-ocr'}):
            raise BatchFailure('ios_batch_encrypted_rotation_artifact_ref_invalid')
    if passed and include_encrypted_key:
        encrypted_image = next(iter(ENCRYPTED_KEY_PROOF))
        if artifacts[encrypted_image] in {artifacts[name] for name in REQUIRED_IMAGES}:
            raise BatchFailure('ios_batch_encrypted_key_image_reused')
        cases = report.get('cases')
        case = cases.get('encryptedKey') if isinstance(cases, dict) else None
        if not encrypted_key_case_valid(case):
            raise BatchFailure('ios_batch_encrypted_key_case_missing')
    published = {'result.json'}
    for name in sorted(allowed, key=lambda name: (name == TAURI_MANUAL_KEY_HOME, name)):
        if name not in artifacts:
            continue
        try:
            data = read_public_file(root, name, 8_000_000)
            if hashlib.sha256(data).hexdigest() != artifacts[name]:
                raise BatchFailure('ios_batch_image_hash_mismatch')
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'PNG' or image.width * image.height > 16_000_000:
                    raise BatchFailure('ios_batch_image_invalid')
                if name == TAURI_MANUAL_KEY_HOME and list(image.size) != home_capture.get('screenPixels'):
                    raise BatchFailure('ios_batch_tauri_manual_key_home_ref_invalid')
                image.verify()
            proof_name = terminal_proofs.get(name)
            if proof_name:
                proof_raw, proof = read_public_json(root, proof_name)
                if (passed and (encrypted_rotation or encrypted_key_manual_only) and
                        hashlib.sha256(proof_raw).hexdigest() != capture.get('criteriaSha256')):
                    raise BatchFailure('ios_batch_ocr_criteria_hash_mismatch')
                if proof.get('imageSha256') != artifacts[name]:
                    raise BatchFailure('ios_batch_ocr_image_hash_mismatch')
                if not all(proof.get(key) is True for key in
                           ('markerVisible', 'tokenVisible', 'proofSequenceVisible')):
                    raise BatchFailure('ios_batch_ocr_not_accepted')
                (destination / proof_name).write_bytes(proof_raw)
                published.add(proof_name)
            (destination / name).write_bytes(data)
            published.add(name)
        except (BatchFailure, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            if passed:
                if isinstance(exc, BatchFailure):
                    raise
                raise BatchFailure('ios_batch_image_invalid') from None
            # An incomplete scene is not exported, even if another scene passed.
            continue
    return published


def select_simulator_app(root, *, command=subprocess.run):
    """Select the actual unsigned arm64 simulator app inside Tauri's archive."""
    root = Path(root).resolve(strict=True)
    candidates = []
    for app in root.glob('**/*.xcarchive/Products/Applications/*.app'):
        if app.is_symlink() or not app.is_dir() or not app.resolve().is_relative_to(root):
            raise BatchFailure('ios_batch_app_path_invalid')
        try:
            info_path = app / 'Info.plist'
            if info_path.is_symlink():
                raise ValueError('symlink')
            info = plistlib.loads(info_path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            raise BatchFailure('ios_batch_app_plist_invalid') from None
        if info.get('CFBundleIdentifier') == 'dev.herdrpocket.tauriprobe':
            candidates.append((app, info))
    if len(candidates) != 1:
        raise BatchFailure('ios_batch_app_not_unique')
    app, info = candidates[0]
    name = info.get('CFBundleExecutable')
    if (info.get('CFBundleSupportedPlatforms') != ['iPhoneSimulator'] or
            info.get('CFBundlePackageType') != 'APPL' or
            not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name)):
        raise BatchFailure('ios_batch_app_not_simulator')
    binary = app / name
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise BatchFailure('ios_batch_app_executable_missing')
    try:
        arch = command(['xcrun', 'lipo', '-archs', str(binary)], check=True,
                       capture_output=True, text=True, timeout=30).stdout.strip()
        build = command(['xcrun', 'vtool', '-show-build', str(binary)], check=True,
                        capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise BatchFailure('ios_batch_app_binary_inspection_failed') from None
    if arch != 'arm64' or not re.search(r'^\s*platform\s+(?:IOSSIMULATOR|7)\s*$', build, re.M):
        raise BatchFailure('ios_batch_app_binary_not_arm64_simulator')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    select = sub.add_parser('select-app')
    select.add_argument('--root', required=True)
    publish = sub.add_parser('publish')
    publish.add_argument('--root', required=True)
    publish.add_argument('--destination', required=True)
    publish.add_argument('--shell', required=True, choices=('flutter', 'tauri'))
    publish.add_argument('--source-sha', required=True)
    cases = publish.add_mutually_exclusive_group()
    cases.add_argument('--include-encrypted-key', action='store_true')
    cases.add_argument('--encrypted-key-rotation', action='store_true')
    cases.add_argument('--encrypted-key-manual-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'select-app':
            print(select_simulator_app(args.root))
        elif args.action == 'publish':
            names = publish_evidence(args.root, args.destination, shell=args.shell, source_sha=args.source_sha,
                                     include_encrypted_key=args.include_encrypted_key, encrypted_rotation=args.encrypted_key_rotation,
                                     encrypted_key_manual_only=args.encrypted_key_manual_only)
            print('Verified public files: ' + ', '.join(sorted(names)))
            if read_public_json(Path(args.destination), 'result.json')[1]['status'] != 'passed':
                raise BatchFailure('ios_batch_runner_reported_failure')
    except (BatchFailure, OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, BatchFailure) else 'ios_batch_path_unavailable') from None


if __name__ == '__main__':
    main()
