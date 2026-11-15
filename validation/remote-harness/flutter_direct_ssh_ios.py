#!/usr/bin/env python3
"""CI-only disposable iOS Simulator ordinary SSH acceptance; exports no raw logs."""
import argparse
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

from flutter_direct_ssh_android import safe_failure, verify_prepared

PACKAGE = 'dev.herdr.herdrFlutterProbe'
TARGET = 'integration_test/ios_direct_ssh_test.dart'
FIELDS = {'schemaVersion', 'platform', 'homepageEntry', 'fingerprintMatched', 'explicitTrustRequired',
          'realTerminalView', 'normalTextInputCommit', 'remoteEchoVisible', 'disconnectUiConfirmed',
          'credentialsCleared', 'physicalImeVerified'}
STAGES = {'home', 'target', 'probe', 'authenticate', 'input', 'disconnect'}
LOG_MARKERS = {'xcodeBuildCompleted': 'Xcode build done.',
               'buildError': 'Failed to build iOS app',
               'launchError': 'Error launching application on',
               'testFailure': 'Some tests failed.',
               'testPassed': 'All tests passed!'}


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


def check_result(value):
    if (set(value) != FIELDS or value['schemaVersion'] != 1 or value['platform'] != 'ios-simulator' or
            value['physicalImeVerified'] is not False or
            any(value[key] is not True for key in FIELDS - {'schemaVersion', 'platform', 'physicalImeVerified'})):
        raise Failure('ios_result_incomplete')
    return value


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
    source_root = Path(__file__).resolve().parents[1] / 'flutter'
    for relative in (TARGET, 'integration_test/direct_ssh_ui_steps.dart'):
        if (app / relative).is_symlink() or (app / relative).read_bytes() != (source_root / relative).read_bytes():
            raise Failure('ios_test_source_mismatch')
    output.mkdir(mode=0o700)
    cleanup = {'simulatorDeleted': False, 'fixtureClosed': False, 'flutterToolStopped': False,
               'rawLogsUploaded': False}
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': 'flutter-ios-simulator-ordinary-ssh',
              'status': 'failed', 'cleanup': cleanup, 'physicalImeVerified': False}
    from direct_ssh_fixture import DirectSshFixture
    fixture, device, process, private, phase, primary = DirectSshFixture(), None, None, None, 'runtime_selection', None
    try:
        runtimes = json.loads(command('xcrun', 'simctl', 'list', 'runtimes', '--json'))['runtimes']
        ios = [r for r in runtimes if r.get('isAvailable') and r.get('identifier', '').startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
        types = json.loads(command('xcrun', 'simctl', 'list', 'devicetypes', '--json'))['devicetypes']
        phones = [d for d in types if d.get('name', '').startswith('iPhone ')]
        if not ios or not phones:
            raise Failure('ios_simulator_runtime_or_phone_unavailable')
        runtime = sorted(ios, key=lambda r: [int(x) for x in r['version'].split('.')])[-1]
        phase = 'simulator_boot'
        for phone in reversed(phones):
            attempt = subprocess.run(['xcrun', 'simctl', 'create', 'herdr-direct-' + env['GITHUB_RUN_ID'],
                                      phone['identifier'], runtime['identifier']], capture_output=True, timeout=60)
            if attempt.returncode == 0:
                device = attempt.stdout.decode().strip()
                break
        if not device:
            raise Failure('ios_simulator_compatible_phone_unavailable')
        report['simulator'] = {'runtime': runtime['identifier'], 'runtimeVersion': runtime['version'], 'deviceType': phone['name']}
        if not re.fullmatch(r'[0-9A-Fa-f-]{36}', device):
            raise Failure('ios_simulator_id_invalid')
        command('xcrun', 'simctl', 'boot', device)
        command('xcrun', 'simctl', 'bootstatus', device, '-b', timeout=300)
        phase = 'fixture_start'
        with fixture:
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-ios-private-', dir=base))
            defines = private / 'defines.json'
            defines.write_text(json.dumps({'HERDR_IOS_DIRECT_SSH': '1', 'HERDR_IOS_RUN_ID': env['GITHUB_RUN_ID'],
                'HERDR_IOS_DIRECT_TARGET': json.dumps({'host': '127.0.0.1', 'port': fixture.port,
                    'username': fixture.username, 'password': fixture.password, 'fingerprint': fixture.fingerprint})}))
            defines.chmod(0o600)
            phase = 'driver_start'
            with (private / 'flutter-private.log').open('wb') as log:
                process = subprocess.Popen(['flutter', 'test', '--no-pub', '--reporter', 'expanded', '-d', device,
                    '--dart-define-from-file=' + str(defines), TARGET], cwd=app, env=env,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline, exchange, confirmed = time.monotonic() + 1200, None, False
                container_timeouts = 0
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
                    failure = read_json(exchange / 'failure.json') if exchange else None
                    if failure and re.fullmatch(r'[a-z_]{1,40}', failure.get('stage', '')):
                        report['failureStage'] = failure['stage']
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
        if device:
            subprocess.run(['xcrun', 'simctl', 'shutdown', device], capture_output=True, timeout=60)
            result = subprocess.run(['xcrun', 'simctl', 'delete', device], capture_output=True, timeout=60)
            cleanup['simulatorDeleted'] = result.returncode == 0
        if private:
            shutil.rmtree(private)
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
