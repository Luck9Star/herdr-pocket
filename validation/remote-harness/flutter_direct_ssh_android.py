#!/usr/bin/env python3
"""Explicit CI-only Android ordinary SSH UI acceptance on one disposable AVD.

Only sanitized result JSON and post-credential screenshots are exported. Private
build defines and Flutter logs remain in RUNNER_TEMP and are never artifacts.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
TARGET = 'integration_test/android_direct_ssh_test.dart'
PUBLIC_FIELDS = {'schemaVersion', 'platform', 'homepageEntry', 'fingerprintMatched', 'explicitTrustRequired',
                 'realTerminalView', 'normalTextInputCommit', 'remoteEchoVisible', 'disconnectUiConfirmed',
                 'credentialsCleared', 'physicalImeVerified'}


class Failure(ValueError):
    pass


def checked_paths(app, output, env):
    if (env.get('GITHUB_ACTIONS') != 'true' or not env.get('GITHUB_REF', '').startswith('refs/heads/codex/') or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')) or
            env.get('ANDROID_SERIAL') != SERIAL or not env.get('RUNNER_TEMP')):
        raise Failure('direct_android_ci_and_owned_avd_required')
    base = Path(env['RUNNER_TEMP']).resolve()
    app, output = Path(app).resolve(), Path(output).resolve()
    if app == base or output == base or not app.is_relative_to(base) or not output.is_relative_to(base) or app == output:
        raise Failure('direct_android_paths_not_isolated')
    if not app.is_dir() or (app / '.git').exists() or output.exists():
        raise Failure('direct_android_app_or_output_not_fresh')
    return app, output


def safe_result(raw):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_device_result_not_json') from None
    if not isinstance(result, dict) or set(result) != PUBLIC_FIELDS or result['schemaVersion'] != 1 or result['platform'] != 'android-api35-emulator':
        raise Failure('direct_android_invalid_device_result')
    if result['physicalImeVerified'] is not False or any(result[key] is not True for key in PUBLIC_FIELDS - {'schemaVersion', 'platform', 'physicalImeVerified'}):
        raise Failure('direct_android_incomplete_device_result')
    return result


def adb(*args, check=True, data=None):
    result = subprocess.run(['adb', '-s', SERIAL, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, input=data, timeout=30)
    if check and result.returncode:
        raise Failure('direct_android_adb_failed')
    return result


def text(*args):
    return adb(*args).stdout.decode().strip()


def package_present():
    return text('shell', 'pm', 'list', 'packages', PACKAGE) == 'package:' + PACKAGE


def forward_set():
    return set(text('forward', '--list').splitlines())


def checked_public_reply(reply, relative, limit):
    # Share the already verified pending diagnostics from the paired Android
    # runner. exec-out can report status zero with run-as errors as stdout.
    from flutter_android_gui import public_file_pending
    if public_file_pending(reply, relative):
        return None
    if len(reply.stdout) > limit or len(reply.stderr) > limit:
        raise Failure('direct_android_public_json_oversize')
    if reply.returncode or reply.stderr:
        raise Failure('direct_android_public_json_read_failed')
    if not reply.stdout.strip():
        raise Failure('direct_android_public_json_empty')
    try:
        value = json.loads(reply.stdout)
    except (ValueError, UnicodeError):
        raise Failure('direct_android_public_json_invalid') from None
    if not isinstance(value, dict):
        raise Failure('direct_android_public_json_invalid')
    return value


def read_public_json(relative, limit=4096):
    if not re.fullmatch(r'cache/herdr-direct-ssh-[0-9]+/(?:result|stage|failure)\.json', relative):
        raise Failure('direct_android_public_path_invalid')
    if not package_present():
        return None
    exists = adb('shell', '-T', 'run-as', PACKAGE, 'test', '-f', relative, check=False)
    if exists.returncode == 1 and not exists.stdout.strip() and not exists.stderr.strip():
        return None
    from flutter_android_gui import public_file_pending
    if public_file_pending(exists, relative):
        return None
    if exists.returncode or exists.stdout.strip() or exists.stderr.strip():
        raise Failure('direct_android_public_file_probe_failed')
    reply = adb('shell', '-T', 'run-as', PACKAGE, 'head', '-c', str(limit + 1), relative, check=False)
    return checked_public_reply(reply, relative, limit)


def safe_failure(error, phase):
    # Exception classes and source locations are diagnostic facts; exception
    # messages/locals may contain credentials and must never be exported.
    frames = []
    trace = error.__traceback__
    while trace is not None:
        file = Path(trace.tb_frame.f_code.co_filename).name
        if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', file):
            frames.append({'file': file, 'line': trace.tb_lineno})
        trace = trace.tb_next
    kind = type(error).__name__
    return {'phase': phase, 'exceptionClass': kind if re.fullmatch(r'[A-Za-z0-9_]{1,80}', kind) else 'Exception',
            'sourceLocations': frames[-4:]}


def verify_prepared(app, env):
    tool_path = ROOT / 'validation/flutter/tool/android_device_test.py'
    sys.path.insert(0, str(tool_path.parent))
    spec = importlib.util.spec_from_file_location('herdr_android_device_preparation', tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_lock(app, env)
    if (app / TARGET).is_symlink() or not (app / TARGET).is_file() or (app / TARGET).read_bytes() != (ROOT / 'validation/flutter' / TARGET).read_bytes():
        raise Failure('direct_android_integration_source_mismatch')
    version = json.loads(subprocess.run(['flutter', '--version', '--machine'], capture_output=True, check=True, timeout=60).stdout)
    if version.get('frameworkRevision') != module.FLUTTER_COMMIT or version.get('frameworkVersion') != module.FLUTTER_VERSION:
        raise Failure('direct_android_flutter_version_mismatch')


def run(args, env):
    app, output = checked_paths(args.project, args.output, env)
    verify_prepared(app, env)
    devices = [line.split()[:2] for line in text('devices').splitlines()[1:] if line.strip()]
    if devices != [[SERIAL, 'device']] or text('shell', 'getprop', 'ro.kernel.qemu') != '1' or text('shell', 'getprop', 'ro.build.version.sdk') != '35' or text('shell', 'am', 'get-current-user') != '0':
        raise Failure('direct_android_not_single_api35_emulator')
    if package_present():
        raise Failure('direct_android_package_already_present')
    output.mkdir(mode=0o700)
    before = forward_set()
    cleanup = {'reverseRemoved': False, 'packageRemoved': False, 'ownedForwardsRemoved': False,
               'fixtureClosed': False, 'flutterToolStopped': False, 'rawLogsUploaded': False}
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'kind': 'flutter-android-ordinary-ssh',
              'status': 'failed', 'cleanup': cleanup, 'physicalImeVerified': False}
    primary = None
    phase = 'fixture_start'
    from direct_ssh_fixture import DirectSshFixture
    fixture = DirectSshFixture()
    reverse_added = False
    process = None
    private = None
    try:
        with fixture:
            phase = 'reverse_setup'
            reverse = 'tcp:' + str(fixture.port)
            if any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines()):
                raise Failure('direct_android_reverse_already_present')
            adb('reverse', reverse, reverse)
            reverse_added = True
            phase = 'private_defines'
            private = Path(tempfile.mkdtemp(prefix='herdr-direct-android-private-', dir=env['RUNNER_TEMP']))
            defines = private / 'defines.json'
            defines.write_text(json.dumps({'HERDR_ANDROID_DIRECT_SSH': '1', 'HERDR_ANDROID_RUN_ID': env['GITHUB_RUN_ID'],
                'HERDR_ANDROID_DIRECT_TARGET': json.dumps({'host': '127.0.0.1', 'port': fixture.port,
                    'username': fixture.username, 'password': fixture.password, 'fingerprint': fixture.fingerprint})}))
            defines.chmod(0o600)
            relative = 'cache/herdr-direct-ssh-' + env['GITHUB_RUN_ID']
            command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
                       '--dart-define-from-file=' + str(defines), TARGET]
            phase = 'driver_start'
            with (private / 'flutter-private.log').open('wb') as log:
                process = subprocess.Popen(command, cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + 1200
                peer_confirmed = False
                while process.poll() is None and time.monotonic() < deadline:
                    phase = 'await_device_result'
                    public = read_public_json(relative + '/result.json')
                    if public is not None:
                        safe_result(json.dumps(public))
                        phase = 'peer_close_confirmation'
                        if not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed'):
                            raise Failure('direct_android_remote_input_or_close_missing')
                        if process.poll() is not None:
                            raise Failure('direct_android_driver_exited_before_peer_confirmation')
                        # The device test is still alive and waiting here, so
                        # driver shutdown cannot masquerade as the UI's close.
                        reply = b'{"protocolAccepted":true,"peerClosedBeforeDriverExit":true}'
                        pending = relative + '/peer-confirmed.new'
                        adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=reply)
                        adb('shell', 'run-as', PACKAGE, 'mv', pending, relative + '/peer-confirmed.json')
                        peer_confirmed = True
                        report['peerClosedBeforeDriverExit'] = True
                        break
                    time.sleep(.5)
                phase = 'await_driver_exit'
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Failure('direct_android_flutter_timeout') from None
                if code == 0 and not peer_confirmed:
                    raise Failure('direct_android_peer_confirmation_missing')
            cleanup['flutterToolStopped'] = True
            if code:
                # Stage is an enum from our test; never export the raw test log.
                failure = read_public_json(relative + '/failure.json', 256)
                if failure is not None:
                    stage = failure.get('stage', '')
                    if isinstance(stage, str) and re.fullmatch(r'[a-z_]{1,40}', stage):
                        report['failureStage'] = stage
                raise Failure('direct_android_device_test_failed')
            phase = 'read_device_result'
            public = read_public_json(relative + '/result.json')
            if public is None:
                raise Failure('direct_android_device_result_missing')
            report['device'] = safe_result(json.dumps(public))
            if not fixture.wait_for('markerReceived') or not fixture.wait_for('sessionClosed'):
                raise Failure('direct_android_remote_input_or_close_missing')
            evidence = fixture.snapshot()
            if not all(evidence[name] for name in ('authAccepted', 'ptyRequested', 'shellRequested', 'markerReceived', 'sessionClosed')):
                raise Failure('direct_android_protocol_evidence_incomplete')
            report['protocol'] = evidence
            phase = 'read_screenshots'
            for name in ('home', 'connected', 'disconnected'):
                png = adb('exec-out', 'run-as', PACKAGE, 'cat', relative + '/' + name + '.png').stdout
                if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8_000_000:
                    raise Failure('direct_android_screenshot_invalid')
                (output / (name + '.png')).write_bytes(png)
            report['status'] = 'passed'
    except Exception as error:
        primary = str(error) if isinstance(error, Failure) else 'direct_android_runner_failed'
        report['failureCode'] = primary
        report['diagnostic'] = safe_failure(error, phase)
    finally:
        report['lastPhase'] = phase
        report['protocol'] = fixture.snapshot()
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        try:
            if reverse_added:
                adb('reverse', '--remove', reverse)
            cleanup['reverseRemoved'] = not reverse_added or not any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines())
            if package_present():
                adb('shell', 'am', 'force-stop', PACKAGE)
                adb('uninstall', PACKAGE)
            cleanup['packageRemoved'] = not package_present()
            for line in forward_set() - before:
                parts = line.split()
                if len(parts) == 3 and parts[0] == SERIAL and re.fullmatch(r'tcp:\d+', parts[1]):
                    adb('forward', '--remove', parts[1])
            cleanup['ownedForwardsRemoved'] = forward_set() == before
        except Failure:
            report['cleanupCode'] = 'direct_android_adb_cleanup_failed'
        fixture.close()
        cleanup['fixtureClosed'] = fixture.snapshot()['connectionsClosed']
        if not all(cleanup[key] for key in cleanup if key != 'rawLogsUploaded'):
            report['status'] = 'failed'
            report['cleanupCode'] = 'direct_android_cleanup_incomplete'
        if private is not None:
            shutil.rmtree(private)
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'passed':
        raise Failure(primary or 'direct_android_cleanup_incomplete')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        report = run(args, dict(os.environ))
        print(json.dumps({'status': report['status'], 'kind': report['kind']}))
    except Exception as error:
        print(str(error) if isinstance(error, Failure) else 'direct_android_runner_failed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
