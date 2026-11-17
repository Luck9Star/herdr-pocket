"""No AVD or SSH: verify that the device driver cannot claim unobserved UI/peer evidence."""
import types
import hashlib
import io
import json
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import tauri_android_direct_ssh as driver


class Fixture:
    port=2222
    username='fixture'
    password='synthetic-password'
    fingerprint='SHA256:synthetic'
    marker='hp-check'
    echo_marker='POCKET-ANDROID-SSH-OK'
    def __init__(self): self.reads=0
    def snapshot(self):
        self.reads+=1
        return {**{key:True for key in ('authAccepted','ptyRequested','shellRequested','markerReceived')}, 'helperKeysExact':True, 'sessionClosed':self.reads>3}


class Browser:
    def __init__(self): self.actions=[];self.expressions=[];self.review=True;self.echo=True
    def click(self,selector): self.actions.append(('click',selector))
    def fill(self,selector,value): self.actions.append(('fill',selector,value))
    def select_option(self,selector,value): self.actions.append(('select',selector,value))
    def read(self,selector):
        return {'#ssh-fingerprint':Fixture.fingerprint,'#ssh-status':'已连接，已断开'}.get(selector,'')
    def evaluate(self,expression):
        self.expressions.append(expression)
        if "#ssh-review" in expression: return self.review
        if "#ssh-password" in expression: return ''
        if "#ssh-setup" in expression: return False
        if 'xterm-rows' in expression: return self.echo
        return True
    def call(self,name,args): self.actions.append((name,args))


class RotationFixture:
    """Synthetic A→B peer: first transport A, every later connection on the same
    listener presents B. Owns the rotation sequence judgement."""
    port=3333
    username='fixture'
    password='synthetic-password'
    fingerprint='SHA256:firstKey'
    rotated_fingerprint='SHA256:rotatedKey'
    marker='hp-check'
    echo_marker='POCKET-ANDROID-SSH-OK'
    def __init__(self,state): self.state=state;self.stages=[];self.evidence_error=None
    def wait_for_connections_closed(self,minimum,timeout=10): self.state.closed=max(self.state.closed,minimum)
    def rotation_evidence(self,stage):
        self.stages.append(stage)
        if self.evidence_error: raise ValueError(self.evidence_error)
        return {'stage':stage}
    def snapshot(self):
        return {'connections':self.state.connections,'markerReceived':self.state.marker,
                'sessionClosed':self.state.closed>=4}


class RotationState:
    def __init__(self):
        self.connections=0;self.closed=0;self.marker=False
        self.review=False;self.s10=False;self.nav_removed=False;self.live=False
        self.review_disabled=False;self.credential_disabled=False;self.submit_disabled=False
        self.password='';self.fingerprint='';self.status='';self.echo=False
        self.actions=['ssh-key-recheck','ssh-key-cancel']
        self.cancel_shows=RotationFixture.fingerprint
        self.reprobe_shows=RotationFixture.rotated_fingerprint
        self.target='目标：fixture@127.0.0.1:3333'


class RotationBrowser:
    """State machine mirroring the reviewed UI: refuses to show outcomes the
    product would not produce, so the driver cannot assert unobserved facts."""
    def __init__(self,state): self.state=state;self.actions=[];self.expressions=[]
    def click(self,selector):
        self.actions.append(('click',selector));state=self.state
        if selector=='#ssh-probe':
            state.connections+=1;state.review=False;state.password=''
            key=(RotationFixture.fingerprint if state.connections==1 else
                 getattr(state,f'reprobe_shows', 'B') if state.connections>=3 else RotationFixture.fingerprint)
            state.fingerprint=f'主机 127.0.0.1:3333 · {key}'
            state.review_disabled=state.connections<3;state.credential_disabled=state.connections<3
            state.submit_disabled=state.connections<3
        elif selector=='#ssh-review': state.review=True
        elif selector=='#ssh-form button[type=submit]':
            if state.review and state.connections==1:
                state.connections=2;state.s10=True;state.nav_removed=True;state.password=''
                state.review=False;state.review_disabled=True;state.credential_disabled=True;state.submit_disabled=True
                state.status='主机公钥与已核对的指纹不一致，连接已拒绝。'
            elif state.review and state.connections>=3 and not state.live:
                state.connections=4;state.live=True;state.password='';state.status='已连接'
        elif selector=='#ssh-key-cancel':
            state.s10=False;state.nav_removed=False;state.password=''
            state.fingerprint=f'主机 127.0.0.1:3333 · {state.cancel_shows} · 已保留的旧信任'
            state.status='已保留旧信任'
        elif selector=='#ssh-disconnect': state.live=False;state.status='已断开';state.closed=4
    def fill(self,selector,value):
        self.actions.append(('fill',selector,value))
        if selector=='#ssh-password': self.state.password=value
    def read(self,selector):
        state=self.state
        if selector=='#ssh-fingerprint': return state.fingerprint
        if selector=='#ssh-status': return state.status
        if selector=='#ssh-key-change-target': return state.target if state.s10 else ''
        if selector=='#ssh-key-change': return ('目标 127.0.0.1 旧 '+RotationFixture.fingerprint+' 新 '+RotationFixture.rotated_fingerprint) if state.s10 else ''
        return ''
    def evaluate(self,expression):
        self.expressions.append(expression);state=self.state
        negated=expression.lstrip().startswith('!')
        if "'#ssh-review').checked" in expression: return state.review
        if "'#ssh-review').disabled" in expression: return not state.review_disabled
        if "'#ssh-password').value || " in expression: return bool(state.password) or not state.credential_disabled
        if "'#ssh-password').value" in expression: return bool(state.password)
        if "'#ssh-form button[type=submit]').disabled" in expression: return not state.submit_disabled
        if "'#ssh-key-change').hidden" in expression and ('app-header' in expression):
            return (not state.s10) and (not state.nav_removed)
        if "'#ssh-key-change').hidden" in expression:
            return state.s10 if negated else (not state.s10)
        if 'app-header' in expression or 'route-tabs' in expression:
            return (not state.nav_removed) if negated else (not state.nav_removed)
        if "'#ssh-key-change button'" in expression: return state.actions if state.s10 else []
        if "'#ssh-live').hidden" in expression: return state.live if negated else (not state.live)
        if 'xterm-rows' in expression: return state.echo
        if 'xterm-helper-textarea' in expression: return True
        return True
    def call(self,name,args):
        self.actions.append((name,args))
        if name=='Input.insertText' and args.get('text')==RotationFixture.marker: self.state.marker=True;self.state.echo=True


_real_wait_for=driver.wait_for
def _fast_wait_for(probe,code,timeout=60):
    return _real_wait_for(probe,code,timeout=0.2)


class DirectSshAndroidTests(unittest.TestCase):
    def setUp(self):
        self._wait_patcher=patch.object(driver,'wait_for',_fast_wait_for)
        self._wait_patcher.start()
        self.addCleanup(self._wait_patcher.stop)

    def test_real_ui_order_and_independent_peer_evidence(self):
        browser=Browser()
        result=driver.exercise_ui(browser,Fixture())
        self.assertEqual(browser.actions[:7],[('click','#host-open-remote'),('click','#add-ssh'),
            ('fill','#ssh-host','127.0.0.1'),('fill','#ssh-port','2222'),('fill','#ssh-user','fixture'),
            ('click','#ssh-probe'),('click','#ssh-review')])
        self.assertIn(('Input.insertText',{'text':'hp-check'}),browser.actions)
        self.assertEqual([action[1] for action in browser.actions if action[0]=='click' and 'data-ssh-key' in action[1]], [f'#ssh-helper-keys button[data-ssh-key="{key}"]' for key in ('esc','tab','left','ctrl-c')])
        self.assertTrue(result['helperKeysExact'])
        self.assertEqual(sum(action[0]=='Input.dispatchKeyEvent' for action in browser.actions),2)
        self.assertTrue(all(result[k] for k in ('fingerprintReviewed','connected','terminalInputReceived','terminalEchoRendered','disconnected','passwordCleared')))
        self.assertNotIn(Fixture.password,str(result))
        for expression in browser.expressions:
            self.assertNotIn('.click(',expression)
            self.assertNotIn('__TAURI_INTERNALS__.invoke',expression)

    def test_edit_rejects_stale_review_before_any_connect(self):
        browser=Browser();browser.review=False
        with self.assertRaisesRegex(driver.GuiFailure,'direct_credential_invalidated_host_review'):
            driver.exercise_ui(browser,Fixture())
        self.assertNotIn(('click','#ssh-form button[type=submit]'),browser.actions)

    def test_encrypted_key_ui_uses_selection_and_exports_no_secrets(self):
        fixture=Fixture();fixture.private_key='synthetic encrypted key';fixture.passphrase='synthetic passphrase'
        browser=Browser();result=driver.exercise_ui(browser,fixture,encrypted_key=True)
        self.assertIn(('select','#ssh-auth-method','key'),browser.actions)
        self.assertIn(('fill','#ssh-key',fixture.private_key),browser.actions)
        self.assertIn(('fill','#ssh-passphrase',fixture.passphrase),browser.actions)
        self.assertNotIn(('fill','#ssh-password',fixture.password),browser.actions)
        self.assertNotIn(fixture.private_key,str(result));self.assertNotIn(fixture.passphrase,str(result))

    def test_missing_peer_evidence_does_not_pass(self):
        class Missing(Fixture):
            def snapshot(self): return {**super().snapshot(),'shellRequested':False}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_peer_evidence_incomplete'):
            driver.exercise_ui(Browser(),Missing())

    def test_prior_peer_close_cannot_be_claimed_as_user_disconnect(self):
        class Closed(Fixture):
            def snapshot(self): return {**super().snapshot(),'sessionClosed':True}
        browser=Browser()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_session_ended_before_disconnect'):
            driver.exercise_ui(browser,Closed())
        self.assertNotIn(('click','#ssh-disconnect'),browser.actions)

    def test_probe_diagnostics_are_bounded_and_do_not_include_fixture_secrets(self):
        fixture=Fixture()
        fixture.snapshot=lambda: {'connections':2, 'authAccepted':False, 'secret':fixture.password}
        evidence=driver.probe_evidence(fixture)
        self.assertEqual(evidence, {'connectionObserved':True, 'authenticationAccepted':False})
        self.assertNotIn(fixture.password, str(evidence))

    def test_device_guard_refuses_non_ci_before_adb(self):
        with patch.dict(driver.os.environ,{'GITHUB_ACTIONS':'false'},clear=True), patch.object(driver,'adb') as adb:
            with self.assertRaisesRegex(driver.GuiFailure,'direct_unsafe_fixture'):
                driver.run_device(types.SimpleNamespace(is_file=lambda:True),Fixture())
            adb.assert_not_called()

    def test_rotation_ui_refuses_cancels_reprobes_and_connects_on_the_changed_key(self):
        state=RotationState();fixture=RotationFixture(state);browser=RotationBrowser(state)
        result=driver.exercise_key_change_ui(browser,fixture)
        self.assertEqual(browser.actions[:6],[('click','#host-open-remote'),('click','#add-ssh'),
            ('fill','#ssh-host','127.0.0.1'),('fill','#ssh-port','3333'),('fill','#ssh-user','fixture'),
            ('click','#ssh-probe')])
        self.assertEqual(fixture.stages,[2,3,4])
        self.assertIn(('click','#ssh-key-cancel'),browser.actions)
        self.assertEqual(browser.actions.count(('click','#ssh-review')),2)
        # After cancelling, the hidden review buttons are never driven: the
        # re-probe goes through the visible form button.
        recheck_index=browser.actions.index(('click','#ssh-key-cancel'))
        self.assertIn(('click','#ssh-probe'),browser.actions[recheck_index+1:recheck_index+3])
        self.assertNotIn(('click','#ssh-key-recheck'),browser.actions)
        self.assertIn(('Input.insertText',{'text':'hp-check'}),browser.actions)
        self.assertTrue(all(result[key] for key in ('refusalBlocked','reviewNoExits','cancelKeptTrust',
                                                    'reprobePresented','connected','terminalInputReceived',
                                                    'terminalEchoRendered','disconnected','passwordCleared')))
        self.assertEqual(result['rotationEvidence'],[{'stage':2},{'stage':3},{'stage':4}])
        self.assertNotIn(RotationFixture.password,str(result))
        for expression in browser.expressions:
            self.assertNotIn('.click(',expression)
            self.assertNotIn('__TAURI_INTERNALS__.invoke',expression)

    def test_rotation_requires_the_review_page_to_remove_every_navigation_exit(self):
        class NavigationLeftBehind(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-form button[type=submit]': self.state.nav_removed=False
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_navigation_available'):
            driver.exercise_key_change_ui(NavigationLeftBehind(state),RotationFixture(state))

    def test_rotation_requires_exactly_the_two_review_actions(self):
        state=RotationState();state.actions=['ssh-key-recheck','ssh-key-cancel','ssh-form-button']
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_actions_invalid'):
            driver.exercise_key_change_ui(RotationBrowser(state),RotationFixture(state))

    def test_rotation_requires_the_exact_reviewed_target(self):
        state=RotationState();state.target='目标：someone-else@10.9.8.7:2222'
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_review_target_missing'):
            driver.exercise_key_change_ui(RotationBrowser(state),RotationFixture(state))

    def test_rotation_cancel_must_show_the_old_key_and_only_the_old_key(self):
        state=RotationState();state.cancel_shows='SHA256:rotatedKey'
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_cancel_old_key_missing'):
            driver.exercise_key_change_ui(RotationBrowser(state),RotationFixture(state))

    def test_rotation_cancel_must_leave_no_stale_confirmation(self):
        class StaleReview(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-key-cancel': self.state.review=True
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_cancel_review_stale'):
            driver.exercise_key_change_ui(StaleReview(state),RotationFixture(state))

    def test_rotation_cancel_must_clear_and_lock_credentials(self):
        class RetainedPassword(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-key-cancel': self.state.password='temporary-local-secret'
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_cancel_credentials_live'):
            driver.exercise_key_change_ui(RetainedPassword(state),RotationFixture(state))
        state=RotationState();state.credential_disabled=False
        browser=RotationBrowser(state)
        # The submit button must stay disabled after cancelling as well.
        class LiveSubmit(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-key-cancel': self.state.submit_disabled=False
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_cancel_submit_live'):
            driver.exercise_key_change_ui(LiveSubmit(state),RotationFixture(state))

    def test_rotation_reprobe_must_replace_the_old_key_display(self):
        class BothKeysShown(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-probe' and self.state.connections==3:
                    self.state.fingerprint=f'主机 127.0.0.1:3333 · {RotationFixture.fingerprint} {RotationFixture.rotated_fingerprint}'
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_reprobe_old_key_stale'):
            driver.exercise_key_change_ui(BothKeysShown(state),RotationFixture(state))

    def test_rotation_reprobe_must_not_carry_a_stale_review(self):
        class StaleReviewSurvives(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-probe' and self.state.connections==3: self.state.review=True
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_reprobe_review_stale'):
            driver.exercise_key_change_ui(StaleReviewSurvives(state),RotationFixture(state))

    def test_rotation_cancel_must_not_start_another_connection(self):
        class ExtraConnection(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-key-cancel': self.state.connections=3  # a silent reconnect
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_cancel_reconnected'):
            driver.exercise_key_change_ui(ExtraConnection(state),RotationFixture(state))

    def test_rotation_rejects_peer_sequence_judgement_failures(self):
        state=RotationState();fixture=RotationFixture(state);fixture.evidence_error='unexpected sequence'
        browser=RotationBrowser(state)
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_evidence_invalid'):
            driver.exercise_key_change_ui(browser,fixture)
        self.assertEqual(fixture.stages,[2])

    def test_rotation_recheck_must_present_the_rotated_fingerprint(self):
        class NeverRotated(RotationBrowser):
            def click(self,selector):
                super().click(selector)
                if selector=='#ssh-probe' and self.state.connections==3:
                    self.state.fingerprint=f'主机 127.0.0.1:3333 · {RotationFixture.fingerprint}'
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_reprobe_missing'):
            driver.exercise_key_change_ui(NeverRotated(state),RotationFixture(state))

    def test_rotation_review_content_must_show_both_fingerprints(self):
        class Opaque(RotationBrowser):
            def read(self,selector):
                return '目标 127.0.0.1' if selector=='#ssh-key-change' and self.state.s10 else super().read(selector)
        state=RotationState()
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_review_content_missing'):
            driver.exercise_key_change_ui(Opaque(state),RotationFixture(state))


class TerminalScreenshotProofTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture();self.fixture.screen_token='ACDEFHJKMNPQ'
        self.geometry={'targetMatched':True,'targetVisible':True,'terminalVisible':True,
            'targetRect':[8,20,300,20],'viewport':[400,700],'dpr':2,
            'visualViewport':[0,0,1],'terminal':[10.25,150.25,379.5,500.5]}
        self.hierarchy=self.xml('[0,48][800,1448]')
        self.png=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\x0dIHDR'+struct.pack('>II',800,1500)+b'opaque-test-pixels'

    @staticmethod
    def xml(bounds, extra=''):
        return ('UI hierarchy dumped to: /dev/tty\n<hierarchy><node class="android.webkit.WebView" '
            f'package="{driver.PACKAGE}" bounds="{bounds}" text="do-not-export"/>{extra}</hierarchy>')

    def capture(self, output, *, geometry=None, hierarchy=None, gate=None, capture=None):
        with patch.object(driver,'_terminal_geometry',side_effect=geometry or [self.geometry]*6), \
             patch.object(driver,'_read_window_hierarchy',side_effect=hierarchy or [self.hierarchy]*6), \
             patch.object(driver,'_framebuffer_png',side_effect=capture or [(self.png,(800,1500))]*3), \
             patch.object(driver,'verify_terminal_screenshot',side_effect=gate), \
             patch.object(driver.time,'sleep'):
            return driver.capture_terminal_proof(Mock(),self.fixture,output,stem='terminal')

    def test_framebuffer_mapping_includes_android_insets_and_rounds_inside_terminal(self):
        self.assertEqual(driver._terminal_framebuffer_bounds(self.geometry,self.hierarchy,(800,1500)),
            (21,349,758,1000))

    def test_mapping_rejects_hidden_wrong_target_zoom_and_inconsistent_webview_scale(self):
        for update in ({'targetVisible':False},{'targetMatched':False},{'terminalVisible':False},
                       {'visualViewport':[0,0,2]},{'dpr':3},{'terminal':[0,0,401,10]}):
            with self.subTest(update=update), self.assertRaises(driver.GuiFailure):
                driver._terminal_framebuffer_bounds({**self.geometry,**update},self.hierarchy,(800,1500))

    def test_mapping_requires_unique_owned_webview_frame(self):
        foreign='<node class="android.webkit.WebView" package="other.package" bounds="[0,0][800,1500]"/>'
        self.assertEqual(driver._terminal_framebuffer_bounds(self.geometry,
            self.xml('[0,48][800,1448]',foreign),(800,1500)),(21,349,758,1000))
        duplicate=f'<node class="android.webkit.WebView" package="{driver.PACKAGE}" bounds="[0,0][800,1500]"/>'
        with self.assertRaisesRegex(driver.GuiFailure,'mapping_invalid'):
            driver._terminal_framebuffer_bounds(self.geometry,self.xml('[0,48][800,1448]',duplicate),(800,1500))

    def test_binary_capture_keeps_bytes_and_never_uses_text_adb(self):
        reply=types.SimpleNamespace(returncode=0,stdout=self.png,stderr=b'')
        with patch.object(driver.subprocess,'run',return_value=reply) as run,patch.object(driver,'adb') as adb:
            self.assertEqual(driver._framebuffer_png(),(self.png,(800,1500)))
        self.assertEqual(run.call_args.args[0],['adb','-s',driver.SERIAL,'exec-out','screencap','-p'])
        adb.assert_not_called()

    def test_capture_passes_exact_png_and_physical_bounds_to_shared_gate(self):
        gate=Mock(return_value={'markerVisible':True,'tokenVisible':True,'ocrEngine':'test engine'})
        with tempfile.TemporaryDirectory() as folder:
            result=self.capture(folder,gate=gate)
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
            self.assertEqual(json.loads(Path(folder,'terminal.json').read_text()),result)
        gate.assert_called_once_with(self.png,expected_token=self.fixture.screen_token,bounds=(21,349,758,1000))
        self.assertEqual(result['expectedTarget'],'fixture@127.0.0.1:2222')
        self.assertEqual(result['imageSha256'],hashlib.sha256(self.png).hexdigest())
        self.assertEqual(result['status'],'passed')

    def test_physical_webview_change_preserves_raw_png_and_rejects_before_ocr(self):
        changed=self.xml('[0,50][800,1450]')
        gate=Mock()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(driver.GuiFailure,'geometry_changed'):
                self.capture(folder,hierarchy=[self.hierarchy,changed]*3,gate=gate)
            result=json.loads(Path(folder,'terminal.json').read_text())
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
            self.assertEqual(result['captureAttempts'],3)
            self.assertNotEqual(result['geometryBefore'],result['geometryAfter'])
        gate.assert_not_called()

    def test_new_png_mapping_failure_does_not_keep_earlier_ocr_or_crop(self):
        second=self.png+b'new-frame'
        gate=Mock(side_effect=driver.ScreenshotGateError('terminal_screenshot_token_not_visible',
            {'markerVisible':True,'tokenVisible':False,'ocrEngine':'old engine','terminalBounds':[1,2,3,4]}))
        wrong={**self.geometry,'targetMatched':False}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(driver.GuiFailure,'target_missing'):
                self.capture(folder,geometry=[self.geometry]*2+[wrong]*4,gate=gate,
                    capture=[(self.png,(800,1500)),(second,(800,1500)),(second,(800,1500))])
            result=json.loads(Path(folder,'terminal.json').read_text())
            for key in ('markerVisible','tokenVisible','ocrEngine','terminalBounds'):
                self.assertNotIn(key,result)
            self.assertEqual(result['imageSha256'],hashlib.sha256(second).hexdigest())
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),second)

    def test_capture_failure_identifies_last_retained_frame_without_stale_ocr(self):
        failure=driver.GuiFailure('direct_terminal_framebuffer_capture_failed')
        gate=Mock(side_effect=driver.ScreenshotGateError('terminal_screenshot_token_not_visible',
            {'markerVisible':True,'ocrEngine':'old engine'}))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(driver.GuiFailure,'capture_failed'):
                self.capture(folder,gate=gate,capture=[(self.png,(800,1500)),failure,failure])
            result=json.loads(Path(folder,'terminal.json').read_text())
            self.assertEqual(result['captureAttempts'],3)
            self.assertEqual(result['imageCaptureAttempt'],1)
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
            self.assertNotIn('ocrEngine',result);self.assertNotIn('markerVisible',result)

    def test_hidden_target_exports_only_bounded_geometry_without_xml_or_secrets(self):
        hidden={**self.geometry,'targetVisible':False,'password':self.fixture.password,'rawText':'private transcript',
            'unbounded':[float('nan')],'dpr':float('inf')}
        diagnostic=driver._geometry_diagnostic(hidden,self.hierarchy)
        self.assertEqual(diagnostic['viewport'],[400,700]);self.assertFalse(diagnostic['targetVisible'])
        self.assertEqual(diagnostic['webViewCandidateBounds'],[[0,48,800,1448]])
        for value in (self.fixture.password,'private transcript','do-not-export','Infinity'):
            self.assertNotIn(value,json.dumps(diagnostic))
        self.assertNotIn('dpr',diagnostic)

    @unittest.skipUnless(shutil.which('node'),'Node is needed to execute the read-only DOM geometry probe')
    def test_dom_probe_rejects_clipped_occluded_hidden_and_stale_target_with_numeric_diagnostics(self):
        expression=driver._terminal_geometry(types.SimpleNamespace(evaluate=lambda text:text),
            'fixture@127.0.0.1:2222')
        script="""
        const expression=EXPRESSION;
        const box=(left,top,width,height)=>({left,top,width,height,right:left+width,bottom:top+height});
        let clip=false,occluded=false,shown=true,missing=false;
        globalThis.innerWidth=400;globalThis.innerHeight=700;globalThis.devicePixelRatio=2;
        globalThis.window={visualViewport:{offsetLeft:0,offsetTop:0,scale:1}};
        const parent={parentElement:null,style:{overflowX:'visible',overflowY:'hidden'},
          getBoundingClientRect:()=>box(0,0,400,clip?0:700)};
        const target={parentElement:parent,textContent:'fixture@127.0.0.1:2222 · SSH 已连接',
          checkVisibility:()=>shown,getBoundingClientRect:()=>box(8,20,300,20),contains:()=>false};
        const screen={parentElement:null,checkVisibility:()=>true,
          getBoundingClientRect:()=>box(10,150,380,500)};
        globalThis.getComputedStyle=e=>e.style;
        globalThis.document={querySelector:s=>s==='#ssh-target'?(missing?null:target):screen,
          createRange:()=>({selectNodeContents:()=>{},getClientRects:()=>[target.getBoundingClientRect()]}),
          elementFromPoint:()=>occluded?{}:target};
        const values=[eval(expression)];
        clip=true;values.push(eval(expression));clip=false;
        occluded=true;values.push(eval(expression));occluded=false;
        shown=false;values.push(eval(expression));shown=true;
        target.textContent='fixture@127.0.0.1:9999 · SSH 已连接';values.push(eval(expression));
        missing=true;values.push(eval(expression));
        process.stdout.write(JSON.stringify(values));
        """.replace('EXPRESSION',json.dumps(expression))
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True,timeout=10,check=True)
        values=json.loads(result.stdout)
        self.assertTrue(values[0]['targetVisible']);self.assertTrue(values[0]['targetMatched'])
        for value in values[1:4]:
            self.assertFalse(value['targetVisible'])
            self.assertEqual(value['viewport'],[400,700]);self.assertEqual(value['targetRect'],[8,20,300,20])
            self.assertEqual(value['terminal'],[10,150,380,500])
        self.assertFalse(values[4]['targetMatched'])
        self.assertFalse(values[5]['targetVisible']);self.assertEqual(values[5]['viewport'],[400,700])

    def test_failed_uiautomator_measurement_still_saves_raw_png_and_public_diagnostics(self):
        gate=Mock()
        failure=driver.GuiFailure('direct_terminal_hierarchy_invalid')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(driver.GuiFailure,'direct_terminal_framebuffer_mapping_invalid'):
                self.capture(folder,geometry=[self.geometry]*6,hierarchy=[failure]*6,gate=gate)
            result=json.loads(Path(folder,'terminal.json').read_text())
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
            self.assertEqual(result['imageSize'],[800,1500])
            self.assertEqual(result['geometryBefore']['viewport'],[400,700])
            self.assertFalse(result['geometryBefore']['webViewHierarchyParsed'])
        gate.assert_not_called()

    def test_ui_ordinary_and_rotation_capture_after_one_input_before_disconnect(self):
        for rotation in (False,True):
            with self.subTest(rotation=rotation):
                state=RotationState();fixture=RotationFixture(state) if rotation else Fixture()
                fixture.screen_token=self.fixture.screen_token
                browser=RotationBrowser(state) if rotation else Browser()
                def proof(*args,**kwargs):
                    self.assertEqual(sum(a[0]=='Input.insertText' for a in browser.actions),1)
                    self.assertNotIn(('click','#ssh-disconnect'),browser.actions)
                    return {'status':'passed'}
                with patch.object(driver,'capture_terminal_proof',side_effect=proof) as capture:
                    result=(driver.exercise_key_change_ui(browser,fixture,evidence_dir='/tmp') if rotation
                        else driver.exercise_ui(browser,fixture,evidence_dir='/tmp'))
                capture.assert_called_once()
                self.assertEqual(result['terminalScreenshot'],{'status':'passed'})
                self.assertEqual(sum(a[0]=='Input.insertText' for a in browser.actions),1)

    def test_encrypted_path_does_not_capture_even_if_fixture_has_screen_token(self):
        self.fixture.private_key='synthetic key';self.fixture.passphrase='synthetic passphrase'
        with patch.object(driver,'capture_terminal_proof') as capture:
            driver.exercise_ui(Browser(),self.fixture,encrypted_key=True)
        capture.assert_not_called()

    def test_hierarchy_uses_unique_device_file_exec_out_cat_and_finally_cleanup(self):
        paths=[]
        def adb(*args):
            paths.append(args)
            return self.hierarchy if args[:2]==('exec-out','cat') else 'dumped'
        with patch.object(driver,'adb',side_effect=adb):
            self.assertEqual(driver._read_window_hierarchy(),self.hierarchy)
            self.assertEqual(driver._read_window_hierarchy(),self.hierarchy)
        first=paths[0][-1];second=paths[3][-1]
        self.assertNotEqual(first,second)
        self.assertRegex(first,r'^/data/local/tmp/pocket-ssh-hierarchy-[0-9a-f]{32}\.xml$')
        self.assertEqual(paths[1],('exec-out','cat',first))
        self.assertEqual(paths[2],('shell','rm','-f',first))

    def test_hierarchy_dump_or_invalid_xml_failure_still_removes_device_file(self):
        for failure in (driver.GuiFailure('android_adb_command_failed'),'UI hierarchy dumped to /dev/tty'):
            with self.subTest(failure=type(failure).__name__):
                reply=[failure] if isinstance(failure,Exception) else ['dumped',failure]
                reply.append('')
                with patch.object(driver,'adb',side_effect=reply) as adb,self.assertRaises(driver.GuiFailure):
                    driver._read_window_hierarchy()
                self.assertEqual(adb.call_args.args[:3],('shell','rm','-f'))

    def test_hierarchy_cleanup_failure_blocks_capture_instead_of_allowing_pixel_fallback(self):
        failure=driver.GuiFailure('android_adb_command_failed')
        with patch.object(driver,'adb',side_effect=['dumped',self.hierarchy,failure]), \
             self.assertRaisesRegex(driver.GuiFailure,'direct_terminal_hierarchy_cleanup_failed'):
            driver._read_window_hierarchy()
        gate=Mock()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(driver,'_terminal_geometry',return_value=self.geometry), \
             patch.object(driver,'_read_window_hierarchy',side_effect=driver.GuiFailure('direct_terminal_hierarchy_cleanup_failed')), \
             patch.object(driver,'_webview_png',return_value=self.png), \
             patch.object(driver,'_framebuffer_png',return_value=(self.png,(800,1500))), \
             patch.object(driver,'_registered_terminal_bounds') as register, \
             patch.object(driver,'verify_terminal_screenshot',gate):
            with self.assertRaisesRegex(driver.GuiFailure,'direct_terminal_hierarchy_cleanup_failed'):
                driver.capture_terminal_proof(Mock(),self.fixture,folder,stem='terminal')
            result=json.loads(Path(folder,'terminal.json').read_text())
            self.assertEqual(result['captureAttempts'],1)
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
        register.assert_not_called();gate.assert_not_called()


class PixelRegistrationTests(unittest.TestCase):
    @staticmethod
    def png(image):
        result=io.BytesIO();image.save(result,format='PNG');return result.getvalue()

    def setUp(self):
        from PIL import Image
        import random
        randomizer=random.Random(405)
        self.reference=Image.frombytes('RGB',(160,240),randomizer.randbytes(160*240*3))
        self.frame=Image.new('RGB',(210,300),(0,0,0));self.frame.paste(self.reference,(17,23))
        # A native IME covers the lower WebView; layoutViewport remains unchanged.
        self.frame.paste((70,80,90),(0,225,210,300))
        self.geometry={'targetMatched':True,'targetVisible':True,'terminalVisible':True,
            'viewport':[160,240],'dpr':1,'visualViewport':[0,0,1],
            'targetRect':[8,12,140,24],'terminal':[8,60,140,130]}
        self.visible=(17,23,177,225)

    def test_exact_pixels_derive_nonzero_origin_despite_keyboard_clipped_native_frame(self):
        bounds,evidence=driver._registered_terminal_bounds(self.geometry,self.png(self.reference),self.png(self.frame),visible_bounds=self.visible)
        self.assertEqual(bounds,(25,83,140,130));self.assertEqual(evidence['origin'],[17,23])
        self.assertEqual(len(evidence['anchors']),3)
        self.assertEqual(evidence['anchors'][0]['sourceBounds'][:2],[8,12])

    def test_registration_rejects_same_size_unrelated_frame_and_repeated_ambiguous_content(self):
        from PIL import Image
        unrelated=Image.new('RGB',self.frame.size,(20,30,40))
        repeated=Image.new('RGB',(370,300));repeated.paste(self.reference,(0,0));repeated.paste(self.reference,(190,0))
        for frame in (unrelated,repeated):
            with self.subTest(size=frame.size),self.assertRaisesRegex(driver.GuiFailure,'pixel_registration_failed'):
                driver._registered_terminal_bounds(self.geometry,self.png(self.reference),self.png(frame),visible_bounds=self.visible)

    def test_registration_requires_target_and_terminal_to_agree_on_origin(self):
        target=self.reference.crop((8,12,148,36));self.frame.paste((0,0,0),(25,35,165,59))
        self.frame.paste(target,(30,35))
        with self.assertRaisesRegex(driver.GuiFailure,'pixel_registration_failed'):
            driver._registered_terminal_bounds(self.geometry,self.png(self.reference),self.png(self.frame),visible_bounds=self.visible)

    def test_clipped_cdp_height_uses_dpr_without_stretching_and_intersects_visible_terminal(self):
        clipped=self.reference.crop((0,0,160,155))
        bounds,evidence=driver._registered_terminal_bounds(self.geometry,self.png(clipped),self.png(self.frame),visible_bounds=self.visible)
        self.assertEqual(evidence['origin'],[17,23]);self.assertEqual(bounds,(25,83,140,95))
        self.assertEqual(evidence['webViewImageSize'],[160,155])

    def test_registration_rejects_wrong_width_oversize_height_and_target_outside_source(self):
        for source in (self.reference.resize((100,240)),self.reference.resize((160,300)),
                       self.reference.crop((0,0,160,24))):
            with self.subTest(size=source.size),self.assertRaisesRegex(driver.GuiFailure,'pixel_registration_failed'):
                driver._registered_terminal_bounds(self.geometry,self.png(source),self.png(self.frame),visible_bounds=self.visible)

    def test_wrong_target_zoom_or_out_of_frame_terminal_cannot_use_registration(self):
        for update in ({'targetMatched':False},{'visualViewport':[0,0,2]},
                       {'terminal':[8,60,200,130]}):
            with self.subTest(update=update),self.assertRaises(driver.GuiFailure):
                driver._registered_terminal_bounds({**self.geometry,**update},self.png(self.reference),self.png(self.frame),visible_bounds=self.visible)

    def test_native_visible_frame_intersection_excludes_keyboard_and_missing_frame_rejects(self):
        bounds,_=driver._registered_terminal_bounds(self.geometry,self.png(self.reference),self.png(self.frame),
            visible_bounds=(17,23,177,160))
        self.assertEqual(bounds,(25,83,140,77))
        with self.assertRaisesRegex(driver.GuiFailure,'pixel_registration_failed'):
            driver._registered_terminal_bounds(self.geometry,self.png(self.reference),self.png(self.frame))

    def test_capture_fallback_uses_actual_adb_png_and_archives_independent_cdp_pngs(self):
        fixture=Fixture();fixture.screen_token='HEAD FACT SEAT HAVE BARN DECK PATH PART'
        hierarchy=TerminalScreenshotProofTests.xml('[17,23][177,225]')
        source=self.png(self.reference);actual=self.png(self.frame)
        gate=Mock(return_value={'markerVisible':True,'tokenVisible':True,'proofSequenceVisible':True})
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(driver,'_terminal_geometry',return_value=self.geometry), \
             patch.object(driver,'_read_window_hierarchy',return_value=hierarchy), \
             patch.object(driver,'_webview_png',return_value=source), \
             patch.object(driver,'_framebuffer_png',return_value=(actual,self.frame.size)), \
             patch.object(driver,'verify_terminal_screenshot',gate):
            result=driver.capture_terminal_proof(Mock(),fixture,folder,stem='terminal')
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),actual)
            for suffix in ('before','after'):
                self.assertEqual(Path(folder,f'terminal-webview-{suffix}.png').read_bytes(),source)
        self.assertEqual(result['coordinateMethod'],'exact_pixel_registration')
        self.assertEqual(result['pixelRegistrationBefore']['origin'],[17,23])
        gate.assert_called_once_with(actual,expected_token=fixture.screen_token,bounds=(25,83,140,130))


if __name__=='__main__': unittest.main()
