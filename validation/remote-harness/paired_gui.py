"""Exercise a real pairing UI against the runner's disposable SSH server."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pairing'))
from pairing import CONFIRM_ADD, CONFIRM_REVOKE, FixturePairingHost, decode


class GuiFailure(Exception):
    """Static phase codes only; never publish driver, host or widget output."""


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
    def __init__(self, root, config, host):
        self.root = root
        self.config = config
        self.host = host
        self.request_id = None
        self.fingerprint = None

    def approve(self, raw):
        now = int(time.time())
        preview = self.host.preview(raw, now=now)
        if self.request_id or preview['account'] != self.config['username']:
            raise GuiFailure('unexpected_fixture_request')
        response = self.host.authorize(raw, now=now, confirmation=CONFIRM_ADD)
        request = decode(raw, now=now)
        public_line = self.host.store.read()
        if len(public_line.splitlines()) != 1 or not public_line.startswith(request['public_key'].encode() + b' '):
            raise GuiFailure('fixture_authorization_mismatch')
        self.request_id = request['request_id']
        self.fingerprint = preview['fingerprint']
        # sshd's private, newly created AuthorizedKeysFile starts empty. Only
        # the key actually approved by the fixture helper becomes acceptable.
        self.replace_authorization(public_line)
        return response

    def replace_authorization(self, content):
        pending = self.root / 'authorization.new'
        with pending.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        os.replace(pending, self.root / 'authorized_keys')

    def verify_ssh(self):
        if not self.fingerprint:
            raise GuiFailure('device_key_not_approved')
        log = bounded_wire(self.root / 'sshd.log', 2_097_152).decode(errors='replace')
        pattern = (r'Accepted publickey for ' + re.escape(self.config['username']) +
                   r' from 127\.0\.0\.1 port [0-9]+ ssh2: ED25519 ' + re.escape(self.fingerprint) + r'(?:\s|$)')
        if not re.search(pattern, log):
            raise GuiFailure('device_fingerprint_not_authenticated_by_sshd')
        if not (self.root / 'capture-running').is_file() or (self.root / 'received.bin').stat().st_size:
            raise GuiFailure('unexpected_remote_input')

    def revoke(self):
        if self.request_id:
            self.host.revoke(self.request_id, now=int(time.time()), confirmation=CONFIRM_REVOKE)
            if self.host.store.read():
                raise GuiFailure('fixture_revoke_incomplete')
            self.replace_authorization(b'')


def run_flutter(args, root, env, config, approval):
    exchange = root / 'gui-exchange'
    exchange.mkdir(mode=0o700)
    target = exchange / 'target.json'
    target.write_text(json.dumps(config))
    widget_env = dict(env, HERDR_PAIRING_GUI_CONFIG=str(target), HERDR_PAIRING_GUI_DIR=str(exchange),
                      HERDR_PAIRING_GUI_TEST_KEY=str(root / 'client'))
    command = ['flutter', 'test', '--no-pub', '--reporter', 'expanded', 'test/pairing_gui_ssh_test.dart']
    with owned_process(command, cwd=args.flutter_app, env=widget_env, log=root/'widget.log') as proc:
        def request_ready():
            if proc.poll() is not None:
                raise GuiFailure('widget_exited_before_request')
            return (exchange / 'request.json').is_file()
        wait_for(request_ready, 'widget_request_timeout', timeout=100)
        response = approval.approve(bounded_wire(exchange / 'request.json'))
        pending = exchange / 'response.new'
        pending.write_bytes(response)
        pending.rename(exchange / 'response.json')
        try:
            code = proc.wait(timeout=100)
        except subprocess.TimeoutExpired as exc:
            raise GuiFailure('widget_completion_timeout') from exc
        if code or not (exchange / 'result.json').is_file():
            # Return only named, fixed test-stage failures (never raw widget logs).
            raise GuiFailure('widget_pairing_or_observe_failed')
        result = json.loads(bounded_wire(exchange / 'result.json'))
        required = ('paired', 'paneChosen', 'fullRendered', 'deltaRendered', 'stoppedStale')
        calls = result.get('signCalls')
        if not all(result.get(field) is True for field in required) or type(calls) != int or not 1 <= calls <= 8:
            raise GuiFailure('widget_evidence_incomplete')
        frames = result.get('frameCount')
        deltas = result.get('deltaFrames')
        if type(frames) is not int or type(deltas) is not int or not 1 <= deltas < frames <= 1_000_000 or result.get('connectionCount') != 1:
            raise GuiFailure('widget_frame_evidence_incomplete')
        return {**{field: True for field in required}, 'signCalls': calls, 'frameCount': frames, 'deltaFrames': deltas,
                'keyStore': 'test-only Dart signer with runner-generated identity'}


class WebDriver:
    """Minimal W3C client. Exercise public controls in the native Linux WebView."""
    def __init__(self):
        self.base = 'http://127.0.0.1:4444'
        self.session = ''

    def call(self, method, path, data=None):
        raw = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.base + path, data=raw, method=method,
                                     headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)['value']

    def start(self, binary):
        def ready():
            try:
                return self.call('GET', '/status')
            except (OSError, ValueError):
                return False
        wait_for(ready, 'webdriver_unavailable')
        reply = self.call('POST', '/session', {'capabilities':{'alwaysMatch':{
            'tauri:options':{'application':str(binary.resolve())}}}})
        self.session = '/session/' + reply['sessionId']
        self.call('POST', self.session + '/window/rect', {'width':390, 'height':844})

    def element(self, selector):
        def find():
            result = self.call('POST', self.session+'/elements', {'using':'css selector','value':selector})
            return result and result[0]['element-6066-11e4-a52e-4f735466cecf']
        return self.session+'/element/'+wait_for(find, 'missing_control_'+re.sub(r'[^a-z0-9_-]', '', selector)[:40])

    def click(self, selector):
        self.call('POST', self.element(selector)+'/click', {})

    def fill(self, selector, value):
        path = self.element(selector)
        self.call('POST', path+'/clear', {})
        self.call('POST', path+'/value', {'text':str(value), 'value':list(str(value))})

    def read(self, selector, prop='innerText'):
        return self.call('GET', self.element(selector)+'/property/'+prop)

    def close(self):
        if self.session:
            self.call('DELETE', self.session)


def run_tauri(args, root, env, config, approval):
    driver = WebDriver()
    with owned_process(['tauri-driver'], cwd=root, env=env, log=root/'driver.log'):
        try:
            driver.start(args.tauri_app)
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
            driver.click('#remote-review')
            driver.click('#remote-connect')
            pane_selector = '#remote-panes button'
            button = wait_for(lambda:driver.read(pane_selector), 'pane_dashboard_missing')
            if not button.startswith(config['paneId']+' · '):
                raise GuiFailure('unexpected_dashboard_pane')
            driver.click(pane_selector)
            def tick():
                match = re.search(r'Synthetic observe tick\s+(\d+)', driver.read('#remote-terminal'))
                return int(match[1]) if match else 0
            initial = wait_for(tick, 'full_screen_missing')
            def advanced_tick():
                current = tick()
                return current if current > initial else 0
            updated = wait_for(advanced_tick, 'screen_delta_missing')
            driver.click('#remote-cancel')
            wait_for(lambda:'陈旧' in driver.read('#remote-captured'), 'stale_marker_missing')
            return {'paired':True, 'paneChosen':True, 'fullRendered':True, 'deltaRendered':True,
                    'stoppedStale':True, 'initialScreenTick':initial, 'updatedScreenTick':updated,
                    'keyStore':'native process-memory Linux test identity'}
        finally:
            driver.close()


def run_gui(args, root, env, config):
    run_id = os.environ.get('GITHUB_RUN_ID','')
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'\d+',run_id) or
            not os.environ.get('GITHUB_REF','').startswith('refs/heads/codex/') or
            root.parent != Path('/tmp') or not root.name.startswith('hp-mobile-'+run_id+'-') or
            (root/'authorized_keys').stat().st_size or 'privateKeyPem' in config or config['host'] != '127.0.0.1'):
        raise GuiFailure('unsafe_fixture')
    result = {'adapter': args.paired_gui, 'testId':'reviewed-device-key-to-observe', 'status':'failed'}
    try:
        with FixturePairingHost(host_public_key=config['expectedHostKey'], fixture_account=config['username']) as host:
            approval = FixtureApproval(root, config, host)
            try:
                exercise = run_tauri if args.paired_gui == 'tauri' else run_flutter
                result.update(exercise(args, root, env, config, approval))
                approval.verify_ssh()
            finally:
                approval.revoke()
        result.update(status='passed', matchedDeviceKeyInSshd=True, receivedInputBytes=0, revokedFixtureKey=True)
    except GuiFailure as exc:
        result['errorCode'] = str(exc)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result['errorCode'] = 'gui_'+type(exc).__name__.lower()
    return result
