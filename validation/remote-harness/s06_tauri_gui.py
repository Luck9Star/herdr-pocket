"""Native GTK S06 driver. Reuses WebDriver and the reviewed two-peer fixture."""
import base64
import json
import re
import time

from paired_gui import WebDriver, GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for


WINDOW_HEIGHT = 1200
WIDE_WIDTH = 1440
NARROW_WIDTH = 700

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
if(!hit(initial) || initial.clearance<24)
    row.scrollIntoView({block:'center',inline:'start',behavior:'instant'});
const final=measure();
const focusPreserved=document.activeElement===focus && panel.dataset.focus===selected;
return {text:focusPreserved && hit(final) ? row.textContent.replace(/\u00a0/g,' ').trim() : null,
    layout:{reason:!focusPreserved?'focus-changed':hit(final)?'row-hit':'row-clipped',initial,final}};
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
        one(view, ':scope > p:not([data-role])')?.textContent.split(' · ').slice(-2)
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


def layout_matches(layout, targets, phases, focused):
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
              view.get('currentFrame') is not (phase == 'active') or view.get('inputControls') is not False):
            return False
    return True


def require_same_positions(before, after):
    for layout in (before, after):
        require_side_by_side([view.get('rect') for view in layout['views']])
    for original, restored in zip(before['views'], after['views']):
        if any(abs(original['rect'][key] - restored['rect'][key]) > 1 for key in ('left', 'right', 'width')):
            raise GuiFailure('s06_tauri_split_position_changed')


def peer_connection_evidence(approval):
    """Match only this reviewed key's loopback SSH connection and peer close."""
    text = bounded_wire(approval.root / 'sshd.log', 2_097_152).decode(errors='replace')
    pattern = (r'Accepted publickey for ' + re.escape(approval.config['username']) +
               r' from 127\.0\.0\.1 port ([0-9]+) ssh2: ED25519 ' +
               re.escape(approval.fingerprint or '') + r'(?:\s|$)')
    accepted = list(re.finditer(pattern, text))
    closed = True
    for match in accepted:
        port = re.escape(match[1])
        closing = (r'(?:Received disconnect from 127\.0\.0\.1 port ' + port +
                   r':|Disconnected from user [^\n]+ 127\.0\.0\.1 port ' + port +
                   r'(?:\s|$)|Connection closed by (?:user [^\n]+ )?127\.0\.0\.1 port ' + port + r'(?:\s|$))')
        closed = closed and re.search(closing, text[match.end():]) is not None
    return {'authenticationCount': len(accepted), 'closed': bool(accepted) and closed}


class SplitDriver:
    def __init__(self, driver, output=None):
        self.driver = driver
        self.output = output
        self.tick_layouts = {}

    def read(self, script, *args):
        return self.driver.call('POST', self.driver.session + '/execute/sync', {'script': script, 'args': list(args)})

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

    def escape_direct_input(self, panels, targets):
        before = ('originalTargetsActive', 'selectedB', 'directXterm', 'bReceiptMatched', 'aFocusButtonReady')

        def ready(arm=False):
            evidence = self.read(DIRECT_EXIT_SCRIPT, panels, targets, arm)
            return (isinstance(evidence, dict) and all(evidence.get(key) is True for key in before) and
                    (not arm or evidence.get('armed') is True))

        def escaped():
            evidence = self.read(DIRECT_EXIT_SCRIPT, panels, targets, False)
            return (isinstance(evidence, dict) and type(evidence.get('keyCount')) is int and
                    evidence['keyCount'] == 1 and all(evidence.get(key) is True for key in (
                        'originalTargetsActive', 'selectedB', 'aFocusButtonFocused',
                        'bothReadOnly', 'trustedConsumedChord')))

        # The independent peer has received b. Wait for the matching local
        # receipt as well, so this exit cannot interrupt an in-flight send.
        wait_for(ready, 's06_tauri_direct_escape_not_ready')
        if not ready(arm=True):
            raise GuiFailure('s06_tauri_direct_escape_not_armed')
        # W3C WebDriver key values for F6, Control and Shift. Send exactly once.
        self.keyboard('\ue036', modifiers=('\ue009', '\ue008'))
        wait_for(escaped, 's06_tauri_direct_escape_unconfirmed')

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

    def rendered_tick(self, panel, side):
        sample = self.read(TICK_ROW_SCRIPT, panel)
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


def exercise(args, root, env, configs, approvals, expected):
    driver, stage = WebDriver(), 'start'
    ui = SplitDriver(driver, args.output)
    guarded = bool(args.input_fixture)
    other = root / 's06-peer-b'

    def check_bytes(data):
        for directory, value in zip((root, other), data):
            if bounded_wire(directory / 'received.bin', 4096) != value:
                raise GuiFailure('s06_tauri_remote_bytes_changed')

    try:
        with owned_process(['tauri-driver'], cwd=root, env=env, log=root / 's06-tauri-driver.log'):
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
                    driver.click('#host-open-remote')
                    driver.click('#add-herdr')
                    for field, key in [('host', 'host'), ('port', 'port'), ('user', 'username'),
                            ('session', 'session'), ('herdr', 'herdrPath'), ('socket', 'socketPath'), ('pin', 'expectedHostKey')]:
                        driver.fill('#remote-' + field, config[key])
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
                if guarded:
                    ui.named('逐键输入', panels[1] + ' .tab-mode-actions')
                    wait_for(lambda: ui.read('return document.querySelector(arguments[0]+" .tab-mobile-controls")?.dataset.mode;', panels[1]) == 'direct',
                             's06_tauri_direct_mode_not_ready')
                    ui.keyboard('b')
                    wait_for(lambda: bounded_wire(other / 'received.bin', 4096) == b'b', 's06_tauri_direct_input_missing')
                    stage = 'direct_escape'
                    ui.escape_direct_input(panels, targets)
                    if any(peer_connection_evidence(approval) != {'authenticationCount': 1, 'closed': False}
                           for approval in approvals):
                        raise GuiFailure('s06_tauri_direct_escape_peer_changed')
                    check_bytes((b'', b'b'))
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
                stage = 'close'
                for panel in panels:
                    ui.focus(panel); ui.named('关闭此标签', panel + ' .tab-connection-actions')
                    # The click starts an async cancel. Wait for that real tab
                    # to disappear before addressing the remaining single view;
                    # its split-only focus header is intentionally gone then.
                    wait_for(lambda: ui.read('return !document.querySelector(arguments[0]);', panel) is True,
                             's06_tauri_closed_panel_still_present')
                wait_for(lambda: ui.read('return document.querySelector("#tab-workspace").hidden;') is True,
                         's06_tauri_tabs_not_closed')
                wait_for(lambda: all(peer_connection_evidence(a) == {'authenticationCount': 1, 'closed': True}
                                     for a in approvals), 's06_tauri_peer_close_unconfirmed', timeout=12)
                check_bytes(expected)
                return {**{key: True for key in ('normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
                    'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus', 'focusDoesNotRestoreInput',
                    'lateInputRejected', 'stoppedBoth')},
                    'sides': [{'visibleFrameSnapshots': 2, 'tickAdvanced': second > first, 'inputAccepted': guarded}
                              for first, second in ticks],
                    'peerAuthenticationCounts': [peer_connection_evidence(a)['authenticationCount'] for a in approvals],
                    'peersClosedBeforeDriverExit': True, 'frameEvidence': 'public visible-terminal-text UI snapshots; native WebDriver actions',
                    **({'guardedDirectEscape': {'trustedChordConsumed': True, 'domFocusMovedToA': True,
                        'selectedTargetStayedB': True, 'originalTargetsAndPeersPreserved': True,
                        'readOnlyAfterEscape': True, 'noExtraInputBytes': True}} if guarded else {}),
                    **({'windowResize': resize_evidence} if resize_evidence is not None else {})}
            finally:
                driver.close()
    except GuiFailure as error:
        raise GuiFailure('s06_tauri_' + stage + '_' + str(error)) from None
