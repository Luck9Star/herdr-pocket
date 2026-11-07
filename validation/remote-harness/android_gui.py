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
from flutter_android_gui import DeviceFailure, wait_system_ime

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


def system_keyboard(visible):
    try:
        return wait_system_ime(lambda: (adb('shell', 'dumpsys', 'input_method'),
            adb('shell', 'dumpsys', 'window', 'displays')), PACKAGE, visible)
    except DeviceFailure as error:
        raise GuiFailure(str(error)) from None


def exercise_keyboard(browser, approval, mode):
    """Real system window evidence; focus only selects the editor to exercise."""
    if mode not in ('direct', 'draft'):
        raise GuiFailure('android_keyboard_mode_invalid')
    expected = b'' if mode == 'direct' else b'k'
    draft = browser.read('#remote-input-draft', 'value') if mode == 'draft' else None
    target = browser.read('#remote-input-target')
    if not isinstance(target, str) or not target:
        raise GuiFailure('android_keyboard_target_missing')
    evidence = []
    for visible, selector in ((True, '#remote-keyboard-show'), (False, '#remote-keyboard-hide')):
        browser.click(selector)
        sample = system_keyboard(visible)
        approval.verify_ssh(expected)
        if mode == 'draft' and browser.read('#remote-input-draft', 'value') != draft:
            raise GuiFailure('android_keyboard_changed_local_draft')
        if browser.read('#remote-input-target') != target:
            raise GuiFailure('android_keyboard_target_changed')
        if not visible and browser.evaluate("document.querySelector('#remote-keyboard-show')?.disabled===true") is not True:
            raise GuiFailure('android_keyboard_hide_did_not_revoke_input')
        evidence.append({**sample, 'checkpoint': 'keyboard-' + mode + ('-shown' if visible else '-hidden')})
        if mode == 'draft' and visible:
            if sample.get('visible') is not True or sample.get('ownedTarget') is not True:
                raise GuiFailure('android_system_back_requires_visible_owned_ime')
            focus_expression = "document.activeElement===document.querySelector('#remote-input-draft')"
            before_focus = browser.evaluate(focus_expression)
            if type(before_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            # Exactly one real system Back, only after owned IME visibility.
            # Never retry this action: a second Back could navigate the app.
            adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
            hidden = system_keyboard(False)
            after_focus = browser.evaluate(focus_expression)
            if type(after_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            approval.verify_ssh(expected)
            if browser.read('#remote-input-draft', 'value') != draft or browser.read('#remote-input-target') != target:
                raise GuiFailure('android_system_back_changed_draft_or_target')
            evidence.append({**hidden, 'checkpoint': 'keyboard-draft-back-hidden',
                'systemBackSent': True, 'editorFocusedBeforeBack': before_focus,
                'editorFocusedAfterBack': after_focus})
            reselected = browser.evaluate("document.querySelector('#remote-keyboard-show')?.disabled===true")
            if type(reselected) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            if reselected:
                browser.click('#remote-input-draft-mode')
                wait_for(lambda: '草稿仅在核对' in (browser.read('#remote-input-status') or ''),
                         'android_keyboard_mode_reentry_missing')
            browser.click('#remote-keyboard-show')
            reopened = system_keyboard(True)
            approval.verify_ssh(expected)
            if browser.read('#remote-input-draft', 'value') != draft or browser.read('#remote-input-target') != target:
                raise GuiFailure('android_system_back_changed_draft_or_target')
            reopened_focus = browser.evaluate(focus_expression)
            if type(reopened_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            evidence.append({**reopened, 'checkpoint': 'keyboard-draft-back-reopened',
                'modeReselected': reselected, 'editorFocused': reopened_focus})
    # Hide revokes input. Only an explicit mode action may reopen the editor;
    # wait for the system window again before the original synthetic commit.
    browser.click('#remote-input-' + ('direct' if mode == 'direct' else 'draft-mode'))
    wait_for(lambda: ('逐键输入已启用' if mode == 'direct' else '草稿仅在核对') in
             (browser.read('#remote-input-status') or ''), 'android_keyboard_mode_reentry_missing')
    if mode == 'direct':
        sample = system_keyboard(True)
        approval.verify_ssh(expected)
        evidence.append({**sample, 'checkpoint': 'keyboard-direct-reopened'})
    return evidence


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

    def evaluate(self, expression, *, user_gesture=False):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True,
                                                'userGesture': user_gesture})
        if 'exceptionDetails' in result:
            raise GuiFailure('android_control_operation_failed')
        return result.get('result', {}).get('value')

    def copy_synthetic_clipboard(self):
        """Copy only the constant fixture value into this disposable emulator."""
        self.fill('#remote-input-draft', '测')
        copied = self.evaluate(
            "(()=>{const e=document.querySelector('#remote-input-draft');"
            "if(!e || document.activeElement!==e || e.value!=='测') return false;"
            "e.focus();e.select();return document.execCommand('copy')})()",
            user_gesture=True)
        if copied is not True:
            raise GuiFailure('android_synthetic_clipboard_copy_failed')

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

    def direct_key(self, key):
        # Dispatch a real key through the focused xterm textarea, without Enter.
        if key != 'k' or not self.evaluate("document.activeElement === document.querySelector('#remote-terminal .xterm-helper-textarea')"):
            raise GuiFailure('android_direct_focus_missing')
        for kind in ('keyDown', 'keyUp'):
            params = {'type': kind, 'key': key, 'code': 'KeyK', 'windowsVirtualKeyCode': 75}
            if kind == 'keyDown':
                params.update({'text': key, 'unmodifiedText': key})
            self.call('Input.dispatchKeyEvent', params)

    def hidden_key_probe(self):
        # Exercise the old view after navigation; receiver must remain unchanged.
        for kind in ('keyDown', 'keyUp'):
            params = {'type': kind, 'key': 'z', 'code': 'KeyZ', 'windowsVirtualKeyCode': 90}
            if kind == 'keyDown':
                params.update({'text': 'z', 'unmodifiedText': 'z'})
            self.call('Input.dispatchKeyEvent', params)

    def receipt(self, previous, pane, length):
        def read_receipt():
            raw = self.evaluate("document.querySelector('#remote-input-status').dataset.receipt || null")
            if not raw or raw == previous:
                return False
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                raise GuiFailure('android_input_receipt_invalid') from None
            if (not isinstance(value, dict) or set(value) != {'requestId', 'paneId', 'terminalId', 'acceptedBytes'} or
                not isinstance(value['requestId'], str) or not re.fullmatch(r'[0-9a-f]{32}', value['requestId']) or
                value['paneId'] != pane or not isinstance(value['terminalId'], str) or
                not value['terminalId'] or type(value['acceptedBytes']) is not int or value['acceptedBytes'] != length):
                raise GuiFailure('android_input_receipt_invalid')
            return raw, value
        return wait_for(read_receipt, 'android_input_receipt_missing', timeout=60)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def restore_reviewed_draft(browser, pane_id, terminal_id, rendered):
    # A saved host is not a terminal target: restore the identity and explicitly
    # choose the same pane and terminal before asserting draft recovery.
    if browser.read('#remote-input-draft', 'value'):
        raise GuiFailure('android_unbound_draft_exposed')
    browser.click('#host-restore-review')
    browser.click('#host-restore')
    wait_for(lambda: browser.evaluate("document.querySelector('#host-restore-panel').hidden"),
             'android_identity_restore_missing', timeout=60)
    browser.click('#remote-review')
    browser.click('#remote-connect')
    selector = '#remote-panes button'
    button = wait_for(lambda: browser.evaluate(
        "document.querySelector('#remote-panes button')?.firstChild?.textContent || null"),
        'android_reentry_dashboard_missing', timeout=60)
    if button != f'{pane_id} · {terminal_id}':
        raise GuiFailure('android_reentry_target_mismatch')
    browser.click(selector)
    wait_for(lambda: rendered('full'), 'android_reentry_full_missing', timeout=60)
    wait_for(lambda: browser.evaluate("!document.querySelector('#remote-input-controls').hidden"),
             'android_reentry_input_controls_missing', timeout=60)
    browser.click('#remote-input-draft-mode')
    wait_for(lambda: '草稿仅在核对' in (browser.read('#remote-input-status') or ''),
             'android_reentry_draft_mode_missing')
    if browser.read('#remote-input-draft', 'value') != 'Pocket测':
        raise GuiFailure('android_reentry_draft_changed')


FONT_DIAGNOSTIC_GEOMETRY = r'''(()=>{
  const dialog=document.querySelector('.terminal-font-diagnostics[open]');
  const screen=dialog?.querySelector('.xterm-screen');
  if(!dialog)return null;
  const rowHost=screen?.querySelector('.xterm-rows');
  const rows=rowHost?[...rowHost.children]:[];
  const rect=(row,find)=>{
    const walker=document.createTreeWalker(row,NodeFilter.SHOW_TEXT);
    let node,chosen=null,offset=-1;
    while((node=walker.nextNode())){
      const index=find(node.data);
      if(index>=0){chosen=node;offset=index;}
    }
    if(!chosen)return null;
    const range=document.createRange();range.setStart(chosen,offset);range.setEnd(chosen,offset+1);
    const box=range.getBoundingClientRect();
    return box.width>0&&box.height>0?{left:box.left,width:box.width}:null;
  };
  const first=rect(rows[0]||document.createElement('div'),text=>text.indexOf('1'));
  const box=screen?.getBoundingClientRect();
  const cellWidth=first?.width||null, screenWidth=box?.width||null;
  const columns=cellWidth&&screenWidth?screenWidth/cellWidth:null;
  const markerColumns=rows.map(row=>{
    const marker=rect(row,text=>text.lastIndexOf('|'));
    return marker&&first&&cellWidth?1+Math.round((marker.left+marker.width/2-first.left-first.width/2)/cellWidth):null;
  });
  const markerOffsets=rows.map(row=>{
    const marker=rect(row,text=>text.lastIndexOf('|'));
    return marker&&first&&cellWidth?1+(marker.left+marker.width/2-first.left-first.width/2)/cellWidth:null;
  });
  return {rowCount:rows.length,columns:columns?Math.round(columns):null,columnRatio:columns,
    markerColumns,markerOffsets,cellWidthPx:cellWidth,screenWidthPx:screenWidth};
})()'''


def font_diagnostic_geometry(browser):
    value = browser.evaluate(FONT_DIAGNOSTIC_GEOMETRY)
    if not isinstance(value, dict):
        raise GuiFailure('android_font_diagnostic_dom_unavailable')
    if value.get('rowCount') not in (0, 8):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    width = value.get('screenWidthPx')
    if width is not None and (not isinstance(width, (int, float)) or width <= 0):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    ratio = value.get('columnRatio')
    if ratio is not None and (not isinstance(ratio, (int, float)) or abs(ratio - 16) > 0.2):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    offsets = value.get('markerOffsets')
    if not isinstance(offsets, list) or len(offsets) not in (0, 8):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    measured = [item is not None for item in offsets]
    if any(measured) and not all(measured):
        marker_status = 'partially_measurable'
    elif offsets and all(measured):
        if any(not isinstance(item, (int, float)) or abs(item - 15) > 0.2 for item in offsets):
            raise GuiFailure('android_font_diagnostic_marker_position_invalid')
        marker_status = 'verified'
    else:
        marker_status = 'unmeasurable'
    cell_width = value.get('cellWidthPx')
    if cell_width is not None and (not isinstance(cell_width, (int, float)) or cell_width <= 0):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    if value.get('columns') is not None and value['columns'] != 16:
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    markers = value.get('markerColumns')
    if not isinstance(markers, list) or len(markers) != len(offsets):
        raise GuiFailure('android_font_diagnostic_geometry_invalid')
    if marker_status == 'verified' and markers != [15] * 8:
        raise GuiFailure('android_font_diagnostic_marker_position_invalid')
    return {'rowCount': value['rowCount'], 'columns': value.get('columns'),
            'markerPositionStatus': marker_status,
            'markerColumn': 15 if marker_status == 'verified' else None,
            'markerColumnZeroBased': 14 if marker_status == 'verified' else None,
            'markerColumns': markers,
            'cellWidthPx': round(cell_width, 3) if cell_width is not None else None,
            'screenWidthPx': round(width, 3) if width is not None else None,
            'columnRatio': round(ratio, 4) if ratio is not None else None}


def exercise_font_diagnostics(browser, approval, rendered):
    """Open the production local sample, measure rendered xterm cells, then resume observation."""
    if not browser.evaluate("document.querySelector('#remote-font-diagnostics')?.disabled===false"):
        raise GuiFailure('android_font_diagnostic_control_unavailable')
    before = rendered('delta')
    browser.click('#remote-font-diagnostics')
    wait_for(lambda: browser.evaluate("!!document.querySelector('.terminal-font-diagnostics[open]')"),
             'android_font_diagnostic_dialog_missing')
    rendered_sample = wait_for(lambda: browser.evaluate("(()=>{const s=document.querySelector('.terminal-font-diagnostics [role=status]')?.textContent||'';return s.startsWith('示例已绘制')?'ready':s.startsWith('本地诊断样例不可用')?'failed':false})()"),
             'android_font_diagnostic_sample_missing')
    if rendered_sample != 'ready':
        raise GuiFailure('android_font_diagnostic_sample_unavailable')
    geometry = font_diagnostic_geometry(browser)
    state = browser.evaluate('''(()=>{const d=document.querySelector('.terminal-font-diagnostics[open]');
      const close=d?.querySelector('button');const trigger=document.querySelector('#remote-font-diagnostics');
      const area=document.querySelector('#remote-input-controls');const remote=document.querySelector('#remote-terminal .xterm-helper-textarea');
      const draft=document.querySelector('#remote-input-draft');
      return {dialogOpen:!!d,nativeModal:!!d&&d.matches(':modal'),ariaModal:d?.getAttribute('aria-modal')==='true',
        closeFocused:!!close&&document.activeElement===close,
        triggerEnabled:!!trigger&&!trigger.disabled,inputControlsPresent:!!area,
        inputControlsHidden:!!area&&area.hidden,
        keyboardShowDisabled:document.querySelector('#remote-keyboard-show')?.disabled===true,
        keyboardHideDisabled:document.querySelector('#remote-keyboard-hide')?.disabled===true,
        remoteTextareaReadOnly:!!remote&&remote.readOnly,
        remoteTextareaInputMode:remote?.getAttribute('inputmode')||null,
        remoteTextareaFocused:!!remote&&document.activeElement===remote,
        remoteDraftFocused:!!draft&&document.activeElement===draft};})()''')
    expected_state = {'dialogOpen': True, 'nativeModal': True, 'ariaModal': True,
        'closeFocused': True, 'triggerEnabled': True,
        'keyboardShowDisabled': True, 'keyboardHideDisabled': True,
        'remoteTextareaReadOnly': True, 'remoteTextareaInputMode': 'none', 'remoteTextareaFocused': False}
    if (not isinstance(state, dict) or
            state.get('remoteDraftFocused') is not False or
            type(state.get('inputControlsPresent')) is not bool or
            type(state.get('inputControlsHidden')) is not bool):
        raise GuiFailure('android_font_diagnostic_input_or_focus_guard_failed')
    for key, expected in expected_state.items():
        actual = state.get(key)
        # CDP decodes fresh JSON strings. Compare their values, and require
        # exact types so 0 and 1 cannot stand in for boolean focus evidence.
        if type(actual) is not type(expected) or actual != expected:
            raise GuiFailure('android_font_guard_' + key.lower())
    approval.verify_ssh(b'')
    during = rendered('delta')
    browser.click('.terminal-font-diagnostics button')
    wait_for(lambda: browser.evaluate("!document.querySelector('.terminal-font-diagnostics')"),
             'android_font_diagnostic_close_missing')
    focus = browser.evaluate("document.activeElement===document.querySelector('#remote-font-diagnostics')")
    if focus is not True:
        raise GuiFailure('android_font_diagnostic_focus_not_restored')
    def resumed_delta():
        count = rendered('delta')
        return count if count > during else False
    after = wait_for(resumed_delta, 'android_font_diagnostic_observation_not_resumed', timeout=30)
    approval.verify_ssh(b'')
    return {'geometry': geometry, 'inputLocked': True, 'safeFocus': True,
            'inputControlsPresent': state['inputControlsPresent'],
            'inputControlsHidden': state['inputControlsHidden'],
            'focusRestored': True, 'observationContinued': True,
            'deltaFramesBefore': before, 'deltaFramesDuring': during, 'deltaFramesAfter': after,
            'receivedInputBytesDuringProbe': 0}


def exercise_local_paste(browser, approval, receipt, raw_receipt):
    # Seed only synthetic text. Copy's temporary editor value is replaced before
    # either production clipboard read; no pre-existing clipboard is inspected.
    browser.copy_synthetic_clipboard()
    browser.fill('#remote-input-draft', 'Pocket')

    def unchanged_receipt():
        if browser.evaluate("document.querySelector('#remote-input-status').dataset.receipt || null") != raw_receipt:
            raise GuiFailure('android_paste_receipt_changed')
        if not browser.evaluate("document.querySelector('#remote-input-preview-area').hidden"):
            raise GuiFailure('android_paste_opened_send_preview')

    for choice, expected in (('cancel', 'Pocket'), ('append', 'Pocket测')):
        browser.click('#remote-read-paste')
        wait_for(lambda: not browser.evaluate("document.querySelector('#remote-paste-review').hidden"),
                 'android_paste_review_missing')
        if (browser.read('#remote-paste-preview') != '测' or
                browser.read('#remote-paste-target') != f"目标：{receipt['paneId']} · {receipt['terminalId']}" or
                browser.read('#remote-input-draft', 'value') != 'Pocket'):
            raise GuiFailure('android_paste_review_mismatch')
        unchanged_receipt()
        browser.click('#remote-paste-' + choice)
        wait_for(lambda: browser.evaluate("document.querySelector('#remote-paste-review').hidden"),
                 'android_paste_' + choice + '_missing')
        if browser.read('#remote-input-draft', 'value') != expected:
            raise GuiFailure('android_paste_' + choice + '_changed_draft')
        unchanged_receipt()
        # Each checkpoint is before any send-preview/confirmation. The real
        # receiver must still contain only the earlier direct character.
        approval.verify_ssh(b'k')
        if choice == 'cancel':
            # The paired form returns to observation when a paste is reviewed.
            browser.click('#remote-input-draft-mode')
            wait_for(lambda: '草稿仅在核对' in (browser.read('#remote-input-status') or '') and
                     browser.evaluate("document.activeElement === document.querySelector('#remote-input-draft')"),
                     'android_draft_focus_after_cancel_missing')
    return {'syntheticClipboardCopySucceeded': True, 'pasteReviewCancelled': True,
            'pasteCancelPreservedDraft': True, 'pasteAppendApplied': True,
            'pasteOperationsNoExtraSshBytes': True}


def run_android(args, root, env, config, approval):
    if bool(getattr(args, 'android_guarded_input', False)) != bool(getattr(args, 'input_fixture', None)):
        raise GuiFailure('android_guarded_input_fixture_mismatch')
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('ANDROID_SERIAL') != SERIAL or
            config.get('host') != '127.0.0.1' or
            not isinstance(config.get('port'), int) or not 1 <= config['port'] <= 65535 or
            not Path(args.tauri_app).is_file()):
        raise GuiFailure('android_unsafe_fixture')
    devices = [line.split()[:2] for line in adb('devices').splitlines()[1:] if line.strip()]
    if devices != [[SERIAL, 'device']]:
        raise GuiFailure('android_existing_or_non_emulator_device')
    if (adb('shell', 'getprop', 'ro.kernel.qemu') != '1' or
            adb('shell', 'getprop', 'ro.build.version.sdk') != '35' or
            adb('shell', 'am', 'get-current-user') != '0'):
        raise GuiFailure('android_emulator_api_mismatch')
    if 'package:' + PACKAGE in adb('shell', 'pm', 'list', 'packages').splitlines():
        raise GuiFailure('android_package_already_present')
    adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
    if adb('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard') != '1':
        raise GuiFailure('android_system_ime_fixture_configuration_failed')
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
        try:
            request = wait_for(lambda: browser.read('#pair-request','value'), 'android_public_request_missing', timeout=60)
        except GuiFailure as error:
            if str(error) != 'android_public_request_missing':
                raise
            phase = browser.evaluate("document.querySelector('#pair-status').dataset.createPhase || 'not_started'")
            allowed = {'review','catalog','device','ready','persist_failed','not_started'}
            failures = {'host_storage_unavailable','host_storage_busy','host_storage_corrupt','host_storage_lock_failed',
                        'host_path_bridge_unavailable','host_path_invalid','invalid_host_name',
                        'invalid_config','invalid_host_key','key_unavailable','invalid_device_key','pairing_busy',
                        'host_pairing_exists','host_already_exists','host_restore_required','invalid_public_field','unavailable'}
            allowed.update(stage+'_'+code for stage in ('catalog','device') for code in failures)
            raise GuiFailure('android_public_request_'+(phase if phase in allowed else 'unknown')) from None
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
        def board_phase():
            value = browser.evaluate("document.querySelector('#remote-panes [data-dashboard-phase]')?.dataset.dashboardPhase")
            return value if value in ('fresh', 'unavailable') else None
        initial_board = wait_for(board_phase, 'android_initial_host_board_phase_missing')
        browser.click(selector)
        def rendered(attr):
            return browser.evaluate(f"Number(document.querySelector('#remote-captured').dataset.{attr}Frames || 0)")
        full = wait_for(lambda: rendered('full'), 'android_full_render_ack_missing', timeout=60)
        deltas = wait_for(lambda: rendered('delta'), 'android_delta_render_ack_missing', timeout=60)
        font_diagnostic_evidence = exercise_font_diagnostics(browser, approval, rendered)
        receipts = []
        paste_evidence = {}
        keyboard_evidence = []
        if getattr(args, 'input_fixture', None):
            wait_for(lambda: browser.evaluate("!document.querySelector('#remote-input-controls').hidden"),
                     'android_input_controls_missing', timeout=60)
            browser.click('#remote-input-direct')
            wait_for(lambda: '逐键输入已启用' in (browser.read('#remote-input-status') or ''),
                     'android_direct_mode_missing')
            keyboard_evidence.extend(exercise_keyboard(browser, approval, 'direct'))
            browser.direct_key('k')
            raw, first = browser.receipt(None, config['paneId'], 1)
            receipts.append(first)
            browser.click('#remote-input-draft-mode')
            wait_for(lambda: '草稿仅在核对' in (browser.read('#remote-input-status') or ''),
                     'android_draft_mode_missing')
            browser.fill('#remote-input-draft', 'Pocket')
            keyboard_evidence.extend(exercise_keyboard(browser, approval, 'draft'))
            paste_evidence = exercise_local_paste(browser, approval, first, raw)
            browser.click('#host-return-home')
            wait_for(lambda: browser.evaluate("!document.querySelector('#host-home').hidden"), 'android_home_not_visible')
            if browser.evaluate("document.activeElement.matches('#remote-input-draft, #remote-terminal .xterm-helper-textarea')"):
                raise GuiFailure('android_hidden_input_still_focused')
            browser.hidden_key_probe()
            browser.click('#host-list .saved-host-actions button')
            wait_for(lambda: browser.evaluate("!document.querySelector('#host-restore-panel').hidden"),
                     'android_restore_panel_missing')
            approval.verify_ssh(b'k')
            restore_reviewed_draft(browser, config['paneId'], first['terminalId'], rendered)
            # Reconnection, selection and local recovery must not replay input.
            approval.verify_ssh(b'k')
            browser.click('#remote-input-preview')
            if browser.read('#remote-input-preview-text') != 'Pocket测':
                raise GuiFailure('android_draft_preview_mismatch')
            browser.click('#remote-input-confirm')
            _, second = browser.receipt(raw, config['paneId'], len('Pocket测'.encode('utf-8')))
            if second['requestId'] == first['requestId'] or second['terminalId'] != first['terminalId']:
                raise GuiFailure('android_input_receipt_target_mismatch')
            if browser.read('#remote-input-draft', 'value'):
                raise GuiFailure('android_submitted_draft_retained')
            receipts.append(second)
        else:
            if not browser.evaluate("['remote-keyboard-show','remote-keyboard-hide'].every(id=>document.getElementById(id)?.disabled===true)"):
                raise GuiFailure('android_readonly_keyboard_controls_enabled')
            keyboard_evidence.append({**system_keyboard(False), 'checkpoint': 'keyboard-observe-hidden'})
            approval.verify_ssh(b'')
        terminal_board = wait_for(board_phase, 'android_host_board_phase_during_terminal_missing')
        browser.click('#remote-cancel')
        wait_for(lambda: '陈旧' in (browser.read('#remote-captured') or ''), 'android_stale_marker_missing')
        return {'paired':True, 'paneChosen':True, 'fullRendered':True, 'deltaRendered':True,
                'stoppedStale':True, 'fullRenderAcknowledgements':full, 'deltaRenderAcknowledgements':deltas,
                'inputQueueAccepted':bool(receipts), 'inputReceipts':receipts,
                'fontDiagnosticEvidence':font_diagnostic_evidence,
                **paste_evidence,
                'systemKeyboardEvidence': {'checkpoints': keyboard_evidence, 'showWithHardwareKeyboard': True,
                    'scope': 'owned API35 IME service window; CDP commits are not IME touch/composition proof'},
                'hiddenReentryFreshFull':bool(receipts),
                'initialHostBoardPhase':initial_board, 'hostBoardPhaseDuringTerminal':terminal_board,
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
