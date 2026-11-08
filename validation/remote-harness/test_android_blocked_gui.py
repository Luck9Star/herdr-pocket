"""Isolated stock phone blocked-target driver contracts; no ADB, SSH or keys."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
stub=types.ModuleType('paired_gui')
stub.GuiFailure=type('GuiFailure',(Exception,),{})
def wait(check,code,**_):
    for _ in range(3):
        value=check()
        if value:
            return value
    raise stub.GuiFailure(code)
stub.wait_for=wait
spec=importlib.util.spec_from_file_location('blocked_android_gui',HERE/'android_gui.py')
android=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'paired_gui':stub}):
    spec.loader.exec_module(android)

TARGETS=[{'paneId':'w2:p1','terminalId':'term_aaa'},{'paneId':'w3:p1','terminalId':'term_bbb'}]
CONFIG={'host':'127.0.0.1','port':2222,'username':'fixture','session':'pocket-probe','herdrPath':'/owned/herdr','socketPath':'/owned/herdr.sock','expectedHostKey':'ssh-ed25519 PUBLIC'}
RECEIPT={**TARGETS[1],'listedRows':2,'reviewRequired':True,'observing':True,'markerMatched':True,'otherMarkerAbsent':True}

class Browser:
    def __init__(self,*,measurement=None,same_label=True,review=True):
        self.actions=[];self.measurement=measurement;self.same_label=same_label;self.review=review;self.expressions=[]
    def evaluate(self,expression):
        self.expressions.append(expression)
        if 'const expected=' in expression and 'sameLabel:' in expression:
            return {'selector':'#host-list > .saved-host-card:nth-child(1)','listedRows':2,'sameLabel':self.same_label}
        if 'checks.length===1' in expression:
            return self.review
        if 'const paneId=title.at(-2)' in expression:
            return self.measurement if self.measurement is not None else {key:RECEIPT[key] for key in ('paneId','terminalId','observing','markerMatched','otherMarkerAbsent')}
        if "document.querySelector('#remote-review').checked" in expression:
            return False
        if "?.checked===true" in expression or "document.querySelector('#tab-workspace').hidden" in expression or "document.querySelector('#host-restore-panel').hidden" in expression or "!document.querySelector('#host-home').hidden" in expression:
            return True
        raise AssertionError('unexpected_expression')
    def click(self,selector):self.actions.append(('click',selector))
    def click_named(self,scope,label):self.actions.append(('named',scope,label))
    def read(self,selector,prop='textContent'):
        if selector=='#pair-request':return 'PUBLIC REQUEST'
        fields={'#remote-'+field:str(CONFIG[key]) for field,key in [('host','host'),('port','port'),('user','username'),('session','session'),('herdr','herdrPath'),('socket','socketPath'),('pin','expectedHostKey')]}
        return fields[selector]

def approval():
    return types.SimpleNamespace(blocked_targets=TARGETS,verify_blocked_targets=Mock(return_value=TARGETS),verify_ssh=Mock())

class AndroidBlockedTests(unittest.TestCase):
    def test_primary_pane_selector_never_chooses_first_of_three_or_injects_css(self):
        self.assertEqual(android.primary_pane_selector('w1:p1'),'#remote-panes button[data-pane-id="w1:p1"]')
        for value in ('',None,'p"],button','p\\x','x'*129):
            with self.subTest(value=value),self.assertRaises(android.GuiFailure):android.primary_pane_selector(value)
        source=(HERE/'android_gui.py').read_text()
        flow=source[source.index('def run_android('):]
        self.assertIn("selector = primary_pane_selector(config['paneId'])",flow)
        self.assertNotIn("selector = '#remote-panes button'",flow)

    def test_real_entry_order_keeps_explicit_review_and_returns_only_checked_b_evidence(self):
        browser=Browser();host=approval()
        with patch.object(android,'checked_receipt',wraps=android.checked_receipt) as checked:
            actual=android.exercise_blocked_target(browser,host,CONFIG)
        self.assertEqual(actual,RECEIPT);checked.assert_called_once_with(RECEIPT,TARGETS)
        self.assertEqual(host.verify_blocked_targets.call_count,2);host.verify_ssh.assert_called_once_with(b'')
        self.assertEqual(browser.actions,[('click','#host-return-home'),
            ('click','#host-list > .saved-host-card:nth-child(1) .blocked-target-list button[data-blocked-target="w3:p1/term_bbb"]'),
            ('click','#view-content input[type=checkbox]'),('named','#view-content','连接'),('named','#view-content','关闭此标签'),
            ('click','#host-return-home'),('named','#host-list > .saved-host-card:nth-child(1) .saved-host-actions','打开'),
            ('click','#host-restore-review'),('click','#host-restore')])
        joined='\n'.join(browser.expressions)
        for forbidden in ('.click(','.onclick','__TAURI','remote_tab_observe','dispatchEvent','POCKET-BLOCKED-A frame'):
            self.assertNotIn(forbidden,joined)
        self.assertNotIn('PUBLIC REQUEST',json.dumps(actual))

    def test_wrong_receipt_labels_review_or_changed_host_snapshot_stop_before_revoke(self):
        for browser in (Browser(same_label=False),Browser(review=False),Browser(measurement={**RECEIPT,'terminalId':'term_aaa'}),Browser(measurement={**RECEIPT,'observing':False}),Browser(measurement={**RECEIPT,'otherMarkerAbsent':False})):
            host=approval()
            with self.subTest(browser=browser),self.assertRaises(android.GuiFailure):android.exercise_blocked_target(browser,host,CONFIG)
            self.assertFalse(any(action[-1]=='打开' for action in browser.actions));host.verify_ssh.assert_not_called()
        host=approval();host.verify_blocked_targets.side_effect=[TARGETS,list(reversed(TARGETS))]
        with self.assertRaises(android.GuiFailure):android.exercise_blocked_target(Browser(),host,CONFIG)
        host.verify_ssh.assert_not_called()

    def test_guarded_run_skips_new_stock_steps_and_new_receipt_field(self):
        source=(HERE/'android_gui.py').read_text();flow=source[source.index('def run_android('):]
        self.assertRegex(flow,r"if not guarded:\s+progress.phase\('blocked_target_entry'\)\s+blocked_evidence=exercise_blocked_target")
        self.assertIn("**({'blockedTargetEvidence':blocked_evidence} if blocked_evidence is not None else {})",flow)

    def test_visible_named_control_uses_real_cdp_pointer_events(self):
        view=object.__new__(android.AndroidWebView);view.evaluate=Mock(return_value={'x':123,'y':234});view.call=Mock()
        view.click_named('#view-content','连接')
        self.assertEqual([call.args for call in view.call.call_args_list],[('Input.dispatchMouseEvent',{'type':'mousePressed','x':123,'y':234,'button':'left','clickCount':1}),('Input.dispatchMouseEvent',{'type':'mouseReleased','x':123,'y':234,'button':'left','clickCount':1})])
        expression=view.evaluate.call_args.args[0]
        self.assertIn("buttons.length!==1",expression);self.assertIn("e.contains(document.elementFromPoint(x,y))",expression)
        self.assertNotIn('.click()',expression)

    @unittest.skipUnless(shutil.which('node'),'Node is required for the exact DOM measurement expression')
    def test_actual_measurement_expression_requires_complete_b_row_exact_bound_pair_and_observe(self):
        browser=Browser();android.exercise_blocked_target(browser,approval(),CONFIG)
        expression=next(e for e in browser.expressions if 'const paneId=title.at(-2)' in e)
        script=r'''
const expression=JSON.parse(process.argv[1]);
const base={paneId:'w3:p1',terminalId:'term_bbb',lines:['POCKET-BLOCKED-B frame 42'],verified:true,mode:'观察模式；输入已关闭。',readOnly:true,inputmode:'none',focused:false,hidden:false};
const cases=[base,...[
 {paneId:'w2:p1'},{terminalId:'term_aaa'},{lines:['prefix POCKET-BLOCKED-B frame 42']},{lines:['POCKET-BLOCKED-B frame 42 suffix']},
 {lines:['POCKET-BLOCKED-A frame 42']},{lines:['POCKET-BLOCKED-B frame 42','POCKET-BLOCKED-A frame 41']},
 {verified:false},{mode:'逐键输入已启用；每次输入单独发送。'},{readOnly:false},{inputmode:'text'},{focused:true},{hidden:true}
].map(change=>({...base,...change}))];
const results=cases.map(value=>{
 const area={readOnly:value.readOnly,getAttribute:()=>value.inputmode};
 const term={closest:()=>value.hidden?{}:null,getClientRects:()=>[{}],querySelectorAll:()=>value.lines.map(textContent=>({textContent})),querySelector:()=>area};
 const view={children:[{tagName:'P',textContent:`same host · ${value.paneId} · ${value.terminalId}`}],querySelector:selector=>selector==='.terminal-host'?term:selector==='p[aria-live=polite]'?{textContent:value.mode}:selector==='[data-connection-stage=terminal]'?{dataset:{stageState:value.verified?'verified':'pending'}}:null};
 return new Function('document','return '+expression)({querySelector:()=>view,activeElement:value.focused?area:null});
});process.stdout.write(JSON.stringify(results));
'''
        result=subprocess.run([shutil.which('node'),'-e',script,json.dumps(expression)],capture_output=True,text=True,timeout=10,check=True)
        values=json.loads(result.stdout)
        self.assertEqual(values[0],{key:RECEIPT[key] for key in ('paneId','terminalId','observing','markerMatched','otherMarkerAbsent')})
        self.assertEqual(values[1:],[None]*12)

class AndroidBoardAndDeviceGuards(unittest.TestCase):
    """Board search and shared device review contracts; no host identity or device write leaves the AVD."""

    def test_board_counters_read_the_visible_status_and_both_task_state_buckets(self):
        snapshot={'statusText':'显示 1 / 2 台主机','currentLabel':'当前待处理（0）','historyLabel':'上次受阻，待核查（1）'}
        self.assertEqual(android._board_counts(snapshot),(1,2,0,1))
        empty={'statusText':'没有匹配的主机 · 显示 0 / 2 台主机','currentLabel':'当前待处理（0）',
               'historyLabel':'上次受阻，待核查（1）'}
        self.assertEqual(android._board_counts(empty),(0,2,0,1))
        for changes in ({'statusText':'显示 1 台主机'},{'currentLabel':'当前待处理 0'},{'historyLabel':'上次受阻'}):
            with self.subTest(changes=changes),self.assertRaises(android.GuiFailure):
                android._board_counts({**snapshot,**changes})

    def test_shared_device_status_paths_are_classified_without_a_readable_device_state(self):
        self.assertEqual(android._device_class(
            {'status':'设备状态未知或共享设备能力不可用；受影响范围已列出，不能执行设备操作。','pending':False}),'unknown')
        self.assertEqual(android._device_class(
            {'status':'网络目录或主机清单不可用，受影响范围未知；不能执行设备操作。','pending':False}),'catalog_blocked')
        self.assertEqual(android._device_class(
            {'status':'操作已确认；请核对当前设备状态。','pending':True}),'pending')
        self.assertIsNone(android._device_class(
            {'status':'操作已确认；请核对当前设备状态。','pending':False}))

    def test_new_phases_are_registered_with_their_bounded_failure_codes(self):
        self.assertIn('board_search',android.AndroidProgress.PHASES)
        self.assertIn('device_impact_review',android.AndroidProgress.PHASES)
        self.assertIn('boardSearchVerified',android.AndroidProgress.COMPLETED)
        self.assertIn('deviceImpactReviewed',android.AndroidProgress.COMPLETED)
        for code in ('android_board_search_state_invalid','android_board_search_count_mismatch',
                     'android_board_search_history_missing','android_board_search_native_call',
                     'android_board_search_reset_missing','android_board_search_clear_missing',
                     'android_board_search_counter_unavailable','android_select_option_missing',
                     'android_select_option_failed','android_device_impact_entry_missing',
                     'android_device_impact_status_invalid','android_device_impact_action_enabled',
                     'android_device_impact_reread_invalid','android_device_impact_entry_lost',
                     'android_device_impact_write_invoked'):
            self.assertIn(code,android.AndroidProgress.ERROR_CODES)

    def test_the_review_only_reads_and_never_writes_a_device_identity(self):
        self.assertIn('zerotier_device_write',android.DEVICE_WRITE_COMMANDS)
        self.assertIn('network_identity_write',android.DEVICE_WRITE_COMMANDS)
        for read_only in ('network_list','host_list','zerotier_device_status'):
            self.assertNotIn(read_only,android.DEVICE_WRITE_COMMANDS)
        source=(HERE/'android_gui.py').read_text()
        self.assertIn("progress.phase('device_impact_review')",source)
        self.assertIn("progress.mark('deviceImpactReviewed')",source)
        self.assertIn("**({'boardSearchEvidence':board_evidence} if board_evidence is not None else {})",source)
        self.assertIn("**({'deviceImpactEvidence':device_evidence} if device_evidence is not None else {})",source)


if __name__=='__main__':unittest.main()
