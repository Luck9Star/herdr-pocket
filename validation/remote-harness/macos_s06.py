"""Run the stock paired S06 XCUITest on an owned GitHub-hosted macOS window."""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

from macos_secure_xcuitest import install_test_semantics_hook, prepare
from macos_s06_diagnostics import TEST_SELECTION, diagnostics
from paired_dual_demo import prepared_pairing_hosts
from paired_gui import GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for
from s06_tauri_gui import peer_connection_evidence

HERE = Path(__file__).resolve().parent
HERDR_SHA256 = 'fb77c2232a05a8035421382c894392f4174e4e38a18e48af3dd0290157c3a7e2'
SESSIONS = {'et': 's06-a', 'ts': 's06-b'}
MARKERS = {'et': 'HPS06A', 'ts': 'HPS06B'}
CHECKS = ('homepage', 'reviewedPairings', 'twoVisibleTargets', 'bothTicksAdvanced', 'stockControlsDisabled',
          'keyboardFocus', 'narrowStowed', 'originalSidesRestored', 'explicitResume', 'stoppedBoth',
          'localProfilesAbsentFromBoard', 'channelRoundTrip')


def prepare_test(app, nonce):
    """Only change the generated native test target and opt-in AX notification."""
    if re.fullmatch(r'[a-f0-9]{64}', nonce) is None:
        raise GuiFailure('s06_native_channel_scope_invalid')
    fixture = (HERE / 'macos_s06_fixture.swift').read_text()
    channel = (HERE / 'macos_s06_channel.swift').read_text()
    template = (HERE / 'macos_s06_xcuitest.swift').read_text()
    placeholder = '__HP_S06_CHANNEL_NONCE__'
    if template.count(placeholder) != 1:
        raise GuiFailure('s06_native_test_template_invalid')
    prepare(app)
    install_test_semantics_hook(app)
    (app / 'macos/RunnerTests/RunnerTests.swift').write_text(
        fixture + '\n' + channel + '\n' + template.replace(placeholder, nonce))


def stock_binary(binary):
    size = binary.stat().st_size
    if not 0 < size <= 100 * 1024 * 1024 or hashlib.sha256(binary.read_bytes()).hexdigest() != HERDR_SHA256:
        raise GuiFailure('s06_stock_binary_digest_mismatch')


def checked_candidate(app, source):
    try:
        manifest = json.loads(bounded_wire(app / 'candidate-manifest.json', 16384))
        lock_sha = hashlib.sha256(bounded_wire(app / 'pubspec.lock', 65536)).hexdigest()
    except (GuiFailure, OSError, ValueError):
        raise GuiFailure('s06_native_candidate_lock_not_verified') from None
    if (not isinstance(manifest, dict) or manifest.get('sourceCommit') != source
            or manifest.get('variant') != 'experimental-patched'
            or manifest.get('candidateLockSha256') != lock_sha):
        raise GuiFailure('s06_native_candidate_lock_not_verified')
    return {'variant': manifest['variant'], 'candidateLockSha256': lock_sha}


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


class NativeChannel:
    def __init__(self, executable, nonce, party='host'):
        self.executable, self.nonce, self.party = executable, nonce, party
        self.released = False

    def call(self, action, topic=None, payload=b''):
        command = [self.executable, self.party, self.nonce, action]
        if topic is not None:
            command.append(topic)
        child = subprocess.run(command, input=payload, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=8, check=False)
        if child.returncode or len(child.stdout) > 4096:
            raise GuiFailure('s06_native_private_channel_rejected')
        return child.stdout

    def send(self, topic, payload):
        self.call('send', topic, payload)

    def receive(self, topic):
        return self.call('receive', topic) or None

    def release_all(self):
        self.call('releaseAll')
        self.released = True


def compile_channel(root):
    executable = root / 's06-broker'
    with (root / 'broker-build-private.log').open('wb') as log:
        subprocess.run(['swiftc', HERE / 'macos_s06_channel.swift', HERE / 'macos_s06_broker.swift',
                        '-o', executable], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
    return executable


@contextmanager
def owned_channel(root):
    channel = NativeChannel(compile_channel(root), secrets.token_hex(32))
    try:
        yield channel
    finally:
        channel.release_all()


def release_payload(configs):
    return json.dumps({'schemaVersion': 1, 'peers': configs}).encode()


def test_command(xcode, bundle):
    # Use the same test action as the existing macOS native suite. The
    # separately verified build-for-testing warms this derived-data directory.
    return xcode + ['-only-testing:' + TEST_SELECTION, '-resultBundlePath', str(bundle), 'test']


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


def requests_and_disconnect(proc, channel, targets):
    reviewed = {}
    audits = None
    roundtrip = False
    deadline = time.monotonic() + 750
    while proc.poll() is None and time.monotonic() < deadline:
        if not roundtrip:
            challenge = channel.receive('testReady')
            if challenge is None:
                time.sleep(.2)
                continue
            if not re.fullmatch(rb'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', challenge):
                raise GuiFailure('s06_native_private_channel_challenge_invalid')
            channel.send('hostReady', challenge)
            roundtrip = True
        for index, target in enumerate(targets.values()):
            if index in reviewed:
                continue
            raw = channel.receive(f'request{index}')
            if raw is None:
                continue
            facts = target.review(raw)
            if any(facts['deviceFingerprint'] == item['deviceFingerprint'] or
                   facts['requestId'] == item['requestId'] for item in reviewed.values()):
                raise GuiFailure('s06_device_identity_reused')
            response = target.approve(raw, request_id=facts['requestId'],
                                      device_fingerprint=facts['deviceFingerprint'], reviewed=True)
            reviewed[index] = facts
            channel.send(f'response{index}', response)
        stopping = channel.receive('stopRequested') if audits is None and len(reviewed) == 2 else None
        if stopping is not None and stopping != b'\x01':
            raise GuiFailure('s06_native_stop_signal_invalid')
        if stopping is not None and all(
                peer_connection_evidence(target.approval) == {'authenticationCount': 1, 'closed': True}
                for target in targets.values()):
            audits = [target.audit(b'') for target in targets.values()]
            if any(item['acceptedSessions'] != 1 or item['approvedDeviceSessions'] != 1 or
                   item['otherAcceptedDeviceSessions'] != 0 for item in audits):
                raise GuiFailure('s06_native_peer_authentication_mismatch')
            channel.send('peersClosed', b'\x01')
        time.sleep(.2)
    if proc.poll() != 0:
        raise GuiFailure('s06_native_test_timeout' if proc.poll() is None else 's06_native_xcuitest_failed')
    if not roundtrip:
        raise GuiFailure('s06_native_private_channel_unconfirmed')
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
              'scope': 'native macOS Flutter window with real paired loopback OpenSSH/herdr',
              'privateTransport': 'one-use scoped AppKit pasteboards'}
    stage = 'build'
    channel = None
    try:
        result['flutterCandidate'] = checked_candidate(app, source)
        stock_binary(binary)
        with tempfile.TemporaryDirectory(prefix='hpns06-', dir='/tmp') as temporary, ExitStack() as owned:
            root = Path(temporary).resolve()
            stage = 'channel'
            channel = owned.enter_context(owned_channel(root))
            stage = 'build'
            prepare_test(app, channel.nonce)
            xcode = ['xcodebuild', '-workspace', str(app / 'macos/Runner.xcworkspace'),
                     '-scheme', 'Runner', '-configuration', 'Debug', '-destination', 'platform=macOS',
                     '-derivedDataPath', str(root / 'derived'), '-parallel-testing-enabled', 'NO']
            with owned_process(xcode + ['build-for-testing'], cwd=app, env=os.environ,
                               log=root / 'build-private.log') as build:
                if build.wait(timeout=900) != 0:
                    raise GuiFailure('s06_native_test_build_failed')
            stage = 'fixture'
            with fixtures(binary, root) as (targets, children, metadata, configs):
                channel.send('release', release_payload(configs))
                stage = 'test'
                result['releasePublished'] = True
                proc = None
                bundle, private_test_log = root / 'private.xcresult', root / 'test-private.log'
                try:
                    with owned_process(test_command(xcode, bundle), cwd=app,
                                       env=os.environ, log=private_test_log) as proc:
                        audit = requests_and_disconnect(proc, channel, targets)
                finally:
                    native = diagnostics(private_test_log, bundle, proc.poll() if proc else None)
                    result['nativeDiagnostics'] = native
                    if last := native.get('lastLoggedStage'):
                        result['nativeStage'] = last
                ui = checked_ui_result(json.loads(channel.receive('result') or b'null'))
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
    if channel is not None:
        result['privateChannelReleased'] = channel.released
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
