import unittest
import subprocess
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import tauri_android_dual_overlay as dual


class DualEvidenceTests(unittest.TestCase):
    def test_same_single_approved_session_and_exact_bytes_required(self):
        sample = {'acceptedSessions':1, 'newSessions':0, 'soleApprovedSession':True,
                  'inputAttributionAmbiguous':False, 'exactBytes':True, 'capturedBytes':5,
                  'sessions':[{'ordinal':1, 'approvedDevice':True, 'active':True}]}
        self.assertTrue(dual.checked_audit(sample, 5, ordinal=1, sessions_count=1, active=True))
        for patch in ({'acceptedSessions':2}, {'newSessions':1}, {'exactBytes':False},
                      {'capturedBytes':4},
                      {'sessions':[{'ordinal':2,'approvedDevice':True,'active':True}]}):
            with self.subTest(patch=patch):
                self.assertFalse(dual.checked_audit({**sample, **patch}, 5, ordinal=1, sessions_count=1, active=True))
        self.assertFalse(dual.checked_audit(sample, 5, ordinal=1, sessions_count=1, active=False))
        history = {**sample, 'acceptedSessions':2, 'soleApprovedSession':False,
                   'inputAttributionAmbiguous':True, 'sessions':[
                       {'ordinal':1,'approvedDevice':True,'active':False},
                       {'ordinal':2,'approvedDevice':True,'active':True}]}
        self.assertTrue(dual.checked_audit(history, 5, ordinal=2, sessions_count=2, active=True))
        self.assertFalse(dual.checked_audit(history, 5, ordinal=1, sessions_count=2, active=True))

    def test_removed_tab_never_types_into_surviving_session(self):
        browser = Mock()
        with patch.object(dual,'find_tab',return_value=None):
            self.assertEqual(dual.guard_stale_target(browser,'ts'), 'removed_tab_unreachable')
        browser.call.assert_not_called()
        with patch.object(dual,'find_tab',return_value='#old'), patch.object(dual,'select_tab'):
            browser.evaluate.return_value = True
            with self.assertRaises(dual.GuiFailure): dual.guard_stale_target(browser,'ts')
            browser.call.assert_not_called()
            browser.evaluate.return_value = False
            self.assertEqual(dual.guard_stale_target(browser,'ts'), 'retained_tab_disabled_keyboard_tested')
            browser.call.assert_called_once()

    def test_ack_matches_one_rendered_row_with_nonbreaking_spaces(self):
        expr = dual.rendered_marker_expression('Synthetic TS ACK ONE')
        script = """const text=JSON.parse(process.argv[1]);
          global.document={querySelectorAll:()=>text.map(x=>({textContent:x,getClientRects:()=>[{}]}))};
          process.stdout.write(String(eval(process.argv[2])));"""
        def matches(rows):
            return subprocess.check_output(['node','-e',script,json.dumps(rows),expr],text=True)=='true'
        self.assertTrue(matches(['Synthetic\u00a0TS\u00a0ACK\u00a0ONE']))
        self.assertFalse(matches(['Synthetic TS ACK', ' ONE']))
        self.assertFalse(matches(['Synthetic ET ACK ONE']))

    def test_system_confirmation_requires_matching_visible_message_and_button(self):
        xml = ('<?xml version="1.0"?><hierarchy><node text="创建本机加密设备状态"/>'
               '<node text="确定" enabled="true" bounds="[10,20][110,80]"/></hierarchy>')
        diagnostic = {}
        with patch.object(dual,'adb',side_effect=['',xml,'','']) as adb:
            self.assertTrue(dual.native_dialog_click('创建本机加密设备状态',{'确定'},diagnostic=diagnostic))
            adb.assert_any_call('shell','input','tap','60','50')
        self.assertTrue(diagnostic['expectedSeen'] and diagnostic['uniqueButton'] and diagnostic['clicked'])

    def test_cdp_confirmation_requires_matching_origin_and_real_native_tap(self):
        browser = dual.ConfirmingWebView.__new__(dual.ConfirmingWebView)
        browser.sequence=0;browser.expectedConfirmation='创建本机加密设备状态'
        browser.confirmationObserved=False;browser.confirmationHistory=[];browser.pageOrigin=('http','tauri.localhost',None)
        browser.ws=Mock()
        event={'method':'Page.javascriptDialogOpening','params':{'url':'http://tauri.localhost/',
               'type':'confirm','message':'创建本机加密设备状态？','hasBrowserHandler':True}}
        browser.ws.recv.side_effect=[json.dumps(event),json.dumps({'id':1,'result':{}})]
        def visible(_expected,_buttons,**kwargs):
            kwargs['diagnostic'].update(xmlParsed=True,expectedSeen=True,uniqueButton=True,clicked=True)
            return True
        with patch.object(dual,'native_dialog_click',side_effect=visible):
            browser.call('Input.dispatchMouseEvent',{})
        self.assertTrue(browser.confirmationObserved)
        self.assertTrue(browser.confirmDiagnostic['nativeClicked'])
        self.assertEqual(browser.ws.send.call_count,1)  # No JS/IPC override.
        browser.sequence=0;browser.confirmationObserved=False
        event['params']['url']='https://elsewhere.invalid/'
        browser.ws.recv.side_effect=[json.dumps(event)]
        with self.assertRaises(dual.GuiFailure): browser.call('Input.dispatchMouseEvent',{})

    def test_ordinary_tree_requires_owned_webview_not_brand_text(self):
        root=ET.fromstring('<hierarchy><node package="other" class="android.webkit.WebView"/>'
                           '<node package="dev.herdrpocket.tauriprobe" class="android.webkit.WebView"/>'
                           '<node package="dev.herdrpocket.tauriprobe" class="android.view.View"/></hierarchy>')
        self.assertTrue(dual.ordinary_native_tree(list(root.iter('node')))['ownedWebView'])
        self.assertFalse(dual.ordinary_native_tree([root[0]])['ownedWebView'])
        self.assertFalse(dual.ordinary_native_tree([])['ownedWebView'])

    def test_native_tree_failures_are_fixed_codes_and_always_clean_dump(self):
        for xml,code in [('private text','dual_native_ui_xml_missing'),
                         ('<?xml version="1.0"?><hierarchy><node></hierarchy>','dual_native_ui_xml_invalid')]:
            with self.subTest(code=code),patch.object(dual,'adb',side_effect=['dumped',xml,'']) as adb:
                with self.assertRaisesRegex(dual.GuiFailure,'^'+code+'$'):dual.native_ui_nodes()
                self.assertEqual(adb.call_args.args,('shell','rm','-f','/data/local/tmp/herdr-dual-ui.xml'))
        for outputs,code in [([dual.GuiFailure('private dump error'),''],'dual_native_ui_dump_failed'),
                             (['dumped',dual.GuiFailure('private read error'),''],'dual_native_ui_read_failed')]:
            with self.subTest(code=code),patch.object(dual,'adb',side_effect=outputs):
                with self.assertRaisesRegex(dual.GuiFailure,'^'+code+'$'):dual.native_ui_nodes()

    def test_ordinary_tree_readiness_retries_reads_without_relaxing_owned_tree(self):
        nodes=[ET.Element('node',{'package':dual.PACKAGE,'class':'android.webkit.WebView'})]
        nodes += [ET.Element('node'),ET.Element('node')]
        report={}
        def poll(probe,code,**kwargs):
            for _ in range(3):
                value=probe()
                if value:return value
            raise dual.GuiFailure(code)
        with patch.object(dual,'wait_for',side_effect=poll),patch.object(dual,'native_ui_nodes',
                side_effect=[dual.GuiFailure('dual_native_ui_xml_invalid'),nodes[:1],nodes]) as read:
            tree=dual.wait_for_ordinary_tree(report)
        self.assertEqual(read.call_count,3)
        self.assertTrue(tree['ownedWebView']);self.assertEqual(tree['nodeCount'],3)
        self.assertEqual(report['nativeTreeObservation'],{'attempts':3,'lastError':None})

    def test_unowned_tree_and_dump_cleanup_failure_remain_failures(self):
        nodes=[ET.Element('node',{'package':'unrelated','class':'android.webkit.WebView'}) for _ in range(3)]
        def once(probe,code,**kwargs):
            value=probe()
            if value:return value
            raise dual.GuiFailure(code)
        report={}
        with patch.object(dual,'wait_for',side_effect=once),patch.object(dual,'native_ui_nodes',return_value=nodes):
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_native_ui_tree_not_ready$'):
                dual.wait_for_ordinary_tree(report)
        self.assertFalse(report['ordinaryNativeTree']['ownedWebView'])
        self.assertEqual(report['nativeTreeObservation']['lastError'],'dual_native_ui_tree_incomplete')
        with patch.object(dual,'wait_for',side_effect=once),patch.object(dual,'native_ui_nodes',
                side_effect=dual.GuiFailure('dual_native_ui_cleanup_failed')):
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_native_ui_cleanup_failed$'):
                dual.wait_for_ordinary_tree({})

    def test_transport_diagnostics_are_fixed_nonsecret_counts(self):
        session=Mock()
        session.control.call.return_value={'event':'ts_diagnostics','keyRequests':1,'noiseRequests':0,
            'registerRequests':0,'mapRequests':0,'tlsHandshakeErrors':0,'authCompletions':0,
            'secondClientRegistered':False,'unexpectedPrivateField':'must not escape'}
        counters={'accepted':1,'upstreamBytes':2,'downstreamBytes':3,'workerFailures':0}
        session.relay.stats.return_value={role:dict(counters) for role in ('control','derp','easytier')}
        result=dual.public_transport_sample(session)
        self.assertNotIn('unexpectedPrivateField',result['host'])
        session.relay.stats.return_value['control']['upstreamBytes']=-1
        with self.assertRaises(dual.GuiFailure):dual.public_transport_sample(session)

    def test_start_observer_forwards_actual_callback_and_redacts_unknown_error(self):
        script = r"""const callbacks=new Map(), values=[],sent=[];
          global.window={__TAURI_INTERNALS__:{callbacks},ipc:{postMessage:x=>{sent.push(x);return 17}}};
          callbacks.set(11,x=>values.push(x));callbacks.set(12,x=>values.push(x));
          if(!eval(process.argv[1]))throw Error('install');
          const message=JSON.stringify({cmd:'network_node_start',callback:11,error:12,payload:{secret:'private'}});
          if(window.ipc.postMessage(message)!==17 || sent[0]!==message)throw Error('forward');
          callbacks.get(12)('untrusted private failure');
          const state=window.__dualStartObserver.state;
          if(values[0]!=='untrusted private failure'||state.sent!==1||state.rejected!==1||state.errorCode!=='other')throw Error('callback');
          process.stdout.write('ok');"""
        result=subprocess.check_output(['node','-e',script,dual.START_OBSERVER],text=True)
        self.assertEqual(result,'ok')

    def test_public_host_control_requires_matching_event(self):
        control = Mock()
        control.call.return_value = {'event':'pairing_review','requestId':'synthetic'}
        self.assertEqual(dual.host_request(control, {'op':'review_pairing'}, 'pairing_review')['requestId'], 'synthetic')
        control.call.return_value = {'event':'rejected'}
        with self.assertRaises(dual.GuiFailure):
            dual.host_request(control, {'op':'review_pairing'}, 'pairing_review')


class DualDirectionIsolationTests(unittest.TestCase):
    SHA='a'*40
    CLEANUP={'reverseRemoved':True,'relayStopped':True,'controllerStopped':True,
             'namespaceRemoved':True,'hostPrivateDirectoryRemoved':True,'controlReaderStopped':True,'privateFilesRemoved':True}

    def drive_main(self, ts_packages_removed, cleanup=None):
        calls=[]
        def fake_run_direction(apk, auth_apk, session, stopped, report):
            calls.append(stopped)
            report.update(startObserverInstalled=True,startObserverRestored=True,browserClosed=True,
                forwardRemoved=True,packagesRemoved=ts_packages_removed if stopped=='ts' else True)
            raise dual.GuiFailure('dual_action_unavailable' if stopped=='ts' else 'dual_second_probe_failure')
        session=MagicMock();session.report={'stage':'ready','cleanup':dict(self.CLEANUP if cleanup is None else cleanup)}
        code=None
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('app.apk','auth.apk','bundle.zip'):(Path(tmp)/name).write_bytes(b'payload')
            checkout=Path(tmp)/'checkout';checkout.mkdir()
            argv=['tauri_android_dual_overlay.py','--apk',str(Path(tmp)/'app.apk'),'--auth-apk',str(Path(tmp)/'auth.apk'),
                  '--bundle',str(Path(tmp)/'bundle.zip'),'--output',str(Path(tmp)/'out'),
                  '--host-source-checkout',str(checkout),'--host-source-sha',self.SHA,
                  '--native-source-sha',self.SHA,'--apk-source-sha',self.SHA]
            with patch('sys.argv',argv),patch.dict(os.environ,{'RUNNER_TEMP':tmp,'GITHUB_SHA':self.SHA}),\
                 patch('android_dual_overlay_session.AndroidDualOverlaySession',return_value=session),\
                 patch.object(dual,'run_direction',side_effect=fake_run_direction):
                try:dual.main()
                except SystemExit as exit:code=exit.code
            result=json.loads((Path(tmp)/'out'/'result.json').read_text())
        return calls,result,code

    def test_clean_direction_failure_still_runs_second_direction(self):
        calls,result,code=self.drive_main(True)
        self.assertEqual(calls,['ts','et'])
        self.assertEqual(sorted(result['directions']),['et','ts'])
        self.assertEqual(result['directions']['ts']['directionErrorCode'],'dual_action_unavailable')
        self.assertEqual(result['directions']['et']['directionErrorCode'],'dual_second_probe_failure')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['errorCode'],'dual_action_unavailable')
        self.assertEqual(code,1)

    def test_dirty_cleanup_keeps_fail_fast(self):
        calls,result,code=self.drive_main(False)
        self.assertEqual(calls,['ts'])
        self.assertNotIn('et',result['directions'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['errorCode'],'dual_action_unavailable')
        self.assertEqual(code,1)

    def test_partial_environment_cleanup_keeps_fail_fast(self):
        calls,result,code=self.drive_main(True,cleanup={'reverseRemoved':True,'relayStopped':True,'controllerStopped':True})
        self.assertEqual(calls,['ts'])
        self.assertNotIn('et',result['directions'])
        self.assertEqual(result['directions']['ts']['directionErrorCode'],'dual_action_unavailable')
        self.assertEqual(result['errorCode'],'dual_action_unavailable')
        self.assertEqual(code,1)

    def test_direction_cleanup_proven_matches_run_43746891366_shape(self):
        current={'environmentCleanup':{'reverseRemoved':True,'relayStopped':True,'controllerStopped':True,
                    'namespaceRemoved':True,'hostPrivateDirectoryRemoved':True,'controlReaderStopped':True,'privateFilesRemoved':True},
                 'browserClosed':True,'forwardRemoved':True,'packagesRemoved':True,'privateDirectoryRemoved':True}
        self.assertTrue(dual.direction_cleanup_proven(current))
        partial={**current,'environmentCleanup':{'reverseRemoved':True,'relayStopped':True,'controllerStopped':True}}
        self.assertFalse(dual.direction_cleanup_proven(partial))
        for key in dual.DUAL_ENVIRONMENT_CLEANUP_KEYS:
            with self.subTest(cleanupKey=key):
                self.assertFalse(dual.direction_cleanup_proven(
                    {**current,'environmentCleanup':{**current['environmentCleanup'],key:False}}))
        missing_packages={**current};del missing_packages['packagesRemoved']
        missing_private={**current};del missing_private['privateDirectoryRemoved']
        for mutation in ({'environmentCleanup':{}},{'packagesRemoved':False},{'browserClosed':False}):
            with self.subTest(mutation=mutation):
                self.assertFalse(dual.direction_cleanup_proven({**current,**mutation}))
        for mutation in (missing_packages,missing_private):
            with self.subTest(mutation='missing '+next(iter(set(mutation)^set(current)))):
                self.assertFalse(dual.direction_cleanup_proven(mutation))

    def test_failure_code_reuses_known_taxonomy(self):
        self.assertEqual(dual.failure_code(dual.GuiFailure('dual_action_unavailable')),'dual_action_unavailable')
        self.assertEqual(dual.failure_code(RuntimeError('unexpected')),'dual_driver_failed')

    def test_reported_source_shas_come_from_verified_inputs(self):
        calls,result,code=self.drive_main(True)
        self.assertEqual(result['nativeSourceSHA'],self.SHA)
        self.assertEqual(result['apkSourceSHA'],self.SHA)
        self.assertEqual(result['hostSourceSHA'],self.SHA)
        self.assertNotEqual(result['nativeSourceSHA'],'93ca6cd4b9ccdbe8658d5470c8862b26092aa9dc')
        self.assertNotEqual(result['apkSourceSHA'],'bf39bb44e6df54140984a0abbe93d40f992c1f23')

    def test_source_shas_required_and_shape_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('app.apk','auth.apk','bundle.zip'):(Path(tmp)/name).write_bytes(b'payload')
            checkout=Path(tmp)/'checkout';checkout.mkdir()
            base=['tauri_android_dual_overlay.py','--apk',str(Path(tmp)/'app.apk'),'--auth-apk',str(Path(tmp)/'auth.apk'),
                  '--bundle',str(Path(tmp)/'bundle.zip'),'--output',str(Path(tmp)/'out'),
                  '--host-source-checkout',str(checkout)]
            good={'--host-source-sha':self.SHA,'--native-source-sha':self.SHA,'--apk-source-sha':self.SHA}
            for flag in ('--native-source-sha','--apk-source-sha','--host-source-sha'):
                for bad in (None,'',self.SHA.upper(),'short','x'*41,'not-a-sha'):
                    with self.subTest(flag=flag,bad=bad):
                        argv=[*base]
                        for key,value in good.items():
                            if key!=flag:argv+= [key,value]
                        if bad is not None:argv+= [flag,bad]
                        with patch('sys.argv',argv),patch.dict(os.environ,{'RUNNER_TEMP':tmp,'GITHUB_SHA':self.SHA}):
                            with self.assertRaises(SystemExit) as caught:dual.main()
                        # missing flag: argparse rejects with its own code 2 before shape checks
                        expected=2 if bad is None else 'dual_'+flag.lstrip('-').replace('-','_')+'_invalid'
                        self.assertEqual(caught.exception.code,expected)
                        self.assertFalse((Path(tmp)/'out'/'result.json').exists())


if __name__ == '__main__': unittest.main()
