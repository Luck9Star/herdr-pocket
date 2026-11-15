#!/usr/bin/env python3
"""Tauri API35 dual overlay test; actual UI only, ephemeral host-side fixture."""
import base64
import json
import os
from pathlib import Path
import queue
import re
import select
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from android_gui import AndroidWebView, PACKAGE, SERIAL, adb
from android_dual_overlay_reverse import assert_owned_avd
from paired_gui import GuiFailure, wait_for

AUTH_PACKAGE = 'dev.herdrpocket.dualtestauth'


class ConfirmingWebView(AndroidWebView):
    """Accept only the confirmation resulting from the real, reviewed UI click."""
    def __init__(self, port):
        super().__init__(port)
        self.expectedConfirmation = None
        self.confirmationObserved = False
        self.confirmDiagnostic = {}
        self.confirmationHistory = []
        self.ws.settimeout(45)
        self.call('Page.enable')
        url=self.evaluate('location.href')
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https','tauri') or parsed.hostname not in ('tauri.localhost','localhost'):
            raise GuiFailure('dual_webview_origin_invalid')
        self.pageOrigin=(parsed.scheme,parsed.hostname,parsed.port)

    def call(self, method, params=None):
        self.sequence += 1
        ident = self.sequence
        try:
            self.ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
            while True:
                frame = self.ws.recv()
                if len(frame) > 1048576:raise GuiFailure('android_cdp_output_limit')
                reply = json.loads(frame)
                if reply.get('method') == 'Page.javascriptDialogOpening':
                    dialog = reply.get('params', {})
                    source=urlsplit(dialog.get('url',''))
                    origin=(source.scheme,source.hostname,source.port)
                    handler=dialog.get('hasBrowserHandler')
                    self.confirmDiagnostic={'dialogEvent':True,'originMatched':origin==self.pageOrigin,
                                            'expectedTextMatched':isinstance(dialog.get('message'),str) and
                                                self.expectedConfirmation is not None and self.expectedConfirmation in dialog['message'],
                                            'hasBrowserHandler':handler is True}
                    if (self.expectedConfirmation is None or self.confirmationObserved or
                            dialog.get('type') != 'confirm' or origin!=self.pageOrigin or
                            not self.confirmDiagnostic['expectedTextMatched']):
                        raise GuiFailure('dual_unexpected_confirmation')
                    native = {}
                    clicked=native_dialog_click(self.expectedConfirmation, {'OK','确定'}, timeout=20, diagnostic=native)
                    self.confirmDiagnostic.update(nativeXmlParsed=native.get('xmlParsed') is True,
                        nativeExpectedVisible=native.get('expectedSeen') is True,
                        nativeButtonVisible=native.get('uniqueButton') is True,
                        nativeClicked=native.get('clicked') is True)
                    if not clicked:
                        raise GuiFailure('dual_confirmation_not_user_visible')
                    self.confirmationHistory.append(dict(self.confirmDiagnostic))
                    self.confirmationObserved = True
                    continue
                if reply.get('id') != ident:continue
                if 'error' in reply:raise GuiFailure('android_cdp_command_failed')
                return reply.get('result', {})
        except GuiFailure:raise
        except Exception:raise GuiFailure('android_cdp_transport_failed') from None


def host_request(control, request, expected):
    value = control.call(request)
    if not isinstance(value, dict) or value.get('event') != expected:
        raise GuiFailure('dual_host_event_unexpected')
    return value


def checked_audit(value, expected_length, *, ordinal, sessions_count, active, new_sessions=0):
    sessions = value.get('sessions')
    if (value.get('acceptedSessions') != sessions_count or value.get('newSessions') != new_sessions or
            value.get('exactBytes') is not True or value.get('capturedBytes') != expected_length or
            not isinstance(sessions, list) or len(sessions) != sessions_count):
        return False
    matching = [entry for entry in sessions if entry.get('ordinal') == ordinal]
    return (len(matching) == 1 and matching[0].get('approvedDevice') is True and
            matching[0].get('active') is active and
            sum(entry.get('active') is True for entry in sessions) == int(active))


def audit(host, role, expected, *, ordinal, sessions_count, active=True, new_sessions=0):
    def sample():
        value = host_request(host, {'op':'audit', 'role':role,
            'expectedBase64':base64.b64encode(expected).decode('ascii')}, 'host_audit')
        # Count and ordinal are checked on every poll, so a reconnect cannot be
        # hidden by a later newSessions=0 after the controller advances its cursor.
        if (value.get('acceptedSessions') != sessions_count or value.get('newSessions') != new_sessions or
                not isinstance(value.get('capturedBytes'), int) or value['capturedBytes'] > len(expected)):
            raise GuiFailure('dual_peer_evidence_mismatch')
        if value['capturedBytes'] == len(expected) and value.get('exactBytes') is not True:
            raise GuiFailure('dual_peer_evidence_mismatch')
        return value if checked_audit(value, len(expected), ordinal=ordinal, sessions_count=sessions_count,
                                      active=active, new_sessions=new_sessions) else None
    return wait_for(sample, 'dual_peer_evidence_timeout', timeout=30)


def native_ui_nodes():
    # The AVD is owned and disposable. Dump only to one fixed shell-private
    # path; never publish XML, and remove it even when parsing fails.
    dump_path='/data/local/tmp/herdr-dual-ui.xml'
    try:
        adb('shell','uiautomator','dump',dump_path,timeout=15)
        xml=adb('shell','cat',dump_path,timeout=5)
        start=xml.find('<?xml')
        if start < 0:raise GuiFailure('dual_native_ui_xml_missing')
        root=ET.fromstring(xml[start:xml.rfind('>')+1])
        return list(root.iter('node'))
    finally:
        adb('shell','rm','-f',dump_path,check=False,timeout=5)


def ordinary_native_tree(nodes):
    return {'xmlParsed':True,'nodeCount':min(len(nodes),999),
            'ownedWebView':any(node.get('package')==PACKAGE and
                node.get('class','').endswith('WebView') for node in nodes)}


def native_dialog_click(expected, button, *, timeout=20, cancelled=None, diagnostic=None):
    """Read the actual system dialog and click its uniquely labeled visible button."""
    deadline = time.monotonic() + timeout
    if diagnostic is None: diagnostic = {}
    diagnostic.update(attempts=0,xmlParsed=False,expectedSeen=False,uniqueButton=False,clicked=False)
    while time.monotonic() < deadline and not (cancelled and cancelled.is_set()):
        try:
            diagnostic['attempts'] += 1
            nodes = native_ui_nodes()
            diagnostic['xmlParsed']=True
            if not any(expected in (n.get('text') or '') for n in nodes):
                continue
            diagnostic['expectedSeen']=True
            buttons = [n for n in nodes if n.get('text') in button and n.get('enabled') == 'true']
            if len(buttons) != 1:
                continue
            diagnostic['uniqueButton']=True
            match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', buttons[0].get('bounds', ''))
            if not match:
                continue
            x1, y1, x2, y2 = map(int, match.groups())
            if x2 <= x1 or y2 <= y1:
                continue
            if cancelled and cancelled.is_set():
                return False
            adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
            diagnostic['clicked']=True
            return True
        except (GuiFailure, ET.ParseError, ValueError):
            pass
    return False


def confirm_click(browser, scope, label, expected):
    """Activate a real button and confirm the exact native WebView dialog."""
    if browser.expectedConfirmation is not None:
        raise GuiFailure('dual_confirmation_already_pending')
    browser.expectedConfirmation=expected
    browser.confirmationObserved=False
    try:
        browser.click_named(scope,label,'dual_button_unavailable')
        if not browser.confirmationObserved:
            browser.call('Runtime.evaluate',{'expression':'true','returnByValue':True})
        if not browser.confirmationObserved:
            raise GuiFailure('dual_confirmation_not_observed')
    finally:
        browser.expectedConfirmation=None


def profile_scope(browser, name):
    expression = '''(()=>{const all=[...document.querySelectorAll('#network-panel > article.network-profile-card')];
      const matches=all.map((e,i)=>({e,i})).filter(x=>x.e.querySelector('h3')?.textContent.trim()===%s);
      return matches.length===1 ? '#network-panel > article.network-profile-card:nth-of-type('+(matches[0].i+1)+')' : null})()''' % json.dumps(name)
    return wait_for(lambda: browser.evaluate(expression), 'dual_profile_missing', timeout=60)


def expand_profile(browser, title):
    scope = profile_scope(browser, title)
    if browser.evaluate('!!document.querySelector(%s)?.open' % json.dumps(scope+' details')) is not True:
        browser.click(scope+' details summary')
    return scope


def wait_named(browser, scope, text, timeout=60):
    expr = '''(()=>{const e=document.querySelector(%s);if(!e)return false;
      return [...e.querySelectorAll('button')].some(b=>b.textContent.trim()===%s&&!b.disabled&&b.getClientRects().length)})()''' % (json.dumps(scope), json.dumps(text))
    return wait_for(lambda: browser.evaluate(expr) is True, 'dual_action_unavailable', timeout=timeout)


def public_transport_sample(session):
    value=session.control.call({'op':'ts_diagnostics'})
    keys=('keyRequests','noiseRequests','registerRequests','mapRequests','tlsHandshakeErrors','authCompletions')
    if (not isinstance(value,dict) or value.get('event')!='ts_diagnostics' or
            any(type(value.get(key)) is not int or not 0<=value[key]<=1000000 for key in keys) or
            type(value.get('secondClientRegistered')) is not bool):
        raise GuiFailure('dual_host_diagnostics_invalid')
    stats=session.relay.stats()
    expected={'accepted','upstreamBytes','downstreamBytes','workerFailures'}
    if (set(stats)!={'control','derp','easytier'} or any(set(row)!=expected or
            any(type(n) is not int or not 0<=n<=1000000 for n in row.values()) for row in stats.values())):
        raise GuiFailure('dual_relay_diagnostics_invalid')
    return {'host':{key:value[key] for key in (*keys,'secondClientRegistered')},'relay':stats}


def create_network(browser, role, material, report):
    report['stage']='network_'+role+'_form'
    browser.click_named('#network-panel', '新增网络配置', 'dual_add_network_missing')
    browser.fill('.network-editor > label:first-of-type input', 'QA TS' if role == 'ts' else 'QA ET')
    browser.select_option('.network-editor > label:nth-of-type(2) select', 'tailscale' if role == 'ts' else 'easytier')
    if role == 'ts':
        browser.fill('.network-editor > div > label:first-of-type input', material['controlUrl'])
    else:
        browser.fill('.network-editor > div > label:first-of-type input', material['etNetwork']['networkName'])
        browser.fill('.network-editor > div > label:nth-of-type(2) textarea', material['etNetwork']['peerUrl'])
    browser.click('.network-editor button[type=submit]')
    report['stage']='network_'+role+'_save'
    title = 'QA TS · Tailscale' if role == 'ts' else 'QA ET · EasyTier'
    scope = wait_for(lambda: profile_scope(browser, title), 'dual_profile_create_failed', timeout=60)
    expand_profile(browser, title)
    wait_named(browser, scope, '配置本机身份')
    report['stage']='network_'+role+'_identity'
    if role == 'ts':
        confirm_click(browser, scope, '配置本机身份', '创建本机加密设备状态')
    else:
        browser.click_named(scope, '配置本机身份')
        browser.fill('.network-editor input[type=password]', material['etNetwork']['networkSecret'])
        confirm_click(browser, '.network-editor', '保存本机身份', '保存本机网络身份')
    wait_named(browser, scope, '启动节点', timeout=90)
    report['stage']='network_'+role+'_start'
    confirm_click(browser, scope, '启动节点', '启动 QA ')
    wait_named(browser, scope, '停止节点', timeout=90)
    return scope


def authorize_ts(browser, host, scope):
    wait_named(browser, scope, '登录 Tailscale', timeout=120)
    confirm_click(browser, scope, '登录 Tailscale', '显式发起登录')
    wait_named(browser, scope, '打开授权页面', timeout=120)
    confirm_click(browser, scope, '打开授权页面', '通过系统打开')
    # The optional resolver and this purpose-built activity are visible system UI.
    chosen = native_dialog_click('双网测试授权', {'双网测试授权'}, timeout=5)
    if chosen:
        native_dialog_click('双网测试授权', {'仅此一次','Just once'}, timeout=5)
    if not native_dialog_click('隔离测试控制面', {'批准本次测试授权'}, timeout=30):
        raise GuiFailure('dual_authorization_receiver_missing')
    url = wait_for(lambda: adb('shell','run-as',AUTH_PACKAGE,'cat','files/approved-url',check=False),
                   'dual_authorization_handoff_missing', timeout=30)
    if host_request(host, {'op':'complete_ts_auth','authorize':True,'url':url}, 'ts_authorized').get('ok') is not True:
        raise GuiFailure('dual_authorization_unconfirmed')
    adb('shell','monkey','-p',PACKAGE,'-c','android.intent.category.LAUNCHER','1')
    return True


def pair_host(browser, host, role, profile):
    browser.click('#host-open-remote')
    browser.click('#add-herdr')
    browser.fill('#connection-profile-raw', json.dumps(profile, ensure_ascii=False, separators=(',', ':')))
    browser.click('#connection-profile-preview')
    fingerprint = wait_for(lambda: browser.read('#connection-profile-fingerprint'), 'dual_profile_review_missing')
    browser.click('#connection-profile-apply')
    browser.click('#pair-target-review')
    browser.click('#pair-create')
    request = wait_for(lambda: browser.read('#pair-request','value'), 'dual_pair_request_missing', timeout=90)
    review = host_request(host, {'op':'review_pairing','role':role,'request':request}, 'pairing_review')
    summary = browser.read('#pair-request-summary') or ''
    if (review.get('hostFingerprint') not in fingerprint or
            review.get('deviceFingerprint') not in summary or review.get('requestId') not in summary):
        raise GuiFailure('dual_pair_review_mismatch')
    approved = host_request(host, {'op':'approve_pairing','role':role,'request':request,
        'requestId':review['requestId'],'deviceFingerprint':review['deviceFingerprint'],
        'reviewed':True}, 'pairing_approved')
    browser.fill('#pair-response', approved['response'])
    browser.click('#pair-preview')
    browser.click('#pair-source-review')
    browser.click('#pair-accept')
    wait_for(lambda:'授权响应已审查' in (browser.read('#pair-status') or ''), 'dual_pair_accept_missing', timeout=90)
    browser.fill('#host-save-name', 'QA host '+role.upper())
    browser.click('#host-save')
    wait_for(lambda:'已保存' in (browser.read('#host-save-status') or ''), 'dual_host_save_missing', timeout=90)
    browser.click('#host-return-home')


def bind_host(browser, role):
    name = 'QA host '+role.upper()
    expression = '''(()=>{const rows=[...document.querySelectorAll('#network-panel .network-binding')];
      const found=rows.map((e,i)=>({e,i})).filter(x=>x.e.querySelector('strong')?.textContent===%s);
      return found.length===1?'#network-panel .network-binding:nth-of-type('+(found[0].i+1)+')':null})()''' % json.dumps(name)
    scope = wait_for(lambda:browser.evaluate(expression), 'dual_binding_row_missing')
    label = 'QA TS · tailscale' if role == 'ts' else 'QA ET · easytier'
    option = wait_for(lambda:browser.evaluate('''(()=>{const s=document.querySelector(%s);if(!s)return null;
      const a=[...s.options].filter(o=>o.textContent===%s&&!o.disabled);return a.length===1?a[0].value:null})()''' % (json.dumps(scope+' select'),json.dumps(label))),
      'dual_binding_option_missing')
    browser.select_option(scope+' select', option)
    confirm_click(browser, scope, '应用', '更改 '+name+' 的网络绑定')
    wait_for(lambda:browser.read(scope+' select','value') == option, 'dual_binding_save_missing', timeout=60)


def host_card(browser, role):
    expression = '''(()=>{const all=[...document.querySelectorAll('#host-list > article.saved-host-card')];
      const found=all.map((e,i)=>({e,i})).filter(x=>x.e.querySelector('h3')?.textContent===%s);
      return found.length===1?'#host-list > article.saved-host-card:nth-of-type('+(found[0].i+1)+')':null})()''' % json.dumps('QA host '+role.upper())
    return wait_for(lambda:browser.evaluate(expression), 'dual_host_card_missing')


def find_tab(browser, role):
    expression = """(()=>{const all=[...document.querySelectorAll('#view-tabs > button')];
      const found=all.map((e,i)=>({e,i})).filter(x=>x.e.textContent.startsWith(%s));
      return found.length===1?'#view-tabs > button:nth-of-type('+(found[0].i+1)+')':null})()""" % json.dumps('QA host '+role.upper()+' ·')
    return browser.evaluate(expression)


def select_tab(browser, role):
    selector = wait_for(lambda:find_tab(browser, role), 'dual_tab_missing')
    browser.click(selector)
    wait_for(lambda:browser.evaluate('document.querySelector(%s)?.getAttribute("aria-pressed")==="true"' % json.dumps(selector)),
             'dual_tab_selection_unconfirmed')


def guard_stale_target(browser, role):
    if not find_tab(browser,role):
        # Never type into the surviving tab when the old tab is gone.
        return 'removed_tab_unreachable'
    select_tab(browser,role)
    enabled = browser.evaluate("[...document.querySelectorAll('#view-content .tab-mobile-controls button')].some(b=>!b.disabled&&['逐键输入','启用草稿输入','发送草稿'].includes(b.textContent.trim()))")
    if enabled is not False:
        raise GuiFailure('dual_stopped_input_still_enabled')
    browser.call('Input.insertText', {'text':'STALE'})
    return 'retained_tab_disabled_keyboard_tested'


def open_tab(browser, role):
    browser.click('#show-remote')
    scope = host_card(browser, role)
    browser.click(scope+' details.host-manage summary')
    browser.click_named(scope, '新终端标签', 'dual_open_tab_missing')
    wait_for(lambda:browser.evaluate("!document.querySelector('#tab-workspace').hidden"), 'dual_workspace_missing')
    browser.click('#view-content > label input[type=checkbox]')
    browser.click_named('#view-content .tab-connection-actions', '连接', 'dual_connect_missing')
    pane = wait_for(lambda:browser.evaluate('''(()=>{const p=[...document.querySelectorAll('#view-content .session-dashboard button[data-pane-id]')].filter(e=>!e.disabled);
      return p.length===1?{pane:p[0].dataset.paneId,terminal:p[0].dataset.terminalId}:null})()'''),
      'dual_dashboard_missing',timeout=120)
    if not pane.get('pane') or not pane.get('terminal'):
        raise GuiFailure('dual_target_missing')
    browser.click('#view-content .session-dashboard button[data-pane-id]')
    wait_for(lambda:'当前观察画面' in (browser.read('#view-content .tab-frame-status') or ''),
             'dual_full_missing',timeout=90)
    wait_named(browser, '#view-content', '启用草稿输入', timeout=60)
    return pane


def rendered_marker_expression(marker):
    # Match one rendered row, normalizing xterm's non-breaking spaces. Do not
    # concatenate adjacent rows into a marker that never appeared on screen.
    return """(()=>[...document.querySelectorAll('#view-content .xterm-rows > div')]
      .some(row=>row.getClientRects().length>0 && row.textContent.replace(/\u00a0/g,' ').includes(%s)))()""" % json.dumps(marker)


def rendered_marker(browser, marker):
    return browser.evaluate(rendered_marker_expression(marker)) is True


def send_draft(browser, value):
    browser.click_named('#view-content', '启用草稿输入', 'dual_draft_mode_missing')
    wait_for(lambda:browser.evaluate("document.querySelector('#view-content .tab-mobile-controls')?.dataset.mode==='draft'"),
             'dual_draft_not_enabled')
    browser.fill('#view-content .tab-draft-field', value)
    confirm_click(browser, '#view-content', '发送草稿', '发送到 QA host')
    wait_for(lambda:browser.evaluate("!!document.querySelector('#view-content details[data-role=input-receipt]:not([hidden])' )"),
             'dual_input_receipt_missing',timeout=90)


def baseline(host, role, expected):
    def sample():
        value = host_request(host, {'op':'audit', 'role':role,
            'expectedBase64':base64.b64encode(expected).decode('ascii')}, 'host_audit')
        sessions=value.get('sessions')
        count=value.get('capturedBytes')
        if not isinstance(count,int) or count > len(expected) or not isinstance(sessions,list):
            raise GuiFailure('dual_baseline_invalid')
        if count != len(expected):
            return None
        if value.get('exactBytes') is not True:
            raise GuiFailure('dual_baseline_invalid')
        live=[item for item in sessions if item.get('active') is True and item.get('approvedDevice') is True]
        if len(live)!=1 or sum(item.get('active') is True for item in sessions)!=1 or value.get('acceptedSessions')!=len(sessions):
            raise GuiFailure('dual_baseline_session_invalid')
        return (live[0]['ordinal'],len(sessions))
    return wait_for(sample,'dual_baseline_timeout',timeout=30)


def run_direction(apk, auth_apk, session, stopped, report):
    control, material = session.control, session.materials
    from android_dual_overlay_reverse import _adb
    from urllib.parse import urlsplit
    assert_owned_avd()
    for package in (PACKAGE, AUTH_PACKAGE):
        if 'package:'+package in adb('shell','pm','list','packages',package).splitlines():
            raise GuiFailure('dual_package_already_installed')
    parsed = urlsplit(material['controlUrl'])
    if parsed.scheme!='https' or parsed.hostname!='127.0.0.1' or parsed.port is None:
        raise GuiFailure('dual_control_origin_invalid')
    installed=[];forward=None;browser=None
    try:
        report['stage']='device_setup'
        for path,package in ((apk,PACKAGE),(auth_apk,AUTH_PACKAGE)):
            adb('install','-t',str(path),timeout=120);installed.append(package)
        adb('shell','run-as',PACKAGE,'mkdir','-p','files/empty-dual-overlay-ca')
        adb('shell','run-as',PACKAGE,'touch','files/enable-dual-overlay-private-ca')
        _adb('shell','-T','run-as',PACKAGE,'tee','files/dual-overlay-ca.pem',input_data=session.read_ca())
        adb('shell','run-as',AUTH_PACKAGE,'mkdir','-p','files')
        _adb('shell','-T','run-as',AUTH_PACKAGE,'tee','files/port',input_data=str(parsed.port).encode())
        adb('shell','monkey','-p',PACKAGE,'-c','android.intent.category.LAUNCHER','1')
        pid=wait_for(lambda:adb('shell','pidof',PACKAGE,check=False), 'dual_app_missing',timeout=60)
        if not re.fullmatch(r'\d+',pid):raise GuiFailure('dual_app_pid_invalid')
        socket_name='webview_devtools_remote_'+pid
        wait_for(lambda:'@'+socket_name in adb('shell','cat','/proc/net/unix',check=False), 'dual_webview_socket_missing',timeout=60)
        port=adb('forward','tcp:0','localabstract:'+socket_name)
        if not port.isdigit() or not 1<=int(port)<=65535:raise GuiFailure('dual_forward_invalid')
        forward='tcp:'+port
        def connect():
            try:
                view=ConfirmingWebView(int(port))
                if view.evaluate("document.readyState==='complete' && !!document.querySelector('#nav-network') && !!window.__TAURI_INTERNALS__"):
                    return view
                view.close()
            except GuiFailure:pass
            return False
        browser=wait_for(connect,'dual_webview_not_ready',timeout=90)
        nodes=native_ui_nodes()
        report['ordinaryNativeTree']=ordinary_native_tree(nodes)
        report['ordinaryWebViewHomeVerified']=browser.read('.app-header h1')=='Herdr Pocket'
        if (len(nodes)<3 or not report['ordinaryNativeTree']['ownedWebView'] or
                not report['ordinaryWebViewHomeVerified']):
            raise GuiFailure('dual_native_ui_tree_incomplete')
        report['stage']='network_setup'
        report['transportBeforeNetwork']=public_transport_sample(session)
        browser.click('#nav-network')
        wait_for(lambda:browser.evaluate("!document.querySelector('#network-panel').hidden"),'dual_network_page_missing')
        ts_scope=create_network(browser,'ts',material,report)
        create_network(browser,'et',material,report)
        report['stage']='network_ts_authorize'
        authorize_ts(browser,control,ts_scope)
        wait_for(lambda:'Tailscale 报告 Running' in (browser.read(ts_scope) or ''), 'dual_ts_running_missing',timeout=120)
        report['tsExplicitAuthorization']=True
        report['stage']='pairing'
        browser.click('#show-remote')
        for role in ('ts','et'):
            pair_host(browser,control,role,session.read_host_profile(role))
        report['pairingApprovedBoth']=True
        browser.click('#nav-network')
        for role in ('ts','et'):
            bind_host(browser,role)
        report['bindingBoth']=True
        report['stage']='connect_and_input'
        targets={}
        for role in ('ts','et'):
            targets[role]=open_tab(browser,role)
            send_draft(browser, 'T' if role=='ts' else 'E')
            marker='Synthetic '+role.upper()+' ACK ONE'
            wait_for(lambda:rendered_marker(browser,marker), 'dual_first_ack_frame_missing',timeout=60)
        if targets['ts']==targets['et']:raise GuiFailure('dual_targets_not_distinct')
        initials={'ts':b'T','et':b'E'}
        baseline_values={role:baseline(control,role,initials[role]) for role in ('ts','et')}
        report['bothInputAndDistinctTargets']=True
        surviving='et' if stopped=='ts' else 'ts'
        # Visit the survivor immediately before stopping the other node.
        select_tab(browser,surviving)
        browser.click('#nav-network')
        scope=expand_profile(browser,'QA TS · Tailscale' if stopped=='ts' else 'QA ET · EasyTier')
        confirm_click(browser,scope,'停止节点','停止 QA ')
        wait_named(browser,scope,'启动节点',timeout=120)
        report['stage']='post_stop'
        ordinal,count=baseline_values[surviving]
        audit(control,surviving,initials[surviving],ordinal=ordinal,sessions_count=count)
        browser.click('#nav-terminal')
        select_tab(browser,surviving)
        wait_named(browser,'#view-content .tab-connection-actions','恢复观察',timeout=60)
        browser.click_named('#view-content .tab-connection-actions','恢复观察')
        wait_for(lambda:'当前观察画面' in (browser.read('#view-content .tab-frame-status') or ''),
                 'dual_resumed_full_missing',timeout=90)
        second=b't' if surviving=='ts' else b'e'
        send_draft(browser,second.decode())
        marker='Synthetic '+surviving.upper()+' ACK TWO'
        wait_for(lambda:rendered_marker(browser,marker), 'dual_second_ack_frame_missing',timeout=60)
        audit(control,surviving,initials[surviving]+second,ordinal=ordinal,sessions_count=count)
        report['survivorSameAuthenticatedSession']=True
        report['staleInputGuard']=guard_stale_target(browser,stopped)
        prior_ordinal,prior_count=baseline_values[stopped]
        audit(control,stopped,initials[stopped],ordinal=prior_ordinal,sessions_count=prior_count,active=False)
        audit(control,surviving,initials[surviving]+second,ordinal=ordinal,sessions_count=count)
        report['stoppedInputUnavailableAndUnchanged']=True
        report['stage']='complete'
    except Exception as error:
        try:report['transportAtFailure']=public_transport_sample(session)
        except Exception:report['transportAtFailureUnavailable']=True
        if browser:
            diagnostic=getattr(browser,'confirmDiagnostic',None)
            if isinstance(diagnostic,dict):
                report['confirmationDiagnostic']={key:value for key,value in diagnostic.items() if key in ('dialogEvent','originMatched','expectedTextMatched','hasBrowserHandler','nativeXmlParsed','nativeExpectedVisible','nativeButtonVisible','nativeClicked') and type(value) in (bool,int)}
            try:
                report['uiDiagnostic']=browser.evaluate("""(()=>{const p=document.querySelector('#network-panel'),f=p?.querySelector('.network-editor');
                  const c=p?.querySelector('.network-profile-card'),text=c?.textContent||'',status=p?.querySelector('[role=status]')?.textContent||'';
                  const labels=['节点启动中','节点正在停止','Tailscale 需要显式登录','Tailscale 等待管理员批准','Tailscale 报告 Running',
                    '先配置本机网络身份','本机身份服务不可用','本机身份状态未知','节点状态未确认','节点服务待接入','节点已停止'];
                  const matches=labels.map((label,i)=>text.includes(label)?i:-1).filter(i=>i>=0);
                  const buttons=[...c?.querySelectorAll('button')||[]],action=label=>{const x=buttons.filter(b=>b.textContent.trim()===label);
                    return {count:Math.min(x.length,9),enabled:x.length===1&&!x[0].disabled,visible:x.length===1&&!!x[0].getClientRects().length}};
                  return {networkVisible:!!p&&!p.hidden,editorVisible:!!f&&!!f.getClientRects().length,
                    profileCount:Math.min(9,p?.querySelectorAll('.network-profile-card').length||0),
                    editorInputs:Math.min(9,f?.querySelectorAll('input,select,textarea').length||0),applicationVisible:!document.hidden,
                    nodeStatusCodes:matches,detailsOpen:!!c?.querySelector('details')?.open,
                    identitySaved:text.includes('本机身份已保存'),start:action('启动节点'),stop:action('停止节点'),login:action('登录 Tailscale'),
                    operationConfirmed:status.includes('节点操作已确认'),operationUnconfirmed:status.includes('节点操作结果未确认')}})()""")
            except Exception:pass
        code=str(error)
        if isinstance(error,GuiFailure):
            if code.startswith('android_control_missing_'):report['uiFailure']='control_missing'
            elif code.startswith('android_text_control_missing_'):report['uiFailure']='text_control_missing'
            elif code in {'android_text_input_mismatch','android_select_option_missing','android_select_option_failed',
                          'android_cdp_transport_failed','android_cdp_command_failed','android_control_operation_failed'}:
                report['uiFailure']=code
        raise
    finally:
        if browser:
            report['nativeConfirmations']=getattr(browser,'confirmationHistory',[])
            try:browser.close();report['browserClosed']=True
            except Exception:report['browserClosed']=False
        if forward:
            try:
                adb('forward','--remove',forward)
                report['forwardRemoved']=not any(forward in row.split() for row in adb('forward','--list').splitlines())
            except Exception:report['forwardRemoved']=False
        try:
            for package in reversed(installed):
                adb('shell','am','force-stop',package);adb('uninstall',package,timeout=60)
            report['packagesRemoved']=all('package:'+package not in adb('shell','pm','list','packages',package).splitlines() for package in (PACKAGE,AUTH_PACKAGE))
        except Exception:report['packagesRemoved']=False


def main():
    import argparse
    import hashlib
    import shutil
    import tempfile
    parser=argparse.ArgumentParser()
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--auth-apk', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host-source-checkout', type=Path, required=True)
    parser.add_argument('--host-source-sha', required=True)
    args=parser.parse_args()
    root=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    paths=[args.apk.resolve(strict=True),args.auth_apk.resolve(strict=True),args.bundle.resolve(strict=True),args.output.resolve()]
    if any(path==root or not path.is_relative_to(root) for path in paths):
        raise SystemExit('dual_owned_paths_required')
    output=paths[3];output.mkdir(parents=True,exist_ok=True)
    result={'schemaVersion':1,'status':'failed','sourceSHA':os.environ.get('GITHUB_SHA'),
            'nativeSourceSHA':'93ca6cd4b9ccdbe8658d5470c8862b26092aa9dc',
            'apkSourceSHA':'bf39bb44e6df54140984a0abbe93d40f992c1f23',
            'apkFrontendDifference':'none from checked application source',
            'scope':'owned API35 x86_64; real UI, synthetic peers, QA-only TS private trust; no physical IME',
            'apkSha256':hashlib.sha256(paths[0].read_bytes()).hexdigest(),'directions':{}}
    from android_dual_overlay_session import AndroidDualOverlaySession
    result['hostSourceSHA']=args.host_source_sha
    try:
        for role in ('ts','et'):
            current={'stage':'setup'};result['directions'][role]=current
            private=Path(tempfile.mkdtemp(prefix='hp-dual-host-',dir=root));private.chmod(0o700)
            session=AndroidDualOverlaySession(paths[2], private, host_source=args.host_source_sha,
                source_checkout=args.host_source_checkout, device=SERIAL, lifetime=1800)
            try:
                with session:
                    run_direction(paths[0],paths[1],session,role,current)
            finally:
                state=session.report
                stage=state.get('stage')
                if stage in ('device-and-bundle','namespace','host-controller','relay-and-reverse','ready'):
                    current['environmentStage']=stage
                for key in ('deviceApi35Verified','hostReady','deviceUserspaceReachabilityVerified'):
                    if type(state.get(key)) is bool:current[key]=state[key]
                for key in ('relayRoles','reverseMappings'):
                    if type(state.get(key)) is int and 0<=state[key]<=3:current[key]=state[key]
                current['environmentCleanup']=state.get('cleanup', {})
                shutil.rmtree(private)
                current['privateDirectoryRemoved']=not private.exists()
                (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            required=('tsExplicitAuthorization','pairingApprovedBoth','bindingBoth','bothInputAndDistinctTargets',
                      'survivorSameAuthenticatedSession','stoppedInputUnavailableAndUnchanged',
                      'browserClosed','forwardRemoved','packagesRemoved','privateDirectoryRemoved')
            cleanup=current['environmentCleanup']
            if (current.get('stage')!='complete' or any(current.get(key) is not True for key in required) or
                    current.get('staleInputGuard') not in ('retained_tab_disabled_keyboard_tested','removed_tab_unreachable') or
                    not isinstance(cleanup,dict) or not cleanup or any(value is not True for value in cleanup.values())):
                raise GuiFailure('dual_evidence_incomplete')
        result['status']='passed'
    except Exception as error:
        text=str(error)
        from android_dual_overlay_session import SessionError
        known={'host_control_unavailable','host_controller_readiness_invalid','host_material_reachability_claim_invalid',
               'owned_namespace_collision','controlled_session_command_failed','owned_private_material_required',
               'bounded_private_material_required','shared_overlay_session_cleanup_incomplete'}
        result['errorCode']=text if re.fullmatch(r'dual_[a-z0-9_]{1,80}',text) or isinstance(error,SessionError) and text in known else 'dual_driver_failed'
    finally:
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    if result['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
