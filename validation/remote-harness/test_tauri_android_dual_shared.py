import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import tauri_android_dual_overlay as dual


def audit(role, *, active=True, close='unconfirmed', new=0):
    return {'event':'host_audit','role':role,'acceptedSessions':1,'newSessions':new,
            'capturedBytes':0,'newInputBytes':0,'exactBytes':True,'authorizationActive':True,
            'soleApprovedSession':True,'inputAttributionAmbiguous':False,
            'sessions':[{'ordinal':1,'approvedDevice':True,'active':active,'peerClose':close,
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

    def drive(self,a_close):
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
        def host_call(request):
            role=request['role']
            self.assertEqual(request['expectedBase64'],'')
            value=audit(role,active=role not in events,new=int(first[role]),
                close=(a_close if role=='et' else 'client_disconnect') if role in events else 'unconfirmed')
            first[role]=False
            return value
        session.control.call.side_effect=host_call
        report={}
        states=({'seq':i,'binding':binding} for i in range(1,5))
        def close_tab(_browser,role):
            events.append(role)
            return 'removed'
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
                start_observer_snapshot=Mock(return_value={'sent':1,'resolved':1,'rejected':0})), \
                patch('flutter_android_gui.public_host_fingerprint',side_effect=str):
            if a_close=='peer_reset':
                with self.assertRaisesRegex(dual.GuiFailure,'^dual_shared_peer_reset$'):
                    dual.run_shared_easytier(browser,session,report,Mock())
                self.assertEqual(report['closeFailures'],['a'])
            else:
                dual.run_shared_easytier(browser,session,report,Mock())
                self.assertEqual(report['stage'],'complete')
        self.assertEqual(events,['et','ts','stop'])
        self.assertEqual(report['aCloseBeforeBTabClose'],a_close)
        self.assertEqual(report['bCloseBeforeNodeStop'],'client_disconnect')
        self.assertEqual(report['bExplicitlyResumedSameTab'],{'firstTick':21,'nextTick':22})
        self.assertEqual(report['bothStockWriteBytes'],0)
        self.assertFalse(report['nativeBindingProviderFieldPresent'])
        self.assertEqual(report['relayCheckpoints']['after_node_stop'],{'a':0,'b':0})
        self.assertEqual(report['peerCheckpoints']['after_a_close']['b']['acceptedSessions'],1)
        self.assertTrue(report['peerCheckpoints']['before_b_close']['b']['sessions'][0]['active'])
