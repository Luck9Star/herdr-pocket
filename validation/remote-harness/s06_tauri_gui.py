"""Native GTK S06 driver. Reuses WebDriver and the reviewed two-peer fixture."""
import base64
import json
import re
import time

from paired_gui import WebDriver, GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for


WINDOW_HEIGHT = 1200
WIDE_WIDTH = 1440
NARROW_WIDTH = 700


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

    def keyboard(self, text):
        actions = []
        for char in text:
            actions.extend([{'type': 'keyDown', 'value': char}, {'type': 'keyUp', 'value': char}])
        self.driver.call('POST', self.driver.session + '/actions', {'actions': [
            {'type': 'key', 'id': 's06-native-keyboard', 'actions': actions}]})

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
            const views=arguments[0].map(selector=>{
                const panel=document.querySelector(selector);
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
            return {views,split:root?.dataset.split,
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
        # Read a hit-testable rendered row without moving the application's input focus.
        text = self.read(r"""
            const host=document.querySelector(arguments[0]+' .terminal-host');
            const screen=host?.querySelector('.xterm-screen'), row=screen?.querySelector('.xterm-rows')?.children[22];
            if(!row || !row.getClientRects().length)return null;
            const r=screen.getBoundingClientRect();
            const y=r.top+22.5*r.height/24;
            if(![0,10,29].every(col=>{
                const x=r.left+(col+.5)*r.width/80;
                const hit=document.elementFromPoint(x,y);
                return x>=0&&x<innerWidth&&y>=0&&y<innerHeight&&!!hit&&host.contains(hit);
            }))return null;
            return row.textContent.replace(/\u00a0/g,' ').trim() || null;
        """, panel)
        return observed_tick(text, side) if text is not None else None

    def ticks(self, panels, sides, floors=None):
        for side in sides:
            self.collapse_details(panels[side])
        self.driver.wait_control(panels[sides[0]] + ' .term-scroll')

        def current():
            ticks = [self.rendered_tick(panels[side], side) for side in sides]
            if not all(type(tick) is int for tick in ticks):
                return None
            if floors is not None and not all(tick > floor for tick, floor in zip(ticks, floors)):
                return None
            return ticks
        return wait_for(current, 's06_tauri_viewport_ticks_unconfirmed', timeout=12)

    def screenshot(self, name):
        # The ordinary pairing form may reopen when returning to the workspace.
        if self.read('return document.querySelector("#remote-setup").open;') is not False:
            raise GuiFailure('s06_tauri_screenshot_form_visible')
        png = base64.b64decode(self.driver.call('GET', self.driver.session + '/screenshot'), validate=True)
        if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 4_194_304:
            raise GuiFailure('s06_tauri_screenshot_invalid')
        (self.output / ('s06-tauri-' + name + '.png')).write_bytes(png)


def exercise_window_resize(ui, panels, targets, approvals, check_bytes):
    # Existing S06 left B focused. Keep it so through the automatic cycle.
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
    initial_ticks = ui.ticks(panels, (0, 1))
    check_open_peers()
    ui.screenshot('resize-wide-before')

    narrow_window = ui.window(NARROW_WIDTH)
    ui.wait_layout(panels, targets, narrowed_active, b, 'narrow_active')
    # The suffix is only shown after the native observation enters Paused.
    wait_for(lambda: ui.read("""return [...document.querySelectorAll('#view-tabs button')].filter(
        e=>e.getAttribute('aria-pressed')==='false' && e.textContent.endsWith(' · 观察已暂停')).length;""") == 1,
        's06_tauri_resize_partner_pause_unconfirmed')
    narrow_tick = ui.ticks(panels, (1,), (initial_ticks[1],))[0]
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
    restored_ticks = ui.ticks(panels, (0, 1), (initial_ticks[0], narrow_tick))
    check_open_peers()
    ui.screenshot('resize-wide-restored')

    # Return to the real home board explicitly to pause both observations,
    # then use the ordinary Terminal navigation to return to their saved tabs.
    ui.driver.click('#host-return-home')
    wait_for(lambda: ui.read("""const a=document.querySelectorAll('#view-content .tab-connection-actions');
        return a.length===2 && [...a].every(e=>e.dataset.state==='paused');""") is True,
        's06_tauri_manual_pause_unconfirmed')
    ui.driver.click('#nav-terminal')
    if ui.read('return document.querySelector("#remote-setup").open;') is True:
        ui.named('配对与连接资料', '#remote-setup', 'summary')
    ui.wait_layout(panels, targets, paused, b, 'manual_paused')
    held_ticks = ui.ticks(panels, (0, 1))
    if ui.window(NARROW_WIDTH) != narrow_window:
        raise GuiFailure('s06_tauri_manual_narrow_viewport_changed')
    ui.wait_layout(panels, targets, narrowed_paused, b, 'manual_narrow')
    if ui.window(WIDE_WIDTH) != before_window:
        raise GuiFailure('s06_tauri_manual_wide_viewport_changed')
    manual_wide = ui.wait_layout(panels, targets, paused, b, 'manual_wide')
    require_same_positions(before, manual_wide)
    if ui.ticks(panels, (0, 1)) != held_ticks:
        raise GuiFailure('s06_tauri_manual_pause_old_frame_changed')
    check_open_peers()
    ui.screenshot('resize-manual-paused')

    # Focusing the original secondary is distinct from actively resuming it.
    ui.focus(panels[0])
    ui.wait_layout(panels, targets, paused, 0, 'manual_focused')
    ui.named('恢复观察', panels[0] + ' .tab-connection-actions')
    ui.wait_layout(panels, targets, ('active', 'paused'), 0, 'manual_resumed')
    manual_resumed_tick = ui.ticks(panels, (0,), (held_ticks[0],))[0]
    if ui.ticks(panels, (1,)) != [held_ticks[1]]:
        raise GuiFailure('s06_tauri_manual_resume_woke_other_peer')
    check_open_peers()
    return {'windowRectRoundTrip': True, 'sizes': [before_window, narrow_window, restored_window],
            'panelRectsBeforeAndAfter': [[view['rect'] for view in layout['views']]
                                        for layout in (before, restored)],
            'originalTargetsAndPositions': True, 'originalFocus': True,
            'layoutPauseAcknowledged': True, 'newFullAndAdvancingTicks': True,
            'fixtureTicks': {'wideBefore': initial_ticks, 'narrowPrimary': narrow_tick,
                             'wideRestored': restored_ticks, 'manualPaused': held_ticks,
                             'manualSecondaryAfterResume': manual_resumed_tick},
            'manualPauseSurvivedRoundTrip': True, 'manualResumeOnlySelected': True,
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
                for index, panel in enumerate(panels):
                    stage = 'connect_' + str(index)
                    ui.focus(panel)
                    driver.click(panel + ' input[type="checkbox"]')
                    ui.named('连接', panel + ' .tab-connection-actions')
                    pane = panel + ' button[data-pane-id="' + configs[index]['paneId'] + '"]'
                    driver.wait_control(pane)
                    if driver.attribute(pane, 'data-terminal-id') != fixture_terminal_id(configs[index]):
                        raise GuiFailure('s06_tauri_live_target_mismatch')
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
                    **({'windowResize': resize_evidence} if resize_evidence is not None else {})}
            finally:
                driver.close()
    except GuiFailure as error:
        raise GuiFailure('s06_tauri_' + stage + '_' + str(error)) from None
