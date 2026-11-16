import copy
import json
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock,patch
import tauri_android_dual_overlay as dual

PORT=43123
COMPONENT=dual.AUTH_PACKAGE+'/'+dual.AUTH_PACKAGE+'.AuthActivity'
LINKS=f'''{dual.AUTH_PACKAGE}:
  ID: private-id
  Signatures: [private-signature]
  Domain verification state:
    127.0.0.1: none
  User 0:
    Verification link handling allowed: true
    Selection state:
      Enabled:
        127.0.0.1
      Disabled:
'''

def consent_nodes(package=dual.AUTH_PACKAGE,port=PORT):
    return [ET.Element('node',{'package':package,'class':'android.widget.TextView',
                              'text':'隔离测试控制面：127.0.0.1:'+str(port)}),
            ET.Element('node',{'package':package,'class':'android.widget.Button','text':'批准本次测试授权',
                              'enabled':'true','bounds':'[10,20][30,40]'})]

def once(probe,code,**kwargs):
    value=probe()
    if not value:raise dual.GuiFailure(code)
    return value

class AuthRoutingTests(unittest.TestCase):
    def test_api35_user_selection_requires_exact_loopback_and_enabled_handling(self):
        self.assertEqual(dual.loopback_user_selection(LINKS),{'linkHandlingAllowed':True,'onlyLoopbackSelected':True})
        self.assertFalse(dual.loopback_user_selection(LINKS.replace('allowed: true','allowed: false'))['linkHandlingAllowed'])
        self.assertFalse(dual.loopback_user_selection(LINKS.replace('        127.0.0.1','        example.invalid'))['onlyLoopbackSelected'])
        self.assertFalse(dual.loopback_user_selection(LINKS.replace('      Disabled:','        other.invalid\n      Disabled:'))['onlyLoopbackSelected'])
        self.assertFalse(dual.loopback_user_selection(LINKS.replace('User 0:','User 10:'))['onlyLoopbackSelected'])

    def test_precise_selection_is_owned_and_ordinary_resolution_never_starts_a_url(self):
        report={};calls=[];positive_queries=0
        def adb(*args,**kwargs):
            nonlocal positive_queries
            calls.append(args)
            if args==('shell','am','get-current-user'):return '0'
            if args[:4]==('shell','cmd','package','resolve-activity'):
                if args[-1]=='https://example.invalid/':return 'com.android.chrome/com.google.android.apps.chrome.Main'
                positive_queries+=1
                return 'com.android.chrome/com.google.android.apps.chrome.Main' if positive_queries==1 else dual.AUTH_PACKAGE+'/.AuthActivity'
            if args[:3]==('shell','pm','get-app-links'):return LINKS
            if args[:3]==('shell','pm','set-app-links-user-selection'):return ''
            raise AssertionError(args)
        with patch.object(dual,'assert_owned_avd') as owned,patch.object(dual,'adb',side_effect=adb):
            dual.prepare_auth_receiver(PORT,report)
        owned.assert_called_once()
        selection=next(call for call in calls if 'set-app-links-user-selection' in call)
        self.assertEqual(selection,('shell','pm','set-app-links-user-selection','--user','0','--package',dual.AUTH_PACKAGE,'true','127.0.0.1'))
        self.assertFalse(any('start' in call or 'all' in call for call in calls))
        self.assertEqual(report['authHandler']['afterHandler'],'test_receiver')
        self.assertEqual(report['authHandler']['unrelatedHandler'],'browser')
        self.assertNotIn('private-',json.dumps(report));self.assertNotIn(str(PORT),json.dumps(report))

    def test_shell_success_without_confirmed_selection_is_not_accepted(self):
        with patch.object(dual,'assert_owned_avd'),patch.object(dual,'resolve_view_component',return_value=None), \
                patch.object(dual,'adb',side_effect=['0','',LINKS.replace('User 0:','User 10:')]):
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_auth_selection_unconfirmed$'):
                dual.prepare_auth_receiver(PORT,{})

    def test_unowned_device_is_rejected_before_selection(self):
        with patch.object(dual,'assert_owned_avd',side_effect=dual.GuiFailure('owned_avd_required')),patch.object(dual,'adb') as adb:
            with self.assertRaises(dual.GuiFailure):dual.prepare_auth_receiver(PORT,{})
        adb.assert_not_called()

    def test_foreground_parser_accepts_only_one_resumed_component(self):
        raw='topResumedActivity=ActivityRecord{abc u0 '+dual.AUTH_PACKAGE+'/.AuthActivity t4}\n'
        with patch.object(dual,'adb',return_value=raw):self.assertEqual(dual.foreground_component(),COMPONENT)
        raw+='mResumedActivity: ActivityRecord{def u0 com.android.chrome/.Main t5}\n'
        with patch.object(dual,'adb',return_value=raw):self.assertIsNone(dual.foreground_component())

class AuthConsentTests(unittest.TestCase):
    def test_consent_requires_exact_package_source_port_foreground_and_unique_button(self):
        point,state=dual.auth_consent_candidate(consent_nodes(),COMPONENT,PORT)
        self.assertEqual(point,(20,30));self.assertTrue(state['sourceMatched']);self.assertTrue(state['uniqueReceiverButton'])
        cases=[(consent_nodes('unrelated.app'),COMPONENT,PORT),
               (consent_nodes(),dual.PACKAGE+'/'+dual.PACKAGE+'.MainActivity',PORT),
               (consent_nodes(),COMPONENT,PORT+1)]
        duplicated=consent_nodes();duplicated.append(copy.deepcopy(duplicated[1]));cases.append((duplicated,COMPONENT,PORT))
        foreign=consent_nodes();foreign.append(consent_nodes('unrelated.app')[1]);cases.append((foreign,COMPONENT,PORT))
        disabled=consent_nodes();disabled[1].set('enabled','false');cases.append((disabled,COMPONENT,PORT))
        for nodes,foreground,port in cases:
            with self.subTest(foreground=foreground,port=port):
                self.assertIsNone(dual.auth_consent_candidate(nodes,foreground,port)[0])
        self.assertNotIn('127.0.0.1',json.dumps(state));self.assertNotIn(dual.AUTH_PACKAGE,json.dumps(state))

    def test_visible_consent_is_clicked_once_and_unknown_tap_is_never_replayed(self):
        for failed in (False,True):
            report={}
            with patch.object(dual,'native_ui_nodes',return_value=consent_nodes()), \
                    patch.object(dual,'foreground_component',return_value=COMPONENT),patch.object(dual,'wait_for',side_effect=once), \
                    patch.object(dual,'adb',side_effect=dual.GuiFailure('unknown tap') if failed else None) as adb:
                if failed:
                    with self.assertRaisesRegex(dual.GuiFailure,'^dual_authorization_tap_unconfirmed$'):
                        dual.approve_auth_receiver(PORT,report)
                else:dual.approve_auth_receiver(PORT,report)
            self.assertEqual(adb.call_count,1);self.assertEqual(adb.call_args.args,('shell','input','tap','20','30'))
            self.assertTrue(report['authorization']['tapSent'])
            self.assertEqual(report['authorization'].get('tapCompleted',False),not failed)

    def test_product_system_open_and_visible_consent_precede_private_handoff(self):
        order=[];report={};browser=Mock();browser.evaluate.return_value=True
        url='https://127.0.0.1:'+str(PORT)+'/auth/synthetic-token'
        def confirm(_browser,_scope,label,_expected):order.append('product-open' if label=='打开授权页面' else 'explicit-login')
        def approve(*args):order.append('visible-consent')
        def adb(*args,**kwargs):
            if 'cat' in args:order.append('read-private-handoff');return url
            order.append('return-product');return ''
        def host(*args):order.append('host-authorize');return {'ok':True}
        with patch.object(dual,'wait_named'),patch.object(dual,'confirm_click',side_effect=confirm), \
                patch.object(dual,'approve_auth_receiver',side_effect=approve),patch.object(dual,'adb',side_effect=adb), \
                patch.object(dual,'host_request',side_effect=host),patch.object(dual,'wait_for',side_effect=once):
            dual.authorize_ts(browser,Mock(),'owned-scope',PORT,report)
        self.assertEqual(order,['explicit-login','product-open','visible-consent','read-private-handoff','host-authorize','return-product'])
        self.assertNotIn('synthetic-token',json.dumps(report));self.assertNotIn(str(PORT),json.dumps(report))
        self.assertTrue(report['authorization']['hostAuthorizationConfirmed'])

if __name__=='__main__':unittest.main()
