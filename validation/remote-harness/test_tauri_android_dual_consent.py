"""Real-format native XML and command-flow A/B; not Android key-delivery proof."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

import tauri_android_dual_overlay as dual

PORT=43123
COMPONENT=dual.AUTH_PACKAGE+'/'+dual.AUTH_PACKAGE+'.AuthActivity'


def nodes(focused='true',status='ready'):
    xml=f'''<hierarchy rotation="0"><node index="0" package="{dual.AUTH_PACKAGE}" class="android.widget.LinearLayout">
<node index="0" package="{dual.AUTH_PACKAGE}" class="android.widget.TextView" content-desc="dual_auth_origin" text="隔离测试控制面：127.0.0.1:{PORT}"/>
<node index="1" package="{dual.AUTH_PACKAGE}" class="android.widget.TextView" content-desc="{status}"/>
<node index="2" package="{dual.AUTH_PACKAGE}" class="android.widget.Button" content-desc="dual_auth_approve" text="批准本次测试授权" enabled="true" clickable="true" focused="{focused}" bounds="[20,40][60,80]"/>
</node></hierarchy>'''
    return list(ET.fromstring(xml).iter('node'))


def poll(probe,code,**kwargs):
    for _ in range(4):
        result=probe()
        if result:return result
    raise dual.GuiFailure(code)


def post(status='delivered'):
    _,state=dual.auth_consent_candidate(nodes(status=status),COMPONENT,PORT)
    state['foregroundStable']=True
    return None,state


def activated():
    return {'authorization':{'activationAttempted':True,'activationCompleted':True}}


class ConsentActivationTests(unittest.TestCase):
    def test_positive_geometry_without_focus_sends_nothing_stable_focus_sends_one_enter(self):
        point,state=dual.auth_consent_candidate(nodes(focused='false'),COMPONENT,PORT)
        self.assertIsNone(point);self.assertTrue(state['boundsValid'])
        with patch.object(dual,'auth_receiver_screen',return_value=(point,state)),patch.object(dual,'wait_for',side_effect=poll),patch.object(dual,'adb') as adb:
            with self.assertRaisesRegex(dual.GuiFailure,'dual_authorization_receiver_missing'):dual.approve_auth_receiver(PORT,{})
        adb.assert_not_called()
        point,state=dual.auth_consent_candidate(nodes(),COMPONENT,PORT);state['foregroundStable']=True
        report={}
        frames=[(point,state),(None,{'status':'ready'}),(point,state),(point,state)]
        with patch.object(dual,'auth_receiver_screen',side_effect=frames),patch.object(dual,'wait_for',side_effect=poll),patch.object(dual,'adb') as adb:
            dual.approve_auth_receiver(PORT,report)
        self.assertEqual(adb.call_args_list, [unittest.mock.call('shell','input','keyevent','KEYCODE_ENTER')])
        self.assertEqual(report['authorization']['stableReads'],2)

    def test_activity_window_and_tree_must_all_match_before_key_readiness(self):
        for foreground,window,ready in [(COMPONENT,COMPONENT,True),(None,COMPONENT,False),(COMPONENT,dual.PACKAGE+'/.MainActivity',False)]:
            raw='mCurrentFocus=Window{abc u0 '+window+'}'
            with patch.object(dual,'foreground_component',return_value=foreground),patch.object(dual,'native_ui_nodes',return_value=nodes()),patch.object(dual,'adb',return_value=raw):
                point,state=dual.auth_receiver_screen(PORT)
            self.assertEqual(point is not None,ready)
            self.assertEqual(state['foregroundStable'],ready)

    def test_unrecognized_status_or_wrong_source_description_never_activates(self):
        for value in (nodes(status='unrecognized-private-state'),nodes()):
            if value[2].get('content-desc')=='ready':value[1].set('content-desc','wrong-origin')
            self.assertIsNone(dual.auth_consent_candidate(value,COMPONENT,PORT)[0])


class PrivateHandoffTests(unittest.TestCase):
    def test_post_confirmation_status_and_file_failures_are_distinct_without_reactivation(self):
        cases=[('ready','missing','confirmation_not_effective'),('click_received','missing','delivery_pending'),
               ('delivery_failed','missing','delivery_failed'),('source_mismatch','missing','source_mismatch'),
               ('delivered','missing','delivered_file_missing'),('delivered','unavailable','handoff_file_unavailable'),
               ('delivered','unreadable','handoff_unreadable'),('delivered','not_regular','handoff_unreadable')]
        for status,file_state,code in cases:
            report=activated()
            with self.subTest(status=status,file=file_state),patch.object(dual,'auth_receiver_screen',return_value=post(status)), \
                    patch.object(dual,'private_handoff_file_state',return_value=file_state),patch.object(dual,'wait_for',side_effect=poll),patch.object(dual,'adb') as adb:
                with self.assertRaisesRegex(dual.GuiFailure,'^dual_authorization_'+code+'$'):
                    dual.confirmed_private_handoff(PORT,report)
            adb.assert_not_called()
            self.assertEqual(report['authorization']['postConsent']['status'],status)
            self.assertEqual(report['authorization']['postConsent']['fileState'],file_state)

    def test_delivered_readable_file_still_requires_private_origin_and_successful_read(self):
        good='https://127.0.0.1:'+str(PORT)+'/private?token=secret'
        values=[good,good.replace(str(PORT),str(PORT+1)),good+'#',good.replace('127.0.0.1','user@127.0.0.1'),'',dual.GuiFailure('private error')]
        for value in values:
            report=activated()
            with self.subTest(valid=value==good),patch.object(dual,'auth_receiver_screen',return_value=post()), \
                    patch.object(dual,'private_handoff_file_state',return_value='readable'),patch.object(dual,'wait_for',side_effect=poll), \
                    patch.object(dual,'adb',side_effect=value if isinstance(value,Exception) else None,return_value=value) as adb:
                if value==good:self.assertEqual(dual.confirmed_private_handoff(PORT,report),good)
                else:
                    with self.assertRaises(dual.GuiFailure):dual.confirmed_private_handoff(PORT,report)
            self.assertEqual(adb.call_count,1)
            serialized=json.dumps(report)
            for private in ('secret','private error',str(PORT),'https://'):self.assertNotIn(private,serialized)

    def test_handoff_reader_cannot_run_before_confirmed_single_activation(self):
        with patch.object(dual,'auth_receiver_screen') as screen,patch.object(dual,'private_handoff_file_state') as files:
            with self.assertRaisesRegex(dual.GuiFailure,'dual_authorization_activation_unconfirmed'):
                dual.confirmed_private_handoff(PORT,{})
        screen.assert_not_called();files.assert_not_called()

    def test_file_state_uses_owned_directory_and_explicit_posix_enumerations(self):
        with tempfile.TemporaryDirectory(prefix='hp-consent-file-') as folder:
            root=Path(folder)
            def adb(*args,**kwargs):
                self.assertEqual(args[:6],('shell','run-as',dual.AUTH_PACKAGE,'sh','-c',args[5]))
                script=shlex.split(args[-1]);self.assertEqual(len(script),1)
                return subprocess.check_output(['sh','-c',script[0]],cwd=root,text=True)
            with patch.object(dual,'adb',side_effect=adb):
                self.assertEqual(dual.private_handoff_file_state(),'unavailable')
                (root/'files').mkdir();self.assertEqual(dual.private_handoff_file_state(),'missing')
                target=root/'files/approved-url';target.write_bytes(b'synthetic-private-content')
                self.assertEqual(dual.private_handoff_file_state(),'readable')
                if os.geteuid()!=0:
                    target.chmod(0);self.assertEqual(dual.private_handoff_file_state(),'unreadable');target.chmod(0o600)
                target.unlink();target.mkdir();self.assertEqual(dual.private_handoff_file_state(),'not_regular')
                target.rmdir();target.symlink_to(root/'not-present');self.assertEqual(dual.private_handoff_file_state(),'not_regular')
        with patch.object(dual,'adb',return_value='private unexpected stderr'):
            self.assertEqual(dual.private_handoff_file_state(),'unavailable')


if __name__=='__main__':unittest.main()
