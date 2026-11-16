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
def sample(*,active=True,count=1,new=0,captured=1,exact=True):
    return {'event':'host_audit','acceptedSessions':count,'newSessions':new,'capturedBytes':captured,'exactBytes':exact,
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
        host,timeline=self.snapshot([sample(),sample(active=False)])
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
    def test_diagnostic_failure_is_unknown_and_never_sets_or_retries_state(self):
        host,timeline=self.snapshot([RuntimeError('private raw error'),{**sample(),'acceptedSessions':True}])
        self.assertEqual(host.call.call_count,2)
        for role in ('ts','et'):
            self.assertEqual(timeline['samples'][0]['roles'][role],
                             {'available':False,'originalOrdinal':1,'originalSessionCount':1,'expectedBytes':1})
        self.assertNotIn('private',json.dumps(timeline))
    def test_diagnostic_audit_cursor_cannot_hide_a_reconnect_from_original_strict_audit(self):
        host=Mock();host.call.side_effect=[sample(count=2,new=1),sample(),sample(count=2,new=0)]
        timeline={}
        dual.record_stop_checkpoint(host,timeline,'before_stop',BASELINES,EXPECTED,dual.time.monotonic())
        self.assertFalse(timeline['samples'][0]['roles']['ts']['sessionCountUnchanged'])
        with patch.object(dual,'wait_for',side_effect=lambda probe,*args,**kwargs:probe()):
            with self.assertRaisesRegex(dual.GuiFailure,'dual_peer_evidence_mismatch'):
                dual.audit(host,'ts',b'T',ordinal=1,sessions_count=1)
        self.assertEqual(host.call.call_count,3)
    def test_missing_original_session_is_not_reported_as_known_inactive(self):
        value=sample();value['sessions'][0]['ordinal']=2
        _,timeline=self.snapshot([value,sample()])
        facts=timeline['samples'][0]['roles']['ts']
        self.assertFalse(facts['originalSessionFound']);self.assertIsNone(facts['originalActive']);self.assertIsNone(facts['originalApproved'])
    def test_flags_are_snapshots_of_actual_attempt_and_ack_not_late_success(self):
        timeline={'secondInputAttempted':False,'secondAckSeen':False}
        self.snapshot([sample(),sample()],timeline,phase='before_stop')
        timeline['secondInputAttempted']=True
        self.snapshot([sample(captured=2),sample()],timeline,phase='failure',expected={'ts':b'Tt','et':b'E'})
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
        failure=dual.GuiFailure('dual_peer_evidence_timeout')
        namespace=dict(vars(dual),report=report,browser=browser,control=object(),stopped='et',initials=dict(EXPECTED),
            baseline_values=BASELINES,bindings={'ts':'ts-profile','et':'et-profile'},select_tab=Mock(),expand_profile=Mock(return_value='#owned-card'),
            install_stop_observer=Mock(),stop_node_once=stop,wait_named=Mock(),send_draft=send,
            audit=Mock(side_effect=failure),record_stop_checkpoint=lambda host,timeline,phase,*_:phases.append(phase))
        exec(compile(module,'<actual-driver-stop-fragment>','exec'),namespace)
        with self.assertRaises(dual.GuiFailure) as caught:namespace['exercise']()
        self.assertIs(caught.exception,failure);self.assertEqual(stop.call_count,1);send.assert_not_called()
        self.assertEqual(phases,['before_navigation','before_stop','after_stop_return','after_stopped_ui','failure'])
        self.assertFalse(report['stopTimeline']['secondInputAttempted']);self.assertFalse(report['stopTimeline']['secondAckSeen'])

if __name__=='__main__':unittest.main()
