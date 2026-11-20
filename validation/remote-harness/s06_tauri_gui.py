"""Native GTK S06 driver. Reuses WebDriver and the reviewed two-peer fixture."""
import base64
from contextlib import contextmanager, nullcontext
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paired_gui import WebDriver, GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for


WINDOW_HEIGHT = 1200
WIDE_WIDTH = 1440
NARROW_WIDTH = 700


def owned_xvfb(env, *, proc=Path('/proc'), parent=None):
    """Match the Xvfb child of our own xvfb-run wrapper and its authorization file."""
    display, authority = env.get('DISPLAY', ''), env.get('XAUTHORITY', '')
    if not re.fullmatch(r':[0-9]+', display) or not authority:
        return False

    def argv(pid):
        return [os.fsdecode(arg) for arg in (proc / str(pid) / 'cmdline').read_bytes().split(b'\0') if arg]

    pid = os.getppid() if parent is None else parent
    try:
        while pid > 1:
            if any(Path(arg).name == 'xvfb-run' for arg in argv(pid)[:2]):
                children = (proc / str(pid) / 'task' / str(pid) / 'children').read_text().split()
                for child in children:
                    try:
                        args = argv(child)
                    except FileNotFoundError:
                        continue
                    if (len(args) >= 2 and Path(args[0]).name == 'Xvfb' and args[1] == display and
                            ('-auth', authority) in zip(args, args[1:]) and
                            ('-nolisten', 'tcp') in zip(args, args[1:])):
                        return True
                return False
            status = (proc / str(pid) / 'status').read_text()
            pid = int(re.search(r'^PPid:\s+([0-9]+)$', status, re.MULTILINE)[1])
    except (OSError, TypeError, ValueError):
        return False
    return False


@contextmanager
def park_xvfb_pointer(env):
    if not owned_xvfb(env):
        yield False
        return
    try:
        x11 = ctypes.CDLL('libX11.so.6')  # A runtime dependency of Xvfb.
    except OSError as error:
        raise GuiFailure('s06_tauri_xvfb_x11_unavailable') from error
    display_type, window_type, integer = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int
    x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], display_type
    x11.XDefaultRootWindow.argtypes, x11.XDefaultRootWindow.restype = [display_type], window_type
    x11.XGetInputFocus.argtypes = [display_type, ctypes.POINTER(window_type), ctypes.POINTER(integer)]
    x11.XWarpPointer.argtypes = [display_type, window_type, window_type, integer, integer,
                               ctypes.c_uint, ctypes.c_uint, integer, integer]
    x11.XSync.argtypes, x11.XCloseDisplay.argtypes = [display_type, integer], [display_type]
    display = x11.XOpenDisplay(env['DISPLAY'].encode())
    if not display:
        raise GuiFailure('s06_tauri_xvfb_display_unavailable')
    try:
        focus, revert_to = window_type(), integer()
        x11.XGetInputFocus(display, ctypes.byref(focus), ctypes.byref(revert_to))
        parked = focus.value == 1  # PointerRoot is the bare Xvfb default.
        if parked:
            # At the default point (960, 700), a 700px window moves out from
            # under the pointer and Xvfb sends a real blur. Park before launch.
            root = x11.XDefaultRootWindow(display)
            if not x11.XWarpPointer(display, 0, root, 0, 0, 0, 0, 300, 100):
                raise GuiFailure('s06_tauri_xvfb_pointer_setup_failed')
            x11.XSync(display, 0)
        # Xvfb resets the pointer when the last client disconnects.
        yield parked
    finally:
        x11.XCloseDisplay(display)


TICK_ROW_SCRIPT = r"""
const panel=document.querySelector(arguments[0]);
const viewport=panel?.querySelector('.term-scroll'), host=viewport?.querySelector('.terminal-host');
const screen=host?.querySelector('.xterm-screen'), row=screen?.querySelector('.xterm-rows')?.children[22];
if(!row || !row.getClientRects().length)return {text:null,layout:{reason:'row-missing'}};
const focus=document.activeElement, selected=panel.dataset.focus;
const round=value=>Math.round(value*10)/10;
function hitTarget(x,y){
    if(x<0 || x>=innerWidth || y<0 || y>=innerHeight)return 'outside-window';
    const hit=document.elementFromPoint(x,y);
    if(!hit)return 'no-target';
    if(host.contains(hit))return 'terminal';
    // A scrollport hit could be its browser-painted scrollbar area.
    if(hit===viewport)return 'scrollport';
    if(hit.closest('.route-tabs'))return 'navigation';
    if(hit.closest('.terminal-selection'))return 'selection-dialog';
    if(hit.closest('.tab-mobile-controls'))return 'input-controls';
    if(panel.contains(hit))return 'panel';
    return 'outside-panel';
}
function measure(){
    const canvas=screen.getBoundingClientRect(), line=row.getBoundingClientRect(), rect=viewport.getBoundingClientRect();
    const y=line.top+line.height/2;
    const left=rect.left+viewport.clientLeft, top=rect.top+viewport.clientTop;
    const right=left+viewport.clientWidth, bottom=top+viewport.clientHeight;
    const points=[0,10,29].map(col=>{
        const x=canvas.left+(col+.5)*canvas.width/80;
        const inClient=x>=left && x<right && y>=top && y<bottom;
        return {x:round(x),y:round(y),inClient,target:hitTarget(x,y)};
    });
    return {points,rowY:round(y),screenHeight:round(canvas.height),
        client:{left:round(left),top:round(top),right:round(right),bottom:round(bottom)},
        clearance:round(Math.min(y-Math.max(top,0),Math.min(bottom,innerHeight)-y)),
        terminalScrollTop:round(viewport.scrollTop),terminalScrollLeft:round(viewport.scrollLeft),
        terminalScrollHeight:viewport.scrollHeight,terminalScrollWidth:viewport.scrollWidth,
        pageScrollY:round(scrollY),windowWidth:innerWidth,windowHeight:innerHeight,
        devicePixelRatio,visualViewportScale:window.visualViewport?.scale ?? null};
}
const initial=measure(), hit=data=>data.points.every(point=>point.inClient && point.target==='terminal');
// Keep the sample away from an edge where a native scrollbar may overlap it.
// A regular scroll can only move the row as far as the content allows.
if(arguments[1] !== false && (!hit(initial) || initial.clearance<24))
    row.scrollIntoView({block:'center',inline:'start',behavior:'instant'});
const final=measure();
const focusPreserved=document.activeElement===focus && panel.dataset.focus===selected;
return {text:focusPreserved && hit(final) ? row.textContent.replace(/\u00a0/g,' ').trim() : null,
    layout:{reason:!focusPreserved?'focus-changed':hit(final)?'row-hit':'row-clipped',initial,final}};
"""


FIRST_DIRECT_KEY_SCRIPT = r"""
const [panels, targets, action] = arguments;
const kinds = ['keydown', 'keypress', 'beforeinput', 'input', 'keyup', 'compositionstart', 'compositionend'];
const count = (sample, name) => { sample[name] = Math.min(sample[name] + 1, 64); };
const one = (root, selector) => {
    const matches = root?.querySelectorAll(selector);
    return matches?.length === 1 ? matches[0] : null;
};
const root = one(document, '#view-content');
const views = panels.map(selector => one(root, ':scope > ' + selector));
const [a, b] = views;
const visible = element => !!element && !element.closest('[hidden]') &&
    !!element.getClientRects().length && getComputedStyle(element).visibility === 'visible';
const originalTargetsActive = !document.hidden && !document.querySelector('dialog[open]') &&
    visible(one(document, '#remote-page')) && root?.dataset.split === '2' &&
    root.querySelectorAll(':scope > [data-role="workbench-panel"]').length === 2 &&
    views.every((view, index) => visible(view) &&
        one(view, ':scope > .panel-head + p')?.textContent.split(' · ').slice(-2)
            .join(' · ') === targets[index].join(' · ') &&
        one(view, '.tab-connection-actions')?.dataset.state === 'active');
const selectedB = a?.dataset.focus === 'false' && b?.dataset.focus === 'true';
const [aEditor, editor] = views.map(view => one(view, '.terminal-host textarea.xterm-helper-textarea'));
const aReadOnly = aEditor?.readOnly === true && aEditor.getAttribute('inputmode') === 'none' &&
    one(a, '.tab-mobile-controls')?.dataset.mode === 'observe';
const bReadOnly = editor?.readOnly === true && editor.getAttribute('inputmode') === 'none';
const bEditorWritable = visible(editor) && !editor.disabled && !editor.readOnly &&
    editor.getAttribute('inputmode') === 'text';
const bEditorFocused = !!editor && document.activeElement === editor;
const documentFocused = document.hasFocus();
const controls = one(b, '.tab-mobile-controls');
const bMode = controls?.dataset.mode;
const bModeReady = visible(controls) && bMode === 'direct' &&
    one(controls, ':scope > p[role="status"]')?.textContent === '逐键输入已启用；每次输入单独发送。';
const receipt = one(b, '[data-role="input-receipt"]:not([hidden]) > p')?.textContent;
const bReceipt = !receipt ? 'absent' :
    receipt.includes(` · pane：${targets[1][0]} · terminal：${targets[1][1]} · 受理 1 字节。`) ? 'matched' : 'other';

let record = window.__s06FirstDirectKey;
if (action === 'prepare' && !record && originalTargetsActive && selectedB && aReadOnly &&
    visible(editor) && bReadOnly && bMode === 'observe' && bReceipt === 'absent') {
    record = {editor, keyDowns: 0, matched: false, modeResources: 0, sendResources: 0,
        events: Object.fromEntries(kinds.map(kind => [kind, {atDocument: 0, trustedOriginal: 0,
            fixtureCharacter: 0, usableLegacyCode: 0, composed: 0, whileComposing: 0, preventedAtDocument: 0,
            atEditorAfterHandlers: 0, preventedAtEditor: 0}]))};
    // The mode grant calibrates custom-protocol resource timing in this WebView.
    // The native fallback may have no resource entry, which stays unavailable.
    try {
        const runtime = window.__TAURI_INTERNALS__;
        const mode = runtime.convertFileSrc('remote_tab_input_mode', 'ipc');
        const send = runtime.convertFileSrc('remote_tab_input_send', 'ipc');
        record.countResources = entries => {
            for (const entry of entries) {
                if (entry.name === mode) count(record, 'modeResources');
                if (entry.name === send) count(record, 'sendResources');
            }
        };
        record.resources = new PerformanceObserver(list => record.countResources(list.getEntries()));
        record.resources.observe({type: 'resource'});
    } catch {
        record.resources = null;
    }
    window.__s06FirstDirectKey = record;
}
const originalEditorB = !!record && editor === record.editor;
if (action === 'arm' && originalEditorB && !record.onCapture && originalTargetsActive && selectedB && aReadOnly &&
    documentFocused && bEditorFocused && bEditorWritable && bModeReady && bReceipt === 'absent') {
    const original = event => event.isTrusted && document.hasFocus() && event.target === record.editor &&
        document.activeElement === record.editor && !record.editor.readOnly &&
        record.editor.getAttribute('inputmode') === 'text';
    const plain = event => !event.repeat && !event.isComposing &&
            !event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey &&
            event.key === 'b';
    // Observe on either side of the existing target handlers without changing
    // the event. No key value, text, resource URL or IPC payload is retained.
    record.onCapture = event => {
        const kind = event.type;
        if (kind === 'keydown') {
            record.keyDowns++;
            record.matched = plain(event) && original(event);
        }
        if (event.target !== record.editor) return;
        const sample = record.events[kind];
        count(sample, 'atDocument');
        if (event.defaultPrevented) count(sample, 'preventedAtDocument');
        if (!original(event)) return;
        count(sample, 'trustedOriginal');
        if (event.composed) count(sample, 'composed');
        if (event.isComposing) count(sample, 'whileComposing');
        if (kind === 'keydown' || kind === 'keyup') {
            if (plain(event)) count(sample, 'fixtureCharacter');
            if (event.keyCode === 66) count(sample, 'usableLegacyCode');
        } else if (kind === 'keypress') {
            if (plain(event)) count(sample, 'fixtureCharacter');
            if (event.charCode === 98 || (event.which == null && event.keyCode === 98))
                count(sample, 'usableLegacyCode');
        } else if ((kind === 'beforeinput' || kind === 'input') &&
                   event.inputType === 'insertText' && event.data === 'b' && !event.isComposing) {
            count(sample, 'fixtureCharacter');
        }
    };
    record.onEditor = event => {
        if (!original(event)) return;
        const sample = record.events[event.type];
        count(sample, 'atEditorAfterHandlers');
        if (event.defaultPrevented) count(sample, 'preventedAtEditor');
    };
    for (const kind of kinds) {
        document.addEventListener(kind, record.onCapture, {capture: true, passive: true});
        record.editor.addEventListener(kind, record.onEditor, {capture: true, passive: true});
    }
}
if (record?.resources) record.countResources(record.resources.takeRecords());
const result = {originalTargetsActive, selectedB, originalEditorB, aReadOnly, bReadOnly,
    documentFocused, bEditorFocused, bEditorWritable, bModeReady, bMode, bReceipt,
    armed: !!record?.onCapture, keyDowns: record?.keyDowns ?? 0, trustedKeyOnOriginalB: record?.matched === true,
    events: record?.events ?? null, ipcTiming: {calibrated: (record?.modeResources ?? 0) > 0,
        completedSendResources: record?.sendResources ?? 0}};
if (action === 'finish' && record) {
    if (record.onCapture) {
        for (const kind of kinds) {
            document.removeEventListener(kind, record.onCapture, true);
            record.editor.removeEventListener(kind, record.onEditor, true);
        }
    }
    record.resources?.disconnect();
    delete window.__s06FirstDirectKey;
}
return result;
"""


DIRECT_EXIT_SCRIPT = r"""
const [panels, targets, arm] = arguments;
const one = (root, selector) => {
    const matches = root?.querySelectorAll(selector);
    return matches?.length === 1 ? matches[0] : null;
};
const root = one(document, '#view-content');
const page = one(document, '#remote-page');
const views = panels.map(selector => one(root, ':scope > ' + selector));
const [a, b] = views;
const visible = element => !!element && !element.closest('[hidden]') &&
    !!element.getClientRects().length && getComputedStyle(element).visibility === 'visible';
const originalTargetsActive = !document.hidden && !document.querySelector('dialog[open]') &&
    visible(page) && root?.dataset.split === '2' &&
    root.querySelectorAll(':scope > [data-role="workbench-panel"]').length === 2 &&
    views.every((view, index) => visible(view) &&
        one(view, ':scope > .panel-head + p')?.textContent.split(' · ').slice(-2)
            .join(' · ') === targets[index].join(' · ') &&
        one(view, '.tab-connection-actions')?.dataset.state === 'active');
const selectedB = a?.dataset.focus === 'false' && b?.dataset.focus === 'true';
const xterms = views.map(view => one(view, '.terminal-host textarea.xterm-helper-textarea'));
const modes = views.map(view => one(view, '.tab-mobile-controls')?.dataset.mode);
const editor = xterms[1];
const directXterm = !!editor && visible(editor) && document.activeElement === editor &&
    !editor.readOnly && editor.getAttribute('inputmode') === 'text' && modes[1] === 'direct';
const bReceipt = one(b, '[data-role="input-receipt"]:not([hidden]) > p')?.textContent;
const bReceiptMatched = bReceipt?.includes(
    ` · pane：${targets[1][0]} · terminal：${targets[1][1]} · 受理 1 字节。`) === true;
const aFocusButton = one(a, '.panel-head > button[data-role="panel-focus"]');
const aFocusButtonReady = visible(aFocusButton) && !aFocusButton.disabled &&
    aFocusButton.textContent.trim() === '设为输入焦点' &&
    aFocusButton.getAttribute('aria-pressed') === 'false';

let armed = false;
if (arm && originalTargetsActive && selectedB && directXterm && bReceiptMatched &&
    aFocusButtonReady && !window.__s06DirectExitKey) {
    const record = {editor, destination: aFocusButton, count: 0, matched: false};
    window.__s06DirectExitKey = record;
    // Passive observer on the router's same capture target, registered later.
    // Read the native key after the router has had the opportunity to consume it.
    document.addEventListener('keydown', event => {
        if (event.key !== 'F6') return;
        record.count++;
        record.matched = event.target === record.editor && event.isTrusted && event.defaultPrevented &&
            event.ctrlKey && event.shiftKey && !event.altKey && !event.metaKey &&
            !event.repeat && !event.isComposing;
    }, {capture: true, passive: true});
    armed = true;
}
const record = window.__s06DirectExitKey;
return {originalTargetsActive, selectedB, directXterm, bReceiptMatched, aFocusButtonReady, armed,
    aFocusButtonFocused: aFocusButtonReady && aFocusButton === record?.destination &&
        document.activeElement === aFocusButton,
    bothReadOnly: xterms.every((item, index) => !!item?.readOnly &&
        item.getAttribute('inputmode') === 'none' && modes[index] === 'observe'),
    keyCount: record?.count ?? 0, trustedConsumedChord: record?.matched === true};
"""


DIRECT_RESIZE_SCRIPT = r"""
const [panels, targets, action] = arguments;
const one = (root, selector) => {
    const matches = root?.querySelectorAll(selector);
    return matches?.length === 1 ? matches[0] : null;
};
const root = one(document, '#view-content');
const [a,b] = panels.map(selector => one(root, ':scope > ' + selector));
const editor = one(b, '.terminal-host textarea.xterm-helper-textarea');
const controls = one(b, '.tab-mobile-controls');
const connection = one(b, '.tab-connection-actions');
const receipt = one(b, '[data-role="input-receipt"]:not([hidden]) > p')?.textContent;
const aTab = one(document, '#view-tabs button[aria-pressed="false"]');
const selectedB = b?.dataset.focus === 'true' && b.getClientRects().length > 0 &&
    one(document, '#view-tabs button[aria-pressed="true"]') !== null;
const targetB = one(b, ':scope > .panel-head + p')?.textContent.split(' · ').slice(-2).join(' · ') ===
    targets[1].join(' · ');
const directB = !!editor && !document.hidden && !document.querySelector('dialog[open]') &&
    document.hasFocus() && document.activeElement === editor && !editor.readOnly && editor.getAttribute('inputmode') === 'text' &&
    controls?.dataset.mode === 'direct' && connection?.dataset.state === 'active';
const receiptB = receipt?.includes(` · pane：${targets[1][0]} · terminal：${targets[1][1]} · 受理 1 字节。`) === true;
const aEditor = one(a, '.terminal-host textarea.xterm-helper-textarea');
const aObserves = one(a, '.tab-mobile-controls')?.dataset.mode === 'observe' &&
    aEditor?.readOnly === true && aEditor.getAttribute('inputmode') === 'none';
let record = window.__s06DirectResize;
if (action === 'arm' && !record && root?.dataset.split === '2' &&
    selectedB && targetB && directB && receiptB && aTab && aObserves) {
    record = {editor, controls, connection, receipt, aTab, firstBlur: null, changed: false};
    record.onBlur = () => { record.firstBlur ??= {
        width: innerWidth, documentFocused: document.hasFocus(), editorAttached: editor.isConnected
    }; };
    editor.addEventListener('blur', record.onBlur, {passive: true});
    const check = mutations => {
        record.changed ||= mutations.some(m =>
            (m.type === 'childList' && [...m.removedNodes].some(node => node.contains(editor))) ||
            (m.target === editor && m.attributeName === 'readonly' && m.oldValue !== null) ||
            (m.target === editor && m.attributeName === 'inputmode' && m.oldValue !== 'text') ||
            (m.target === controls && m.attributeName === 'data-mode' && m.oldValue !== 'direct') ||
            (m.target === b && m.attributeName === 'data-focus' && m.oldValue !== 'true') ||
            (m.target === connection && m.attributeName === 'data-state' && m.oldValue !== 'active'));
    };
    const watcher = new MutationObserver(check);
    watcher.observe(root, {subtree: true, childList: true, attributes: true, attributeOldValue: true,
        attributeFilter: ['readonly','inputmode','data-mode','data-focus','data-state']});
    record.drain = () => check(watcher.takeRecords());
    record.stop = () => {
        watcher.disconnect();
        editor.removeEventListener('blur', record.onBlur);
    };
    window.__s06DirectResize = record;
}
record?.drain();
const singleB = root?.matches(panels[1]) === true;
const actualB = b ?? (singleB ? root : null);
const result = {armed: !!record, selectedB, targetB, directB, receiptB, aObserves,
    originalEditor: !!record && record.editor === editor,
    originalInputState: !!record && record.controls === controls && record.connection === connection &&
        record.receipt === receipt && !record.changed,
    neverBlurred: !!record && !record.firstBlur,
    aPaused: !!record && aTab === record.aTab && aTab.textContent.endsWith(' · 观察已暂停'),
    diagnostic: {width: innerWidth, documentFocused: document.hasFocus(), split: root?.dataset.split,
        singleB, wrappedB: !!b, originalEditorAttached: record?.editor.isConnected === true,
        actualBMode: one(actualB, '.tab-mobile-controls')?.dataset.mode,
        firstBlur: record?.firstBlur ?? null}};
if (action === 'finish' && record) {
    record.stop();
    delete window.__s06DirectResize;
}
return result;
"""


MANUAL_PAUSE_SCRIPT = r"""
const [selectors,targets,element]=arguments;
const one=(root,selector)=>{
    const matches=root.querySelectorAll(selector);
    return matches.length===1?matches[0]:null;
};
const visible=e=>!!e && !e.closest('[hidden]') && getComputedStyle(e).visibility==='visible' &&
    !!e.getClientRects().length;
const centerHit=r=>{
    if(!r||r.width<=0||r.height<=0)return null;
    const x=r.left+r.width/2, y=r.top+r.height/2;
    return x>=0&&x<innerWidth&&y>=0&&y<innerHeight?document.elementFromPoint(x,y):null;
};
const remote=one(document,'#remote-page'), board=one(document,'#home-dashboard');
const heading=board?.querySelector('#host-board-intro h2'), showBoard=one(document,'#show-remote');
const onBoard=visible(heading) && heading.contains(centerHit(heading.getBoundingClientRect())) &&
    showBoard?.getAttribute('aria-pressed')==='true';
const onWorkspace=visible(remote) && !visible(document.querySelector('#host-home'));
const page=document.hidden?'background':onWorkspace?'workspace':
    onBoard&&!!remote&&!visible(remote)?'dashboard':'other';
const states=selectors.map((selector,i)=>{
    const panel=remote&&one(remote, '#view-content '+selector);
    if(!panel)return {phase:'missing',notice:'none'};
    const title=panel.querySelector(':scope > p:not([data-role])');
    const target=title?.textContent.split(' · ').slice(-2) ?? [];
    if(target.length!==2||!target.every((part,j)=>part===targets[i][j]))return {phase:'unbound',notice:'none'};
    const phase=one(panel,'.tab-connection-actions')?.dataset.state;
    const notice=panel.querySelector(':scope > p[role="status"]')?.textContent;
    return {phase:['disconnected','connecting','starting','active','pausing','paused','resuming','closed'].includes(phase)
        ?phase:'other',notice:notice==='观察已暂停，SSH 保留；需主动恢复。'?'paused-message':
        notice==='暂停未确认，连接已取消；不会自动重连。'?'pause-failed-message':'none'};
});
const phases=states.map(state=>state.phase), pauseNotices=states.map(state=>state.notice);
const viewCount=Math.min(remote?.querySelectorAll('#view-content .tab-connection-actions').length ?? 0,3);
const count=document.querySelectorAll('#host-return-home').length;
const button=one(document,'#host-return-home');
const buttonBound=button?.tagName==='BUTTON' && button?.textContent.trim()==='返回主机看板' &&
    !!button.closest('#remote-page #workbench-main') && button===element;
const enabled=!!button && !button.matches(':disabled');
const prepared=page==='workspace' && buttonBound && enabled && visible(button) &&
    viewCount===2 && phases.length===2 && phases.every(phase=>phase==='active');
if(prepared)button.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
const r=visible(button)?button.getBoundingClientRect():null;
const hit=centerHit(r);
const hitKind=hit?(button?.contains(hit)?'button':'other'):r?'outside-or-empty':'not-visible';
const buttonReady=prepared && !!hit && button.contains(hit);
if(buttonReady){
    // Read only the fact that the real control received each user event.
    const events={pointerDown:false,click:false};
    window.__s06ManualPauseEvents=events;
    button.addEventListener('pointerdown',e=>events.pointerDown=e.isTrusted,{capture:true,once:true});
    button.addEventListener('click',e=>events.click=e.isTrusted,{capture:true,once:true});
}
const unsafe=['dialog[open]','#remote-setup[open]','.terminal-selection',
    '#config-transfer','#home-ssh','#home-add','#network-panel'].some(selector=>
        [...document.querySelectorAll(selector)].some(visible));
const events=window.__s06ManualPauseEvents;
const round=value=>Math.round(value);
return {page,phases,pauseNotices,viewCount,buttonReady,buttonBound:!!buttonBound,buttonEnabled:enabled,
    buttonCount:Math.min(count,2),
    buttonRect:r?[r.left,r.top,r.right,r.bottom].map(round):null,hit:hitKind,
    viewport:[innerWidth,innerHeight],scrollY:round(scrollY),
    pointerDown:events?.pointerDown===true,trustedClick:events?.click===true,
    safeScreenshot:!unsafe && (page==='workspace'||page==='dashboard')};
"""


def observed_tick(text, side):
    if not isinstance(text, str) or len(text.encode()) > 65536:
        raise GuiFailure('s06_tauri_visible_text_invalid')
    prefix = 'Synthetic observe tick' if side == 0 else 'S06 B tick'
    matches = re.findall(re.escape(prefix) + r' ([0-9]{6})', text)
    if len(matches) != 1:
        raise GuiFailure('s06_tauri_visible_peer_marker_missing')
    return int(matches[0])


def require_side_by_side(rectangles):
    if (not isinstance(rectangles, list) or len(rectangles) != 2 or
            any(not isinstance(r, dict) or any(type(r.get(k)) is not int for k in ('left', 'right', 'top', 'width', 'height'))
                or r['width'] <= 0 or r['height'] <= 0 for r in rectangles)):
        raise GuiFailure('s06_tauri_panel_geometry_invalid')
    left, right = sorted(rectangles, key=lambda r: r['left'])
    if abs(left['top'] - right['top']) > 1 or left['right'] > right['left'] + 1:
        raise GuiFailure('s06_tauri_panels_not_side_by_side')


def window_dimensions(rect):
    if (not isinstance(rect, dict) or any(type(rect.get(name)) is not int or rect[name] <= 0
                                         for name in ('width', 'height'))):
        raise GuiFailure('s06_tauri_window_geometry_invalid')
    return {name: rect[name] for name in ('width', 'height')}


def layout_matches(layout, targets, phases, focused, *, guarded=False):
    narrow = any(phase is None for phase in phases)
    if (not isinstance(layout, dict) or layout.get('split') != ('1' if narrow else '2') or
            layout.get('mounted') != (1 if narrow else 2) or layout.get('splitVisible') is not (not narrow) or
            layout.get('stashNotice') is not narrow or layout.get('returnVisible') is not True):
        return False
    views = layout.get('views')
    if not isinstance(views, list) or len(views) != len(phases):
        return False
    for index, (view, target, phase) in enumerate(zip(views, targets, phases)):
        if phase is None:
            if view is not None:
                return False
        elif (not isinstance(view, dict) or view.get('target') != list(target) or view.get('phase') != phase or
              view.get('focused') is not (index == focused) or
              view.get('currentFrame') is not (phase == 'active') or view.get('inputControls') is not guarded):
            return False
    return True


def require_same_positions(before, after):
    for layout in (before, after):
        require_side_by_side([view.get('rect') for view in layout['views']])
    for original, restored in zip(before['views'], after['views']):
        if any(abs(original['rect'][key] - restored['rect'][key]) > 1 for key in ('left', 'right', 'width')):
            raise GuiFailure('s06_tauri_split_position_changed')


def peer_log_evidence(approval):
    """Keep the authenticated source ports private to the peer observer."""
    text = bounded_wire(approval.root / 'sshd.log', 2_097_152).decode(errors='replace').replace('\r\n', '\n')
    username = re.escape(approval.config['username'])
    accepted = (r'^Accepted publickey for ' + username + r' from 127\.0\.0\.1 port ([0-9]{1,5}) ssh2: ED25519 ' +
                re.escape(approval.fingerprint or '') + r'(?=\s|$)')
    connections = []
    for match in re.finditer(accepted, text, re.MULTILINE):
        port = int(match[1])
        if not 1 <= port <= 65535:
            continue
        peer = rf'127\.0\.0\.1 port {port}'
        remainder = text[match.end():]
        reuse = re.search(rf'^(?:Connection from|Accepted [^\n]* from) {peer}(?=\s|$)', remainder, re.MULTILINE)
        session = remainder[:reuse.start()] if reuse else remainder
        closed = re.search(rf'^(?:Received disconnect from {peer}:|'
                           rf'Disconnected from user {username} {peer}(?=\s|$)|'
                           rf'Connection closed by (?:user {username} )?{peer}(?=\s|$))[^\n]*$',
                           session, re.MULTILINE)
        # An authenticated transport reset explains a missing graceful record.
        # It cannot satisfy the close gate.
        reset = re.search(rf'^Read error from remote host {peer}: Connection reset by peer$', session, re.MULTILINE)
        connections.append((port, bool(closed and '[preauth]' not in closed[0]), bool(reset)))
    return connections


def peer_connection_evidence(approval):
    connections = peer_log_evidence(approval)
    return {'authenticationCount': len(connections), 'closed': bool(connections) and all(row[1] for row in connections)}


def loopback_tcp_states(path=Path('/proc/net/tcp')):
    """Snapshot only IPv4 loopback tuples on the sshd's network namespace."""
    try:
        with path.open(encoding='ascii') as source:
            text = source.read(2_097_153)
        if len(text) > 2_097_152 or 'local_address' not in text.split('\n', 1)[0]:
            return None
        result = {}
        for line in text.splitlines()[1:]:
            columns = line.split()
            if len(columns) < 4:
                return None
            local, remote, state = columns[1:4]
            if local.startswith('0100007F:') and remote.startswith('0100007F:'):
                result[int(local[9:], 16), int(remote[9:], 16)] = state
        return result
    except (OSError, ValueError):
        return None


def peer_close_sample(approvals):
    sockets = loopback_tcp_states()
    rows = []
    for approval in approvals:
        connections = peer_log_evidence(approval)
        listener = approval.config.get('port')
        socket_state = 'unavailable'
        if sockets is not None and type(listener) is int and len(connections) == 1:
            state = sockets.get((listener, connections[0][0]))
            socket_state = ('absent' if state is None else 'established' if state == '01' else
                            'closing' if state in ('04', '05', '06', '07', '08', '09', '0B') else 'other')
        rows.append({'authenticationCount': min(len(connections), 64),
                     'recognizedCloseCount': min(sum(row[1] for row in connections), 64),
                     'resetCount': min(sum(row[2] for row in connections), 64), 'socketState': socket_state})
    return rows


class SplitDriver:
    def __init__(self, driver, output=None):
        self.driver = driver
        self.output = output
        self.tick_layouts = {}

    def read(self, script, *args):
        return self.driver.call('POST', self.driver.session + '/execute/sync', {'script': script, 'args': list(args)})

    def open_pairing(self, *, empty_board):
        board = '#host-home:not([hidden]) #home-dashboard:not([hidden])'
        if empty_board:
            # The empty board hides the header, even in a wide window.
            self.driver.click(board + ' #host-empty:not([hidden]) #host-empty-add')
        else:
            self.driver.click('body:has(' + board + ' #host-list .saved-host-card) #host-open-remote')
        self.driver.click('#host-home:not([hidden]) #home-add:not([hidden]) #add-herdr')
        self.driver.wait_control('#remote-page:not([hidden]) #remote-setup[open] #remote-host')

    def entry_failure(self, stage):
        if self.output is None or not self.driver.session:
            return
        controls = {
            'board': '#home-dashboard', 'emptyAdd': '#host-empty-add',
            'headerAdd': '#host-open-remote', 'connectionChoice': '#add-herdr',
            'pairingHostField': '#remote-host', 'settings': '#home-settings',
            'importPanel': '#config-transfer', 'importFile': '#config-transfer input[type="file"]',
            'importPreview': '#config-transfer .config-preview',
            'workspace': '#tab-workspace',
        }
        try:
            visible = self.read('''return arguments[0].map(selector => {
                const node = document.querySelector(selector);
                return !!node && node.getClientRects().length > 0 &&
                    getComputedStyle(node).visibility === 'visible';
            });''', list(controls.values()))
            if (isinstance(visible, list) and len(visible) == len(controls) and
                    all(type(value) is bool for value in visible)):
                report = {'stage': stage, 'visible': dict(zip(controls, visible))}
                (self.output / 's06-tauri-entry-failure.json').write_text(json.dumps(report, sort_keys=True))
        except (GuiFailure, OSError, ValueError):
            pass  # Preserve the original failure. No UI text, form values, or raw screenshots.

    def named(self, text, scope='body', tag='button'):
        # Locate by public text, then send a real WebDriver click. Never invoke
        # a product handler, IPC command, renderer or input callback directly.
        def locate():
            found = []
            try:
                for element in self.driver.call('POST', self.driver.session + '/elements',
                        {'using': 'css selector', 'value': scope + ' ' + tag}):
                    key = element['element-6066-11e4-a52e-4f735466cecf']
                    path = self.driver.session + '/element/' + key
                    label = self.driver.call('GET', path + '/property/textContent')
                    if (isinstance(label, str) and label.strip() == text and
                            self.driver.call('GET', path + '/displayed') and self.driver.call('GET', path + '/enabled')):
                        found.append(path)
            except GuiFailure as error:
                if str(error) in {'webdriver_textContent_stale_element_reference',
                                 'webdriver_displayed_stale_element_reference',
                                 'webdriver_enabled_stale_element_reference'}:
                    return None  # No click was sent: relocate the read-only lookup.
                raise
            if len(found) > 1:
                raise GuiFailure('s06_tauri_ambiguous_public_control')
            return found[0] if found else None
        path = wait_for(locate, 's06_tauri_public_control_missing')
        self.driver.call('POST', path + '/click', {})

    def keyboard(self, text, *, modifiers=()):
        actions = [{'type': 'keyDown', 'value': key} for key in modifiers]
        for char in text:
            actions.extend([{'type': 'keyDown', 'value': char}, {'type': 'keyUp', 'value': char}])
        actions.extend({'type': 'keyUp', 'value': key} for key in reversed(modifiers))
        self.driver.call('POST', self.driver.session + '/actions', {'actions': [
            {'type': 'key', 'id': 's06-native-keyboard', 'actions': actions}]})

    def first_direct_key(self, panels, targets, wires):
        ready = ('originalTargetsActive', 'selectedB', 'originalEditorB', 'aReadOnly',
                 'documentFocused', 'bEditorFocused', 'bEditorWritable', 'bModeReady', 'armed')
        boolean_fields = (*ready, 'bReadOnly', 'trustedKeyOnOriginalB')
        event_kinds = ('keydown', 'keypress', 'beforeinput', 'input', 'keyup', 'compositionstart', 'compositionend')
        event_fields = ('atDocument', 'trustedOriginal', 'fixtureCharacter', 'usableLegacyCode', 'composed', 'whileComposing',
                        'preventedAtDocument', 'atEditorAfterHandlers', 'preventedAtEditor')
        report = {'stage': 'before_mode', 'keyboardAttempted': False,
                  'beforeMode': None, 'beforeKey': None, 'afterKey': None}

        def bounded_count(value):
            return value if type(value) is int and 0 <= value <= 64 else None

        def read(action):
            state = self.read(FIRST_DIRECT_KEY_SCRIPT, panels, targets, action)
            if not isinstance(state, dict):
                raise GuiFailure('s06_tauri_direct_key_observation_invalid')
            events = state.get('events')
            stages = {kind: {field: bounded_count(events[kind].get(field)) for field in event_fields}
                      for kind in event_kinds if isinstance(events, dict) and isinstance(events.get(kind), dict)}
            timing = state.get('ipcTiming')
            calibrated = isinstance(timing, dict) and timing.get('calibrated') is True
            sends = bounded_count(timing.get('completedSendResources')) if isinstance(timing, dict) else None
            observed = calibrated or bool(sends)
            return {**{field: state.get(field) is True for field in boolean_fields},
                    'bMode': state.get('bMode') if state.get('bMode') in ('observe', 'draft', 'direct') else None,
                    'bReceipt': state.get('bReceipt') if state.get('bReceipt') in ('absent', 'matched', 'other') else None,
                    'keyDowns': bounded_count(state.get('keyDowns')), 'events': stages,
                    'ipcTiming': {'calibrated': calibrated, 'status': 'observed' if observed else 'unavailable',
                                  'completedSendResources': sends if observed else None}}

        def peer_inputs():
            result = []
            for index, wire in enumerate(wires):
                try:
                    data = bounded_wire(wire, 4096)
                except (GuiFailure, OSError):
                    result.append({'byteCount': None, 'match': 'unavailable'})
                else:
                    match = 'empty' if not data else 'expected' if index == 1 and data == b'b' else 'other'
                    result.append({'byteCount': len(data), 'match': match})
            return result

        def arm():
            current = report['beforeKey'] = read('arm')
            return (all(current[field] for field in ready) and current['bMode'] == 'direct' and
                    current['bReceipt'] == 'absent' and current['keyDowns'] == 0)

        def received():
            a, b = (peer['match'] for peer in peer_inputs())
            if a != 'empty' or b not in ('empty', 'expected'):
                raise GuiFailure('s06_tauri_direct_peer_bytes_mismatch')
            return b == 'expected'

        def confirmed():
            current = report['afterKey'] = read('sample')
            return (all(current[field] for field in ready) and current['bMode'] == 'direct' and
                    current['bReceipt'] == 'matched' and current['keyDowns'] == 1 and current['trustedKeyOnOriginalB'])

        try:
            report['peerBefore'] = peer_inputs()
            if any(peer['match'] != 'empty' for peer in report['peerBefore']):
                raise GuiFailure('s06_tauri_direct_peer_bytes_mismatch')
            before = report['beforeMode'] = read('prepare')
            if not all(before[field] for field in ('originalEditorB', 'aReadOnly', 'bReadOnly')):
                raise GuiFailure('s06_tauri_direct_key_original_editor_missing')
            self.named('逐键输入', panels[1] + ' .tab-mode-actions')
            report['stage'] = 'before_key'
            wait_for(arm, 's06_tauri_direct_key_not_ready')
            report['peerBefore'] = peer_inputs()
            if any(peer['match'] != 'empty' for peer in report['peerBefore']):
                raise GuiFailure('s06_tauri_direct_peer_bytes_mismatch')
            report['stage'] = 'native_key'
            report['keyboardAttempted'] = True
            self.keyboard('b')
            report['stage'] = 'peer_input'
            wait_for(received, 's06_tauri_direct_input_missing')
            report['stage'] = 'key_receipt'
            wait_for(confirmed, 's06_tauri_direct_key_delivery_unconfirmed')
            report['stage'] = 'confirmed'
        finally:
            try:
                report['afterKey'] = read('finish')
            except (GuiFailure, OSError):
                pass
            if self.output is not None:
                report['peerAfter'] = peer_inputs()
                (self.output / 's06-tauri-first-direct-key.json').write_text(json.dumps(report, sort_keys=True))

    def escape_direct_input(self, panels, targets):
        before = ('originalTargetsActive', 'selectedB', 'directXterm', 'bReceiptMatched', 'aFocusButtonReady')
        after = ('originalTargetsActive', 'selectedB', 'aFocusButtonFocused', 'bothReadOnly', 'trustedConsumedChord')

        def ready(arm=False):
            evidence = self.read(DIRECT_EXIT_SCRIPT, panels, targets, arm)
            return (isinstance(evidence, dict) and all(evidence.get(key) is True for key in before) and
                    (not arm or evidence.get('armed') is True))

        def escaped():
            evidence = self.read(DIRECT_EXIT_SCRIPT, panels, targets, False)
            if (isinstance(evidence, dict) and type(evidence.get('keyCount')) is int and
                    evidence['keyCount'] == 1 and all(evidence.get(key) is True for key in after)):
                return {key: evidence[key] for key in (*after, 'keyCount')}
            return None

        # The independent peer has received b. Wait for the matching local
        # receipt as well, so this exit cannot interrupt an in-flight send.
        wait_for(ready, 's06_tauri_direct_escape_not_ready')
        if not ready(arm=True):
            raise GuiFailure('s06_tauri_direct_escape_not_armed')
        # W3C WebDriver key values for F6, Control and Shift. Send exactly once.
        self.keyboard('\ue036', modifiers=('\ue009', '\ue008'))
        return wait_for(escaped, 's06_tauri_direct_escape_unconfirmed')

    def focus(self, panel):
        if self.read('return document.querySelector(arguments[0])?.dataset.focus;', panel) != 'true':
            self.driver.click(panel + ' [data-role="panel-focus"]')
        wait_for(lambda: self.read('return document.querySelector(arguments[0])?.dataset.focus;', panel) == 'true',
                 's06_tauri_focus_not_selected')

    def layout_evidence(self, panel, side, phase):
        if self.output is None:
            return
        data = self.read('''const panel=document.querySelector(arguments[0]);
            const host=panel?.querySelector('.terminal-host'), screen=host?.querySelector('.xterm-screen');
            const tool=panel?.querySelector('.terminal-select-button');
            const rect=e=>{if(!e)return null;const r=e.getBoundingClientRect();return Object.fromEntries(
                ['left','top','right','bottom','width','height'].map(k=>[k,Math.round(r[k])]));};
            const text=panel?.innerText||'';
            const reason=text.includes('没有可安全测量')?'unmeasurable':text.includes('超过 64 KiB')?'too_large':
                text.includes('输入仍在处理')?'input_pending':'none';
            const ancestors=[];for(let e=screen?.parentElement;e&&ancestors.length<8;e=e.parentElement){
                const s=getComputedStyle(e);ancestors.push({rect:rect(e),clipX:/auto|scroll|hidden|clip/.test(s.overflowX),
                    clipY:/auto|scroll|hidden|clip/.test(s.overflowY)});}
            const r=screen?.getBoundingClientRect(), hits=[];
            if(r)for(const row of [0,22])for(const col of [0,10,29]){
                const hit=document.elementFromPoint(r.left+(col+.5)*r.width/80,r.top+(row+.5)*r.height/24);
                hits.push(!!hit&&!!host?.contains(hit));}
            return {viewportWidth:innerWidth,viewportHeight:innerHeight,scrollY:Math.round(scrollY),
                panel:rect(panel),terminal:rect(screen),tool:rect(tool),
                panelFocused:panel?.dataset.focus==='true',toolDisabled:!!tool?.disabled,documentHidden:document.hidden,
                selectionOpen:!!document.querySelector('.terminal-selection'),reason,cellHitSamples:hits,ancestors};''', panel)
        (self.output / f's06-tauri-layout-{side}-{phase}.json').write_text(json.dumps(data, sort_keys=True))

    def failure_screenshot(self, side):
        if self.output is None:
            return
        try:
            png = base64.b64decode(self.driver.call('GET', self.driver.session + '/screenshot'), validate=True)
            if png.startswith(b'\x89PNG\r\n\x1a\n') and len(png) <= 4_194_304:
                (self.output / f's06-tauri-visible-failure-{side}.png').write_bytes(png)
        except (GuiFailure, OSError, ValueError):
            pass

    def snapshot_tick(self, panel, side):
        self.focus(panel)
        self.collapse_details(panel)
        self.layout_evidence(panel, side, 'before')
        # The shared click helper centers controls by scrolling. This tool sits
        # below the terminal: native element-click uses the minimum necessary
        # scroll, preserving the cells above it for the product's visibility gate.
        self.named('选择终端文本', panel)
        field = '.terminal-selection textarea[readonly]'
        try:
            wait_for(lambda: self.read('return !!document.querySelector(arguments[0]);', field),
                     's06_tauri_visible_text_not_opened', timeout=4)
        except GuiFailure:
            self.layout_evidence(panel, side, 'after')
            self.failure_screenshot(side)
            raise
        value = self.driver.read(field, 'value')
        tick = observed_tick(value, side)
        self.named('关闭', '.terminal-selection')
        return tick

    def collapse_details(self, panel):
        for label in ('连接资料与诊断', '会话窗格'):
            if self.read('''return [...document.querySelector(arguments[0]).querySelectorAll('details')]
                .some(e=>e.open && e.querySelector('summary')?.textContent===arguments[1]);''', panel, label):
                self.named(label, panel, 'summary')

    def visible_frames(self, panels):
        # Normal local scrolling only. Both real terminal canvases must have
        # visible, hit-testable tick cells before a native screenshot is evidence.
        for panel in panels:
            self.collapse_details(panel)
        self.driver.wait_control(panels[0] + ' .term-scroll')
        return self.read('''return arguments[0].every(selector=>{
            const host=document.querySelector(selector+' .terminal-host'), screen=host?.querySelector('.xterm-screen');
            if(!screen)return false;const r=screen.getBoundingClientRect();
            return [0,10,29].every(col=>{const x=r.left+(col+.5)*r.width/80,y=r.top+22.5*r.height/24;
                const hit=document.elementFromPoint(x,y);return x>=0&&x<innerWidth&&y>=0&&y<innerHeight&&!!hit&&host.contains(hit);});
        });''', panels) is True


    def window(self, width):
        """Set the OS window once and wait for a native rect and the WebView to agree."""
        requested = {'width': width, 'height': WINDOW_HEIGHT}
        endpoint = self.driver.session + '/window/rect'
        if window_dimensions(self.driver.call('POST', endpoint, requested)) != requested:
            raise GuiFailure('s06_tauri_window_size_unconfirmed')
        return self.wait_window(width)

    def wait_window(self, width):
        requested = {'width': width, 'height': WINDOW_HEIGHT}
        endpoint = self.driver.session + '/window/rect'

        def observed():
            os_rect = window_dimensions(self.driver.call('GET', endpoint))
            viewport = window_dimensions(self.read('return {width:innerWidth,height:innerHeight};'))
            if os_rect == requested and (viewport['width'] >= 1300 if width == WIDE_WIDTH else viewport['width'] < 900):
                return {'window': os_rect, 'viewport': viewport}
            return None

        return wait_for(observed, 's06_tauri_window_viewport_unconfirmed')

    def read_layout(self, panels):
        return self.read(r"""
            const root=document.querySelector('#view-content');
            const visible=e=>!!e && !e.closest('[hidden]') && !!e.getClientRects().length &&
                getComputedStyle(e).visibility==='visible';
            const announce=root?.querySelector('[data-role="split-stash-note"]');
            const panels=arguments[0].map(selector=>document.querySelector(selector));
            const activeElement=document.activeElement;
            const owner=panels.findIndex(panel=>visible(panel) && panel.contains(activeElement));
            const domFocusOwner=!activeElement?'none':owner===0?'panel-a':owner===1?'panel-b':'outside-panels';
            const views=panels.map(panel=>{
                if(!visible(panel))return null;
                const title=[...panel.children].find(e=>e.tagName==='P' && !e.hasAttribute('data-role'));
                const target=title?.textContent.split(' · ').slice(-2) ?? [];
                const r=panel.getBoundingClientRect();
                const rect=Object.fromEntries(['left','right','top','width','height'].map(k=>[k,Math.round(r[k])]));
                return {target,rect,phase:panel.querySelector('.tab-connection-actions')?.dataset.state,
                    focused:panel.dataset.focus==='true',
                    currentFrame:panel.querySelector('.tab-frame-status')?.textContent.startsWith('当前观察画面。')===true,
                    inputControls:!!panel.querySelector('.tab-mobile-controls')};
            });
            const one=(selector,scope=document)=>{
                const matches=scope.querySelectorAll(selector);
                return matches.length===1?matches[0]:null;
            };
            const nav=one('nav.route-tabs > #nav-terminal'), remote=one('#remote-page');
            const workspace=remote&&one('#tab-workspace',remote);
            const home=one('#host-home'), board=home&&one('#home-dashboard',home);
            const isTerminal=visible(nav) && nav.getAttribute('aria-pressed')==='true' &&
                visible(workspace) && workspace.contains(root) && !!home && !visible(home);
            const page=document.hidden?'background':isTerminal?'terminal':visible(board)?'dashboard':'other';
            const form=page==='terminal'&&one('#remote-setup',remote);
            const summary=form&&one(':scope > summary',form);
            const pairing=form?.tagName==='DETAILS' && visible(summary) &&
                summary.textContent.trim()==='配对与连接资料' ? (form.open?'open':'closed') : 'unproven';
            return {views,domFocusOwner,page,pairing,split:root?.dataset.split,
                mounted:root?.dataset.role==='workbench-panel' ? 1 :
                    root?.querySelectorAll(':scope > section[data-role="workbench-panel"]').length,
                splitVisible:visible(document.querySelector('#workbench-split')),
                stashNotice:visible(announce) && announce.textContent.includes('分屏空间不足'),
                returnVisible:visible(document.querySelector('#host-return-home'))};
        """, panels)

    def wait_layout(self, panels, targets, phases, focused, stage):
        def observed():
            layout = self.read_layout(panels)
            return layout if layout_matches(layout, targets, phases, focused) else None
        return wait_for(observed, 's06_tauri_layout_' + stage)

    def rendered_tick(self, panel, side, *, scroll=True):
        sample = self.read(TICK_ROW_SCRIPT, panel, scroll)
        layout = sample['layout']
        self.tick_layouts[side] = layout
        if layout['reason'] == 'focus-changed':
            raise GuiFailure('s06_tauri_tick_scroll_changed_focus')
        return observed_tick(sample['text'], side) if layout['reason'] == 'row-hit' else None

    def ticks(self, panels, sides, floors=None, stage='sample'):
        self.tick_layouts = {}
        for side in sides:
            self.collapse_details(panels[side])

        def current():
            ticks = [self.rendered_tick(panels[side], side) for side in sides]
            if not all(type(tick) is int for tick in ticks):
                return None
            if floors is not None and not all(tick > floor for tick, floor in zip(ticks, floors)):
                return None
            return ticks
        try:
            return wait_for(current, 's06_tauri_viewport_ticks_unconfirmed_' + stage, timeout=12)
        except GuiFailure:
            if self.output is not None:
                diagnostic = {'stage': stage, 'sides': self.tick_layouts}
                (self.output / 's06-tauri-tick-failure.json').write_text(json.dumps(diagnostic, sort_keys=True))
            raise

    def pause_on_board(self, panels, targets):
        """Click the real return control once and observe the board and both original tabs."""
        trace = {'clickSent': False, 'clickReturned': False, 'before': None, 'after': []}
        endpoint = self.driver.session
        element_key = 'element-6066-11e4-a52e-4f735466cecf'

        def prepare():
            controls = self.driver.call('POST', endpoint + '/elements',
                                        {'using': 'css selector', 'value': '#host-return-home'})
            element = controls[0] if len(controls) == 1 else None
            try:
                sample = self.read(MANUAL_PAUSE_SCRIPT, panels, targets, element)
            except GuiFailure as error:
                if str(error) == 'webdriver_sync_stale_element_reference':
                    return None  # The read is safe to retry. No click was sent.
                raise
            trace['before'] = sample
            return element[element_key] if element and sample['buttonReady'] is True else None

        def observe():
            sample = self.read(MANUAL_PAUSE_SCRIPT, panels, targets, None)
            recent = trace['after']
            if not recent or recent[-1] != sample:
                recent.append(sample)
                if len(recent) > 8:
                    del recent[1]
            return sample

        def paused_on_board():
            sample = observe()
            # The board must really be on screen. The two phases only allow
            # returning to Terminal, where wait_layout verifies the visible pause.
            return (sample['page'] == 'dashboard' and sample['viewCount'] == 2 and
                    sample['phases'] == ['paused', 'paused'])

        try:
            control = wait_for(prepare, 's06_tauri_manual_pause_control_unconfirmed')
            trace['clickSent'] = True
            self.driver.call('POST', endpoint + '/element/' + control + '/click', {})
            trace['clickReturned'] = True
            wait_for(paused_on_board, 's06_tauri_manual_pause_unconfirmed')
        except (GuiFailure, OSError, ValueError):
            if self.output is not None:
                trace['screenshotSaved'] = False
                try:
                    if observe()['safeScreenshot'] is True:
                        self.screenshot('manual-pause-failure')
                        trace['screenshotSaved'] = True
                except (GuiFailure, OSError, ValueError):
                    pass  # Keep the original operation failure.
                (self.output / 's06-tauri-manual-pause-failure.json').write_text(json.dumps(trace, sort_keys=True))
            raise

    def return_to_paused_split(self, panels, targets, focused):
        latest = None

        def terminal():
            nonlocal latest
            latest = self.read_layout(panels)
            return latest if latest['page'] == 'terminal' else None

        def paused():
            layout = terminal()
            if (layout and layout['pairing'] == 'closed' and
                    layout_matches(layout, targets, ('paused', 'paused'), focused)):
                return layout
            return None

        try:
            self.driver.click('#nav-terminal')
            route = wait_for(terminal, 's06_tauri_manual_return_route_unconfirmed')
            if route['pairing'] == 'open':
                self.named('配对与连接资料', '#remote-page #remote-setup', '> summary')
            elif route['pairing'] != 'closed':
                raise GuiFailure('s06_tauri_manual_return_pairing_unproven')
            return wait_for(paused, 's06_tauri_layout_manual_paused')
        except (GuiFailure, OSError, ValueError):
            if self.output is not None:
                self.manual_return_evidence(panels, targets, latest or {})
            raise

    def manual_return_evidence(self, panels, targets, layout):
        def known(value, choices):
            return value if value in choices else 'other'

        phases = ('disconnected', 'connecting', 'starting', 'active', 'pausing', 'paused', 'resuming', 'closed')
        sides = []
        for view, target in zip(layout.get('views', []), targets):
            sides.append(None if view is None else {
                'targetMatches': view.get('target') == list(target),
                'phase': known(view.get('phase'), phases),
                'focused': view.get('focused') is True,
                'currentFrame': view.get('currentFrame') is True,
                'inputControls': view.get('inputControls') is True,
            })
        report = {
            'page': known(layout.get('page'), ('terminal', 'dashboard', 'background')),
            'pairing': known(layout.get('pairing'), ('open', 'closed', 'unproven')),
            'domFocusOwner': known(layout.get('domFocusOwner'), ('none', 'panel-a', 'panel-b', 'outside-panels')),
            'sides': sides,
            'screenshotSaved': False,
        }
        try:
            if self.read(MANUAL_PAUSE_SCRIPT, panels, targets, None)['safeScreenshot'] is True:
                self.screenshot('manual-return-failure')
                report['screenshotSaved'] = True
        except (GuiFailure, OSError, ValueError):
            pass
        (self.output / 's06-tauri-manual-return-failure.json').write_text(json.dumps(report, sort_keys=True))

    def screenshot(self, name):
        # The ordinary pairing form may reopen when returning to the workspace.
        if self.read('return document.querySelector("#remote-setup").open;') is not False:
            raise GuiFailure('s06_tauri_screenshot_form_visible')
        png = base64.b64decode(self.driver.call('GET', self.driver.session + '/screenshot'), validate=True)
        if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 4_194_304:
            raise GuiFailure('s06_tauri_screenshot_invalid')
        (self.output / ('s06-tauri-' + name + '.png')).write_bytes(png)


def exercise_window_resize(ui, panels, targets, approvals, check_bytes):
    # Keep B as the selected input target in stock (read-only) observation.
    # DOM focus is sampled separately because WebDriver may click details.
    active = ('active', 'active')
    paused = ('paused', 'paused')
    narrowed_active = (None, 'active')
    narrowed_paused = (None, 'paused')
    b = 1

    def check_open_peers():
        if any(peer_connection_evidence(approval) != {'authenticationCount': 1, 'closed': False}
               for approval in approvals):
            raise GuiFailure('s06_tauri_resize_did_not_keep_two_original_ssh_connections')
        check_bytes((b'', b''))

    before_window = ui.window(WIDE_WIDTH)
    before = ui.wait_layout(panels, targets, active, b, 'wide_before')
    initial_ticks = ui.ticks(panels, (0, 1), stage='wide_before')
    check_open_peers()
    ui.screenshot('resize-wide-before')

    narrow_window = ui.window(NARROW_WIDTH)
    narrowed = ui.wait_layout(panels, targets, narrowed_active, b, 'narrow_active')
    # The suffix is only shown after the native observation enters Paused.
    wait_for(lambda: ui.read("""return [...document.querySelectorAll('#view-tabs button')].filter(
        e=>e.getAttribute('aria-pressed')==='false' && e.textContent.endsWith(' · 观察已暂停')).length;""") == 1,
        's06_tauri_resize_partner_pause_unconfirmed')
    narrow_tick = ui.ticks(panels, (1,), (initial_ticks[1],), 'narrow_active')[0]
    check_open_peers()
    ui.screenshot('resize-narrow')

    restored_window = ui.window(WIDE_WIDTH)
    if restored_window != before_window:
        raise GuiFailure('s06_tauri_restored_viewport_changed')
    # Native Active on a resumed epoch is emitted after re-binding the original
    # target and receiving the xterm callback for the new full. Compare the
    # visible fixture ticks too, so an old retained canvas is insufficient.
    restored = ui.wait_layout(panels, targets, active, b, 'wide_restored')
    require_same_positions(before, restored)
    restored_ticks = ui.ticks(panels, (0, 1), (initial_ticks[0], narrow_tick), 'wide_restored')
    check_open_peers()
    ui.screenshot('resize-wide-restored')

    # Return to the real home board explicitly to pause both observations,
    # then use the ordinary Terminal navigation to return to their saved tabs.
    ui.pause_on_board(panels, targets)
    ui.return_to_paused_split(panels, targets, b)
    held_ticks = ui.ticks(panels, (0, 1), stage='manual_paused')
    if ui.window(NARROW_WIDTH) != narrow_window:
        raise GuiFailure('s06_tauri_manual_narrow_viewport_changed')
    ui.wait_layout(panels, targets, narrowed_paused, b, 'manual_narrow')
    if ui.window(WIDE_WIDTH) != before_window:
        raise GuiFailure('s06_tauri_manual_wide_viewport_changed')
    manual_wide = ui.wait_layout(panels, targets, paused, b, 'manual_wide')
    require_same_positions(before, manual_wide)
    if ui.ticks(panels, (0, 1), stage='manual_wide') != held_ticks:
        raise GuiFailure('s06_tauri_manual_pause_old_frame_changed')
    check_open_peers()
    ui.screenshot('resize-manual-paused')

    # Focusing the original secondary is distinct from actively resuming it.
    ui.focus(panels[0])
    ui.wait_layout(panels, targets, paused, 0, 'manual_focused')
    ui.named('恢复观察', panels[0] + ' .tab-connection-actions')
    ui.wait_layout(panels, targets, ('active', 'paused'), 0, 'manual_resumed')
    manual_resumed_tick = ui.ticks(panels, (0,), (held_ticks[0],), 'manual_resumed')[0]
    if ui.ticks(panels, (1,), stage='manual_other_paused') != [held_ticks[1]]:
        raise GuiFailure('s06_tauri_manual_resume_woke_other_peer')
    check_open_peers()
    return {'windowRectRoundTrip': True, 'sizes': [before_window, narrow_window, restored_window],
            'panelRectsBeforeAndAfter': [[view['rect'] for view in layout['views']]
                                        for layout in (before, restored)],
            'originalTargetsAndPositions': True, 'originalSelectedInputTargetPreserved': True,
            'domFocusOwnerSamples': [layout['domFocusOwner'] for layout in (before, narrowed, restored)],
            'layoutPauseAcknowledged': True, 'newFullAndAdvancingTicks': True,
            'fixtureTicks': {'wideBefore': initial_ticks, 'narrowPrimary': narrow_tick,
                             'wideRestored': restored_ticks, 'manualPaused': held_ticks,
                             'manualSecondaryAfterResume': manual_resumed_tick},
            'manualPauseEntry': '返回主机看板', 'manualPauseSurvivedRoundTrip': True,
            'manualResumeOnlySelected': True,
            'originalPeerAuthenticationCounts': [1, 1], 'zeroInputBytes': True}


def exercise_direct_resize(ui, panels, targets, approvals, check_bytes):
    before_fields = ('selectedB', 'targetB', 'directB', 'receiptB', 'aObserves')
    retained_fields = ('armed', 'selectedB', 'targetB', 'directB', 'receiptB',
                       'originalEditor', 'originalInputState', 'neverBlurred')
    active = ('active', 'active')
    stage, last, diagnostic = 'wide_before', {}, None

    def safe_focus_sample(sample):
        width = sample.get('width')
        return {'width': width if type(width) is int and 0 < width <= 16384 else None,
                'documentFocused': sample.get('documentFocused') is True}

    def read(action):
        nonlocal last, diagnostic
        result = ui.read(DIRECT_RESIZE_SCRIPT, panels, targets, action)
        if not isinstance(result, dict):
            raise GuiFailure('s06_tauri_direct_resize_observation_invalid')
        last = {key: result.get(key) is True for key in (*retained_fields, 'aObserves', 'aPaused')}
        sample = result.get('diagnostic')
        if isinstance(sample, dict):
            first_blur = sample.get('firstBlur')
            diagnostic = {**safe_focus_sample(sample),
                          **{key: sample.get(key) is True for key in ('singleB', 'wrappedB', 'originalEditorAttached')},
                          'split': sample.get('split') if sample.get('split') in ('1', '2') else None,
                          'actualBMode': sample.get('actualBMode') if sample.get('actualBMode') in
                          ('observe', 'draft', 'direct') else None,
                          'firstBlur': {**safe_focus_sample(first_blur),
                                        'editorAttached': first_blur.get('editorAttached') is True}
                          if isinstance(first_blur, dict) else None}
        return last

    def fields_match(fields, observation):
        return all(observation[key] for key in fields)

    def check_retained(action='sample'):
        current = read(action)
        if not fields_match(retained_fields, current):
            raise GuiFailure('s06_tauri_direct_resize_input_focus_lost_' + stage)
        return current

    def check_original_peer_bytes():
        if any(peer_connection_evidence(approval) != {'authenticationCount': 1, 'closed': False}
               for approval in approvals):
            raise GuiFailure('s06_tauri_direct_resize_peer_changed_' + stage)
        check_bytes((b'', b'b'))

    def wait_layout(phases, *, narrow=False):
        def observed():
            current = check_retained()
            layout = ui.read_layout(panels)
            if ((current['aPaused'] if narrow else current['aObserves']) and
                    layout_matches(layout, targets, phases, 1, guarded=True) and layout.get('domFocusOwner') == 'panel-b'):
                return layout
            return None
        return wait_for(observed, 's06_tauri_direct_resize_layout_' + stage)

    def a_tick(floor=-1):
        def observed():
            check_retained()
            try:
                tick = ui.rendered_tick(panels[0], 0, scroll=False)
            except GuiFailure as error:
                if str(error) != 's06_tauri_visible_peer_marker_missing':
                    raise
                return None  # A rendered row can be empty before the fresh full reaches xterm.
            return tick if type(tick) is int and tick > floor else None
        return wait_for(observed, 's06_tauri_direct_resize_a_tick_' + stage, timeout=12)

    try:
        before_window = ui.wait_window(WIDE_WIDTH)
        wait_for(lambda: fields_match(before_fields, read('sample')), 's06_tauri_direct_resize_not_ready')
        check_retained('arm')
        before = wait_layout(active)
        initial_tick = a_tick()
        check_original_peer_bytes()

        stage = 'narrow'
        narrow_window = ui.window(NARROW_WIDTH)
        narrowed = wait_layout((None, 'active'), narrow=True)
        check_original_peer_bytes()

        stage = 'wide_restored'
        restored_window = ui.window(WIDE_WIDTH)
        if restored_window != before_window:
            raise GuiFailure('s06_tauri_direct_resize_viewport_changed')
        restored = wait_layout(active)
        require_same_positions(before, restored)
        restored_tick = a_tick(initial_tick)
        check_original_peer_bytes()
        check_retained('finish')
    except GuiFailure:
        if ui.output is not None:
            (ui.output / 's06-tauri-direct-resize-failure.json').write_text(
                json.dumps({'stage': stage, 'observation': last, 'diagnostic': diagnostic}, sort_keys=True))
        raise
    return {'windowRectRoundTrip': True, 'sizes': [before_window, narrow_window, restored_window],
            'originalEditorFocusAndInputStatePreserved': True, 'originalTargetAndReceiptPreserved': True,
            'layoutPausedAAndRestoredSameTargetNewFrame': True, 'originalPanelColumnsRestored': True,
            'domFocusOwnerSamples': [layout['domFocusOwner'] for layout in (before, narrowed, restored)],
            'panelRectsBeforeAndAfter': [[view['rect'] for view in layout['views']]
                                        for layout in (before, restored)],
            'aFixtureTicks': [initial_tick, restored_tick], 'originalPeerAuthenticationCounts': [1, 1],
            'peerInputBytesBeforeEscape': [0, 1]}


def exercise_peer_close(ui, panels, approvals):
    report = {'before': None, 'steps': [], 'workspaceHidden': False, 'final': None}

    def finished():
        report['final'] = peer_close_sample(approvals)
        return all(row['authenticationCount'] == 1 and row['recognizedCloseCount'] == 1 and row['resetCount'] == 0
                   for row in report['final'])

    try:
        report['before'] = peer_close_sample(approvals)
        for index, panel in enumerate(panels):
            ui.focus(panel)
            step = {'side': index, 'before': peer_close_sample(approvals), 'attempted': False,
                    'clickReturned': False, 'panelRemoved': False, 'after': None}
            report['steps'].append(step)
            original = step['before'][index]
            if original['authenticationCount'] != 1 or original['recognizedCloseCount'] or original['resetCount']:
                raise GuiFailure('s06_tauri_peer_changed_before_close')
            step['attempted'] = True
            ui.named('关闭此标签', panel + ' .tab-connection-actions')
            step['clickReturned'] = True
            # Await the real UI removal before addressing the remaining panel.
            wait_for(lambda: ui.read('return !document.querySelector(arguments[0]);', panel) is True,
                     's06_tauri_closed_panel_still_present')
            step['panelRemoved'] = True
            step['after'] = peer_close_sample(approvals)
        wait_for(lambda: ui.read('return document.querySelector("#tab-workspace").hidden;') is True,
                 's06_tauri_tabs_not_closed')
        report['workspaceHidden'] = True
        wait_for(finished, 's06_tauri_peer_close_unconfirmed', timeout=12)
        return [row['authenticationCount'] for row in report['final']]
    finally:
        if ui.output is not None:
            if report['final'] is None:
                try:
                    report['final'] = peer_close_sample(approvals)
                except (GuiFailure, OSError):
                    pass
            # Record before WebDriver exit or fixture cleanup can affect the peers.
            (ui.output / 's06-tauri-peer-close.json').write_text(json.dumps(report, sort_keys=True))


def write_import_fixture(root):
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'shared/config-transfer-v1.json').read_text())
    # WebKit's WebDriver key entry drops the supplementary character in the
    # shared vector. Exercise replacement with the same payload and an ASCII password.
    password = os.urandom(16).hex()
    header = b'HPKT\x01\x01' + os.urandom(28)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('ascii'), header[6:22], 600_000)
    encrypted = AESGCM(key).encrypt(header[22:34], fixture['plaintext'].encode('utf-8'), header)
    archive = root / 's06-import-fixture.hpkt'
    archive.write_bytes(header + encrypted)
    return archive, password


def wait_import_survivor_tick(ui, tab_id, *, after=None):
    def observe():
        if after is not None and ui.read('''const panel = document.querySelector("#view-content");
            return panel?.dataset.tabId === arguments[0] &&
                panel.querySelector(".tab-frame-status")?.textContent.startsWith("当前观察画面。");''',
                                        tab_id) is not True:
            return None
        try:
            tick = ui.rendered_tick('#view-content', 1)
        except GuiFailure as error:
            if str(error) != 's06_tauri_visible_peer_marker_missing':
                raise
            return None  # The visible row can briefly be blank while xterm paints the new frame.
        return tick + 1 if tick is not None and (after is None or tick > after) else None

    code = 's06_import_survivor_frame_not_visible' if after is None else 's06_import_survivor_not_advancing'
    return wait_for(observe, code, timeout=12) - 1


def exercise_import_replace(ui, driver, root, approvals, tab_ids, check_bytes, expected):
    """Opt-in real SSH import path using the public configuration fixture."""
    def sample():
        return [{key: row[key] for key in ('authenticationCount','recognizedCloseCount','resetCount')}
                for row in peer_close_sample(approvals)]
    open_peer = {'authenticationCount':1,'recognizedCloseCount':0,'resetCount':0}
    closed_peer = {'authenticationCount':1,'recognizedCloseCount':1,'resetCount':0}
    archive, password = write_import_fixture(root)
    driver.click('#workbench-split')
    if ui.read('return document.querySelector("#remote-setup").open;'):
        ui.named('配对与连接资料', '#remote-page #remote-setup', '> summary')
    driver.click('#host-return-home')
    wait_for(lambda: ui.read('return !document.querySelector("#home-dashboard").hidden;'), 's06_import_board_missing')
    driver.click('#nav-settings'); driver.click('#config-transfer-open')
    field = '#config-transfer input[type="file"]'
    wait_for(lambda: ui.read('return !!document.querySelector(arguments[0]);', field), 's06_import_file_missing')
    path = driver.element(field)
    driver.call('POST', path + '/value', {'text':str(archive), 'value':list(str(archive))})
    driver.fill('#config-transfer > fieldset:nth-of-type(2) input[type="password"]', password)
    ui.named('解密并预览', '#config-transfer')
    wait_for(lambda: ui.read('return !!document.querySelector(".config-preview");'), 's06_import_preview_missing')
    driver.click('input[name="config-choice-0"][value="replace"]')
    ui.screenshot('import-preview')
    peer_before = sample()
    if peer_before != [open_peer] * 2:
        raise GuiFailure('s06_import_peers_not_open_before_apply')
    ui.named('确认应用所选操作', '.config-preview')
    wait_for(lambda: '导入完成' in driver.read('#config-transfer [role="status"]'), 's06_import_apply_unconfirmed', timeout=20)
    wait_for(lambda: sample()[0] == closed_peer,
             's06_import_peer_a_not_closed', timeout=12)
    after_apply = sample()
    if after_apply != [closed_peer, open_peer]:
        raise GuiFailure('s06_import_peer_b_changed')
    ui.named('关闭', '#config-transfer'); driver.click('#nav-terminal')
    if ui.read('return document.querySelector("#remote-setup").open;'):
        ui.named('配对与连接资料', '#remote-page #remote-setup', '> summary')
    driver.click('#view-tabs button:nth-child(1)')
    wait_for(lambda: ui.read('return document.querySelector("#view-content")?.dataset.tabId;') == tab_ids[0],
             's06_import_old_tab_missing')
    old_tick = wait_for(lambda: (value + 1) if (value := ui.rendered_tick('#view-content', 0)) is not None else None,
                        's06_import_old_frame_not_visible', timeout=12) - 1
    if not ui.read('return [...document.querySelectorAll("#view-content button")].find(b=>b.textContent==="连接")?.disabled === true;'):
        raise GuiFailure('s06_import_old_connect_enabled')
    ui.screenshot('import-old-retained')
    ui.named('关闭此标签', '#view-content')
    wait_for(lambda: ui.read('return document.querySelectorAll("#view-tabs button").length;') == 1,
             's06_import_old_tab_not_closed')
    after_old_close = sample()
    if after_old_close != after_apply:
        raise GuiFailure('s06_import_peer_b_closed_with_a')
    driver.click('#view-tabs button:nth-child(1)')
    wait_for(lambda: ui.read('return document.querySelector("#view-content")?.dataset.tabId;') == tab_ids[1],
             's06_import_survivor_missing')
    before = wait_import_survivor_tick(ui, tab_ids[1])
    ui.named('恢复观察', '#view-content')
    after = wait_import_survivor_tick(ui, tab_ids[1], after=before)
    if sample() != [closed_peer, open_peer]:
        raise GuiFailure('s06_import_survivor_reconnected')
    ui.screenshot('import-survivor-advanced');check_bytes(expected)
    before_survivor_close = sample()
    if before_survivor_close != [closed_peer, open_peer]:
        raise GuiFailure('s06_import_survivor_changed_before_close')
    ui.named('关闭此标签', '#view-content')
    def final_sample():
        final = sample()
        return final if final == [closed_peer] * 2 else None
    final = wait_for(final_sample, 's06_import_peers_not_closed', timeout=12)
    evidence = {'realFileImport':True,'oldFrameRetained':True,'oldConnectDisabled':True,
            'oldTabManuallyClosed':True,'survivorAdvancedOnOriginalConnection':True,
            'peersClosedBeforeDriverExit':True, 'oldVisibleTick':old_tick,
            'survivorVisibleTicks':{'beforeResume':before,'afterResume':after},
            'peerSamples':{'beforeApply':peer_before,'afterApply':after_apply,
                           'afterOldTabClose':after_old_close,'beforeSurvivorClose':before_survivor_close,
                           'afterSurvivorClose':final}}
    (ui.output / 's06-tauri-import-replace.json').write_text(json.dumps(evidence, sort_keys=True))
    return evidence


def exercise(args, root, env, configs, approvals, expected):
    driver, stage = WebDriver(), 'prepare_display'
    ui = SplitDriver(driver, args.output)
    guarded = bool(args.input_fixture)
    import_replace = os.environ.get('HERDR_S06_IMPORT_REPLACE') == '1'
    if import_replace and guarded: raise GuiFailure('s06_import_requires_stock')
    other = root / 's06-peer-b'

    def check_bytes(data):
        for directory, value in zip((root, other), data):
            if bounded_wire(directory / 'received.bin', 4096) != value:
                raise GuiFailure('s06_tauri_remote_bytes_changed')

    try:
        pointer = park_xvfb_pointer(os.environ) if guarded else nullcontext(False)
        with pointer as parked, owned_process(['tauri-driver'], cwd=root, env=env, log=root / 's06-tauri-driver.log'):
            if guarded:
                (args.output / 's06-tauri-xvfb-pointer.json').write_text(json.dumps({'parkedBeforeLaunch': parked}))
            stage = 'start'
            try:
                driver.start(args.tauri_app)
                rect = driver.call('POST', driver.session + '/window/rect', {'width': 1440, 'height': 1200})
                if rect.get('width') != 1440 or rect.get('height') != 1200:
                    raise GuiFailure('s06_tauri_window_size_unconfirmed')
                if ui.read('return window.innerWidth;') < 1300:
                    raise GuiFailure('s06_tauri_viewport_not_wide')
                # Create and review both native identities before opening views.
                # Only these two independently approved keys may authenticate.
                host_ids = []
                for index, (config, approval) in enumerate(zip(configs, approvals)):
                    stage = 'pair_' + str(index)
                    ui.open_pairing(empty_board=index == 0)
                    for field, key in [('host', 'host'), ('port', 'port'), ('user', 'username'),
                            ('session', 'session'), ('herdr', 'herdrPath'), ('socket', 'socketPath'), ('pin', 'expectedHostKey')]:
                        driver.fill('#remote-' + field, config[key])
                    if import_replace and index == 0: driver.fill('#host-save-name', '测试主机')
                    driver.click('#pair-mode'); driver.click('#pair-target-review'); driver.click('#pair-create')
                    request = wait_for(lambda: driver.read('#pair-request', 'value'), 's06_tauri_pair_request_missing')
                    response = approval.approve(request.encode())
                    public_lines = b''.join(bounded_wire(a.host.home / '.ssh' / 'authorized_keys', 4096)
                                            for a in approvals if a.applied)
                    approval.replace_authorization(public_lines)
                    driver.fill('#pair-response', response.decode())
                    driver.click('#pair-preview'); driver.click('#pair-source-review'); driver.click('#pair-accept')
                    wait_for(lambda: '授权响应已审查' in driver.read('#pair-status'), 's06_tauri_pair_review_missing')
                    driver.click('#host-return-home')
                    host_id = wait_for(lambda: ui.read('''return [...document.querySelectorAll('#host-list .saved-host-card')]
                        .find(e=>e.innerText.includes('会话 '+arguments[0]))?.dataset.hostId;''', config['session']),
                        's06_tauri_saved_host_missing')
                    if not isinstance(host_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', host_id):
                        raise GuiFailure('s06_tauri_saved_host_id_invalid')
                    host_ids.append(host_id)
                if host_ids[0] == host_ids[1]:
                    raise GuiFailure('s06_tauri_saved_targets_collided')
                tab_ids = []
                for index, host_id in enumerate(host_ids):
                    stage = 'tab_' + str(index)
                    card = '#host-list .saved-host-card[data-host-id="' + host_id + '"]'
                    ui.named('管理', card, 'summary'); ui.named('新终端标签', card)
                    def created():
                        value = ui.read('return document.querySelector("#view-content")?.dataset.tabId;')
                        return value if value and value not in tab_ids else None
                    tab_id = wait_for(created, 's06_tauri_new_tab_missing')
                    if not isinstance(tab_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', tab_id):
                        raise GuiFailure('s06_tauri_tab_id_invalid')
                    tab_ids.append(tab_id)
                    if index == 0:
                        driver.click('#host-return-home')
                stage = 'split'
                driver.click('#workbench-split')
                wait_for(lambda: ui.read('return document.querySelector("#view-content").dataset.split;') == '2',
                         's06_tauri_split_not_opened')
                panels = ['[data-role="workbench-panel"][data-tab-id="' + tab + '"]' for tab in tab_ids]
                geometry = ui.read('''return arguments[0].map(selector=>{const r=document.querySelector(selector).getBoundingClientRect();
                    return Object.fromEntries(['left','right','top','width','height'].map(k=>[k,Math.round(r[k])]));});''', panels)
                (args.output / 's06-tauri-panel-geometry.json').write_text(json.dumps(geometry))
                require_side_by_side(geometry)
                targets = []
                for index, panel in enumerate(panels):
                    stage = 'connect_' + str(index)
                    ui.focus(panel)
                    driver.click(panel + ' input[type="checkbox"]')
                    ui.named('连接', panel + ' .tab-connection-actions')
                    pane = panel + ' button[data-pane-id="' + configs[index]['paneId'] + '"]'
                    driver.wait_control(pane)
                    displayed_terminal = driver.attribute(pane, 'data-terminal-id')
                    terminal = fixture_terminal_id(configs[index])
                    if displayed_terminal != terminal:
                        raise GuiFailure('s06_tauri_live_target_mismatch')
                    targets.append((configs[index]['paneId'], terminal))
                    driver.click(pane)
                    driver.wait_control(panel + ' .terminal-select-button')
                stage = 'visible_frames'
                ticks = []
                for index, panel in enumerate(panels):
                    first = ui.snapshot_tick(panel, index)
                    def advanced():
                        second = ui.snapshot_tick(panel, index)
                        return second if second > first else None
                    second = wait_for(advanced, 's06_tauri_peer_frame_not_advancing', timeout=12)
                    ticks.append([first, second])
                ui.focus(panels[1])
                check_bytes((b'', b''))
                if not guarded and any(ui.read('return !!document.querySelector(arguments[0]+" .tab-mobile-controls");', panel)
                                       for panel in panels):
                    raise GuiFailure('s06_tauri_stock_input_controls_unexpected')
                # Screenshot only the controlled, credential-free paired workspace.
                if not ui.visible_frames(panels):
                    ui.failure_screenshot('both')
                    raise GuiFailure('s06_tauri_both_frames_not_visible')
                ui.screenshot('connected')
                stage = 'input_focus'
                direct_resize_evidence = None
                if guarded:
                    ui.first_direct_key(panels, targets, (root / 'received.bin', other / 'received.bin'))
                    stage = 'direct_resize'
                    direct_resize_evidence = exercise_direct_resize(ui, panels, targets, approvals, check_bytes)
                    (args.output / 's06-tauri-direct-resize.json').write_text(json.dumps(direct_resize_evidence, sort_keys=True))
                    stage = 'direct_escape'
                    escape_observation = ui.escape_direct_input(panels, targets)
                    if any(peer_connection_evidence(approval) != {'authenticationCount': 1, 'closed': False}
                           for approval in approvals):
                        raise GuiFailure('s06_tauri_direct_escape_peer_changed')
                    check_bytes((b'', b'b'))
                    (args.output / 's06-tauri-direct-escape.json').write_text(json.dumps(
                        {'observation': escape_observation, 'originalPeersPreserved': True, 'noExtraInputBytes': True},
                        sort_keys=True))
                    stage = 'input_focus'
                ui.focus(panels[0])
                driver.click(panels[1] + ' .terminal-host')
                ui.keyboard('x')  # Late key on the old panel, without selecting its header.
                time.sleep(.25)
                check_bytes((b'', expected[1]))
                if guarded:
                    ui.focus(panels[0]); ui.named('启用草稿输入', panels[0] + ' .tab-mode-actions')
                    wait_for(lambda: ui.read('return document.querySelector(arguments[0]+" .tab-mobile-controls")?.dataset.mode;', panels[0]) == 'draft',
                             's06_tauri_draft_mode_not_ready')
                    driver.fill(panels[0] + ' .tab-draft-field', 'Pocket测')
                    ui.named('发送草稿', panels[0] + ' .tab-mode-actions')
                    alert = driver.call('GET', driver.session + '/alert/text')
                    if not isinstance(alert, str) or 'Pocket测' not in alert or '9 字节' not in alert:
                        raise GuiFailure('s06_tauri_draft_preview_mismatch')
                    driver.call('POST', driver.session + '/alert/accept', {})
                    wait_for(lambda: bounded_wire(root / 'received.bin', 4096) == expected[0], 's06_tauri_draft_input_missing')
                ui.focus(panels[1])
                if guarded and ui.read('return document.querySelector(arguments[0]+" .tab-mobile-controls")?.dataset.mode;', panels[1]) != 'observe':
                    raise GuiFailure('s06_tauri_input_mode_restored_automatically')
                driver.click(panels[0] + ' .terminal-host'); ui.keyboard('y')
                driver.click(panels[1] + ' .terminal-host'); ui.keyboard('z')
                time.sleep(.25); check_bytes(expected)
                resize_evidence = None
                if not guarded:
                    stage = 'window_resize'
                    targets = [(config['paneId'], fixture_terminal_id(config)) for config in configs]
                    resize_evidence = exercise_window_resize(ui, panels, targets, approvals, check_bytes)
                stage = 'import_replace' if import_replace else 'close'
                import_evidence = exercise_import_replace(ui, driver, root, approvals, tab_ids, check_bytes, expected) if import_replace else None
                peer_authentication_counts = ([peer['authenticationCount'] for peer in import_evidence['peerSamples']['afterSurvivorClose']]
                                              if import_replace else exercise_peer_close(ui, panels, approvals))
                check_bytes(expected)
                return {**{key: True for key in ('normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
                    'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus', 'focusDoesNotRestoreInput',
                    'lateInputRejected', 'stoppedBoth')},
                    'sides': [{'visibleFrameSnapshots': 2, 'tickAdvanced': second > first, 'inputAccepted': guarded}
                              for first, second in ticks],
                    'peerAuthenticationCounts': peer_authentication_counts,
                    'peersClosedBeforeDriverExit': True, 'frameEvidence': 'public visible-terminal-text UI snapshots; native WebDriver actions',
                    **({'importReplace': import_evidence} if import_evidence is not None else {}),
                    **({'guardedDirectEscape': {'trustedChordConsumed': True, 'domFocusMovedToA': True,
                        'selectedTargetStayedB': True, 'originalTargetsAndPeersPreserved': True,
                        'readOnlyAfterEscape': True, 'noExtraInputBytes': True}} if guarded else {}),
                    **({'guardedDirectResize': direct_resize_evidence} if direct_resize_evidence is not None else {}),
                    **({'windowResize': resize_evidence} if resize_evidence is not None else {})}
            except GuiFailure:
                if stage in ('pair_0', 'pair_1', 'import_replace'):
                    ui.entry_failure(stage)
                raise
            finally:
                driver.close()
    except GuiFailure as error:
        raise GuiFailure('s06_tauri_' + stage + '_' + str(error)) from None
