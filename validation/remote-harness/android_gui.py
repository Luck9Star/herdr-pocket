"""Drive the debug Android WebView on the disposable CI emulator, never mock IPC.

The only exported evidence is the fixed allowlist below. Raw CDP, adb, target
configuration and public pairing material stay inside the runner process.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

from paired_gui import GuiFailure, wait_for
from paired_tui import STEPS
from mobile_blocked_result import checked_targets, checked_receipt
from flutter_android_gui import (
    DeviceFailure, public_host_fingerprint, public_ime_diagnostic, public_profile_json, wait_system_ime,
    safe_theme_prompt_cursors, theme_prompt_expectations,
)

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
        failure = GuiFailure(str(error))
        failure.system_ime_diagnostic = getattr(error, 'diagnostic', None)
        raise failure from None


class AndroidProgress:
    """Bounded per-stage evidence survives a later failure; no raw dumps/text."""
    PHASES = {'setup','pairing','canvas_selection','dashboard','board_search','observe_full','observe_delta','canvas_marker','font_diagnostics',
        'direct_mode','draft_mode','direct_input_receipt','paste_review','hidden_recovery',
        'draft_input_receipt','tui','stop_observation','blocked_target_entry','complete',
        'keyboard_observe_hidden','keyboard_direct_shown','keyboard_direct_hidden','keyboard_direct_reopened',
        'keyboard_draft_shown','keyboard_draft_back_request','keyboard_draft_back_hidden',
        'keyboard_draft_back_reopened','keyboard_draft_hidden','local_revocation_review','device_impact_review'}
    COMPLETED = {'publicProfileReviewed','publicRequestCopyReported','revocationReviewed','authorizationReviewed','paneChosen','fullRendered','deltaRendered',
        'canvasSelectionVerified','canvasGeometryVerified','canvasMarkerVisible','canvasViewportRestored',
        'fontDiagnosticsCompleted','directKeyboardCompleted','directReceiptVerified',
        'draftKeyboardCompleted','pasteReviewCompleted','draftRestored','draftReceiptVerified','tuiCompleted','stoppedStale','blockedTargetVerified',
        'boardSearchVerified','deviceImpactReviewed'}
    ERROR_CODES = {'android_blocked_target_evidence_invalid','android_blocked_card_missing','android_blocked_same_label_missing','android_blocked_review_required','android_blocked_render_missing','android_blocked_original_form_missing','android_system_ime_target_mismatch','android_system_ime_evidence_unavailable',
        'android_system_ime_show_unconfirmed','android_system_ime_hide_unconfirmed',
        'android_system_ime_expected_state_invalid','android_driver_failure',
        'android_canvas_default_invalid','android_canvas_selection_failed','android_canvas_viewport_missing',
        'android_canvas_marker_missing','android_canvas_geometry_invalid','android_canvas_scroll_failed',
        'android_canvas_marker_not_visible','android_canvas_viewport_restore_failed',
        'android_theme_selection_invalid','android_theme_selection_missing',
        'android_theme_measurement_missing','android_theme_measurement_invalid',
        'android_revoke_clock_invalid','android_revoke_device_time_unready','android_revoke_controls_unconfirmed',
        'android_board_search_state_invalid','android_board_search_count_mismatch','android_board_search_history_missing',
        'android_board_search_native_call','android_board_search_reset_missing','android_board_search_clear_missing',
        'android_board_search_counter_install_failed','android_board_search_counter_read_invalid',
        'android_board_search_counter_no_ipc','android_board_search_counter_unsettle_timeout',
        'android_home_not_visible','android_cdp_transport_failed','android_cdp_command_failed',
        'android_control_operation_failed',
        'android_select_option_missing','android_select_option_failed',
        'android_host_board_phase_during_terminal_missing','android_observer_still_active',
        'android_stale_marker_missing','android_tui_observe_return_missing',
        'android_device_impact_entry_missing','android_device_impact_status_invalid','android_device_impact_action_enabled',
        'android_device_impact_reread_invalid','android_device_impact_entry_lost','android_device_impact_write_invoked'}
    def __init__(self, args):
        self.stream = None; self.success = False
        sha = os.environ.get('GITHUB_SHA','')
        self.data = {'schemaVersion':1,'adapter':'tauri-android','status':'running','stage':'setup',
            'sourceSHA':sha if re.fullmatch(r'[0-9a-f]{40}',sha) else None,
            'completed':{key:False for key in sorted(self.COMPLETED)},
            'fullRenderAcknowledgements':0,'deltaRenderAcknowledgements':0,'inputReceiptCount':0,
            'systemImeChecks':[], 'cleanup':{key:'not_needed' for key in ('browser','application','forward','reverse')}}
        output = getattr(args,'output',None)
        if output is not None:
            parent = Path(output).absolute(); temporary = Path(os.environ.get('RUNNER_TEMP','/nonexistent')).resolve()
            if (not parent.is_dir() or parent.resolve()!=parent or parent==temporary or not parent.is_relative_to(temporary)):
                raise GuiFailure('android_progress_output_invalid')
            try:
                fd = os.open(parent/'tauri-android-progress.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                self.stream = os.fdopen(fd,'w',encoding='ascii')
            except OSError:
                raise GuiFailure('android_progress_output_unavailable') from None
        self.publish()
    def publish(self):
        payload=json.dumps(self.data,sort_keys=True,separators=(',',':'))+'\n'
        if len(payload)>16384:raise GuiFailure('android_progress_report_limit')
        if self.stream:
            try:
                self.stream.seek(0); self.stream.write(payload); self.stream.truncate(); self.stream.flush()
            except OSError:
                raise GuiFailure('android_progress_output_unavailable') from None
    def phase(self,value):
        if value not in self.PHASES:raise GuiFailure('android_progress_stage_invalid')
        self.data['stage']=value; self.publish()
    def mark(self,value):
        if value not in self.COMPLETED:raise GuiFailure('android_progress_stage_invalid')
        self.data['completed'][value]=True; self.publish()
    def count(self,key,value):
        if key not in ('fullRenderAcknowledgements','deltaRenderAcknowledgements','inputReceiptCount') or type(value) is not int or not 0<=value<=1_000_000:
            raise GuiFailure('android_progress_counter_invalid')
        self.data[key]=value; self.publish()
    def ime(self,sample):
        if len(self.data['systemImeChecks'])>=12:raise GuiFailure('android_progress_report_limit')
        item={'stage':self.data['stage'],'status':'passed','diagnostic':public_ime_diagnostic(sample.get('diagnostic'))}
        for key in ('ownedTarget','visible','hidden','windowVisible','decorVisible','inputViewShown','windowInsetsImeVisible'):
            if type(sample.get(key)) is bool:item[key]=sample[key]
        if type(sample.get('stableSamples')) is int and 2<=sample['stableSamples']<=100:item['stableSamples']=sample['stableSamples']
        self.data['systemImeChecks'].append(item); self.publish()
    def fail(self,error):
        code=str(error)
        # Dynamic per-control click waits are bounded static codes, not secrets.
        published = code if (code in self.ERROR_CODES or code.startswith('android_control_missing_')) else 'android_driver_failure'
        self.data.update(status='failed',errorCode=published)
        diagnostic=public_ime_diagnostic(getattr(error,'system_ime_diagnostic',None))
        if diagnostic:self.data['systemImeFailure']=diagnostic
        counter=_public_counter_context(getattr(error,'counter_context',None))
        if counter:self.data['counterContext']=counter
        click=getattr(error,'counter_click_context',None)
        if isinstance(click,dict) and all(isinstance(click.get(part),dict) for part in ('before','after')):
            self.data['counterClickContext']={part:_public_counter_context(click[part])
                                              for part in ('before','after')}
        home_status=getattr(error,'home_status',None)
        if isinstance(home_status,str):self.data['homeStatus']=' '.join(home_status.split())[:120]
        self.publish()
    def finish(self,cleanup_failed):
        self.data['status']='passed' if self.success and not cleanup_failed else 'failed'
        if cleanup_failed:self.data['cleanupErrorCode']='android_cleanup_failed'
        if self.data['status']=='passed':self.data['stage']='complete'
        self.publish()
        if self.stream:os.fsync(self.stream.fileno())
    def close(self):
        if self.stream:self.stream.close();self.stream=None


def wait_fixture_revocation_clock(browser, receipt, progress=None):
    """Wait passively for the AVD's own strict receipt window, never relax it."""
    try:
        value = json.loads(receipt)
        issued, expires = value['issued_at'], value['expires_at']
        if (value.get('status') != 'revoked' or type(issued) is not int or
                type(expires) is not int or not 0 <= issued < expires <= issued + 600):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise GuiFailure('android_revoke_clock_invalid') from None
    attempts = 0
    def ready():
        nonlocal attempts
        current = browser.evaluate('Math.floor(Date.now()/1000)')
        if type(current) is not int:
            raise GuiFailure('android_revoke_clock_invalid')
        attempts += 1
        sample = {'attempts': min(attempts, 99), 'issuedAtReached': current >= issued,
                  'notExpired': current < expires}
        if progress:
            progress.data['revocationClock'] = sample
            progress.publish()
        return sample['issuedAtReached'] and sample['notExpired']
    wait_for(ready, 'android_revoke_device_time_unready', timeout=5)


def require_revocation_review_controls(browser, progress=None):
    """Keep a public boolean diagnosis; never expose request or receipt text."""
    state = browser.evaluate("""(()=>{
      const accept=document.querySelector('#pair-accept');
      const source=document.querySelector('#pair-source-review');
      const preview=document.querySelector('#pair-response-preview');
      const fields=document.querySelector('#remote-fields');
      return {acceptPresent:!!accept,acceptDisabled:!accept||accept.matches(':disabled'),
        sourceChecked:source?.checked===true,previewVisible:!!preview&&!preview.hidden,
        fieldsDisabled:!fields||fields.disabled,documentHidden:document.hidden};})()""")
    keys = ('acceptPresent', 'acceptDisabled', 'sourceChecked', 'previewVisible',
            'fieldsDisabled', 'documentHidden')
    if not isinstance(state, dict) or any(type(state.get(key)) is not bool for key in keys):
        raise GuiFailure('android_revoke_controls_unconfirmed')
    clean = {key: state[key] for key in keys}
    if progress:
        progress.data['revocationControls'] = clean
        progress.publish()
    if not (clean['acceptPresent'] and clean['sourceChecked'] and clean['previewVisible'] and
            not clean['acceptDisabled'] and not clean['fieldsDisabled'] and not clean['documentHidden']):
        raise GuiFailure('android_revoke_controls_unconfirmed')


def exercise_keyboard(browser, approval, mode, progress=None):
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
        if progress:progress.phase('keyboard_'+mode+('_shown' if visible else '_hidden'))
        browser.click(selector)
        sample = system_keyboard(visible)
        approval.verify_ssh(expected)
        if mode == 'draft' and browser.read('#remote-input-draft', 'value') != draft:
            raise GuiFailure('android_keyboard_changed_local_draft')
        if browser.read('#remote-input-target') != target:
            raise GuiFailure('android_keyboard_target_changed')
        if not visible and browser.evaluate("document.querySelector('#remote-keyboard-show')?.disabled===true") is not True:
            raise GuiFailure('android_keyboard_hide_did_not_revoke_input')
        if progress:progress.ime(sample)
        evidence.append({**sample, 'checkpoint': 'keyboard-' + mode + ('-shown' if visible else '-hidden')})
        if mode == 'draft' and visible:
            if sample.get('visible') is not True or sample.get('ownedTarget') is not True:
                raise GuiFailure('android_system_back_requires_visible_owned_ime')
            focus_expression = "document.activeElement===document.querySelector('#remote-input-draft')"
            before_focus = browser.evaluate(focus_expression)
            if type(before_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            if progress:progress.phase('keyboard_draft_back_request')
            # Exactly one real system Back, only after owned IME visibility.
            # Never retry this action: a second Back could navigate the app.
            adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
            if progress:progress.phase('keyboard_draft_back_hidden')
            hidden = system_keyboard(False)
            after_focus = browser.evaluate(focus_expression)
            if type(after_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            approval.verify_ssh(expected)
            if browser.read('#remote-input-draft', 'value') != draft or browser.read('#remote-input-target') != target:
                raise GuiFailure('android_system_back_changed_draft_or_target')
            if progress:progress.ime(hidden)
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
            if progress:progress.phase('keyboard_draft_back_reopened')
            browser.click('#remote-keyboard-show')
            reopened = system_keyboard(True)
            approval.verify_ssh(expected)
            if browser.read('#remote-input-draft', 'value') != draft or browser.read('#remote-input-target') != target:
                raise GuiFailure('android_system_back_changed_draft_or_target')
            reopened_focus = browser.evaluate(focus_expression)
            if type(reopened_focus) is not bool:
                raise GuiFailure('android_keyboard_focus_evidence_invalid')
            if progress:progress.ime(reopened)
            evidence.append({**reopened, 'checkpoint': 'keyboard-draft-back-reopened',
                'modeReselected': reselected, 'editorFocused': reopened_focus})
    # Hide revokes input. Only an explicit mode action may reopen the editor;
    # wait for the system window again before the original synthetic commit.
    browser.click('#remote-input-' + ('direct' if mode == 'direct' else 'draft-mode'))
    wait_for(lambda: ('逐键输入已启用' if mode == 'direct' else '草稿仅在核对') in
             (browser.read('#remote-input-status') or ''), 'android_keyboard_mode_reentry_missing')
    if mode == 'direct':
        if progress:progress.phase('keyboard_direct_reopened')
        sample = system_keyboard(True)
        approval.verify_ssh(expected)
        if progress:progress.ime(sample)
        evidence.append({**sample, 'checkpoint': 'keyboard-direct-reopened'})
    return evidence


def _public_counter_context(value):
    """Bounded read-only page context only; drop unknown keys and unbounded URLs."""
    if not isinstance(value, dict):
        return None
    safe = {'readyState':'unknown','internals':False,'invokeType':'unknown','url':'unknown',
        'present':False,'count':0,'tallyKeys':[],'lastJsError':None,
        'clickSeen':0,'lastClickTarget':None,'errorCount':0}
    if value.get('readyState') in ('loading','interactive','complete'):
        safe['readyState'] = value['readyState']
    if type(value.get('internals')) is bool:
        safe['internals'] = value['internals']
    if value.get('invokeType') in ('function','undefined','object','string','number','boolean','symbol','bigint','missing'):
        safe['invokeType'] = value['invokeType']
    url = value.get('url')
    if isinstance(url, str) and url[:7] in ('tauri:/','http://','https:/','file://'):
        safe['url'] = url[:120]
    if type(value.get('present')) is bool:
        safe['present'] = value['present']
    count = value.get('count')
    if type(count) is int:
        safe['count'] = max(count, 0)
    keys = value.get('tallyKeys')
    if (isinstance(keys, list) and len(keys) <= 16 and
            all(isinstance(item, str) for item in keys)):
        safe['tallyKeys'] = [item[:64] for item in keys]
    last_error = value.get('lastJsError')
    if isinstance(last_error, str) and last_error:
        safe['lastJsError'] = last_error[:200]
    if type(value.get('clickSeen')) is int:
        safe['clickSeen'] = min(max(value['clickSeen'],0),1000)
    if isinstance(value.get('lastClickTarget'),str):
        safe['lastClickTarget'] = value['lastClickTarget'][:64]
    if type(value.get('errorCount')) is int:
        safe['errorCount'] = max(value['errorCount'],0)
    probe = value.get('ipcProbe')
    if (isinstance(probe, dict) and type(probe.get('ipcWritable')) in (bool,type(None)) and
            type(probe.get('ipcConfigurable')) in (bool,type(None)) and
            type(probe.get('bridgeMissing')) is bool and type(probe.get('bridgeReverted')) is bool):
        safe['ipcProbe'] = {key: probe[key] for key in
            ('bridgeMissing','bridgeReverted','ipcWritable','ipcConfigurable')}
    return safe


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

    def click(self, selector, trace=None):
        # scrollIntoView is layout-only. Actual activation goes through CDP input.
        expression = '''(()=>{const e=document.querySelector(%s); if(!e || e.matches(':disabled') || e.hidden) return null;
          e.scrollIntoView({block:'center',inline:'center'}); const r=e.getBoundingClientRect();
          const x=r.left+r.width/2,y=r.top+r.height/2;
          return r.width>0 && r.height>0 && x>=0 && y>=0 && x<innerWidth && y<innerHeight &&
                 e.contains(document.elementFromPoint(x,y)) ? {x,y}:null})()''' % json.dumps(selector)
        point = wait_for(lambda: self.evaluate(expression), 'android_control_missing_'+selector.lstrip('#').replace(' ','_'))
        # Real-device evidence (run 42617523564): between the hit-check eval and
        # the CDP dispatch the layout can still move — xterm focus and IME
        # insets shift the keys panel — so the stale point misses the control.
        # Gate on layout stillness: two identical reads before dispatching.
        stable_expression = '''(()=>{const e=document.querySelector(%s); if(!e) return null;
          const r=e.getBoundingClientRect(); const x=r.left+r.width/2,y=r.top+r.height/2;
          return {x:Math.round(x*4),y:Math.round(y*4),w:innerWidth,h:innerHeight,
                  hit:e.contains(document.elementFromPoint(x,y))}})()''' % json.dumps(selector)
        wait_for(lambda: (lambda a, b: a if (a and b and a['x'] == b['x'] and a['y'] == b['y']
                                            and a['w'] == b['w'] and a['h'] == b['h'] and a['hit']) else None)(
            self.evaluate(stable_expression), self.evaluate(stable_expression)),
                 'android_control_unstable_'+selector.lstrip('#').replace(' ','_'))
        point = self.evaluate(stable_expression)
        point = {'x': point['x'] / 4, 'y': point['y'] / 4}
        if trace is not None:
            # Bounded pointer evidence only: no text, no identifiers, no secrets.
            trace.append(self.evaluate('''(()=>{const e=document.querySelector(%s);const r=e?.getBoundingClientRect?.();
              const a=document.activeElement;return {selector:%s,rect:r?{x:Math.round(r.x),y:Math.round(r.y),
                w:Math.round(r.width),h:Math.round(r.height)}:null,
                viewport:{w:innerWidth,h:innerHeight},
                activeElement:a?(a.id||a.className||a.tagName):null,
                activeInsideKeys:!!(a&&document.getElementById('remote-input-keys')?.contains(a)),
                disabled:!!e?.disabled,hidden:!!e?.hidden}})()''' % (json.dumps(selector), json.dumps(selector))))
        for kind in ('mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', {'type': kind, 'x': point['x'], 'y': point['y'],
                                                 'button': 'left', 'clickCount': 1})
        # The dispatch itself can race a late layout shift: verify the control
        # was hit at the point we used, and re-verify after the event settles.
        check_expression = '''(()=>{const e=document.querySelector(%s); const r=e?.getBoundingClientRect?.();
          if(!e||!r) return null; const x=%d,y=%d;
          return r.left<=x && x<=r.right && r.top<=y && y<=r.bottom &&
                 e.contains(document.elementFromPoint(x,y))})()''' % (json.dumps(selector), point['x'], point['y'])
        wait_for(lambda: self.evaluate(check_expression), 'android_control_missed_'+selector.lstrip('#').replace(' ','_'), timeout=10)
        if trace is not None:
            trace.append(self.evaluate('''(()=>{const a=document.activeElement;return {
              activeElement:a?(a.id||a.className||a.tagName):null,
              activeInsideKeys:!!(a&&document.getElementById('remote-input-keys')?.contains(a)),
              inputStatus:(document.getElementById('remote-input-status')?.textContent||'').slice(0,80),
              hasReceipt:!!document.getElementById('remote-input-status')?.dataset.receipt}})()'''))

    def click_named(self, scope, label, code='android_blocked_card_missing'):
        """Activate a unique visible named button through actual CDP pointer input."""
        expression = r'''(()=>{const root=document.querySelector(%s);if(!root)return null;
          const buttons=[...root.querySelectorAll('button')].filter(e=>e.textContent.trim()===%s &&
            !e.matches(':disabled') && !e.closest('[hidden]') && e.getClientRects().length);
          if(buttons.length!==1)return null;const e=buttons[0];e.scrollIntoView({block:'center',inline:'center'});
          const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
          return r.width>0 && r.height>0 && x>=0 && y>=0 && x<innerWidth && y<innerHeight &&
            e.contains(document.elementFromPoint(x,y))?{x,y}:null})()''' % (json.dumps(scope),json.dumps(label))
        point=wait_for(lambda:self.evaluate(expression),code)
        for kind in ('mousePressed','mouseReleased'):
            self.call('Input.dispatchMouseEvent',{'type':kind,'x':point['x'],'y':point['y'],'button':'left','clickCount':1})

    def fill(self, selector, value):
        expression = '''(()=>{const e=document.querySelector(%s); if(!e || !e.getClientRects().length || e.matches(':disabled') || e.readOnly) return false;
          e.scrollIntoView({block:'center'}); e.focus(); e.select(); return document.activeElement===e})()''' % json.dumps(selector)
        wait_for(lambda: self.evaluate(expression), 'android_text_control_missing_'+selector.lstrip('#'))
        self.call('Input.insertText', {'text': str(value)})
        if self.read(selector, 'value') != str(value):
            raise GuiFailure('android_text_input_mismatch')

    def select_observer_canvas(self, guarded):
        """Choose on the actual select using CDP input, never assign its value."""
        if self.read('#remote-canvas', 'value') != '80x24':
            raise GuiFailure('android_canvas_default_invalid')
        if guarded:
            return
        self.click('#remote-canvas')
        for key, code, number in (('ArrowDown','ArrowDown',40),('Enter','Enter',13)):
            for kind in ('keyDown','keyUp'):
                self.call('Input.dispatchKeyEvent', {'type':kind,'key':key,'code':code,'windowsVirtualKeyCode':number})
        wait_for(lambda: self.read('#remote-canvas','value') == '120x40',
                 'android_canvas_selection_failed')

    def direct_key(self, key):
        # Dispatch a real key through the focused xterm textarea, without Enter.
        if key != 'k' or not self.evaluate("document.activeElement === document.querySelector('#remote-terminal .xterm-helper-textarea')"):
            raise GuiFailure('android_direct_focus_missing')
        for kind in ('keyDown', 'keyUp'):
            params = {'type': kind, 'key': key, 'code': 'KeyK', 'windowsVirtualKeyCode': 75}
            if kind == 'keyDown':
                params.update({'text': key, 'unmodifiedText': key})
            self.call('Input.dispatchKeyEvent', params)

    def select_font_sample(self, ident):
        """Select consecutive bundled samples with actual native select keyboard input."""
        previous = {'powerlevel10k':'glyphs','oh-my-posh':'powerlevel10k'}.get(ident)
        selector = '.terminal-font-diagnostics select[aria-label="诊断样例"]'
        if previous is None or self.read(selector, 'value') != previous:
            raise GuiFailure('android_theme_selection_invalid')
        self.click(selector)
        for key, number in (('ArrowDown',40),('Enter',13)):
            for kind in ('keyDown','keyUp'):
                self.call('Input.dispatchKeyEvent', {'type':kind,'key':key,'code':key,'windowsVirtualKeyCode':number})
        wait_for(lambda: self.read(selector,'value') == ident, 'android_theme_selection_missing')

    def select_option(self, selector, value):
        """Choose one option of a real select with CDP keyboard input, never by assignment."""
        options = wait_for(lambda: self.evaluate(
            '(()=>{const e=document.querySelector(%s);if(!e||!e.getClientRects().length)return null;'
            'return [...e.options].map(o=>o.value)})()' % json.dumps(selector)),
            'android_select_option_missing')
        if not isinstance(options, list) or value not in options:
            raise GuiFailure('android_select_option_missing')
        current = self.read(selector, 'value')
        if current not in options:
            raise GuiFailure('android_select_option_failed')
        steps = options.index(value) - options.index(current)
        if steps:
            self.click(selector)
            key = 'ArrowDown' if steps > 0 else 'ArrowUp'
            for _ in range(abs(steps)):
                for kind in ('keyDown', 'keyUp'):
                    self.call('Input.dispatchKeyEvent', {'type':kind,'key':key,'code':key,'windowsVirtualKeyCode':40})
            for kind in ('keyDown', 'keyUp'):
                self.call('Input.dispatchKeyEvent', {'type':kind,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
        wait_for(lambda: self.read(selector, 'value') == value, 'android_select_option_failed')

    def _counter_page_context(self):
        """Read-only page state so a reset WebView can be told from a busy one."""
        try:
            value = self.evaluate('(()=>{const i=window.__TAURI_INTERNALS__;'
                'const c=i&&i.__herdrInvokeCounter;'
                'const t=c&&c.tally&&typeof c.tally==="object"?Object.keys(c.tally):null;'
                'const p=i&&i.__herdrIpcProbe&&typeof i.__herdrIpcProbe==="object"?i.__herdrIpcProbe:null;'
                'return {readyState:document.readyState,internals:!!i,'
                'invokeType:i?typeof i.invoke:"missing",url:location.href,present:!!c,'
                'count:c&&typeof c.count==="number"&&isFinite(c.count)?Math.trunc(c.count):null,'
                'tallyKeys:Array.isArray(t)?t.slice(0,16):null,'
                'clickSeen:c&&typeof c.clickSeen==="number"&&isFinite(c.clickSeen)?Math.trunc(c.clickSeen):null,'
                'lastClickTarget:c&&typeof c.lastClickTarget==="string"?c.lastClickTarget:null,'
                'errorCount:c&&typeof c.errorCount==="number"&&isFinite(c.errorCount)?Math.trunc(c.errorCount):null,'
                'lastJsError:c&&typeof c.lastJsError==="string"?c.lastJsError:null,'
                'ipcProbe:p?{bridgeMissing:p.bridgeMissing===true,bridgeReverted:p.bridgeReverted===true,'
                'ipcWritable:typeof p.ipcWritable==="boolean"?p.ipcWritable:null,'
                'ipcConfigurable:typeof p.ipcConfigurable==="boolean"?p.ipcConfigurable:null}:null}})()')
        except GuiFailure:
            value = {}  # A failed probe still reports every field as unknown.
        return _public_counter_context(value) or _public_counter_context({})

    def _counter_failure(self, code):
        """Counter failures carry page context; a failed probe degrades to unknown."""
        failure = GuiFailure(code)
        failure.counter_context = self._counter_page_context()
        return failure

    def install_invoke_counter(self):
        """Count real app IPC so a local-only interaction can be proven on the device.

        Tauri 2.x defines internals.invoke/ipc/postMessage with value-only
        Object.defineProperty (non-writable, non-configurable), so assignment
        silently no-ops and can never report a working patch. The live hook on
        Android is the wry Java bridge: window.ipc is a plain window property
        and ipc-protocol.js reads it dynamically at every send, so replacing
        window.ipc with a wrapper counts every command at the native boundary.
        """
        script = ('(()=>{const i=window.__TAURI_INTERNALS__;const b=window.ipc;'
            'if(!i||typeof i.invoke!=="function")return false;'
            'const d=b?Object.getOwnPropertyDescriptor(window,"ipc"):null;'
            'if(!b||typeof b.postMessage!=="function")'
            '{i.__herdrIpcProbe={bridgeMissing:true,ipcWritable:d?d.writable:null,'
            'ipcConfigurable:d?d.configurable:null};return false;}'
            'if(window.__herdrIpcBridge){window.ipc=window.__herdrIpcBridge;'
            'return window.ipc===window.__herdrIpcBridge;}'
            'const c={count:0,tally:{},lastJsError:null,errorCount:0,clickSeen:0,lastClickTarget:null};'
            'const wrapped={postMessage:function(message){c.count+=1;let cmd=null;'
            'try{cmd=typeof message==="string"?JSON.parse(message).cmd:null;}catch(e){}'
            'if(typeof cmd==="string"&&Object.keys(c.tally).length<64)c.tally[cmd]=(c.tally[cmd]||0)+1;'
            'return b.postMessage(message);}};'
            'i.__herdrInvokeCounter=c;'
            'window.__herdrIpcOriginal=b;window.__herdrIpcBridge=wrapped;'
            'try{window.ipc=wrapped;}catch(e){}'
            'if(window.ipc!==wrapped){i.__herdrIpcProbe={bridgeReverted:true,'
            'ipcWritable:d?d.writable:null,ipcConfigurable:d?d.configurable:null};return false;}'
            'delete i.__herdrIpcProbe;'
            'if(!window.__herdrClickHook){window.__herdrClickHook=e=>{'
            'const t=window.__TAURI_INTERNALS__,k=t&&t.__herdrInvokeCounter;'
            'if(k){k.clickSeen+=1;k.lastClickTarget=(e&&e.target&&e.target.id)||"?";}};'
            'document.addEventListener("click",window.__herdrClickHook,true);}'
            'if(!window.__herdrErrorHook){window.__herdrErrorHook=true;'
            'const note=v=>{const t=window.__TAURI_INTERNALS__;const k=t&&t.__herdrInvokeCounter;'
            'if(k){k.errorCount+=1;k.lastJsError=String(v).slice(0,200);}};'
            'window.addEventListener("error",e=>note("sync:"+((e&&e.message)||"error")));'
            'window.addEventListener("unhandledrejection",'
            'e=>note("async:"+((e&&e.reason&&(e.reason.message||e.reason))||"rejected")));}'
            'return window.ipc===wrapped;})()')
        def installed():
            # A briefly reset JS context returns false or throws; both self-heal here.
            # A reverted bridge is re-asserted by the install-once guard above.
            try:
                return self.evaluate(script) is True
            except GuiFailure:
                return False
        try:
            wait_for(installed, 'android_board_search_counter_install_failed', timeout=15)
        except GuiFailure:
            raise self._counter_failure('android_board_search_counter_install_failed') from None

    def invoke_counter(self):
        value = self.evaluate(
            '(()=>{const i=window.__TAURI_INTERNALS__;const c=i&&i.__herdrInvokeCounter;'
            'return c?{count:c.count,tally:c.tally}:null})()')
        if (not isinstance(value, dict) or type(value.get('count')) is not int or value['count'] < 0 or
                not isinstance(value.get('tally'), dict) or len(value['tally']) > 64 or
                any(not isinstance(name, str) or type(number) is not int or number < 0
                    for name, number in value['tally'].items())):
            raise self._counter_failure('android_board_search_counter_read_invalid')
        return value

    def remove_invoke_counter(self):
        self.evaluate(
            '(()=>{if(window.__herdrClickHook){document.removeEventListener("click",window.__herdrClickHook,true);'
            'delete window.__herdrClickHook;}'
            'const original=window.__herdrIpcOriginal;if(!original)return false;'
            'window.ipc=original;delete window.__herdrIpcOriginal;delete window.__herdrIpcBridge;'
            'const i=window.__TAURI_INTERNALS__;if(i)delete i.__herdrInvokeCounter;'
            'return window.ipc===original;})()')

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


def primary_pane_selector(pane_id):
    if not isinstance(pane_id,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',pane_id):
        raise GuiFailure('android_unexpected_dashboard_pane')
    return '#remote-panes button[data-pane-id="'+pane_id+'"]'


def _blocked_card(browser,targets):
    bindings=[row['paneId']+'/'+row['terminalId'] for row in targets]
    expression=r'''(()=>{const home=document.querySelector('#host-home');if(!home || home.hidden)return null;
      const expected=%s,cards=[...home.querySelectorAll('#host-list > .saved-host-card')];
      const matches=cards.map((card,index)=>{const rows=[...card.querySelectorAll('.blocked-target-list button[data-blocked-target]')];
        const ids=rows.map(row=>row.dataset.blockedTarget);
        if(rows.length!==2 || new Set(ids).size!==2 || !expected.every(id=>ids.includes(id)))return null;
        return {selector:'#host-list > .saved-host-card:nth-child('+(index+1)+')',listedRows:rows.length,
          sameLabel:rows.every(row=>row.textContent.trim().split(' · ').slice(3).join(' · ')==='pocket-blocked')};
      }).filter(Boolean);return matches.length===1?matches[0]:null})()''' % json.dumps(bindings)
    value=wait_for(lambda:browser.evaluate(expression),'android_blocked_card_missing')
    if (not isinstance(value,dict) or set(value)!={'selector','listedRows','sameLabel'} or
            not isinstance(value['selector'],str) or not re.fullmatch(r'#host-list > \.saved-host-card:nth-child\([1-9][0-9]{0,2}\)',value['selector']) or
            type(value['listedRows']) is not int or value['listedRows']!=2):
        raise GuiFailure('android_blocked_target_evidence_invalid')
    if value['sameLabel'] is not True:
        raise GuiFailure('android_blocked_same_label_missing')
    return value


def exercise_blocked_target(browser,approval,config):
    """Observe synthetic B from the real stale host card, then restore pairing UI."""
    try:
        targets=checked_targets(approval.blocked_targets)
        if checked_targets(approval.verify_blocked_targets())!=targets:
            raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise GuiFailure('android_blocked_target_evidence_invalid') from None
    target=targets[1]
    browser.click('#host-return-home')
    wait_for(lambda:browser.evaluate("!document.querySelector('#host-home').hidden"),'android_home_not_visible')
    card=_blocked_card(browser,targets)
    browser.click(card['selector']+' .blocked-target-list button[data-blocked-target="'+target['paneId']+'/'+target['terminalId']+'"]')
    review=r'''(()=>{const view=document.querySelector('#view-content');if(!view || view.closest('[hidden]'))return false;
      const checks=[...view.querySelectorAll('input[type=checkbox]')],buttons=[...view.querySelectorAll('button')].filter(e=>e.textContent.trim()==='连接');
      return checks.length===1 && !checks[0].checked && buttons.length===1 && buttons[0].disabled &&
        !view.querySelector('.terminal-host .xterm-screen') && view.textContent.includes(%s) && view.textContent.includes(%s)})()''' % (json.dumps(target['paneId']),json.dumps(target['terminalId']))
    wait_for(lambda:browser.evaluate(review) is True,'android_blocked_review_required')
    browser.click('#view-content input[type=checkbox]')
    wait_for(lambda:browser.evaluate("document.querySelector('#view-content input[type=checkbox]')?.checked===true"),'android_blocked_review_required')
    browser.click_named('#view-content','连接')
    measurement=r'''(()=>{const view=document.querySelector('#view-content'),term=view?.querySelector('.terminal-host');
      if(!view || !term || term.closest('[hidden]') || !term.getClientRects().length)return null;
      const title=[...view.children].find(e=>e.tagName==='P')?.textContent.split(' · ') || [];
      const paneId=title.at(-2),terminalId=title.at(-1),expected=%s;
      const rows=[...term.querySelectorAll('.xterm-rows > div')].map(e=>e.textContent.replace(/\u00a0/g,' ').trim());
      const area=term.querySelector('.xterm-helper-textarea'),mode=view.querySelector('p[aria-live=polite]');
      const verified=view.querySelector('[data-connection-stage=terminal]')?.dataset.stageState==='verified';
      const observing=mode?.textContent==='观察模式；输入已关闭。' && !!area && area.readOnly &&
        area.getAttribute('inputmode')==='none' && document.activeElement!==area;
      const markerMatched=rows.some(line=>/^POCKET-BLOCKED-B(?: frame [0-9]+)?$/.test(line));
      const otherMarkerAbsent=rows.length>0 && rows.every(line=>!line.includes('POCKET-BLOCKED-A'));
      if(paneId!==expected.paneId || terminalId!==expected.terminalId || !verified || !observing || !markerMatched || !otherMarkerAbsent)return null;
      return {paneId,terminalId,observing,markerMatched,otherMarkerAbsent}})()''' % json.dumps(target)
    raw=wait_for(lambda:browser.evaluate(measurement),'android_blocked_render_missing',timeout=60)
    if not isinstance(raw,dict):
        raise GuiFailure('android_blocked_target_evidence_invalid')
    raw={**raw,'listedRows':card['listedRows'],'reviewRequired':True}
    try:
        if checked_targets(approval.verify_blocked_targets())!=targets:
            raise ValueError()
        evidence=checked_receipt(raw,targets)
    except (ValueError,TypeError):
        raise GuiFailure('android_blocked_target_evidence_invalid') from None
    approval.verify_ssh(b'')
    browser.click_named('#view-content','关闭此标签')
    wait_for(lambda:browser.evaluate("document.querySelector('#tab-workspace').hidden"),'android_blocked_original_form_missing')
    browser.click('#host-return-home')
    wait_for(lambda:browser.evaluate("!document.querySelector('#host-home').hidden"),'android_home_not_visible')
    _restore_paired_form(browser,config,targets)
    return evidence


def _restore_paired_form(browser,config,targets):
    """Restore the paired identity form that the revocation review needs."""
    card=_blocked_card(browser,targets)
    browser.click_named(card['selector']+' .saved-host-actions','打开')
    wait_for(lambda:browser.evaluate("!document.querySelector('#host-restore-panel').hidden"),'android_blocked_original_form_missing')
    for field,key in [('host','host'),('port','port'),('user','username'),('session','session'),('herdr','herdrPath'),('socket','socketPath'),('pin','expectedHostKey')]:
        if browser.read('#remote-'+field,'value')!=str(config[key]):
            raise GuiFailure('android_blocked_original_form_missing')
    browser.click('#host-restore-review')
    browser.click('#host-restore')
    wait_for(lambda:browser.evaluate("document.querySelector('#host-restore-panel').hidden"),'android_blocked_original_form_missing')
    if (not browser.read('#pair-request','value') or
            browser.evaluate("document.querySelector('#remote-review').checked || !document.querySelector('#remote-connect').disabled") is not False):
        raise GuiFailure('android_blocked_original_form_missing')


BOARD_STATUS_PATTERN = re.compile(r'显示 (\d+) / (\d+) 台主机$')
BOARD_CURRENT_PATTERN = re.compile(r'^当前待处理（(\d+)）$')
BOARD_HISTORY_PATTERN = re.compile(r'^上次受阻，待核查（(\d+)）$')
BOARD_EMPTY_MARK = '没有匹配的主机'
BOARD_SNAPSHOT_KEYS = {'totalCards','visibleCards','query','state','clearHidden','resetHidden',
    'statusHidden','statusText','currentLabel','historyLabel','sessionVisible','blockedRows'}
BOARD_SNAPSHOT = r'''(()=>{const fragment=%s;
  const list=document.querySelector('#host-list');
  const cards=list?[...list.children].filter(c=>c.classList.contains('saved-host-card')):[];
  const visible=cards.filter(c=>!c.hidden);
  const value=id=>{const e=document.querySelector(id);return e?e.value:null;};
  const hidden=id=>{const e=document.querySelector(id);return !e||e.hidden===true;};
  const text=id=>{const e=document.querySelector(id);return e?e.textContent.trim():null;};
  return {totalCards:cards.length,visibleCards:visible.length,
    query:value('#host-query'),state:value('#host-attention'),
    clearHidden:hidden('#host-query-clear'),resetHidden:hidden('#host-filter-reset'),
    statusHidden:hidden('#host-filter-status'),statusText:text('#host-filter-status'),
    currentLabel:text('#host-attention-current'),historyLabel:text('#host-attention-history'),
    sessionVisible:visible.some(c=>c.textContent.includes(fragment)),
    blockedRows:visible.map(c=>[...c.querySelectorAll('.blocked-target-list button[data-blocked-target]')]
      .map(b=>b.dataset.blockedTarget))};})()'''


def _board_snapshot(browser, fragment):
    value = browser.evaluate(BOARD_SNAPSHOT % json.dumps(fragment))
    if not isinstance(value, dict) or set(value) != BOARD_SNAPSHOT_KEYS:
        raise GuiFailure('android_board_search_count_mismatch')
    if (type(value['totalCards']) is not int or value['totalCards'] < 0 or
            type(value['visibleCards']) is not int or value['visibleCards'] < 0 or
            value['visibleCards'] > value['totalCards'] or
            not isinstance(value['query'], str) or not isinstance(value['state'], str) or
            type(value['clearHidden']) is not bool or type(value['resetHidden']) is not bool or
            type(value['statusHidden']) is not bool or type(value['sessionVisible']) is not bool or
            not isinstance(value['statusText'], str) or not isinstance(value['currentLabel'], str) or
            not isinstance(value['historyLabel'], str) or
            not isinstance(value['blockedRows'], list) or
            any(not isinstance(ids, list) or any(not isinstance(item, str) for item in ids)
                for ids in value['blockedRows'])):
        raise GuiFailure('android_board_search_count_mismatch')
    return value


def _board_counts(snapshot):
    """Read the dual-condition counter and both task-state counters from the board."""
    status = BOARD_STATUS_PATTERN.search(snapshot['statusText'])
    current = BOARD_CURRENT_PATTERN.match(snapshot['currentLabel'])
    history = BOARD_HISTORY_PATTERN.match(snapshot['historyLabel'])
    if not status or not current or not history:
        raise GuiFailure('android_board_search_count_mismatch')
    return int(status.group(1)), int(status.group(2)), int(current.group(1)), int(history.group(1))


def _counter_probe(browser):
    """Read a counter, failing fast when the page or CDP transport is unavailable."""
    try:
        return browser.invoke_counter()
    except GuiFailure as error:
        if str(error) in ('android_board_search_counter_read_invalid',
                          'android_cdp_transport_failed','android_cdp_command_failed'):
            raise
        return None


def _counter_count_reached(browser, minimum):
    """Return whether the counter has reached the requested minimum."""
    value = _counter_probe(browser)
    return value is not None and value['count'] >= minimum


def _counter_board_command_seen(browser):
    value = _counter_probe(browser)
    return value is not None and any(value['tally'].get(name,0) > 0 for name in ('host_list','network_list'))


def _settled_invoke_count(browser):
    """Wait until the app stops issuing IPC so a local-only interaction can be measured."""
    previous = -1
    stable = 0
    for _ in range(120):
        current = browser.invoke_counter()['count']
        if current == previous:
            stable += 1
            if stable >= 3:
                return current
        else:
            stable = 0
            previous = current
        time.sleep(0.25)
    raise browser._counter_failure('android_board_search_counter_unsettle_timeout')


def exercise_board_search(browser, approval, config):
    """Search the saved board locally: text, task state, dual counts, history and reset."""
    before_click, after_click = {}, {}
    install_attempted = False
    final_context = None
    def remove_counter():
        try:
            browser.remove_invoke_counter()
        except GuiFailure:
            pass  # Never let cleanup hide the diagnostic that got us here.
    try:
        try:
            targets = checked_targets(approval.blocked_targets)
        except (ValueError, TypeError, AttributeError):
            raise GuiFailure('android_blocked_target_evidence_invalid') from None
        fragment = str(config['session'])[:8]
        install_attempted = True
        browser.install_invoke_counter()
        before_click = browser._counter_page_context()
        browser.click('#host-return-home')
        after_click = browser._counter_page_context()
        wait_for(lambda: browser.evaluate("!document.querySelector('#host-home').hidden"), 'android_home_not_visible')
        # The board refresh must issue a real host or network list request.
        wait_for(lambda: _counter_board_command_seen(browser), 'android_board_search_counter_no_ipc', timeout=15)
        baseline = _settled_invoke_count(browser)
        expected = {row['paneId']+'/'+row['terminalId'] for row in targets}

        # A session fragment finds the saved host and still lists both blocked panes.
        browser.fill('#host-query', fragment)
        snapshot = _board_snapshot(browser, fragment)
        matched, total, current_count, history_count = _board_counts(snapshot)
        if (snapshot['query'] != fragment or snapshot['clearHidden'] is not False or
                snapshot['statusHidden'] is not False or snapshot['sessionVisible'] is not True or
                matched != snapshot['visibleCards'] or total != snapshot['totalCards'] or matched < 1):
            raise GuiFailure('android_board_search_count_mismatch')
        rows = [ids for ids in snapshot['blockedRows'] if ids]
        if (len(rows) != 1 or len(rows[0]) != 2 or len(set(rows[0])) != 2 or set(rows[0]) != expected):
            raise GuiFailure('android_board_search_history_missing')
        text_matched = matched

        # The stale report belongs to the history bucket and not to the current one.
        browser.select_option('#host-attention', 'current')
        snapshot = _board_snapshot(browser, fragment)
        matched, total, current_count, history_count = _board_counts(snapshot)
        if (snapshot['state'] != 'current' or matched != 0 or snapshot['visibleCards'] != 0 or
                current_count != 0 or history_count < 1):
            raise GuiFailure('android_board_search_state_invalid')

        # Both conditions together select that blocked host again.
        browser.select_option('#host-attention', 'history')
        snapshot = _board_snapshot(browser, fragment)
        matched, total, current_count, history_count = _board_counts(snapshot)
        if (snapshot['state'] != 'history' or matched != snapshot['visibleCards'] or
                total != snapshot['totalCards'] or matched < 1 or matched > history_count):
            raise GuiFailure('android_board_search_state_invalid')
        dual_count = matched

        # Clearing the text keeps the task state.
        browser.click('#host-query-clear')
        snapshot = _board_snapshot(browser, fragment)
        matched, total, current_count, history_count = _board_counts(snapshot)
        if (snapshot['query'] != '' or snapshot['state'] != 'history' or snapshot['clearHidden'] is not True or
                matched != snapshot['visibleCards'] or matched != history_count):
            raise GuiFailure('android_board_search_clear_missing')

        # An empty result offers the reset that restores the original list.
        browser.fill('#host-query', 'no-such-host-'+fragment)
        snapshot = _board_snapshot(browser, fragment)
        matched, total, current_count, history_count = _board_counts(snapshot)
        if (snapshot['visibleCards'] != 0 or matched != 0 or total != snapshot['totalCards'] or
                snapshot['resetHidden'] is not False or BOARD_EMPTY_MARK not in snapshot['statusText']):
            raise GuiFailure('android_board_search_reset_missing')
        browser.click('#host-filter-reset')
        snapshot = _board_snapshot(browser, fragment)
        if (snapshot['state'] != 'all' or snapshot['query'] != '' or snapshot['statusHidden'] is not True or
                snapshot['statusText'] != '' or snapshot['visibleCards'] != snapshot['totalCards']):
            raise GuiFailure('android_board_search_reset_missing')

        # Searching and filtering stay on the device: no native call is added.
        added = browser.invoke_counter()['count'] - baseline
        if added != 0:
            raise GuiFailure('android_board_search_native_call')
        final_context = browser._counter_page_context()
        remove_counter()
        install_attempted = False
        _restore_paired_form(browser, config, targets)
        return {'textMatched':text_matched, 'dualConditionCount':dual_count, 'totalHosts':total,
            'currentCount':current_count, 'historyCount':history_count, 'historyRows':2,
            'historyDistinguished':True, 'clearedKeptState':True, 'resetRestoredList':True,
            'nativeCallsAdded':added}
    except GuiFailure as error:
        if not isinstance(getattr(error,'counter_context',None),dict):
            error.counter_context = (final_context if final_context is not None else
                                     browser._counter_failure(str(error)).counter_context)
        error.counter_click_context = {'before':before_click,'after':after_click}
        try:
            status = browser.read('#host-home-status')
            if isinstance(status,str):error.home_status = ' '.join(status.split())[:120]
        except GuiFailure:
            pass  # Preserve the original failure if the page is no longer readable.
        raise
    finally:
        if install_attempted:
            remove_counter()


DEVICE_REVIEW_SELECTOR = 'dialog[aria-labelledby="zerotier-device-title"]'
DEVICE_ACTION_LABELS = frozenset({'创建共享设备','删除共享设备','恢复待定创建','放弃待定创建',
    '恢复待定删除','确认操作','取消操作'})
DEVICE_WRITE_COMMANDS = frozenset({'zerotier_device_write','network_identity_write','network_save',
    'network_delete','network_bind','network_node_start','network_node_stop','network_node_login',
    'network_node_open_auth'})
DEVICE_REVIEW_SNAPSHOT = r'''(()=>{const title=document.querySelector('dialog[open] #zerotier-device-title');
  if(!title)return null;
  const dialog=title.closest('dialog');
  const status=dialog.querySelector('p[role=status]');
  const lines=[...dialog.querySelectorAll('p')].map(p=>p.textContent.trim());
  return {title:title.textContent.trim(),status:status?status.textContent.trim():null,
    hasScope:lines.some(t=>t.startsWith('受影响网络：'))&&lines.some(t=>t.startsWith('受影响主机：')),
    pending:lines.some(t=>t.startsWith('待定创建：')||t.startsWith('待定删除：')),
    buttons:[...dialog.querySelectorAll('button')].map(b=>({text:b.textContent.trim(),disabled:b.disabled}))};})()'''


def _device_review(browser):
    value = browser.evaluate(DEVICE_REVIEW_SNAPSHOT)
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'title','status','hasScope','pending','buttons'}:
        raise GuiFailure('android_device_impact_status_invalid')
    if (not isinstance(value['title'], str) or not isinstance(value['status'], str) or
            type(value['hasScope']) is not bool or type(value['pending']) is not bool or
            not isinstance(value['buttons'], list) or
            any(not isinstance(item, dict) or set(item) != {'text','disabled'} or
                not isinstance(item['text'], str) or type(item['disabled']) is not bool
                for item in value['buttons'])):
        raise GuiFailure('android_device_impact_status_invalid')
    return value


def _device_class(snapshot):
    """Classify the shared device display path the unbound Android build can reach."""
    status = snapshot['status']
    if '设备状态未知' in status:
        return 'unknown'
    if '受影响范围未知' in status:
        return 'catalog_blocked'
    if snapshot['pending']:
        return 'pending'
    return None


def _settled_device_review(browser):
    snapshot = _device_review(browser)
    return snapshot if snapshot and _device_class(snapshot) else None


def exercise_device_impact_review(browser):
    """Review the shared device impact without creating identities or joining a network."""
    browser.install_invoke_counter()
    try:
        browser.click('#host-return-home')
        wait_for(lambda: browser.evaluate("!document.querySelector('#host-home').hidden"), 'android_home_not_visible')
        browser.click('#network-open')
        wait_for(lambda: browser.evaluate(
            "(()=>{const p=document.querySelector('#network-panel');return !!p&&!p.hidden})()"),
            'android_device_impact_entry_missing')
        browser.click_named('#network-panel','审查 ZeroTier 共享设备','android_device_impact_entry_missing')
        snapshot = wait_for(lambda: _settled_device_review(browser), 'android_device_impact_status_invalid', timeout=60)
        state = _device_class(snapshot)
        if state not in ('unknown','catalog_blocked','pending'):
            raise GuiFailure('android_device_impact_status_invalid')
        if snapshot['title'] != 'ZeroTier 共享设备':
            raise GuiFailure('android_device_impact_status_invalid')
        actions = [item for item in snapshot['buttons'] if item['text'] in DEVICE_ACTION_LABELS]
        if state in ('unknown','catalog_blocked'):
            # Without a readable device state no identity operation may be offered.
            if actions or snapshot['hasScope'] is not (state == 'unknown'):
                raise GuiFailure('android_device_impact_action_enabled')
        for label in ('刷新状态','关闭'):
            if not any(item['text'] == label and item['disabled'] is False for item in snapshot['buttons']):
                raise GuiFailure('android_device_impact_status_invalid')

        # A second read must issue fresh catalog and device reads.
        before = browser.invoke_counter()['count']
        browser.click_named(DEVICE_REVIEW_SELECTOR,'刷新状态','android_device_impact_reread_invalid')
        wait_for(lambda: _counter_count_reached(browser, before + 3), 'android_device_impact_reread_invalid', timeout=30)
        reread_calls = browser.invoke_counter()['count'] - before
        reread = wait_for(lambda: _settled_device_review(browser), 'android_device_impact_reread_invalid', timeout=60)
        if _device_class(reread) != state:
            raise GuiFailure('android_device_impact_reread_invalid')

        # The entry stays available after the dialog returns.
        browser.click_named(DEVICE_REVIEW_SELECTOR,'关闭','android_device_impact_entry_lost')
        wait_for(lambda: browser.evaluate("!document.querySelector(%s)" % json.dumps(DEVICE_REVIEW_SELECTOR)),
                 'android_device_impact_entry_lost')
        if browser.evaluate("(()=>{const p=document.querySelector('#network-panel');if(!p||p.hidden)return false;"
                             "return [...p.querySelectorAll('button')].some(b=>b.textContent.trim()==='审查 ZeroTier 共享设备'&&!b.disabled)})()") is not True:
            raise GuiFailure('android_device_impact_entry_lost')
        browser.click_named('#network-panel','审查 ZeroTier 共享设备','android_device_impact_entry_lost')
        again = wait_for(lambda: _settled_device_review(browser), 'android_device_impact_entry_lost', timeout=60)
        if _device_class(again) != state:
            raise GuiFailure('android_device_impact_entry_lost')
        browser.click_named(DEVICE_REVIEW_SELECTOR,'关闭','android_device_impact_entry_lost')
        wait_for(lambda: browser.evaluate("!document.querySelector(%s)" % json.dumps(DEVICE_REVIEW_SELECTOR)),
                 'android_device_impact_entry_lost')

        # No identity or network write may be issued by this review.
        writes = sum(number for name, number in browser.invoke_counter()['tally'].items()
                     if name in DEVICE_WRITE_COMMANDS)
        if writes:
            raise GuiFailure('android_device_impact_write_invoked')
    finally:
        browser.remove_invoke_counter()
    return {'statusClass':state, 'scopeListed':bool(snapshot['hasScope']), 'deviceActions':len(actions),
        'rereadCalls':reread_calls, 'reentered':True, 'writeCalls':writes}


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
    selector = primary_pane_selector(pane_id)
    button = wait_for(lambda: browser.evaluate(
        'document.querySelector('+json.dumps(selector)+')?.firstChild?.textContent || null'),
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


# Inspect only the known synthetic marker; neither marker text nor terminal contents
# enter evidence. Geometry is computed in the page and only booleans leave it.
CANVAS_MARKER_CHECK = r'''(()=>{
  const c=document.querySelector('#remote-captured'),v=document.querySelector('#remote-terminal')?.parentElement;
  const screen=document.querySelector('#remote-terminal .xterm-screen');
  const rows=screen?.querySelector('.xterm-rows')?.children;
  if(c?.dataset.state!=='active'||c.dataset.cols!=='120'||c.dataset.rows!=='40'||!v||!screen||!rows||rows.length!==40)return null;
  const row=rows[31],walker=document.createTreeWalker(row,NodeFilter.SHOW_TEXT);
  let node,found=null,index=-1;
  while((node=walker.nextNode())) {const i=node.data.indexOf('HPWIDE');if(i>=0){found=node;index=i;break;}}
  if(!found)return null;
  const range=document.createRange();range.setStart(found,index);range.setEnd(found,index+6);
  const marker=range.getBoundingClientRect(), grid=screen.getBoundingClientRect(), viewport=v.getBoundingClientRect();
  const cell=grid.width/120;
  const correctColumn=cell>0 && Math.abs((marker.left-grid.left)/cell-91)<0.2;
  const visible=marker.width>0 && marker.height>0 && marker.left>=Math.max(viewport.left,0) &&
    marker.right<=Math.min(viewport.right,innerWidth) && marker.top>=Math.max(viewport.top,0) &&
    marker.bottom<=Math.min(viewport.bottom,innerHeight);
  return {geometry:true,correctColumn,visible};
})()'''


def exercise_observer_canvas(browser):
    before = browser.evaluate("""(()=>{const v=document.querySelector('#remote-terminal')?.parentElement;
      if(!v)return null;v.scrollIntoView({block:'center'});return {left:v.scrollLeft,top:v.scrollTop};})()""")
    if (not isinstance(before, dict) or any(type(before.get(k)) not in (int,float) or not math.isfinite(before[k]) or before[k]<0 for k in ('left','top'))):
        raise GuiFailure('android_canvas_viewport_missing')
    geometry = wait_for(lambda: browser.evaluate(CANVAS_MARKER_CHECK), 'android_canvas_marker_missing', timeout=60)
    if geometry.get('geometry') is not True or geometry.get('correctColumn') is not True:
        raise GuiFailure('android_canvas_geometry_invalid')
    try:
        # This changes only the local scroll container; no terminal or network command.
        scrolled=browser.evaluate("""(()=>{const v=document.querySelector('#remote-terminal')?.parentElement;
          if(!v)return false;v.scrollLeft=v.scrollWidth;v.scrollTop=v.scrollHeight;return true;})()""")
        if scrolled is not True:raise GuiFailure('android_canvas_scroll_failed')
        def marker_visible():
            state=browser.evaluate(CANVAS_MARKER_CHECK)
            return isinstance(state,dict) and all(state.get(key) is True for key in ('geometry','correctColumn','visible'))
        visible=wait_for(marker_visible, 'android_canvas_marker_not_visible')
    finally:
        restored=browser.evaluate("""(()=>{const v=document.querySelector('#remote-terminal')?.parentElement;
          if(!v)return false;v.scrollLeft=%s;v.scrollTop=%s;
          return Math.abs(v.scrollLeft-%s)<1 && Math.abs(v.scrollTop-%s)<1;})()""" %
          (before['left'],before['top'],before['left'],before['top']))
    if restored is not True:raise GuiFailure('android_canvas_viewport_restore_failed')
    return {'geometryVerified':True,'markerVisible':visible is True,'viewportRestored':True}


def theme_prompt_measurement(browser, ident):
    if ident not in ('powerlevel10k','oh-my-posh'):
        raise GuiFailure('android_theme_selection_invalid')
    probe = Path(__file__).with_name('theme-prompt-measurement.js').read_text(encoding='utf-8')
    expression = f'({probe})({json.dumps(ident)})'
    value = wait_for(lambda: browser.evaluate(expression), 'android_theme_measurement_missing')
    expected = theme_prompt_expectations()[ident]
    if (not isinstance(value, dict) or set(value) != set(expected) or
            any(type(value[key]) is not int or value[key] != number for key, number in expected.items())):
        raise GuiFailure('android_theme_measurement_invalid')
    return value.copy()


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
    theme_cursors = {}
    for ident in ('powerlevel10k','oh-my-posh'):
        browser.select_font_sample(ident)
        theme_cursors[ident] = theme_prompt_measurement(browser, ident)
    try:
        theme_cursors = safe_theme_prompt_cursors(theme_cursors)
    except DeviceFailure:
        raise GuiFailure('android_theme_measurement_invalid') from None
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
    return {'geometry': geometry, 'localThemePromptCursors': theme_cursors, 'inputLocked': True, 'safeFocus': True,
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


# Only fixed fixture markers are inspected; terminal contents never leave CDP.
TUI_MARKERS = {
    'initial': ('Pocket TUI', 'F1 Help   F5 Refresh   F10 Finish', '> Build'),
    'select-next': ('Pocket TUI', '> Review', 'Focus: list'),
    'focus-detail': ('Pocket TUI', '> Review', 'Focus: detail', 'Detail: xy'),
    'erase-character': ('Pocket TUI', '> Review', 'Focus: detail', 'Detail: x'),
    'focus-list': ('Pocket TUI', '> Review', 'Focus: list', 'Detail: x'),
    'insert-row': ('Pocket TUI', '> New', 'Focus: list', 'Detail: x'),
    'delete-row': ('Pocket TUI', '> Review', 'Focus: list', 'Detail: x'),
    'open-help': ('Pocket TUI Help', 'F1 Return to list'),
    'close-help': ('Pocket TUI', '> Review', 'Refreshes: 0'),
    'refresh': ('Pocket TUI', '> Review', 'Refreshes: 1'),
}

def tui_screen_matches(browser, marker):
    expected = TUI_MARKERS[marker]
    expression = r"""(()=>{const c=document.querySelector('#remote-captured');
      const terminal=document.querySelector('#remote-terminal');
      if(c?.dataset.state!=='active'||!terminal)return false;
      terminal.scrollIntoView({block:'center',inline:'nearest'});
      const rows=terminal.querySelectorAll('.xterm-rows > div');
      if(!rows.length)return false;
      const lines=[...rows].map(row=>row.textContent.replaceAll('\u00a0',' ').trimEnd());
      return %s.every(marker=>lines.includes(marker));})()""" % json.dumps(expected)
    return browser.evaluate(expression) is True


def exercise_tui(browser, approval, pane, terminal, previous_receipt, previous_request_ids, progress=None):
    """Drive only the reviewed target with real auxiliary-button clicks."""
    expected_target = f'目标：{pane} · {terminal}'
    if browser.read('#remote-input-target') != expected_target:
        raise GuiFailure('android_tui_target_mismatch')
    browser.click('#remote-input-direct')
    wait_for(lambda: '逐键输入已启用' in (browser.read('#remote-input-status') or ''),
             'android_tui_direct_mode_missing')
    def frame_counts():
        value = browser.evaluate("""(()=>{const c=document.querySelector('#remote-captured');
          return c?.dataset.state==='active' ? [Number(c.dataset.fullFrames || 0),
            Number(c.dataset.deltaFrames || 0)] : null})()""")
        if (not isinstance(value, list) or len(value) != 2 or
                any(type(item) is not int or item < 0 for item in value)):
            raise GuiFailure('android_tui_frame_state_invalid')
        return value

    before_full, _ = frame_counts()
    approval.start_tui(terminal_id=terminal)
    wait_for(lambda: frame_counts()[0] > before_full and tui_screen_matches(browser, 'initial'),
             'android_tui_initial_full_missing', timeout=60)
    browser.click('#remote-input-keys [aria-controls="remote-more-keys"]')
    if browser.evaluate("document.querySelector('#remote-more-keys')?.hidden === false") is not True:
        raise GuiFailure('android_tui_more_keys_missing')
    seen = set(previous_request_ids)
    raw = previous_receipt
    checks = ['initial']
    receipts = []
    for key, length, checkpoint in STEPS:
        if (browser.read('#remote-input-target') != expected_target or
                browser.evaluate("document.querySelector('#remote-captured')?.dataset.state === 'active'") is not True):
            raise GuiFailure('android_tui_target_mismatch')
        before = sum(frame_counts())
        trace = []
        browser.click(f'#remote-input-keys [data-remote-key="{key}"]', trace=trace)
        if progress is not None:
            # Only the latest bounded pointer evidence survives; the report
            # budget stays small and no terminal text ever enters it.
            progress.data['tuiPointerTrace'] = trace[-2:]
            progress.publish()
        raw, receipt = browser.receipt(raw, pane, length)
        if receipt['terminalId'] != terminal or receipt['requestId'] in seen:
            raise GuiFailure('android_tui_receipt_mismatch')
        seen.add(receipt['requestId'])
        receipts.append(receipt)
        if progress is not None:
            progress.data['tuiReceiptsVerified'] = len(receipts)
            progress.publish()
        if checkpoint != 'finish':
            wait_for(lambda: sum(frame_counts()) > before and tui_screen_matches(browser, checkpoint),
                     'android_tui_screen_missing', timeout=30)
            checks.append(checkpoint)
    return {'receipts': receipts, 'screenChecks': checks, 'observedInitialFull': True}


def run_android(args, root, env, config, approval):
    if getattr(args, 'android_tui', False) and not getattr(args, 'input_fixture', None):
        raise GuiFailure('android_tui_requires_guarded_fixture')
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
    progress = AndroidProgress(args)
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
        progress.phase('pairing')
        browser.click('#host-open-remote')
        browser.fill('#connection-profile-raw', public_profile_json(config))
        browser.click('#connection-profile-preview')
        fingerprint = public_host_fingerprint(config['expectedHostKey'])
        wait_for(lambda: (browser.read('#connection-profile-fingerprint') or '').endswith(fingerprint),
                 'android_profile_fingerprint_missing')
        if browser.read('#remote-host', 'value') or browser.read('#pair-request', 'value'):
            raise GuiFailure('android_profile_preview_changed_target')
        browser.click('#connection-profile-apply')
        for field, key in [('host','host'), ('port','port'), ('user','username'), ('session','session'),
                           ('herdr','herdrPath'), ('socket','socketPath'), ('pin','expectedHostKey')]:
            if browser.read('#remote-'+field, 'value') != str(config[key]):
                raise GuiFailure('android_profile_target_mismatch')
        require_unreviewed = """(() => {
          const el = id => document.getElementById(id);
          return el('remote-profile-provider').value === 'direct' && el('pair-mode').checked &&
            !el('pair-target-review').checked && !el('pair-source-review').checked &&
            !el('remote-review').checked && el('pair-create').disabled &&
            el('remote-connect').disabled && !el('pair-request').value;
        })()"""
        if browser.evaluate(require_unreviewed) is not True:
            raise GuiFailure('android_profile_review_already_granted')
        progress.mark('publicProfileReviewed')
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
        # A clipboard permission failure may still use the displayed public
        # request. Preserve the rest of the device-key/SSH result in that case.
        browser.click('#pair-request-copy')
        handoff = wait_for(lambda: browser.read('#pair-handoff-status'), 'android_request_copy_not_reported')
        copy_reported = handoff.startswith('已复制')
        if copy_reported:
            progress.mark('publicRequestCopyReported')
        response = approval.approve(request.encode('utf-8'))
        browser.fill('#pair-response', response.decode('utf-8'))
        browser.click('#pair-preview')
        browser.click('#pair-source-review')
        browser.click('#pair-accept')
        wait_for(lambda: '授权响应已审查' in (browser.read('#pair-status') or ''), 'android_authorization_not_reviewed', timeout=60)
        progress.mark('authorizationReviewed'); progress.phase('canvas_selection')
        guarded=bool(getattr(args,'input_fixture',None))
        browser.select_observer_canvas(guarded);progress.mark('canvasSelectionVerified');progress.phase('dashboard')
        browser.click('#remote-review')
        browser.click('#remote-connect')
        selector = primary_pane_selector(config['paneId'])
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
        progress.phase('observe_full')
        full = wait_for(lambda: rendered('full'), 'android_full_render_ack_missing', timeout=60)
        progress.mark('fullRendered'); progress.count('fullRenderAcknowledgements',full); progress.phase('observe_delta')
        deltas = wait_for(lambda: rendered('delta'), 'android_delta_render_ack_missing', timeout=60)
        progress.mark('deltaRendered'); progress.mark('paneChosen'); progress.count('deltaRenderAcknowledgements',deltas)
        canvas_evidence={}
        if not guarded:
            progress.phase('canvas_marker')
            canvas_evidence=exercise_observer_canvas(browser)
            progress.mark('canvasGeometryVerified');progress.mark('canvasMarkerVisible');progress.mark('canvasViewportRestored')
        progress.phase('font_diagnostics')
        font_diagnostic_evidence = exercise_font_diagnostics(browser, approval, rendered)
        progress.mark('fontDiagnosticsCompleted')
        receipts = []
        paste_evidence = {}
        keyboard_evidence = []
        tui_evidence = None
        if getattr(args, 'input_fixture', None):
            wait_for(lambda: browser.evaluate("!document.querySelector('#remote-input-controls').hidden"),
                     'android_input_controls_missing', timeout=60)
            progress.phase('direct_mode')
            browser.click('#remote-input-direct')
            wait_for(lambda: '逐键输入已启用' in (browser.read('#remote-input-status') or ''),
                     'android_direct_mode_missing')
            keyboard_evidence.extend(exercise_keyboard(browser, approval, 'direct',progress=progress))
            progress.mark('directKeyboardCompleted'); progress.phase('direct_input_receipt')
            browser.direct_key('k')
            raw, first = browser.receipt(None, config['paneId'], 1)
            receipts.append(first); progress.mark('directReceiptVerified'); progress.count('inputReceiptCount',1)
            progress.phase('draft_mode')
            browser.click('#remote-input-draft-mode')
            wait_for(lambda: '草稿仅在核对' in (browser.read('#remote-input-status') or ''),
                     'android_draft_mode_missing')
            browser.fill('#remote-input-draft', 'Pocket')
            keyboard_evidence.extend(exercise_keyboard(browser, approval, 'draft',progress=progress))
            progress.mark('draftKeyboardCompleted'); progress.phase('paste_review')
            paste_evidence = exercise_local_paste(browser, approval, first, raw)
            progress.mark('pasteReviewCompleted'); progress.phase('hidden_recovery')
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
            progress.mark('draftRestored'); progress.phase('draft_input_receipt')
            browser.click('#remote-input-preview')
            if browser.read('#remote-input-preview-text') != 'Pocket测':
                raise GuiFailure('android_draft_preview_mismatch')
            browser.click('#remote-input-confirm')
            raw, second = browser.receipt(raw, config['paneId'], len('Pocket测'.encode('utf-8')))
            if second['requestId'] == first['requestId'] or second['terminalId'] != first['terminalId']:
                raise GuiFailure('android_input_receipt_target_mismatch')
            if browser.read('#remote-input-draft', 'value'):
                raise GuiFailure('android_submitted_draft_retained')
            receipts.append(second); progress.mark('draftReceiptVerified'); progress.count('inputReceiptCount',2)
            if getattr(args, 'android_tui', False):
                approval.verify_ssh('kPocket测'.encode('utf-8'))
                progress.phase('tui')
                tui_evidence = exercise_tui(browser, approval, config['paneId'], first['terminalId'],
                                            raw, [first['requestId'], second['requestId']], progress)
                progress.mark('tuiCompleted')
        else:
            if not browser.evaluate("['remote-keyboard-show','remote-keyboard-hide'].every(id=>document.getElementById(id)?.disabled===true)"):
                raise GuiFailure('android_readonly_keyboard_controls_enabled')
            progress.phase('keyboard_observe_hidden')
            sample=system_keyboard(False)
            approval.verify_ssh(b'')
            progress.ime(sample)
            keyboard_evidence.append({**sample, 'checkpoint': 'keyboard-observe-hidden'})
        # The TUI run leaves direct mode holding the terminal focus. Stopping
        # observation from that state is the device-only interaction this
        # batch still has to prove; do not paper over it with a mode switch.
        terminal_board = wait_for(board_phase, 'android_host_board_phase_during_terminal_missing')
        progress.phase('stop_observation')
        stop_trace = []
        browser.click('#remote-cancel', trace=stop_trace)
        if progress is not None:
            progress.data['stopPointerTrace'] = stop_trace[-2:]
            progress.publish()
        wait_for(lambda: '陈旧' in (browser.read('#remote-captured') or ''), 'android_stale_marker_missing')
        progress.mark('stoppedStale')
        blocked_evidence=None
        board_evidence=None
        device_evidence=None
        if not guarded:
            progress.phase('blocked_target_entry')
            blocked_evidence=exercise_blocked_target(browser,approval,config)
            progress.mark('blockedTargetVerified')
            progress.phase('board_search')
            board_evidence=exercise_board_search(browser,approval,config)
            progress.mark('boardSearchVerified')
        progress.phase('local_revocation_review')
        wait_for(lambda: browser.evaluate("document.querySelector('#remote-cancel').disabled"),
                 'android_observer_still_active')
        # The disposable host's real helper removes the key first. The GUI
        # separately reviews the returned bytes; it cannot edit the host.
        receipt = approval.revoke()
        wait_fixture_revocation_clock(browser, receipt, progress)
        browser.fill('#pair-response', receipt.decode('utf-8'))
        browser.click('#pair-preview')
        if browser.evaluate("document.querySelector('#pair-source-review').checked || !document.querySelector('#pair-accept').disabled"):
            raise GuiFailure('android_revoke_missing_independent_review')
        browser.click('#pair-source-review')
        require_revocation_review_controls(browser, progress)
        browser.click('#pair-accept')
        wait_for(lambda: '目录已确认撤销' in (browser.read('#pair-status') or ''), 'android_revoke_not_persisted')
        if browser.evaluate("!document.querySelector('#remote-connect').disabled || !document.querySelector('#pair-create').disabled"):
            raise GuiFailure('android_revoked_target_still_enabled')
        progress.mark('revocationReviewed')
        progress.phase('device_impact_review')
        device_evidence=exercise_device_impact_review(browser)
        progress.mark('deviceImpactReviewed')
        progress.success=True
        return {'paired':True, 'publicProfileReviewed':True, 'publicRequestCopyReported':copy_reported,
                'revocationReviewed':True, 'paneChosen':True, 'fullRendered':True, 'deltaRendered':True,
                'stoppedStale':True, 'fullRenderAcknowledgements':full, 'deltaRenderAcknowledgements':deltas,
                'inputQueueAccepted':bool(receipts), 'inputReceipts':receipts,
                **({'blockedTargetEvidence':blocked_evidence} if blocked_evidence is not None else {}),
                **({'boardSearchEvidence':board_evidence} if board_evidence is not None else {}),
                **({'deviceImpactEvidence':device_evidence} if device_evidence is not None else {}),
                'fontDiagnosticEvidence':font_diagnostic_evidence, 'observerCanvasEvidence':canvas_evidence,
                **({'tui': tui_evidence} if tui_evidence is not None else {}),
                **paste_evidence,
                'systemKeyboardEvidence': {'checkpoints': keyboard_evidence, 'showWithHardwareKeyboard': True,
                    'scope': 'owned API35 IME service window; CDP commits are not IME touch/composition proof'},
                'hiddenReentryFreshFull':bool(receipts),
                'initialHostBoardPhase':initial_board, 'hostBoardPhaseDuringTerminal':terminal_board,
                'keyStore':'Android API 35 emulator AndroidKeyStore-wrapped device key',
                'device':'ephemeral Android emulator', 'uiDriver':'debug WebView CDP input'}
    except GuiFailure as error:
        progress.fail(error)
        raise
    except Exception:
        progress.fail(GuiFailure('android_driver_failure'))
        raise
    finally:
        if browser:
            try:
                browser.close(); progress.data['cleanup']['browser']='confirmed'
            except Exception:
                cleanup_failed = True; progress.data['cleanup']['browser']='failed'
        if installed:
            try:
                adb('shell', 'am', 'force-stop', PACKAGE)
                adb('uninstall', PACKAGE, timeout=60); progress.data['cleanup']['application']='confirmed'
            except GuiFailure:
                cleanup_failed = True; progress.data['cleanup']['application']='failed'
        if forward:
            try:
                adb('forward', '--remove', forward); progress.data['cleanup']['forward']='confirmed'
            except GuiFailure:
                cleanup_failed = True; progress.data['cleanup']['forward']='failed'
        try:
            adb('reverse', '--remove', reverse); progress.data['cleanup']['reverse']='confirmed'
        except GuiFailure:
            cleanup_failed = True; progress.data['cleanup']['reverse']='failed'
        try:
            progress.finish(cleanup_failed)
        finally:
            progress.close()
        if cleanup_failed:
            raise GuiFailure('android_cleanup_failed')
