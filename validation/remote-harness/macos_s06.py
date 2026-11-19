"""Run the stock paired S06 XCUITest on an owned GitHub-hosted macOS window."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from macos_secure_xcuitest import install_test_semantics_hook, prepare
from paired_dual_demo import prepared_pairing_hosts
from paired_gui import GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for
from s06_tauri_gui import peer_connection_evidence

HERE = Path(__file__).resolve().parent
HERDR_SHA256 = 'fb77c2232a05a8035421382c894392f4174e4e38a18e48af3dd0290157c3a7e2'
SESSIONS = {'et': 's06-a', 'ts': 's06-b'}
MARKERS = {'et': 'HPS06A', 'ts': 'HPS06B'}
CHECKS = ('homepage', 'reviewedPairings', 'twoVisibleTargets', 'bothTicksAdvanced', 'stockControlsDisabled',
          'keyboardFocus', 'narrowStowed', 'originalSidesRestored', 'explicitResume', 'stoppedBoth',
          'localIdentitiesRemoved')
STAGES = ('display', 'homepage', 'pairA', 'pairB', 'keyA', 'keyB', 'connectA', 'connectB',
          'split', 'frames', 'keyboard', 'resize', 'resume', 'stop', 'remove')


def prepare_test(app, exchange):
    """Only change the generated native test target and opt-in AX notification."""
    template = (HERE / 'macos_s06_xcuitest.swift').read_text()
    placeholder = '__HP_S06_EXCHANGE_BASE64__'
    if template.count(placeholder) != 1:
        raise GuiFailure('s06_native_test_template_invalid')
    prepare(app)
    install_test_semantics_hook(app)
    payload = base64.b64encode(os.fsencode(exchange)).decode('ascii')
    (app / 'macos/RunnerTests/RunnerTests.swift').write_text(template.replace(placeholder, payload))


def stock_binary(binary):
    size = binary.stat().st_size
    if not 0 < size <= 100 * 1024 * 1024 or hashlib.sha256(binary.read_bytes()).hexdigest() != HERDR_SHA256:
        raise GuiFailure('s06_stock_binary_digest_mismatch')


@contextmanager
def fixtures(binary, base):
    stock_binary(binary)

    def set_marker(stage):
        for role, marker in MARKERS.items():
            if stage != role + '_capture_start':
                continue
            root = base / role
            # The copied, owned capture program generates both the marker and
            # changing ticks inside herdr's actual PTY. No UI frame injection.
            script = root / 'capture_input.py'
            text = script.read_text()
            original = r'\x1b[23;1HSynthetic observe tick'
            if text.count(original) != 1:
                raise GuiFailure('s06_capture_template_invalid')
            script.write_text(text.replace(original, r'\x1b[12;1H' + marker))
            fixture = {'frames': [{'data': '\x1b[2J\x1b[HNative S06 owned peer\r\n'}]}
            (root / 'terminal-fixture.json').write_text(json.dumps(fixture))

    with prepared_pairing_hosts(binary, base, set_marker, sessions=SESSIONS) as (targets, children, metadata):
        configs = [{**target.config, 'fingerprint': target.host.pin, 'marker': MARKERS[role],
                    'terminalId': fixture_terminal_id(target.config)} for role, target in targets.items()]
        if (len({value['paneId'] for value in configs}) != 1 or
                len({value['terminalId'] for value in configs}) != 2 or
                len({value['port'] for value in configs}) != 2):
            raise GuiFailure('s06_fixture_identity_invalid')
        yield targets, children, metadata, configs


def write_exchange(path, payload):
    pending = path.with_suffix('.new')
    with pending.open('xb') as stream:
        stream.write(payload)
    pending.replace(path)


def native_stage(exchange):
    try:
        phase = bounded_wire(exchange / 'stage', 32).decode('ascii')
        return phase if phase in STAGES else None
    except (GuiFailure, OSError, UnicodeError):
        return None


def checked_ui_result(raw):
    if (not isinstance(raw, dict) or set(raw) != {'checks', 'widths'}
            or not isinstance(raw['checks'], dict) or set(raw['checks']) != set(CHECKS)
            or any(raw['checks'][name] is not True for name in CHECKS)):
        raise GuiFailure('s06_native_ui_checks_incomplete')
    widths = raw['widths']
    if (not isinstance(widths, list) or len(widths) != 3 or
            any(type(value) is not int or abs(value - expected) > 2
                for value, expected in zip(widths, (1440, 700, 1440)))):
        raise GuiFailure('s06_native_window_widths_invalid')
    return raw


def final_pty(root):
    data = json.loads(bounded_wire(root / 'pty-size.json', 2048))
    expected = {'schemaVersion': 1, 'state': 2, 'endReason': 1, 'signalAvailable': 1, 'signalsMayCoalesce': 1,
                'changes': 0, 'readErrors': 0, 'captureErrors': 0, 'winchHandlers': 0,
                'signalSamples': 0, 'terminationSignal': 0}
    positive = ('initialRows', 'initialColumns', 'rows', 'columns', 'samples', 'elapsedMs', 'maxSampleGapMs')
    if (not isinstance(data, dict) or any(type(data.get(key)) is not int for key in (*expected, *positive))
            or any(data[key] != value for key, value in expected.items())
            or not 1 <= data['rows'] == data['initialRows'] <= 65535
            or not 1 <= data['columns'] == data['initialColumns'] <= 65535
            or data['samples'] < 3 or data['elapsedMs'] < 1000 or not 0 <= data['maxSampleGapMs'] <= 1500):
        raise GuiFailure('s06_native_pty_incomplete_or_changed')
    return {key: data[key] for key in ('rows', 'columns', 'samples', 'elapsedMs', 'maxSampleGapMs', 'changes')}


def requests_and_disconnect(proc, exchange, targets):
    reviewed = {}
    audits = None
    deadline = time.monotonic() + 750
    while proc.poll() is None and time.monotonic() < deadline:
        for index, target in enumerate(targets.values()):
            request = exchange / f'request-{index}.json'
            if not request.is_file() or index in reviewed:
                continue
            raw = bounded_wire(request, 2048)
            facts = target.review(raw)
            if any(facts['deviceFingerprint'] == item['deviceFingerprint'] or
                   facts['requestId'] == item['requestId'] for item in reviewed.values()):
                raise GuiFailure('s06_device_identity_reused')
            response = target.approve(raw, request_id=facts['requestId'],
                                      device_fingerprint=facts['deviceFingerprint'], reviewed=True)
            reviewed[index] = facts
            write_exchange(exchange / f'response-{index}.json', response)
        if (audits is None and len(reviewed) == 2 and (exchange / 'stop-requested').is_file() and
                all(peer_connection_evidence(target.approval) == {'authenticationCount': 1, 'closed': True}
                    for target in targets.values())):
            audits = [target.audit(b'') for target in targets.values()]
            if any(item['acceptedSessions'] != 1 or item['approvedDeviceSessions'] != 1 or
                   item['otherAcceptedDeviceSessions'] != 0 for item in audits):
                raise GuiFailure('s06_native_peer_authentication_mismatch')
            write_exchange(exchange / 'peers-closed', b'1')
        time.sleep(.1)
    if proc.poll() != 0:
        raise GuiFailure('s06_native_test_timeout' if proc.poll() is None else 's06_native_xcuitest_failed')
    if audits is None:
        raise GuiFailure('s06_native_live_peer_close_missing')
    return audits


def isolated_runner(app, output):
    env = os.environ
    sha = env.get('GITHUB_SHA', '')
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or env.get('RUNNER_OS') != 'macOS' or env.get('RUNNER_ARCH') != 'ARM64'
            or env.get('GITHUB_REF') != 'refs/heads/codex/macos-s06-native-window'
            or re.fullmatch(r'[a-f0-9]{40}', sha) is None or os.geteuid() == 0):
        raise GuiFailure('s06_native_requires_isolated_arm64_runner')
    root = Path(env['RUNNER_TEMP']).resolve(strict=True)
    if (app.resolve() != root / 'macos-s06-flutter' or output.resolve() != root / 'macos-s06-evidence'
            or app.is_symlink() or output.exists() or output.is_symlink()):
        raise GuiFailure('s06_native_runner_paths_invalid')
    return sha


def run(app, binary, output):
    source = isolated_runner(app, output)
    output.mkdir(mode=0o700)
    result = {'schemaVersion': 1, 'status': 'failed', 'sourceSHA': source, 'mode': 'stock',
              'scope': 'native macOS Flutter window with real paired loopback OpenSSH/herdr'}
    stage = 'build'
    try:
        stock_binary(binary)
        with tempfile.TemporaryDirectory(prefix='hpns06-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            exchange = root / 'exchange'
            exchange.mkdir(mode=0o700)
            prepare_test(app, exchange)
            xcode = ['xcodebuild', '-workspace', str(app / 'macos/Runner.xcworkspace'),
                     '-scheme', 'Runner', '-configuration', 'Debug', '-destination', 'platform=macOS',
                     '-derivedDataPath', str(root / 'derived'), '-parallel-testing-enabled', 'NO']
            with owned_process(xcode + ['build-for-testing'], cwd=app, env=os.environ,
                               log=root / 'build-private.log') as build:
                if build.wait(timeout=900) != 0:
                    raise GuiFailure('s06_native_test_build_failed')
            stage = 'fixture'
            with fixtures(binary, root) as (targets, children, metadata, configs):
                write_exchange(exchange / 'fixture.json', json.dumps(configs).encode())
                stage = 'test'
                try:
                    with owned_process(xcode + ['-resultBundlePath', str(root / 'private.xcresult'),
                                                'test-without-building'],
                                       cwd=app, env=os.environ, log=root / 'test-private.log') as proc:
                        audit = requests_and_disconnect(proc, exchange, targets)
                finally:
                    if last := native_stage(exchange):
                        result['nativeStage'] = last
                ui = checked_ui_result(json.loads(bounded_wire(exchange / 'ui.json', 2048)))
                if any(fixture_terminal_id(target.config) != config['terminalId']
                       for target, config in zip(targets.values(), configs)):
                    raise GuiFailure('s06_native_terminal_binding_changed')
                stage = 'cleanup'
            pty = [final_pty(target.root) for target in targets.values()]
            if (any(child.poll() is None for child in children) or
                    any(bounded_wire(target.root / 'authorized_keys', 4096)
                        or bounded_wire(target.root / 'received.bin', 4096)
                        or (target.root / 'capture-running').exists()
                        or target.approval.revocation_response is None for target in targets.values())):
                raise GuiFailure('s06_native_cleanup_incomplete')
        if root.exists():
            raise GuiFailure('s06_native_temp_cleanup_incomplete')
        result.update(status='passed', ui=ui, servers=audit, pty=pty, **metadata,
                      samePaneDifferentTerminal=True, independentHostPins=True,
                      peerClosedBeforeTestExit=True, temporaryFixturesRemoved=True)
    except (GuiFailure, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        specific = str(error) if isinstance(error, GuiFailure) else ''
        result.update(errorCode=specific if re.fullmatch(r's06_[a-z_]{1,63}', specific)
                      else 's06_native_' + stage + '_failed')
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--herdr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(0 if run(args.app, args.herdr, args.output) else 1)
    except GuiFailure as error:
        raise SystemExit(str(error)) from None
