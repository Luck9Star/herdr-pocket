#!/usr/bin/env python3
"""Exercise the shipped Tauri ordinary SSH UI on an owned API35 emulator.

The fixture is local and synthetic. No IPC implementation is replaced and only
bounded boolean evidence is written; credentials and terminal output stay local.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from android_gui import AndroidWebView, PACKAGE, SERIAL, adb
from paired_gui import GuiFailure, wait_for


def exercise_ui(browser, fixture, *, encrypted_key=False):
    """Use actual CDP click/keyboard events and independently check the peer."""
    browser.click('#host-open-remote')
    browser.click('#add-ssh')
    browser.fill('#ssh-host', '127.0.0.1')
    browser.fill('#ssh-port', str(fixture.port))
    browser.fill('#ssh-user', fixture.username)
    browser.click('#ssh-probe')
    wait_for(lambda: fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''),
             'direct_fingerprint_missing', timeout=60)
    browser.click('#ssh-review')
    if encrypted_key:
        browser.select_option('#ssh-auth-method', 'key')
        browser.fill('#ssh-key', fixture.private_key)
        browser.fill('#ssh-passphrase', fixture.passphrase)
    else:
        browser.fill('#ssh-password', fixture.password)
    if browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_credential_invalidated_host_review')
    browser.click('#ssh-form button[type=submit]')
    wait_for(lambda: browser.evaluate("!document.querySelector('#ssh-live').hidden") and
             '已连接' in (browser.read('#ssh-status') or ''), 'direct_ready_missing', timeout=60)
    if browser.evaluate("!!document.querySelector('#ssh-password').value || !!document.querySelector('#ssh-key').value || !!document.querySelector('#ssh-passphrase').value"):
        raise GuiFailure('direct_credentials_retained')
    browser.click('#ssh-focus')
    wait_for(lambda: browser.evaluate("document.activeElement === document.querySelector('#ssh-terminal .xterm-helper-textarea')"),
             'direct_terminal_focus_missing')
    browser.call('Input.insertText', {'text': fixture.marker})
    for kind in ('keyDown', 'keyUp'):
        browser.call('Input.dispatchKeyEvent', {'type':kind,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
    wait_for(lambda: fixture.snapshot().get('markerReceived') is True,
             'direct_peer_input_missing', timeout=60)
    wait_for(lambda: browser.evaluate("[...document.querySelectorAll('#ssh-terminal .xterm-rows > div')].some(e=>e.textContent.includes(%s))" % json.dumps(fixture.echo_marker)),
             'direct_terminal_echo_missing', timeout=60)
    if not encrypted_key:
        for key in ('esc', 'tab', 'left', 'ctrl-c'):
            browser.click(f'#ssh-helper-keys button[data-ssh-key="{key}"]')
        wait_for(lambda: fixture.snapshot().get('helperKeysExact') is True,
                 'direct_helper_keys_mismatch', timeout=30)
    if fixture.snapshot().get('sessionClosed') is not False:
        raise GuiFailure('direct_session_ended_before_disconnect')
    browser.click('#ssh-disconnect')
    wait_for(lambda: not browser.evaluate("document.querySelector('#ssh-setup').hidden") and
             '已断开' in (browser.read('#ssh-status') or ''), 'direct_disconnect_ui_missing', timeout=60)
    wait_for(lambda: fixture.snapshot().get('sessionClosed') is True,
             'direct_peer_close_missing', timeout=60)
    peer = fixture.snapshot()
    if (not encrypted_key and peer.get('helperKeysExact') is not True) or any(peer.get(k) is not True for k in ('authAccepted','ptyRequested','shellRequested','markerReceived','sessionClosed')):
        raise GuiFailure('direct_peer_evidence_incomplete')
    return {'fingerprintReviewed':True,'credentialReviewPreserved':True,'connected':True,
            'terminalInputReceived':True,'terminalEchoRendered':True,'disconnected':True,
            'passwordCleared':True, **({'helperKeysExact':True} if not encrypted_key else {}), 'peer':{k:True for k in ('authAccepted','ptyRequested','shellRequested','markerReceived','sessionClosed')}}


def exercise_key_change_ui(browser, fixture, *, evidence_dir=None):
    """Same host:port A→B: refuse, review with no exits, cancel, re-probe, approve."""
    browser.click('#host-open-remote')
    browser.click('#add-ssh')
    browser.fill('#ssh-host', '127.0.0.1')
    browser.fill('#ssh-port', str(fixture.port))
    browser.fill('#ssh-user', fixture.username)
    browser.click('#ssh-probe')
    wait_for(lambda: fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''),
             'direct_rotation_probe_missing', timeout=60)
    browser.click('#ssh-review')
    browser.fill('#ssh-password', fixture.password)
    if browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_rotation_review_invalidated')
    browser.click('#ssh-form button[type=submit]')
    wait_for(lambda: browser.evaluate("!document.querySelector('#ssh-key-change').hidden"),
             'direct_rotation_review_missing', timeout=60)
    review_text = (browser.read('#ssh-key-change') or '')
    if (fixture.fingerprint not in review_text or fixture.rotated_fingerprint not in review_text):
        raise GuiFailure('direct_rotation_review_content_missing')
    if f'{fixture.username}@127.0.0.1:{fixture.port}' not in (browser.read('#ssh-key-change-target') or ''):
        raise GuiFailure('direct_rotation_review_target_missing')
    actions = browser.evaluate("[...document.querySelectorAll('#ssh-key-change button')].filter(b=>!b.hidden).map(b=>b.id)")
    if sorted(actions or []) != ['ssh-key-cancel', 'ssh-key-recheck']:
        raise GuiFailure('direct_rotation_actions_invalid')
    # While the review is open every other navigation exit is removed entirely;
    # a disabled leftover would still be an escape hatch for mouse and keyboard.
    if browser.evaluate("!document.querySelector('.app-header').hidden || !document.querySelector('.route-tabs').hidden"):
        raise GuiFailure('direct_rotation_navigation_available')
    if evidence_dir is not None:
        _save_review_screenshot(browser, evidence_dir)
    fixture.wait_for_connections_closed(minimum=2, timeout=30)
    evidence_2 = _rotation_stage(fixture, 2)
    # Cancelling keeps the old trust: the review closes, navigation returns and
    # no new connection is attempted.
    browser.click('#ssh-key-cancel')
    wait_for(lambda: browser.evaluate("document.querySelector('#ssh-key-change').hidden && !document.querySelector('.app-header').hidden && !document.querySelector('.route-tabs').hidden"),
             'direct_rotation_cancel_navigation_missing', timeout=60)
    cancelled = (browser.read('#ssh-fingerprint') or '')
    if fixture.fingerprint not in cancelled or fixture.rotated_fingerprint in cancelled:
        raise GuiFailure('direct_rotation_cancel_old_key_missing')
    if browser.evaluate("document.querySelector('#ssh-review').checked") is not False:
        raise GuiFailure('direct_rotation_cancel_review_stale')
    if browser.evaluate("!document.querySelector('#ssh-review').disabled") is not False:
        raise GuiFailure('direct_rotation_cancel_entries_live')
    if browser.evaluate("!!document.querySelector('#ssh-password').value || !document.querySelector('#ssh-password').disabled"):
        raise GuiFailure('direct_rotation_cancel_credentials_live')
    if browser.evaluate("!document.querySelector('#ssh-form button[type=submit]').disabled") is not False:
        raise GuiFailure('direct_rotation_cancel_submit_live')
    if fixture.snapshot().get('connections') != 2:
        raise GuiFailure('direct_rotation_cancel_reconnected')
    # The explicit re-probe from the visible form presents the changed key for
    # fresh human review; the hidden review buttons are never driven.
    browser.click('#ssh-probe')
    wait_for(lambda: fixture.rotated_fingerprint in (browser.read('#ssh-fingerprint') or ''),
             'direct_rotation_reprobe_missing', timeout=60)
    if fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''):
        raise GuiFailure('direct_rotation_reprobe_old_key_stale')
    # Nothing is pre-approved: the confirmation box and credentials start
    # unlocked-but-empty at best, and no stale review may survive the probe.
    if browser.evaluate("document.querySelector('#ssh-review').checked") is not False:
        raise GuiFailure('direct_rotation_reprobe_review_stale')
    if browser.evaluate("!!document.querySelector('#ssh-password').value"):
        raise GuiFailure('direct_rotation_reprobe_credentials_stale')
    fixture.wait_for_connections_closed(minimum=3, timeout=30)
    evidence_3 = _rotation_stage(fixture, 3)
    browser.click('#ssh-review')
    browser.fill('#ssh-password', fixture.password)
    if browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_rotation_review_invalidated')
    browser.click('#ssh-form button[type=submit]')
    wait_for(lambda: browser.evaluate("!document.querySelector('#ssh-live').hidden") and
             '已连接' in (browser.read('#ssh-status') or ''), 'direct_rotation_ready_missing', timeout=60)
    if browser.evaluate("!!document.querySelector('#ssh-password').value"):
        raise GuiFailure('direct_rotation_credentials_retained')
    browser.click('#ssh-focus')
    wait_for(lambda: browser.evaluate("document.activeElement === document.querySelector('#ssh-terminal .xterm-helper-textarea')"),
             'direct_rotation_terminal_focus_missing')
    browser.call('Input.insertText', {'text': fixture.marker})
    for kind in ('keyDown', 'keyUp'):
        browser.call('Input.dispatchKeyEvent', {'type':kind,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
    wait_for(lambda: fixture.snapshot().get('markerReceived') is True,
             'direct_rotation_peer_input_missing', timeout=60)
    wait_for(lambda: browser.evaluate("[...document.querySelectorAll('#ssh-terminal .xterm-rows > div')].some(e=>e.textContent.includes(%s))" % json.dumps(fixture.echo_marker)),
             'direct_rotation_terminal_echo_missing', timeout=60)
    browser.click('#ssh-disconnect')
    wait_for(lambda: '已断开' in (browser.read('#ssh-status') or ''), 'direct_rotation_disconnect_ui_missing', timeout=60)
    fixture.wait_for_connections_closed(minimum=4, timeout=30)
    evidence_4 = _rotation_stage(fixture, 4)
    return {'probeReviewed':True,'refusalBlocked':True,'reviewNoExits':True,'cancelKeptTrust':True,
            'reprobePresented':True,'connected':True,'terminalInputReceived':True,'terminalEchoRendered':True,
            'disconnected':True,'passwordCleared':True,
            'rotationEvidence':[evidence_2,evidence_3,evidence_4]}


def _save_review_screenshot(browser, evidence_dir):
    """Best-effort PNG of the refused review page; public fingerprints only."""
    try:
        shot = browser.call('Page.captureScreenshot', {'format': 'png'})
        data = (shot or {}).get('data')
        if data:
            (Path(evidence_dir) / 's10-host-key-change-android.png').write_bytes(base64.b64decode(data))
    except Exception:
        pass


def _rotation_stage(fixture, stage):
    """The shared peer owns the sequence judgement; the driver only demands it."""
    try:
        return fixture.rotation_evidence(stage)
    except ValueError:
        raise GuiFailure('direct_rotation_evidence_invalid')


def run_device(apk, fixture, *, encrypted_key=False, key_change=False, evidence_dir=None):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('ANDROID_SERIAL') != SERIAL or
            not os.environ.get('GITHUB_REF','').startswith('refs/heads/codex/') or not apk.is_file()):
        raise GuiFailure('direct_unsafe_fixture')
    devices=[line.split()[:2] for line in adb('devices').splitlines()[1:] if line.strip()]
    if (devices != [[SERIAL,'device']] or adb('shell','getprop','ro.kernel.qemu') != '1' or
            adb('shell','getprop','ro.build.version.sdk') != '35' or
            adb('shell','am','get-current-user') != '0' or
            'package:' + PACKAGE in adb('shell','pm','list','packages',PACKAGE)):
        raise GuiFailure('direct_unowned_or_invalid_device')
    reverse=f'tcp:{fixture.port}'
    installed=False; forwarded=None; browser=None; reverse_added=False; cleanup=[]
    try:
        adb('reverse',reverse,reverse);reverse_added=True
        adb('install',str(apk),timeout=90);installed=True
        adb('shell','monkey','-p',PACKAGE,'-c','android.intent.category.LAUNCHER','1')
        pid=wait_for(lambda:adb('shell','pidof',PACKAGE,check=False),'direct_app_missing',timeout=60)
        if not re.fullmatch(r'\d+',pid):raise GuiFailure('direct_app_pid_invalid')
        socket_name='webview_devtools_remote_'+pid
        wait_for(lambda:'@'+socket_name in adb('shell','cat','/proc/net/unix',check=False),
                 'direct_webview_socket_missing',timeout=60)
        port=adb('forward','tcp:0','localabstract:'+socket_name)
        if not port.isdigit() or not 1 <= int(port) <= 65535:raise GuiFailure('direct_forward_invalid')
        forwarded='tcp:'+port
        def connect():
            try:
                view=AndroidWebView(int(port))
                if view.evaluate("document.readyState === 'complete' && !!document.querySelector('#ssh-form') && !!window.__TAURI_INTERNALS__"):
                    return view
                view.close()
            except GuiFailure: pass
            return False
        browser=wait_for(connect,'direct_webview_not_ready',timeout=60)
        result=(exercise_key_change_ui(browser,fixture,evidence_dir=evidence_dir) if key_change
                else exercise_ui(browser,fixture,encrypted_key=encrypted_key))
    finally:
        if browser:
            try: browser.close()
            except Exception: cleanup.append('browser')
        if installed:
            try:
                adb('shell','am','force-stop',PACKAGE);adb('uninstall',PACKAGE,timeout=60)
                if adb('shell','pidof',PACKAGE,check=False) or 'package:'+PACKAGE in adb('shell','pm','list','packages',PACKAGE):
                    cleanup.append('application')
            except GuiFailure: cleanup.append('application')
        if forwarded:
            try:
                adb('forward','--remove',forwarded)
                if any(forwarded in row.split() for row in adb('forward','--list').splitlines()): cleanup.append('forward')
            except GuiFailure: cleanup.append('forward')
        if reverse_added:
            try:
                adb('reverse','--remove',reverse)
                if any(reverse in row.split() for row in adb('reverse','--list').splitlines()): cleanup.append('reverse')
            except GuiFailure: cleanup.append('reverse')
        if cleanup: raise GuiFailure('direct_cleanup_failed')
    result['cleanup']={'browser':True,'application':True,'forward':True,'reverse':True}
    return result


def probe_evidence(fixture):
    """Report only whether the owned peer saw a connection or authentication."""
    peer = fixture.snapshot()
    return {'connectionObserved': isinstance(peer.get('connections'), int) and peer['connections'] > 0,
            'authenticationAccepted': peer.get('authAccepted') is True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apk',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(os.environ.get('RUNNER_TEMP','/nonexistent')).resolve()
    output=args.output.absolute()
    if output.resolve()!=output or not output.is_relative_to(root) or output==root:
        raise SystemExit('direct_output_invalid')
    output.mkdir(parents=True,exist_ok=True)
    sha=os.environ.get('GITHUB_SHA','')
    report={'schemaVersion':1,'sourceSHA':sha if re.fullmatch(r'[0-9a-f]{40}',sha) else None,
            'status':'failed','scope':'synthetic loopback SSH and owned API35 Android WebView; CDP input is not real IME composition'}
    try:
        from direct_ssh_fixture import DirectSshFixture
        report['apkSha256']=hashlib.sha256(args.apk.read_bytes()).hexdigest()
        with DirectSshFixture(observe_helper_keys=True) as fixture:
            try:
                report.update(run_device(args.apk,fixture))
            except GuiFailure:
                report['probeEvidence'] = probe_evidence(fixture)
                raise
        if fixture.snapshot().get('connectionsClosed') is not True:
            raise GuiFailure('direct_fixture_cleanup_failed')
        report['cleanup']['fixtureConnections']=True
        with DirectSshFixture(rotate_after_probe=True, observe_helper_keys=True) as rotation:
            report['phase']='host_key_rotation'
            try:
                rotation_result=run_device(args.apk,rotation,key_change=True,evidence_dir=output)
                rotation_result['s10Screenshot']=(output/'s10-host-key-change-android.png').exists()
            except GuiFailure:
                report['probeEvidence'] = probe_evidence(rotation)
                raise
        if rotation.snapshot().get('connectionsClosed') is not True:
            raise GuiFailure('direct_fixture_cleanup_failed')
        rotation_result['cleanup']['fixtureConnections']=True
        report['rotation']=rotation_result
        from tauri_encrypted_key_fixture import EncryptedKeyFixture
        report['phase']='encrypted_key'
        with EncryptedKeyFixture() as key_fixture:
            try:
                key_result=run_device(args.apk,key_fixture,encrypted_key=True)
            except GuiFailure:
                report['probeEvidence'] = probe_evidence(key_fixture)
                raise
        if key_fixture.snapshot().get('connectionsClosed') is not True:
            raise GuiFailure('direct_fixture_cleanup_failed')
        key_result['cleanup']['fixtureConnections']=True
        report['encryptedKey']=key_result
        report['phase']='complete'
        report['status']='passed'
    except GuiFailure as error:
        code=str(error)
        report['errorCode']=code if re.fullmatch(r'direct_[a-z0-9_]{1,80}',code) else 'direct_driver_failed'
    except Exception:
        report['errorCode']='direct_fixture_or_driver_failed'
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if report['status']!='passed': raise SystemExit(1)


if __name__=='__main__': main()
