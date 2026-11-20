"""Exercise a real pairing UI against the runner's disposable SSH server."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'helper'))
sys.path.insert(0, str(REPO / 'validation/pairing'))
from pairing import fingerprint
from guarded_input import ANDROID_ROUTES, DIRECT, DRAFT, EvidenceError, expected_bytes, mobile_receipts, mobile_tui_evidence
from paired_tui import validate_report

# The pairing fixture uses POSIX authorization files and a PTY. The Windows
# ordinary SSH runner only shares the portable evidence helpers in this module.
if sys.platform != 'win32':
    from herdr_pocket_helper.store import Host
    from blocked_fixture import BlockedFixtureFailure, bindings as blocked_bindings, snapshot as blocked_snapshot


class GuiFailure(Exception):
    """Static phase codes only; never publish driver, host or widget output."""


def retained_host_card_matches(detail, card):
    """Compare the visible stale card with its independently observed summary."""
    expected = re.search(r'受阻(?:至少)? \d+(?!\d)', detail)
    actual = re.search(r'受阻(?:至少)? \d+(?!\d)', card)
    return bool(expected and actual and expected.group() == actual.group() and '上次快照' in card)


def fixture_terminal_id(config):
    # Read back the selected pane from the fixture server independently of the
    # app. Different sessions can both contain w1:p1.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(4)
        sock.connect(config['socketPath'])
        sock.sendall(b'{"id":"verify-input-target","method":"session.snapshot","params":{}}\n')
        with sock.makefile('rb') as stream:
            line = stream.readline(1_048_577)
    if len(line) > 1_048_576 or not line.endswith(b'\n'):
        raise GuiFailure('fixture_snapshot_invalid')
    reply = json.loads(line)
    result = reply.get('result', {}) if isinstance(reply, dict) else {}
    if (not isinstance(result, dict) or reply.get('id') != 'verify-input-target' or
            result.get('type') != 'session_snapshot' or not isinstance(result.get('snapshot'), dict)):
        raise GuiFailure('fixture_snapshot_invalid')
    snapshot = result['snapshot']
    panes = snapshot.get('panes')
    if snapshot.get('version') != '0.9.5' or snapshot.get('protocol') != 22 or not isinstance(panes, list):
        raise GuiFailure('fixture_snapshot_invalid')
    ids = [row.get('terminal_id') for row in panes if isinstance(row, dict) and row.get('pane_id') == config['paneId']]
    if len(ids) != 1 or not isinstance(ids[0], str) or not re.fullmatch(r'term_[0-9a-f]{1,123}', ids[0]):
        raise GuiFailure('fixture_terminal_binding_invalid')
    return ids[0]


def widget_failure(exchange, fallback):
    # Only emit stages chosen by the harness. Never copy widget logs or form data.
    stages = {'host_board', 'public_request', 'host_authorization', 'restore_pending',
              'response_review', 'ssh_and_dashboard', 'active_host_summary', 'observe_frames',
              'pause_resume_original', 'retained_host_summary', 'resumed_host_summary', 'guarded_input', 'stop'}
    path = exchange / 'stage'
    if path.is_file():
        phase = bounded_wire(path, 40).decode('ascii', errors='ignore')
        if phase in stages:
            return GuiFailure(f'{fallback}_{phase}')
    return GuiFailure(fallback)


def wait_for(probe, code, *, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.1)
    raise GuiFailure(code)


@contextmanager
def owned_process(argv, *, cwd, env, log):
    if sys.platform == 'win32':
        raise GuiFailure('paired_gui_posix_required')
    with log.open('wb') as stream:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            yield proc
        finally:
            # WebKit and Flutter may have children after their launcher exits.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


def bounded_wire(path, limit=2048):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise GuiFailure('oversize_gui_exchange')
    return data


class FixtureApproval:
    def __init__(self, root, config, host, *, blocked_targets=None, keyring=None):
        if sys.platform == 'win32':
            raise GuiFailure('paired_gui_posix_required')
        self.root = root
        self.config = config
        self.host = host
        self.keyring = keyring
        self.request_id = None
        self.fingerprint = None
        self.applied = False
        self.revocation_response = None
        self.tui_terminal_id = None
        self.tui_started = False
        self.tui_verified = False
        self.blocked_targets = []
        if blocked_targets:
            try:
                self.blocked_targets = blocked_bindings(blocked_snapshot(config['socketPath']),blocked_targets)
            except BlockedFixtureFailure:
                raise GuiFailure('blocked_fixture_binding_invalid') from None

    def verify_blocked_targets(self):
        """Read back the two synthetic bindings, independently of GUI summaries."""
        try:
            return blocked_bindings(blocked_snapshot(self.config['socketPath']),self.blocked_targets)
        except BlockedFixtureFailure:
            raise GuiFailure('blocked_fixture_binding_invalid') from None

    def approve(self, raw):
        now = int(time.time())
        try:
            request = self.host.review(raw, now)
        except ValueError:
            raise GuiFailure('fixture_public_request_invalid') from None
        if self.request_id or request['account'] != self.config['username']:
            raise GuiFailure('unexpected_fixture_request')
        if self.keyring is not None:
            from linux_pairing_keyring import KeyringFailure
            try:
                self.keyring.verify(request['public_key'])
            except KeyringFailure as error:
                raise GuiFailure(str(error)) from None
            except (OSError, subprocess.SubprocessError):
                raise GuiFailure('private_keyring_verification_failed') from None
        try:
            response = self.host.authorize(raw, request['request_id'], now=now)
        except (OSError, ValueError):
            raise GuiFailure('fixture_device_authorization_failed') from None
        public_line = bounded_wire(self.host.home / '.ssh' / 'authorized_keys', 4096)
        if len(public_line.splitlines()) != 1 or not public_line.startswith(request['public_key'].encode() + b' '):
            raise GuiFailure('fixture_authorization_mismatch')
        self.request_id = request['request_id']
        self.fingerprint = fingerprint(request['public_key'])
        # sshd's private, newly created AuthorizedKeysFile starts empty. Only
        # the key actually approved by the fixture helper becomes acceptable.
        self.replace_authorization(public_line)
        self.applied = True
        return response

    def replace_authorization(self, content):
        pending = self.root / 'authorization.new'
        with pending.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        os.replace(pending, self.root / 'authorized_keys')

    def fingerprint_authenticated(self):
        if not self.applied or not (self.root/'sshd.log').is_file():
            return False
        log = bounded_wire(self.root / 'sshd.log', 2_097_152).decode(errors='replace')
        pattern = (r'Accepted publickey for ' + re.escape(self.config['username']) +
                   r' from 127\.0\.0\.1 port [0-9]+ ssh2: ED25519 ' + re.escape(self.fingerprint) + r'(?:\s|$)')
        return re.search(pattern, log) is not None

    def verify_ssh(self, expected=b''):
        if not self.fingerprint_authenticated():
            raise GuiFailure('device_fingerprint_not_authenticated_by_sshd')
        if expected:
            wait_for(lambda: (self.root/'received.bin').stat().st_size >= len(expected), 'fixture_input_missing', timeout=4)
        if not (self.root/'capture-running').is_file() or bounded_wire(self.root/'received.bin',4096) != expected:
            raise GuiFailure('unexpected_remote_input')

    def start_tui(self, *, terminal_id):
        if self.tui_started or self.tui_verified:
            raise GuiFailure('paired_tui_already_started')
        self.tui_started = True  # A failed/ambiguous start is never replayed.
        if not isinstance(terminal_id, str) or fixture_terminal_id(self.config) != terminal_id:
            raise GuiFailure('paired_tui_target_changed')
        self.verify_ssh(DIRECT + DRAFT)
        self.tui_terminal_id = terminal_id
        marker = self.root / 'start-tui'
        try:
            with marker.open('xb') as output:
                output.write(b'start\n'); output.flush(); os.fsync(output.fileno())
        except OSError:
            raise GuiFailure('paired_tui_start_unconfirmed') from None
        def ready():
            if not (self.root / 'capture-running').is_file():
                raise GuiFailure('paired_tui_capture_stopped')
            path = self.root / 'tui-ready'
            return path.is_file() and not path.is_symlink() and bounded_wire(path, 16) == b'ready\n'
        wait_for(ready, 'paired_tui_start_timeout', timeout=15)
        if fixture_terminal_id(self.config) != terminal_id:
            raise GuiFailure('paired_tui_target_changed')
        return {'ready': True, 'sameTarget': True, 'initialInputMatched': True}

    def verify_tui(self, *, terminal_id):
        if not self.tui_started or self.tui_verified or terminal_id != self.tui_terminal_id:
            raise GuiFailure('paired_tui_state_invalid')
        self.tui_verified = True  # Verification failure is not a restart signal.
        wait_for(lambda: (self.root / 'tui-complete').is_file(), 'paired_tui_completion_timeout', timeout=15)
        if (self.root / 'tui-complete').is_symlink() or bounded_wire(self.root / 'tui-complete', 16) != b'complete\n':
            raise GuiFailure('paired_tui_completion_invalid')
        if fixture_terminal_id(self.config) != terminal_id:
            raise GuiFailure('paired_tui_target_changed')
        self.verify_ssh(DIRECT + DRAFT)
        try:
            state = validate_report(bounded_wire(self.root / 'tui-result.json', 2048))
        except (OSError, ValueError):
            raise GuiFailure('paired_tui_report_invalid') from None
        return {'sameTarget': True, 'initialInputMatched': True, 'finalInputMatched': True,
                'terminalModesRestored': True, 'postFinishKernelInputAbsent': True, **state}

    def revoke(self):
        if self.request_id and self.revocation_response is None:
            receipt = self.host.revoke(self.request_id, self.request_id, now=int(time.time()))
            if bounded_wire(self.host.home / '.ssh' / 'authorized_keys', 4096):
                raise GuiFailure('fixture_revoke_incomplete')
            self.replace_authorization(b'')
            self.revocation_response = receipt
        return self.revocation_response


def run_flutter(args, root, env, config, approval):
    exchange = root / 'gui-exchange'
    exchange.mkdir(mode=0o700)
    target = exchange / 'target.json'
    target.write_text(json.dumps(config))
    widget_env = dict(env, HERDR_PAIRING_GUI_CONFIG=str(target), HERDR_PAIRING_GUI_DIR=str(exchange))
    native = approval.keyring is not None
    if not native:
        widget_env['HERDR_PAIRING_GUI_TEST_KEY'] = str(root / 'client')
    if args.input_fixture:
        widget_env['HERDR_PAIRING_GUI_EXPECT_INPUT'] = '1'
    if native:
        widget_env.pop('FLUTTER_TEST', None)
        from flutter_linux_pairing import native_command
        command = native_command(args, root, env)
    else:
        command = ['flutter', 'test', '--no-pub', '--reporter', 'expanded', 'test/pairing_gui_ssh_test.dart']
    with owned_process(command, cwd=args.flutter_app, env=widget_env, log=root/'widget.log') as proc:
        def request_ready():
            if proc.poll() is not None:
                raise widget_failure(exchange, 'widget_exited_before_request')
            return (exchange / 'request.json').is_file()
        wait_for(request_ready, 'widget_request_timeout', timeout=420 if native else 100)
        response = approval.approve(bounded_wire(exchange / 'request.json'))
        pending = exchange / 'response.new'
        pending.write_bytes(response)
        pending.rename(exchange / 'response.json')
        try:
            code = proc.wait(timeout=100)
        except subprocess.TimeoutExpired as exc:
            raise widget_failure(exchange, 'widget_completion_timeout') from exc
        if code or not (exchange / 'result.json').is_file():
            # Return only named, fixed test-stage failures (never raw widget logs).
            raise widget_failure(exchange, 'widget_pairing_or_observe_failed')
        result = json.loads(bounded_wire(exchange / 'result.json'))
        required = ('paired', 'paneChosen', 'fullRendered', 'deltaRendered', 'stoppedStale',
                    'reopenedPendingRequest', 'pauseResumeSameConnection', 'hostSummaryActive',
                    'hostSummaryRetained', 'hostSummaryResumed', 'hostSummaryStopped')
        calls = result.get('signCalls')
        mode_ok = (result.get('nativeCatalogAndKeys') is True and calls is None and result.get('identityCreations') is None
                   if native else result.get('identityCreations') == 1 and type(calls) is int and 1 <= calls <= 8)
        if not all(result.get(field) is True for field in required) or not mode_ok:
            raise GuiFailure('widget_evidence_incomplete')
        frames = result.get('frameCount')
        deltas = result.get('deltaFrames')
        if type(frames) is not int or type(deltas) is not int or not 1 <= deltas < frames <= 1_000_000 or result.get('connectionCount') != 1:
            raise GuiFailure('widget_frame_evidence_incomplete')
        if args.input_fixture and result.get('inputQueueAccepted') is not True:
            raise GuiFailure('widget_input_not_accepted')
        return {**{field: True for field in required}, 'inputQueueAccepted':bool(args.input_fixture), 'frameCount': frames, 'deltaFrames': deltas,
                'localViewportChanges':result.get('localViewportChanges',0),
                **({'keyStore': 'private Linux Secret Service', 'flutterNativeSource': args.flutter_native_source,
                    'nativeCatalogReadback': True} if native else
                   {'keyStore': 'test-only Dart signer with runner-generated identity', 'signCalls': calls})}


class WebDriver:
    """Minimal W3C client. Exercise public controls in the native Linux WebView."""
    def __init__(self, *, native_webkit=False):
        self.base = 'http://127.0.0.1:4444'
        self.session = ''
        self.native_webkit = native_webkit

    def call(self, method, path, data=None):
        raw = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.base + path, data=raw, method=method,
                                     headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                return json.load(response)['value']
        except urllib.error.HTTPError as error:
            # Include only the W3C error class and the operation, never its message.
            try:
                label = json.loads(error.read(8192))['value']['error']
            except (KeyError, TypeError, ValueError):
                label = 'unknown'
            safe = label if isinstance(label, str) and re.fullmatch(r'[a-z ]{1,40}', label) else 'unknown'
            raise GuiFailure('webdriver_' + path.rsplit('/', 1)[-1][:18] + '_' + safe.replace(' ', '_')) from None

    def start(self, binary):
        def ready():
            try:
                return self.call('GET', '/status')
            except (OSError, ValueError):
                return False
        wait_for(ready, 'webdriver_unavailable')
        application = str(binary.resolve())
        options = ({'webkitgtk:browserOptions': {'binary': application, 'args': []}} if self.native_webkit
                   else {'tauri:options': {'application': application}})
        reply = self.call('POST', '/session', {'capabilities': {'alwaysMatch': options}})
        self.session = '/session/' + reply['sessionId']
        self.call('POST', self.session + '/window/rect', {'width':390, 'height':844})

    def element(self, selector):
        def find():
            result = self.call('POST', self.session+'/elements', {'using':'css selector','value':selector})
            return result and result[0]['element-6066-11e4-a52e-4f735466cecf']
        return self.session+'/element/'+wait_for(find, 'missing_control_'+re.sub(r'[^a-z0-9_-]', '', selector)[:40])

    def click(self, selector):
        self.wait_control(selector)
        self.call('POST', self.element(selector)+'/click', {})

    def wait_control(self, selector, editable=False):
        # The document contains hidden forms and an initially disabled board
        # button. Observe readiness; interactions still use WebDriver events.
        script = """const e=document.querySelector(arguments[0]);
            if (!e || !e.getClientRects().length || e.matches(':disabled') ||
                getComputedStyle(e).visibility !== 'visible') return false;
            e.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
            if (arguments[1]) {
                if (e.readOnly) return false;
                e.focus();
                return document.activeElement === e;
            }
            const r=e.getBoundingClientRect(), at=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return e.contains(at);"""
        def ready():
            return self.call('POST', self.session+'/execute/sync', {'script':script,'args':[selector,editable]})
        wait_for(ready, ('form_not_editable_' if editable else 'control_not_ready_')+selector.lstrip('#'))

    def fill(self, selector, value):
        self.wait_control(selector, editable=True)
        label = selector.lstrip('#')
        path = self.element(selector)
        try:
            self.call('POST', path+'/clear', {})
            self.call('POST', path+'/value', {'text':str(value), 'value':list(str(value))})
        except GuiFailure as error:
            raise GuiFailure(f'{error}_{label}') from None
        if self.read(selector,'value') != str(value):
            raise GuiFailure('form_input_mismatch_'+label)

    def _read_element(self, selector, kind, name):
        # A live dashboard can replace a node between lookup and an idempotent
        # property read. Relocate only for that exact W3C error; never replay a
        # click, fill or other state-changing operation.
        stale = 'webdriver_' + name[:18] + '_stale_element_reference'
        for attempt in range(5):
            try:
                return self.call('GET', self.element(selector)+'/'+kind+'/'+name)
            except GuiFailure as error:
                if str(error) != stale or attempt == 4:
                    raise
                time.sleep(0.05)

    def read(self, selector, prop='innerText'):
        return self._read_element(selector, 'property', prop)

    def attribute(self, selector, name):
        return self._read_element(selector, 'attribute', name)

    def close(self):
        if self.session:
            self.call('DELETE', self.session)


def open_host_summary(driver):
    """Expand the visible details with a WebDriver click before reading innerText."""
    def is_open():
        return driver.attribute('#host-task-details', 'open')
    if not is_open():
        driver.click('#host-task-details > summary')
        wait_for(is_open, 'host_summary_not_expanded')


def stop_tauri_observation(driver):
    # In the guarded layout the input dock is the reachable stop action;
    # stock observation has only the separate stop action. Click once only.
    script = """for (const selector of ['#remote-stop-dock','#remote-stop-visible']) {
        const e=document.querySelector(selector);
        if (e && e.getClientRects().length && !e.matches(':disabled') &&
            getComputedStyle(e).visibility === 'visible') return selector;
    } return null;"""
    selector = wait_for(lambda: driver.call('POST', driver.session + '/execute/sync',
                                           {'script': script, 'args': []}), 'stop_control_unavailable')
    if selector not in ('#remote-stop-dock', '#remote-stop-visible'):
        raise GuiFailure('stop_control_invalid')
    driver.click(selector)
    wait_for(lambda: '陈旧' in driver.read('#remote-captured'), 'stale_marker_missing')
    wait_for(lambda: driver.call('POST', driver.session + '/execute/sync',
        {'script': "return document.querySelector('#remote-input-controls').hidden;", 'args': []}) is True,
        'input_controls_not_retired_after_stop')


def run_tauri(args, root, env, config, approval):
    native = approval.keyring is not None
    if native and args.input_fixture:
        raise GuiFailure('restart_requires_stock_read_only')
    driver = WebDriver(native_webkit=native)
    restart = None
    if native:
        from tauri_linux_pairing_restart import RestartReceipt, no_keyring_writes
        restart = RestartReceipt(args.tauri_app, root, env, config, approval)
    command = ['/usr/bin/WebKitWebDriver', '--host=127.0.0.1', '--port=4444'] if native else ['tauri-driver']
    driver_env = dict(env, TAURI_WEBVIEW_AUTOMATION='true') if native else env
    with owned_process(command, cwd=root, env=driver_env, log=root/'driver.log') as driver_process, ExitStack() as lifetime:
        try:
            driver.start(args.tauri_app)
            if restart is not None:
                restart.first_started(driver_process.pid)
            from s06_tauri_gui import SplitDriver
            SplitDriver(driver).open_pairing(empty_board=True)
            for field, key in [('host','host'), ('port','port'), ('user','username'), ('session','session'),
                               ('herdr','herdrPath'), ('socket','socketPath'), ('pin','expectedHostKey')]:
                driver.fill('#remote-'+field, config[key])
            driver.click('#pair-mode')
            driver.click('#pair-target-review')
            driver.click('#pair-create')
            request = wait_for(lambda:driver.read('#pair-request', 'value'), 'public_request_missing')
            response = approval.approve(request.encode())
            driver.fill('#pair-response', response.decode())
            driver.click('#pair-preview')
            driver.click('#pair-source-review')
            driver.click('#pair-accept')
            wait_for(lambda: '授权响应已审查' in driver.read('#pair-status'), 'authorization_not_reviewed')
            driver.click('#remote-review')
            driver.click('#remote-connect')
            pane_selector = '#remote-panes button'
            button = wait_for(lambda:driver.read(pane_selector), 'pane_dashboard_missing')
            if not button.startswith(config['paneId']+' · '):
                raise GuiFailure('unexpected_dashboard_pane')
            open_host_summary(driver)
            summary_selector = '#host-task-board [data-live-host-summary]'
            phase_selector = '#remote-panes [data-dashboard-phase]'
            session_label = f" · 会话 {config['session']} · 受阻"
            def current_board():
                phase = driver.attribute(phase_selector,'data-dashboard-phase')
                prefix = {'fresh': '当前快照', 'unavailable': '本次快照（持续更新不可用）'}.get(phase)
                summary = driver.read(summary_selector)
                return phase if prefix and prefix + session_label in summary and ' · 同步 ' in summary else None
            initial_board = wait_for(current_board, 'direct_host_summary_missing')
            driver.click(pane_selector)
            def rendered(attr):
                value = driver.attribute('#remote-captured','data-'+attr+'-frames')
                return int(value) if value and value.isdigit() else 0
            full = wait_for(lambda:rendered('full'), 'full_render_ack_missing')
            deltas = wait_for(lambda:rendered('delta'), 'delta_render_ack_missing')
            for width in (1040,390):
                dimensions = driver.call('POST',driver.session+'/window/rect',{'width':width,'height':844})
                if dimensions.get('width') != width:
                    raise GuiFailure('local_viewport_resize_unconfirmed')
                def next_delta():
                    count = rendered('delta')
                    return count if count > deltas else 0
                deltas = wait_for(next_delta,'delta_missing_after_local_resize')
            if args.input_fixture:
                driver.click('#remote-input-draft-mode')
                driver.fill('#remote-input-draft', 'Pocket测')
                driver.click('#remote-input-preview')
                driver.click('#remote-input-confirm')
                wait_for(lambda: '已接收入队' in driver.read('#remote-input-status'), 'input_ack_missing')
            terminal_board = wait_for(current_board, 'direct_host_summary_expired_during_terminal')
            stop_tauri_observation(driver)
            def stopped_summary():
                label = driver.read(summary_selector)
                position = label.find('上次快照（状态已陈旧）' + session_label)
                return label[position:] if position >= 0 else None
            retained = wait_for(stopped_summary, 'direct_host_summary_not_retained')
            driver.click('#host-return-home')
            wait_for(lambda: retained_host_card_matches(retained,
                driver.read('#host-list [data-host-task-summary]')),
                     'retained_home_summary_missing')
            result = {'paired':True, 'paneChosen':True, 'fullRendered':True, 'deltaRendered':True,
                    'initialHostBoardPhase':initial_board, 'hostBoardPhaseDuringTerminal':terminal_board,
                    'hostSummaryRetainedOnHome':True,
                    'stoppedStale':True, 'fullRenderAcknowledgements':full, 'deltaRenderAcknowledgements':deltas,
                    'localViewportChanges':2, 'inputQueueAccepted':bool(args.input_fixture),
                    'keyStore':('private Linux Secret Service' if approval.keyring else
                        'isolated Secret Service session; keyring binding not independently verified'
                        if getattr(args, 'private_keyring_session', False) else 'Linux identity; storage not independently verified')}
            if restart is not None:
                restart.before_first_exit(driver, driver_process.pid)
                lifetime.enter_context(no_keyring_writes(approval, root, env))
        finally:
            driver.close()
        if restart is not None:
            restart.after_first_exit()
            second = WebDriver(native_webkit=True)
            try:
                second.start(args.tauri_app)
                if second.session == driver.session:
                    raise GuiFailure('restart_webview_session_reused')
                result['restart'] = restart.second(second, driver_process.pid)
            finally:
                second.close()
    return result


def run_gui(args, root, env, config):
    if sys.platform == 'win32':
        raise GuiFailure('paired_gui_posix_required')
    run_id = os.environ.get('GITHUB_RUN_ID','')
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'\d+',run_id) or
            not os.environ.get('GITHUB_REF','').startswith('refs/heads/codex/') or
            root.parent != Path('/tmp') or not root.name.startswith('hp-mobile-'+run_id+'-') or
            (root/'authorized_keys').stat().st_size or 'privateKeyPem' in config or config['host'] != '127.0.0.1'):
        raise GuiFailure('unsafe_fixture')
    guarded_mobile = args.paired_gui in ANDROID_ROUTES and bool(args.input_fixture)
    case = 'reviewed-device-key-to-direct-and-draft' if guarded_mobile else 'reviewed-device-key-to-observe'
    result = {'adapter': args.paired_gui, 'testId': case, 'status':'failed'}
    keyring = getattr(args, 'linux_keyring', None)
    try:
        if getattr(args, 'android_tui', False) and not guarded_mobile:
            raise GuiFailure('android_tui_requires_guarded_input')
        # Exercise the shipping helper against its own private scratch home.
        # The normal CLI obtains the operator's home from pwd instead.
        import tempfile
        with tempfile.TemporaryDirectory(dir=root, prefix='fixture-home-') as scratch:
            host = Host(Path(scratch), config['username'], config['expectedHostKey'])
            blocked_targets = getattr(args,'blocked_targets',None)
            approval = FixtureApproval(root, config, host, blocked_targets=blocked_targets, keyring=keyring)
            terminal = None
            try:
                if args.paired_gui == 'tauri-android':
                    from android_gui import run_android as exercise
                elif args.paired_gui == 'flutter-android':
                    from flutter_android_gui import run_flutter_android as exercise
                else:
                    exercise = run_tauri if args.paired_gui == 'tauri' else run_flutter
                terminal = fixture_terminal_id(config) if guarded_mobile else None
                observed = exercise(args, root, env, config, approval)
                receipts = observed.pop('inputReceipts', None)
                tui = observed.pop('tui', None)  # Publish only after strict validation.
                observed.pop('hostTui', None)  # Host attestation can never originate from a GUI.
                result.update(observed)
                expected = expected_bytes(args.paired_gui, bool(args.input_fixture))
                if expected and result.get('inputQueueAccepted') is not True:
                    raise GuiFailure('missing_guarded_input_receipt')
                if guarded_mobile:
                    if result.get('pasteOperationsNoExtraSshBytes') is not True:
                        raise GuiFailure('mobile_clipboard_receiver_check_missing')
                    try:
                        result['inputReceipts'] = mobile_receipts(receipts, config['paneId'], terminal)
                    except EvidenceError as exc:
                        raise GuiFailure(str(exc)) from None
                    if fixture_terminal_id(config) != terminal:
                        raise GuiFailure('fixture_input_target_changed')
                    if getattr(args, 'android_tui', False):
                        try:
                            result['tui'] = mobile_tui_evidence(tui, result['inputReceipts'],
                                                                pane=config['paneId'], terminal=terminal)
                        except EvidenceError as exc:
                            raise GuiFailure(str(exc)) from None
                        result['hostTui'] = approval.verify_tui(terminal_id=terminal)
                    elif tui is not None:
                        raise GuiFailure('unexpected_mobile_tui')
                elif receipts:
                    raise GuiFailure('unexpected_mobile_receipts')
                elif tui is not None:
                    raise GuiFailure('unexpected_mobile_tui')
                approval.verify_ssh(expected)
                if keyring is not None:
                    if len(keyring.verified) != 1:
                        raise GuiFailure('private_keyring_public_proof_missing')
                    result['linuxKeyring'] = {'publicKeysMatched': 1, 'sameKeyAuthenticated': True}
            finally:
                result['temporaryHostApprovedRequest'] = approval.applied
                try:
                    # An error in the later removal/cleanup UI must not erase an
                    # independently completed host result, or turn the GUI green.
                    if (getattr(args, 'android_tui', False) and terminal is not None
                            and approval.tui_started and not approval.tui_verified
                            and (root / 'tui-complete').is_file()):
                        try:
                            result['hostTui'] = approval.verify_tui(terminal_id=terminal)
                        except (GuiFailure, OSError, ValueError):
                            result['hostTuiVerificationFailed'] = True
                    result['matchedDeviceKeyInSshd'] = approval.fingerprint_authenticated()
                finally:
                    approval.revoke()
                    result['revokedFixtureKey'] = approval.applied
        result.update(status='passed', matchedDeviceKeyInSshd=True, receivedInputBytes=len(expected), revokedFixtureKey=True)
    except GuiFailure as exc:
        result['errorCode'] = str(exc)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result['errorCode'] = 'gui_'+type(exc).__name__.lower()
    return result
