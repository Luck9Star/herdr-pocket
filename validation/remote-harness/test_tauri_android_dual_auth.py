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
    127.0.0.1: approved
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
            if args[:4]==('shell','cmd','package','query-activities'):
                return 'com.android.chrome/com.google.android.apps.chrome.Main'+('\n'+COMPONENT if args[-1]!='https://example.invalid/' else '')
            if args[:3]==('shell','pm','get-app-links'):return LINKS
            if args[:3]==('shell','pm','set-app-links'):return ''
            raise AssertionError(args)
        with patch.object(dual,'assert_owned_avd') as owned,patch.object(dual,'adb',side_effect=adb):
            dual.prepare_auth_receiver(PORT,report)
        owned.assert_called_once()
        selection=next(call for call in calls if 'set-app-links' in call)
        self.assertEqual(selection,('shell','pm','set-app-links','--package',dual.AUTH_PACKAGE,'2','127.0.0.1'))
        self.assertFalse(any('start' in call or 'all' in call for call in calls))
        self.assertEqual(report['authHandler']['afterHandler'],'test_receiver')
        self.assertEqual(report['authHandler']['unrelatedHandler'],'browser')
        self.assertNotIn('private-',json.dumps(report));self.assertNotIn(str(PORT),json.dumps(report))

    def test_shell_success_without_confirmed_selection_is_not_accepted(self):
        with patch.object(dual,'assert_owned_avd'),patch.object(dual,'resolve_view_component',return_value=None), \
                patch.object(dual,'adb',side_effect=['0','',LINKS.replace('User 0:','User 10:')]):
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_auth_app_link_unconfirmed$'):
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
                patch.object(dual,'choose_auth_receiver',side_effect=lambda *args:order.append('system-choice')), \
                patch.object(dual,'approve_auth_receiver',side_effect=approve),patch.object(dual,'adb',side_effect=adb), \
                patch.object(dual,'host_request',side_effect=host),patch.object(dual,'wait_for',side_effect=once):
            dual.authorize_ts(browser,Mock(),'owned-scope',PORT,report)
        self.assertEqual(order,['explicit-login','product-open','system-choice','visible-consent','read-private-handoff','host-authorize','return-product'])
        self.assertNotIn('synthetic-token',json.dumps(report));self.assertNotIn(str(PORT),json.dumps(report))
        self.assertTrue(report['authorization']['hostAuthorizationConfirmed'])


RESOLVER='android/com.android.internal.app.ResolverActivity'
def resolver_nodes(selected=False,enabled=False,caption='Just once',package='android',default=False):
    root=ET.Element('node',{'package':package})
    def node(parent,resource,**extra):
        attrs={'package':package,'resource-id':'android:id/'+resource,'enabled':'true','bounds':'[10,20][30,40]'}
        attrs.update(extra);return ET.SubElement(parent,'node',attrs)
    listing=node(root,'resolver_list')
    if default:node(root,'title',text='Open with 双网测试授权')
    else:
        row=node(listing,'row',selected=str(selected).lower())
        node(row,'text1',text='双网测试授权')
    other=node(listing,'row');node(other,'text1',text='Chrome')
    node(root,'button_once',text=caption,enabled=str(enabled).lower(),**{'class':'android.widget.Button'})
    node(root,'button_always',text='Always',**{'class':'android.widget.Button'})
    return list(root.iter('node'))
def bounded(probe,code,**kwargs):
    for _ in range(5):
        if probe():return True
    raise dual.GuiFailure(code)
class ResolverTests(unittest.TestCase):
    def test_app_link_state_requires_exact_declared_host_and_approved_state(self):
        self.assertTrue(dual.loopback_app_link_approved(LINKS))
        invalid=[LINKS.replace(': approved',': none'),LINKS.replace(': approved',': verified'),
                 LINKS.replace('127.0.0.1: approved','example.invalid: approved'),
                 LINKS.replace('127.0.0.1: approved','127.0.0.1: approved\n    example.invalid: approved'),
                 LINKS.replace('127.0.0.1: approved','127.0.0.1: approved\n    127.0.0.1: approved')]
        for raw in invalid:
            self.assertFalse(dual.loopback_app_link_approved(raw))
            with patch.object(dual,'assert_owned_avd'),patch.object(dual,'resolve_view_component',return_value=RESOLVER), \
                    patch.object(dual,'adb',side_effect=['0','',raw]):
                with self.assertRaisesRegex(dual.GuiFailure,'^dual_auth_app_link_unconfirmed$'):dual.prepare_auth_receiver(PORT,{})
    def test_receiver_manifest_has_only_exact_loopback_autoverify_filter(self):
        from pathlib import Path
        manifest=ET.parse(Path(dual.__file__).parent/'tauri-dual-auth-receiver/AndroidManifest.xml').getroot()
        android='{http://schemas.android.com/apk/res/android}'
        filters=manifest.findall('./application/activity/intent-filter')
        self.assertEqual(len(filters),1);self.assertEqual(filters[0].get(android+'autoVerify'),'true')
        self.assertEqual([x.attrib for x in filters[0].findall('data')],[{android+'scheme':'https',android+'host':'127.0.0.1'}])

    def test_api35_app_link_requires_exact_post_selection_resolution_and_candidate_scope(self):
        for resolved in (COMPONENT,RESOLVER):
            report={}
            with patch.object(dual,'assert_owned_avd'),patch.object(dual,'resolve_view_component',side_effect=[resolved,COMPONENT,'com.android.chrome/.Main']), \
                    patch.object(dual,'adb',side_effect=['0','',LINKS]), \
                    patch.object(dual,'query_view_components',side_effect=[{COMPONENT,'com.android.chrome/.Main'}, {'com.android.chrome/.Main'}]):
                dual.prepare_auth_receiver(PORT,report)
            self.assertTrue(report['authHandler']['receiverCandidate'])
            self.assertFalse(report['authHandler']['unrelatedReceiverCandidate'])
        for resolved,candidates in ((COMPONENT,(set(),set())),(COMPONENT,({COMPONENT},{COMPONENT})),
                                    (RESOLVER,({COMPONENT},set()))):
            with patch.object(dual,'assert_owned_avd'),patch.object(dual,'resolve_view_component',side_effect=[RESOLVER,resolved,'com.android.chrome/.Main']), \
                    patch.object(dual,'adb',side_effect=['0','',LINKS]),patch.object(dual,'query_view_components',side_effect=candidates):
                with self.assertRaisesRegex(dual.GuiFailure,'^dual_auth_handler_scope_mismatch$'):dual.prepare_auth_receiver(PORT,{})
    def test_exact_resolver_rows_then_once_and_already_selected_default(self):
        self.assertEqual(dual.resolver_receiver_action(resolver_nodes(),RESOLVER)[0],'row')
        for caption in ('Just once','JUST ONCE','仅此一次'):
            self.assertEqual(dual.resolver_receiver_action(resolver_nodes(True,True,caption),RESOLVER)[0],'once')
        self.assertEqual(dual.resolver_receiver_action(resolver_nodes(enabled=True),RESOLVER,True)[0],'once')
        self.assertEqual(dual.resolver_receiver_action(resolver_nodes(enabled=True,default=True),RESOLVER)[0],'once')
        nodes=resolver_nodes(True,True);action,point,state=dual.resolver_receiver_action(nodes,RESOLVER)
        self.assertEqual(point,(20,30));self.assertEqual(state['alwaysButtons'],1)
        self.assertNotIn('双网',json.dumps(state));self.assertNotIn('android',json.dumps(state))
    def test_foreign_duplicate_wrong_resource_and_always_are_not_clicked(self):
        cases=[(resolver_nodes(True,True),'other.app/.ResolverActivity',False),
               (resolver_nodes(True,True,package='other.app'),RESOLVER,False)]
        nodes=resolver_nodes(True,True);label=next(n for n in nodes if n.get('text')=='双网测试授权')
        label.set('resource-id','android:id/wrong');cases.append((nodes,RESOLVER,True))
        nodes=resolver_nodes(True,True);row=next(n for n in nodes if n.get('resource-id')=='android:id/row')
        row.append(copy.deepcopy(next(n for n in nodes if n.get('text')=='双网测试授权')))
        nodes=list(nodes[0].iter('node'));cases.append((nodes,RESOLVER,True))
        nodes=resolver_nodes(True,True)
        for n in nodes:
            if n.get('resource-id')=='android:id/button_once':n.set('resource-id','android:id/button_always')
        cases.append((nodes,RESOLVER,True))
        nodes=resolver_nodes(True,True);rows=[n for n in nodes if n.get('resource-id')=='android:id/row'];rows[1].set('selected','true')
        cases.append((nodes,RESOLVER,True))
        for nodes,foreground,tapped in cases:
            with self.subTest(foreground=foreground):self.assertIsNone(dual.resolver_receiver_action(nodes,foreground,tapped)[0])
    def test_actual_foreground_supports_two_step_direct_row_and_no_chooser(self):
        for fore,frames,taps in (([RESOLVER,RESOLVER,COMPONENT],[resolver_nodes(),resolver_nodes(True,True)],2),
                                ([RESOLVER,COMPONENT],[resolver_nodes()],1),([COMPONENT],[],0),
                                ([RESOLVER,COMPONENT],[resolver_nodes(True,True)],1)):
            report={'authHandler':{'receiverCandidate':True,'unrelatedReceiverCandidate':False}}
            with patch.object(dual,'foreground_component',side_effect=fore),patch.object(dual,'native_ui_nodes',side_effect=frames), \
                    patch.object(dual,'wait_for',side_effect=bounded),patch.object(dual,'adb') as adb:
                dual.choose_auth_receiver(report)
            self.assertEqual(adb.call_count,taps)
            self.assertTrue(report['authorization']['chooser']['receiverForeground'])
    def test_unknown_tap_or_still_visible_chooser_never_replays(self):
        for failed in (False,True):
            report={'authHandler':{'receiverCandidate':True,'unrelatedReceiverCandidate':False}}
            with patch.object(dual,'foreground_component',return_value=RESOLVER),patch.object(dual,'native_ui_nodes',return_value=resolver_nodes()), \
                    patch.object(dual,'wait_for',side_effect=bounded),patch.object(dual,'adb',side_effect=dual.GuiFailure('private') if failed else None) as adb:
                expected='dual_authorization_resolver_tap_unconfirmed' if failed else 'dual_authorization_resolver_missing'
                with self.assertRaisesRegex(dual.GuiFailure,'^'+expected+'$'):dual.choose_auth_receiver(report)
            self.assertEqual(adb.call_count,1)
            self.assertNotIn('private',json.dumps(report))
    def test_default_title_must_be_outside_list_and_scope_is_required(self):
        nodes=resolver_nodes(enabled=True,default=True);title=next(n for n in nodes if n.get('resource-id')=='android:id/title')
        nodes[0].remove(title);next(n for n in nodes if n.get('resource-id')=='android:id/resolver_list').append(title)
        self.assertIsNone(dual.resolver_receiver_action(list(nodes[0].iter('node')),RESOLVER)[0])
        with patch.object(dual,'adb') as adb:
            with self.assertRaisesRegex(dual.GuiFailure,'^dual_auth_candidate_scope_missing$'):dual.choose_auth_receiver({})
        adb.assert_not_called()
    def test_failure_host_counts_exclude_private_session_data_and_unknown_is_not_zero(self):
        value={'acceptedSessions':1,'capturedBytes':12,'private':'secret',
               'sessions':[{'approvedDevice':True,'active':True,'fingerprint':'private-key'}]}
        with patch.object(dual,'host_request',return_value=value):result=dual.public_host_failure_counts(Mock())
        self.assertEqual(result['ts'],{'available':True,'acceptedSessions':1,'capturedBytes':12,'approvedSessionObserved':True,'activeSessions':1})
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('secret',json.dumps(result))
        with patch.object(dual,'host_request',return_value={'acceptedSessions':True}):result=dual.public_host_failure_counts(Mock())
        self.assertEqual(result,{'ts':{'available':False},'et':{'available':False}})

if __name__=='__main__':unittest.main()
