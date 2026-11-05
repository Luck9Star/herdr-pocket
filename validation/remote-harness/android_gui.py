"""Drive the debug Android WebView on the disposable CI emulator, never mock IPC.

The only exported evidence is the fixed allowlist below. Raw CDP, adb, target
configuration and public pairing material stay inside the runner process.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from paired_gui import GuiFailure, wait_for

PACKAGE = 'dev.herdrpocket.tauriprobe'
SERIAL = 'emulator-5554'


def adb(*args, check=True, timeout=30):
    try:
        result = subprocess.run(['adb', '-s', SERIAL, *map(str, args)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GuiFailure('android_adb_unavailable') from None
    if check and result.returncode:
        raise GuiFailure('android_adb_command_failed')
    if len(result.stdout) > 1_048_576 or len(result.stderr) > 1_048_576:
        raise GuiFailure('android_adb_output_limit')
    return result.stdout.decode('utf-8', errors='replace').strip()


class AndroidWebView:
    """CDP input on real rendered controls; no internal JS or native commands."""
    def __init__(self, port):
        import websocket
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=5) as stream:
                pages = json.load(stream)
            matches = [p for p in pages if p.get('type') == 'page' and
                       ('tauri.localhost' in p.get('url', '') or p.get('url', '').startswith('tauri://localhost'))]
            if len(matches) != 1:
                raise GuiFailure('android_webview_target_missing')
            url = matches[0]['webSocketDebuggerUrl']
            # Never connect to a URL supplied by a page or network peer.
            path = re.search(r'/devtools/page/[A-Za-z0-9_-]+$', url)
            if not path:
                raise GuiFailure('android_webview_target_invalid')
            self.ws = websocket.create_connection(f'ws://127.0.0.1:{port}{path.group()}',
                                                  timeout=10, suppress_origin=True)
            self.sequence = 0
        except GuiFailure:
            raise
        except Exception:
            raise GuiFailure('android_webview_cdp_unavailable') from None

    def call(self, method, params=None):
        self.sequence += 1
        ident = self.sequence
        try:
            self.ws.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
            while True:
                frame = self.ws.recv()
                if len(frame) > 1_048_576:
                    raise GuiFailure('android_cdp_output_limit')
                reply = json.loads(frame)
                if reply.get('id') != ident:
                    continue
                if 'error' in reply:
                    raise GuiFailure('android_cdp_command_failed')
                return reply.get('result', {})
        except GuiFailure:
            raise
        except Exception:
            raise GuiFailure('android_cdp_transport_failed') from None

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        if 'exceptionDetails' in result:
            raise GuiFailure('android_control_operation_failed')
        return result.get('result', {}).get('value')

    def read(self, selector, prop='textContent'):
        if prop not in ('textContent', 'value'):
            raise GuiFailure('android_invalid_property')
        expression = f'(()=>{{const e=document.querySelector({json.dumps(selector)});return e?e.{prop}:null}})()'
        return self.evaluate(expression)

    def click(self, selector):
        # scrollIntoView is layout-only. Actual activation goes through CDP input.
        expression = '''(()=>{const e=document.querySelector(%s); if(!e || e.matches(':disabled') || e.hidden) return null;
          e.scrollIntoView({block:'center',inline:'center'}); const r=e.getBoundingClientRect();
          const x=r.left+r.width/2,y=r.top+r.height/2;
          return r.width>0 && r.height>0 && x>=0 && y>=0 && x<innerWidth && y<innerHeight &&
                 e.contains(document.elementFromPoint(x,y)) ? {x,y}:null})()''' % json.dumps(selector)
        point = wait_for(lambda: self.evaluate(expression), 'android_control_missing_'+selector.lstrip('#').replace(' ','_'))
        for kind in ('mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', {'type': kind, 'x': point['x'], 'y': point['y'],
                                                 'button': 'left', 'clickCount': 1})

    def fill(self, selector, value):
        expression = '''(()=>{const e=document.querySelector(%s); if(!e || !e.getClientRects().length || e.matches(':disabled') || e.readOnly) return false;
          e.scrollIntoView({block:'center'}); e.focus(); e.select(); return document.activeElement===e})()''' % json.dumps(selector)
        wait_for(lambda: self.evaluate(expression), 'android_text_control_missing_'+selector.lstrip('#'))
        self.call('Input.insertText', {'text': str(value)})
        if self.read(selector, 'value') != str(value):
            raise GuiFailure('android_text_input_mismatch')

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def run_android(args, root, env, config, approval):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('ANDROID_SERIAL') != SERIAL or
            config.get('host') != '127.0.0.1' or
            not isinstance(config.get('port'), int) or not 1 <= config['port'] <= 65535 or
            not Path(args.tauri_app).is_file()):
        raise GuiFailure('android_unsafe_fixture')
    if adb('shell', 'getprop', 'ro.kernel.qemu') != '1' or adb('shell', 'getprop', 'ro.build.version.sdk') != '35':
        raise GuiFailure('android_emulator_api_mismatch')
    if 'package:' + PACKAGE in adb('shell', 'pm', 'list', 'packages').splitlines():
        raise GuiFailure('android_package_already_present')
    forward = None
    installed = False
    browser = None
    reverse = f"tcp:{config['port']}"
    cleanup_failed = False
    try:
        adb('reverse', reverse, reverse)
        adb('install', str(args.tauri_app), timeout=90)
        installed = True
        adb('shell', 'monkey', '-p', PACKAGE, '-c', 'android.intent.category.LAUNCHER', '1')
        pid = wait_for(lambda: adb('shell', 'pidof', PACKAGE, check=False), 'android_app_not_started', timeout=60)
        if not re.fullmatch(r'\d+', pid):
            raise GuiFailure('android_app_pid_invalid')
        socket_name = 'webview_devtools_remote_' + pid
        wait_for(lambda: '@'+socket_name in adb('shell', 'cat', '/proc/net/unix', check=False),
                 'android_webview_debug_socket_missing', timeout=60)
        port = adb('forward', 'tcp:0', 'localabstract:'+socket_name)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise GuiFailure('android_forward_invalid')
        forward = 'tcp:' + port
        def connect():
            try:
                view = AndroidWebView(int(port))
                if view.evaluate("document.readyState === 'complete' && !!document.querySelector('#remote-form') && !!window.__TAURI_INTERNALS__"):
                    return view
                view.close()
            except GuiFailure:
                return False
            return False
        browser = wait_for(connect, 'android_webview_not_ready', timeout=60)
        browser.click('#host-open-remote')
        for field, key in [('host','host'), ('port','port'), ('user','username'), ('session','session'),
                           ('herdr','herdrPath'), ('socket','socketPath'), ('pin','expectedHostKey')]:
            browser.fill('#remote-'+field, config[key])
        browser.click('#pair-mode')
        browser.click('#pair-target-review')
        browser.click('#pair-create')
        request = wait_for(lambda: browser.read('#pair-request','value'), 'android_public_request_missing', timeout=60)
        if len(request.encode('utf-8')) > 2048:
            raise GuiFailure('android_public_request_oversize')
        response = approval.approve(request.encode('utf-8'))
        browser.fill('#pair-response', response.decode('utf-8'))
        browser.click('#pair-preview')
        browser.click('#pair-source-review')
        browser.click('#pair-accept')
        wait_for(lambda: '授权响应已审查' in (browser.read('#pair-status') or ''), 'android_authorization_not_reviewed', timeout=60)
        browser.click('#remote-review')
        browser.click('#remote-connect')
        selector = '#remote-panes button'
        button = wait_for(lambda: browser.read(selector), 'android_pane_dashboard_missing', timeout=60)
        if not button.startswith(config['paneId']+' · '):
            raise GuiFailure('android_unexpected_dashboard_pane')
        browser.click(selector)
        def rendered(attr):
            return browser.evaluate(f"Number(document.querySelector('#remote-captured').dataset.{attr}Frames || 0)")
        full = wait_for(lambda: rendered('full'), 'android_full_render_ack_missing', timeout=60)
        deltas = wait_for(lambda: rendered('delta'), 'android_delta_render_ack_missing', timeout=60)
        browser.click('#remote-cancel')
        wait_for(lambda: '陈旧' in (browser.read('#remote-captured') or ''), 'android_stale_marker_missing')
        return {'paired':True, 'paneChosen':True, 'fullRendered':True, 'deltaRendered':True,
                'stoppedStale':True, 'fullRenderAcknowledgements':full, 'deltaRenderAcknowledgements':deltas,
                'keyStore':'Android API 35 emulator AndroidKeyStore-wrapped device key',
                'device':'ephemeral Android emulator', 'uiDriver':'debug WebView CDP input'}
    finally:
        if browser:
            browser.close()
        if installed:
            try:
                adb('shell', 'am', 'force-stop', PACKAGE)
                adb('uninstall', PACKAGE, timeout=60)
            except GuiFailure:
                cleanup_failed = True
        if forward:
            try:
                adb('forward', '--remove', forward)
            except GuiFailure:
                cleanup_failed = True
        try:
            adb('reverse', '--remove', reverse)
        except GuiFailure:
            cleanup_failed = True
        if cleanup_failed:
            raise GuiFailure('android_cleanup_failed')
