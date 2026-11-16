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
    # Dump only to the owned AVD's fixed private path; never publish its XML.
    dump_path='/data/local/tmp/herdr-dual-ui.xml'
    try:
        try:adb('shell','uiautomator','dump',dump_path,timeout=15)
        except GuiFailure:raise GuiFailure('dual_native_ui_dump_failed') from None
        try:xml=adb('shell','cat',dump_path,timeout=5)
        except GuiFailure:raise GuiFailure('dual_native_ui_read_failed') from None
        start=xml.find('<?xml')
        if start < 0:raise GuiFailure('dual_native_ui_xml_missing')
        try:root=ET.fromstring(xml[start:xml.rfind('>')+1])
        except ET.ParseError:raise GuiFailure('dual_native_ui_xml_invalid') from None
        return list(root.iter('node'))
    finally:
        try:adb('shell','rm','-f',dump_path,check=False,timeout=5)
        except GuiFailure:raise GuiFailure('dual_native_ui_cleanup_failed') from None


def ordinary_native_tree(nodes):
    return {'xmlParsed':True,'nodeCount':min(len(nodes),999),
            'ownedWebView':any(node.get('package')==PACKAGE and
                node.get('class','').endswith('WebView') for node in nodes)}


def wait_for_ordinary_tree(report, timeout=45):
    retryable={'dual_native_ui_dump_failed','dual_native_ui_read_failed',
               'dual_native_ui_xml_missing','dual_native_ui_xml_invalid'}
    observation={'attempts':0,'lastError':None}
    report['nativeTreeObservation']=observation
    def inspect():
        observation['attempts']=min(observation['attempts']+1,999)
        try:nodes=native_ui_nodes()
        except GuiFailure as error:
            if str(error) not in retryable:raise
            observation['lastError']=str(error)
            return False
        tree=ordinary_native_tree(nodes)
        report['ordinaryNativeTree']=tree
        if len(nodes)<3 or not tree['ownedWebView']:
            observation['lastError']='dual_native_ui_tree_incomplete'
            return False
        observation['lastError']=None
        return tree
    return wait_for(inspect,'dual_native_ui_tree_not_ready',timeout=timeout)


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


def named_action_available(browser, scope, text):
    expr = '''(()=>{const e=document.querySelector(%s);if(!e)return false;
      return [...e.querySelectorAll('button')].some(b=>b.textContent.trim()===%s&&!b.disabled&&b.getClientRects().length)})()''' % (json.dumps(scope), json.dumps(text))
    return browser.evaluate(expr) is True


def wait_named(browser, scope, text, timeout=60):
    return wait_for(lambda: named_action_available(browser,scope,text), 'dual_action_unavailable', timeout=timeout)


def wait_node_start(browser, scope, before, timeout=90):
    def settled():
        current=start_observer_snapshot(browser)
        if current['rejected']>before['rejected']:
            raise GuiFailure('dual_node_start_rejected')
        return current['resolved']>before['resolved'] and named_action_available(browser,scope,'停止节点')
    return wait_for(settled,'dual_node_start_unconfirmed',timeout=timeout)


START_OBSERVER = r"""(()=>{
  const original=window.ipc, internals=window.__TAURI_INTERNALS__;
  const callbacks=internals?.callbacks;
  if(!original || typeof original.postMessage!=='function' || !(callbacks instanceof Map) || window.__dualStartObserver) return false;
  const allowed=new Set(['overlay_provider_unavailable','overlay_identity_unavailable','overlay_stale_revision',
    'cancelled','mobile_node_busy','mobile_node_capacity','mobile_node_cleanup_pending','overlay_invalid_deadline',
    'mobile_node_failed','invalid_network_identity','network_profile_disabled','network_identity_unavailable',
    'network_identity_missing','network_identity_changed','invalid_network_binding','network_catalog_changed',
    'network_profile_changed','network_affected_changed','state_unavailable','network_identity_busy',
    'network_changed','network_profile_missing','network_identity_mode_unsupported',
    'network_identity_provider_unavailable','network_identity_unsupported']);
  const expectedAuthPort=0;
  const state={sent:0,resolved:0,rejected:0,errorCode:null,openAuth:{sent:0,resolved:0,rejected:0,expectedAuthUrlValid:false}};
  const wrapped={postMessage(message){
    let data;try{data=typeof message==='string'?JSON.parse(message):null}catch{}
    const target=data?.cmd==='network_node_start'?state:data?.cmd==='network_node_open_auth'?state.openAuth:null;
    if(target){
      target.sent++;
      if(target===state.openAuth){
        const raw=data.payload?.args?.expectedAuthUrl??data.payload?.expectedAuthUrl;
        try{const u=typeof raw==='string'&&raw.length<=4096?new URL(raw):null;
          target.expectedAuthUrlValid=!!u&&u.protocol==='https:'&&u.hostname==='127.0.0.1'&&
            Number(u.port||443)===expectedAuthPort&&!u.username&&!u.password&&!u.hash;
        }catch{target.expectedAuthUrlValid=false;}
      }
      for(const [id,rejected] of [[data.callback,false],[data.error,true]]){
        const callback=callbacks.get(id);
        if(typeof callback!=='function'){target.callbackMissing=true;continue;}
        callbacks.set(id,function(value){
          if(rejected){target.rejected++;if(target===state)state.errorCode=typeof value==='string'&&allowed.has(value)?value:'other';}
          else target.resolved++;
          return callback(value);
        });
      }
    }
    return original.postMessage(message);
  }};
  window.ipc=wrapped;
  if(window.ipc!==wrapped)return false;
  window.__dualStartObserver={state,original,wrapped};
  return true;
})()"""


def install_start_observer(browser, auth_port=None):
    if auth_port is not None and (type(auth_port) is not int or not 1<=auth_port<=65535):
        raise GuiFailure('dual_auth_port_invalid')
    script=START_OBSERVER.replace('const expectedAuthPort=0;','const expectedAuthPort='+str(auth_port or 0)+';')
    if browser.evaluate(script) is not True:
        raise GuiFailure('dual_start_observer_unavailable')


def start_observer_snapshot(browser):
    value=browser.evaluate("(()=>{const x=window.__dualStartObserver;return x?x.state:null})()")
    if (not isinstance(value,dict) or any(type(value.get(key)) is not int or not 0<=value[key]<=9
            for key in ('sent','resolved','rejected')) or value.get('errorCode') is not None and
            not re.fullmatch(r'[a-z_]{1,50}',value['errorCode'])):
        raise GuiFailure('dual_start_observer_invalid')
    result={key:value.get(key) for key in ('sent','resolved','rejected','errorCode','callbackMissing') if key in value}
    if 'openAuth' in value:
        opened=value['openAuth']
        if (not isinstance(opened,dict) or any(type(opened.get(key)) is not int or not 0<=opened[key]<=9
                for key in ('sent','resolved','rejected')) or type(opened.get('expectedAuthUrlValid')) is not bool):
            raise GuiFailure('dual_start_observer_invalid')
        result['openAuth']={key:opened[key] for key in ('sent','resolved','rejected','expectedAuthUrlValid')}
    return result


STOP_OBSERVER = r"""(()=>{
  const original=window.ipc, internals=window.__TAURI_INTERNALS__;
  const callbacks=internals?.callbacks;
  if(!original || typeof original.postMessage!=='function' || !(callbacks instanceof Map) || window.__dualStopObserver) return false;
  const state={sent:0,resolved:0,rejected:0,cmdId:null,profileId:null};
  const wrapped={postMessage(message){
    let data;try{data=typeof message==='string'?JSON.parse(message):null}catch{}
    if(data?.cmd==='network_node_stop'){
      state.sent++;
      const args=data.payload?.args??data.payload??{};
      state.cmdId=typeof args.id==='string'&&args.id.length<=128?args.id:null;
      state.profileId=typeof args.binding?.profileId==='string'&&args.binding.profileId.length<=128?args.binding.profileId:null;
      for(const [id,rejected] of [[data.callback,false],[data.error,true]]){
        const callback=callbacks.get(id);
        if(typeof callback!=='function')continue;
        callbacks.set(id,function(value){ if(rejected)state.rejected++; else state.resolved++; return callback(value); });
      }
    }
    return original.postMessage(message);
  }};
  window.ipc=wrapped;
  if(window.ipc!==wrapped)return false;
  window.__dualStopObserver={state,original,wrapped};
  return true;
})()"""


def install_stop_observer(browser):
    if browser.evaluate(STOP_OBSERVER) is not True:
        raise GuiFailure('dual_stop_observer_unavailable')


def uninstall_stop_observer(browser):
    value=browser.evaluate("(()=>{const x=window.__dualStopObserver;if(!x)return false;window.ipc=x.original;"
                           "const restored=window.ipc===x.original;if(restored)delete window.__dualStopObserver;return restored;})()")
    if value is not True:
        raise GuiFailure('dual_stop_observer_uninstall_failed')
    return True


def stop_observer_snapshot(browser):
    value=browser.evaluate("(()=>{const x=window.__dualStopObserver;return x?x.state:null})()")
    if (not isinstance(value,dict) or any(type(value.get(key)) is not int or not 0<=value[key]<=9
            for key in ('sent','resolved','rejected')) or
            any(value.get(key) is not None and not (isinstance(value.get(key),str) and len(value[key])<=128)
                for key in ('cmdId','profileId'))):
        raise GuiFailure('dual_stop_observer_invalid')
    return {key:value.get(key) for key in ('sent','resolved','rejected','cmdId','profileId')}


STOP_READBACK_SETTLE=0.4
STOP_ACQUIRE_TIMEOUT=30


def stop_button_probe(scope, mode, epoch=None):
    """acquire: stamp a fresh nonce on the uniquely enabled 停止节点 and focus it;
    verify: the SAME DOM node still carries that nonce and keeps focus. Never clicks."""
    acquire=("const b=buttons[0];window.__dualStopEpoch=(window.__dualStopEpoch||0)+1;"
             "b.__dualStopEpoch=window.__dualStopEpoch;b.focus();"
             "return {epoch:window.__dualStopEpoch,focused:document.activeElement===b};")
    verify=("const b=buttons[0];return {same:b.__dualStopEpoch===%d,focused:document.activeElement===b};"
            % (epoch if isinstance(epoch,int) and epoch>0 else -1))
    return """(()=>{const root=document.querySelector(%s);if(!root)return {error:'scope'};
      const buttons=[...root.querySelectorAll('button')].filter(b=>b.textContent.trim()==='停止节点' &&
        !b.matches(':disabled') && !b.closest('[hidden]') && b.getClientRects().length);
      if(buttons.length!==1)return {error:'unique',count:buttons.length};
      %s})()""" % (json.dumps(scope), acquire if mode=='acquire' else verify)


STOP_ERROR_CODES=frozenset({
    'dual_confirmation_already_pending','dual_stop_expected_target_invalid','dual_stop_button_unstable',
    'dual_stop_confirmation_not_observed','dual_stop_rejected','dual_stop_replayed','dual_stop_target_mismatch',
    'dual_stop_target_not_distinct','dual_stop_invocation_unverified','dual_stop_observer_unavailable',
    'dual_stop_observer_invalid','dual_stop_observer_uninstall_failed','dual_stop_observer_regressed',
    'dual_stop_callback_duplication'})


def stop_public_error_code(code):
    """Only known stop error codes are publishable; any other string, however shaped, is unexpected."""
    return code if isinstance(code,str) and code in STOP_ERROR_CODES else 'unexpected_error'


def stop_node_once(browser, scope, role, profile_title, host_name, expected_profile_id,
                   *, stage, attempts, distinct_ids=(), confirm_timeout=45):
    """Stop one overlay node by one real CDP hardware Enter on a twice-verified stable button.

    The pointer press/release path loses the click when the panel re-renders between the two
    pointer events, so activation is keyboard-only and never replayed. The card may be replaced
    right before the probe, so the candidate is re-acquired (read-only + focus) until the SAME
    DOM node is stable across two readbacks. The native stop resolves asynchronously, so the
    wait polls read-only for the exact resolved increment and fails fast on replay, rejection,
    or a target mismatch. The public attempt record carries only the role, booleans, bounded
    counters, and whitelisted error codes - never raw ids, command args, or exception text."""
    label=profile_title.split(' · ')[0]
    expected_dialog='停止 '+label+' 的本机节点？受影响主机：'+host_name+'。'
    if browser.expectedConfirmation is not None:
        raise GuiFailure('dual_confirmation_already_pending')
    if not (isinstance(expected_profile_id,str) and expected_profile_id):
        raise GuiFailure('dual_stop_expected_target_invalid')
    before=stop_observer_snapshot(browser)
    sent_before=int(before.get('sent') or 0); resolved_before=int(before.get('resolved') or 0)
    rejected_before=int(before.get('rejected') or 0)
    attempt={'stage':stage,'role':role,'acquires':0,'readbacks':0,'activation':'cdp-enter',
             'confirmObserved':False,'roleMatch':None,'sentDelta':None,'resolvedDelta':None,
             'rejectedDelta':None,'errorCode':None}
    attempts.append(attempt)
    try:
        deadline=time.monotonic()+STOP_ACQUIRE_TIMEOUT
        stable=False
        while time.monotonic()<deadline:
            first=browser.evaluate(stop_button_probe(scope,'acquire'))
            if (isinstance(first,dict) and 'error' not in first and isinstance(first.get('epoch'),int)
                    and first.get('focused') is True):
                attempt['acquires']+=1
                time.sleep(STOP_READBACK_SETTLE)
                second=browser.evaluate(stop_button_probe(scope,'verify',first['epoch']))
                if (isinstance(second,dict) and 'error' not in second and second.get('same') is True
                        and second.get('focused') is True):
                    stable=True; attempt['readbacks']=2; break
            time.sleep(0.2)
        if not stable:
            raise GuiFailure('dual_stop_button_unstable')
        browser.expectedConfirmation=expected_dialog
        browser.confirmationObserved=False
        browser.confirmDiagnostic=None
        try:
            for kind in ('keyDown','keyUp'):
                params={'type':kind,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13}
                if kind=='keyDown':params['text']='\r'
                browser.call('Input.dispatchKeyEvent',params)
            # No background CDP reader: pump events with side-effect-free evaluates, never re-press.
            observed=False
            confirm_deadline=time.monotonic()+confirm_timeout
            while time.monotonic()<confirm_deadline:
                browser.call('Runtime.evaluate',{'expression':'true','returnByValue':True})
                if browser.confirmationObserved is True:
                    observed=True; break
                time.sleep(0.1)
            if not observed:
                raise GuiFailure('dual_stop_confirmation_not_observed')
            attempt['confirmObserved']=True
        finally:
            browser.expectedConfirmation=None
        verified=False; profile_id=None
        stop_deadline=time.monotonic()+60
        while time.monotonic()<stop_deadline:
            current=stop_observer_snapshot(browser)
            sent=int(current.get('sent') or 0)-sent_before
            resolved=int(current.get('resolved') or 0)-resolved_before
            rejected=int(current.get('rejected') or 0)-rejected_before
            attempt['sentDelta']=sent; attempt['resolvedDelta']=resolved; attempt['rejectedDelta']=rejected
            if sent<0 or resolved<0 or rejected<0:
                raise GuiFailure('dual_stop_observer_regressed')
            if resolved+rejected>sent:
                raise GuiFailure('dual_stop_callback_duplication')
            if rejected>0:
                raise GuiFailure('dual_stop_rejected')
            if sent>1:
                raise GuiFailure('dual_stop_replayed')
            cmd_id=current.get('cmdId'); profile_id=current.get('profileId')
            if sent==1 and (cmd_id is not None and cmd_id!=expected_profile_id or
                            profile_id is not None and profile_id!=expected_profile_id):
                attempt['roleMatch']=False
                raise GuiFailure('dual_stop_target_mismatch')
            if sent==1 and resolved==1:
                attempt['roleMatch']=(cmd_id==expected_profile_id and profile_id==expected_profile_id)
                if attempt['roleMatch'] is not True:
                    raise GuiFailure('dual_stop_target_mismatch')
                if distinct_ids and profile_id in distinct_ids:
                    raise GuiFailure('dual_stop_target_not_distinct')
                verified=True; break
            time.sleep(0.1)
        if not verified:
            raise GuiFailure('dual_stop_invocation_unverified')
        return profile_id
    except Exception as error:
        attempt['errorCode']=stop_public_error_code(str(error))
        raise


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


def public_host_failure_counts(host):
    result={}
    for role in ('ts','et'):
        try:
            value=host_request(host,{'op':'audit','role':role,'expectedBase64':''},'host_audit')
            if any(type(value.get(key)) is not int or not 0<=value[key]<=1000000 for key in ('acceptedSessions','capturedBytes')):
                raise GuiFailure('dual_host_diagnostics_invalid')
            sessions=value.get('sessions')
            if not isinstance(sessions,list) or any(not isinstance(item,dict) or
                    type(item.get('approvedDevice')) is not bool or type(item.get('active')) is not bool for item in sessions):
                raise GuiFailure('dual_host_diagnostics_invalid')
            result[role]={'available':True,'acceptedSessions':value['acceptedSessions'],'capturedBytes':value['capturedBytes'],
                          'approvedSessionObserved':any(item['approvedDevice'] for item in sessions),
                          'activeSessions':min(sum(item['active'] for item in sessions),1000000)}
        except Exception:result[role]={'available':False}
    return result


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
    before=start_observer_snapshot(browser)
    confirm_click(browser, scope, '启动节点', '启动 QA ')
    wait_node_start(browser, scope, before)
    return scope


def canonical_component(value):
    match=re.fullmatch(r'([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)',value.strip())
    if not match:return None
    package,activity=match.groups()
    return package+'/'+(package+activity if activity.startswith('.') else activity)


def component_kind(component):
    if component==AUTH_PACKAGE+'/'+AUTH_PACKAGE+'.AuthActivity':return 'test_receiver'
    if component and component.split('/')[0]==PACKAGE:return 'product'
    if component and component.split('/')[0] in {'com.android.chrome','com.android.browser','org.chromium.chrome'}:return 'browser'
    if component and component.split('/')[0] in {'android','com.android.intentresolver'} and component.endswith(('ResolverActivity','ChooserActivity')):return 'resolver'
    return 'other' if component else 'unresolved'


def resolve_view_component(url):
    raw=adb('shell','cmd','package','resolve-activity','--brief','--user','0',
            '-a','android.intent.action.VIEW','-d',url,check=False)
    values={canonical_component(line.strip()) for line in raw.splitlines()}
    values.discard(None)
    return next(iter(values)) if len(values)==1 else None


def loopback_user_selection(raw):
    lines=raw.splitlines();user=False;enabled=False;hosts=set();allowed=False
    for line in lines:
        text=line.strip()
        if re.fullmatch(r'User [0-9]+:',text):user=text=='User 0:';enabled=False;continue
        if not user:continue
        if text=='Verification link handling allowed: true':allowed=True
        if text in {'Enabled:','Disabled:'}:enabled=text=='Enabled:';continue
        if enabled and text:hosts.add(text)
    return {'linkHandlingAllowed':allowed,'onlyLoopbackSelected':hosts=={'127.0.0.1'}}


def loopback_app_link_approved(raw):
    domains={};collect=False
    for line in raw.splitlines():
        text=line.strip()
        if text=='Domain verification state:':collect=True;continue
        if collect:
            if not line.startswith(' ') or re.fullmatch(r'User [0-9]+:',text):break
            match=re.fullmatch(r'([^\s:]+): ([a-z_]+|[0-9]+)',text)
            if match:
                host,status=match.groups()
                if host in domains:return False
                domains[host]=status
    return domains=={'127.0.0.1':'approved'}


TRUSTED_RESOLVERS={
    'android/com.android.internal.app.ResolverActivity':'android',
    'com.android.intentresolver/com.android.intentresolver.ResolverActivity':'com.android.intentresolver',
}


def verified_system_resolver(component):
    package=TRUSTED_RESOLVERS.get(component)
    if not package:return False
    try:packages=adb('shell','pm','list','packages','-s',package,timeout=10).splitlines()
    except GuiFailure:return False
    return 'package:'+package in packages


def query_view_components(url):
    raw=adb('shell','cmd','package','query-activities','--brief','--user','0',
            '-a','android.intent.action.VIEW','-d',url,check=False)
    values={canonical_component(line.strip()) for line in raw.splitlines()}
    values.discard(None)
    return values


def resolver_resource(node, name):
    return node.get('resource-id') in {'android:id/'+name,'com.android.intentresolver:id/'+name}


def native_point(node):
    match=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
    if not match:return None
    x1,y1,x2,y2=map(int,match.groups())
    return ((x1+x2)//2,(y1+y2)//2) if x2>x1 and y2>y1 else None


def resolver_receiver_action(nodes, foreground, row_tapped=False):
    package=TRUSTED_RESOLVERS.get(foreground)
    state={'foreground':component_kind(foreground),'trustedResolver':bool(package),'receiverLabels':0,
           'receiverRows':0,'receiverSelected':False,'otherSelected':False,'defaultReceiverTitle':False,
           'onceButtons':0,'onceEnabled':False,'alwaysButtons':0}
    if not package or not nodes or nodes[0].get('package')!=package:return None,None,state
    owned=[node for node in nodes if node.get('package')==package]
    parents={child:parent for parent in nodes for child in parent}
    lists={node for node in owned if resolver_resource(node,'resolver_list')}
    labels=[node for node in owned if resolver_resource(node,'text1') and node.get('text')=='双网测试授权']
    state['receiverLabels']=min(len(labels),9)
    rows=[]
    for label in labels:
        child=label
        while child in parents:
            if parents[child] in lists:
                rows.append((child,label));break
            child=parents[child]
    state['receiverRows']=min(len(rows),9)
    marked=lambda node:any(value.get('selected')=='true' or value.get('checked')=='true' for value in node.iter('node'))
    selected=len(rows)==1 and marked(rows[0][0]);state['receiverSelected']=selected
    row=rows[0][0] if len(rows)==1 else None
    state['otherSelected']=any(marked(child) for group in lists for child in group if child is not row)
    def in_list(node):
        while node in parents:
            node=parents[node]
            if node in lists:return True
        return False
    titles=[node for node in owned if resolver_resource(node,'title') and not in_list(node) and '双网测试授权' in node.get('text','')]
    state['defaultReceiverTitle']=len(titles)==1 and not labels
    once=[node for node in owned if resolver_resource(node,'button_once') and node.get('class')=='android.widget.Button']
    state['onceButtons']=min(len(once),9)
    state['alwaysButtons']=min(sum(resolver_resource(node,'button_always') for node in owned),9)
    allowed_once=lambda node:''.join(node.get('text','').split()).casefold() in {'justonce','仅此一次'}
    state['onceEnabled']=len(once)==1 and once[0].get('enabled')=='true' and allowed_once(once[0])
    if (selected or row_tapped or state['defaultReceiverTitle']) and not state['otherSelected'] and state['onceEnabled']:
        if (len(rows)==1 and len(labels)==1) or state['defaultReceiverTitle']:
            return 'once',native_point(once[0]),state
    if not row_tapped and not state['otherSelected'] and len(rows)==1 and len(labels)==1 and rows[0][1].get('enabled')=='true':
        return 'row',native_point(rows[0][1]),state
    return None,None,state


def choose_auth_receiver(report, timeout=45):
    handler=report.get('authHandler',{})
    if handler.get('receiverCandidate') is not True or handler.get('unrelatedReceiverCandidate') is not False:
        raise GuiFailure('dual_auth_candidate_scope_missing')
    state={'rowTapSent':False,'onceTapSent':False};report.setdefault('authorization',{})['chooser']=state
    def select():
        try:
            foreground=foreground_component();state['foreground']=component_kind(foreground)
            if state['foreground']=='test_receiver':
                state['receiverForeground']=True
                return True
            action,point,screen=resolver_receiver_action(native_ui_nodes(),foreground,state['rowTapSent'])
        except GuiFailure:
            state['readUnavailable']=True
            return False
        state['screen']=screen
        key='rowTapSent' if action=='row' else 'onceTapSent'
        if action is None or point is None or state[key]:return False
        state[key]=True
        try:adb('shell','input','tap',str(point[0]),str(point[1]))
        except GuiFailure:raise GuiFailure('dual_authorization_resolver_tap_unconfirmed') from None
        state['rowTapCompleted' if action=='row' else 'onceTapCompleted']=True
        return False
    wait_for(select,'dual_authorization_resolver_missing',timeout=timeout)


def prepare_auth_receiver(port, report):
    # Only a freshly installed fixture on the disposable owned AVD is selected.
    assert_owned_avd()
    if type(port) is not int or not 1<=port<=65535:raise GuiFailure('dual_auth_port_invalid')
    state={'scope':'owned_avd_receiver_loopback_only','linkMode':'force_approved_app_link'};report['authHandler']=state
    if adb('shell','am','get-current-user')!='0':raise GuiFailure('dual_auth_test_user_required')
    probe='https://127.0.0.1:'+str(port)+'/'
    state['beforeHandler']=component_kind(resolve_view_component(probe))
    # This disposable receiver declares only the loopback host as autoVerify.
    adb('shell','pm','set-app-links','--package',AUTH_PACKAGE,'2','127.0.0.1')
    links=adb('shell','pm','get-app-links','--user','0',AUTH_PACKAGE)
    state.update(loopback_user_selection(links),onlyLoopbackApproved=loopback_app_link_approved(links))
    if not state['linkHandlingAllowed'] or not state['onlyLoopbackApproved']:
        raise GuiFailure('dual_auth_app_link_unconfirmed')
    after=resolve_view_component(probe);state['afterHandler']=component_kind(after)
    state['systemResolverVerified']=verified_system_resolver(after)
    state['unrelatedHandler']=component_kind(resolve_view_component('https://example.invalid/'))
    candidates=query_view_components(probe);unrelated=query_view_components('https://example.invalid/')
    receiver=AUTH_PACKAGE+'/'+AUTH_PACKAGE+'.AuthActivity'
    state.update(candidateCount=min(len(candidates),9),receiverCandidate=receiver in candidates,
                 unrelatedCandidateCount=min(len(unrelated),9),unrelatedReceiverCandidate=receiver in unrelated)
    # Pre-query ranking can differ from the app's launch; actual foreground decides next.
    if ((after!=receiver and not state['systemResolverVerified']) or not state['receiverCandidate'] or
            state['unrelatedReceiverCandidate'] or state['unrelatedHandler']!='browser' or not unrelated or
            any(component_kind(value)!='browser' for value in unrelated)):
        raise GuiFailure('dual_auth_handler_scope_mismatch')


def foreground_component():
    raw=adb('shell','dumpsys','activity','activities',timeout=10)
    values={canonical_component(value) for value in re.findall(
        r'(?:topResumedActivity|mResumedActivity)\s*[:=]\s*ActivityRecord\{[^\n]*?\su0\s+([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)',raw)}
    values.discard(None)
    return next(iter(values)) if len(values)==1 else None


def auth_consent_candidate(nodes, foreground, port):
    source='隔离测试控制面：127.0.0.1:'+str(port)
    sources=[node for node in nodes if node.get('package')==AUTH_PACKAGE and node.get('text')==source
             and node.get('content-desc')=='dual_auth_origin']
    buttons=[node for node in nodes if node.get('class')=='android.widget.Button' and
             node.get('text')=='批准本次测试授权']
    owned=len(buttons)==1 and buttons[0].get('package')==AUTH_PACKAGE and buttons[0].get('content-desc')=='dual_auth_approve'
    statuses=[node.get('content-desc') for node in nodes if node.get('package')==AUTH_PACKAGE and
              node.get('class')=='android.widget.TextView' and node.get('content-desc') in
              {'ready','click_received','delivered','delivery_failed','source_mismatch'}]
    status=statuses[0] if len(statuses)==1 else 'unknown'
    boolean=lambda key:buttons[0].get(key)=='true' if owned and buttons[0].get(key) in {'true','false'} else None
    state={'xmlParsed':True,'foreground':component_kind(foreground),'sourceMatched':len(sources)==1,
           'rootPackageMatched':bool(nodes) and nodes[0].get('package')==AUTH_PACKAGE,
           'candidateButtons':min(len(buttons),9),'uniqueReceiverButton':owned,'boundsValid':False,
           'buttonEnabled':boolean('enabled'),'buttonFocused':boolean('focused'),'buttonClickable':boolean('clickable'),'status':status}
    if state['foreground']!='test_receiver' or not state['sourceMatched'] or not state['rootPackageMatched'] or not owned:return None,state
    match=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',buttons[0].get('bounds',''))
    if not match:return None,state
    x1,y1,x2,y2=map(int,match.groups())
    if x2<=x1 or y2<=y1:return None,state
    state['boundsValid']=True
    if any(state[key] is not True for key in ('buttonEnabled','buttonFocused','buttonClickable')) or status!='ready':return None,state
    return ((x1+x2)//2,(y1+y2)//2),state


def auth_receiver_screen(port):
    from tauri_auth_failure_diagnostic import window_component
    before=foreground_component()
    window_before=window_component(adb('shell','dumpsys','window',timeout=5))
    nodes=native_ui_nodes()
    window_after=window_component(adb('shell','dumpsys','window',timeout=5))
    after=foreground_component()
    receiver=AUTH_PACKAGE+'/'+AUTH_PACKAGE+'.AuthActivity'
    point,state=auth_consent_candidate(nodes,before,port)
    state['foregroundStable']=before==after==window_before==window_after==receiver
    return point if state['foregroundStable'] else None,state


def approve_auth_receiver(port, report, timeout=45):
    state=report.setdefault('authorization',{})
    if state.get('activationAttempted') is True:raise GuiFailure('dual_authorization_activation_already_attempted')
    state['stage']='receiver_consent';state['activationMethod']='KEYCODE_ENTER';state['stableReads']=0
    previous=None
    def candidate():
        nonlocal previous
        try:point,screen=auth_receiver_screen(port)
        except GuiFailure:
            state['screenReadUnavailable']=True
            previous=None;state['stableReads']=0
            return False
        state['screen']=screen
        if point is None:previous=None;state['stableReads']=0;return False
        state['stableReads']=min(state['stableReads']+1,2) if previous==point else 1
        previous=point
        return state['stableReads']>=2
    wait_for(candidate,'dual_authorization_receiver_missing',timeout=timeout)
    state['activationAttempted']=True
    try:adb('shell','input','keyevent','KEYCODE_ENTER')
    except GuiFailure:raise GuiFailure('dual_authorization_activation_unconfirmed') from None
    state['activationCompleted']=True


def private_handoff_file_state():
    import shlex
    script=('if [ ! -d files ] || [ ! -r files ] || [ ! -x files ]; then printf unavailable; '
            'elif [ -L files/approved-url ]; then printf not_regular; '
            'elif [ ! -e files/approved-url ]; then printf missing; '
            'elif [ ! -f files/approved-url ]; then printf not_regular; '
            'elif [ ! -r files/approved-url ]; then printf unreadable; else printf readable; fi')
    try:value=adb('shell','run-as',AUTH_PACKAGE,'sh','-c',shlex.quote(script),timeout=5)
    except GuiFailure:return 'unavailable'
    return value if value in {'missing','not_regular','unreadable','readable'} else 'unavailable'


def confirmed_private_handoff(port, report, timeout=30):
    state=report.setdefault('authorization',{});state['stage']='private_handoff'
    if state.get('activationAttempted') is not True or state.get('activationCompleted') is not True:
        raise GuiFailure('dual_authorization_activation_unconfirmed')
    def observe():
        try:_,screen=auth_receiver_screen(port)
        except GuiFailure:screen={'status':'unknown','readUnavailable':True}
        screen['fileState']=private_handoff_file_state();state['postConsent']=screen
        status_scope=all(screen.get(key) is True for key in ('foregroundStable','rootPackageMatched','uniqueReceiverButton'))
        if screen['status'] in {'delivery_failed','source_mismatch'} and status_scope:
            raise GuiFailure('dual_authorization_'+screen['status'])
        scoped=status_scope and screen.get('sourceMatched') is True
        if screen['status']!='delivered' or not scoped:return False
        if screen['fileState'] in {'not_regular','unreadable'}:raise GuiFailure('dual_authorization_handoff_unreadable')
        if screen['fileState']!='readable':return False
        try:url=adb('shell','run-as',AUTH_PACKAGE,'cat','files/approved-url',timeout=5)
        except GuiFailure:
            screen['fileRead']='failed';raise GuiFailure('dual_authorization_handoff_read_failed') from None
        screen['fileRead']='read' if url else 'empty'
        try:
            parsed=urlsplit(url)
            valid=(0<len(url)<=4096 and parsed.scheme=='https' and parsed.hostname=='127.0.0.1' and parsed.port==port and
                   parsed.username is None and parsed.password is None and '#' not in url)
        except ValueError:valid=False
        screen['originValid']=valid
        if not valid:raise GuiFailure('dual_authorization_handoff_invalid')
        return url
    try:return wait_for(observe,'dual_authorization_handoff_missing',timeout=timeout)
    except GuiFailure as error:
        if str(error)!='dual_authorization_handoff_missing':raise
        last=state.get('postConsent',{})
        code={'ready':'confirmation_not_effective','click_received':'delivery_pending'}.get(last.get('status'),'handoff_missing')
        if last.get('status')=='delivered':
            code={'missing':'delivered_file_missing','unavailable':'handoff_file_unavailable'}.get(last.get('fileState'),'handoff_missing')
        raise GuiFailure('dual_authorization_'+code) from None


def authorize_ts(browser, host, scope, port, report):
    authorization=report.setdefault('authorization',{});authorization['stage']='explicit_login'
    wait_named(browser, scope, '登录 Tailscale', timeout=120)
    confirm_click(browser, scope, '登录 Tailscale', '显式发起登录')
    wait_named(browser, scope, '打开授权页面', timeout=120)
    authorization['stage']='product_system_open'
    confirm_click(browser, scope, '打开授权页面', '通过系统打开')
    authorization['productOpenConfirmed']=True
    authorization['stage']='system_choice'
    choose_auth_receiver(report)
    approve_auth_receiver(port,report)
    url=confirmed_private_handoff(port,report)
    authorization['privateHandoffReceived']=True
    if host_request(host, {'op':'complete_ts_auth','authorize':True,'url':url}, 'ts_authorized').get('ok') is not True:
        raise GuiFailure('dual_authorization_unconfirmed')
    authorization['hostAuthorizationConfirmed']=True
    adb('shell','monkey','-p',PACKAGE,'-c','android.intent.category.LAUNCHER','1')
    wait_for(lambda:browser.evaluate('!document.hidden') is True,'dual_authorization_return_missing',timeout=45)
    authorization['stage']='product_resumed'
    return True


PAIR_RESPONSE_FACTS=('exactInput','wireMatches','requestWithinDeviceTime','responseWithinDeviceTime',
    'requestUnexpired','responseUnexpired','expiryOrdering','withinTtl','productValid','previewVisible',
    'fiveLinesMatched','productShowsInvalid','pairMode','sourceChecked','busy','waitingIdentity','targetMatched','ready')


def pairing_response_probe(request,response,account,device_fingerprint,host_fingerprint,fields):
    # Execute the checked product's pure validators with the device's read-only
    # Date.now(), never a host clock, time override, native call or DOM write.
    source=Path(__file__).resolve().parents[1]/'tauri'/'src'
    functions='\n'.join(line.replace('export function ','function ') for name in ('pairing-view.js','pairing-camera.js')
                        for line in (source/name).read_text().splitlines() if not line.startswith('import '))
    spec={'step':'response_material','request':request,'response':response,'account':account,
          'deviceFingerprint':device_fingerprint,'hostFingerprint':host_fingerprint,'fields':fields,'selector':'#pair-preview','target':True}
    return """(()=>{%s
      const spec=%s,$=id=>document.getElementById(id),now=Math.floor(Date.now()/1000);
      const visible=e=>!!e&&!e.hidden&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const req=JSON.parse(spec.request),res=JSON.parse(spec.response),ints=x=>Number.isSafeInteger(x.issued_at)&&Number.isSafeInteger(x.expires_at);
      const sameKeys=(x,keys)=>Object.keys(x).sort().join('|')===keys.sort().join('|');
      const requestKeys=['version','type','request_id','device','public_key','account','host_key','issued_at','expires_at'];
      const responseKeys=['version','type','request_id','account','host_key','fingerprint','issued_at','expires_at','status','authorization_added'];
      const wireMatches=sameKeys(req,requestKeys)&&sameKeys(res,responseKeys)&&ints(req)&&ints(res)&&
        req.version===2&&req.type==='pairing-public-key-request'&&res.version===2&&res.type==='pairing-binding-response'&&
        /^[0-9a-f]{32}$/.test(req.request_id)&&res.request_id===req.request_id&&req.account===spec.account&&res.account===req.account&&
        req.host_key===spec.hostFingerprint&&res.host_key===req.host_key&&res.fingerprint===spec.deviceFingerprint&&
        res.status==='authorized'&&typeof res.authorization_added==='boolean';
      const targetMatched=Object.entries(spec.fields).every(([id,value])=>$(id)?.value===value);
      const exactInput=$('pair-request')?.value===spec.request&&$('pair-response')?.value===spec.response&&
        $('pair-device')?.value===req.device&&[...Object.keys(spec.fields).filter(id=>id!=='remote-profile-provider'),'pair-device'].every(id=>$(id)?.readOnly===true);
      const requestWithinDeviceTime=ints(req)&&req.issued_at<=now,responseWithinDeviceTime=ints(res)&&res.issued_at<=now;
      const requestUnexpired=ints(req)&&now<req.expires_at,responseUnexpired=ints(res)&&now<res.expires_at;
      const expiryOrdering=ints(req)&&ints(res)&&res.expires_at<=req.expires_at;
      const withinTtl=[req,res].every(x=>ints(x)&&x.issued_at>=0&&x.expires_at>x.issued_at&&x.expires_at-x.issued_at<=600);
      let productValid=false;try {const current=pairingCameraRequest(spec.request,spec.account,now);
        validatePairingCameraResponse(spec.response,current,spec.deviceFingerprint,now);productValid=true;}catch{}
      const preview=$('pair-response-preview'),lines=['账号：'+spec.account,'主机指纹：'+spec.hostFingerprint,
        '设备指纹：'+spec.deviceFingerprint,'状态：授权 (authorized)','请求 ID：'+req.request_id];
      const previewVisible=visible(preview),fiveLinesMatched=!!preview&&lines.every(line=>preview.textContent.split(String.fromCharCode(10)).includes(line));
      const productShowsInvalid=!!preview&&preview.textContent==='响应无效、不匹配或已过期；此原记录当前仅可接受的新鲜回执类型也须一致。';
      const pairMode=$('pair-mode')?.checked===true,sourceChecked=$('pair-source-review')?.checked===true;
      const busy=!!$('remote-fields')?.matches(':disabled')||!!$('pair-preview')?.matches(':disabled');
      const waitingIdentity=$('pair-status')?.textContent==='等待主机响应 · 设备指纹 '+spec.deviceFingerprint+' · 授权未知'&&
        $('pair-request-summary')?.textContent.includes('仍待主机操作者确认')&&!$('pair-revocation-mode')?.checked&&
        $('pair-preview')?.textContent==='查看响应内容'&&$('pair-status')?.dataset.createPhase==='ready';
      const ready=wireMatches&&targetMatched&&exactInput&&requestWithinDeviceTime&&responseWithinDeviceTime&&requestUnexpired&&responseUnexpired&&
        expiryOrdering&&withinTtl&&productValid&&pairMode&&!sourceChecked&&!busy&&waitingIdentity&&!document.hidden;
      return {exactInput,wireMatches,requestWithinDeviceTime,responseWithinDeviceTime,requestUnexpired,responseUnexpired,expiryOrdering,withinTtl,
        productValid,previewVisible,fiveLinesMatched,productShowsInvalid,pairMode,sourceChecked,busy,waitingIdentity,targetMatched,ready};})()"""%(functions,json.dumps(spec))


def pair_host(browser, host, role, profile, report=None):
    from flutter_android_gui import public_host_fingerprint, DeviceFailure
    if role not in ('ts','et'):raise GuiFailure('dual_pair_role_mismatch')
    diagnostic={'role':role,'step':'profile','action':'read','control':'public_profile','state':'waiting','completed':[]}
    if report is not None:report.setdefault('pairingAttempts',[]).append(diagnostic)
    if profile.get('provider') != {'ts':'tailscale','et':'easytier'}[role]:
        diagnostic['state']='mismatch';raise GuiFailure('dual_pair_role_mismatch')
    try:fingerprint=public_host_fingerprint(profile['expectedHostKey'])
    except (KeyError,DeviceFailure):
        diagnostic['state']='mismatch';raise GuiFailure('dual_pair_profile_invalid') from None
    raw=json.dumps(profile,ensure_ascii=False,separators=(',',':'))
    fields={"remote-"+field:str(profile[key]) for field,key in
            (('host','host'),('port','port'),('user','username'),('session','session'),
             ('herdr','herdrPath'),('socket','socketPath'),('pin','expectedHostKey'),('profile-provider','provider'))}
    def wire(raw,keys):
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError()
                result[key]=value
            return result
        try:
            if not isinstance(raw,str) or len(raw.encode('utf-8'))>2048:raise ValueError()
            value=json.loads(raw,object_pairs_hook=unique)
            if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError()
            if any(type(value[key]) is not int for key in ('version','issued_at','expires_at')):raise ValueError()
            if any(not isinstance(value[key],str) or not value[key] for key in set(keys)-{'version','issued_at','expires_at','authorization_added'}):raise ValueError()
            return value
        except (ValueError,TypeError):raise GuiFailure('dual_pair_review_mismatch') from None
    request=response=None
    def probe(step,selector,condition,target):
        spec={'step':step,'selector':selector,'fields':fields,'target':target}
        # Read-only public UI predicates. Reports receive booleans, never field,
        # request, response, fingerprint, account, URL or exception text.
        value=browser.evaluate("""(()=>{const spec=%s,$=id=>document.getElementById(id),e=document.querySelector(spec.selector);
          const visible=x=>!!x&&!x.hidden&&!!x.getClientRects().length&&getComputedStyle(x).visibility!=='hidden';
          const targetMatched=Object.entries(spec.fields).every(([id,value])=>$(id)?.value===value);
          const r=e?.getBoundingClientRect(),x=r?r.left+r.width/2:0,y=r?r.top+r.height/2:0;
          const facts={present:!!e,visible:visible(e),enabled:!!e&&!e.matches(':disabled'),foreground:!document.hidden,
            targetMatched,checked:e?.checked===true,centerHit:!!e&&e.contains(document.elementFromPoint(x,y)),asyncReady:(%s)===true};
          return {...facts,ready:facts.present&&facts.visible&&facts.enabled&&facts.foreground&&facts.asyncReady&&(!spec.target||targetMatched)};})()""" % (json.dumps(spec),condition))
        if not isinstance(value,dict):return False
        facts={key:value.get(key) is True for key in ('present','visible','enabled','foreground','targetMatched','checked','centerHit','asyncReady','ready')}
        diagnostic['facts']=facts
        return facts['ready']
    def ready(step,selector,condition='true',target=False,action='read',timeout=60):
        diagnostic.update(step=step,action=action,control=selector.lstrip('#').replace('-','_'),state='waiting')
        wait_for(lambda:probe(step,selector,condition,target),'dual_pair_step_timeout',timeout=timeout)
        diagnostic['state']='ready'
    def click(step,selector,condition='true',target=False):
        ready(step,selector,condition,target,'click')
        # Exactly one actual UI activation. Failed dispatch/unknown postcondition
        # is never replayed, including create, accept, save and review checkboxes.
        browser.click(selector)
        diagnostic['state']='dispatched';diagnostic['completed'].append(step)
    def fill(step,selector,value,condition='true',target=False):
        ready(step,selector,condition,target,'fill')
        browser.fill(selector,value)
        if browser.read(selector,'value')!=value:raise GuiFailure('dual_pair_value_mismatch')
        diagnostic['completed'].append(step)
    def done(step,selector,condition,target=True,timeout=90):
        ready(step,selector,condition,target,timeout=timeout)
        diagnostic['state']='confirmed'
    def checked(selector):return "$(%s)?.checked===true" % json.dumps(selector)
    frozen="[...Object.keys(spec.fields).filter(id=>id!=='remote-profile-provider'),'pair-device'].every(id=>$(id)?.readOnly===true)"
    quiet="!$('remote-fields')?.matches(':disabled')"
    target_ready="$('pair-mode')?.checked===true&&$('pair-status')?.textContent==='公开连接资料已填入；请独立核对用户名和主机公钥，再创建设备公开请求。'&&!$('pair-request')?.value"
    try:
        click('open','#host-open-remote')
        done('add_ready','#add-herdr',"visible($('home-add'))",False)
        click('add','#add-herdr')
        done('new_form','#connection-profile-raw',"visible($('remote-page'))&&!$('pair-request')?.value&&!$('host-save-name')?.value&&!$('pair-mode')?.checked&&$('remote-status')?.textContent==='填写并审查新目标；不会自动连接。'",False)
        fill('import','#connection-profile-raw',raw)
        click('profile_preview','#connection-profile-preview',"$('connection-profile-raw')?.value==="+json.dumps(raw))
        done('profile_ready','#connection-profile-apply',"visible($('connection-profile-fingerprint'))&&$('connection-profile-fingerprint')?.textContent==="+json.dumps('主机公钥指纹（本地计算）：'+fingerprint),False)
        click('apply','#connection-profile-apply',"$('connection-profile-fingerprint')?.textContent==="+json.dumps('主机公钥指纹（本地计算）：'+fingerprint))
        done('target_ready','#pair-target-review',target_ready+"&&!$('pair-target-review')?.checked")
        click('target_review','#pair-target-review',target_ready+"&&!$('pair-target-review')?.checked",True)
        done('target_checked','#pair-create',target_ready+'&&'+checked('pair-target-review'))
        click('create','#pair-create',target_ready+'&&'+checked('pair-target-review'),True)
        # Product publishes request/summary before awaiting refreshHosts; neither
        # alone proves pairOperation finished. Wait for its real controls too.
        done('request_ready','#pair-preview',frozen+"&&$('pair-status')?.dataset.createPhase==='ready'&&!!$('pair-request')?.value&&visible($('pair-request-summary'))&&"+quiet)
        request=browser.read('#pair-request','value')
        public=wire(request,('version','type','request_id','device','public_key','account','host_key','issued_at','expires_at'))
        if (not isinstance(public,dict) or public.get('device')!=browser.read('#pair-device','value') or public.get('type')!='pairing-public-key-request' or public.get('version')!=2 or
                public.get('account')!=profile['username'] or public.get('host_key')!=fingerprint):
            raise GuiFailure('dual_pair_review_mismatch')
        review=host_request(host,{'op':'review_pairing','role':role,'request':request},'pairing_review')
        if (review.get('role')!=role or review.get('hostFingerprint')!=fingerprint or
                review.get('requestId')!=public.get('request_id') or
                public_host_fingerprint(public['public_key'])!=review.get('deviceFingerprint')):
            raise GuiFailure('dual_pair_review_mismatch')
        request_current="$('pair-request')?.value==="+json.dumps(request)
        summary="&&".join("$('pair-request-summary')?.textContent.includes(%s)"%json.dumps(value) for value in
                          (review['deviceFingerprint'],review['requestId'],fingerprint,profile['username']))
        done('request_reviewed','#pair-preview',request_current+'&&'+summary+'&&'+frozen+'&&'+quiet)
        diagnostic.update(step='approve',action='host_review',control='owned_host',state='dispatched')
        approved=host_request(host,{'op':'approve_pairing','role':role,'request':request,
            'requestId':review['requestId'],'deviceFingerprint':review['deviceFingerprint'],'reviewed':True},'pairing_approved')
        if approved.get('role')!=role:raise GuiFailure('dual_pair_review_mismatch')
        response=approved.get('response')
        reply=wire(response,('version','type','request_id','account','host_key','fingerprint','issued_at','expires_at','status','authorization_added'))
        if not isinstance(reply,dict) or any(reply.get(key)!=value for key,value in {'version':2,'type':'pairing-binding-response','request_id':review['requestId'],'account':profile['username'],
               'host_key':fingerprint,'fingerprint':review['deviceFingerprint'],'status':'authorized'}.items()) or type(reply['authorization_added']) is not bool:
            raise GuiFailure('dual_pair_review_mismatch')
        fill('response','#pair-response',response,request_current+'&&'+quiet,True)
        response_current=request_current+"&&$('pair-response')?.value==="+json.dumps(response)
        material_expression=pairing_response_probe(request,response,profile['username'],review['deviceFingerprint'],fingerprint,fields)
        diagnostic['sawFutureIssuance']=False
        def material():
            value=browser.evaluate(material_expression)
            if not isinstance(value,dict) or any(type(value.get(key)) is not bool for key in PAIR_RESPONSE_FACTS):
                raise GuiFailure('dual_pair_response_probe_invalid')
            facts={key:value[key] for key in PAIR_RESPONSE_FACTS}
            diagnostic['responseFacts']=facts
            if facts['wireMatches'] and (not facts['requestWithinDeviceTime'] or not facts['responseWithinDeviceTime']):
                diagnostic['sawFutureIssuance']=True
            if (any(not facts[key] for key in ('exactInput','wireMatches','requestUnexpired','responseUnexpired','expiryOrdering','withinTtl','pairMode','waitingIdentity','targetMatched')) or facts['sourceChecked']):
                raise GuiFailure('dual_pair_response_invalid')
            if facts['requestWithinDeviceTime'] and facts['responseWithinDeviceTime'] and not facts['productValid']:
                raise GuiFailure('dual_pair_response_invalid')
            return facts
        stable=0
        def material_ready():
            nonlocal stable
            facts=material();stable=stable+1 if facts['ready'] else 0
            return stable>=2
        diagnostic.update(step='response_time',action='read',control='pair_response',state='waiting')
        wait_for(material_ready,'dual_pair_device_window_timeout',timeout=30)
        lines=['账号：'+profile['username'],'主机指纹：'+fingerprint,'设备指纹：'+review['deviceFingerprint'],
               '状态：授权 (authorized)','请求 ID：'+review['requestId']]
        preview="visible($('pair-response-preview'))&&"+json.dumps(lines)+".every(line=>$('pair-response-preview')?.textContent.split(String.fromCharCode(10)).includes(line))"
        button=None
        try:
            for attempt in range(2):
                step='response_preview' if attempt==0 else 'response_reinspect'
                diagnostic.update(step=step,action='enter',control='pair_preview',state='waiting')
                stable=0;wait_for(material_ready,'dual_pair_device_window_timeout',timeout=30)
                if button is None:
                    value=browser.call('Runtime.evaluate',{'expression':"document.querySelector('#pair-preview')",'returnByValue':False})
                    button=value.get('result',{}).get('objectId')
                    if not isinstance(button,str):raise GuiFailure('dual_pair_preview_node_missing')
                verify="""function(focus){if(focus)this.focus();return this.isConnected&&this===document.querySelector('#pair-preview')&&
                  document.activeElement===this&&!document.hidden&&!this.matches(':disabled')&&!!this.getClientRects().length&&
                  this.textContent==='查看响应内容'&&!document.querySelector('#pair-source-review')?.checked;}"""
                for focus in (True,False):
                    value=browser.call('Runtime.callFunctionOn',{'objectId':button,'functionDeclaration':verify,
                        'arguments':[{'value':focus}],'returnByValue':True})
                    if value.get('result',{}).get('value') is not True:raise GuiFailure('dual_pair_preview_focus_changed')
                    if material()['ready'] is not True:raise GuiFailure('dual_pair_response_changed')
                # Standard keyboard activation of the same verified button. This
                # only re-runs the product's read-only preview, never acceptance.
                for kind in ('keyDown','keyUp'):
                    params={'type':kind,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13}
                    if kind=='keyDown':params['text']='\r'
                    browser.call('Input.dispatchKeyEvent',params)
                diagnostic['completed'].append(step);diagnostic['state']='dispatched'
                diagnostic.update(step='response_reviewed',action='read',control='pair_source_review')
                def published():
                    facts=material()
                    return facts['ready'] and facts['previewVisible'] and facts['fiveLinesMatched'] and not facts['productShowsInvalid']
                try:
                    wait_for(published,'dual_pair_preview_unpublished',timeout=4)
                    break
                except GuiFailure as error:
                    if str(error)!='dual_pair_preview_unpublished' or attempt==1:raise
                    # At most one read-only reinspection, only for exactly the
                    # same full material, identity and DOM button before review.
                    if material()['ready'] is not True:raise GuiFailure('dual_pair_response_changed')
            done('response_reviewed','#pair-source-review',response_current+'&&'+preview+"&&!$('pair-source-review')?.checked&&"+quiet)
        finally:
            if button is not None:browser.call('Runtime.releaseObject',{'objectId':button})
        click('source_review','#pair-source-review',response_current+'&&'+preview+"&&!$('pair-source-review')?.checked&&"+quiet,True)
        done('source_checked','#pair-accept',response_current+'&&'+preview+'&&'+checked('pair-source-review')+'&&'+quiet)
        click('accept','#pair-accept',response_current+'&&'+preview+'&&'+checked('pair-source-review')+'&&'+quiet,True)
        accepted="$('pair-status')?.textContent==="+json.dumps('授权响应已审查，尚未验证 SSH · '+review['deviceFingerprint'])+'&&'+quiet
        done('accepted','#host-save-name',accepted+'&&'+request_current)
        name='QA host '+role.upper()
        fill('save_name','#host-save-name',name,accepted,True)
        click('save','#host-save',accepted+"&&$('host-save-name')?.value==="+json.dumps(name),True)
        done('saved','#host-return-home',"$('host-save-status')?.textContent==='已保存本机公开资料；不代表主机已验证或仍授权。'&&$('host-save-name')?.value==="+json.dumps(name))
        host_card(browser,role)  # Renamed catalog readback, not an earlier save status.
        click('return','#host-return-home',accepted,True)
        done('returned','#host-open-remote',"visible($('host-home'))&&!visible($('remote-page'))",False)
        diagnostic['state']='complete'
    except Exception as error:
        diagnostic['state']='timeout' if str(error)=='dual_pair_step_timeout' else 'mismatch' if str(error) in ('dual_pair_review_mismatch','dual_pair_value_mismatch') else 'failed'
        raise


def bind_host(browser, role):
    title='QA TS · Tailscale' if role=='ts' else 'QA ET · EasyTier'
    profile=expand_profile(browser,title)
    browser.click_named(profile,'刷新节点状态')
    wait_for(lambda:browser.read('#network-panel > [role=status]')=='已请求读取当前节点状态。',
             'dual_binding_readback_not_ready',timeout=60)
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
    wait_for(lambda:browser.read('#network-panel > [role=status]')=='操作已确认；请查看节点及连接状态。' and
             browser.read(scope+' select','value') == option, 'dual_binding_save_missing', timeout=60)
    return option


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
        report['stage']='device_auth_handler'
        prepare_auth_receiver(parsed.port,report)
        report['stage']='device_setup'
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
        report['stage']='device_home'
        report['ordinaryWebViewHomeVerified']=wait_for(lambda:browser.evaluate(
            "document.querySelector('.app-header h1')?.textContent.trim()==='Herdr Pocket'") is True,
            'dual_ordinary_home_not_ready',timeout=45) is True
        report['stage']='device_native_tree'
        report['ordinaryNativeTree']=wait_for_ordinary_tree(report)
        report['stage']='network_setup'
        install_start_observer(browser,parsed.port)
        report['startObserverInstalled']=True
        report['transportBeforeNetwork']=public_transport_sample(session)
        browser.click('#nav-network')
        wait_for(lambda:browser.evaluate("!document.querySelector('#network-panel').hidden"),'dual_network_page_missing')
        ts_scope=create_network(browser,'ts',material,report)
        create_network(browser,'et',material,report)
        report['stage']='network_ts_authorize'
        authorize_ts(browser,control,ts_scope,parsed.port,report)
        wait_for(lambda:'Tailscale 报告 Running' in (browser.read(ts_scope) or ''), 'dual_ts_running_missing',timeout=120)
        report['tsExplicitAuthorization']=True
        report['stage']='pairing'
        browser.click('#show-remote')
        for role in ('ts','et'):
            pair_host(browser,control,role,session.read_host_profile(role),report)
        report['pairingApprovedBoth']=True
        browser.click('#nav-network')
        bindings={role: bind_host(browser,role) for role in ('ts','et')}
        if not all(isinstance(value,str) and value for value in bindings.values()):
            raise GuiFailure('dual_binding_targets_invalid')
        if bindings['ts']==bindings['et']:
            raise GuiFailure('dual_binding_targets_not_distinct')
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
        install_stop_observer(browser)
        report['stage']='stop_first'
        first_profile=stop_node_once(browser,scope,stopped,
                                     'QA TS · Tailscale' if stopped=='ts' else 'QA ET · EasyTier',
                                     'QA host TS' if stopped=='ts' else 'QA host ET',
                                     bindings[stopped],
                                     stage='stop_first',attempts=report.setdefault('stopAttempts',[]))
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
        report['stage']='stop_survivor'
        browser.click('#nav-network')
        survivor_scope=expand_profile(browser,'QA TS · Tailscale' if surviving=='ts' else 'QA ET · EasyTier')
        stop_node_once(browser,survivor_scope,surviving,
                       'QA TS · Tailscale' if surviving=='ts' else 'QA ET · EasyTier',
                       'QA host TS' if surviving=='ts' else 'QA host ET',
                       bindings[surviving],
                       stage='stop_survivor',attempts=report.setdefault('stopAttempts',[]),
                       distinct_ids=(first_profile,))
        wait_named(browser,survivor_scope,'启动节点',timeout=120)
        uninstall_stop_observer(browser)
        audit(control,surviving,initials[surviving]+second,ordinal=ordinal,sessions_count=count,active=False)
        report['survivorExplicitlyStoppedAndClosed']=True
        report['stage']='complete'
    except Exception as error:
        try:
            from tauri_auth_failure_diagnostic import capture
            report['androidFailureDiagnostic']=capture(adb,native_ui_nodes,foreground_component,{PACKAGE,AUTH_PACKAGE},parsed.port)
        except Exception:report['androidFailureDiagnostic']={'scope':'read-only-failure-facts','readUnavailable':True}
        try:report['foregroundAtFailure']=component_kind(foreground_component())
        except Exception:report['foregroundAtFailure']='unavailable'
        if report.get('stage') in {'pairing','connect_and_input','stop_first','post_stop','stop_survivor','complete'}:
            report['hostCountsAtFailure']=public_host_failure_counts(control)
        try:report['transportAtFailure']=public_transport_sample(session)
        except Exception:report['transportAtFailureUnavailable']=True
        if browser:
            try:report['controlCountsAtFailure']=browser.evaluate("""(()=>{const enabled=id=>{const e=document.getElementById(id);return !!e&&!e.matches(':disabled');};
              const tabs=[...document.querySelectorAll('#view-tabs > button')];return {
                tabButtons:Math.min(tabs.length,9),visibleTabButtons:Math.min(tabs.filter(e=>e.getClientRects().length).length,9),
                pairCreateEnabled:enabled('pair-create'),pairAcceptEnabled:enabled('pair-accept'),connectEnabled:enabled('remote-connect'),
                remotePageVisible:!!document.querySelector('#remote-page')&&!document.querySelector('#remote-page').hidden,
                hostHomeVisible:!!document.querySelector('#host-home')&&!document.querySelector('#host-home').hidden}})()""")
            except Exception:report['controlCountsAtFailureUnavailable']=True
            try:report['startResultObservation']=start_observer_snapshot(browser)
            except Exception:report['startResultObservationUnavailable']=True
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
            try:report['startResultObservation']=start_observer_snapshot(browser)
            except Exception:report['startResultObservationUnavailable']=True
            try:
                report['startObserverRestored']=browser.evaluate("(()=>{const x=window.__dualStartObserver;if(!x)return false;window.ipc=x.original;delete window.__dualStartObserver;return window.ipc===x.original})()") is True
            except Exception:report['startObserverRestored']=False
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


DUAL_ENVIRONMENT_CLEANUP_KEYS=frozenset({'reverseRemoved','relayStopped','controllerStopped','namespaceRemoved',
                                         'hostPrivateDirectoryRemoved','controlReaderStopped','privateFilesRemoved'})
KNOWN_SESSION_ERRORS={'host_control_unavailable','host_controller_readiness_invalid','host_material_reachability_claim_invalid',
                      'owned_namespace_collision','controlled_session_command_failed','owned_private_material_required',
                      'bounded_private_material_required','shared_overlay_session_cleanup_incomplete'}


def failure_code(error):
    from android_dual_overlay_session import SessionError
    text=str(error)
    return text if re.fullmatch(r'dual_[a-z0-9_]{1,80}',text) or isinstance(error,SessionError) and text in KNOWN_SESSION_ERRORS else 'dual_driver_failed'


def direction_cleanup_proven(current):
    cleanup=current.get('environmentCleanup')
    return (isinstance(cleanup,dict) and DUAL_ENVIRONMENT_CLEANUP_KEYS <= cleanup.keys() and
            all(cleanup[key] is True for key in DUAL_ENVIRONMENT_CLEANUP_KEYS) and
            current.get('packagesRemoved') is True and current.get('privateDirectoryRemoved') is True and
            current.get('browserClosed',True) is True and current.get('forwardRemoved',True) is True)


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
    parser.add_argument('--native-source-sha', required=True)
    parser.add_argument('--apk-source-sha', required=True)
    args=parser.parse_args()
    for name,value in (('native-source-sha',args.native_source_sha),('apk-source-sha',args.apk_source_sha),
                       ('host-source-sha',args.host_source_sha)):
        if not re.fullmatch(r'[0-9a-f]{40}',value or ''):raise SystemExit('dual_'+name.replace('-','_')+'_invalid')
    root=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    paths=[args.apk.resolve(strict=True),args.auth_apk.resolve(strict=True),args.bundle.resolve(strict=True),args.output.resolve()]
    if any(path==root or not path.is_relative_to(root) for path in paths):
        raise SystemExit('dual_owned_paths_required')
    output=paths[3];output.mkdir(parents=True,exist_ok=True)
    result={'schemaVersion':1,'status':'failed','sourceSHA':os.environ.get('GITHUB_SHA'),
            'nativeSourceSHA':args.native_source_sha,
            'apkSourceSHA':args.apk_source_sha,
            'apkFrontendDifference':'none from checked application source',
            'scope':'owned API35 x86_64; real UI, synthetic peers, QA-only TS private trust; no physical IME',
            'apkSha256':hashlib.sha256(paths[0].read_bytes()).hexdigest(),'directions':{}}
    from android_dual_overlay_session import AndroidDualOverlaySession
    result['hostSourceSHA']=args.host_source_sha
    try:
        for role in ('ts','et'):
            current={'stage':'setup'};result['directions'][role]=current
            try:
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
                          'survivorSameAuthenticatedSession','stoppedInputUnavailableAndUnchanged','survivorExplicitlyStoppedAndClosed',
                          'browserClosed','forwardRemoved','packagesRemoved','privateDirectoryRemoved','startObserverInstalled','startObserverRestored')
                cleanup=current['environmentCleanup']
                if (current.get('stage')!='complete' or any(current.get(key) is not True for key in required) or
                        current.get('staleInputGuard') not in ('retained_tab_disabled_keyboard_tested','removed_tab_unreachable') or
                        not isinstance(cleanup,dict) or not cleanup or any(value is not True for value in cleanup.values())):
                    raise GuiFailure('dual_evidence_incomplete')
            except Exception as error:
                current['directionErrorCode']=failure_code(error)
                result.setdefault('errorCode',current['directionErrorCode'])
                if not direction_cleanup_proven(current):raise
        if 'errorCode' not in result:result['status']='passed'
    except Exception as error:
        result.setdefault('errorCode',failure_code(error))
    finally:
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    if result['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
