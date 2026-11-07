"""Offline contracts for two owned real-herdr blocked panes; no daemon or keys."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import blocked_fixture as fixture


TARGETS=[{'paneId':'w2:p1','terminalId':'term_aaa'},
         {'paneId':'w3:p1','terminalId':'term_bbb'}]


def rows():
    return [{'pane_id':target['paneId'],'terminal_id':target['terminalId'],
             'agent':fixture.AGENT,'label':fixture.LABEL,'agent_status':'blocked'} for target in TARGETS]


def pty_record(**changes):
    value={'state':2,'endReason':1,'changes':0,'readErrors':0,'captureErrors':0,
           'initialRows':24,'initialColumns':80,'rows':24,'columns':80}
    value.update(changes)
    return value


class BindingTests(unittest.TestCase):
    def test_exact_two_snapshot_bindings_keep_fixed_order_and_same_custom_agent(self):
        actual=fixture.bindings(list(reversed(rows())),TARGETS)
        self.assertEqual(actual,TARGETS)
        self.assertIsNot(actual[0],TARGETS[0])

    def test_unknown_or_changed_identity_state_label_duplicate_and_extra_fields_fail_closed(self):
        malformed=[None,[],TARGETS[:1],TARGETS+[TARGETS[0]],[TARGETS[0]]*2,
                   [dict(TARGETS[0],terminalText='PRIVATE'),TARGETS[1]],
                   [dict(TARGETS[0],terminalId=True),TARGETS[1]]]
        for targets in malformed:
            with self.subTest(targets=targets),self.assertRaises(fixture.BlockedFixtureFailure):
                fixture.bindings(rows(),targets)
        for key,value in (('terminal_id','term_999'),('agent_status','done'),('agent_status','unknown'),
                          ('agent_status',True),('agent','codex'),('agent',None),('label',None),('label','other')):
            changed=rows()
            changed[1][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(fixture.BlockedFixtureFailure):
                fixture.bindings(changed,TARGETS)
        for changed in (rows()+[rows()[0]],rows()+[dict(rows()[0],pane_id='w4:p1')]):
            with self.subTest(rows=changed),self.assertRaises(fixture.BlockedFixtureFailure):
                fixture.bindings(changed,TARGETS)

    def test_snapshot_version_protocol_and_result_envelope_are_not_inferred(self):
        good={'type':'session_snapshot','snapshot':{'version':'0.9.5','protocol':22,'panes':rows()}}
        with patch.object(fixture,'rpc',return_value=good):
            self.assertEqual(fixture.snapshot('/owned/socket'),rows())
        for value in ({},dict(good,type='ok'),{'type':'session_snapshot','snapshot':None},
                      {'type':'session_snapshot','snapshot':dict(good['snapshot'],protocol=True)},
                      {'type':'session_snapshot','snapshot':dict(good['snapshot'],version='0.9.6')},
                      {'type':'session_snapshot','snapshot':dict(good['snapshot'],panes={})}):
            with self.subTest(value=value),patch.object(fixture,'rpc',return_value=value):
                with self.assertRaises(fixture.BlockedFixtureFailure):fixture.snapshot('/owned/socket')

    def test_duplicate_json_fields_are_rejected(self):
        with self.assertRaises(fixture.BlockedFixtureFailure):
            json.loads('{"id":1,"id":2}',object_pairs_hook=fixture._unique)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        alive=patch.object(fixture,'_alive',return_value=False)
        alive.start()
        self.addCleanup(alive.stop)

    def controller(self,root,record=None,received=b''):
        controller=object.__new__(fixture.BlockedTargets)
        controller.stopped=False
        controller.targets=TARGETS
        controller.pids=[999991,999992]
        controller.directories=[]
        for sample in fixture.SAMPLES:
            directory=root/('blocked-'+sample)
            directory.mkdir()
            (directory/'received.bin').write_bytes(received)
            (directory/'pty-size.json').write_text(json.dumps(record or pty_record()))
            controller.directories.append(directory)
        return controller

    def test_normal_stop_requires_zero_input_and_unchanged_owned_pty(self):
        with tempfile.TemporaryDirectory() as name:
            controller=self.controller(Path(name))
            self.assertEqual(controller.stop(),{'targetCount':2,'sameAgentLabel':True,
                'realSnapshotBindings':True,'receivedInputBytes':0,'noObservedResize':True,
                'ownedWaitingProcessesStopped':True})
            self.assertTrue(all((directory/'stop-capture').read_bytes()==b'stop\n'
                                for directory in controller.directories))
            with self.assertRaises(fixture.BlockedFixtureFailure):controller.stop()

    def test_input_resize_unfinished_error_and_bool_records_cannot_pass(self):
        changes=[{'state':1},{'endReason':6},{'changes':1},{'rows':25},{'columns':81},
                 {'captureErrors':1},{'readErrors':1},{'changes':False},{'state':True},
                 {'rows':0},{'initialColumns':'80'}]
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as name:
                with self.assertRaises(fixture.BlockedFixtureFailure):
                    self.controller(Path(name),pty_record(**change)).stop()
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(fixture.BlockedFixtureFailure):
                self.controller(Path(name),received=b'x').stop()


class WiringTests(unittest.TestCase):
    def test_stock_android_only_prepares_extra_workspaces_and_primary_config_stays_separate(self):
        source=Path(__file__).with_name('run-ci.py').read_text()
        start=source.index("        if (args.paired_gui in ('tauri-android','flutter-android')")
        flow=source[start:source.index('        if args.paired_gui:',start)]
        self.assertIn('not args.input_fixture and not args.android_guarded_input and not args.android_tui',flow)
        self.assertIn('args.blocked_targets = blocked_fixture.prepare()',flow)
        self.assertNotIn("config['paneId'] =",flow)
        self.assertNotIn("'pane','split'",source)
        self.assertIn("report['blockedTargetsFixture'] = blocked_fixture.stop()",source)
        self.assertIn("version_check = false\\nmanifest_check = false",source)

    def test_approval_receives_only_two_real_snapshot_targets_and_can_recheck_them(self):
        import paired_gui
        with patch.object(paired_gui,'blocked_snapshot',return_value=rows()):
            approval=paired_gui.FixtureApproval(Path('/owned'),{'socketPath':'/owned/socket'},None,
                                                blocked_targets=TARGETS)
            self.assertEqual(approval.blocked_targets,TARGETS)
            self.assertEqual(approval.verify_blocked_targets(),TARGETS)
        changed=rows()
        changed[1]['terminal_id']='term_999'
        with patch.object(paired_gui,'blocked_snapshot',return_value=changed):
            with self.assertRaises(paired_gui.GuiFailure):approval.verify_blocked_targets()
        default=paired_gui.FixtureApproval(Path('/owned'),{},None)
        self.assertEqual(default.blocked_targets,[])


if __name__=='__main__':
    unittest.main()
