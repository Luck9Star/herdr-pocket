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

    def test_counter_context_separates_a_reset_page_from_a_silent_app_and_a_js_error(self):
        healthy=android._public_counter_context({'readyState':'complete','internals':True,'invokeType':'function',
            'url':'http://tauri.localhost/','present':True,'count':3,
            'tallyKeys':['host_list','network_list'],'clickSeen':3,'lastClickTarget':'host-return-home',
            'errorCount':2,'lastJsError':'sync:'+'x'*300})
        self.assertEqual((healthy['present'],healthy['count']), (True,3))
        self.assertEqual(healthy['tallyKeys'],['host_list','network_list'])
        self.assertEqual((healthy['clickSeen'],healthy['lastClickTarget'],healthy['errorCount']),
                         (3,'host-return-home',2))
        self.assertEqual(healthy['lastJsError'],'sync:'+'x'*195)
        reset=android._public_counter_context({})
        self.assertEqual((reset['present'],reset['count'],reset['tallyKeys'],reset['lastJsError']),(False,0,[],None))
        self.assertEqual((reset['clickSeen'],reset['lastClickTarget'],reset['errorCount']),(0,None,0))
        hostile=android._public_counter_context({'present':'yes','count':-5,'tallyKeys':[1,'ok'],
            'lastJsError':object(),'clickSeen':-10,'lastClickTarget':123,'errorCount':-2})
        self.assertEqual((hostile['present'],hostile['count'],hostile['tallyKeys'],hostile['lastJsError']),(False,0,[],None))
        self.assertEqual((hostile['clickSeen'],hostile['lastClickTarget'],hostile['errorCount']),(0,None,0))
        overflowing=android._public_counter_context({'present':True,'count':2,'tallyKeys':['k'*80,'k'*80],
            'clickSeen':1001,'lastClickTarget':'a'*80,'errorCount':True})
        self.assertEqual(overflowing['tallyKeys'],['k'*64,'k'*64])
        self.assertEqual((overflowing['clickSeen'],overflowing['lastClickTarget'],overflowing['errorCount']),
                         (1000,'a'*64,0))
        invalid=android._public_counter_context({'clickSeen':True,'lastClickTarget':[],'errorCount':3.5})
        self.assertEqual((invalid['clickSeen'],invalid['lastClickTarget'],invalid['errorCount']),(0,None,0))

    def test_a_vanished_counter_fails_fast_instead_of_timing_out_as_no_ipc(self):
        class Busy:
            def __init__(self,code):self.code=code
            def invoke_counter(self):raise android.GuiFailure(self.code)
        for code in ('android_board_search_counter_read_invalid','android_cdp_transport_failed','android_cdp_command_failed'):
            with self.subTest(code=code):
                with self.assertRaises(android.GuiFailure) as failure:
                    android._counter_count_reached(Busy(code),1)
                self.assertEqual(str(failure.exception),code)
        self.assertFalse(android._counter_count_reached(Busy('android_control_operation_failed'),1))

    def test_unreadable_counter_page_context_retains_unknown_fields(self):
        view=object.__new__(android.AndroidWebView);view.evaluate=Mock(return_value=None)
        context=view._counter_page_context()
        self.assertEqual((context['present'],context['count'],context['clickSeen']),(False,0,0))

    @unittest.skipUnless(shutil.which('node'),'Node is required to execute the injected counter probes')
    def test_counter_hooks_capture_clicks_errors_and_do_not_accumulate_on_reinstall(self):
        view=object.__new__(android.AndroidWebView)
        view.evaluate=Mock(side_effect=[True,{},True])
        view.install_invoke_counter();view._counter_page_context();view.remove_invoke_counter()
        install,context,remove=[call.args[0] for call in view.evaluate.call_args_list]
        # The fixture mirrors tauri 2.x exactly: internals.invoke/ipc/postMessage are
        # value-only defineProperty (non-writable, non-configurable) and window.ipc is
        # the plain Java-bridge property. A plain-object internals would fake-green.
        script=r'''
const [install,context,remove]=JSON.parse(process.argv[1]);
const events={},clicks=[],nativeSink=[];
const document={readyState:'complete',addEventListener:(type,fn,capture)=>clicks.push({type,fn,capture}),
  removeEventListener:(type,fn,capture)=>{const i=clicks.findIndex(v=>v.type===type&&v.fn===fn&&v.capture===capture);if(i>=0)clicks.splice(i,1)}};
const bridge={postMessage:function(message){nativeSink.push(message);return 'ok'}};
const window={ipc:bridge,addEventListener:(name,fn)=>(events[name]??=[]).push(fn)};
const internals={};
Object.defineProperty(window,'__TAURI_INTERNALS__',{value:internals});
const frozen=(name,value)=>Object.defineProperty(internals,name,{value});
frozen('postMessage',function(message){window.ipc.postMessage(JSON.stringify(message))});
frozen('ipc',function(message){window.__TAURI_INTERNALS__.postMessage(message)});
frozen('invoke',function(cmd,args,options){window.__TAURI_INTERNALS__.ipc({cmd,args,options});return 'ok'});
const frozenInvoke=internals.invoke;
const run=expr=>new Function('window','document','location','return '+expr)(window,document,{href:'http://tauri.localhost/'});
const fire=(type,value)=>{for(const fn of events[type]||[])fn(value)};
const click=target=>{for(const hook of clicks)hook.fn({target})};
run(install);run(install);click({id:'host-return-home'});
const result=window.__TAURI_INTERNALS__.invoke('host_list',{fixture:1},{token:2});
const invokeIdentity=internals.invoke===frozenInvoke;
const replaced=window.ipc!==bridge;
fire('error',{message:'bad handler'});const sync=run(context);
fire('unhandledrejection',{reason:{message:'failed promise'}});const asyncError=run(context);
click({});const unknown=run(context);
run(remove);const removed={listeners:clicks.length,marker:!!window.__herdrClickHook,
  restored:window.ipc===bridge,deleted:!!window.__herdrIpcBridge};
run(install);click({id:'again'});const reinstalled=run(context);
process.stdout.write(JSON.stringify({sync,asyncError,unknown,removed,reinstalled,capture:clicks[0]?.capture,
  nativeSink:nativeSink.map(m=>JSON.parse(m)),result,invokeIdentity,replaced}));
'''
        result=subprocess.run([shutil.which('node'),'-e',script,json.dumps([install,context,remove])],
                              capture_output=True,text=True,timeout=10,check=True)
        value=json.loads(result.stdout)
        self.assertEqual((value['sync']['clickSeen'],value['sync']['lastClickTarget']), (1,'host-return-home'))
        self.assertEqual((value['sync']['count'],value['sync']['tallyKeys']),(1,['host_list']))
        self.assertTrue(value['invokeIdentity'])  # frozen invoke was never patched
        self.assertTrue(value['replaced'])
        self.assertEqual(value['nativeSink'],[{'cmd':'host_list','args':{'fixture':1},'options':{'token':2}}])
        self.assertEqual(value['result'],'ok')
        self.assertEqual((value['sync']['errorCount'],value['sync']['lastJsError']), (1,'sync:bad handler'))
        self.assertEqual((value['asyncError']['errorCount'],value['asyncError']['lastJsError']),
                         (2,'async:failed promise'))
        self.assertEqual((value['unknown']['clickSeen'],value['unknown']['lastClickTarget']),(2,'?'))
        self.assertEqual(value['removed'],{'listeners':0,'marker':False,'restored':True,'deleted':False})
        self.assertTrue(value['capture'])
        self.assertEqual((value['reinstalled']['clickSeen'],value['reinstalled']['lastClickTarget']), (1,'again'))

    def _board_browser(self):
        browser=Mock()
        context={'present':True,'count':2,'tallyKeys':['host_list','host_update'],
                 'clickSeen':1,'lastClickTarget':'host-return-home','errorCount':0}
        browser._counter_page_context.return_value=context.copy()
        def counter_failure(code):
            failure=android.GuiFailure(code);failure.counter_context=context.copy();return failure
        browser._counter_failure.side_effect=counter_failure
        browser.evaluate.return_value=True
        browser.invoke_counter.return_value={'count':2,'tally':{'host_list':1}}
        browser.read.return_value=' 本机资料不可用；\n 仍可打开手动连接表单。 '
        return browser

    def test_board_gate_requires_a_real_host_or_network_command(self):
        for tally,expected in (({'unrelated':3},'android_board_search_counter_no_ipc'),
                               ({'host_list':0},'android_board_search_counter_no_ipc'),
                               ({'host_list':1},'android_board_search_count_mismatch'),
                               ({'network_list':1},'android_board_search_count_mismatch')):
            with self.subTest(tally=tally):
                browser=self._board_browser()
                browser.invoke_counter.return_value={'count':3,'tally':tally}
                browser.fill.side_effect=android.GuiFailure('android_board_search_count_mismatch')
                with patch.object(android,'_settled_invoke_count',return_value=3),self.assertRaises(android.GuiFailure) as failure:
                    android.exercise_board_search(browser,approval(),CONFIG)
                self.assertEqual(str(failure.exception),expected)
                self.assertEqual(failure.exception.home_status,'本机资料不可用； 仍可打开手动连接表单。')
                self.assertEqual(failure.exception.counter_click_context['after']['clickSeen'],1)
                self.assertEqual(failure.exception.counter_context['tallyKeys'],['host_list','host_update'])
                browser.remove_invoke_counter.assert_called_once()

    def test_board_counter_fatal_errors_keep_context_and_cleanup_cannot_mask_them(self):
        for code in ('android_board_search_counter_read_invalid','android_cdp_transport_failed',
                     'android_cdp_command_failed'):
            with self.subTest(code=code):
                browser=self._board_browser()
                original=android.GuiFailure(code)
                original.counter_context={'present':False,'count':0}
                browser.invoke_counter.side_effect=original
                browser.remove_invoke_counter.side_effect=android.GuiFailure('android_cdp_transport_failed')
                with self.assertRaises(android.GuiFailure) as failure:
                    android.exercise_board_search(browser,approval(),CONFIG)
                self.assertIs(failure.exception,original)
                self.assertEqual(failure.exception.counter_context,{'present':False,'count':0})
                self.assertIn('before',failure.exception.counter_click_context)
                self.assertEqual(failure.exception.home_status,'本机资料不可用； 仍可打开手动连接表单。')

    def test_board_failures_all_keep_counter_and_click_context(self):
        for code in ('android_board_search_count_mismatch','android_board_search_state_invalid',
                     'android_board_search_history_missing','android_board_search_clear_missing',
                     'android_board_search_reset_missing','android_board_search_native_call'):
            with self.subTest(code=code):
                browser=self._board_browser();browser.fill.side_effect=android.GuiFailure(code)
                with patch.object(android,'_settled_invoke_count',return_value=2),self.assertRaises(android.GuiFailure) as failure:
                    android.exercise_board_search(browser,approval(),CONFIG)
                self.assertEqual(str(failure.exception),code)
                self.assertEqual(failure.exception.counter_context['tallyKeys'],['host_list','host_update'])
                self.assertEqual(set(failure.exception.counter_click_context),{'before','after'})

    def test_board_install_failure_retains_original_diagnostic_during_cleanup(self):
        browser=self._board_browser()
        original=android.GuiFailure('android_board_search_counter_install_failed')
        original.counter_context={'present':True,'count':0}
        browser.install_invoke_counter.side_effect=original
        browser.remove_invoke_counter.side_effect=android.GuiFailure('android_cdp_command_failed')
        browser.read.side_effect=android.GuiFailure('android_cdp_transport_failed')
        with self.assertRaises(android.GuiFailure) as failure:
            android.exercise_board_search(browser,approval(),CONFIG)
        self.assertIs(failure.exception,original)
        self.assertEqual(failure.exception.counter_context,{'present':True,'count':0})
        self.assertEqual(failure.exception.counter_click_context,{'before':{},'after':{}})
        browser.remove_invoke_counter.assert_called_once()

    def _board_snapshots(self):
        fragment=CONFIG['session'][:8]
        base={'totalCards':1,'visibleCards':1,'query':fragment,'state':'all',
              'clearHidden':False,'resetHidden':True,'statusHidden':False,
              'statusText':'显示 1 / 1 台主机','currentLabel':'当前待处理（0）',
              'historyLabel':'上次受阻，待核查（1）','sessionVisible':True,
              'blockedRows':[['w2:p1/term_aaa','w3:p1/term_bbb']]}
        return [base,{**base,'state':'current','visibleCards':0,'statusText':'显示 0 / 1 台主机'},
            {**base,'state':'history'},{**base,'state':'history','query':'','clearHidden':True},
            {**base,'state':'history','query':'no-such-host-'+fragment,'visibleCards':0,
             'resetHidden':False,'statusText':'没有匹配的主机 · 显示 0 / 1 台主机'},
            {**base,'state':'all','query':'','statusHidden':True,'statusText':''}]

    def test_real_native_call_failure_reports_the_detected_command(self):
        browser=self._board_browser()
        browser.invoke_counter.side_effect=[{'count':1,'tally':{'host_list':1}},
            {'count':2,'tally':{'host_list':1,'host_update':1}}]
        with patch.object(android,'_settled_invoke_count',return_value=1), \
             patch.object(android,'_board_snapshot',side_effect=self._board_snapshots()),self.assertRaises(android.GuiFailure) as failure:
            android.exercise_board_search(browser,approval(),CONFIG)
        self.assertEqual(str(failure.exception),'android_board_search_native_call')
        self.assertIn('host_update',failure.exception.counter_context['tallyKeys'])
        self.assertEqual(failure.exception.counter_click_context['after']['lastClickTarget'],'host-return-home')

    def test_success_removes_counter_before_restore_and_restore_failures_keep_context(self):
        for fails in (False,True):
            with self.subTest(fails=fails):
                browser=self._board_browser()
                browser.invoke_counter.return_value={'count':1,'tally':{'host_list':1}}
                def restore(*_):
                    browser.remove_invoke_counter.assert_called_once()
                    if fails:raise android.GuiFailure('android_blocked_original_form_missing')
                with patch.object(android,'_settled_invoke_count',return_value=1), \
                     patch.object(android,'_board_snapshot',side_effect=self._board_snapshots()), \
                     patch.object(android,'_restore_paired_form',side_effect=restore):
                    if fails:
                        with self.assertRaises(android.GuiFailure) as failure:
                            android.exercise_board_search(browser,approval(),CONFIG)
                        self.assertEqual(failure.exception.counter_context['tallyKeys'],['host_list','host_update'])
                        self.assertEqual(failure.exception.counter_click_context['after']['clickSeen'],1)
                    else:
                        result=android.exercise_board_search(browser,approval(),CONFIG)
                        self.assertEqual((result['nativeCallsAdded'],result['historyRows']),(0,2))
                browser.remove_invoke_counter.assert_called_once()

    def test_progress_publishes_bounded_home_status_and_counter_context(self):
        progress=android.AndroidProgress(types.SimpleNamespace(output=None))
        failure=android.GuiFailure('android_control_operation_failed')
        failure.home_status='  本机资料不可用；\n  仍可打开手动连接表单。  '+('x'*150)
        failure.counter_context={'clickSeen':1001,'lastClickTarget':'target','errorCount':1,'lastJsError':'async:failed'}
        failure.counter_click_context={'before':{'clickSeen':0},'after':{'clickSeen':1}}
        progress.fail(failure)
        self.assertEqual(progress.data['errorCode'],'android_control_operation_failed')
        self.assertEqual(progress.data['homeStatus'],('本机资料不可用； 仍可打开手动连接表单。 '+('x'*150))[:120])
        self.assertEqual(progress.data['counterContext']['clickSeen'],1000)
        self.assertEqual(progress.data['counterContext']['lastJsError'],'async:failed')
        self.assertEqual(progress.data['counterClickContext']['after']['clickSeen'],1)

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
                     'android_board_search_counter_install_failed','android_board_search_counter_read_invalid',
                     'android_board_search_counter_no_ipc','android_board_search_counter_unsettle_timeout',
                     'android_home_not_visible','android_cdp_transport_failed','android_cdp_command_failed',
                     'android_control_operation_failed',
                     'android_select_option_missing','android_select_option_failed','android_device_impact_entry_missing',
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
