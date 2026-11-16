"""Passive stop checkpoints preserve original session criteria and first failure."""
import ast
import base64
import copy
import inspect
import json
import unittest
from unittest.mock import Mock,patch
import tauri_android_dual_overlay as dual

BASELINES={'ts':(1,1),'et':(1,1)}
EXPECTED={'ts':b'T','et':b'E'}
def sample(*,role='ts',active=True,count=1,new=0,captured=1,exact=True):
    return {'event':'host_audit','role':role,'acceptedSessions':count,'newSessions':new,'capturedBytes':captured,'exactBytes':exact,
            'sessions':[{'ordinal':i+1,'approvedDevice':i==0,'active':active if i==0 else False} for i in range(count)],
            'privateLog':'must-not-publish','fingerprint':'must-not-publish'}

class StopTimelineTests(unittest.TestCase):
    def snapshot(self,values,timeline=None,phase='before_stop',expected=EXPECTED):
        host=Mock();host.call.side_effect=values
        timeline=timeline if timeline is not None else {'secondInputAttempted':False,'secondAckSeen':False}
        with patch.object(dual.time,'monotonic',return_value=101.25):
            dual.record_stop_checkpoint(host,timeline,phase,BASELINES,expected,100)
        return host,timeline
    def test_single_read_original_ordinal_and_exact_bytes_without_raw_content(self):
        host,timeline=self.snapshot([sample(),sample(role='et',active=False)])
        entry=timeline['samples'][0]
        self.assertEqual(entry['elapsedMilliseconds'],1250);self.assertEqual(entry['completedElapsedMilliseconds'],1250)
        self.assertTrue(entry['roles']['ts']['originalActive']);self.assertFalse(entry['roles']['et']['originalActive'])
        self.assertEqual(entry['roles']['ts']['originalOrdinal'],1);self.assertTrue(entry['roles']['ts']['sessionCountUnchanged'])
        self.assertTrue(entry['roles']['ts']['exactBytes']);self.assertFalse(entry['secondInputAttempted']);self.assertFalse(entry['secondAckSeen'])
        self.assertEqual(host.call.call_count,2)
        for call,role in zip(host.call.call_args_list,('ts','et')):
            self.assertEqual(call.args[0],{'op':'audit','role':role,'expectedBase64':base64.b64encode(EXPECTED[role]).decode()})
        text=json.dumps(timeline)
        for secret in ('must-not-publish','fingerprint','expectedBase64','privateLog'):self.assertNotIn(secret,text)
    def test_untrusted_diagnostic_permanently_fences_late_same_count_reply_without_retry(self):
        for first in (TimeoutError('private raw error'),{**sample(),'acceptedSessions':True},
                      {**sample(),'event':'other'},sample(role='et'),{key:value for key,value in sample().items() if key!='role'}):
            with self.subTest(first=type(first).__name__):
                host=Mock();host.call.side_effect=[first,sample(),sample(role='et')]
                timeline={}
                with self.assertRaisesRegex(dual.GuiFailure,'dual_host_control_quarantined'):
                    dual.record_stop_checkpoint(host,timeline,'before_stop',BASELINES,EXPECTED,dual.time.monotonic())
                self.assertTrue(dual.host_control_quarantined(host));self.assertTrue(host.reader_failed)
                self.assertTrue(timeline['controlChannelQuarantined']);self.assertEqual(host.call.call_count,1)
                self.assertEqual(timeline['samples'][0]['roles']['ts'],
                                 {'available':False,'originalOrdinal':1,'originalSessionCount':1,'expectedBytes':1})
                # This queued old reply has the SAME ordinal/count/bytes and
                # could pass the old audit. Quarantine must never consume it.
                with patch.object(dual,'wait_for',side_effect=lambda probe,*args,**kwargs:probe()):
                    with self.assertRaisesRegex(dual.GuiFailure,'dual_host_control_quarantined'):
                        dual.audit(host,'ts',b'T',ordinal=1,sessions_count=1)
                self.assertEqual(dual.public_host_failure_counts(host),{'ts':{'available':False},'et':{'available':False}})
                self.assertEqual(host.call.call_count,1);self.assertNotIn('private',json.dumps(timeline))
    def test_quarantine_blocks_direct_cleanup_protocol_write_but_not_process_cleanup(self):
        from android_dual_overlay_session import PrivateHostControl,SessionError
        control=PrivateHostControl.__new__(PrivateHostControl)
        control.process=Mock();control.process.poll.return_value=None
        control.reader_failed=False;control.lock=__import__('threading').Lock()
        dual.quarantine_host_control(control)
        with self.assertRaises(SessionError):control.call({'op':'stop'},timeout=0)
        control.process.stdin.write.assert_not_called()
        # The process handle is intact for the existing namespace/termination cleanup.
        control.process.terminate();control.process.terminate.assert_called_once()
    def test_original_strict_audit_rejects_wrong_role_even_when_all_counts_match(self):
        host=Mock();host.call.side_effect=[sample(role='et'),sample()]
        with patch.object(dual,'wait_for',side_effect=lambda probe,*args,**kwargs:probe()):
            with self.assertRaisesRegex(dual.GuiFailure,'dual_host_role_mismatch'):
                dual.audit(host,'ts',b'T',ordinal=1,sessions_count=1)
        self.assertTrue(dual.host_control_quarantined(host));self.assertEqual(host.call.call_count,1)
    def test_diagnostic_audit_cursor_cannot_hide_a_reconnect_from_original_strict_audit(self):
        host=Mock();host.call.side_effect=[sample(count=2,new=1),sample(role='et'),sample(count=2,new=0)]
        timeline={}
        dual.record_stop_checkpoint(host,timeline,'before_stop',BASELINES,EXPECTED,dual.time.monotonic())
        self.assertFalse(timeline['samples'][0]['roles']['ts']['sessionCountUnchanged'])
        with patch.object(dual,'wait_for',side_effect=lambda probe,*args,**kwargs:probe()):
            with self.assertRaisesRegex(dual.GuiFailure,'dual_peer_evidence_mismatch'):
                dual.audit(host,'ts',b'T',ordinal=1,sessions_count=1)
        self.assertEqual(host.call.call_count,3)
    def test_missing_original_session_is_not_reported_as_known_inactive(self):
        value=sample();value['sessions'][0]['ordinal']=2
        _,timeline=self.snapshot([value,sample(role='et')])
        facts=timeline['samples'][0]['roles']['ts']
        self.assertFalse(facts['originalSessionFound']);self.assertIsNone(facts['originalActive']);self.assertIsNone(facts['originalApproved'])
    def test_flags_are_snapshots_of_actual_attempt_and_ack_not_late_success(self):
        timeline={'secondInputAttempted':False,'secondAckSeen':False}
        self.snapshot([sample(),sample(role='et')],timeline,phase='before_stop')
        timeline['secondInputAttempted']=True
        self.snapshot([sample(captured=2),sample(role='et')],timeline,phase='failure',expected={'ts':b'Tt','et':b'E'})
        self.assertFalse(timeline['samples'][0]['secondInputAttempted']);self.assertTrue(timeline['samples'][1]['secondInputAttempted'])
        self.assertFalse(timeline['samples'][1]['secondAckSeen']);self.assertEqual(timeline['samples'][1]['roles']['ts']['expectedBytes'],2)
    def test_real_stop_control_flow_preserves_first_post_stop_failure_without_second_input_or_retry(self):
        # Execute the actual driver's stop fragment, keeping its statements and
        # first-error handler; only device prerequisites/native stop are stubbed.
        original=ast.parse(inspect.getsource(dual.run_direction)).body[0]
        work=next(node for node in original.body if isinstance(node,ast.Try))
        def assigns(node,name):
            return isinstance(node,ast.Assign) and any(ast.unparse(target)=="report["+repr(name)+"]" for target in node.targets)
        begin=next(i for i,node in enumerate(work.body) if assigns(node,'bothInputAndDistinctTargets'))
        end=next(i for i,node in enumerate(work.body) if assigns(node,'survivorSameAuthenticatedSession'))
        handler=ast.ExceptHandler(type=ast.Name(id='Exception',ctx=ast.Load()),name='error',
            body=[copy.deepcopy(work.handlers[0].body[0]),ast.Raise()])
        fragment=ast.FunctionDef(name='exercise',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
            body=[ast.Try(body=copy.deepcopy(work.body[begin:end+1]),handlers=[handler],orelse=[],finalbody=[])],decorator_list=[])
        module=ast.fix_missing_locations(ast.Module(body=[fragment],type_ignores=[]))
        report={};browser=Mock();stop=Mock(return_value='owned-profile');send=Mock();phases=[]
        failure=dual.GuiFailure('dual_peer_evidence_timeout');control=Mock()
        def checkpoint(host,timeline,phase,*_):
            phases.append(phase)
            if phase=='failure':
                dual.quarantine_host_control(host)
                raise dual.GuiFailure('dual_host_control_quarantined')
        namespace=dict(vars(dual),report=report,browser=browser,control=control,stopped='et',initials=dict(EXPECTED),
            baseline_values=BASELINES,bindings={'ts':'ts-profile','et':'et-profile'},select_tab=Mock(),expand_profile=Mock(return_value='#owned-card'),
            install_stop_observer=Mock(),stop_node_once=stop,wait_named=Mock(),send_draft=send,
            audit=Mock(side_effect=failure),record_stop_checkpoint=checkpoint)
        exec(compile(module,'<actual-driver-stop-fragment>','exec'),namespace)
        with self.assertRaises(dual.GuiFailure) as caught:namespace['exercise']()
        self.assertIs(caught.exception,failure);self.assertEqual(stop.call_count,1);send.assert_not_called()
        self.assertEqual(phases,['before_navigation','before_stop','after_stop_return','after_stopped_ui','failure'])
        self.assertFalse(report['stopTimeline']['secondInputAttempted']);self.assertFalse(report['stopTimeline']['secondAckSeen'])
        self.assertTrue(dual.host_control_quarantined(control));control.call.assert_not_called()

if __name__=='__main__':unittest.main()
