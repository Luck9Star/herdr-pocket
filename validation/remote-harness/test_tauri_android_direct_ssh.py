"""No AVD or SSH: verify that the device driver cannot claim unobserved UI/peer evidence."""
import types
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


if __name__=='__main__': unittest.main()
