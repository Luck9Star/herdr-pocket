#!/usr/bin/env python3
"""Exercise the shipped Tauri ordinary SSH UI on an owned API35 emulator.

The fixture is local and synthetic. No IPC implementation is replaced and only
bounded boolean evidence is written; credentials and terminal output stay local.
"""
import argparse
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import shutil
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from android_gui import AndroidWebView, PACKAGE, SERIAL, adb, dashboard_add_selector, system_keyboard, public_ime_diagnostic
from flutter_android_gui import parse_system_ime, SystemImeFailure, DeviceFailure
from paired_gui import GuiFailure, wait_for
from terminal_screenshot_gate import ECHO_MARKER, ScreenshotGateError, verify_terminal_screenshot


# Public diagnostics are fixed labels; do not export exception text or selectors.
DIRECT_ERROR_CODES = frozenset('''
    direct_app_missing direct_app_pid_invalid direct_cleanup_failed
    direct_credential_invalidated_host_review direct_credentials_retained direct_disconnect_ui_missing
    direct_driver_failed direct_fingerprint_missing direct_fixture_cleanup_failed
    direct_fixture_or_driver_failed direct_forward_invalid direct_helper_keys_mismatch
    direct_output_invalid direct_peer_close_missing direct_peer_evidence_incomplete
    direct_peer_input_missing direct_ready_missing direct_rotation_actions_invalid
    direct_rotation_cancel_credentials_live direct_rotation_cancel_entries_live direct_rotation_cancel_navigation_missing
    direct_rotation_cancel_old_key_missing direct_rotation_cancel_reconnected direct_rotation_cancel_review_stale
    direct_rotation_cancel_submit_live direct_rotation_credentials_retained direct_rotation_disconnect_ui_missing
    direct_rotation_evidence_invalid direct_rotation_navigation_available direct_rotation_peer_input_missing
    direct_rotation_probe_missing direct_rotation_ready_missing direct_rotation_reprobe_credentials_stale
    direct_rotation_reprobe_missing direct_rotation_reprobe_old_key_stale direct_rotation_reprobe_review_stale
    direct_rotation_review_content_missing direct_rotation_review_invalidated direct_rotation_review_missing
    direct_rotation_review_target_missing direct_rotation_terminal_echo_missing direct_rotation_terminal_focus_missing
    direct_session_ended_before_disconnect direct_terminal_capture_failed direct_terminal_echo_missing
    direct_terminal_evidence_directory_missing direct_terminal_focus_missing direct_terminal_framebuffer_capture_failed
    direct_terminal_framebuffer_mapping_invalid direct_terminal_geometry_changed direct_terminal_hierarchy_cleanup_failed
    direct_terminal_hierarchy_invalid direct_terminal_pixel_registration_failed direct_terminal_screenshot_bounds_invalid
    direct_terminal_screenshot_echo_not_visible direct_terminal_screenshot_ocr_failed direct_terminal_screenshot_ocr_missing
    direct_terminal_screenshot_pillow_missing direct_terminal_screenshot_png_invalid direct_terminal_screenshot_proof_not_adjacent
    direct_terminal_screenshot_token_invalid direct_terminal_screenshot_token_not_visible direct_terminal_target_missing
    direct_terminal_webview_capture_failed direct_header_measurement_invalid direct_header_system_overlap direct_header_content_overlap direct_header_geometry_changed
    direct_unowned_or_invalid_device direct_unsafe_fixture direct_return_home_missing direct_return_home_peer_changed
    direct_setup_layout_unproven direct_mobile_setup_unproven direct_probe_peer_unproven
    direct_active_ui_invalid direct_active_peer_changed direct_active_tap_unproven
    direct_ime_proof_install_unconfirmed direct_ime_proof_page_state_invalid direct_ime_proof_foreground_lost
    direct_ime_proof_marker_not_visible direct_ime_proof_ocr_missing direct_ime_proof_ocr_failed
    direct_ime_proof_publish_failed direct_ime_proof_capture_failed
    direct_webview_not_ready direct_webview_socket_missing
'''.split())
ANDROID_ERROR_CODES = {
    'android_adb_unavailable': 'direct_android_adb_unavailable',
    'android_adb_command_failed': 'direct_android_adb_command_failed',
    'android_adb_output_limit': 'direct_android_adb_output_limit',
    'android_webview_target_missing': 'direct_android_webview_target_missing',
    'android_webview_target_invalid': 'direct_android_webview_target_invalid',
    'android_webview_cdp_unavailable': 'direct_android_webview_cdp_unavailable',
    'android_cdp_output_limit': 'direct_android_cdp_output_limit',
    'android_cdp_command_failed': 'direct_android_cdp_command_failed',
    'android_cdp_transport_failed': 'direct_android_cdp_transport_failed',
    'android_control_operation_failed': 'direct_android_control_operation_failed',
    'android_text_input_mismatch': 'direct_android_text_input_mismatch',
    'android_select_option_missing': 'direct_android_select_option_missing',
    'android_select_option_failed': 'direct_android_select_option_failed',
    'android_system_ime_target_mismatch': 'direct_android_system_ime_target_mismatch',
    'android_system_ime_evidence_unavailable': 'direct_android_system_ime_evidence_unavailable',
    'android_system_ime_show_unconfirmed': 'direct_android_system_ime_show_unconfirmed',
    'android_system_ime_hide_unconfirmed': 'direct_android_system_ime_hide_unconfirmed',
}


def public_driver_error(error):
    code = str(error)
    if code in DIRECT_ERROR_CODES:
        return code
    if code in ANDROID_ERROR_CODES:
        return ANDROID_ERROR_CODES[code]
    if code.startswith('android_control_missing_'):
        return 'direct_android_control_missing'
    if code.startswith('android_text_control_missing_'):
        return 'direct_android_text_control_missing'
    return 'direct_driver_failed'


DRIVER_STAGES = frozenset({'device_preflight', 'reverse_setup', 'install_app', 'launch_app',
    'webview_socket', 'webview_forward', 'webview_ready', 'rotation_ui', 'open_remote',
    'open_ssh_form', 'enter_host', 'enter_port', 'enter_user', 'probe_host',
    'await_fingerprint', 'review_fingerprint', 'select_key_auth', 'enter_private_key',
    'active_initial', 'active_keyboard_opened', 'active_keyboard_closed', 'active_board',
    'active_terminal_from_board', 'active_network', 'active_terminal_from_network',
    'active_settings', 'active_terminal_from_settings',
    'enter_passphrase', 'enter_password', 'connect', 'terminal_input', 'disconnect', 'return_home', 'cleanup'})



def _header_geometry(browser):
    # Read only the existing native inset command and bounded public DOM geometry.
    expression = """(async () => {
      const n=await window.__TAURI_INTERNALS__.invoke('mobile_system_top_inset');
      const measure=selector=>{
        const e=document.querySelector(selector),r=e?.getBoundingClientRect();
        if (!e || !r) return {rect:null,visible:false};
        const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);
        return {rect:[r.left,r.top,r.width,r.height],
          visible:e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) &&
            !!hit && (hit===e || e.contains(hit))};
      };
      const vv=window.visualViewport;
      const compact=matchMedia('(max-width:599px)').matches;
      return {native:{overlapPx:n.overlapPx,systemBottomPx:n.systemBottomPx,viewY:n.viewY,
          statusPx:n.statusPx,stableStatusPx:n.stableStatusPx,windowTopPx:n.windowTopPx,
          cutoutPx:n.cutoutPx,captionPx:n.captionPx,stableCaptionPx:n.stableCaptionPx},
        viewport:[innerWidth,innerHeight],dpr:devicePixelRatio,
        visualViewport:vv?[vv.offsetLeft,vv.offsetTop,vv.scale]:null,scrollY:scrollY,
        appliedTopCss:parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hp-system-top-inset')),
        header:measure(compact?'.ssh-live-header':'.app-header'),title:measure(compact?'#ssh-active-title':'.app-header h1'),button:measure(compact?'#ssh-disconnect':'#host-open-remote'),
        sshTitle:measure(compact?'#ssh-active-title':'#ssh-page-heading'),target:measure(compact?'#ssh-live-endpoint':'#ssh-target'),
        terminal:measure('.ssh-scroll'),xterm:measure('#ssh-terminal .xterm-screen')};
    })()"""
    try:
        result=browser.call('Runtime.evaluate', {'expression':expression, 'returnByValue':True, 'awaitPromise':True})
        if 'exceptionDetails' in result: raise ValueError()
        value=result.get('result',{}).get('value')
        if not isinstance(value,dict): raise ValueError()
        return value
    except (GuiFailure,AttributeError,TypeError,ValueError):
        raise GuiFailure('direct_header_measurement_invalid') from None


def _header_evidence(geometry, *, origin, image_size):
    """Check API35 native physical insets and CSS rectangles against the actual frame."""
    evidence={}
    try:
        if not isinstance(geometry,dict): raise ValueError()
        viewport=geometry['viewport']; visual=geometry['visualViewport']; dpr=geometry['dpr']
        native=geometry['native']; native_keys=('overlapPx','systemBottomPx','viewY','statusPx',
            'stableStatusPx','windowTopPx','cutoutPx','captionPx','stableCaptionPx')
        if (not isinstance(native,dict) or any(type(native.get(k)) is not int for k in native_keys) or
                any(abs(native[k])>1_000_000 for k in native_keys) or
                any(native[k]<0 for k in native_keys if k != 'viewY') or
                not isinstance(viewport,list) or len(viewport)!=2 or
                not isinstance(visual,list) or visual!=[0,0,1] or
                type(dpr) not in (int,float) or not math.isfinite(dpr) or not 0<dpr<=100 or
                any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1_000_000 for v in viewport) or
                not isinstance(origin,(list,tuple)) or len(origin)!=2 or any(type(v) is not int for v in origin) or
                not isinstance(image_size,(list,tuple)) or len(image_size)!=2 or
                any(type(v) is not int or v<=0 for v in image_size)):
            raise ValueError()
        for key in ('scrollY','appliedTopCss'):
            if type(geometry.get(key)) not in (int,float) or not math.isfinite(geometry[key]) or abs(geometry[key])>1_000_000: raise ValueError()
        overlap=native['overlapPx'];system=native['systemBottomPx'];view_y=native['viewY']
        top=native['windowTopPx']+max(native[k] for k in ('statusPx','stableStatusPx','cutoutPx','captionPx','stableCaptionPx'))
        if system!=top or overlap!=max(0,system-view_y) or origin[1]!=view_y: raise ValueError()
        vw,vh=viewport; ox,oy=origin; iw,ih=image_size
        if not (-iw<ox<iw and -ih<oy<ih and system<=ih and overlap<=vh*dpr): raise ValueError()
        evidence={'nativePx':{k:native[k] for k in native_keys},'viewportCss':list(viewport),
            'visualViewport':list(visual),'devicePixelRatio':dpr,'scrollYCss':geometry['scrollY'],
            'appliedTopCss':geometry['appliedTopCss'],'webViewOriginPx':list(origin),'imageSizePx':list(image_size)}
        rectangles={}
        for name in ('header','title','button','sshTitle','target','terminal','xterm'):
            item=geometry[name];rect=item['rect']
            if (not isinstance(rect,list) or len(rect)!=4 or
                    any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1_000_000 for v in rect) or
                    type(item['visible']) is not bool): raise ValueError()
            x,y,w,h=rect
            if w<=0 or h<=0: raise ValueError()
            rectangles[name]=rect
            in_view=x<vw and x+w>0 and y<vh and y+h>0
            evidence[name]={'rectCss':rect,'visible':item['visible'],'inViewport':in_view}
            if name in ('title','button','target'):
                if not item['visible'] or not (0<=x and 0<=y and x+w<=vw and y+h<=vh): raise ValueError()
                x0=math.floor(ox+x*dpr);y0=math.floor(oy+y*dpr)
                x1=math.ceil(ox+(x+w)*dpr);y1=math.ceil(oy+(y+h)*dpr)
                if not (0<=x0<x1<=iw and 0<=y0<y1<=ih): raise ValueError()
                evidence[name]['boundsPx']=[x0,y0,x1-x0,y1-y0]
                if y0<system: raise GuiFailure('direct_header_system_overlap')
        header_bottom=rectangles['header'][1]+rectangles['header'][3]
        if rectangles['target'][1]<header_bottom:
            raise GuiFailure('direct_header_content_overlap')
        return evidence
    except GuiFailure as error:
        error.header_evidence=evidence
        raise
    except (AttributeError,KeyError,TypeError,ValueError,OverflowError):
        error=GuiFailure('direct_header_measurement_invalid')
        error.header_evidence=evidence
        raise error from None


def _terminal_geometry(browser, expected_target):
    """Read displayed geometry only; no terminal buffer or application bridge."""
    return browser.evaluate("""(() => {
      const expected = %s, compact=matchMedia('(max-width:599px)').matches,
        target = document.querySelector(compact?'#ssh-live-endpoint':'#ssh-target');
      const screen = document.querySelector('#ssh-terminal .xterm-screen');
      const visible = e => e && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
      const vv = window.visualViewport;
      if (!target || !screen) return {targetMatched:false,targetVisible:false,terminalVisible:false,
        viewport:[innerWidth,innerHeight],dpr:devicePixelRatio};
      function clipped(element,r) {
        let left=Math.max(0,r.left),top=Math.max(0,r.top);
        let right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom);
        for(let e=element.parentElement;e;e=e.parentElement) {
          const c=getComputedStyle(e),b=e.getBoundingClientRect();
          if(/hidden|clip|auto|scroll/.test(c.overflowX)) {left=Math.max(left,b.left);right=Math.min(right,b.right);}
          if(/hidden|clip|auto|scroll/.test(c.overflowY)) {top=Math.max(top,b.top);bottom=Math.min(bottom,b.bottom);}
        }
        return [left,top,right-left,bottom-top];
      }
      const t=target.getBoundingClientRect();
      const range=document.createRange();range.selectNodeContents(target);
      const textRects=[...range.getClientRects()].filter(r=>r.width>0&&r.height>0);
      const targetVisible=visible(target)&&textRects.length>0&&textRects.every(r=>{
        const [x,y,w,h]=clipped(target,r);
        if(Math.abs(x-r.left)>.25||Math.abs(y-r.top)>.25||w<r.width-.25||h<r.height-.25)return false;
        return [[x+w/2,y+h/2],[x+.5,y+.5],[x+w-.5,y+h-.5]].every(([px,py])=>{
          const hit=document.elementFromPoint(px,py);return hit===target||target.contains(hit);
        });
      });
      return {targetMatched:target.textContent.trim()===(compact?expected:expected+' · SSH 已连接'),
        targetVisible,terminalVisible:visible(screen),targetRect:[t.left,t.top,t.width,t.height],
        viewport:[innerWidth,innerHeight],dpr:devicePixelRatio,
        visualViewport:vv?[vv.offsetLeft,vv.offsetTop,vv.scale]:[0,0,1],
        terminal:clipped(screen,screen.getBoundingClientRect())};
    })()""" % json.dumps(expected_target))


def _webview_frames(hierarchy):
    start=hierarchy.index('<hierarchy')
    end=hierarchy.index('</hierarchy>',start)+len('</hierarchy>')
    root=ET.fromstring(hierarchy[start:end])
    frames=set()
    for node in root.iter('node'):
        if node.get('class')!='android.webkit.WebView' or node.get('package')!=PACKAGE:
            continue
        match=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if match: frames.add(tuple(map(int,match.groups())))
    return frames


def _read_window_hierarchy():
    """Non-PTY adb has no /dev/tty; read a unique device file and always remove it."""
    device_path=f'/data/local/tmp/pocket-ssh-hierarchy-{uuid.uuid4().hex}.xml'
    try:
        adb('shell','uiautomator','dump',device_path)
        hierarchy=adb('exec-out','cat',device_path)
        _webview_frames(hierarchy)  # Require actual XML, never the dump status line.
        return hierarchy
    except (AttributeError,TypeError,ValueError,ET.ParseError):
        raise GuiFailure('direct_terminal_hierarchy_invalid') from None
    finally:
        try: adb('shell','rm','-f',device_path)
        except GuiFailure:
            raise GuiFailure('direct_terminal_hierarchy_cleanup_failed') from None


def _geometry_diagnostic(geometry, hierarchy):
    """Allow only bounded numbers/booleans; never XML, node text or credentials."""
    result={}
    if isinstance(geometry,dict):
        for key,length in (('viewport',2),('targetRect',4),('terminal',4),('visualViewport',3)):
            value=geometry.get(key)
            if (isinstance(value,list) and len(value)==length and
                    all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=1_000_000 for v in value)):
                result[key]=value
        dpr=geometry.get('dpr')
        if type(dpr) in (int,float) and math.isfinite(dpr) and 0<dpr<=100: result['dpr']=dpr
        for key in ('targetVisible','targetMatched','terminalVisible'):
            if type(geometry.get(key)) is bool: result[key]=geometry[key]
    try:
        frames=_webview_frames(hierarchy)
        result['webViewCandidateBounds']=[list(frame) for frame in sorted(frames)[:8]
            if all(0<=value<=1_000_000 for value in frame)]
        result['webViewCandidateCount']=min(len(frames),4096)
    except (AttributeError,TypeError,ValueError,ET.ParseError):
        result['webViewHierarchyParsed']=False
    return result


def _terminal_framebuffer_bounds(geometry, hierarchy, image_size):
    """Map CSS pixels through the actual Android WebView frame, including insets."""
    if (not isinstance(geometry, dict) or geometry.get('targetMatched') is not True or
            geometry.get('targetVisible') is not True):
        raise GuiFailure('direct_terminal_target_missing')
    try:
        if geometry.get('terminalVisible') is not True: raise ValueError()
        viewport=geometry['viewport'];terminal=geometry['terminal'];visual=geometry['visualViewport']
        values=[*viewport,*terminal,geometry['dpr'],*visual]
        if (len(viewport)!=2 or len(terminal)!=4 or len(visual)!=3 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or
                any(v<=0 for v in viewport) or geometry['dpr']<=0 or visual!=[0,0,1]):
            raise ValueError()
        frames=_webview_frames(hierarchy)
        if len(frames)!=1: raise ValueError()
        left,top,right,bottom=frames.pop()
        width,height=image_size
        if not (0<=left<right<=width and 0<=top<bottom<=height): raise ValueError()
        sx=(right-left)/viewport[0];sy=(bottom-top)/viewport[1]
        if any(abs(scale/geometry['dpr']-1)>0.03 for scale in (sx,sy)): raise ValueError()
        x,y,w,h=terminal
        if x<0 or y<0 or w<=0 or h<=0 or x+w>viewport[0] or y+h>viewport[1]: raise ValueError()
        x0=math.ceil(left+x*sx);y0=math.ceil(top+y*sy)
        x1=math.floor(left+(x+w)*sx);y1=math.floor(top+(y+h)*sy)
        if x1<=x0 or y1<=y0: raise ValueError()
        return (x0,y0,x1-x0,y1-y0)
    except (AttributeError,KeyError,TypeError,ValueError,ET.ParseError):
        raise GuiFailure('direct_terminal_framebuffer_mapping_invalid') from None


def _framebuffer_png():
    """Keep the original binary ADB framebuffer; the shared adb helper decodes text."""
    try:
        result=subprocess.run(['adb','-s',SERIAL,'exec-out','screencap','-p'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
        png=result.stdout
        if (result.returncode or not png.startswith(b'\x89PNG\r\n\x1a\n') or
                not 24<=len(png)<=8_000_000 or png[12:16]!=b'IHDR'):
            raise ValueError()
        size=struct.unpack('>II',png[16:24])
        if not all(size) or size[0]*size[1]>16_000_000: raise ValueError()
        return png,size
    except (OSError,subprocess.SubprocessError,ValueError):
        raise GuiFailure('direct_terminal_framebuffer_capture_failed') from None


def _webview_png(browser):
    try:
        result=browser.call('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})
        png=base64.b64decode(result['data'],validate=True)
        if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png)>8_000_000: raise ValueError()
        return png
    except (KeyError,TypeError,ValueError):
        raise GuiFailure('direct_terminal_webview_capture_failed') from None


def _registered_terminal_bounds(geometry, reference_png, framebuffer_png, *, visible_bounds=None):
    """Prove translation with unique exact RGB patches from target and terminal.

    A keyboard may clip the XML WebView bounds while CSS keeps its full height.
    No origin is assumed: three spatially separate, nonuniform patches must each
    occur exactly once in the framebuffer and agree on the same translation.
    """
    if not isinstance(geometry,dict) or any(geometry.get(k) is not True
            for k in ('targetMatched','targetVisible','terminalVisible')):
        raise GuiFailure('direct_terminal_target_missing')
    try:
        from PIL import Image
        with Image.open(io.BytesIO(reference_png)) as source,Image.open(io.BytesIO(framebuffer_png)) as frame:
            if any(image.format!='PNG' or image.width*image.height>16_000_000 for image in (source,frame)):
                raise ValueError()
            reference=source.convert('RGB');framebuffer=frame.convert('RGB')
        if not isinstance(visible_bounds,tuple) or len(visible_bounds)!=4 or any(type(v) is not int for v in visible_bounds):
            raise ValueError()
        vl,vt,vr,vb=visible_bounds
        if not (0<=vl<vr<=framebuffer.width and 0<=vt<vb<=framebuffer.height): raise ValueError()
        vw,vh=geometry['viewport'];dpr=geometry['dpr']
        # innerWidth/innerHeight are integer CSS values. A native IME may clip
        # capture height, so use measured DPR for BOTH axes, never stretch height.
        sx=sy=dpr
        if (geometry['visualViewport']!=[0,0,1] or dpr<=0 or
                abs(reference.width-vw*dpr)>max(2,dpr) or
                not 0<reference.height<=vh*dpr+max(2,dpr)):
            raise ValueError()
        raw=framebuffer.tobytes();anchors=[];origin=None
        for region,needed in (('targetRect',1),('terminal',2)):
            x,y,w,h=geometry[region]
            if x<0 or y<0 or w<=0 or h<=0 or x+w>vw or y+h>vh: raise ValueError()
            left=math.ceil(x*sx);top=math.ceil(y*sy)
            right=min(reference.width,math.floor((x+w)*sx))
            bottom=min(reference.height,math.floor((y+h)*sy))
            if region=='targetRect' and (x+w>reference.width/sx or y+h>reference.height/sy): raise ValueError()
            if not (0<=left<right<=reference.width and 0<=top<bottom<=reference.height): raise ValueError()
            found=0;examined=0;chosen=[]
            for py in range(top,bottom-15,8):
                for px in range(left,right-31,16):
                    examined+=1
                    if examined>192: break
                    if any(abs(px-ax)<32 and abs(py-ay)<16 for ax,ay in chosen): continue
                    patch=reference.crop((px,py,px+32,py+16))
                    if len(set(patch.tobytes()[j:j+3] for j in range(0,32*16*3,3)))<12: continue
                    rows=[patch.crop((0,row,32,row+1)).tobytes() for row in range(16)]
                    row=max(range(16),key=lambda i:len(set(rows[i][j:j+3] for j in range(0,96,3))))
                    positions=set();start=0
                    for _ in range(32):
                        index=raw.find(rows[row],start)
                        if index<0: break
                        start=index+1
                        if index%3: continue
                        fy,fx=divmod(index//3,framebuffer.width);fy-=row
                        if fx+32>framebuffer.width or fy<0 or fy+16>framebuffer.height: continue
                        if framebuffer.crop((fx,fy,fx+32,fy+16)).tobytes()==patch.tobytes():
                            positions.add((fx-px,fy-py))
                    else:
                        continue  # Too many row matches cannot establish uniqueness.
                    if len(positions)!=1: continue
                    translation=positions.pop()
                    fx=px+translation[0];fy=py+translation[1]
                    if not (vl<=fx and vt<=fy and fx+32<=vr and fy+16<=vb): continue
                    if origin is not None and translation!=origin: raise ValueError()
                    origin=translation;chosen.append((px,py));found+=1
                    anchors.append({'sourceBounds':[px,py,32,16],
                        'framebufferBounds':[px+origin[0],py+origin[1],32,16],
                        'patchSha256':hashlib.sha256(patch.tobytes()).hexdigest()})
                    if found==needed: break
                if found==needed or examined>192: break
            if found!=needed: raise ValueError()
        tx,ty,tw,th=geometry['targetRect']
        if not (vl<=origin[0]+tx*sx and vt<=origin[1]+ty*sy and
                origin[0]+(tx+tw)*sx<=vr and origin[1]+(ty+th)*sy<=vb): raise ValueError()
        x,y,w,h=geometry['terminal']
        left=max(vl,math.ceil(origin[0]+x*sx));top=max(vt,math.ceil(origin[1]+y*sy))
        right=min(vr,origin[0]+reference.width,math.floor(origin[0]+(x+w)*sx))
        bottom=min(vb,origin[1]+reference.height,math.floor(origin[1]+(y+h)*sy))
        if not (0<=left<right<=framebuffer.width and 0<=top<bottom<=framebuffer.height): raise ValueError()
        return (left,top,right-left,bottom-top),{'engine':'unique exact RGB patches',
            'origin':list(origin),'webViewImageSize':list(reference.size),
            'visibleWebViewBounds':list(visible_bounds),'anchors':anchors}
    except (ImportError,KeyError,TypeError,ValueError,OSError,ZeroDivisionError):
        raise GuiFailure('direct_terminal_pixel_registration_failed') from None


def capture_terminal_proof(browser, fixture, evidence_dir, *, stem):
    """Read at most three frames after the one original hp-check, never resend input."""
    if evidence_dir is None: raise GuiFailure('direct_terminal_evidence_directory_missing')
    output=Path(evidence_dir)
    expected=f'{fixture.username}@127.0.0.1:{fixture.port}'
    base={'schemaVersion':1,'status':'failed','expectedTarget':expected,
        'expectedToken':fixture.screen_token,'expectedMarker':ECHO_MARKER,
        'captureEngine':'adb exec-out screencap -p','coordinateEngine':'measured WebView frame or exact CDP/framebuffer pixel registration'}
    last_capture={}
    for attempt in range(1,4):
        evidence={**base,**last_capture,'captureAttempts':attempt}
        try:
            before=hierarchy=None;measurement_error=None;webview_before=None;header_before=None
            try: header_before=_header_geometry(browser)
            except GuiFailure as error: measurement_error=error
            try:
                before=_terminal_geometry(browser,expected)
            except GuiFailure as error:
                measurement_error=error
            try: hierarchy=_read_window_hierarchy()
            except GuiFailure as error:
                if str(error)=='direct_terminal_hierarchy_cleanup_failed': measurement_error=error
            evidence['geometryBefore']=_geometry_diagnostic(before,hierarchy)
            try:
                webview_before=_webview_png(browser)
                (output/f'{stem}-webview-before.png').write_bytes(webview_before)
                evidence['webViewBeforeSha256']=hashlib.sha256(webview_before).hexdigest()
            except GuiFailure: pass
            png,size=_framebuffer_png()
            (output/f'{stem}.png').write_bytes(png)
            last_capture={'imageSha256':hashlib.sha256(png).hexdigest(),'imageSize':list(size),
                'image':f'{stem}.png','imageCaptureAttempt':attempt}
            evidence.update(last_capture)
            if measurement_error: raise measurement_error
            header_after=_header_geometry(browser)
            if header_before!=header_after: raise GuiFailure('direct_header_geometry_changed')
            after=_terminal_geometry(browser,expected)
            hierarchy_after=None
            try: hierarchy_after=_read_window_hierarchy()
            except GuiFailure as error:
                if str(error)=='direct_terminal_hierarchy_cleanup_failed': raise
            evidence['geometryAfter']=_geometry_diagnostic(after,hierarchy_after)
            if before!=after: raise GuiFailure('direct_terminal_geometry_changed')
            try:
                bounds=_terminal_framebuffer_bounds(before,hierarchy,size)
                bounds_after=_terminal_framebuffer_bounds(after,hierarchy_after,size)
                if bounds!=bounds_after or _webview_frames(hierarchy)!=_webview_frames(hierarchy_after):
                    raise GuiFailure('direct_terminal_geometry_changed')
                evidence['coordinateMethod']='uiautomator_full_frame'
                frame=next(iter(_webview_frames(hierarchy)))
                origin=frame[:2]
            except GuiFailure as error:
                if str(error) in ('direct_terminal_geometry_changed','direct_terminal_target_missing') or webview_before is None:
                    raise
                try:
                    frames=_webview_frames(hierarchy);frames_after=_webview_frames(hierarchy_after)
                    if len(frames)!=1 or frames!=frames_after: raise ValueError()
                    visible_frame=next(iter(frames))
                except (AttributeError,TypeError,ValueError,ET.ParseError):
                    raise GuiFailure('direct_terminal_framebuffer_mapping_invalid') from None
                webview_after=_webview_png(browser)
                (output/f'{stem}-webview-after.png').write_bytes(webview_after)
                evidence['webViewAfterSha256']=hashlib.sha256(webview_after).hexdigest()
                bounds,registration=_registered_terminal_bounds(before,webview_before,png,visible_bounds=visible_frame)
                bounds_after,registration_after=_registered_terminal_bounds(after,webview_after,png,visible_bounds=visible_frame)
                evidence.update(pixelRegistrationBefore=registration,pixelRegistrationAfter=registration_after)
                if bounds!=bounds_after or registration['origin']!=registration_after['origin']:
                    raise GuiFailure('direct_terminal_geometry_changed')
                evidence['coordinateMethod']='exact_pixel_registration'
                origin=registration['origin']
            evidence['terminalBounds']=list(bounds)
            if (header_before.get('viewport')!=before.get('viewport') or
                    header_before.get('visualViewport')!=before.get('visualViewport') or
                    header_before.get('dpr')!=before.get('dpr') or
                    header_before.get('target',{}).get('rect')!=before.get('targetRect')):
                raise GuiFailure('direct_header_measurement_invalid')
            evidence['headerGeometry']=_header_evidence(header_before,origin=origin,image_size=size)
            evidence.update(verify_terminal_screenshot(png,expected_token=fixture.screen_token,bounds=bounds))
            evidence['status']='passed';evidence.pop('errorCode',None)
            break
        except ScreenshotGateError as error:
            evidence.update(error.evidence)
            evidence['errorCode']='direct_'+str(error)
        except GuiFailure as error:
            if hasattr(error,'header_evidence'): evidence['headerGeometry']=error.header_evidence
            code=str(error)
            evidence['errorCode']=code if re.fullmatch(r'direct_[a-z0-9_]{1,80}',code) else 'direct_terminal_capture_failed'
        finally:
            (output/f'{stem}.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
        if evidence.get('errorCode')=='direct_terminal_hierarchy_cleanup_failed': break
        if attempt<3: time.sleep(0.25)
    if evidence['status']!='passed': raise GuiFailure(evidence['errorCode'])
    return evidence

IME_DOM_KEYS = frozenset(('activeTerminalLive','endpointMatched','connectedBadge','authFormHidden',
    'credentialControlsEmpty','terminalReadyOnly'))


def _ime_dom_state(browser, fixture):
    """Fixed boolean DOM predicates proving the public screen holds no credentials."""
    expected=f'{fixture.username}@127.0.0.1:{fixture.port}'
    value=browser.evaluate(r"""(()=>{
      const expected=__ARG__;
      const shown=e=>!!e&&!e.hidden&&e.getClientRects().length>0&&getComputedStyle(e).visibility==='visible';
      const live=document.getElementById('ssh-live'),setup=document.getElementById('ssh-setup');
      const auth=document.getElementById('ssh-credentials');
      const endpoint=document.getElementById('ssh-live-endpoint');
      const badge=document.querySelector('.ssh-connected-badge');
      const creds=['ssh-password','ssh-key','ssh-passphrase'].map(id=>document.getElementById(id));
      // all three credential controls must EXIST (missing DOM => fail, not pass)
      const credentialControlsEmpty=creds.every(e=>e!==null&&!shown(e)&&e.value==='');
      const rows=[...document.querySelectorAll('#ssh-terminal .xterm-rows > div')]
        .map(row=>row.textContent.replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim()).filter(Boolean);
      // Fixture sends exactly READY + CRLF + '$ ' prompt; allow the bare prompt
      // line and nothing else beyond the READY marker itself.
      const terminalReadyOnly=rows.includes('POCKET-ANDROID-READY')&&rows.every(r=>r==='POCKET-ANDROID-READY'||r==='$');
      return {activeTerminalLive:shown(live)&&!shown(setup),
        endpointMatched:endpoint&&endpoint.textContent.trim()===expected,
        connectedBadge:badge&&badge.textContent.trim()==='已连接',
        authFormHidden:auth!==null&&!shown(auth),
        credentialControlsEmpty,
        terminalReadyOnly};
    })()""".replace('__ARG__', json.dumps(expected)))
    if not isinstance(value,dict) or set(value)!=IME_DOM_KEYS or not all(type(v) is bool for v in value.values()):
        return {key:False for key in IME_DOM_KEYS}
    return value

def public_editor_focus(browser):
    """Fixed booleans: the terminal textarea exists, is the active element,
    the document holds focus, and the page's own IME-known/visible classes.
    Unreadable facts stay null (distinct from False)."""
    try:
        value=browser.evaluate(r"""(()=>{
          const editor=document.querySelector('#ssh-terminal .xterm-helper-textarea');
          return {editorPresent:!!editor,
            editorActive:editor===document.activeElement,
            documentFocused:document.hasFocus(),
            imeKnown:document.body.classList.contains('ssh-ime-known'),
            imeVisible:document.body.classList.contains('ssh-ime-visible')};
        })()""")
    except Exception:
        return {key:None for key in ('editorPresent','editorActive','documentFocused','imeKnown','imeVisible')}
    keys=('editorPresent','editorActive','documentFocused','imeKnown','imeVisible')
    if not isinstance(value,dict) or any(type(value.get(key)) is not bool for key in keys):
        return {key:None for key in keys}
    return {key:value[key] for key in keys}


def _foreground_owned():
    """True only when our package holds the current window focus."""
    text=adb('shell','dumpsys','window','displays',check=False)
    for line in text.splitlines():
        if 'mCurrentFocus' in line:
            # exact package token, not substring of some other component
            return re.search(r'mCurrentFocus=.*[ /=]'+re.escape(PACKAGE)+r'($|/|\s)', line) is not None
    return False


def _ocr_public_marker(png, bounds):
    """True only when OCR of the bounded terminal region shows the READY marker.

    Mirrors terminal_screenshot_gate preprocessing; the transcript itself stays
    local — only the boolean and engine label are ever published."""
    executable = shutil.which('tesseract')
    if executable is None:
        raise GuiFailure('direct_ime_proof_ocr_missing')
    try:
        from PIL import Image, ImageChops, ImageOps, ImageStat
    except ImportError:
        raise GuiFailure('direct_ime_proof_ocr_missing') from None
    x, y, width, height = bounds
    try:
        with Image.open(io.BytesIO(png)) as source:
            if source.format != 'PNG': raise ValueError()
            source.load()
            image = source.convert('RGB')
    except (OSError, ValueError):
        raise GuiFailure('direct_ime_proof_ocr_failed') from None
    if x < 0 or y < 0 or width < 1 or height < 1 or x + width > image.width or y + height > image.height:
        raise GuiFailure('direct_ime_proof_ocr_failed')
    crop = image.crop((x, y, x + width, y + height))
    red, green, blue = crop.split()
    gray = ImageOps.autocontrast(ImageChops.lighter(ImageChops.lighter(red, green), blue))
    if ImageStat.Stat(gray).mean[0] < 127:
        gray = ImageOps.invert(gray)
    gray = ImageOps.expand(gray.resize((width * 2, height * 2)), border=20, fill=255)
    encoded = io.BytesIO()
    gray.save(encoded, format='PNG')
    engine = None
    ocr_env = dict(os.environ, OMP_THREAD_LIMIT='1')
    try:
        version = subprocess.run([executable, '--version'], capture_output=True, timeout=10, check=True, env=ocr_env)
        match = re.match(rb'tesseract ([0-9.]+)', version.stdout)
        if match is None: raise ValueError()
        engine = 'tesseract ' + match[1].decode('ascii')
        visible = False
        for psm in (6, 11):
            result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', str(psm),
                                     '-c', 'load_system_dawg=0', '-c', 'load_freq_dawg=0'],
                                    input=encoded.getvalue(), capture_output=True, timeout=30, check=True, env=ocr_env)
            text = result.stdout.decode('utf-8', errors='strict')
            if any(line.strip().replace(' ', '') == 'POCKET-ANDROID-READY' for line in text.splitlines()):
                visible = True
                break
        return visible, engine
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        raise GuiFailure('direct_ime_proof_ocr_failed') from None




def _atomic_publish(output, png, evidence):
    """Write PNG+JSON via temp names, then os.replace; abort leaves nothing public."""
    image_name = 'ime-keyboard-opened-native.png'
    json_name = 'ime-keyboard-opened-native.json'
    tmp_image = output / (image_name + '.tmp')
    tmp_json = output / (json_name + '.tmp')
    published = []
    try:
        tmp_image.write_bytes(png)
        tmp_json.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp_image, output / image_name)
        published.append(output / image_name)
        os.replace(tmp_json, output / json_name)
    except Exception:
        for path in [tmp_image, tmp_json, *published]:
            try: path.unlink()
            except OSError: pass
        raise GuiFailure('direct_ime_proof_publish_failed') from None


def capture_native_ime_keyboard_proof(browser, fixture):
    """Capture the public IME evidence right after the real keyboard touch.

    Fail closed: every gate (owned foreground, DOM public state, peer 0-input,
    OCR READY marker) must hold on BOTH sides of the in-memory framebuffer
    capture, or nothing is published and the product assertion fails on its
    own. Never sends input; fixture.password is deliberately not consulted."""
    if getattr(browser, '_ime_keyboard_proof_captured', False): return
    browser._ime_keyboard_proof_captured = True
    output = getattr(browser, 'evidence_dir', None)
    if output is None: return
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def fail(code):
        (output / 'ime-keyboard-opened-native.json').write_text(
            json.dumps({'schemaVersion': 2, 'status': 'failed', 'errorCode': code}, indent=2) + '\n',
            encoding='utf-8')
    if not getattr(browser, '_temporary_install_confirmed', False):
        return fail('direct_ime_proof_install_unconfirmed')
    expected = f'{fixture.username}@127.0.0.1:{fixture.port}'
    try:
        dom = _ime_dom_state(browser, fixture)
        if not all(dom.values()): return fail('direct_ime_proof_page_state_invalid')
        active_peer(fixture, input_bytes=0)
        foreground_before = _foreground_owned()
        if not foreground_before: return fail('direct_ime_proof_foreground_lost')
        png, size = _framebuffer_png()
        geometry = _terminal_geometry(browser, expected)
        hierarchy = _read_window_hierarchy()
        bounds = _terminal_framebuffer_bounds(geometry, hierarchy, size)
        marker_visible, ocr_engine = _ocr_public_marker(png, bounds)
        if not marker_visible: return fail('direct_ime_proof_marker_not_visible')
        dom_after = _ime_dom_state(browser, fixture)
        if not all(dom_after.values()): return fail('direct_ime_proof_page_state_invalid')
        active_peer(fixture, input_bytes=0)
        if not _foreground_owned(): return fail('direct_ime_proof_foreground_lost')
        if _webview_frames(hierarchy) != _webview_frames(_read_window_hierarchy()):
            return fail('direct_ime_proof_foreground_lost')
        evidence = {'schemaVersion': 2, 'status': 'passed',
            'captureEngine': 'adb exec-out screencap -p',
            'image': 'ime-keyboard-opened-native.png',
            'imageSha256': hashlib.sha256(png).hexdigest(), 'imageSize': list(size),
            'terminalBounds': list(bounds), 'ocrEngine': ocr_engine,
            'markerVisible': True, 'domGates': dom, 'foregroundHeld': True,
            'installTemporary': True, 'inputSent': False, 'credentialsOnScreen': False,
            'fixedGeometry': active_diagnostic(browser, fixture)}
        _atomic_publish(output, png, evidence)
        return
    except GuiFailure as error:
        code = str(error)
        fail(code if re.fullmatch(r'direct_[a-z0-9_]{1,80}', code) else 'direct_ime_proof_capture_failed')
    except Exception:
        fail('direct_ime_proof_capture_failed')


def staged_setup(browser):
    # The mobile route and the desktop checkbox are mutually exclusive UI witnesses.
    expression = """(function sshSetupLayout(){
      const one=id=>{const a=document.querySelectorAll('#'+id);return a.length===1?a[0]:null;};
      const shown=e=>!!e&&!e.hidden&&e.getClientRects().length>0&&getComputedStyle(e).visibility==='visible';
      const route=one('home-ssh'), title=one('ssh-step-title'), review=one('ssh-review');
      if (!shown(route)) return null;
      if (matchMedia('(max-width:599px)').matches) return route.dataset.sshStep==='target'&&shown(title)&&
        title.innerText.trim()==='普通 SSH'&&!shown(review)?'staged':null;
      return !route.hasAttribute('data-ssh-step')&&!shown(title)&&shown(review)&&review.type==='checkbox'?'legacy':null;
    })()"""
    layout = wait_for(lambda: browser.evaluate(expression), 'direct_setup_layout_unproven')
    if layout not in ('staged', 'legacy'):
        raise GuiFailure('direct_setup_layout_unproven')
    return layout == 'staged'


def mobile_setup(browser, fixture, step, *, fingerprint=None, prior=None, method='password', input_state='empty'):
    key = (fixture.rotated_public_key if fingerprint is not None and
           fingerprint == getattr(fixture, 'rotated_fingerprint', None) else fixture.public_key)
    expectation = {'step': step, 'target': f'{fixture.username}@127.0.0.1:{fixture.port}',
                   'algorithm': key.split()[0], 'fingerprint': fingerprint,
                   'prior': prior, 'priorAlgorithm': fixture.public_key.split()[0], 'method': method, 'input': input_state}
    expression = r"""(function sshMobileSetup(){
      const spec=%s,one=id=>{const a=document.querySelectorAll('#'+id);return a.length===1?a[0]:null;};
      const shown=e=>!!e&&!e.hidden&&e.getClientRects().length>0&&getComputedStyle(e).visibility==='visible';
      const text=id=>{const e=one(id);return shown(e)?e.innerText.trim():null;};
      const button=(id,label,on=true)=>{const e=one(id);return shown(e)&&e.tagName==='BUTTON'&&
        text(id)===label&&e.disabled===!on;};
      const route=one('home-ssh'), target=one('ssh-target-fields'), trust=one('ssh-trust-review'), auth=one('ssh-credentials');
      const password=one('ssh-password'), key=one('ssh-key'), phrase=one('ssh-passphrase'), submit=one('ssh-connect');
      const secrets=[password,key,phrase];
      if (!shown(route) || !target || !trust || !auth || !submit || secrets.some(e=>!e) ||
          password.type!=='password' || key.tagName!=='TEXTAREA' || phrase.type!=='password') return false;
      const closedSecrets=()=>secrets.every(e=>!shown(e)&&e.disabled&&e.value==='')&&!shown(submit)&&submit.disabled;
      if (spec.step==='refused') return !shown(one('ssh-setup'))&&shown(one('ssh-key-change'))&&closedSecrets()&&
        text('ssh-key-change-endpoint')===spec.target&&text('ssh-key-change-algorithms')==='旧密钥算法 · '+spec.priorAlgorithm&&
        text('ssh-key-change-old')?.replace(/\s/g,'')==='旧：'+spec.prior&&
        text('ssh-key-change-new')?.replace(/\s/g,'')==='新：'+spec.fingerprint;
      if (route.dataset.sshStep!==(spec.step==='closed'?'target':spec.step) || shown(one('ssh-review'))) return false;
      if (spec.step==='target'||spec.step==='closed') return shown(target)&&!shown(trust)&&!shown(auth)&&closedSecrets()&&
        text('ssh-step-title')==='普通 SSH'&&shown(one('ssh-step-back'))&&
        button('ssh-probe','探测并核对主机密钥')&&
        (spec.step!=='closed'||(text('ssh-closed-feedback')?.replace(/\s/g,'')===
          '已断开连接本次凭据已清空。重新连接时请重新填写。'&&button('ssh-return-home','返回首页')))&&
        (spec.prior===null || text('ssh-prior-fingerprint')?.replace(/\s/g,'')==='保留的旧指纹：'+spec.prior);
      if (text('ssh-reviewed-endpoint')!==spec.target || shown(target)) return false;
      if (spec.step==='trust') return shown(trust)&&!shown(auth)&&closedSecrets()&&
        text('ssh-step-title')==='核对主机密钥'&&text('ssh-reviewed-algorithm')===spec.algorithm&&
        text('ssh-reviewed-fingerprint')?.replace(/\s/g,'')===spec.fingerprint&&
        button('ssh-trust-confirm','指纹一致，确认继续')&&
        button('ssh-trust-cancel',spec.prior===null?'取消核对':'取消核对，保留旧信任');
      if (!shown(auth) || shown(trust) || text('ssh-step-title')!=='SSH 账号认证' ||
          text('ssh-approved-note')!=='本次主机密钥已确认' || !button('ssh-auth-password','密码') ||
          !button('ssh-auth-key','已有私钥') || !button('ssh-connect','连接 SSH',spec.input==='ready')) return false;
      const active=spec.method==='password'?password:key, selected=spec.method==='password'?'ssh-auth-password':'ssh-auth-key';
      const inactive=spec.method==='password'?'ssh-auth-key':'ssh-auth-password';
      if (one(selected).getAttribute('aria-pressed')!=='true'||one(inactive).getAttribute('aria-pressed')!=='false' ||
          !shown(active)||active.disabled||Boolean(active.value)!==(spec.input!=='empty')) return false;
      return spec.method==='password'
        ? !shown(key)&&!shown(phrase)&&key.value===''&&phrase.value===''
        : !shown(password)&&password.value===''&&shown(phrase)&&!phrase.disabled&&Boolean(phrase.value)===(spec.input==='ready');
    })()""" % json.dumps(expectation)
    wait_for(lambda: browser.evaluate(expression) is True, 'direct_mobile_setup_unproven', timeout=60)


def require_first_probe(fixture):
    if not fixture.wait_for_connections_closed(1, timeout=30):
        raise GuiFailure('direct_probe_peer_unproven')
    snapshot = fixture.snapshot()
    events = snapshot.get('connectionEvents', [])
    if (snapshot.get('connections') != 1 or len(events) != 1 or events[0].get('closed') is not True
            or events[0].get('hostKey') != 'A' or any(events[0].get(key) != 0 for key in
                ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes'))):
        raise GuiFailure('direct_probe_peer_unproven')


def active_peer(fixture, input_bytes=0):
    """Require the original probe and one live authenticated shell with exact input."""
    peer=fixture.snapshot()
    events=peer.get('connectionEvents')
    if (peer.get('connections') != 2 or not isinstance(events,list) or len(events) != 2
            or events[0].get('hostKey') != 'A' or events[0].get('closed') is not True
            or events[1].get('hostKey') != 'A' or events[1].get('closed') is not False
            or peer.get('sessionClosed') is not False or events[1].get('authAccepted') is not True
            or events[1].get('authAttempts') != 1 or events[1].get('authSuccesses') != 1
            or events[1].get('ptyRequests') != 1 or events[1].get('shellRequests') != 1
            or events[1].get('inputBytes') != input_bytes):
        raise GuiFailure('direct_active_peer_changed')


ACTIVE_FACTS = frozenset(('route','live','title','badge','target','control','disconnect',
                          'keyboardState','sectionContent','navSelected'))


def active_diagnostic(browser, fixture):
    """Bounded geometry and peer counters only; never collect text or identifiers."""
    result={}
    try:
        value=browser.evaluate(r"""(()=>{
          const rect=id=>{const e=id==='ssh-connected-badge'?document.querySelector('.ssh-connected-badge'):document.getElementById(id);const r=e?.getBoundingClientRect();
            return r?[r.x,r.y,r.width,r.height].map(Math.round):null;};
          const v=visualViewport;return {viewport:[innerWidth,innerHeight,v?.offsetTop,v?.height].map(Math.round),
            title:rect('ssh-active-title'),badge:rect('ssh-connected-badge'),focus:rect('ssh-focus'),
            hide:rect('ssh-hide-keyboard'),disconnect:rect('ssh-disconnect')};
        })()""")
        keys=('viewport','title','badge','focus','hide','disconnect')
        if (isinstance(value,dict) and set(value)==set(keys) and
            all((key!='viewport' and item is None) or
                (isinstance(item,list) and len(item)==4 and all(type(x) is int and -100000<=x<=100000 for x in item))
                for key,item in value.items())):
            result['geometry']=value
    except (GuiFailure,ValueError,TypeError): pass
    try:
        peer=fixture.snapshot();events=peer.get('connectionEvents'); keys=('authAttempts','authSuccesses','ptyRequests','shellRequests','inputBytes')
        if (type(peer.get('connections')) is int and 0<=peer['connections']<=100 and
                isinstance(events,list) and len(events)==2 and isinstance(events[1],dict) and
                all(type(events[1].get(k)) is int and 0<=events[1][k]<=100000 for k in keys) and
                type(events[1].get('closed')) is bool):
            result['peer']={'connections':peer['connections'],**{k:events[1][k] for k in keys},'closed':events[1]['closed']}
    except (AttributeError,KeyError,TypeError,ValueError): pass
    return result


def active_view(browser, fixture, section, keyboard=False):
    """Check the actual route, endpoint and controls; expose only fixed booleans."""
    expected=f'{fixture.username}@127.0.0.1:{fixture.port}'
    expression=r"""(function ordinaryActive(){
      const spec=%s,one=id=>document.getElementById(id);
      const shown=e=>!!e&&!e.hidden&&e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
      const tabs=document.querySelector('.route-tabs');
      const bottomInset=parseFloat(getComputedStyle(tabs).paddingBottom);
      const hit=e=>{if(!shown(e)||e.disabled)return false;const r=e.getBoundingClientRect(),v=visualViewport;
        if(!v||!Number.isFinite(bottomInset)||bottomInset<0||r.width<=0||r.height<=0||r.left<0||r.top<v.offsetTop||r.right>innerWidth||r.bottom>v.offsetTop+v.height-bottomInset)return false;
        const h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return h===e||e.contains(h);};
      const route=one('home-'+spec.section),live=one('ssh-live'),target=one('ssh-live-endpoint');
      const ssh=spec.section==='ssh',title=one('ssh-active-title'),badge=document.querySelector('.ssh-connected-badge');
      const control=one(spec.keyboard?'ssh-hide-keyboard':'ssh-focus');
      const focused=document.activeElement===document.querySelector('#ssh-terminal .xterm-helper-textarea');
      const panel=one('network-panel'),heading=panel?.querySelector(':scope > h2');
      const networkButton=[...(panel?.querySelectorAll(':scope > button')||[])].find(e=>e.textContent.trim()==='新增网络配置');
      const sectionContent=ssh || (spec.section==='dashboard'?shown(one('home-dashboard')):
        spec.section==='network'?shown(panel)&&shown(heading)&&heading.textContent.trim()==='网络配置'&&shown(networkButton):
        spec.section==='settings'?shown(one('ssh-settings-active'))&&one('ssh-settings-active').textContent.trim()==='普通 SSH 会话保持连接'&&
          shown(one('ssh-settings-endpoint'))&&one('ssh-settings-endpoint').textContent.trim()===spec.target:false);
      return {route:shown(route),live:!!live&&!live.hidden,
        title:!ssh||shown(title)&&title.textContent.trim()==='普通 SSH',
        badge:!ssh||hit(badge)&&badge.textContent.trim()==='已连接',
        target:!ssh||shown(target)&&target.textContent.trim()===spec.target,
        control:!ssh||hit(control),disconnect:!ssh||hit(one('ssh-disconnect')),
        keyboardState:!ssh||(spec.keyboard?focused&&!shown(tabs):!focused),
        sectionContent,navSelected:ssh||one('nav-'+spec.section)?.getAttribute('aria-pressed')==='true'||
          spec.section==='dashboard'&&one('show-remote').getAttribute('aria-pressed')==='true'};
    })()""" % json.dumps({'section':section,'target':expected,'keyboard':keyboard})
    last={}
    def inspect():
        value=browser.evaluate(expression)
        if isinstance(value,dict) and set(value)==ACTIVE_FACTS and all(type(v) is bool for v in value.values()):
            last.update(value)
            return all(value.values())
        return False
    try:
        wait_for(inspect,'direct_active_ui_invalid',timeout=60)
    except GuiFailure as error:
        error.active_diagnostic=dict(last)
        raise


def native_active_tap(browser, selector):
    """Tap only the observed active SSH controls through Android's input dispatcher."""
    if selector not in ('#ssh-focus','#ssh-hide-keyboard'):
        raise GuiFailure('direct_active_tap_unproven')
    expression=r"""(()=>{const e=document.querySelector(%s),r=e?.getBoundingClientRect(),v=visualViewport;
      if(!e||e.disabled||!e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})||!r||!v)return null;
      const x=r.left+r.width/2,y=r.top+r.height/2,h=document.elementFromPoint(x,y);
      return {point:[x,y],rect:[r.left,r.top,r.width,r.height],viewport:[innerWidth,innerHeight],
        visual:[v.offsetLeft,v.offsetTop,v.scale],dpr:devicePixelRatio,hit:h===e||e.contains(h)};})()""" % json.dumps(selector)
    try:
        before=browser.evaluate(expression);frames=_webview_frames(_read_window_hierarchy())
        header=_header_geometry(browser);_,image_size=_framebuffer_png()
        after=browser.evaluate(expression);frames_after=_webview_frames(_read_window_hierarchy())
        if before!=after or not isinstance(before,dict) or before.get('hit') is not True or len(frames)!=1 or frames!=frames_after: raise ValueError()
        point=before['point'];rect=before['rect'];viewport=before['viewport'];visual=before['visual'];dpr=before['dpr']
        vals=[*point,*rect,*viewport,*visual,dpr]
        if (len(point)!=2 or len(rect)!=4 or len(viewport)!=2 or visual!=[0,0,1] or
            any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in vals) or
            dpr<=0 or any(v<=0 for v in viewport) or rect[2]<=0 or rect[3]<=0 or not (0<=point[0]<viewport[0] and 0<=point[1]<viewport[1])): raise ValueError()
        left,top,right,bottom=next(iter(frames));iw,ih=image_size
        if not (0<=left<right<=iw and 0<=top<bottom<=ih and
                abs((right-left)/viewport[0]/dpr-1)<=0.03 and header['native']['viewY']==top): raise ValueError()
        x=round(left+point[0]*dpr);y=round(top+point[1]*dpr)
        if not (left<=x<right and top<=y<bottom): raise ValueError()
    except (AttributeError,KeyError,TypeError,ValueError,OverflowError,ET.ParseError):
        raise GuiFailure('direct_active_tap_unproven') from None
    adb('shell','input','tap',str(x),str(y))


def exercise_active_navigation(browser, fixture, *, progress=None, ime_checks=None):
    """Native IME observations plus bounded peer facts across actual route clicks."""
    def observe(stage,section,keyboard=False):
        if progress is not None: progress['stage']=stage
        try:
            active_view(browser,fixture,section,keyboard=keyboard)
            active_peer(fixture)
        except GuiFailure as error:
            error.active_context=active_diagnostic(browser,fixture)
            raise
    def ime(visible):
        sample=system_keyboard(visible)
        if ime_checks is not None:
            ime_checks.append(public_ime_diagnostic(sample.get('diagnostic')))
        return sample
    observe('active_initial','ssh')
    try:
        ime(False)
    except GuiFailure as error:
        if str(error)!='android_system_ime_hide_unconfirmed': raise
        ime(True)  # Only a confirmed owned keyboard makes Back an IME dismissal.
        adb('shell','input','keyevent','KEYCODE_BACK')
        ime(False)
    if progress is not None: progress['stage']='active_keyboard_opened'
    native_active_tap(browser,'#ssh-focus')
    ime(True)
    capture_native_ime_keyboard_proof(browser, fixture)
    observe('active_keyboard_opened','ssh',True)
    ime(True)
    if progress is not None: progress['stage']='active_keyboard_closed'
    native_active_tap(browser,'#ssh-hide-keyboard')
    ime(False)
    observe('active_keyboard_closed','ssh')
    ime(False)
    for section,selector,label in (('dashboard','#show-remote','board'),('network','#nav-network','network'),('settings','#nav-settings','settings')):
        if progress is not None: progress['stage']='active_'+label
        browser.click(selector)
        observe('active_'+label,section)
        if progress is not None: progress['stage']='active_terminal_from_'+label
        browser.click('#nav-terminal')
        observe('active_terminal_from_'+label,'ssh')
    return {'keyboardOpened':True,'keyboardClosed':True,'board':True,'terminalFromBoard':True,
            'network':True,'terminalFromNetwork':True,'settings':True,'terminalFromSettings':True,
            'singleAuthenticatedShellWithoutInput':True}


def exercise_ui(browser, fixture, *, encrypted_key=False, evidence_dir=None, progress=None):
    """Use actual CDP click/keyboard events and independently check the peer."""
    browser.evidence_dir = evidence_dir
    if progress is not None: progress['stage']='open_remote'
    entry = dashboard_add_selector(browser)
    browser.click(entry)
    if progress is not None: progress['stage']='open_ssh_form'
    browser.click('#add-ssh')
    staged = staged_setup(browser)
    if staged:
        mobile_setup(browser, fixture, 'target')
    if progress is not None: progress['stage']='enter_host'
    browser.fill('#ssh-host', '127.0.0.1')
    if progress is not None: progress['stage']='enter_port'
    browser.fill('#ssh-port', str(fixture.port))
    if progress is not None: progress['stage']='enter_user'
    browser.fill('#ssh-user', fixture.username)
    if progress is not None: progress['stage']='probe_host'
    browser.click('#ssh-probe')
    if progress is not None: progress['stage']='await_fingerprint'
    if staged:
        mobile_setup(browser, fixture, 'trust', fingerprint=fixture.fingerprint)
        require_first_probe(fixture)
    else:
        wait_for(lambda: fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''),
                 'direct_fingerprint_missing', timeout=60)
    if progress is not None: progress['stage']='review_fingerprint'
    browser.click('#ssh-trust-confirm' if staged else '#ssh-review')
    if staged:
        mobile_setup(browser, fixture, 'auth')
    if encrypted_key:
        if progress is not None: progress['stage']='select_key_auth'
        if staged:
            browser.click('#ssh-auth-key')
            mobile_setup(browser, fixture, 'auth', method='key')
        else:
            browser.select_option('#ssh-auth-method', 'key')
        if progress is not None: progress['stage']='enter_private_key'
        browser.fill('#ssh-key', fixture.private_key)
        if staged:
            mobile_setup(browser, fixture, 'auth', method='key', input_state='pem')
        if progress is not None: progress['stage']='enter_passphrase'
        browser.fill('#ssh-passphrase', fixture.passphrase)
    else:
        if progress is not None: progress['stage']='enter_password'
        browser.fill('#ssh-password', fixture.password)
    if staged:
        mobile_setup(browser, fixture, 'auth', method='key' if encrypted_key else 'password', input_state='ready')
        require_first_probe(fixture)
    elif browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_credential_invalidated_host_review')
    if progress is not None: progress['stage']='connect'
    browser.click('#ssh-connect' if staged else '#ssh-form button[type=submit]')
    wait_for(lambda: browser.evaluate("!document.querySelector('#ssh-live').hidden") and
             '已连接' in (browser.read('#ssh-status') or ''), 'direct_ready_missing', timeout=60)
    if browser.evaluate("!!document.querySelector('#ssh-password').value || !!document.querySelector('#ssh-key').value || !!document.querySelector('#ssh-passphrase').value"):
        raise GuiFailure('direct_credentials_retained')
    active_navigation = None
    ime_checks=[]
    if staged and not encrypted_key:
        try:
            active_navigation = exercise_active_navigation(browser,fixture,progress=progress,ime_checks=ime_checks)
        except GuiFailure as error:
            if not hasattr(error,'active_context'): error.active_context=active_diagnostic(browser,fixture)
            error.ime_checks=ime_checks
            error.ime_failure=public_ime_diagnostic(getattr(error,'system_ime_diagnostic',None))
            raise
    if progress is not None: progress['stage']='terminal_input'
    second_open=[]
    if active_navigation:
        # Before/after facts around the second explicit open: fixed IME enums,
        # bounded geometry, zero-input peer; retained on any later failure.
        second_open.append(second_open_checkpoint(browser,fixture,progress))
        try:
            native_active_tap(browser,'#ssh-focus')
            system_keyboard(True)
            active_view(browser,fixture,'ssh',keyboard=True)
            active_peer(fixture)
        except GuiFailure as error:
            if not hasattr(error,'second_open_checkpoint'):
                error.second_open_checkpoint=second_open+[second_open_checkpoint(browser,fixture,progress)]
            raise
        second_open.append(second_open_checkpoint(browser,fixture,progress))
    else:
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
    if active_navigation:
        active_peer(fixture,input_bytes=9)
    terminal_proof=(capture_terminal_proof(browser,fixture,evidence_dir,stem='ssh-terminal-android')
                    if getattr(fixture,'screen_token',None) and not encrypted_key else None)
    if not encrypted_key:
        for key in ('esc', 'tab', 'left', 'ctrl-c'):
            browser.click(f'#ssh-helper-keys button[data-ssh-key="{key}"]')
        wait_for(lambda: fixture.snapshot().get('helperKeysExact') is True,
                 'direct_helper_keys_mismatch', timeout=30)
    if fixture.snapshot().get('sessionClosed') is not False:
        raise GuiFailure('direct_session_ended_before_disconnect')
    if progress is not None: progress['stage']='disconnect'
    browser.click('#ssh-disconnect')
    if staged:
        mobile_setup(browser, fixture, 'closed')
    else:
        wait_for(lambda: not browser.evaluate("document.querySelector('#ssh-setup').hidden") and
                 '已断开' in (browser.read('#ssh-status') or ''), 'direct_disconnect_ui_missing', timeout=60)
    wait_for(lambda: fixture.snapshot().get('sessionClosed') is True,
             'direct_peer_close_missing', timeout=60)
    peer = fixture.snapshot()
    if (not encrypted_key and peer.get('helperKeysExact') is not True) or any(peer.get(k) is not True for k in ('authAccepted','ptyRequested','shellRequested','markerReceived','sessionClosed')):
        raise GuiFailure('direct_peer_evidence_incomplete')
    if progress is not None: progress['stage']='return_home'
    wait_for(lambda: fixture.snapshot().get('connectionsClosed') is True,
             'direct_peer_close_missing', timeout=60)
    closed = fixture.snapshot()['connectionEvents']
    browser.click('#ssh-return-home' if staged else '#show-remote')
    if dashboard_add_selector(browser, failure='direct_return_home_missing') != entry:
        raise GuiFailure('direct_return_home_missing')
    if staged:
        wait_for(lambda: browser.evaluate("""(()=>{const m=document.querySelectorAll('#host-ssh-disconnected'),e=m[0];
          return m.length===1&&!e.hidden&&e.getClientRects().length>0&&e.innerText.trim()==='普通 SSH 已断开';})()""") is True,
                 'direct_return_home_missing')
    after_return = fixture.snapshot()
    if after_return.get('connectionsClosed') is not True or after_return.get('connectionEvents') != closed:
        raise GuiFailure('direct_return_home_peer_changed')
    if staged and (after_return.get('connections') != 2 or len(closed) != 2 or
                   any(event['hostKey'] != 'A' for event in closed) or not closed[1]['authAccepted']):
        raise GuiFailure('direct_peer_evidence_incomplete')
    return {'fingerprintReviewed':True,'credentialReviewPreserved':True,'connected':True,
            'terminalInputReceived':True,'terminalEchoRendered':True,'disconnected':True,
            'passwordCleared':True, 'returnedHome':True, **({'helperKeysExact':True} if not encrypted_key else {}),
            **({'ordinaryActive':active_navigation,'activeImeChecks':ime_checks} if active_navigation else {}),
            **({'secondOpenFacts':second_open} if second_open else {}),
            **({'terminalScreenshot':terminal_proof} if terminal_proof else {}),
            'peer':{k:True for k in ('authAccepted','ptyRequested','shellRequested','markerReceived','sessionClosed')}}

def second_open_checkpoint(browser, fixture, progress=None):
    """Bounded second-open facts only: IME enums, editor focus booleans,
    geometry, and bounded same-connection peer counts.

    Read-only; no raw DOM text, credentials, screenshots, taps or focus changes.
    Every fact is a fixed boolean/enum; an unreadable fact stays null so miss,
    foreign focus and transition states stay distinguishable. When a writable
    progress dict is supplied, a copy is stored immediately so later failures
    (editor focus waits, echo waits) cannot lose this checkpoint.
    """
    checkpoint={'peerCounts':None,'peerClosed':None}
    try:
        raw=parse_system_ime(adb('shell','dumpsys','input_method'), adb('shell','dumpsys','window','displays'), PACKAGE)
        checkpoint['ime']=public_ime_diagnostic(raw.get('diagnostic'))
    except SystemImeFailure as error:
        # keep the whitelisted enums the classifier already produced
        checkpoint['ime']=error.public_diagnostic()
    except (DeviceFailure,GuiFailure):
        checkpoint['ime']={}
    checkpoint['editorFocus']=public_editor_focus(browser)
    diagnostic=active_diagnostic(browser,fixture)
    checkpoint['geometry']=diagnostic.get('geometry') if isinstance(diagnostic,dict) else None
    # bounded peer facts already validated by active_diagnostic (int ranges,
    # exact connection count); never call fixture.snapshot() unbounded here.
    bounded=diagnostic.get('peer') if isinstance(diagnostic,dict) else None
    if isinstance(bounded,dict):
        checkpoint['peerCounts']={key:bounded[key] for key in
            ('authAttempts','authSuccesses','ptyRequests','shellRequests','inputBytes')
            if type(bounded.get(key)) is int}
        checkpoint['peerClosed']=bounded.get('closed') is True
    try:
        active_peer(fixture, input_bytes=0)
        checkpoint['peerUnchanged']=True
    except (GuiFailure,AttributeError):
        checkpoint['peerUnchanged']=False
    if isinstance(progress,dict):
        stored=progress.setdefault('secondOpenFacts',[])
        if isinstance(stored,list): stored.append(dict(checkpoint))
    return checkpoint


def exercise_key_change_ui(browser, fixture, *, evidence_dir=None):
    """Same host:port A→B: refuse, review with no exits, cancel, re-probe, approve."""
    browser.click(dashboard_add_selector(browser))
    browser.click('#add-ssh')
    staged = staged_setup(browser)
    if staged:
        mobile_setup(browser, fixture, 'target')
    browser.fill('#ssh-host', '127.0.0.1')
    browser.fill('#ssh-port', str(fixture.port))
    browser.fill('#ssh-user', fixture.username)
    browser.click('#ssh-probe')
    if staged:
        mobile_setup(browser, fixture, 'trust', fingerprint=fixture.fingerprint)
        require_first_probe(fixture)
    else:
        wait_for(lambda: fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''),
                 'direct_rotation_probe_missing', timeout=60)
    browser.click('#ssh-trust-confirm' if staged else '#ssh-review')
    if staged:
        mobile_setup(browser, fixture, 'auth')
    browser.fill('#ssh-password', fixture.password)
    if staged:
        mobile_setup(browser, fixture, 'auth', input_state='ready')
        require_first_probe(fixture)
    elif browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_rotation_review_invalidated')
    browser.click('#ssh-connect' if staged else '#ssh-form button[type=submit]')
    wait_for(lambda: browser.evaluate("!document.querySelector('#ssh-key-change').hidden"),
             'direct_rotation_review_missing', timeout=60)
    if staged:
        mobile_setup(browser, fixture, 'refused', fingerprint=fixture.rotated_fingerprint, prior=fixture.fingerprint)
    else:
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
    if staged:
        mobile_setup(browser, fixture, 'target', prior=fixture.fingerprint)
    else:
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
    if staged:
        mobile_setup(browser, fixture, 'trust', fingerprint=fixture.rotated_fingerprint, prior=fixture.fingerprint)
    else:
        wait_for(lambda: fixture.rotated_fingerprint in (browser.read('#ssh-fingerprint') or ''),
                 'direct_rotation_reprobe_missing', timeout=60)
        if fixture.fingerprint in (browser.read('#ssh-fingerprint') or ''):
            raise GuiFailure('direct_rotation_reprobe_old_key_stale')
        if browser.evaluate("document.querySelector('#ssh-review').checked") is not False:
            raise GuiFailure('direct_rotation_reprobe_review_stale')
        if browser.evaluate("!!document.querySelector('#ssh-password').value"):
            raise GuiFailure('direct_rotation_reprobe_credentials_stale')
    fixture.wait_for_connections_closed(minimum=3, timeout=30)
    evidence_3 = _rotation_stage(fixture, 3)
    browser.click('#ssh-trust-confirm' if staged else '#ssh-review')
    if staged:
        mobile_setup(browser, fixture, 'auth')
    browser.fill('#ssh-password', fixture.password)
    if staged:
        mobile_setup(browser, fixture, 'auth', input_state='ready')
        _rotation_stage(fixture, 3)
    elif browser.evaluate("document.querySelector('#ssh-review').checked") is not True:
        raise GuiFailure('direct_rotation_review_invalidated')
    browser.click('#ssh-connect' if staged else '#ssh-form button[type=submit]')
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
    terminal_proof=(capture_terminal_proof(browser,fixture,evidence_dir,stem='ssh-rotation-terminal-android')
                    if getattr(fixture,'screen_token',None) else None)
    browser.click('#ssh-disconnect')
    if staged:
        mobile_setup(browser, fixture, 'closed')
    else:
        wait_for(lambda: '已断开' in (browser.read('#ssh-status') or ''), 'direct_rotation_disconnect_ui_missing', timeout=60)
    fixture.wait_for_connections_closed(minimum=4, timeout=30)
    evidence_4 = _rotation_stage(fixture, 4)
    return {'probeReviewed':True,'refusalBlocked':True,'reviewNoExits':True,'cancelKeptTrust':True,
            'reprobePresented':True,'connected':True,'terminalInputReceived':True,'terminalEchoRendered':True,
            'disconnected':True,'passwordCleared':True,
            'rotationEvidence':[evidence_2,evidence_3,evidence_4],
            **({'terminalScreenshot':terminal_proof} if terminal_proof else {})}


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



def _connect_ready(port):
    # A failed ready probe must not leak its already-open CDP connection.
    view = None
    ready = False
    try:
        view = AndroidWebView(port)
        ready = bool(view.evaluate("document.readyState === 'complete' && !!document.querySelector('#ssh-form') && !!window.__TAURI_INTERNALS__"))
        return view if ready else False
    except GuiFailure:
        return False
    finally:
        if view is not None and not ready:
            try: view.close()
            except GuiFailure: pass


def run_device(apk, fixture, *, encrypted_key=False, key_change=False, evidence_dir=None, progress=None):
    if progress is not None: progress['stage']='device_preflight'
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
        if progress is not None: progress['stage']='reverse_setup'
        adb('reverse',reverse,reverse);reverse_added=True
        if progress is not None: progress['stage']='install_app'
        adb('install',str(apk),timeout=90);installed=True
        if progress is not None: progress['stage']='launch_app'
        adb('shell','monkey','-p',PACKAGE,'-c','android.intent.category.LAUNCHER','1')
        pid=wait_for(lambda:adb('shell','pidof',PACKAGE,check=False),'direct_app_missing',timeout=60)
        if not re.fullmatch(r'\d+',pid):raise GuiFailure('direct_app_pid_invalid')
        socket_name='webview_devtools_remote_'+pid
        if progress is not None: progress['stage']='webview_socket'
        wait_for(lambda:'@'+socket_name in adb('shell','cat','/proc/net/unix',check=False),
                 'direct_webview_socket_missing',timeout=60)
        if progress is not None: progress['stage']='webview_forward'
        port=adb('forward','tcp:0','localabstract:'+socket_name)
        if not port.isdigit() or not 1 <= int(port) <= 65535:raise GuiFailure('direct_forward_invalid')
        forwarded='tcp:'+port
        if progress is not None: progress['stage']='webview_ready'
        browser=wait_for(lambda:_connect_ready(int(port)),'direct_webview_not_ready',timeout=60)
        browser._temporary_install_confirmed=True  # fresh install verified above; pm list showed absence
        if progress is not None: progress['stage']='rotation_ui' if key_change else 'open_remote'
        result=(exercise_key_change_ui(browser,fixture,evidence_dir=evidence_dir) if key_change
                else exercise_ui(browser,fixture,encrypted_key=encrypted_key,evidence_dir=evidence_dir,progress=progress))
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
        if cleanup:
            if progress is not None: progress['stage']='cleanup'
            raise GuiFailure('direct_cleanup_failed')
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
    progress={}
    try:
        from direct_ssh_fixture import DirectSshFixture
        report['apkSha256']=hashlib.sha256(args.apk.read_bytes()).hexdigest()
        with DirectSshFixture(observe_helper_keys=True,screen_proof=True) as fixture:
            try:
                report.update(run_device(args.apk,fixture,evidence_dir=output,progress=progress))
                progress.clear()
            except GuiFailure:
                report['probeEvidence'] = probe_evidence(fixture)
                raise
        if fixture.snapshot().get('connectionsClosed') is not True:
            raise GuiFailure('direct_fixture_cleanup_failed')
        report['cleanup']['fixtureConnections']=True
        progress.clear()
        with DirectSshFixture(rotate_after_probe=True, observe_helper_keys=True,screen_proof=True) as rotation:
            report['phase']='host_key_rotation'
            try:
                rotation_result=run_device(args.apk,rotation,key_change=True,evidence_dir=output,progress=progress)
                progress.clear()
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
        progress.clear()
        with EncryptedKeyFixture() as key_fixture:
            try:
                key_result=run_device(args.apk,key_fixture,encrypted_key=True,progress=progress)
                progress.clear()
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
        diagnostic=getattr(error,'active_diagnostic',None)
        if isinstance(diagnostic,dict) and set(diagnostic)==ACTIVE_FACTS and all(type(v) is bool for v in diagnostic.values()):
            report['activeDiagnostic']=diagnostic
        context=getattr(error,'active_context',None)
        if isinstance(context,dict): report['activeContext']=context
        ime_checks=getattr(error,'ime_checks',None)
        if isinstance(ime_checks,list) and len(ime_checks)<=6:
            report['activeImeChecks']=[public_ime_diagnostic(item) for item in ime_checks]
        ime_failure=public_ime_diagnostic(getattr(error,'ime_failure',None))
        if ime_failure: report['activeImeFailure']=ime_failure
        second_open_facts=getattr(error,'second_open_checkpoint',None)
        if isinstance(second_open_facts,list) and 1<=len(second_open_facts)<=3:
            report['secondOpenFacts']=second_open_facts
        stored_facts=progress.get('secondOpenFacts')
        if isinstance(stored_facts,list) and 1<=len(stored_facts)<=3:
            report['secondOpenFacts']=stored_facts
        report['errorCode']=public_driver_error(error)
        if progress.get('stage') in DRIVER_STAGES: report['failureStage']=progress['stage']
    except Exception:
        report['errorCode']='direct_fixture_or_driver_failed'
        stored_facts=progress.get('secondOpenFacts')
        if isinstance(stored_facts,list) and 1<=len(stored_facts)<=3:
            report['secondOpenFacts']=stored_facts
        if progress.get('stage') in DRIVER_STAGES: report['failureStage']=progress['stage']
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if report['status']!='passed': raise SystemExit(1)


if __name__=='__main__': main()
