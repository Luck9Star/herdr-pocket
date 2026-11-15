#!/usr/bin/env python3
"""CI-only disposable iOS Simulator ordinary SSH acceptance; exports no raw logs."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from flutter_direct_ssh_android import safe_failure, verify_prepared

PACKAGE = 'dev.herdr.herdrFlutterProbe'
TARGET = 'integration_test/ios_direct_ssh_test.dart'
FIELDS = {'schemaVersion', 'platform', 'homepageEntry', 'fingerprintMatched', 'explicitTrustRequired',
          'realTerminalView', 'normalTextInputCommit', 'remoteEchoVisible', 'disconnectUiConfirmed',
          'credentialsCleared', 'physicalImeVerified'}
STAGES = {'home', 'target', 'probe', 'authenticate', 'secret_entry', 'screenshot_wait', 'connect_tap', 'connect_preflight',
          'await_terminal', 'await_welcome', 'input', 'disconnect'}
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


def safe_screenshot_request(request, stage):
    return (isinstance(request, dict) and set(request) == {'passwordMasked', 'passwordAuth'} and
            request['passwordMasked'] is True and request['passwordAuth'] is True and
            stage == {'stage': 'screenshot_wait'})


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


def xctest_result_markers(path, private_values=()):
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
    failures = data.get('testFailures', []) if isinstance(data, dict) else []
    messages, identifier = [], None
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
                            clean = sanitized_failure(child, private_values)
                            if clean and clean not in messages:
                                messages.append(clean)
                        elif key in ('failureMessages', 'issues') and isinstance(child, list):
                            for issue in child[:10]:
                                if isinstance(issue, str):
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
    return result


def check_result(value):
    if (set(value) != FIELDS or value['schemaVersion'] != 1 or value['platform'] != 'ios-simulator' or
            value['physicalImeVerified'] is not False or
            any(value[key] is not True for key in FIELDS - {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('ios_result_incomplete')
    return value


def ui_diagnostic(failure):
    diagnostic = {}
    for field in ('connectExists', 'connectEnabled', 'connectHitTestable', 'terminalVisible'):
        if field in failure and (failure[field] is None or isinstance(failure[field], bool)):
            diagnostic[field] = failure.get(field)
    for field, allowed in {
        'exceptionClass': {'TestFailure', 'StateError', 'FlutterError', 'other'},
        'statusCode': {'fingerprint_confirmed', 'connecting', 'auth_failed', 'key_mismatch', 'connect_failed',
                       'background_closed', 'disconnected', 'shell_ended', 'connected', 'page_absent', 'other'},
    }.items():
        if isinstance(failure.get(field), str) and failure[field] in allowed:
            diagnostic[field] = failure[field]
    line = failure.get('sourceLine')
    if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1000:
        diagnostic['sourceLine'] = line
    return diagnostic


def run(app, output, env):
    if (env.get('GITHUB_ACTIONS') != 'true' or
            not env.get('GITHUB_REF', '').startswith('refs/heads/codex/acceptance/direct-ssh-ios-') or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')) or not env.get('RUNNER_TEMP')):
        raise Failure('ios_isolated_ci_required')
    base = Path(env['RUNNER_TEMP']).resolve()
    app, output = Path(app).resolve(), Path(output).resolve()
    if (app == base or output == base or app == output or not app.is_relative_to(base) or
            not output.is_relative_to(base) or not app.is_dir() or output.exists()):
        raise Failure('ios_isolated_paths_required')
    verify_prepared(app, env)
    from ios_xctest_scaffold import prepare as prepare_xctest
    source_root = Path(__file__).resolve().parents[1] / 'flutter'
    for relative in (TARGET, 'integration_test/direct_ssh_ui_steps.dart'):
        if (app / relative).is_symlink() or (app / relative).read_bytes() != (source_root / relative).read_bytes():
            raise Failure('ios_test_source_mismatch')
    output.mkdir(mode=0o700)
    cleanup = {'simulatorDeleted': False, 'fixtureClosed': False, 'flutterToolStopped': False,
               'appRemoved': False, 'privateRemoved': False, 'rawLogsUploaded': False}
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': 'flutter-ios-simulator-ordinary-ssh',
              'status': 'failed', 'cleanup': cleanup, 'physicalImeVerified': False}
    from direct_ssh_fixture import DirectSshFixture
    fixture, device, process, private, phase, primary = DirectSshFixture(), None, None, None, 'runtime_selection', None
    device_name = 'herdr-direct-' + env['GITHUB_RUN_ID'] + '-' + uuid.uuid4().hex
    create_attempted = False
    create_timed_out = False
    overall_deadline = time.monotonic() + 1800
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
        with fixture:
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-ios-private-', dir=base))
            defines = private / 'defines.json'
            defines.write_text(json.dumps({'HERDR_IOS_DIRECT_SSH': '1', 'HERDR_IOS_RUN_ID': env['GITHUB_RUN_ID'],
                'HERDR_IOS_DIRECT_TARGET': json.dumps({'host': '127.0.0.1', 'port': fixture.port,
                    'username': fixture.username, 'password': fixture.password, 'fingerprint': fixture.fingerprint})}))
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
                process = subprocess.Popen([*build, '-resultBundlePath', str(result_bundle), 'test-without-building'], cwd=app / 'ios', env=env,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline, exchange, confirmed = min(overall_deadline, time.monotonic() + 1200), None, False
                container_timeouts = 0
                screenshot_attempted = False
                while process.poll() is None and time.monotonic() < deadline:
                    phase = 'await_device_result'
                    if exchange is None:
                        container, timed_out = app_container(device, min(15, max(1, deadline - time.monotonic())))
                        if timed_out:
                            container_timeouts += 1
                            continue
                        if container is not None:
                            exchange = container / 'tmp' / ('herdr-direct-ssh-' + env['GITHUB_RUN_ID'])
                    if exchange:
                        stage = read_json(exchange / 'stage.json')
                        if stage and stage.get('stage') in STAGES:
                            report['deviceStage'] = stage['stage']
                        request = read_json(exchange / 'screenshot-request.json')
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
                    public = read_json(exchange / 'result.json') if exchange else None
                    if public is not None:
                        check_result(public)
                        phase = 'peer_close_confirmation'
                        if not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed') or process.poll() is not None:
                            raise Failure('ios_peer_input_or_ui_close_missing')
                        pending = exchange / 'peer-confirmed.new'
                        pending.write_text(json.dumps({'protocolAccepted': True, 'peerClosedBeforeDriverExit': True}))
                        pending.replace(exchange / 'peer-confirmed.json')
                        confirmed = True
                        report['peerClosedBeforeDriverExit'] = True
                        break
                    time.sleep(.5)
                phase = 'await_driver_exit'
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Failure('ios_flutter_timeout') from None
                if code or not confirmed:
                    preflight = read_json(exchange / 'connect-diagnostic.json') if exchange else None
                    if preflight:
                        report['connectDiagnostic'] = ui_diagnostic(preflight)
                    post = read_json(exchange / 'connect-post.json') if exchange else None
                    if post:
                        report['connectPostDiagnostic'] = ui_diagnostic(post)
                    failure = read_json(exchange / 'failure.json') if exchange else None
                    if failure and re.fullmatch(r'[a-z_]{1,40}', failure.get('stage', '')):
                        report['failureStage'] = failure['stage']
                        if failure.get('kind') in {'timeout', 'not_hit_testable', 'control_not_ready', 'other'}:
                            report['failureKind'] = failure['kind']
                        report['uiDiagnostic'] = ui_diagnostic(failure)
                    raise Failure('ios_device_test_failed' if code else 'ios_peer_confirmation_missing')
                report['device'] = check_result(read_json(exchange / 'result.json'))
                report['protocol'] = fixture.snapshot()
                if not all(report['protocol'][name] for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')):
                    raise Failure('ios_protocol_evidence_incomplete')
                report['status'] = 'passed'
    except Exception as error:
        primary = str(error) if isinstance(error, Failure) else 'ios_runner_failed'
        report['failureCode'] = primary
        report['diagnostic'] = safe_failure(error, phase)
    finally:
        report['lastPhase'] = phase
        if 'container_timeouts' in locals():
            report['containerQueryTimeouts'] = container_timeouts
        if private:
            report['flutterLogMarkers'] = log_diagnostics(private / 'flutter-private.log')
            try:
                report['xctestResult'] = xctest_result_markers(private / 'test-result.xcresult',
                    (fixture.password, fixture.username, fixture.fingerprint, str(private), str(app), str(base)))
            except (OSError, subprocess.TimeoutExpired):
                report['xctestResult'] = {'resultBundlePresent': True, 'summaryReadable': False}
        report['protocol'] = fixture.snapshot()
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        fixture.close()
        cleanup['fixtureClosed'] = fixture.snapshot()['connectionsClosed']
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
    args = parser.parse_args()
    try:
        result = run(args.project, args.output, dict(os.environ))
        print(json.dumps({'status': result['status'], 'kind': result['kind']}))
    except Exception as error:
        print(str(error) if isinstance(error, Failure) else 'ios_runner_failed', file=sys.stderr)
        sys.exit(1)
