#!/usr/bin/env python3
"""CI-only disposable iOS Simulator ordinary SSH acceptance; exports no raw logs."""
import argparse
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import struct
import sys
import tempfile
import time
import uuid

from contextlib import nullcontext
from flutter_direct_ssh_android import (PUBLIC_FIELDS as FIELDS, ROTATION_PUBLIC_FIELDS, ROTATION_PHASES,
                                       ENCRYPTED_PUBLIC_FIELDS, ENCRYPTED_ROTATION_PUBLIC_FIELDS,
                                       ENCRYPTED_ROTATION_CHECKPOINTS, ENCRYPTED_UI_PHASES, checked_encrypted_stage,
                                       closed_rotation_evidence,
                                       encrypted_probe_evidence, safe_encrypted_connect_diagnostic, safe_encrypted_diagnostic,
                                       ORDINARY_MOBILE_PHASES, Failure as SharedFailure, checked_rotation_stage,
                                       ordinary_mobile_checkpoint, ordinary_session_evidence,
                                       require_ordinary_mobile_checkpoints, rotation_checkpoint,
                                       safe_failure, verify_prepared)

PACKAGE = 'dev.herdr.herdrFlutterProbe'
TARGET = 'integration_test/ios_direct_ssh_test.dart'
ENCRYPTED_ROTATION_REF = 'refs/heads/codex/acceptance/direct-ssh-ios-flutter-only-encrypted-rotation-'
STAGES = {'home', 'target', 'probe', 'authenticate', 'secret_entry', 'screenshot_wait', 'connect_tap', 'connect_preflight',
          'await_terminal', 'await_welcome', 'input', 'disconnect', 'disconnect_tap', 'disconnect_wait',
          'disconnect_secret', 'disconnect_status', 'disconnect_exception', 'disconnect_complete',
          'peer_confirmed', 'report_data_set', 'return_home', 'returned_home'}
STAGES.update({'rotation_' + name for name in ('home', 'initial_probe', 'rejected', 'cancelled',
                                              'fresh_probe', 'authenticate', 'input', 'disconnect', 'complete')})
STAGES.update(ORDINARY_MOBILE_PHASES)
STAGES.update(ENCRYPTED_UI_PHASES | {'encrypted_waiting_private', 'encrypted_home', 'encrypted_probe',
              'encrypted_review', 'encrypted_rejected', 'encrypted_connect', 'encrypted_disconnect',
              'encrypted_returned_home'})
LOG_MARKERS = {'xcodeBuildCompleted': 'Xcode build done.',
               'buildError': 'Failed to build iOS app',
               'launchError': 'Error launching application on',
               'testFailure': 'Some tests failed.',
               'testPassed': 'All tests passed!',
               'testFrameworkException': 'EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK',
               'hitTestWarning': 'derived an Offset that would not hit test',
               'hitTestFinder': 'hitTestable',
               'widgetNotFound': 'Expected: exactly one matching candidate',
               'installationStarted': 'Installing and launching',
               'observatoryConnecting': 'Connecting to VM Service',
               'testLoading': 'loading ',
               'testStarted': 'normal homepage to ordinary SSH'}
LOG_MARKERS.update({'xctestBuildSucceeded': '** TEST BUILD SUCCEEDED **',
                    'xctestStarted': 'Test Suite',
                    'xctestSucceeded': '** TEST EXECUTE SUCCEEDED **',
                    'xctestFailed': '** TEST EXECUTE FAILED **',
                    'xctestInstallFailed': 'Failed to install',
                    'xctestLaunchFailed': 'Failed to launch',
                    'xctestRunnerExited': 'test runner exited',
                    'xctestEarlyExit': 'Early unexpected exit',
                    'xctestTimedOut': 'Timed out',
                    'xctestNoTests': 'No tests were found',
                    'xctestBundleLoadFailed': 'test bundle could not be loaded',
                    'xctestConnectionFailed': 'Failed to establish connection',
                    'xctestCoreSimulatorError': 'CoreSimulatorErrorDomain'})


class Failure(ValueError):
    pass


def command(*args, timeout=60):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise Failure('ios_simulator_command_failed')
    return result.stdout.decode('utf-8')


def read_json(path):
    if not path.is_file():
        return None
    if path.stat().st_size > 4096:
        raise Failure('ios_result_oversize')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise Failure('ios_result_invalid')
    return value


def log_diagnostics(path):
    if not path.is_file():
        return {}
    with path.open('rb') as log:
        log.seek(0, os.SEEK_END)
        size = log.tell()
        log.seek(max(0, size - 131072))
        text = log.read().decode('utf-8', errors='replace')
    return {key: marker in text for key, marker in LOG_MARKERS.items()}


def app_container(device, timeout):
    try:
        result = subprocess.run(['xcrun', 'simctl', 'get_app_container', device, PACKAGE, 'data'],
                                capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, True
    return (Path(result.stdout.decode().strip()) if result.returncode == 0 else None), False


class ContainerLocator:
    """Throttle CoreSimulator lookups and retain the first successful path."""
    def __init__(self, device, *, clock=time.monotonic, lookup=app_container, interval=10):
        self.device = device
        self.clock = clock
        self.lookup = lookup
        self.interval = interval
        self.next_attempt = 0
        self.path = None
        self.attempts = 0
        self.timeouts = 0

    def get(self, timeout):
        if self.path is not None or self.clock() < self.next_attempt:
            return self.path
        self.attempts += 1
        path, timed_out = self.lookup(self.device, timeout)
        self.next_attempt = self.clock() + self.interval
        if timed_out:
            self.timeouts += 1
        elif path is not None:
            self.path = path
        return self.path


def safe_screenshot_request(request, stage):
    return (isinstance(request, dict) and set(request) == {'passwordMasked', 'passwordAuth'} and
            request['passwordMasked'] is True and request['passwordAuth'] is True and
            stage == {'stage': 'screenshot_wait'})


def xctest_execution(build, result_bundle):
    return [*build, '-parallel-testing-enabled', 'NO',
            '-maximum-concurrent-test-simulator-destinations', '1',
            '-resultBundlePath', str(result_bundle),
            'test-without-building']


def owned_devices(name, timeout=180):
    listing = json.loads(command('xcrun', 'simctl', 'list', 'devices', '--json', timeout=timeout))
    result = []
    for devices in listing['devices'].values():
        for item in devices:
            if item.get('name') == name:
                identifier = item.get('udid', '')
                if not re.fullmatch(r'[0-9A-Fa-f-]{36}', identifier):
                    raise Failure('ios_owned_simulator_id_invalid')
                result.append(identifier)
    return result


def sanitized_failure(text, private_values):
    if not isinstance(text, str):
        return ''
    text = text.splitlines()[0][:1000]
    for value in private_values:
        if value:
            text = text.replace(value, '[redacted]')
            text = text.replace(base64.b64encode(value.encode()).decode(), '[redacted]')
    text = re.sub(r'-----BEGIN.*', '[redacted]', text)
    text = re.sub(r'(?i)\b(password|passphrase|private.?key|secret|username)\s*[:=]\s*\S+', r'\1=[redacted]', text)
    text = re.sub(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', '[address]', text)
    text = re.sub(r'(?<![A-Za-z])/(?:[^\s:]+/?)+', '[path]', text)
    text = re.sub(r'\b[A-Za-z0-9_+/=-]{24,}\b', '[token]', text)
    text = re.sub(r'[^A-Za-z0-9 .,;:_()\[\]#=+\-]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:240]


def failure_facts(text, private_values):
    if not isinstance(text, str):
        return {}
    facts = {}
    lines = text.splitlines()[:200]
    for index, line in enumerate(lines):
        stripped = line.strip()
        if 'EXCEPTION CAUGHT BY FLUTTER TEST FRAMEWORK' in line and 'frameworkExcerpt' not in facts:
            excerpt = []
            for following in lines[index + 1:index + 9]:
                candidate = following.strip()
                if not candidate or candidate.startswith(('══', '#', 'When the exception was thrown')):
                    continue
                safe = sanitized_failure(candidate, private_values)
                if safe:
                    excerpt.append(safe)
                if len(excerpt) == 3:
                    break
            if excerpt:
                facts['frameworkExcerpt'] = excerpt
        for prefix, field in (('Expected:', 'expected'), ('Actual:', 'actual'), ('Which:', 'which')):
            if stripped.startswith(prefix) and field not in facts:
                facts[field] = sanitized_failure(stripped, private_values)
        match = re.search(r'direct_ssh_ui_steps\.dart:(\d+)', line)
        if match and 'sourceLine' not in facts:
            number = int(match.group(1))
            if 1 <= number <= 1000:
                facts['sourceLine'] = number
    return facts


def xctest_result_markers(path, private_values=(), *, counts_only=False):
    if not path.exists():
        return {'resultBundlePresent': False}
    result = subprocess.run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                             '--path', str(path), '--format', 'json'], capture_output=True, timeout=60)
    if result.returncode:
        return {'resultBundlePresent': True, 'summaryReadable': False}
    try:
        data = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        return {'resultBundlePresent': True, 'summaryReadable': False}
    result = {'resultBundlePresent': True, 'summaryReadable': True}
    for field in ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests'):
        value = data.get(field) if isinstance(data, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10000:
            result[field] = value
    raw = json.dumps(data).lower()
    for key, marker in {'launchFailed': 'failed to launch', 'installFailed': 'failed to install',
                        'runnerExited': 'test runner exited', 'timedOut': 'timed out',
                        'crashed': 'crashed', 'noTests': 'no tests were found',
                        'bundleLoadFailed': 'test bundle could not be loaded'}.items():
        result[key] = marker in raw
    if counts_only:
        return result  # Encrypted runs never export XCTest's free-form text.
    failures = data.get('testFailures', []) if isinstance(data, dict) else []
    messages, identifier, facts = [], None, {}
    if isinstance(failures, list):
        for item in failures[:3]:
            if not isinstance(item, dict):
                continue
            candidate = next((item.get(key) for key in ('testIdentifierString', 'testIdentifier', 'testName')
                              if isinstance(item.get(key), str)), None)
            if isinstance(candidate, str) and len(candidate) <= 300:
                identifier = candidate
                if 'RunnerTests/' in candidate:
                    result['failureTestIdentifier'] = 'RunnerTests.' + sanitized_failure(candidate.split('RunnerTests/', 1)[1], private_values)
                else:
                    result['failureTestIdentifier'] = sanitized_failure(candidate, private_values)
            for field in ('failureText', 'message', 'issueType'):
                for key, value in failure_facts(item.get(field), private_values).items():
                    facts.setdefault(key, value)
                value = sanitized_failure(item.get(field), private_values)
                if value and value not in messages:
                    messages.append(value)
    if identifier:
        detail = subprocess.run(['xcrun', 'xcresulttool', 'get', 'test-results', 'test-details',
                                 '--path', str(path), '--test-id', identifier, '--format', 'json'],
                                capture_output=True, timeout=60)
        if detail.returncode == 0:
            try:
                detail_data = json.loads(detail.stdout)
            except (ValueError, UnicodeError):
                detail_data = None
            def collect(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in ('failureText', 'message', 'issueType') and isinstance(child, str):
                            for fact, entry in failure_facts(child, private_values).items():
                                facts.setdefault(fact, entry)
                            clean = sanitized_failure(child, private_values)
                            if clean and clean not in messages:
                                messages.append(clean)
                        elif key in ('failureMessages', 'issues') and isinstance(child, list):
                            for issue in child[:10]:
                                if isinstance(issue, str):
                                    for fact, entry in failure_facts(issue, private_values).items():
                                        facts.setdefault(fact, entry)
                                    clean = sanitized_failure(issue, private_values)
                                    if clean and clean not in messages:
                                        messages.append(clean)
                                else:
                                    collect(issue)
                        elif isinstance(child, (dict, list)):
                            collect(child)
                elif isinstance(value, list):
                    for child in value[:30]:
                        collect(child)
            collect(detail_data)
    if messages:
        result['failureReasons'] = messages[:2]
    if facts:
        result['failureFacts'] = facts
    return result


def check_result(value, fields=FIELDS):
    if (not isinstance(value, dict) or set(value) != fields or type(value['schemaVersion']) is not int or
            value['schemaVersion'] != 1 or value['platform'] != 'ios-simulator' or
            value['physicalImeVerified'] is not False or
            any(value[key] is not True for key in fields - {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('ios_result_incomplete')
    return value


def check_rotation_result(value):
    if (not isinstance(value, dict) or set(value) != ROTATION_PUBLIC_FIELDS or
            type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or
            value['platform'] != 'ios-simulator' or value['physicalImeVerified'] is not False or
            any(value[key] is not True for key in ROTATION_PUBLIC_FIELDS -
                {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('ios_rotation_result_incomplete')
    return value


def capture_system_screen(device, path):
    command('xcrun', 'simctl', 'io', device, 'screenshot', str(path), timeout=45)
    png = path.read_bytes()
    if (not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8_000_000 or
            len(png) < 24 or png[12:16] != b'IHDR'):
        raise Failure('ios_screenshot_invalid')
    return png


def target_pixel_proof(png, expected_target, bounds):
    # The measured target widget is a crop locator, never proof of its pixels.
    # Require the full exact target in one OCR row; no fuzzy substitutions.
    from PIL import Image, ImageOps
    from terminal_screenshot_gate import ScreenshotGateError
    image = Image.open(io.BytesIO(png)).convert('RGB')
    x, y, width, height = bounds
    crop = image.crop((x, y, x + width, y + height))
    gray = ImageOps.expand(ImageOps.autocontrast(ImageOps.grayscale(crop)).resize(
        (width * 2, height * 2)), border=20, fill=255)
    encoded = io.BytesIO()
    gray.save(encoded, format='PNG')
    for psm in (7, 6):
        try:
            result = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', str(psm),
                                     '-c', 'load_system_dawg=0', '-c', 'load_freq_dawg=0'],
                                    input=encoded.getvalue(), capture_output=True, check=True, timeout=30,
                                    env=dict(os.environ, OMP_THREAD_LIMIT='1'))
            rows = result.stdout.decode('utf-8', errors='strict').splitlines()
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ScreenshotGateError('ios_target_ocr_failed') from None
        if any(re.sub(r'\s', '', row) == expected_target for row in rows):
            return {'targetVisible': True, 'targetBounds': list(bounds), 'ocrPageSegmentationMode': psm}
    raise ScreenshotGateError('ios_target_not_visible')


def screen_checkpoint(request, completed, fixture, rotation_fixture, device, exchange, private, output, *,
                      encrypted=None, encrypted_rotation=False):
    peers = {} if encrypted_rotation else {'ordinary': fixture, 'key-rotation': rotation_fixture}
    if encrypted is not None:
        peers['encrypted-rotation' if encrypted_rotation else 'encrypted'] = encrypted
    keys = {'tag', 'attempt', 'bounds', 'targetBounds', 'viewSize', 'observedTarget'}
    if (not isinstance(request, dict) or set(request) != keys or type(request['tag']) is not str or request['tag'] not in peers or
            type(request['attempt']) is not int or not 1 <= request['attempt'] <= 12 or
            not isinstance(request['viewSize'], list) or len(request['viewSize']) != 2 or
            any(type(n) is not int or n <= 0 for n in request['viewSize'])):
        raise Failure('ios_screen_request_invalid')
    for field in ('bounds', 'targetBounds'):
        rect = request[field]
        if (not isinstance(rect, list) or len(rect) != 4 or any(type(n) is not int for n in rect) or
                rect[0] < 0 or rect[1] < 0 or rect[2] <= 0 or rect[3] <= 0 or
                rect[0] + rect[2] > request['viewSize'][0] or rect[1] + rect[3] > request['viewSize'][1]):
            raise Failure('ios_screen_bounds_invalid')
    tag, attempt = request['tag'], request['attempt']
    peer = peers[tag]
    expected_target = f'{peer.username}@127.0.0.1:{peer.port}'
    if request['observedTarget'] != expected_target:
        raise Failure('ios_active_target_mismatch')
    if tag in completed and attempt <= completed[tag]['attempt']:
        return
    if ((tag in completed and completed[tag]['accepted']) or
            attempt != (completed[tag]['attempt'] + 1 if tag in completed else 1) or
            (tag == 'ordinary' and not completed.get('key-rotation', {}).get('accepted')) or
            (tag == 'encrypted' and not completed.get('ordinary', {}).get('accepted'))):
        raise Failure('ios_screen_request_out_of_order')
    events = peer.snapshot()['connectionEvents']
    # A screen cannot be admitted before this peer received the sole input.
    if not events or not events[-1]['markerReceived'] or events[-1]['inputBytes'] != 9:
        raise Failure('ios_screen_peer_input_missing')
    if encrypted_rotation:
        encrypted_rotation_session(peer, closed=False)
    name = {'ordinary': 'ordinary-terminal', 'key-rotation': 'key-change-terminal',
            'encrypted': 'encrypted-key-terminal', 'encrypted-rotation': 'encrypted-rotation-terminal'}[tag]
    png = capture_system_screen(device, private / (name + '.png'))
    if list(struct.unpack('>II', png[16:24])) != request['viewSize']:
        raise Failure('ios_screenshot_geometry_mismatch')
    from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot
    target_evidence, evidence, code = None, None, None
    try:
        target_evidence = target_pixel_proof(png, expected_target, request['targetBounds'])
        evidence = verify_terminal_screenshot(png, expected_token=peer.screen_token, bounds=tuple(request['bounds']))
    except ScreenshotGateError as error:
        code = str(error)
        evidence = error.evidence
    accepted = code is None
    # Export only a credential-free active frame with its full target proven
    # from pixels. Keep the shared gate dictionary unchanged in the OCR file.
    if target_evidence is not None and (tag not in ('encrypted', 'encrypted-rotation') or accepted):
        (output / (name + '.png')).write_bytes(png)
        (output / (name + '-ocr.json')).write_text(json.dumps(evidence, indent=2) + '\n')
    completed[tag] = {'attempt': attempt, 'accepted': accepted,
                      'expectedTarget': expected_target, 'targetEvidence': target_evidence}
    if code is not None:
        completed[tag]['failureCode'] = code
    pending = exchange / ('screen-' + tag + '-' + str(attempt) + '.new')
    pending.write_text(json.dumps({'tag': tag, 'attempt': attempt, 'accepted': accepted}))
    pending.replace(pending.with_suffix('.json'))


def review_checkpoint(request, fixture, device, exchange, private, output, *, encrypted_rotation=False):
    tag = 'encrypted-rotation' if encrypted_rotation else 'key-rotation'
    if request != {'tag': tag, 'formAbsent': True, 'secretAbsent': True} or any(
            type(request[key]) is not bool for key in ('formAbsent', 'secretAbsent')):
        raise Failure('ios_review_request_invalid')
    if not fixture.wait_for_connections_closed(2):
        raise Failure('ios_review_peer_not_closed')
    fixture.rotation_evidence(2)
    image = 'encrypted-rotation-review.png' if encrypted_rotation else 'key-change-review.png'
    png = capture_system_screen(device, private / image)
    (output / image).write_bytes(png)
    pending = exchange / ('encrypted-rotation-review-done.new' if encrypted_rotation else 'review-done.new')
    pending.write_text(json.dumps({'captured': True}))
    pending.replace(pending.with_suffix('.json'))


def public_artifacts(output, *, masked_preconnect=False, include_encrypted_key=False, encrypted_rotation=False):
    cases, artifacts = {}, {}
    names = ([('encryptedKeyRotation', 'encrypted-rotation-terminal')] if encrypted_rotation else
             [('ordinary', 'ordinary-terminal'), ('keyChange', 'key-change-terminal')])
    if include_encrypted_key:
        names.append(('encryptedKey', 'encrypted-key-terminal'))
    for tag, name in names:
        png, proof = name + '.png', name + '-ocr.json'
        if (output / png).is_file() and (output / proof).is_file():
            digest = hashlib.sha256((output / png).read_bytes()).hexdigest()
            criteria = json.loads((output / proof).read_text())
            if criteria.get('imageSha256') != digest:
                raise Failure('ios_artifact_criteria_hash_mismatch')
            artifacts[png] = digest
            cases[tag] = {'terminalScreenshot': {'imageFile': png, 'imageSha256': digest,
                'criteriaFile': proof, 'criteriaSha256': hashlib.sha256((output / proof).read_bytes()).hexdigest()},
                'protocolRef': {'ordinary': 'protocol', 'keyChange': 'rotation.protocol',
                                'encryptedKey': 'encryptedProtocol', 'encryptedKeyRotation': 'encryptedRotationProtocol'}[tag]}
    review = output / ('encrypted-rotation-review.png' if encrypted_rotation else 'key-change-review.png')
    if review.is_file():
        digest = hashlib.sha256(review.read_bytes()).hexdigest()
        artifacts[review.name] = digest
        cases.setdefault('encryptedKeyRotation' if encrypted_rotation else 'keyChange', {})['reviewScreenshot'] = {
            'imageFile': review.name, 'imageSha256': digest, 'purpose': 'design-review-no-ocr'}
    preconnect = output / 'preconnect.png'
    if masked_preconnect is True and preconnect.is_file():
        artifacts[preconnect.name] = hashlib.sha256(preconnect.read_bytes()).hexdigest()
    return {'cases': cases, 'artifacts': artifacts}


def ui_diagnostic(failure):
    diagnostic = {}
    for field in ('connectExists', 'connectEnabled', 'connectHitTestable', 'terminalVisible',
                  'probeEnabled', 'trustDialogVisible'):
        if field in failure and (failure[field] is None or isinstance(failure[field], bool)):
            diagnostic[field] = failure.get(field)
    for field, allowed in {
        'exceptionClass': {'TestFailure', 'StateError', 'FlutterError', 'other'},
        'statusCode': {'probe_in_progress', 'probe_failed', 'probe_idle', 'fingerprint_confirmed', 'connecting', 'auth_failed', 'key_mismatch', 'connect_failed',
                       'background_closed', 'disconnected', 'shell_ended', 'connected', 'page_absent', 'other'},
        'appLifecycle': {'resumed', 'inactive', 'hidden', 'paused', 'detached', 'unknown'},
    }.items():
        if isinstance(failure.get(field), str) and failure[field] in allowed:
            diagnostic[field] = failure[field]
    line = failure.get('sourceLine')
    if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1000:
        diagnostic['sourceLine'] = line
    return diagnostic


def connection_diagnostic(value):
    keys = {'phase', 'failureCode', 'hostKeyMatched', 'credentialCaptured', 'passwordRequested'}
    phases = {'idle', 'keyParse', 'socket', 'handshake', 'hostKeyVerified', 'passwordRequest', 'shellRequest', 'connected'}
    failures = {'keyParse', 'socket', 'handshake', 'handshakeTimeout', 'authRejected', 'authAborted',
                'authTimeout', 'timeout', 'hostKeyChanged', 'transport', 'cancelled', 'other'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['phase']) is not str or
            value['phase'] not in phases or
            (value['failureCode'] is not None and (type(value['failureCode']) is not str or value['failureCode'] not in failures)) or
            any(type(value[key]) is not bool for key in keys - {'phase', 'failureCode'})):
        return {}
    return dict(value)


def framework_diagnostic(value, private_values, *, include_excerpt=True):
    if not isinstance(value, dict):
        return None
    result = {}
    allowed = {'TestFailure', 'AssertionError', 'FlutterError', 'StateError', 'TimeoutException', 'other'}
    if isinstance(value.get('exceptionClass'), str) and value['exceptionClass'] in allowed:
        result['exceptionClass'] = value['exceptionClass']
    line = value.get('sourceLine')
    if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1000:
        result['sourceLine'] = line
    excerpt = value.get('excerpt')
    if include_excerpt and isinstance(excerpt, list):
        result['excerpt'] = [safe for item in excerpt[:3]
                             if (safe := sanitized_failure(item, private_values))]
    probe = semantics_probe(value.get('semantics'))
    if probe is not None:
        result['semantics'] = probe
    return result


def semantics_probe(value):
    if not isinstance(value, dict) or set(value) != {'platformEnabled', 'realPlatformEnabled', 'bindingHandles', 'pipelineHandles'}:
        return None
    if not isinstance(value['platformEnabled'], bool) or not isinstance(value['realPlatformEnabled'], bool):
        return None
    if any(not isinstance(value[key], int) or isinstance(value[key], bool) or not 0 <= value[key] <= 100
           for key in ('bindingHandles', 'pipelineHandles')):
        return None
    return value


def layout_diagnostics(value):
    if not isinstance(value, dict) or set(value) != {'events'} or not isinstance(value['events'], list):
        return []
    required = {'direction', 'pixels', 'stage', 'owner', 'file', 'viewSize', 'viewInsets', 'devicePixelRatio'}
    allowed = required | {'line', 'column', 'routeCurrent', 'flexSize'}
    def number(n, maximum):
        return type(n) in (int, float) and 0 <= n <= maximum and math.isfinite(n)
    result = []
    for event in value['events'][:4]:
        if (not isinstance(event, dict) or not required <= set(event) or not set(event) <= allowed or
                any(type(event[key]) is not str for key in ('direction', 'stage', 'owner', 'file')) or
                event['direction'] not in {'left', 'right', 'top', 'bottom'} or
                not number(event['pixels'], 100000) or event['pixels'] <= 0 or
                event['stage'] not in STAGES | {'fixture_validation'} or
                event['owner'] not in {'DirectSshPage', 'HostCatalogPage', 'ProbePage', 'unknown'} or
                event['file'] not in {'direct_ssh_page.dart', 'host_catalog_page.dart', 'main.dart', 'unknown'} or
                not number(event['devicePixelRatio'], 10) or event['devicePixelRatio'] <= 0):
            continue
        valid = True
        for key, length in (('viewSize', 2), ('viewInsets', 4), ('flexSize', 2)):
            if key in event and (not isinstance(event[key], list) or len(event[key]) != length or
                                 any(not number(n, 100000) for n in event[key])):
                valid = False
        for key in ('line', 'column'):
            if key in event and (type(event[key]) is not int or not 1 <= event[key] <= 10000):
                valid = False
        if 'routeCurrent' in event and event['routeCurrent'] is not None and type(event['routeCurrent']) is not bool:
            valid = False
        if valid:
            result.append(dict(event))
    return result


def deliver_encrypted_credentials(exchange, peer):
    # Publish once, mode 0600, without replacing a file the app may already have consumed.
    target = exchange / 'encrypted-credentials.json'
    if exchange.is_symlink() or exchange.parent.is_symlink() or not exchange.is_dir():
        raise Failure('ios_encrypted_exchange_invalid')
    with tempfile.NamedTemporaryFile(dir=exchange) as pending:
        pending.write(json.dumps({'privateKey': peer.private_key, 'passphrase': peer.passphrase}).encode())
        pending.flush()
        try:
            os.link(pending.name, target)
        except FileExistsError:
            raise Failure('ios_encrypted_credentials_already_delivered') from None


def encrypted_rotation_session(peer, *, closed):
    from tauri_ios_direct_ssh import Failure as FixtureFailure, rotation_session_evidence
    try:
        session = rotation_session_evidence(peer, closed=closed)['connectionEvents'][-1]
    except FixtureFailure:
        raise Failure('ios_encrypted_rotation_session_invalid') from None
    exact = {'id': 4, 'authAttempts': 1, 'authSuccesses': 1, 'ptyRequests': 1, 'shellRequests': 1, 'inputBytes': 9}
    if any(type(session.get(field)) is not int or session[field] != value for field, value in exact.items()):
        raise Failure('ios_encrypted_rotation_session_invalid')
    return session


def encrypted_case_evidence(exchange, peer, checkpoints, *, rotating=False):
    prefix = 'encrypted-rotation' if rotating else 'encrypted'
    fields = ENCRYPTED_ROTATION_PUBLIC_FIELDS if rotating else ENCRYPTED_PUBLIC_FIELDS
    device = check_result(read_json(exchange / (prefix + '-result.json')), fields)
    modes = read_json(exchange / (prefix + '-mode-switch.json'))
    phases = ENCRYPTED_ROTATION_CHECKPOINTS if rotating else ('review', 'rejected')
    if (tuple(checkpoints) != phases or (not rotating and checkpoints['review'] != checkpoints['rejected']) or
            not isinstance(modes, dict) or set(modes) != {'passwordToKeyCleared', 'keyToPasswordCleared', 'sameTrust'} or
            any(value is not True for value in modes.values()) or os.path.lexists(exchange / 'encrypted-credentials.json')):
        raise Failure('ios_encrypted_checkpoints_incomplete')
    if not peer.wait_for_connections_closed(4 if rotating else 2):
        raise Failure('ios_encrypted_peer_not_closed')
    if rotating:
        session = encrypted_rotation_session(peer, closed=True)
        rotation = closed_rotation_evidence(peer, 4)
    else:
        ordinary_session_evidence(peer, closed=True)
        session = peer.snapshot()['connectionEvents'][1]
        if session.get('singleMarkerLineExact') is not True:
            raise Failure('ios_encrypted_input_not_exact')
    fields = ('id', 'hostKey', 'authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes',
              'outputBytes', 'markerReceived', 'sessionClosed', 'closed', 'singleMarkerLineExact')
    result = {'fingerprintReviewed': device['fingerprintMatched'], 'terminalInputReceived': device['remoteEchoVisible'],
            'disconnected': device['disconnectUiConfirmed'], 'device': device, 'modeSwitch': modes,
            'acceptedSession': {field: session[field] for field in fields}, 'authenticationMethod': 'publickey'}
    if rotating:
        result.update(checkpoints=checkpoints, finalEvidence=rotation)
    else:
        result['wrongPassphrase'] = {'rejected': device['wrongPassphraseRejectedLocally'], 'peer': checkpoints['rejected']}
    return result


def run(app, output, env, *, include_encrypted_key=False, encrypted_rotation=False):
    if (env.get('GITHUB_ACTIONS') != 'true' or
            not env.get('GITHUB_REF', '').startswith('refs/heads/codex/acceptance/direct-ssh-ios-') or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')) or not env.get('RUNNER_TEMP')):
        raise Failure('ios_isolated_ci_required')
    if include_encrypted_key != env['GITHUB_REF'].startswith('refs/heads/codex/acceptance/direct-ssh-ios-flutter-only-encrypted-key-'):
        raise Failure('ios_encrypted_ref_mismatch')
    if (encrypted_rotation != env['GITHUB_REF'].startswith(ENCRYPTED_ROTATION_REF) or
            (encrypted_rotation and (include_encrypted_key or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'))):
        raise Failure('ios_encrypted_rotation_ref_or_dispatch_mismatch')
    secret_case = include_encrypted_key or encrypted_rotation
    encrypted_exchange = 'encrypted-rotation' if encrypted_rotation else 'encrypted'
    base = Path(env['RUNNER_TEMP']).resolve()
    app, output = Path(app).resolve(), Path(output).resolve()
    if (app == base or output == base or app == output or not app.is_relative_to(base) or
            not output.is_relative_to(base) or not app.is_dir() or output.exists()):
        raise Failure('ios_isolated_paths_required')
    verify_prepared(app, env)
    from ios_xctest_scaffold import prepare as prepare_xctest
    source_root = Path(__file__).resolve().parents[1] / 'flutter'
    for relative in (TARGET, 'integration_test/direct_ssh_ui_steps.dart', 'integration_test/ios_exchange.dart',
                     'test/ios_layout_diagnostics.dart'):
        if (app / relative).is_symlink() or (app / relative).read_bytes() != (source_root / relative).read_bytes():
            raise Failure('ios_test_source_mismatch')
    output.mkdir(mode=0o700)
    cleanup = {'simulatorDeleted': False, 'fixtureClosed': False, 'flutterToolStopped': False,
               'appRemoved': False, 'privateRemoved': False, 'rawLogsUploaded': False}
    kind = 'flutter-ios-simulator-encrypted-key-rotation' if encrypted_rotation else 'flutter-ios-simulator-ordinary-ssh'
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': kind,
              'status': 'failed', 'cleanup': cleanup, 'physicalImeVerified': False}
    overall_deadline = time.monotonic() + 1800
    from direct_ssh_fixture import DirectSshFixture
    fixture = rotation_fixture = None
    if not encrypted_rotation:
        fixture = DirectSshFixture(screen_proof=True, channel_deadline=overall_deadline)
        rotation_fixture = DirectSshFixture(rotate_after_probe=True, screen_proof=True, channel_deadline=overall_deadline)
    device, process, private, phase, primary = None, None, None, 'runtime_selection', None
    screens = {}
    rotation = {'checkpoints': {}}
    mobile = {}
    if not encrypted_rotation:
        report.update(rotation=rotation, ordinaryMobileCheckpoints=mobile)
    encrypted, encrypted_checkpoints, key_case, delivered = None, {}, {}, False
    private_values = ('127.0.0.1', str(app), str(base))
    if not encrypted_rotation:
        private_values += (fixture.password, fixture.username, fixture.fingerprint, rotation_fixture.password,
                           rotation_fixture.fingerprint, rotation_fixture.rotated_fingerprint)
    device_name = 'herdr-direct-' + env['GITHUB_RUN_ID'] + '-' + uuid.uuid4().hex
    create_attempted = False
    create_timed_out = False
    def remaining(limit):
        left = overall_deadline - time.monotonic()
        if left <= 0:
            raise Failure('ios_overall_timeout')
        return min(limit, left)
    try:
        phase = 'runtime_list'
        runtimes = json.loads(command('xcrun', 'simctl', 'list', 'runtimes', '--json', timeout=remaining(240)))['runtimes']
        ios = [r for r in runtimes if r.get('isAvailable') and r.get('identifier', '').startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
        phase = 'device_type_list'
        types = json.loads(command('xcrun', 'simctl', 'list', 'devicetypes', '--json', timeout=remaining(240)))['devicetypes']
        phones = [d for d in types if d.get('name', '').startswith('iPhone ')]
        if not ios or not phones:
            raise Failure('ios_simulator_runtime_or_phone_unavailable')
        runtime = sorted(ios, key=lambda r: [int(x) for x in r['version'].split('.')])[-1]
        phase = 'simulator_create'
        for phone in reversed(phones):
            create_attempted = True
            try:
                attempt = subprocess.run(['xcrun', 'simctl', 'create', device_name,
                                          phone['identifier'], runtime['identifier']], capture_output=True, timeout=remaining(240))
            except subprocess.TimeoutExpired:
                create_timed_out = True
                raise
            if attempt.returncode == 0:
                device = attempt.stdout.decode().strip()
                break
            if owned_devices(device_name, timeout=remaining(180)):
                raise Failure('ios_simulator_create_unconfirmed')
        if not device:
            raise Failure('ios_simulator_compatible_phone_unavailable')
        report['simulator'] = {'runtime': runtime['identifier'], 'runtimeVersion': runtime['version'], 'deviceType': phone['name']}
        if not re.fullmatch(r'[0-9A-Fa-f-]{36}', device):
            raise Failure('ios_simulator_id_invalid')
        phase = 'simulator_boot'
        command('xcrun', 'simctl', 'boot', device, timeout=remaining(240))
        phase = 'simulator_boot_ready'
        command('xcrun', 'simctl', 'bootstatus', device, '-b', timeout=remaining(360))
        phase = 'fixture_start'
        if secret_case:
            from ios_encrypted_key_fixture import EncryptedKeyFixture
            encrypted = EncryptedKeyFixture(rotate_after_probe=encrypted_rotation, screen_proof=True,
                                            channel_deadline=overall_deadline)
        with (fixture or nullcontext()), (rotation_fixture or nullcontext()), (encrypted or nullcontext()):
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-ios-private-', dir=base))
            defines = private / 'defines.json'
            targets = {'HERDR_IOS_DIRECT_SSH': '1', 'HERDR_IOS_RUN_ID': env['GITHUB_RUN_ID']}
            if not encrypted_rotation:
                targets.update(
                    HERDR_IOS_DIRECT_TARGET=json.dumps({'host': '127.0.0.1', 'port': fixture.port,
                        'username': fixture.username, 'password': fixture.password, 'fingerprint': fixture.fingerprint}),
                    HERDR_IOS_ROTATION_TARGET=json.dumps({'host': '127.0.0.1', 'port': rotation_fixture.port,
                        'username': rotation_fixture.username, 'password': rotation_fixture.password,
                        'fingerprint': rotation_fixture.fingerprint, 'rotatedFingerprint': rotation_fixture.rotated_fingerprint}))
            if encrypted:
                target = {'host': '127.0.0.1', 'port': encrypted.port, 'username': encrypted.username,
                          'fingerprint': encrypted.fingerprint}
                if encrypted_rotation:
                    target['rotatedFingerprint'] = encrypted.rotated_fingerprint
                targets.update(HERDR_IOS_ENCRYPTED_KEY_CASE='rotation' if encrypted_rotation else '1',
                               HERDR_IOS_ENCRYPTED_KEY_TARGET=json.dumps(target))
            defines.write_text(json.dumps(targets))
            defines.chmod(0o600)
            phase = 'xctest_scaffold'
            prepare_xctest(app)
            with (private / 'flutter-private.log').open('wb') as log:
                phase = 'flutter_config_only'
                result = subprocess.run(['flutter', 'build', 'ios', '--config-only', '--debug', '--simulator',
                    '--dart-define-from-file=' + str(defines), TARGET], cwd=app, env=env,
                    stdout=log, stderr=subprocess.STDOUT, timeout=remaining(600))
                if result.returncode:
                    raise Failure('ios_flutter_config_failed')
                phase = 'pod_install'
                result = subprocess.run(['pod', 'install'], cwd=app / 'ios', env=env,
                    stdout=log, stderr=subprocess.STDOUT, timeout=remaining(600))
                if result.returncode:
                    raise Failure('ios_pod_install_failed')
                derived = private / 'derived'
                build = ['xcodebuild', '-workspace', 'Runner.xcworkspace', '-scheme', 'Runner',
                         '-configuration', 'Debug', '-sdk', 'iphonesimulator', '-destination', 'id=' + device,
                         '-derivedDataPath', str(derived), 'CODE_SIGNING_ALLOWED=NO']
                phase = 'xctest_build'
                result = subprocess.run([*build, 'build-for-testing'], cwd=app / 'ios', env=env,
                    stdout=log, stderr=subprocess.STDOUT, timeout=remaining(900))
                if result.returncode:
                    raise Failure('ios_xctest_build_failed')
                phase = 'xctest_launch'
                result_bundle = private / 'test-result.xcresult'
                process = subprocess.Popen(xctest_execution(build, result_bundle), cwd=app / 'ios', env=env,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline, exchange, confirmed = min(overall_deadline, time.monotonic() + 1200), None, False
                locator = ContainerLocator(device)
                screenshot_attempted = False
                review_captured = False
                while process.poll() is None and time.monotonic() < deadline:
                    phase = 'await_device_result'
                    if exchange is None:
                        container = locator.get(min(15, max(1, deadline - time.monotonic())))
                        if container is not None:
                            exchange = container / 'tmp' / ('herdr-direct-ssh-' + env['GITHUB_RUN_ID'])
                    if exchange:
                        stage = read_json(exchange / 'stage.json')
                        if stage and stage.get('stage') in STAGES:
                            report['deviceStage'] = stage['stage']
                        review = read_json(exchange / 'review-request.json')
                        if review is not None and not review_captured:
                            if stage != {'stage': 'rotation_rejected'}:
                                raise Failure('ios_review_stage_invalid')
                            if encrypted_rotation and (not delivered or tuple(encrypted_checkpoints) != ('review',)):
                                raise Failure('ios_encrypted_rotation_review_out_of_order')
                            review_checkpoint(review, encrypted if encrypted_rotation else rotation_fixture,
                                              device, exchange, private, output, encrypted_rotation=encrypted_rotation)
                            review_captured = True
                        screen = read_json(exchange / 'screen-request.json')
                        if screen is not None:
                            if encrypted_rotation and (not review_captured or
                                    tuple(encrypted_checkpoints) != ENCRYPTED_ROTATION_CHECKPOINTS):
                                raise Failure('ios_encrypted_rotation_screen_out_of_order')
                            screen_checkpoint(screen, screens, fixture, rotation_fixture, device, exchange, private, output,
                                              encrypted=encrypted if delivered else None, encrypted_rotation=encrypted_rotation)
                        checkpoint = None if encrypted_rotation else read_json(exchange / 'rotation-stage.json')
                        if checkpoint is not None:
                            evidence = rotation_checkpoint(rotation_fixture, checkpoint, rotation['checkpoints'])
                            if evidence is not None:
                                phase_name, count = checked_rotation_stage(checkpoint, rotation['checkpoints'])
                                if fixture.snapshot()['connections'] != 0 or process.poll() is not None:
                                    raise Failure('ios_rotation_independence_missing')
                                if phase_name == 'complete':
                                    rotation['device'] = check_rotation_result(read_json(exchange / 'rotation-result.json'))
                                    rotation['peerClosedBeforeDriverExit'] = True
                                rotation['checkpoints'][phase_name] = evidence
                                pending = exchange / ('rotation-' + phase_name + '-confirmed.new')
                                pending.write_text(json.dumps({'phase': phase_name, 'stage': count,
                                                               'serverEvidenceAccepted': True}))
                                pending.replace(pending.with_suffix('.json'))
                        mobile_stage = None if encrypted_rotation else read_json(exchange / 'ordinary-mobile-stage.json')
                        if mobile_stage is not None:
                            checkpoint = ordinary_mobile_checkpoint(fixture, mobile_stage, mobile)
                            if checkpoint is not None:
                                phase_name, evidence = checkpoint
                                phase = 'ordinary_mobile_' + phase_name
                                if process.poll() is not None:
                                    raise Failure('ios_driver_exited_before_mobile_confirmation')
                                mobile[phase_name] = evidence
                                pending = exchange / ('ordinary-mobile-' + phase_name + '-confirmed.new')
                                pending.write_text(json.dumps({'phase': phase_name, 'serverEvidenceAccepted': True}))
                                pending.replace(pending.with_suffix('.json'))
                        request = None if encrypted_rotation else read_json(exchange / 'screenshot-request.json')
                        if (not screenshot_attempted and safe_screenshot_request(request, stage)
                                and process.poll() is None):
                            screenshot_attempted = True
                            try:
                                screenshot = private / 'preconnect.png'
                                command('xcrun', 'simctl', 'io', device, 'screenshot', str(screenshot), timeout=45)
                                image = screenshot.read_bytes()
                                if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image) > 8_000_000:
                                    raise Failure('ios_screenshot_invalid')
                                (output / 'preconnect.png').write_bytes(image)
                                report['maskedPreconnectScreenshot'] = True
                            except (Failure, OSError, subprocess.TimeoutExpired):
                                report['maskedPreconnectScreenshot'] = False
                            finally:
                                (exchange / 'screenshot-done.json').write_text('{}')
                    public = read_json(exchange / 'result.json') if exchange and not encrypted_rotation else None
                    if public is not None and not confirmed:
                        report['device'] = check_result(public)
                        require_ordinary_mobile_checkpoints(mobile)
                        if (set(screens) != {'ordinary', 'key-rotation'} or
                                not all(value['accepted'] for value in screens.values()) or not review_captured):
                            raise Failure('ios_screen_proof_missing')
                        if 'device' not in rotation or set(rotation['checkpoints']) != set(ROTATION_PHASES):
                            raise Failure('ios_rotation_confirmation_missing')
                        phase = 'peer_close_confirmation'
                        if (not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed') or
                                not fixture.wait_for_connections_closed(2) or process.poll() is not None):
                            raise Failure('ios_peer_input_or_ui_close_missing')
                        ordinary_session_evidence(fixture, closed=True)
                        pending = exchange / 'peer-confirmed.new'
                        pending.write_text(json.dumps({'protocolAccepted': True, 'peerClosedBeforeDriverExit': True}))
                        pending.replace(exchange / 'peer-confirmed.json')
                        confirmed = True
                        report['peerClosedBeforeDriverExit'] = True
                        if not encrypted:
                            break
                    if encrypted and exchange and (confirmed or encrypted_rotation):
                        if not delivered and stage == {'stage': 'encrypted_waiting_private'}:
                            if encrypted.snapshot()['connections'] != 0:
                                raise Failure('ios_encrypted_peer_not_independent')
                            deliver_encrypted_credentials(exchange, encrypted)
                            delivered = True
                        if delivered:
                            request = read_json(exchange / (encrypted_exchange + '-stage.json'))
                            name = (checked_encrypted_stage(request, encrypted_checkpoints, rotating=encrypted_rotation)
                                    if request is not None else None)
                            if name:
                                if encrypted_rotation and name != 'review':
                                    if not review_captured:
                                        raise Failure('ios_encrypted_rotation_review_missing')
                                    encrypted_checkpoints[name] = closed_rotation_evidence(encrypted, ROTATION_PHASES[name])
                                else:
                                    encrypted_checkpoints[name] = encrypted_probe_evidence(encrypted)
                                if process.poll() is not None:
                                    raise Failure('ios_encrypted_driver_exited_before_confirmation')
                                pending = exchange / (encrypted_exchange + '-' + name + '-confirmed.new')
                                pending.write_text(json.dumps({'phase': name, 'serverEvidenceAccepted': True}))
                                pending.replace(pending.with_suffix('.json'))
                            if (exchange / (encrypted_exchange + '-result.json')).is_file():
                                if not screens.get(encrypted_exchange, {}).get('accepted'):
                                    raise Failure('ios_encrypted_screen_proof_missing')
                                key_case = encrypted_case_evidence(exchange, encrypted, encrypted_checkpoints,
                                                                   rotating=encrypted_rotation)
                                if process.poll() is not None:
                                    raise Failure('ios_encrypted_driver_exited_before_confirmation')
                                pending = exchange / (encrypted_exchange + '-peer-confirmed.new')
                                pending.write_text(json.dumps({'protocolAccepted': True, 'peerClosedBeforeDriverExit': True}))
                                pending.replace(pending.with_suffix('.json'))
                                confirmed = True
                                report['peerClosedBeforeDriverExit'] = True
                                key_case['peerClosedBeforeDriverExit'] = True
                                break
                    time.sleep(.5)
                phase = 'await_driver_exit'
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Failure('ios_flutter_timeout') from None
                if exchange:
                    report['layoutOverflows'] = layout_diagnostics(read_json(exchange / 'overflow-diagnostic.json'))
                    final_stage = read_json(exchange / 'stage.json')
                    if final_stage and final_stage.get('stage') in STAGES:
                        report['deviceStage'] = final_stage['stage']
                    framework = read_json(exchange / 'framework-error.json')
                    if framework:
                        report['frameworkDiagnostic'] = framework_diagnostic(framework,
                            (*private_values, str(private)), include_excerpt=not secret_case)
                    probes = {}
                    for name in ('baseline', 'home', 'report_data_set'):
                        probe = semantics_probe(read_json(exchange / ('semantics-' + name + '.json')))
                        if probe is not None:
                            probes[name] = probe
                    if probes:
                        report['semanticsProbes'] = probes
                if code or not confirmed or (secret_case and not key_case.get('peerClosedBeforeDriverExit')):
                    if delivered:
                        for filename, field, validate in (
                                ('encrypted-diagnostic.json', 'encryptedUiDiagnostic', safe_encrypted_diagnostic),
                                ('encrypted-connect-diagnostic.json', 'encryptedConnectDiagnostic', safe_encrypted_connect_diagnostic)):
                            value = read_json(exchange / filename)
                            if value is not None:
                                report[field] = validate(value)
                    preflight = read_json(exchange / 'connect-diagnostic.json') if exchange else None
                    if preflight:
                        report['connectDiagnostic'] = ui_diagnostic(preflight)
                    post = read_json(exchange / 'connect-post.json') if exchange else None
                    if post:
                        report['connectPostDiagnostic'] = ui_diagnostic(post)
                    failure = read_json(exchange / 'failure.json') if exchange else None
                    if failure and failure.get('stage') in STAGES | {'fixture_validation'}:
                        report['failureStage'] = failure['stage']
                        if failure.get('kind') in {'timeout', 'not_hit_testable', 'control_not_ready', 'other'}:
                            report['failureKind'] = failure['kind']
                        report['uiDiagnostic'] = ui_diagnostic(failure)
                        report['connectionDiagnostic'] = connection_diagnostic(failure.get('connection'))
                    raise Failure('ios_device_test_failed' if code else 'ios_peer_confirmation_missing')
                expected_stage = 'encrypted_returned_home' if secret_case else 'returned_home'
                if report.get('deviceStage') != expected_stage or report.get('frameworkDiagnostic') is not None:
                    raise Failure('ios_final_test_state_incomplete')
                if encrypted:
                    if encrypted_rotation:
                        encrypted_rotation_session(encrypted, closed=True)
                    else:
                        ordinary_session_evidence(encrypted, closed=True)
                    key_case.update(status='passed', returnedHome=True)
                if not encrypted_rotation:
                    report['device'] = check_result(read_json(exchange / 'result.json'))
                    report['protocol'] = fixture.snapshot()
                    if not all(report['protocol'][name] for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')):
                        raise Failure('ios_protocol_evidence_incomplete')
                    ordinary_session_evidence(fixture, closed=True)
                    rotation['protocol'] = rotation_fixture.snapshot()
                    rotation['finalEvidence'] = rotation_fixture.rotation_evidence(4)
                    accepted = rotation['finalEvidence']['acceptedSession']
                    if accepted['inputBytes'] != 9 or accepted['authAttempts'] != 1:
                        raise Failure('ios_rotation_replayed_input_or_auth')
                report['status'] = 'passed'
    except Exception as error:
        primary = str(error) if isinstance(error, (Failure, SharedFailure)) else 'ios_runner_failed'
        report['failureCode'] = primary
        report['diagnostic'] = safe_failure(error, phase)
    finally:
        report['lastPhase'] = phase
        if 'exchange' in locals() and exchange:
            try:
                report['layoutOverflows'] = layout_diagnostics(read_json(exchange / 'overflow-diagnostic.json'))
            except (Failure, OSError, ValueError):
                report['layoutDiagnosticCode'] = 'ios_layout_diagnostic_invalid'
        if 'locator' in locals():
            report['containerQueryTimeouts'] = locator.timeouts
            report['containerQueryAttempts'] = locator.attempts
        if private:
            report['flutterLogMarkers'] = log_diagnostics(private / 'flutter-private.log')
            try:
                report['xctestResult'] = xctest_result_markers(private / 'test-result.xcresult',
                    (*private_values, str(private)), counts_only=secret_case)
            except (OSError, subprocess.TimeoutExpired):
                report['xctestResult'] = {'resultBundlePresent': True, 'summaryReadable': False}
        if not encrypted_rotation:
            report['protocol'] = fixture.snapshot()
            rotation['protocol'] = rotation_fixture.snapshot()
        if encrypted:
            report['encryptedRotationProtocol' if encrypted_rotation else 'encryptedProtocol'] = encrypted.snapshot()
            report['encryptedCheckpoints'] = encrypted_checkpoints
        report['screens'] = screens
        try:
            report.update(public_artifacts(output, masked_preconnect=report.get('maskedPreconnectScreenshot') is True,
                                           include_encrypted_key=include_encrypted_key, encrypted_rotation=encrypted_rotation))
            required = {'ordinary-terminal.png', 'key-change-review.png', 'key-change-terminal.png'}
            if encrypted_rotation:
                required = {'encrypted-rotation-review.png', 'encrypted-rotation-terminal.png'}
                report['cases'].setdefault('encryptedKeyRotation', {}).update(key_case)
            elif include_encrypted_key:
                required.add('encrypted-key-terminal.png')
                report['cases'].setdefault('encryptedKey', {}).update(key_case)
            if report['status'] == 'passed' and not required <= set(report['artifacts']):
                raise Failure('ios_artifact_set_incomplete')
        except (Failure, OSError, ValueError):
            report['status'] = 'failed'
            report['artifactCode'] = 'ios_artifact_criteria_hash_mismatch'
            report['artifacts'] = {}
            primary = primary or 'ios_artifact_manifest_invalid'
            report['failureCode'] = primary
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        if not encrypted_rotation:
            fixture.close()
            rotation_fixture.close()
            cleanup['fixtureClosed'] = (fixture.snapshot()['connectionsClosed'] and
                                        rotation_fixture.snapshot()['connectionsClosed'])
        else:
            cleanup['fixtureClosed'] = not encrypted or encrypted.snapshot()['connectionsClosed']
        if encrypted:
            encrypted.close()
            cleanup['encryptedFixtureClosed'] = encrypted.snapshot()['connectionsClosed']
            if encrypted_rotation:
                cleanup['fixtureClosed'] = cleanup['encryptedFixtureClosed']
            cleanup['encryptedSecretsCleared'] = not (encrypted.private_key or encrypted.passphrase or encrypted.wrong_passphrase)
            if delivered:
                try:
                    if exchange.is_symlink() or exchange.parent.is_symlink():
                        raise OSError()
                    (exchange / 'encrypted-credentials.json').unlink(missing_ok=True)
                except OSError:
                    cleanup['encryptedSecretsCleared'] = False
        report['simulatorCreateAttempted'] = create_attempted
        if not create_attempted:
            cleanup['simulatorDeleted'] = True
            report['simulatorCleanup'] = 'not_created'
        else:
            try:
                # On create timeout the service may have created the device
                # despite the lost reply. Only this run's random name is ours.
                owned = owned_devices(device_name)
                if device and device not in owned:
                    raise Failure('ios_owned_simulator_not_found')
                for identifier in owned:
                    subprocess.run(['xcrun', 'simctl', 'shutdown', identifier], capture_output=True, timeout=120)
                    command('xcrun', 'simctl', 'delete', identifier, timeout=180)
                cleanup['simulatorDeleted'] = not owned_devices(device_name) and (bool(owned) or not create_timed_out)
                report['simulatorCleanup'] = ('deleted' if owned else
                    'create_timed_out_no_device_found' if create_timed_out else 'no_owned_device_found')
            except (Failure, OSError, ValueError, subprocess.TimeoutExpired):
                report['simulatorCleanup'] = 'unconfirmed'
        try:
            if private:
                shutil.rmtree(private)
            cleanup['privateRemoved'] = private is None or not private.exists()
        except OSError:
            report['privateCleanupCode'] = 'ios_private_cleanup_failed'
        try:
            # Generated Flutter/Xcode files can contain encoded fixture defines.
            # The app path was verified as an owned RUNNER_TEMP child above.
            shutil.rmtree(app)
            cleanup['appRemoved'] = not app.exists()
        except OSError:
            report['appCleanupCode'] = 'ios_app_cleanup_failed'
        if not all(cleanup[k] for k in cleanup if k != 'rawLogsUploaded'):
            report['status'] = 'failed'
            report['cleanupCode'] = 'ios_cleanup_incomplete'
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'passed':
        raise Failure(primary or 'ios_cleanup_incomplete')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    cases = parser.add_mutually_exclusive_group()
    cases.add_argument('--include-encrypted-key', action='store_true')
    cases.add_argument('--encrypted-key-rotation', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.project, args.output, dict(os.environ), include_encrypted_key=args.include_encrypted_key,
                     encrypted_rotation=args.encrypted_key_rotation)
        print(json.dumps({'status': result['status'], 'kind': result['kind']}))
    except Exception as error:
        print(str(error) if isinstance(error, Failure) else 'ios_runner_failed', file=sys.stderr)
        sys.exit(1)
