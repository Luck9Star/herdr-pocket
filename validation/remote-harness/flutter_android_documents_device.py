#!/usr/bin/env python3
"""CI-only integration-test/real DocumentsUI round trip; no raw evidence is published."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from paired_gui import GuiFailure, owned_process
import flutter_android_documents_oracle as oracle
from flutter_android_documents_preflight import PACKAGE, SERIAL, Failure as AdbFailure, adb
from flutter_android_gui import (SystemImeFailure, parse_system_ime, public_file_pending, public_ime_diagnostic,
                                 wait_system_ime)
from tauri_android_config_document import (Picker, ARCHIVE, CORRUPT, DOWNLOADS, MAX_ARCHIVE,
                                           foreground, binary_file, wait_download_storage)

PASSWORD = 'fixture-document-passphrase'
STAGES = ('app_ready', 'initial19', 'cancel_picker', 'cancel_done', 'hide_export', 'save_picker', 'export_done',
          'control13', 'wrong_picker', 'hide_wrong', 'wrong_done', 'tampered_picker', 'hide_tampered', 'tampered_done',
          'correct_picker', 'hide_correct', 'preview', 'apply_dispatch', 'apply_done')
CATALOG = 'no_backup/herdr-hosts-v1/catalog.json'
ROOT = Path(__file__).resolve().parents[2]


def need(condition, code):
    if not condition:
        raise GuiFailure(code)


def wait_import_ime(read_dump):
    """Wait for two consecutive owned samples with either settled visibility."""
    deadline = time.monotonic() + 12
    previous = None
    last = {'formatVersion': 1, 'reason': 'no_sample'}
    attempts = 0
    while time.monotonic() < deadline and attempts < 100:
        attempts += 1
        try:
            sample = parse_system_ime(*read_dump(), PACKAGE)
        except SystemImeFailure as error:
            error.diagnostic['attempts'] = attempts
            if not error.retryable:
                raise
            last = error.diagnostic
            previous = None
        else:
            last = sample['diagnostic']
            state = last['visibility']
            if state in ('visible', 'hidden') and state == previous:
                return {**sample, 'diagnostic': {**last, 'attempts': attempts}}
            previous = state
        time.sleep(0.15)
    raise SystemImeFailure('android_system_ime_state_unconfirmed', {**last, 'attempts': attempts, 'timedOut': True})


def dismiss_document_ime(stage, launcher):
    def read_dump():
        return (adb('shell', 'dumpsys', 'input_method').decode('utf-8', 'replace'),
                adb('shell', 'dumpsys', 'window', 'displays').decode('utf-8', 'replace'))

    need(launcher and foreground() == launcher, 'ime_foreground_unconfirmed')
    # Export separately proves an actual IME show/hide. Import only needs a
    # clear viewport after fixture entry and can return with the IME hidden.
    before = wait_system_ime(read_dump, PACKAGE, True) if stage == 'hide_export' else wait_import_ime(read_dump)
    need(foreground() == launcher, 'ime_foreground_unconfirmed')
    detail = {'outcome': 'already_hidden', 'before': public_ime_diagnostic(before['diagnostic'])}
    if before['visible']:
        adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
        after = wait_system_ime(read_dump, PACKAGE, False)
        need(foreground() == launcher, 'ime_foreground_unconfirmed')
        detail.update(outcome='system_back', after=public_ime_diagnostic(after['diagnostic']))
    return detail


def device_catalog():
    raw = adb('exec-out', 'run-as', PACKAGE, 'head', '-c', str(oracle.MAX_CATALOG + 1), CATALOG)
    need(0 < len(raw) <= oracle.MAX_CATALOG, 'catalog_read_failed')
    return raw


def exchange_read(relative):
    # A single known app-private public JSON file; content is validated below and never logged.
    try:
        p = subprocess.run(['adb', '-s', SERIAL, 'shell', '-T', 'run-as', PACKAGE, 'head', '-c', '257', relative],
                           capture_output=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        raise GuiFailure('exchange_read_timeout') from None
    except OSError:
        raise GuiFailure('exchange_read_unavailable') from None
    if public_file_pending(p, relative):
        return None
    need(not p.returncode and len(p.stdout) <= 256 and not p.stderr, 'exchange_read_failed')
    try:
        value = json.loads(p.stdout)
    except (ValueError, UnicodeError):
        raise GuiFailure('exchange_invalid') from None
    need(isinstance(value, dict) and set(value) == {'stage'} and value['stage'] in STAGES, 'exchange_invalid')
    return value['stage']


def acknowledge(relative, stage):
    # Unknown writes are never replayed; only fixed public stage names cross stdin.
    value = json.dumps({'stage': stage}, separators=(',', ':')).encode()
    try:
        p = subprocess.run(['adb', '-s', SERIAL, 'shell', '-T', 'run-as', PACKAGE, 'tee', relative + '/ack.new'],
                           input=value, capture_output=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        raise GuiFailure('ack_write_timeout') from None
    except OSError:
        raise GuiFailure('ack_write_unavailable') from None
    need(p.returncode == 0 and p.stdout == value and not p.stderr, 'ack_write_unconfirmed')
    adb('shell', 'run-as', PACKAGE, 'mv', relative + '/ack.new', relative + '/ack.json')


def adb_failure_report(error):
    operations = {'devices', 'window', 'hierarchy_dump', 'package_list', 'package_path', 'device_property',
                  'current_user', 'launch', 'tap', 'scratch_check', 'scratch_remove', 'file_read',
                  'install', 'uninstall', 'other'}
    outcomes = {'timeout', 'os_error', 'nonzero', 'output_limit'}
    result = {'error': 'adb_operation_failed'}
    if error.operation in operations and error.outcome in outcomes:
        result['commandDiagnostic'] = {'operation': error.operation, 'outcome': error.outcome}
    return result


def ensure_running(process, report):
    code = process.poll()
    if code is not None:
        if type(code) is int and -255 <= code <= 255:
            report['flutterExitCode'] = code
        raise GuiFailure('flutter_process_exited')


def checked_cleanup(report, name, action):
    try:
        action()
        report['cleanup'][name] = True
        report['cleanupDiagnostics'][name] = {'outcome': 'confirmed'}
    except AdbFailure as error:
        report['cleanupDiagnostics'][name] = {'outcome': 'adb_failed'}
        diagnostic = adb_failure_report(error).get('commandDiagnostic')
        if diagnostic:
            report['cleanupDiagnostics'][name]['commandDiagnostic'] = diagnostic
    except Exception:
        report['cleanupDiagnostics'][name] = {'outcome': 'unconfirmed'}


def verify_tool_stopped(process):
    if process is None or process.poll() is None:
        raise GuiFailure('flutter_tool_unconfirmed')
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return
    raise GuiFailure('flutter_tool_unconfirmed')


def installed_digest(expected, expected_size, report):
    entries = adb('shell', 'pm', 'path', PACKAGE).decode().splitlines()
    need(len(entries) == 1 and re.fullmatch(r'package:/data/app/[A-Za-z0-9_./=+~\-]+/base\.apk', entries[0]),
         'installed_path_invalid')
    path = entries[0][8:]
    proof = {'hostBytes': expected_size, 'hostSha256': expected, 'attempts': []}
    report['apkVerification'] = proof

    def read(prefix, operation):
        args = (['/system/bin/stat', '-c', '%s', path] if operation == 'size' else
                ['/system/bin/sha256sum', path])
        try:
            result = subprocess.run(['adb', '-s', SERIAL, 'shell', '-T', *prefix, *args],
                                    capture_output=True, timeout=90, check=False)
        except subprocess.TimeoutExpired:
            return None, 'timeout'
        except OSError:
            return None, 'unavailable'
        if result.returncode != 0:
            return None, 'nonzero'
        if result.stderr or len(result.stdout) > 1024:
            return None, 'invalid_output'
        value = result.stdout.rstrip(b'\r\n')
        if operation == 'size':
            if not re.fullmatch(rb'[1-9][0-9]{0,8}', value):
                return None, 'invalid_output'
            return int(value), 'ok'
        expected_suffix = b'  ' + path.encode('ascii')
        if not value.endswith(expected_suffix) or not re.fullmatch(rb'[0-9a-f]{64}', value[:-len(expected_suffix)]):
            return None, 'invalid_output'
        return value[:64].decode('ascii'), 'ok'

    # Android shell v2 preserves the remote exit status. If shell lacks access,
    # the owned debug app's run-as identity gets one read-only attempt.
    for owner, prefix in (('shell', []), ('run_as', ['run-as', PACKAGE])):
        attempt = {'reader': owner}
        proof['attempts'].append(attempt)
        size, attempt['size'] = read(prefix, 'size')
        if size is None:
            continue
        attempt['bytes'] = size
        digest, attempt['sha256'] = read(prefix, 'sha256')
        if digest is None:
            continue
        attempt['digest'] = digest
        # A valid mismatch is final; do not select a more convenient reader.
        need(size == expected_size and digest == expected, 'installed_hash_mismatch')
        proof['matched'] = True
        return
    raise GuiFailure('installed_hash_unavailable')


def check_environment(app, output):
    env = os.environ
    temp = Path(env.get('RUNNER_TEMP', '/nonexistent')).resolve()
    avd = Path(env.get('ANDROID_AVD_HOME', '/nonexistent')).resolve()
    need(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REF', '').startswith('refs/heads/codex/')
         and re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ID', ''))
         and re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))
         and env.get('ANDROID_SERIAL') == SERIAL and avd.is_dir() and avd != temp and avd.is_relative_to(temp)
         and app.is_relative_to(temp) and output.is_relative_to(temp) and output != temp, 'unsafe_runner')
    source = ROOT / 'validation/remote-harness/flutter_android_documents_device_test.dart'
    target = app / 'integration_test/flutter_android_documents_device_test.dart'
    need(source.is_file() and target.is_file() and source.read_bytes() == target.read_bytes(), 'test_source_mismatch')
    subprocess.run(['python3', str(ROOT / 'validation/flutter/tool/android_device_test.py'),
                    'verify-lock', '--destination', str(app)], check=True, capture_output=True, timeout=60)
    devices = subprocess.run(['adb', 'devices'], capture_output=True, check=True, timeout=10).stdout.decode().splitlines()[1:]
    need([row.split() for row in devices if row.strip()] == [[SERIAL, 'device']]
         and adb('shell', 'getprop', 'ro.kernel.qemu').strip() == b'1'
         and adb('shell', 'getprop', 'ro.build.version.sdk').strip() == b'35'
         and adb('shell', 'am', 'get-current-user').strip() == b'0', 'device_unconfirmed')
    need(not adb('shell', 'pm', 'list', 'packages', PACKAGE).strip(), 'package_already_present')
    return temp


def drive(app, output):
    temp = check_environment(app, output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run_id = os.environ['GITHUB_RUN_ID']
    relative = 'cache/herdr-documents-' + run_id
    apk = app / 'build/app/outputs/flutter-apk/app-debug.apk'
    need(apk.is_file() and not apk.is_symlink(), 'apk_missing')
    prebuilt_hash = hashlib.sha256(apk.read_bytes()).hexdigest()
    apk_hash = None
    report = {'schemaVersion': 1, 'sourceSHA': os.environ['GITHUB_SHA'], 'status': 'failed',
              'binary': 'flutter-integration-test', 'executionMode': 'flutter-test-vm-listener',
              'prebuiltApkSha256': prebuilt_hash, 'stage': 'setup',
              'checkpoints': [], 'pickerOpens': 0,
              'cleanup': {'package': False, 'folder': False, 'hierarchy': False, 'flutterTool': False}}
    ledger = oracle.Ledger()
    picker = Picker(report)
    folder = 'hp-config-' + secrets.token_hex(12)
    path = DOWNLOADS + '/' + folder
    folder_owned = False
    folder_attempted = False
    app_attempted = False
    process = None
    try:
        adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
        need(adb('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard').strip() == b'1', 'ime_fixture_unconfirmed')
        wait_download_storage(report)
        folder_attempted = True
        adb('shell', 'mkdir', path)
        folder_owned = True
        cmd = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
               '--dart-define=HERDR_ANDROID_DOCUMENTS=1', '--dart-define=HERDR_ANDROID_DOCUMENTS_RUN_ID=' + run_id,
               'integration_test/flutter_android_documents_device_test.dart']
        app_attempted = True
        with owned_process(cmd, cwd=app, env=os.environ, log=temp / 'flutter-documents-private.log') as process:
            prior = None
            for stage in STAGES:
                report['stage'] = stage
                deadline = time.monotonic() + 180
                while True:
                    ensure_running(process, report)
                    current = exchange_read(relative + '/checkpoint.json')
                    if current == stage:
                        break
                    need(current is None or current == prior, 'checkpoint_order_invalid')
                    need(time.monotonic() < deadline, 'checkpoint_timeout')
                    time.sleep(0.3)
                if stage == 'app_ready':
                    # flutter test uses a generated listener entrypoint and can rebuild the
                    # APK. Bind the actual test binary, not the separate prebuild.
                    apk_bytes = apk.read_bytes()
                    apk_hash = hashlib.sha256(apk_bytes).hexdigest()
                    report['apkSha256'] = apk_hash
                    installed_digest(apk_hash, len(apk_bytes), report)
                    picker.launcher = foreground()
                    need(picker.launcher and picker.launcher.split('/')[0] == PACKAGE, 'foreground_unconfirmed')
                    report['installedHashMatched'] = True
                elif stage in ('initial19', 'control13', 'wrong_done', 'tampered_done', 'preview', 'apply_done'):
                    ledger.record({'wrong_done': 'wrong_password', 'tampered_done': 'tampered',
                                   'apply_done': 'apply'}.get(stage, stage), device_catalog())
                    if stage == 'apply_done':
                        report['applyConfirmed'] = True
                elif stage == 'cancel_done':
                    ledger.record('cancel', device_catalog())
                    need(not adb('shell', 'ls', '-A', path).strip(), 'folder_changed')
                elif stage == 'export_done':
                    ledger.record('export', device_catalog())
                    need(adb('shell', 'ls', '-A', path).decode().strip() == ARCHIVE, 'archive_missing')
                    raw = binary_file([], path + '/' + ARCHIVE, MAX_ARCHIVE, 'archive_read_failed')
                    oracle.archive(raw, PASSWORD)
                    damaged = raw[:-1] + bytes([raw[-1] ^ 1])
                    try:
                        oracle.archive(damaged, PASSWORD)
                    except GuiFailure:
                        pass
                    else:
                        raise GuiFailure('tamper_guard_failed')
                    private = temp / ('flutter-damaged-' + secrets.token_hex(12))
                    try:
                        private.write_bytes(damaged)
                        adb('push', str(private), path + '/' + CORRUPT)
                    finally:
                        private.unlink(missing_ok=True)
                    report['archive'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                elif stage.startswith('hide_'):
                    observation = dismiss_document_ime(stage, picker.launcher)
                    report.setdefault('imeStages', {})[stage] = observation
                elif stage == 'apply_dispatch':
                    need(device_catalog() == ledger.reference, 'catalog_changed')
                    ledger.begin_apply()
                    report['applyAuthorized'] = True
                elif stage.endswith('_picker'):
                    picker.enter()
                    if stage == 'cancel_picker':
                        picker.cancel()
                    else:
                        picker.directory(folder)
                        ensure_running(process, report)
                        if stage == 'save_picker':
                            picker.save(folder)
                        else:
                            picker.open(folder, CORRUPT if stage == 'tampered_picker' else ARCHIVE)
                    picker.wait_return()
                acknowledge(relative, stage)
                report['checkpoints'].append(stage)
                prior = stage
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                raise GuiFailure('flutter_exit_timeout') from None
            need(code == 0, 'flutter_test_failed')
            need(apk_hash is not None and hashlib.sha256(apk.read_bytes()).hexdigest() == apk_hash,
                 'built_apk_changed')
            report['status'] = 'passed'
    except AdbFailure as error:
        report.update(adb_failure_report(error))
    except SystemImeFailure as error:
        report['error'] = str(error)
        report['imeDiagnostic'] = public_ime_diagnostic(error.diagnostic)
    except OSError:
        report['error'] = 'os_operation_failed'
    except Exception as error:
        report['error'] = str(error) if isinstance(error, GuiFailure) and re.fullmatch(r'[a-z_]+', str(error)) else 'driver_failed'
    finally:
        cleanup_facts = report['cleanupDiagnostics'] = {}

        def hierarchy_absent():
            adb('shell', 'test', '!', '-e', picker.scratch)
            adb('shell', 'test', '!', '-L', picker.scratch)

        def package_absent():
            if adb('shell', 'pm', 'list', 'packages', PACKAGE).strip():
                adb('uninstall', PACKAGE, timeout=60)
            need(not adb('shell', 'pm', 'list', 'packages', PACKAGE).strip(), 'package_cleanup_unconfirmed')

        def folder_absent():
            adb('shell', 'rm', '-f', path + '/' + ARCHIVE, path + '/' + CORRUPT)
            adb('shell', 'rmdir', path)
            adb('shell', 'test', '!', '-e', path)

        if process is not None:
            checked_cleanup(report, 'flutterTool', lambda: verify_tool_stopped(process))
        else:
            cleanup_facts['flutterTool'] = {'outcome': 'not_started' if not app_attempted else 'unconfirmed'}
        checked_cleanup(report, 'hierarchy', hierarchy_absent)
        if picker.scratch_cleanup_failed:
            cleanup_facts['hierarchy']['earlierFailure'] = True
        if app_attempted:
            checked_cleanup(report, 'package', package_absent)
        else:
            cleanup_facts['package'] = {'outcome': 'not_attempted'}
        if folder_owned:
            checked_cleanup(report, 'folder', folder_absent)
        else:
            cleanup_facts['folder'] = {'outcome': 'unconfirmed' if folder_attempted else 'not_attempted'}
        if not all(report['cleanup'].values()):
            report['status'] = 'failed'
        (output / 'flutter-documents-roundtrip.json').write_text(json.dumps(report, indent=2) + '\n')
    need(report['status'] == 'passed', 'roundtrip_failed')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    drive(args.project.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
