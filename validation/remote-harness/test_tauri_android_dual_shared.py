import base64
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import tauri_android_dual_overlay as dual


def audit(role, *, active=True, close='unconfirmed', new=0, captured=0, delta=0, exact=True, ordinal=1):
    return {'event':'host_audit','role':role,'acceptedSessions':1,'newSessions':new,
            'capturedBytes':captured,'newInputBytes':delta,'exactBytes':exact,'authorizationActive':True,
            'soleApprovedSession':True,'inputAttributionAmbiguous':False,
            'sessions':[{'ordinal':ordinal,'approvedDevice':True,'active':active,'peerClose':close,
                         'capturedBytes':captured,
                         'private':'do not publish'}], 'raw':'do not publish'}


class SharedPeerEvidenceTests(unittest.TestCase):
    def test_pending_close_and_peer_reset_are_distinct(self):
        host=Mock()
        host.call.side_effect=[audit('et'),audit('ts')]
        report={}
        self.assertEqual(dual.shared_peer_state(host,report,'after_a_close',live=('b',),
                                                closing='a',timeout=0),'unconfirmed')
        for kind in ('peer_eof','client_disconnect','peer_reset'):
            with self.subTest(kind=kind):
                host.call.side_effect=[audit('et',active=False,close=kind),audit('ts')]
                self.assertEqual(dual.shared_peer_state(host,report,'after_a_close',live=('b',),
                                                        closing='a',timeout=0),kind)
                self.assertNotIn('do not publish',json.dumps(report))
                self.assertTrue(report['peerCheckpoints']['after_a_close']['b']['sessions'][0]['active'])

    def test_survivor_audit_observes_one_new_byte_on_original_ssh_only(self):
        host=Mock(reader_failed=False)
        closed=audit('et',active=False,close='client_disconnect',captured=1)
        host.call.side_effect=[closed,audit('ts',captured=1,exact=False),
                               closed,audit('ts',captured=2,delta=1)]
        report={}
        with patch.object(dual.time,'sleep'):
            dual.shared_peer_state(host,report,'survivor',live=('b',),require_closed=('a',),
                                   inputs={'a':b'E','b':b'Tt'},pending='b')
        requested=[(call.args[0]['role'],base64.b64decode(call.args[0]['expectedBase64']))
                   for call in host.call.call_args_list]
        self.assertEqual(requested,[('et',b'E'),('ts',b'Tt')]*2)
        self.assertTrue(report['peerCheckpoints']['survivor']['b']['inputAttributedToOriginalSession'])
        self.assertNotIn('do not publish',json.dumps(report))

    def test_wrong_side_duplicate_and_replacement_session_are_rejected(self):
        cases=(
            (audit('et',active=False,close='client_disconnect',captured=2,delta=1,exact=False),
             audit('ts',captured=2,delta=1), 'dual_shared_input_bytes_mismatch'),
            (audit('et',active=False,close='client_disconnect',captured=1),
             audit('ts',captured=3,delta=2,exact=False), 'dual_shared_input_bytes_mismatch'),
            (audit('et',active=False,close='client_disconnect',captured=1),
             audit('ts',captured=2,delta=1,exact=False), 'dual_shared_input_bytes_mismatch'),
            (audit('et',active=False,close='client_disconnect',captured=1),
             audit('ts',captured=2,delta=1,ordinal=2), 'dual_shared_original_ssh_changed'),
        )
        for a,b,code in cases:
            with self.subTest(code=code):
                host=Mock(reader_failed=False)
                host.call.side_effect=[a,b]
                with self.assertRaisesRegex(dual.GuiFailure,'^'+code+'$'):
                    dual.shared_peer_state(host,{},'survivor',live=('b',),require_closed=('a',),
                                           inputs={'a':b'E','b':b'Tt'},pending='b',timeout=0)

    def test_new_connection_stock_write_and_survivor_loss_fail_closed(self):
        cases=(
            (dict(audit('ts'),newSessions=1),'dual_shared_original_ssh_changed'),
            (dict(audit('ts'),capturedBytes=2,exactBytes=False),'dual_shared_stock_writes_detected'),
            (audit('ts',active=False,close='peer_eof'),'dual_shared_live_peer_lost'),
            (dict(audit('ts'),sessions=[{'ordinal':1,'approvedDevice':True,'active':True,
                                       'peerClose':'private session text'}]),'dual_shared_peer_evidence_invalid'),
        )
        for survivor,expected in cases:
            with self.subTest(expected=expected):
                host=Mock(reader_failed=False)
                host.call.side_effect=[audit('et',active=False,close='peer_eof'),survivor]
                report={}
                with self.assertRaisesRegex(dual.GuiFailure,'^'+expected+'$'):
                    dual.shared_peer_state(host,report,'after_a_close',live=('b',),closing='a',timeout=0)
                self.assertNotIn('private session text',json.dumps(report))

    def test_native_observer_passes_through_status_and_records_stop_binding(self):
        script=r"""
        const delivered=[],calls=[];
        const privateBinding={profileId:'p',profileRevision:2,identityRef:'i',networkName:'n'};
        global.window={ipc:{postMessage(value){calls.push(value)}}, __TAURI_INTERNALS__:{callbacks:new Map()}};
        const c=window.__TAURI_INTERNALS__.callbacks;
        c.set(7,v=>delivered.push(v));
        if(!eval(process.argv[1]))throw Error('observer missing');
        window.ipc.postMessage(JSON.stringify({cmd:'network_node_status',payload:{id:'p'},callback:7}));
        const value={state:'engine-started',binding:privateBinding,authUrl:'private URL'};
        c.get(7)(value);
        window.ipc.postMessage(JSON.stringify({cmd:'network_node_stop',payload:{binding:privateBinding}}));
        if(delivered.length!==1 || delivered[0]!==value || calls.length!==2)throw Error('altered IPC');
        process.stdout.write(JSON.stringify(window.__sharedNode.state));
        """
        result=json.loads(subprocess.check_output(['node','-e',script,dual.SHARED_NODE_OBSERVER],text=True))
        self.assertEqual(result,{'seq':1,'latest':{'seq':1,'id':'p','state':'engine-started',
            'binding':['p',2,'i','n',False,None]},'stopBinding':['p',2,'i','n',False,None]})

    def test_native_binding_preserves_omission_and_rejects_wrong_provider(self):
        browser=Mock()
        prefix=['p',1,'i','n']
        for state,stopped in (('engine-started',False),('stopped',True)):
            browser.evaluate.return_value={'seq':2,'id':'p','state':state,'binding':prefix+[False,None]}
            self.assertEqual(dual.shared_node_state(browser,'p',after=1,stopped=stopped),
                             browser.evaluate.return_value)
        for wrong in ('tailscale','zerotier',None):
            with self.subTest(wrong=wrong):
                browser.evaluate.return_value={'seq':2,'id':'p','state':'engine-started','binding':prefix+[True,wrong]}
                with self.assertRaisesRegex(dual.GuiFailure,'^dual_shared_native_provider_mismatch$'):
                    dual.shared_node_state(browser,'p')


class SharedScenarioTests(unittest.TestCase):
    def test_no_writes_two_tab_closes_and_explicit_stop_even_with_reset_evidence(self):
        for a_close in ('peer_eof','peer_reset'):
            with self.subTest(a_close=a_close):
                self.drive(a_close)

    def test_write_opt_in_sends_to_survivor_only_after_confirmed_a_close(self):
        self.drive('peer_eof',active_input=True)
        self.drive('peer_reset',active_input=True)

    def drive(self,a_close,*,active_input=False):
        events=[]
        browser=Mock()
        session=Mock()
        binding=['profile',1,'id','network',False,None]
        browser.evaluate.return_value=binding
        session.control.reader_failed=False
        session.read_host_profile.side_effect=lambda role:{'host':role,'port':2,'expectedHostKey':role}
        session.relay.active_connections.side_effect=[{'easytier':1,'easytierSecond':1}]*3+[
            {'easytier':0,'easytierSecond':0}]
        first={'et':True,'ts':True}
        received={'et':b'','ts':b''}
        def host_call(request):
            role=request['role']
            self.assertEqual(base64.b64decode(request['expectedBase64']),received[role])
            value=audit(role,active=role not in events,new=int(first[role]),
                close=(a_close if role=='et' else 'client_disconnect') if role in events else 'unconfirmed',
                captured=len(received[role]))
            first[role]=False
            return value
        session.control.call.side_effect=host_call
        report={}
        states=({'seq':i,'binding':binding} for i in range(1,5))
        def close_tab(_browser,role):
            events.append(role)
            return 'removed'
        def record_input(_browser,_control,_report,phase,_target,_tab,inputs,_receipts,_ensure):
            events.append(phase)
            role, marker, _=dual.SHARED_WRITES[phase]
            received[role]+=marker
            inputs[dual.SHARED_HOSTS[role]]+=marker
        with patch.multiple(dual,create_network=Mock(),pair_host=Mock(),
                bind_host=Mock(return_value='profile'),expand_profile=Mock(return_value='#et'),
                shared_bound_hosts=Mock(return_value='QA host ET、QA host TS'),
                shared_status_sequence=Mock(side_effect=[1,2]),
                shared_node_state=Mock(side_effect=states),
                open_tab=Mock(return_value={'pane':'pane','terminal':'terminal'}),
                shared_tab_id=Mock(side_effect=lambda _browser,role,_target:role),
                shared_tick=Mock(side_effect=[10,20,21,22]),find_tab=Mock(return_value=None),
                select_tab=Mock(),wait_named=Mock(),install_stop_observer=Mock(),uninstall_stop_observer=Mock(),
                named_action_available=Mock(return_value=True),
                close_shared_tab=Mock(side_effect=close_tab),
                stop_node_once=Mock(side_effect=lambda *_args,**_kwargs:events.append('stop')),
                resume_shared_input_tab=Mock(),shared_input_once=Mock(side_effect=record_input),
                start_observer_snapshot=Mock(return_value={'sent':1,'resolved':1,'rejected':0})), \
                patch('flutter_android_gui.public_host_fingerprint',side_effect=str):
            if a_close=='peer_reset':
                code='dual_shared_a_close_required_before_survivor_input' if active_input else 'dual_shared_peer_reset'
                with self.assertRaisesRegex(dual.GuiFailure,'^'+code+'$'):
                    dual.run_shared_easytier(browser,session,report,Mock(),active_input=active_input)
                if active_input:
                    self.assertEqual(events,['a_first','b_first','et'])
                    return
                self.assertEqual(report['closeFailures'],['a'])
            else:
                dual.run_shared_easytier(browser,session,report,Mock(),active_input=active_input)
                self.assertEqual(report['stage'],'complete')
        if active_input:
            self.assertEqual(events,['a_first','b_first','et','b_after_a_close','ts','stop'])
            self.assertEqual(report['finalVerifiedInputBytes'],{'a':1,'b':2})
            self.assertEqual(received,{'et':b'E','ts':b'Tt'})
            self.assertNotIn('bothStockWriteBytes',report)
        else:
            self.assertEqual(events,['et','ts','stop'])
            self.assertEqual(report['bothStockWriteBytes'],0)
        self.assertEqual(report['aCloseBeforeBTabClose'],a_close)
        self.assertEqual(report['bCloseBeforeNodeStop'],'client_disconnect')
        self.assertEqual(report['bExplicitlyResumedSameTab'],{'firstTick':21,'nextTick':22})
        self.assertFalse(report['nativeBindingProviderFieldPresent'])
        self.assertEqual(report['relayCheckpoints']['after_node_stop'],{'a':0,'b':0})
        self.assertEqual(report['peerCheckpoints']['after_a_close']['b']['acceptedSessions'],1)
        self.assertTrue(report['peerCheckpoints']['before_b_close']['b']['sessions'][0]['active'])


class SharedInputUiTests(unittest.TestCase):
    def test_actual_input_focus_requires_same_activity_and_default_display(self):
        app=dual.PACKAGE
        exact=f"Display: mDisplayId=0\n mCurrentFocus=Window{{cfe u0 {app}/.MainActivity}}"
        for window,expected in ((exact,True),(exact.replace('u0','u10'),False),
                                (exact.replace('mDisplayId=0','mDisplayId=1'),False),
                                (exact.replace('MainActivity','OtherActivity'),False)):
            with self.subTest(expected=expected), patch.object(dual,'adb',return_value=window), \
                    patch.object(dual,'foreground_component',return_value=f'{app}/{app}.MainActivity'):
                self.assertEqual(dual.shared_input_foreground(),expected)

    def send(self, *, rendered=True, reused=False, foreground=True):
        browser=Mock()
        browser.evaluate.return_value=True
        ident='1'*32
        browser.read.side_effect=['', 't', '请求 ID：'+ident+
            ' · pane：pane · terminal：terminal · 受理 1 字节。主机已受理，命令结果请查看终端。']
        target={'pane':'pane','terminal':'terminal'}
        receipt_ids={ident} if reused else set()
        report={}
        expected=('dual_shared_input_peer_frame_missing' if not rendered else
                  'dual_shared_input_receipt_invalid' if reused else
                  'dual_shared_input_foreground_unconfirmed' if not foreground else None)
        def observe(probe,code,**kwargs):
            if not probe():
                raise dual.GuiFailure(code)
            return True
        with patch.multiple(dual,shared_tab_id=Mock(return_value='tab-b'),
                            shared_input_foreground=Mock(return_value=foreground),wait_named=Mock(),
                            rendered_marker=Mock(side_effect=[False,rendered]),
                            confirm_click=Mock(),shared_peer_state=Mock(),wait_for=observe):
            inputs={'a':b'E','b':b'T'}
            arguments=(browser,Mock(),report,'b_after_a_close',target,'tab-b',inputs,receipt_ids,Mock())
            if expected:
                with self.assertRaisesRegex(dual.GuiFailure,'^'+expected+'$'):
                    dual.shared_input_once(*arguments)
                self.assertEqual(dual.shared_peer_state.call_count,1)
            else:
                dual.shared_input_once(*arguments)
                self.assertEqual(inputs,{'a':b'E','b':b'Tt'})
                end=dual.shared_peer_state.call_args
                self.assertEqual(end.args[2],'b_after_a_close_after')
                self.assertEqual(end.kwargs['require_closed'],('a',))
                self.assertEqual(end.kwargs['pending'],'b')
            # A failure or completed action cannot launch a second confirmation.
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_shared_input_already_attempted$'):
                dual.shared_input_once(*arguments)
            if foreground:
                dual.confirm_click.assert_called_once_with(browser,'#view-content','发送草稿',
                    '发送到 QA host TS · pane · terminal？',once=True)
            else:
                dual.confirm_click.assert_not_called()
        self.assertNotIn(ident,json.dumps(report))
        return report['sharedInputActions']['b_after_a_close']

    def test_matched_receipt_requires_distinct_host_frame_and_peer_audit(self):
        self.assertTrue(self.send()['peerBytesAndSessionVerified'])
        receipt_only=self.send(rendered=False)
        self.assertEqual(receipt_only['uiAcceptedBytes'],1)
        self.assertNotIn('peerFrameRendered',receipt_only)
        self.assertNotIn('peerBytesAndSessionVerified',receipt_only)
        self.assertNotIn('uiAcceptedBytes',self.send(reused=True))
        self.assertFalse(self.send(foreground=False)['nativeConfirmationAttempted'])

    def test_unknown_native_dialog_tap_is_not_repeated(self):
        nodes=[{'text':'发送到 QA host TS · pane · terminal？'},
               {'text':'确定','enabled':'true','bounds':'[10,10][100,100]'}]
        with patch.object(dual,'native_ui_nodes',return_value=nodes), \
                patch.object(dual,'adb',side_effect=dual.GuiFailure('android_adb_command_failed')) as adb:
            self.assertFalse(dual.native_dialog_click(nodes[0]['text'],{'确定'},once=True))
        adb.assert_called_once_with('shell','input','tap','55','55')
