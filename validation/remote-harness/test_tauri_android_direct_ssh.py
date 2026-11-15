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


class DirectSshAndroidTests(unittest.TestCase):
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


if __name__=='__main__': unittest.main()
