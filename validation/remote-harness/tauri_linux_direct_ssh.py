#!/usr/bin/env python3
"""Exercise the native Linux Tauri desktop against a disposable ordinary SSH peer."""
import argparse
import base64
import binascii
import errno
import hashlib
import io
import json
import os
import re
import socket
import tempfile
import time
import urllib.request
from contextlib import suppress
from pathlib import Path

from direct_ssh_fixture import DirectSshFixture
from ios_encrypted_key_fixture import EncryptedKeyFixture
from paired_gui import GuiFailure, WebDriver, owned_process, wait_for
from PIL import Image
from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot

CHECK_FIELDS = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')
SECRET_FIELDS = ('#ssh-password', '#ssh-key', '#ssh-passphrase')
TYPED_LINE = 'hp-check\ue007'  # WebDriver Enter, sent to the focused xterm.
RENDER_PENDING = {'terminal_screenshot_echo_not_visible', 'terminal_screenshot_token_not_visible',
                  'terminal_screenshot_proof_not_adjacent'}

DASHBOARD_WITNESS = '''const home = node('#home-dashboard'), empty = node('#host-empty');
  const add = node('#host-empty-add');
  return visible(home) && visible(empty) && home.contains(empty) && empty.contains(add) &&
    actionableButton(add, '添加主机');'''

CHOICE_WITNESS = '''const page = node('#home-add'), heading = node('#add-choice-heading');
  const choice = node('#add-ssh'), label = node('#add-ssh-label');
  return !visible(node('#home-dashboard')) && visible(page) && visible(heading) &&
    heading.innerText === '选择连接方式' && page.contains(choice) && choice.contains(label) &&
    choice.getAttribute('aria-labelledby') === label.id && visible(label) &&
    label.innerText === '普通 SSH 终端' && actionableButton(choice);'''

TARGET_WITNESS = '''const page = node('#home-ssh'), step = node('#ssh-step-title');
  const target = node('#ssh-target-fields');
  return !visible(node('#home-add')) && visible(page) && visible(step) && step.innerText === '普通 SSH' &&
    visible(target) && page.contains(target) && ['#ssh-host', '#ssh-port', '#ssh-user'].every(selector => {
      const field = node(selector);
      return visible(field) && target.contains(field) && !field.disabled && !field.readOnly;
    }) && !visible(node('#ssh-trust-review')) && !visible(node('#ssh-credentials'));'''

REVIEW_WITNESS = r'''const selectors = ['#ssh-step-title', '#ssh-reviewed-target', '#ssh-reviewed-endpoint',
    '#ssh-reviewed-key', '#ssh-reviewed-algorithm', '#ssh-reviewed-fingerprint', '#ssh-trust-confirm'];
  if (selectors.some(s => document.querySelectorAll(s).length !== 1)) return false;
  const title = node(selectors[0]), target = node(selectors[1]), endpoint = node(selectors[2]);
  const card = node(selectors[3]), algorithm = node(selectors[4]), fingerprint = node(selectors[5]);
  const confirm = node(selectors[6]), review = node('#ssh-review');
  const inView = el => { if (!visible(el)) return false; const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; };
  if (!selectors.every(s => inView(node(s))) || !target.contains(endpoint) || !card.contains(algorithm) ||
      !card.contains(fingerprint) || title.innerText !== '核对主机密钥' || endpoint.innerText !== arguments[0] ||
      algorithm.innerText !== arguments[1] || fingerprint.innerText.replace(/\s/g, '') !== arguments[2] ||
      confirm.innerText !== '指纹一致，确认继续' || confirm.disabled || !review || review.checked || visible(review) ||
      !node('#ssh-password').disabled || !node('#ssh-connect').disabled) return false;
  const range = document.createRange(); range.selectNodeContents(fingerprint);
  const parts = [...range.getClientRects()];
  return parts.length > 0 && parts.every(r => r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 &&
    r.right <= innerWidth && r.bottom <= innerHeight &&
    fingerprint.contains(document.elementFromPoint((r.left+r.right)/2, (r.top+r.bottom)/2)));'''

KEY_FIELDS_WITNESS = '''const endpoint = node('#ssh-reviewed-endpoint'), key = node('#ssh-key');
  const passphrase = node('#ssh-passphrase'), choice = node('#ssh-auth-key');
  return visible(node('#ssh-credentials')) && visible(endpoint) && endpoint.innerText === arguments[0] &&
    node('#ssh-review').checked && node('#ssh-auth-method').value === 'key' &&
    visible(choice) && choice.getAttribute('aria-pressed') === 'true' &&
    visible(key) && !key.disabled && !key.readOnly && visible(passphrase) &&
    passphrase.type === 'password' && !passphrase.disabled && !passphrase.readOnly &&
    !visible(node('#ssh-password')) && node('#ssh-password').value === '';'''

KEY_REJECTED_WITNESS = '''const status = node('#ssh-status');
  return visible(status) && status.innerText === '连接失败或已中断，请核查连接资料。' &&
    !visible(node('#ssh-live')) && !visible(node('#ssh-key-change')) &&
    node('#ssh-live-endpoint').innerText === '' && node('#ssh-connect').disabled &&
    arguments[0].every(s => node(s).value === '');'''


def require(condition, code):
    if not condition:
        raise GuiFailure(code)


class DesktopDriver(WebDriver):
    def start(self, binary):
        def ready():
            try:
                return self.call('GET', '/status').get('ready') is True
            except (OSError, ValueError):
                return False

        wait_for(ready, 'webdriver_unavailable')
        reply = self.call('POST', '/session', {'capabilities': {'alwaysMatch': {
            'webkitgtk:browserOptions': {'binary': str(binary.resolve()), 'args': []},
        }}})
        self.session = '/session/' + reply['sessionId']

    def observe(self, script, *args):
        helpers = '''const node = selector => document.querySelector(selector);
            const visible = el => !!el && el.getClientRects().length > 0 &&
                getComputedStyle(el).visibility === 'visible';
            const actionableButton = (el, label) => {
                if (!visible(el) || el.tagName !== 'BUTTON' || el.disabled || el.closest('[inert]') ||
                    (label !== undefined && el.innerText !== label)) return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 &&
                    r.right <= innerWidth && r.bottom <= innerHeight &&
                    el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
            };'''
        return self.call('POST', self.session + '/execute/sync', {'script': helpers + script, 'args': args})

    def click(self, selector):
        # The native element command owns scrolling, hit testing and activation.
        wait_for(lambda: self.observe('const el = node(arguments[0]); return visible(el) && !el.disabled;',
                                     selector), 'control_unavailable_' + selector.lstrip('#'))
        self.call('POST', self.element(selector) + '/click', {})

    def fill(self, selector, value):
        self.click(selector)
        field = self.element(selector)
        self.call('POST', field + '/clear', {})
        # Element Send Keys in WebKitGTK drops literal newlines. Native Enter
        # preserves the encrypted PEM's line boundaries in its textarea.
        strokes = value.replace('\n', '\ue007') if selector == '#ssh-key' else value
        self.call('POST', field + '/value', {'text': strokes, 'value': list(strokes)})
        require(self.read(selector, 'value') == value, 'form_input_mismatch_' + selector.lstrip('#'))

    def send_test_line(self):
        self.call('POST', self.session + '/actions', {'actions': [{
            'type': 'key', 'id': 'ordinary-ssh-keyboard',
            'actions': [{'type': action, 'value': key} for key in TYPED_LINE for action in ('keyDown', 'keyUp')],
        }]})


def probe_evidence(facts, count):
    events = facts['connectionEvents']
    require(facts['connections'] == len(events) == count, 'direct_ssh_connection_count_invalid')
    probe = events[0]
    # Product discovery records the host key and deliberately rejects it before
    # completing SSH negotiation. The full key is checked in the user review.
    require(probe['id'] == 1 and probe['hostKey'] == 'A' and probe['closed'] is True
            and all(probe[field] == 0 for field in CHECK_FIELDS),
            'direct_ssh_probe_not_empty')
    if count == 1:
        require(facts['connectionsClosed'] is True, 'direct_ssh_probe_not_closed')


def session_evidence(facts, *, sent, closed):
    probe_evidence(facts, 2)
    verify_shell(facts, 2, 'A', sent=sent, closed=closed, publickey=False)


def verify_shell(facts, connection, host_key, *, sent, closed, publickey):
    session = facts['connectionEvents'][connection - 1]
    attempts = (1, 2) if publickey else (1,)
    code = 'direct_ssh_key_shell_unproven' if publickey else 'direct_ssh_password_shell_unproven'
    require(session['id'] == connection and session['hostKey'] == host_key and session['handshakeCompleted'] is True
            and session['authAccepted'] is True and session['authAttempts'] in attempts and session['authSuccesses'] == 1
            and session['ptyRequests'] == session['shellRequests'] == 1 and session['outputBytes'] > 0,
            code)
    # The fixture's anchored marker matcher plus the exact length excludes a
    # prefix, trailing bytes or replay. The sole terminator is CR or LF.
    require(session['markerReceived'] is sent and session['inputBytes'] == (9 if sent else 0)
            and (not publickey or session.get('singleMarkerLineExact') is sent),
            'direct_ssh_unexpected_input')
    require(facts['connectionsClosed'] is closed and session['closed'] is closed
            and session['sessionClosed'] is closed
            and (not closed or session['closeReason'] in ('peer_eof', 'transport_closed')),
            'direct_ssh_close_order_invalid')


def rejected_key_evidence(facts, count):
    probe_evidence(facts, count)
    rejected = facts['connectionEvents'][1]
    require(rejected['id'] == 2 and rejected['hostKey'] == 'A'
            and rejected['handshakeCompleted'] is True and rejected['closed'] is True
            and not rejected['authAccepted'] and not rejected['markerReceived'] and not rejected['sessionClosed']
            and all(rejected[field] == 0 for field in CHECK_FIELDS)
            and (count != 2 or facts['connectionsClosed'] is True),
            'direct_ssh_wrong_passphrase_peer_not_empty')


def key_session_evidence(facts, *, sent, closed):
    rejected_key_evidence(facts, 3)
    verify_shell(facts, 3, 'A', sent=sent, closed=closed, publickey=True)


def fill_encrypted_credentials(driver, fixture, endpoint, *, passphrase):
    wait_for(lambda: driver.observe(KEY_FIELDS_WITNESS, endpoint), 'direct_ssh_key_fields_unproven')
    require(driver.observe('return node("#ssh-connect").disabled && '
                           'arguments[0].every(s => node(s).value === "");', SECRET_FIELDS),
            'direct_ssh_key_fields_not_empty')
    driver.fill('#ssh-key', fixture.private_key)
    require(driver.observe('return node("#ssh-connect").disabled && node("#ssh-passphrase").value === "";'),
            'direct_ssh_encrypted_key_did_not_require_passphrase')
    driver.fill('#ssh-passphrase', passphrase)
    require(driver.observe(KEY_FIELDS_WITNESS, endpoint), 'direct_ssh_key_review_changed')
    wait_for(lambda: driver.observe('return actionableButton(node("#ssh-connect"), "连接 SSH");'),
             'direct_ssh_key_connect_not_actionable')


def exercise_wrong_passphrase(driver, fixture, endpoint, report):
    fill_encrypted_credentials(driver, fixture, endpoint, passphrase=fixture.wrong_passphrase)
    # No state-changing action is repeated. Continue only after the explicit
    # failed UI outcome and the closed, unauthenticated transport both exist.
    driver.click('#ssh-connect')
    wait_for(lambda: driver.observe(KEY_REJECTED_WITNESS, SECRET_FIELDS),
             'direct_ssh_wrong_passphrase_not_rejected')
    require(fixture.wait_for_connections_closed(2), 'direct_ssh_wrong_passphrase_peer_open')
    rejected_key_evidence(fixture.snapshot(), 2)
    report['wrongPassphrase'] = {'localRejectionObserved': True, 'handshakeCompleted': True,
                                 'authenticationAttempts': 0, 'ptyRequests': 0, 'inputBytes': 0,
                                 'transportClosed': True, 'credentialsCleared': True}


def terminal_geometry(driver, endpoint):
    return driver.observe('''const endpoint = node('#ssh-live-endpoint');
        const output = node('#ssh-terminal-output');
        const screen = node('#ssh-terminal .xterm-screen');
        if (!visible(screen) || !visible(endpoint) || endpoint.innerText !== arguments[0] ||
            visible(node('#ssh-setup')) || arguments[1].some(selector => node(selector).value !== '') ||
            document.querySelectorAll('#ssh-terminal .xterm-helper-textarea').length !== 1 ||
            document.activeElement !== node('#ssh-terminal .xterm-helper-textarea') ||
            document.hidden || !document.hasFocus() || devicePixelRatio !== 1 || innerWidth < 960) return null;
        const target = endpoint.getBoundingClientRect();
        if (target.left < 0 || target.top < 0 || target.right > innerWidth || target.bottom > innerHeight ||
            !endpoint.contains(document.elementFromPoint((target.left + target.right) / 2,
                                                         (target.top + target.bottom) / 2))) return null;
        const r = screen.getBoundingClientRect(), c = output.getBoundingClientRect();
        const left = Math.ceil(Math.max(0, r.left, c.left + output.clientLeft));
        const top = Math.ceil(Math.max(0, r.top, c.top + output.clientTop));
        const right = Math.floor(Math.min(innerWidth, r.right, c.left + output.clientLeft + output.clientWidth));
        const bottom = Math.floor(Math.min(innerHeight, r.bottom, c.top + output.clientTop + output.clientHeight));
        if (!screen.contains(document.elementFromPoint((left + right) / 2, (top + bottom) / 2))) return null;
        return right - left >= 300 && bottom - top >= 120 ? {
            viewport: [innerWidth, innerHeight], bounds: [left, top, right - left, bottom - top],
            endpointBounds: [target.left, target.top, target.width, target.height],
        } : null;''', endpoint, SECRET_FIELDS)


def decode_viewport_capture(value, viewport):
    try:
        if not isinstance(value, str) or len(value) > 10_700_000:
            raise ValueError()
        png = base64.b64decode(value, validate=True)
        if len(png) > 8_000_000 or not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError()
        with Image.open(io.BytesIO(png)) as image:
            if image.format != 'PNG' or list(image.size) != viewport:
                raise ValueError()
        return png
    except (binascii.Error, OSError, ValueError, Image.DecompressionBombError):
        raise GuiFailure('direct_ssh_viewport_png_invalid') from None


def capture_terminal(driver, endpoint, token):
    # A native WebDriver screenshot contains the WebView viewport. Measurements
    # on both sides of the capture must agree in original one-to-one pixels.
    for capture_index in range(1, 4):
        before = wait_for(lambda: terminal_geometry(driver, endpoint), 'direct_ssh_terminal_geometry_missing')
        png = decode_viewport_capture(driver.call('GET', driver.session + '/screenshot'), before['viewport'])
        require(terminal_geometry(driver, endpoint) == before, 'direct_ssh_terminal_geometry_changed')
        try:
            screen = verify_terminal_screenshot(png, expected_token=token, bounds=before['bounds'])
            return png, {**screen, 'captureAttempt': capture_index, 'capture': 'native WebKitGTK WebDriver viewport',
                         'targetBounds': before['endpointBounds']}
        except ScreenshotGateError as error:
            if str(error) not in RENDER_PENDING or capture_index == 3:
                raise
            time.sleep(.2)  # Only the pixels may be read again.


def capture_outcome(driver, selector):
    # Snapshot only after the real UI assertions; do not alter visibility or replay input.
    def geometry():
        return driver.observe('''const el = node(arguments[0]);
            if (!visible(el) || document.hidden || !document.hasFocus() || devicePixelRatio !== 1) return null;
            const r = el.getBoundingClientRect();
            if (r.left < 0 || r.top < 0 || r.right > innerWidth || r.bottom > innerHeight ||
                r.width <= 0 || r.height <= 0) return null;
            return {viewport: [innerWidth, innerHeight], bounds: [r.left, r.top, r.width, r.height]};''', selector)
    before = wait_for(geometry, 'direct_ssh_outcome_geometry_missing')
    png = decode_viewport_capture(driver.call('GET', driver.session + '/screenshot'), before['viewport'])
    require(geometry() == before, 'direct_ssh_outcome_geometry_changed')
    return png, {'imageSha256': hashlib.sha256(png).hexdigest(), 'imageSize': before['viewport'],
                 'bounds': before['bounds'], 'capture': 'native WebKitGTK WebDriver viewport'}


def execute(driver, fixture, report, *, encrypted=False):
    host = '127.0.0.1'
    endpoint = f'{fixture.username}@{host}:{fixture.port}'
    algorithm = fixture.public_key.split(' ', 1)[0]
    report['stage'] = 'dashboard'
    # The private catalog starts empty. Wait for its card: the transient header
    # disappears when the desktop empty layout finishes loading.
    wait_for(lambda: driver.observe(DASHBOARD_WITNESS), 'direct_ssh_empty_dashboard_entry_unavailable')
    driver.click('#host-empty-add')
    report['stage'] = 'connection_choice'
    wait_for(lambda: driver.observe(CHOICE_WITNESS), 'direct_ssh_connection_choice_unavailable')
    driver.click('#add-ssh')
    report['stage'] = 'target'
    wait_for(lambda: driver.observe(TARGET_WITNESS), 'direct_ssh_target_form_unavailable')
    for selector, value in (('#ssh-host', host), ('#ssh-port', str(fixture.port)), ('#ssh-user', fixture.username)):
        driver.fill(selector, value)
    require(driver.observe('return ["#ssh-password", "#ssh-connect", "#ssh-review"].every(s => node(s).disabled);'),
            'direct_ssh_credentials_ungated_before_probe')

    report['stage'] = 'probe'
    driver.click('#ssh-probe')
    wait_for(lambda: driver.observe(REVIEW_WITNESS, endpoint, algorithm, fixture.fingerprint),
             'direct_ssh_fingerprint_not_visible_or_mismatched')
    require(fixture.wait_for_connections_closed(1), 'direct_ssh_probe_not_closed')
    probe_evidence(fixture.snapshot(), 1)
    report['stage'] = 'authentication'
    driver.click('#ssh-trust-confirm')
    wait_for(lambda: driver.observe('''const endpoint = node('#ssh-reviewed-endpoint'), password = node('#ssh-password');
        const step = node('#ssh-step-title'), choice = node('#ssh-auth-password');
        return visible(step) && step.innerText === 'SSH 账号认证' && !visible(node('#ssh-trust-review')) &&
            visible(node('#ssh-credentials')) && visible(endpoint) && endpoint.innerText === arguments[0] &&
            node('#ssh-review').checked && node('#ssh-auth-method').value === 'password' &&
            visible(choice) && choice.getAttribute('aria-pressed') === 'true' && visible(password) &&
            password.type === 'password' && !password.disabled && !password.readOnly &&
            node('#ssh-connect').disabled;''', endpoint),
            'direct_ssh_password_review_invalid')
    report['target'] = {'host': host, 'port': fixture.port, 'username': fixture.username,
                        'algorithm': algorithm, 'fingerprint': fixture.fingerprint}
    report['fingerprintReviewed'] = True

    verify_session = key_session_evidence if encrypted else session_evidence
    connection_count = 3 if encrypted else 2
    if encrypted:
        report['stage'] = 'wrong_passphrase'
        driver.click('#ssh-auth-key')
        exercise_wrong_passphrase(driver, fixture, endpoint, report)
    report['stage'] = 'connect'
    if encrypted:
        fill_encrypted_credentials(driver, fixture, endpoint, passphrase=fixture.passphrase)
        rejected_key_evidence(fixture.snapshot(), 2)
    else:
        driver.fill('#ssh-password', fixture.password)
    driver.click('#ssh-connect')
    require(fixture.wait_for('shellRequested'), 'direct_ssh_shell_not_requested')
    wait_for(lambda: bool(fixture.snapshot()['connectionEvents'][-1]['outputBytes']), 'direct_ssh_shell_no_output')
    verify_session(fixture.snapshot(), sent=False, closed=False)
    if encrypted:
        report['publicKeyAuthenticated'] = True
    wait_for(lambda: driver.observe('const el = node("#ssh-live-endpoint"); '
                                    'return visible(el) && el.innerText === arguments[0];', endpoint),
             'direct_ssh_live_target_mismatched')

    report['stage'] = 'input'
    driver.click('#ssh-terminal .xterm-screen')
    wait_for(lambda: terminal_geometry(driver, endpoint), 'direct_ssh_input_target_unproven')
    driver.send_test_line()
    require(fixture.wait_for('markerReceived'), 'direct_ssh_marker_not_received')
    verify_session(fixture.snapshot(), sent=True, closed=False)

    report['stage'] = 'capture'
    png, screen = capture_terminal(driver, endpoint, fixture.screen_token)
    verify_session(fixture.snapshot(), sent=True, closed=False)

    report['stage'] = 'disconnect'
    driver.click('#ssh-disconnect')
    wait_for(lambda: driver.observe('''const card = node('#ssh-closed-feedback');
        const title = node('#ssh-closed-title'), detail = node('#ssh-closed-detail');
        return visible(card) && visible(title) && visible(detail) && card.contains(title) && card.contains(detail) &&
            card.dataset.phase === 'confirmed' && actionableButton(node('#ssh-return-home'), '返回首页') &&
            title.innerText === '本机已断开' && detail.innerText === '凭据已清空，重连时请重新填写。' &&
            !visible(node('#ssh-live')) && node('#ssh-live-endpoint').innerText === '';'''),
             'direct_ssh_ui_disconnect_unconfirmed')
    require(fixture.wait_for_connections_closed(connection_count), 'direct_ssh_peer_disconnect_unconfirmed')
    verify_session(fixture.snapshot(), sent=True, closed=True)
    require(driver.observe('return arguments[0].every(s => node(s).value === "") && '
                           'node("#ssh-connect").disabled;', SECRET_FIELDS), 'direct_ssh_credentials_not_cleared')
    outcome_png, outcome = capture_outcome(driver, '#ssh-closed-feedback')
    verify_session(fixture.snapshot(), sent=True, closed=True)
    report['stage'] = 'return_home'
    driver.click('#ssh-return-home')
    wait_for(lambda: driver.observe('''const home = node('#home-dashboard'), result = node('#host-ssh-disconnected');
        const empty = node('#host-empty'), add = node('#host-empty-add'), shortcut = node('#home-open-ssh');
        return visible(home) && visible(result) && home.contains(result) && result.innerText === '本机已断开' &&
            result.dataset.phase === 'confirmed' && visible(empty) && home.contains(empty) && empty.contains(add) &&
            actionableButton(add, '添加主机') && home.contains(shortcut) && actionableButton(shortcut, '普通 SSH') &&
            !visible(node('#home-ssh'));'''),
             'direct_ssh_home_not_restored')
    home_png, home = capture_outcome(driver, '#host-ssh-disconnected')
    verify_session(fixture.snapshot(), sent=True, closed=True)
    report.update(terminal=screen, disconnectOutcome=outcome, homeOutcome=home,
                  returnedHome=True, credentialFieldsCleared=True)
    return {'ordinary-terminal.png': png, 'ordinary-disconnect.png': outcome_png, 'ordinary-home.png': home_png}



def driver_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def port_is_released(port):
    with socket.socket() as client:
        client.settimeout(.25)
        return client.connect_ex(('127.0.0.1', port)) == errno.ECONNREFUSED


def native_run(app, report, *, encrypted=False):
    report['stage'] = 'launch'
    driver = DesktopDriver()
    port = driver_port()
    driver.base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='hp-tauri-linux-direct-') as temporary:
        root = Path(temporary)
        env = {key: os.environ[key] for key in ('PATH', 'DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                                               'LANG', 'LC_ALL', 'WEBKIT_DISABLE_COMPOSITING_MODE',
                                               'LIBGL_ALWAYS_SOFTWARE', 'GDK_SCALE', 'GDK_DPI_SCALE') if key in os.environ}
        env.update(HOME=str(root), SHELL='/bin/sh', TAURI_AUTOMATION='true', TAURI_WEBVIEW_AUTOMATION='true')
        for item in ('CONFIG', 'STATE', 'DATA', 'CACHE', 'RUNTIME'):
            path = root / item.lower()
            path.mkdir(mode=0o700)
            env[f'XDG_{item}_{"DIR" if item == "RUNTIME" else "HOME"}'] = str(path)
        # The GTK driver already serves W3C. Use its owned loopback listener
        # directly so an intermediary cannot drop an action's HTTP response.
        with owned_process(['WebKitWebDriver', '--host=127.0.0.1', f'--port={port}'],
                           cwd=root, env=env, log=root / 'driver.log') as process:
            try:
                driver.start(app)
                rect = driver.call('POST', driver.session + '/window/rect', {'width': 1440, 'height': 1200})
                require(rect.get('width') == 1440 and rect.get('height') == 1200,
                        'direct_ssh_window_size_unconfirmed')
                fixture_class = EncryptedKeyFixture if encrypted else DirectSshFixture
                with fixture_class(screen_proof=True, channel_deadline=time.monotonic() + 240) as fixture:
                    try:
                        images = execute(driver, fixture, report, encrypted=encrypted)
                    finally:
                        # Snapshot before fixture cleanup, so a forced close
                        # can never appear as a successful user disconnect.
                        report['peer'] = fixture.snapshot()
                report['stage'] = 'cleanup'
                require(fixture.snapshot()['connectionsClosed'] is True and fixture.password == ''
                        and port_is_released(fixture.port), 'direct_ssh_fixture_cleanup_unconfirmed')
                if encrypted:
                    require(not any((fixture.private_key, fixture.passphrase, fixture.wrong_passphrase)),
                            'direct_ssh_fixture_credentials_not_cleared')
            except BaseException:
                with suppress(GuiFailure, OSError, ValueError):
                    driver.close()
                raise
            else:
                try:
                    driver.close()
                except (GuiFailure, OSError, ValueError):
                    raise GuiFailure('direct_ssh_webdriver_session_cleanup_unconfirmed') from None
        require(process.poll() is not None, 'direct_ssh_driver_process_still_running')
        wait_for(lambda: port_is_released(port), 'direct_ssh_driver_ports_not_released', timeout=5)
    require(not root.exists(), 'direct_ssh_temporary_resources_remain')
    report['cleanup'] = {'peerListenerReleased': True, 'fixturePasswordCleared': True,
                         'webdriverProcessStopped': True, 'webdriverPortsReleased': True, 'privateDirectoryRemoved': True}
    if encrypted:
        report['cleanup']['fixtureKeyAndPassphrasesCleared'] = True
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--authentication', choices=('password', 'key'), default='password')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.source_sha) or not args.app.is_file():
        parser.error('a built native app and a full source SHA are required')

    # WebDriver carries a disposable password over an owned loopback only.
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'sourceSHA': args.source_sha, 'platform': 'Linux Tauri GTK / Xvfb',
              'authentication': 'publickey' if args.authentication == 'key' else 'password',
              'scope': 'native application and isolated loopback SSH', 'status': 'failed'}
    try:
        images = native_run(args.app.resolve(), report, encrypted=args.authentication == 'key')
        for name, png in images.items():
            (args.output / name).write_bytes(png)
        report.update(status='passed', stage='complete')
    except (GuiFailure, ScreenshotGateError) as error:
        report['errorCode'] = str(error)
    except Exception:  # noqa: BLE001 - never publish arbitrary driver or peer exception text.
        report['errorCode'] = 'linux_direct_ssh_runner_failed'
    (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if report['status'] != 'passed':
        print(f"Linux Tauri ordinary SSH failed at {report.get('stage')}: {report['errorCode']}", flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
