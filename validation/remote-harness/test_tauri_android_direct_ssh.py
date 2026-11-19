"""No AVD or SSH: verify that the device driver cannot claim unobserved UI/peer evidence."""
import types
import io
import hashlib
import os
import sys
import json
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

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
        return {**{key:True for key in ('authAccepted','ptyRequested','shellRequested','markerReceived')},
                'helperKeysExact':True, 'sessionClosed':self.reads>3,
                'connectionsClosed':self.reads>3, 'connectionEvents': [{'authAttempts': 1, 'inputBytes': 9}]}


class Browser:
    def __init__(self): self.actions=[];self.expressions=[];self.review=True;self.echo=True;self.entry='#host-open-remote'
    def click(self,selector): self.actions.append(('click',selector))
    def fill(self,selector,value): self.actions.append(('fill',selector,value))
    def select_option(self,selector,value): self.actions.append(('select',selector,value))
    def read(self,selector):
        return {'#ssh-fingerprint':Fixture.fingerprint,'#ssh-status':'已连接，已断开'}.get(selector,'')
    def evaluate(self,expression):
        self.expressions.append(expression)
        if 'dashboardAddEntry' in expression: return self.entry
        if 'sshSetupLayout' in expression: return 'legacy'
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
        if 'dashboardAddEntry' in expression: return '#host-open-remote'
        if 'sshSetupLayout' in expression: return 'legacy'
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

    def test_staged_encrypted_key_only_uses_mobile_confirmation_auth_and_back_controls(self):
        class KeyFixture(Fixture):
            private_key='synthetic key'
            passphrase='synthetic phrase'
            def snapshot(self):
                return {**super().snapshot(), 'connections':2,
                        'connectionEvents':[{'hostKey':'A'}, {'hostKey':'A','authAccepted':True}]}
        class MobileBrowser(Browser):
            def evaluate(self, expression):
                return 'staged' if 'sshSetupLayout' in expression else super().evaluate(expression)
        browser=MobileBrowser()
        fixture=KeyFixture()
        with patch.object(driver, 'mobile_setup') as verify, patch.object(driver, 'require_first_probe') as probe, \
             patch.object(driver, 'native_active_tap', side_effect=lambda b, selector: b.click(selector)) as native:
            result=driver.exercise_ui(browser, fixture, encrypted_key=True)
        self.assertTrue(result['returnedHome'])
        self.assertEqual([c.args[1] for c in native.call_args_list], ['#ssh-disconnect', '#ssh-return-home'])
        self.assertEqual(probe.call_count,2)
        actions=browser.actions
        self.assertNotIn(('click','#ssh-review'), actions)
        self.assertNotIn(('select','#ssh-auth-method','key'), actions)
        requested=[('click','#ssh-trust-confirm'),('click','#ssh-auth-key'),('fill','#ssh-key',fixture.private_key),
                   ('fill','#ssh-passphrase',fixture.passphrase),('click','#ssh-connect'),('click','#ssh-return-home')]
        self.assertEqual([a for a in actions if a in requested],requested)
        self.assertEqual([('auth','key','empty'),('auth','key','pem'),('auth','key','ready')],
                         [(call.args[2],call.kwargs['method'],call.kwargs.get('input_state','empty'))
                          for call in verify.call_args_list if 'method' in call.kwargs])

    def test_staged_rotation_rechecks_after_native_refusal_and_cancellation(self):
        class MobileRotation(RotationBrowser):
            def evaluate(self, expression):
                return 'staged' if 'sshSetupLayout' in expression else super().evaluate(expression)
            def click(self, selector):
                super().click({'#ssh-trust-confirm':'#ssh-review','#ssh-connect':'#ssh-form button[type=submit]'}.get(selector,selector))
                self.actions[-1]=('click',selector)
        state=RotationState()
        fixture=RotationFixture(state)
        browser=MobileRotation(state)
        with patch.object(driver,'mobile_setup') as verify, patch.object(driver,'require_first_probe'), \
             patch.object(driver,'native_active_tap',side_effect=lambda b, selector: b.click(selector)) as native:
            driver.exercise_key_change_ui(browser,fixture)
        self.assertEqual([c.args[1] for c in native.call_args_list], ['#ssh-disconnect', '#ssh-return-home'])
        self.assertEqual([a[1] for a in browser.actions if a[0]=='click' and a[1] in
                          ('#ssh-trust-confirm','#ssh-connect','#ssh-key-cancel')],
                         ['#ssh-trust-confirm','#ssh-connect','#ssh-key-cancel','#ssh-trust-confirm','#ssh-connect'])
        self.assertEqual([(call.args[2],call.kwargs) for call in verify.call_args_list if call.args[2] in ('trust','refused')],
                         [('trust',{'fingerprint':fixture.fingerprint}),('refused',{'fingerprint':fixture.rotated_fingerprint,
                          'prior':fixture.fingerprint}),('trust',{'fingerprint':fixture.rotated_fingerprint,
                          'prior':fixture.fingerprint})])
        self.assertEqual(fixture.stages,[2,3,3,4,4])

    def test_initial_peer_gate_cannot_accept_an_early_authentication_attempt(self):
        facts={'hostKey':'A','closed':True,
               **{k:0 for k in ('authAttempts','authSuccesses','ptyRequests','shellRequests','inputBytes','outputBytes')}}
        peer=Mock()
        peer.wait_for_connections_closed.return_value=True
        peer.snapshot.return_value={'connections':1,'connectionEvents':[facts]}
        driver.require_first_probe(peer)
        facts['authAttempts']=1
        with self.assertRaisesRegex(driver.GuiFailure,'direct_probe_peer_unproven'):
            driver.require_first_probe(peer)

    @unittest.skipUnless(shutil.which('node'), 'requires Node.js to run the real mobile setup probe')
    def test_mobile_trust_dom_requires_exact_endpoint_algorithm_and_locked_credentials(self):
        browser=Mock()
        browser.evaluate.return_value=True
        fingerprint='SHA256:'+'A'*43
        rotated='SHA256:'+'B'*43
        fixture=types.SimpleNamespace(username='fixture',port=1234,public_key='ssh-rsa synthetic',
                                      rotated_fingerprint=rotated,rotated_public_key='ssh-ed25519 synthetic')
        driver.mobile_setup(browser,fixture,'trust',fingerprint=fingerprint)
        expression=browser.evaluate.call_args.args[0]
        driver.mobile_setup(browser,fixture,'refused',fingerprint=rotated,prior=fingerprint)
        refused=browser.evaluate.call_args.args[0]
        driver.mobile_setup(browser,fixture,'closed')
        closed=browser.evaluate.call_args.args[0]
        browser.evaluate.return_value='staged'
        self.assertTrue(driver.staged_setup(browser))
        layout=browser.evaluate.call_args.args[0]
        script=r'''const assert=require('node:assert/strict');
const check=()=>%s;
const checkRefused=()=>%s;
const checkClosed=()=>%s;
const choose=()=>%s;
const element=(innerText='',options={})=>({innerText,hidden:false,value:'',disabled:false,
  tagName:'DIV', getClientRects(){return this.hidden?[]:[0];}, ...options});
const button=label=>element(label,{tagName:'BUTTON'});
const nodes={
 'home-ssh':element('',{dataset:{sshStep:'trust'}}), 'ssh-step-title':element('核对主机密钥'),
 'ssh-target-fields':element('',{hidden:true}), 'ssh-trust-review':element(),
 'ssh-credentials':element('',{hidden:true}), 'ssh-review':element('',{hidden:true}),
 'ssh-reviewed-endpoint':element('fixture@127.0.0.1:1234'), 'ssh-reviewed-algorithm':element('ssh-rsa'),
 'ssh-reviewed-fingerprint':element('SHA256:'+'A'.repeat(21)+'\n'+'A'.repeat(22)),
 'ssh-trust-confirm':button('指纹一致，确认继续'), 'ssh-trust-cancel':button('取消核对'),
 'ssh-connect':element('',{tagName:'BUTTON',hidden:true,disabled:true}),
 'ssh-password':element('',{type:'password',hidden:true,disabled:true}),
 'ssh-passphrase':element('',{type:'password',hidden:true,disabled:true}),
 'ssh-key':element('',{tagName:'TEXTAREA',hidden:true,disabled:true})};
let duplicate;
global.document={querySelectorAll(selector){const id=selector.slice(1); return !nodes[id]?[]:id===duplicate?[nodes[id],nodes[id]]:[nodes[id]];}};
global.getComputedStyle=()=>({visibility:'visible'});
assert.equal(check(),true);
const reject=(id,key,value)=>{const old=nodes[id][key];nodes[id][key]=value;assert.ok(!check());nodes[id][key]=old;};
reject('ssh-reviewed-endpoint','innerText','fixture@127.0.0.1:12345');
reject('ssh-reviewed-fingerprint','innerText','SHA256:'+'A'.repeat(44));
reject('ssh-reviewed-algorithm','innerText','ssh-ed25519');
reject('ssh-password','disabled',false);
reject('ssh-password','value','stale');
reject('ssh-key','hidden',false);
reject('ssh-trust-cancel','disabled',true);
duplicate='ssh-trust-confirm';assert.ok(!check());
duplicate=null;
Object.assign(nodes, {'ssh-setup':element('',{hidden:true}), 'ssh-key-change':element(),
  'ssh-key-change-endpoint':element('fixture@127.0.0.1:1234'),
  'ssh-key-change-algorithms':element('旧密钥算法 · ssh-rsa'),
  'ssh-key-change-old':element('旧：SHA256:'+'A'.repeat(43)),
  'ssh-key-change-new':element('新：SHA256:'+'B'.repeat(43)),
  'ssh-key-change-target':element('目标：fixture@127.0.0.1:1234',{hidden:true})});
assert.equal(checkRefused(),true);
nodes['ssh-key-change-endpoint'].hidden=true;assert.ok(!checkRefused());
nodes['ssh-key-change-endpoint'].hidden=false;
nodes['ssh-key-change-algorithms'].innerText='旧密钥算法 · ssh-ed25519';assert.ok(!checkRefused());
let narrow=true;
global.matchMedia=()=>({matches:narrow});
const route=nodes['home-ssh'], title=nodes['ssh-step-title'], review=nodes['ssh-review'];
route.hasAttribute=()=>Object.hasOwn(route.dataset,'sshStep');
route.dataset.sshStep='target';title.innerText='普通 SSH';
Object.assign(nodes, {'ssh-target-fields':element(), 'ssh-trust-review':element('',{hidden:true}),
  'ssh-closed-feedback':element(), 'ssh-closed-title':element('本机已断开'),
  'ssh-closed-detail':element('凭据已清空，重连时请重新填写。'),
  'ssh-return-home':button('返回首页'), 'ssh-step-back':button('返回'),
  'ssh-probe':button('探测并核对主机密钥')});
assert.equal(checkClosed(),true);
nodes['ssh-closed-detail'].innerText='远端已报告结束，凭据已清空。';assert.ok(!checkClosed());
nodes['ssh-closed-detail'].innerText='凭据已清空，重连时请重新填写。';
nodes['ssh-password'].value='stale';assert.ok(!checkClosed());nodes['ssh-password'].value='';
nodes['ssh-return-home'].disabled=true;assert.ok(!checkClosed());nodes['ssh-return-home'].disabled=false;
assert.equal(choose(),'staged');
delete route.dataset.sshStep;title.hidden=true;review.hidden=false;review.type='checkbox';
assert.equal(choose(),null);
narrow=false;assert.equal(choose(),'legacy');
''' % (expression,refused,closed,layout)
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_compact_home_uses_the_card_and_returns_after_peer_close(self):
        browser = Browser()
        browser.entry = '#host-empty-add'
        result = driver.exercise_ui(browser, Fixture())
        self.assertEqual(browser.actions[:2], [('click', '#host-empty-add'), ('click', '#add-ssh')])
        self.assertEqual(browser.actions[-2:], [('click', '#ssh-disconnect'), ('click', '#show-remote')])
        self.assertTrue(result['returnedHome'])
        class ReplaysAfterReturn(Browser):
            def click(self, selector):
                super().click(selector)
                if selector == '#show-remote':
                    fixture.snapshot = lambda: {'connectionsClosed': False, 'connectionEvents': []}
        fixture = Fixture()
        with self.assertRaisesRegex(driver.GuiFailure, 'direct_return_home_peer_changed'):
            driver.exercise_ui(ReplaysAfterReturn(), fixture)

    @unittest.skipUnless(shutil.which('node'), 'requires Node.js to run the real dashboard selector')
    def test_dashboard_selector_prefers_real_actions_and_rejects_mismatched_pages(self):
        browser = Mock()
        browser.evaluate.return_value = '#host-empty-add'
        self.assertEqual(driver.dashboard_add_selector(browser), '#host-empty-add')
        expression = browser.evaluate.call_args.args[0]
        js = '''const assert = require('node:assert/strict');
const select = () => %s;
const row = (textContent, tagName='DIV', props={}) => ({textContent, tagName,
  hidden:false, getClientRects(){return this.visible ? [0] : [];},
  matches(){return this.disabled===true;}, hasAttribute(){return this.compact===true;},
  visible:true, ...props});
const entries = {
  '#host-home #home-dashboard': [row('')],
  '#host-home-status': [row('', 'P', {hidden:true})],
  '#home-dashboard #host-empty': [row('', 'SECTION', {compact:true})],
  '#host-open-remote': [row('＋ 添加主机','BUTTON',{visible:false})],
  '#host-empty h3': [row('还没有主机')],
  '#host-empty p': [row('添加主机后，在这里查看会话和任务状态。')],
  '#host-empty #host-empty-add': [row('添加主机','BUTTON')],
  '#host-empty #home-open-ssh': [row('普通 SSH 终端','BUTTON')],
};
global.document = {hidden:false, querySelectorAll: selector => entries[selector] || []};
global.getComputedStyle = () => ({visibility:'visible', opacity:'1'});
assert.equal(select(), '#host-empty-add');
const status = entries['#host-home-status'][0];
status.hidden = false; status.textContent = '正在读取本机资料…'; assert.equal(select(), null);
status.textContent = '本机资料不可用；仍可打开手动连接表单。'; assert.equal(select(), null);
status.textContent = '还没有已存主机；网络配置暂不可读。'; assert.equal(select(), '#host-empty-add');
status.hidden = true;
const add = entries['#host-empty #host-empty-add'];
add.push(row('添加主机','BUTTON')); assert.equal(select(), null); add.pop();
add[0].tagName = 'DIV'; assert.equal(select(), null); add[0].tagName = 'BUTTON';
add[0].disabled = true; assert.equal(select(), null); add[0].disabled = false;
const header = entries['#host-open-remote'][0];
header.visible = true; assert.equal(select(), null);
const card = entries['#home-dashboard #host-empty'][0];
card.compact = false; assert.equal(select(), '#host-open-remote');
card.hidden = true; assert.equal(select(), '#host-open-remote');
entries['#host-home #home-dashboard'][0].hidden = true; assert.equal(select(), null);
''' % expression
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ready_probe_closes_failed_view_and_recovers_without_replaying_input(self):
        broken = Mock()
        broken.evaluate.side_effect = driver.GuiFailure('android_cdp_transport_failed')
        pending = Mock()
        pending.evaluate.return_value = False
        ready = Mock()
        ready.evaluate.return_value = True
        with patch.object(driver, 'AndroidWebView', side_effect=[broken, pending, ready]) as constructor:
            self.assertFalse(driver._connect_ready(1234))
            self.assertFalse(driver._connect_ready(1234))
            self.assertIs(driver._connect_ready(1234), ready)
        broken.close.assert_called_once_with()
        pending.close.assert_called_once_with()
        ready.close.assert_not_called()
        self.assertEqual(constructor.call_count, 3)
        self.assertFalse(broken.method_calls and any(call[0] in ('click', 'fill') for call in broken.method_calls))

    def test_preprobe_failure_stage_and_error_are_fixed_and_do_not_export_secrets(self):
        class FailedBrowser(Browser):
            def __init__(self, failed_selector, code):
                super().__init__(); self.failed_selector=failed_selector; self.code=code
            def click(self, selector):
                if selector == self.failed_selector: raise driver.GuiFailure(self.code)
                super().click(selector)
            def fill(self, selector, value):
                if selector == self.failed_selector: raise driver.GuiFailure(self.code)
                super().fill(selector, value)
        for selector, code, expected_stage, expected_code in (
            ('#host-open-remote','android_control_missing_host-open-remote','open_remote','direct_android_control_missing'),
            ('#add-ssh','android_cdp_transport_failed','open_ssh_form','direct_android_cdp_transport_failed'),
            ('#ssh-port','android_text_control_missing_ssh-port','enter_port','direct_android_text_control_missing'),
            ('#ssh-probe','secret-key-or-password','probe_host','direct_driver_failed'),
        ):
            progress={}
            with self.subTest(selector=selector), self.assertRaises(driver.GuiFailure) as caught:
                driver.exercise_ui(FailedBrowser(selector,code),Fixture(),encrypted_key=True,progress=progress)
            public={'failureStage':progress['stage'], 'errorCode':driver.public_driver_error(caught.exception)}
            self.assertEqual(public,{'failureStage':expected_stage,'errorCode':expected_code})
            self.assertNotIn('secret',json.dumps(public))
        self.assertEqual(driver.public_driver_error(driver.GuiFailure('direct_fingerprint_missing')),
                         'direct_fingerprint_missing')
        self.assertEqual(driver.public_driver_error(driver.GuiFailure('direct_private_key_secret')),
                         'direct_driver_failed')

    def test_manifest_retains_safe_failure_stage_after_two_completed_scenarios(self):
        import sys
        import direct_ssh_fixture
        import tauri_encrypted_key_fixture
        ordinary = MagicMock(); rotation = MagicMock(); encrypted = MagicMock()
        for peer in (ordinary, rotation, encrypted):
            peer.__enter__ = Mock(return_value=peer)
            peer.__exit__ = Mock(return_value=False)
            peer.snapshot.return_value = {'connectionsClosed': True, 'connections': 0, 'authAccepted': False}
        def run_device(apk, fixture, *, progress, **kwargs):
            if fixture is encrypted:
                progress['stage'] = 'enter_port'
                raise driver.GuiFailure('android_text_control_missing_sensitive-selector')
            progress['stage'] = 'disconnect'
            return {'cleanup': {}}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); apk=root/'fixture.apk'; apk.write_bytes(b'APK fixture')
            output=root/'output'
            with patch.dict(driver.os.environ, {'RUNNER_TEMP':str(root)}, clear=True), \
                 patch.object(sys,'argv',['driver','--apk',str(apk),'--output',str(output)]), \
                 patch.object(direct_ssh_fixture,'DirectSshFixture',side_effect=[ordinary, rotation]), \
                 patch.object(tauri_encrypted_key_fixture,'EncryptedKeyFixture',return_value=encrypted), \
                 patch.object(driver,'run_device',side_effect=run_device):
                with self.assertRaises(SystemExit): driver.main()
            report=json.loads((output/'manifest.json').read_text())
            self.assertEqual((report['phase'], report['failureStage'], report['errorCode']),
                             ('encrypted_key', 'enter_port', 'direct_android_text_control_missing'))
            self.assertEqual(report['probeEvidence'], {'connectionObserved':False, 'authenticationAccepted':False})
            self.assertNotIn('sensitive-selector', json.dumps(report))
            self.assertIn('rotation',report)

    def test_actual_android_webview_control_failure_is_classified_at_real_entry(self):
        import android_gui
        view=driver.AndroidWebView.__new__(driver.AndroidWebView)
        view.evaluate=Mock(side_effect=['#host-open-remote', None, None])
        def immediate(probe, code, **kwargs):
            value=probe()
            if not value: raise driver.GuiFailure(code)
            return value
        progress={}
        with patch.object(android_gui,'wait_for',side_effect=immediate):
            with self.assertRaises(driver.GuiFailure) as caught:
                driver.exercise_ui(view,Fixture(),encrypted_key=True,progress=progress)
        self.assertEqual(progress['stage'],'open_remote')
        self.assertEqual(driver.public_driver_error(caught.exception),'direct_android_control_missing')
        self.assertEqual(view.evaluate.call_count,3)

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




class ActiveNavigationTests(unittest.TestCase):
    def peer(self):
        return {'connections':2,'sessionClosed':False,'connectionEvents':[
          {'hostKey':'A','closed':True},
          {'hostKey':'A','closed':False,'authAccepted':True,'authAttempts':1,'authSuccesses':1,
           'ptyRequests':1,'shellRequests':1,'inputBytes':0}]}

    def test_peer_gate_rejects_reconnection_extra_auth_pty_input_and_closed(self):
        import copy
        facts=self.peer(); fixture=Mock(); fixture.snapshot.return_value=facts
        driver.active_peer(fixture)
        for key,value in [('authAttempts',2),('authSuccesses',2),('ptyRequests',2),
                          ('shellRequests',2),('inputBytes',1),('closed',True),('hostKey','B')]:
            changed=copy.deepcopy(facts);changed['connectionEvents'][1][key]=value
            fixture.snapshot.return_value=changed
            with self.subTest(key=key),self.assertRaisesRegex(driver.GuiFailure,'direct_active_peer_changed'):
                driver.active_peer(fixture)
        fixture.snapshot.return_value={**facts,'connections':3}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_active_peer_changed'): driver.active_peer(fixture)
        changed=copy.deepcopy(facts);changed['connectionEvents'][1]['inputBytes']=9
        fixture.snapshot.return_value=changed;driver.active_peer(fixture,input_bytes=9)
        with self.assertRaisesRegex(driver.GuiFailure,'direct_active_peer_changed'): driver.active_peer(fixture)

    def test_native_tap_maps_stable_webview_to_android_screen_and_rejects_ambiguity(self):
        browser=Mock();geometry={'point':[100,120],'rect':[78,98,44,44],
            'viewport':[400,800],'visual':[0,0,1],'dpr':2,'hit':True}
        browser.evaluate.return_value=geometry
        with patch.object(driver,'_read_window_hierarchy',return_value='owned'), \
             patch.object(driver,'_webview_frames',return_value={(10,40,810,1400)}), \
             patch.object(driver,'_header_geometry',return_value={'native':{'viewY':40}}), \
             patch.object(driver,'_framebuffer_png',return_value=(b'',(850,1500))),patch.object(driver,'adb') as adb:
            driver.native_active_tap(browser,'#ssh-focus')
            adb.assert_called_once_with('shell','input','tap','210','280')
            adb.reset_mock();browser.evaluate.side_effect=None;browser.evaluate.return_value=geometry
            driver.native_active_tap(browser,'#ssh-disconnect')
            adb.assert_called_once_with('shell','input','tap','210','280')
            adb.reset_mock();browser.evaluate.side_effect=[None,geometry,geometry]
            driver.native_active_tap(browser,'#ssh-return-home')
            adb.assert_called_once_with('shell','input','tap','210','280')
            adb.reset_mock();browser.evaluate.side_effect=[geometry,{**geometry,'hit':False}]
            with self.assertRaisesRegex(driver.GuiFailure,'direct_active_tap_unproven'):
                driver.native_active_tap(browser,'#ssh-focus')
            adb.assert_not_called()
            with self.assertRaisesRegex(driver.GuiFailure,'direct_active_tap_unproven'):
                driver.native_active_tap(browser,'#unsupported')
            adb.assert_not_called()

    def test_preexisting_owned_keyboard_is_dismissed_before_native_focus_tap(self):
        browser=Mock();fixture=Mock();order=[]
        def system(visible):
            order.append(('ime',visible))
            if len(order)==1: raise driver.GuiFailure('android_system_ime_hide_unconfirmed')
            return {'diagnostic':{}}
        def native(b,selector): order.append(('tap',selector))
        def adb(*args): order.append(('adb',args))
        with patch.object(driver,'active_view'),patch.object(driver,'active_peer'), \
             patch.object(driver,'native_active_tap',side_effect=native),patch.object(driver,'system_keyboard',side_effect=system), \
             patch.object(driver,'adb',side_effect=adb):
            driver.exercise_active_navigation(browser,fixture)
        self.assertEqual(order[:5],[('ime',False),('ime',True),('adb',('shell','input','keyevent','KEYCODE_BACK')),
                                  ('ime',False),('tap','#ssh-focus')])

    def test_preexisting_keyboard_must_be_owned_before_back(self):
        with patch.object(driver,'active_view'),patch.object(driver,'active_peer'), \
             patch.object(driver,'system_keyboard',side_effect=[driver.GuiFailure('android_system_ime_hide_unconfirmed'),
                                                              driver.GuiFailure('android_system_ime_target_mismatch')]), \
             patch.object(driver,'adb') as adb,patch.object(driver,'native_active_tap') as tap:
            with self.assertRaisesRegex(driver.GuiFailure,'android_system_ime_target_mismatch'):
                driver.exercise_active_navigation(Mock(),Mock())
            adb.assert_not_called();tap.assert_not_called()

    def test_active_view_fails_closed_for_each_false_fact_and_malformed_evidence(self):
        fixture=Fixture(); good=dict.fromkeys(driver.ACTIVE_FACTS,True);browser=Mock()
        with patch.object(driver,'wait_for',side_effect=lambda probe,code,timeout: probe() or (_ for _ in ()).throw(driver.GuiFailure(code))):
            browser.evaluate.return_value=good;driver.active_view(browser,fixture,'ssh')
            for key in driver.ACTIVE_FACTS:
                browser.evaluate.return_value={**good,key:False}
                with self.subTest(key=key),self.assertRaises(driver.GuiFailure) as caught:
                    driver.active_view(browser,fixture,'ssh')
                self.assertIs(caught.exception.active_diagnostic[key],False)
            browser.evaluate.return_value={**good,'unexpected':'private text'}
            with self.assertRaises(driver.GuiFailure) as caught: driver.active_view(browser,fixture,'ssh')
            self.assertEqual(caught.exception.active_diagnostic,{})

    def test_diagnostic_keeps_only_bounded_geometry_and_peer_counts(self):
        fixture=Mock();fixture.snapshot.return_value=self.peer();browser=Mock()
        geometry={key:[1,2,3,4] for key in ('viewport','title','badge','focus','hide','disconnect')}
        browser.evaluate.return_value=geometry
        result=driver.active_diagnostic(browser,fixture)
        self.assertEqual(result['geometry'],geometry)
        self.assertEqual(result['peer']['connections'],2)
        self.assertNotIn('hostKey',result['peer'])
        browser.evaluate.return_value={**geometry,'secret':'do not export'}
        self.assertNotIn('geometry',driver.active_diagnostic(browser,fixture))
        fixture.snapshot.return_value={**self.peer(),'connections':999999}
        self.assertNotIn('peer',driver.active_diagnostic(browser,fixture))

    def test_failure_records_exact_active_stage(self):
        browser=Mock();fixture=Mock();progress={}
        def view(b,f,section,keyboard=False):
            if section=='network': raise driver.GuiFailure('direct_active_ui_invalid')
        with patch.object(driver,'active_view',side_effect=view),patch.object(driver,'active_peer'), \
             patch.object(driver,'system_keyboard',return_value={'diagnostic':{}}),patch.object(driver,'native_active_tap'),patch.object(driver,'active_diagnostic',return_value={}):
            with self.assertRaises(driver.GuiFailure): driver.exercise_active_navigation(browser,fixture,progress=progress)
        self.assertEqual(progress['stage'],'active_network')

    def test_navigation_checks_each_route_and_native_keyboard_before_peer(self):
        browser=Mock();fixture=Mock();calls=[]
        with patch.object(driver,'active_view',side_effect=lambda b,f,s,keyboard=False:calls.append((s,keyboard))), \
             patch.object(driver,'active_peer') as peer, patch.object(driver,'system_keyboard',return_value={'diagnostic':{}}) as ime, \
             patch.object(driver,'native_active_tap') as tap:
            result=driver.exercise_active_navigation(browser,fixture)
        self.assertEqual(calls,[('ssh',False),('ssh',True),('ssh',False),('dashboard',False),
            ('ssh',False),('network',False),('ssh',False),('settings',False),('ssh',False)])
        self.assertEqual(peer.call_count,9)
        self.assertEqual([c.args[0] for c in ime.call_args_list],[False,True,True,False,False])
        self.assertEqual([c.args[1] for c in tap.call_args_list],['#ssh-focus','#ssh-hide-keyboard'])
        self.assertTrue(all(result.values()))
        self.assertEqual([c.args[0] for c in browser.click.call_args_list],['#show-remote','#nav-terminal','#nav-network','#nav-terminal','#nav-settings','#nav-terminal'])


class HeaderGeometryTests(unittest.TestCase):
    def setUp(self):
        self.geometry={'viewport':[400,700],'visualViewport':[0,0,1],'dpr':2.0,
            'scrollY':0,'appliedTopCss':28,
            'native':{'overlapPx':56,'systemBottomPx':104,'viewY':48,'windowTopPx':0,
                'statusPx':104,'stableStatusPx':104,'cutoutPx':0,'captionPx':0,'stableCaptionPx':0},
            'header':{'rect':[0,0,400,85],'visible':True},
            'title':{'rect':[20,30,120,20],'visible':True},
            'button':{'rect':[260,32,120,44],'visible':True},
            'sshTitle':{'rect':[20,90,120,20],'visible':True},
            'target':{'rect':[8,120,300,20],'visible':True},
            'terminal':{'rect':[8,150,300,400],'visible':True},
            'xterm':{'rect':[8,150,300,400],'visible':True}}

    def test_header_uses_unpanned_window_inset_and_physical_registered_origin(self):
        evidence=driver._header_evidence(self.geometry,origin=(10,48),image_size=(850,1500))
        self.assertEqual(evidence['nativePx']['systemBottomPx'],104)
        self.assertEqual(evidence['title']['boundsPx'],[50,108,240,40])
        self.assertEqual(evidence['button']['boundsPx'],[530,112,240,88])
        # WindowMetrics bounds remain fixed as the WebView pans upward.
        native={**self.geometry['native'],'viewY':-10,'overlapPx':114}
        values={**self.geometry,'native':native,
            'header':{'rect':[0,0,400,100],'visible':True},
            'title':{'rect':[20,60,120,20],'visible':True},
            'button':{'rect':[260,60,120,35],'visible':True},
            'sshTitle':{'rect':[20,105,120,20],'visible':True},
            'target':{'rect':[8,130,300,20],'visible':True}}
        panned=driver._header_evidence(values,origin=(10,-10),image_size=(850,1500))
        self.assertEqual(panned['nativePx']['systemBottomPx'],104)
        self.assertEqual(panned['title']['boundsPx'][1],110)

    def test_header_overlap_and_unknown_geometry_fail_closed(self):
        bad_title={**self.geometry,'title':{'rect':[20,27,120,20],'visible':True}}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_header_system_overlap'):
            driver._header_evidence(bad_title,origin=(10,48),image_size=(850,1500))
        for change in ({'native':{**self.geometry['native'],'overlapPx':None}}, {'dpr':0},
                       {'visualViewport':[0,1,1]}, {'button':{'rect':[260,32,120,44],'visible':False}},
                       {'button':{'rect':[390,32,120,44],'visible':True}}):
            with self.subTest(change=change), self.assertRaisesRegex(driver.GuiFailure,'direct_header_measurement_invalid'):
                driver._header_evidence({**self.geometry,**change},origin=(10,48),image_size=(850,1500))
        for native in ({**self.geometry['native'],'windowTopPx':None},
                       {**self.geometry['native'],'viewY':49}):
            with self.subTest(native=native), self.assertRaisesRegex(driver.GuiFailure,'direct_header_measurement_invalid'):
                driver._header_evidence({**self.geometry,'native':native},origin=(10,48),image_size=(850,1500))
        overlap={**self.geometry,'target':{'rect':[8,70,300,20],'visible':True}}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_header_content_overlap'):
            driver._header_evidence(overlap,origin=(10,48),image_size=(850,1500))
        wrong={**self.geometry,'native':{**self.geometry['native'],'windowTopPx':10}}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_header_measurement_invalid'):
            driver._header_evidence(wrong,origin=(10,48),image_size=(850,1500))
        hidden_title={**self.geometry,'sshTitle':{'rect':[20,-30,120,20],'visible':False}}
        self.assertFalse(driver._header_evidence(hidden_title,origin=(10,48),image_size=(850,1500))['sshTitle']['visible'])

    def test_partly_visible_ssh_title_is_diagnostic_only(self):
        partial={**self.geometry,'sshTitle':{'rect':[20,-5,120,20],'visible':True}}
        evidence=driver._header_evidence(partial,origin=(10,48),image_size=(850,1500))
        self.assertTrue(evidence['sshTitle']['visible'])
        self.assertTrue(evidence['sshTitle']['inViewport'])
        self.assertNotIn('boundsPx',evidence['sshTitle'])

    def test_header_reads_only_native_inset_and_dom_geometry(self):
        browser=Mock();browser.call.return_value={'result':{'value':self.geometry}}
        self.assertEqual(driver._header_geometry(browser),self.geometry)
        args=browser.call.call_args.args
        self.assertEqual(args[0],'Runtime.evaluate')
        self.assertTrue(args[1]['awaitPromise'])
        self.assertIn("invoke('mobile_system_top_inset')",args[1]['expression'])
        self.assertNotIn('__herdrPocketInsetGeometry',args[1]['expression'])
        browser.call.return_value={'exceptionDetails':{}}
        with self.assertRaisesRegex(driver.GuiFailure,'direct_header_measurement_invalid'):
            driver._header_geometry(browser)

class TerminalScreenshotProofTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture();self.fixture.screen_token='ACDEFHJKMNPQ'
        self.geometry={'targetMatched':True,'targetVisible':True,'terminalVisible':True,
            'targetRect':[8,20,300,20],'viewport':[400,700],'dpr':2,
            'visualViewport':[0,0,1],'terminal':[10.25,150.25,379.5,500.5]}
        self.header={'viewport':[400,700],'visualViewport':[0,0,1],'dpr':2,'scrollY':0,'appliedTopCss':0,
            'native':{'overlapPx':0,'systemBottomPx':48,'viewY':48,'windowTopPx':0,'statusPx':48,
                'stableStatusPx':48,'cutoutPx':0,'captionPx':0,'stableCaptionPx':0},
            'header':{'rect':[0,0,400,15],'visible':True},'title':{'rect':[5,2,30,10],'visible':True},
            'button':{'rect':[300,2,90,10],'visible':True},'sshTitle':{'rect':[8,-30,120,20],'visible':False},
            'target':{'rect':[8,20,300,20],'visible':True},'terminal':{'rect':[10,150,379,500],'visible':True},
            'xterm':{'rect':[10,150,379,500],'visible':True}}
        self.header_patch=patch.object(driver,'_header_geometry',return_value=self.header)
        self.header_patch.start();self.addCleanup(self.header_patch.stop)
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

    def test_header_overlap_retains_real_frame_and_blocks_ocr(self):
        invalid={**self.header,'native':{**self.header['native'],'windowTopPx':40,
            'statusPx':48,'stableStatusPx':48,'systemBottomPx':88,'overlapPx':40}}
        gate=Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(driver,'_header_geometry',return_value=invalid):
            with self.assertRaisesRegex(driver.GuiFailure,'direct_header_system_overlap'):
                self.capture(folder,gate=gate)
            report=json.loads(Path(folder,'terminal.json').read_text())
            self.assertEqual(Path(folder,'terminal.png').read_bytes(),self.png)
            self.assertEqual(report['headerGeometry']['nativePx']['systemBottomPx'],88)
            self.assertEqual(report['errorCode'],'direct_header_system_overlap')
        gate.assert_not_called()

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
        let compact=false;globalThis.matchMedia=()=>({matches:compact});
        globalThis.window={visualViewport:{offsetLeft:0,offsetTop:0,scale:1}};
        const parent={parentElement:null,style:{overflowX:'visible',overflowY:'hidden'},
          getBoundingClientRect:()=>box(0,0,400,clip?0:700)};
        const target={parentElement:parent,textContent:'fixture@127.0.0.1:2222 · SSH 已连接',
          checkVisibility:()=>shown,getBoundingClientRect:()=>box(8,20,300,20),contains:()=>false};
        const screen={parentElement:null,checkVisibility:()=>true,
          getBoundingClientRect:()=>box(10,150,380,500)};
        globalThis.getComputedStyle=e=>e.style;
        globalThis.document={querySelector:s=>(s==='#ssh-target'||s==='#ssh-live-endpoint')?(missing?null:target):screen,
          createRange:()=>({selectNodeContents:()=>{},getClientRects:()=>[target.getBoundingClientRect()]}),
          elementFromPoint:()=>occluded?{}:target};
        const values=[eval(expression)];
        clip=true;values.push(eval(expression));clip=false;
        occluded=true;values.push(eval(expression));occluded=false;
        shown=false;values.push(eval(expression));shown=true;
        target.textContent='fixture@127.0.0.1:9999 · SSH 已连接';values.push(eval(expression));
        missing=true;values.push(eval(expression));missing=false;
        compact=true;target.textContent='fixture@127.0.0.1:2222';values.push(eval(expression));
        target.textContent='fixture@127.0.0.1:9999';values.push(eval(expression));
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
        self.assertTrue(values[6]['targetMatched']);self.assertTrue(values[6]['targetVisible'])
        self.assertFalse(values[7]['targetMatched'])

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
        header={'viewport':[160,240],'visualViewport':[0,0,1],'dpr':1,'scrollY':0,'appliedTopCss':0,
            'native':{'overlapPx':0,'systemBottomPx':23,'viewY':23,'windowTopPx':0,'statusPx':23,
                'stableStatusPx':23,'cutoutPx':0,'captionPx':0,'stableCaptionPx':0},
            'header':{'rect':[0,0,160,8],'visible':True},'title':{'rect':[5,1,30,5],'visible':True},
            'button':{'rect':[100,1,40,5],'visible':True},'sshTitle':{'rect':[8,-30,100,10],'visible':False},
            'target':{'rect':[8,12,140,24],'visible':True},'terminal':{'rect':[8,60,140,130],'visible':True},
            'xterm':{'rect':[8,60,140,130],'visible':True}}
        self.header_patch=patch.object(driver,'_header_geometry',return_value=header)
        self.header_patch.start();self.addCleanup(self.header_patch.stop)

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

class CombinedRotationFixture(RotationFixture):
    private_key='SYNTHETIC-PRIVATE-KEY'
    passphrase='SYNTHETIC-PASSPHRASE'
    screen_token=None

    def public_key_auth_evidence(self):
        return {'stage':4,'connections':4,'publicKeyAccepted':True,
                'authAttempts':1,'authSuccesses':1,'ptyRequests':1,
                'shellRequests':1,'inputBytes':4,'outputBytes':48}


class CombinedRotationBrowser(RotationBrowser):
    def __init__(self,state):
        super().__init__(state)
        state.private_key=False;state.passphrase=False;state.method=None

    def select_option(self,selector,value):
        self.actions.append(('select',selector,value))
        self.state.method=value

    def fill(self,selector,value):
        super().fill(selector,value)
        if selector=='#ssh-key': self.state.private_key=True
        if selector=='#ssh-passphrase': self.state.passphrase=True

    def click(self,selector):
        super().click(selector)
        if selector in ('#ssh-key-cancel','#ssh-probe') or (
                selector in ('#ssh-form button[type=submit]','#ssh-connect') and self.state.live):
            self.state.private_key=False;self.state.passphrase=False

    def evaluate(self,expression):
        if "'#ssh-key').value" in expression or "'#ssh-passphrase').value" in expression:
            self.expressions.append(expression)
            return self.state.private_key or self.state.passphrase
        return super().evaluate(expression)


class RotatingEncryptedKeyTests(unittest.TestCase):
    def setUp(self):
        self._wait_patcher=patch.object(driver,'wait_for',_fast_wait_for)
        self._wait_patcher.start()
        self.addCleanup(self._wait_patcher.stop)

    def test_combined_case_uses_public_key_credentials_and_publishes_fixed_facts(self):
        state=RotationState();browser=CombinedRotationBrowser(state);fixture=CombinedRotationFixture(state)
        result=driver.exercise_key_change_ui(browser,fixture,encrypted_key=True)
        self.assertEqual(state.method,'key')
        self.assertIn(('fill','#ssh-key',CombinedRotationFixture.private_key),browser.actions)
        self.assertIn(('fill','#ssh-passphrase',CombinedRotationFixture.passphrase),browser.actions)
        self.assertNotIn(('fill','#ssh-password',CombinedRotationFixture.password),browser.actions)
        self.assertEqual(result['publicKeyEvidence']['publicKeyAccepted'],True)
        self.assertEqual(result['publicKeyEvidence']['authSuccesses'],1)
        published=json.dumps(result)
        for secret in (CombinedRotationFixture.private_key,CombinedRotationFixture.passphrase,CombinedRotationFixture.password):
            self.assertNotIn(secret,published)

    def test_combined_case_rejects_missing_public_key_acceptance(self):
        state=RotationState();browser=CombinedRotationBrowser(state);fixture=CombinedRotationFixture(state)
        fixture.public_key_auth_evidence=Mock(side_effect=ValueError('invalid_public_key_auth_evidence'))
        with self.assertRaisesRegex(driver.GuiFailure,'direct_rotation_encrypted_key_evidence_invalid'):
            driver.exercise_key_change_ui(browser,fixture,encrypted_key=True)

    def test_optional_scenario_runs_only_combined_case(self):
        import tauri_encrypted_key_fixture
        self.assertTrue(hasattr(tauri_encrypted_key_fixture,'RotatingEncryptedKeyFixture'))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();apk=root/'test.apk';apk.write_bytes(b'apk')
            output=root/'evidence'
            fake_fixture=Mock();fake_fixture.snapshot.return_value={'connectionsClosed':True}
            fake_module=types.SimpleNamespace(RotatingEncryptedKeyFixture=lambda: MagicMock(
                __enter__=Mock(return_value=fake_fixture),__exit__=Mock(return_value=False)))
            rotation_result={'cleanup':{},'publicKeyEvidence':{'publicKeyAccepted':True}}
            with patch.dict(sys.modules,{'tauri_encrypted_key_fixture':fake_module}), \
                 patch.dict(os.environ,{'RUNNER_TEMP':str(root),'GITHUB_SHA':'0'*40},clear=False), \
                 patch.object(sys,'argv',['driver','--apk',str(apk),'--output',str(output),
                                         '--scenario','encrypted-key-rotation']), \
                 patch.object(driver,'run_device',return_value=rotation_result) as run_device, \
                 patch.object(driver,'probe_evidence',return_value={}):
                driver.main()
            report=json.loads((output/'manifest.json').read_text())
            self.assertEqual(report['status'],'passed')
            self.assertEqual(report['scenario'],'encrypted-key-rotation')
            self.assertEqual(report['commandPath'],'native Tauri ssh commands in Android WebView')
            manifest=(output/'manifest.json').read_text()
            for secret in (CombinedRotationFixture.private_key,CombinedRotationFixture.passphrase,CombinedRotationFixture.password):
                self.assertNotIn(secret,manifest)
            self.assertEqual(report['rotationEncryptedKey'],rotation_result)
            self.assertNotIn('encryptedKey',report)
            self.assertEqual(run_device.call_args.kwargs['key_change'],True)
            self.assertEqual(run_device.call_args.kwargs['encrypted_key'],True)

    def test_rotating_fixture_public_key_evidence_is_bounded_and_rejects_password_success(self):
        import tauri_encrypted_key_fixture as module
        fixture=object.__new__(module.RotatingEncryptedKeyFixture)
        events=[{'authAttempts':0,'authSuccesses':0,'ptyRequests':0,'shellRequests':0,
                 'inputBytes':0,'outputBytes':0} for _ in range(3)]
        final={'authAttempts':1,'authSuccesses':1,'ptyRequests':1,'shellRequests':1,
               'inputBytes':4,'outputBytes':48,'publicKeyAccepted':True}
        with patch.object(fixture,'rotation_evidence',return_value={'stage':4,'connections':4}), \
             patch.object(fixture,'snapshot',return_value={'connectionEvents':[*events,final]}):
            evidence=fixture.public_key_auth_evidence()
        self.assertEqual(evidence['publicKeyAccepted'],True)
        self.assertEqual(set(evidence),{'stage','connections','publicKeyAccepted','authAttempts',
            'authSuccesses','ptyRequests','shellRequests','inputBytes','outputBytes'})
        with patch.object(fixture,'rotation_evidence',return_value={'stage':4,'connections':4}), \
             patch.object(fixture,'snapshot',return_value={'connectionEvents':[*events,{**final,'publicKeyAccepted':False}]}):
            with self.assertRaises(ValueError): fixture.public_key_auth_evidence()



if __name__=='__main__': unittest.main()
