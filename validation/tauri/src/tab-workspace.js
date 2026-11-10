import {ConnectionDiagnostics,connectionDiagnosticIdentity,connectionStageText,createConnectionDiagnosticsView} from './connection-diagnostics.js';
import {canvasPresets,parseCanvas} from './observe-canvas.js';
import {createTerminalSelection} from './terminal-selection.js';
import {createFontDiagnostics} from './terminal-font-diagnostics.js';
import {RemoteTabs} from './remote-tabs.js';
import {RemoteFrameQueue,validDashboard} from './remote-state.js';
import {SessionDashboard} from './dashboard-watch.js';
import {matchedReceipt} from './input-receipt.js';
import {OnlineInputQueue} from './online-input-queue.js';
import {InputComposition,blockPendingKeys} from './input-composition.js';
import {draftBytes} from './input-codec.js';
import {applyPaste,previewPaste} from './paste-review.js';
import {readClipboardForPaste,clipboardPasteMessage} from './mobile-clipboard.js';
import {createTabInputToolbar} from './tab-input-toolbar.js';
import {requestMobileKeyboard} from './mobile-soft-keyboard.js';
import {dashboardPresentation,paneStatusText} from './dashboard-presentation.js';
import {LocalTerminalViewport,terminalViewportIdentity} from './local-terminal-viewport.js';
import {observationError} from './observation-error.js';
import {hostSummaryIdentity} from './host-dashboard-summary.js';

/** A foreground tab owns its native attempt and renderer. No reconnect is automatic.
 *  桌面分屏（切片 2）：≥900px 且≥2 标签时可双面板同观——后端 visible 是集合语义，仅 focus 独占；
 *  切换焦点沿用 gate.js 的 focusRevision 语义（旧面板租约立即失效）；分屏绝不 resize 远端画布。 */
export function initTabWorkspace({native,invoke,theme,hostName,hostInfo=()=>null,getFontSize=()=>14,channelFactory,terminalFactory,onDashboard=()=>{},clipboardRead=readClipboardForPaste,keyboardRequest=requestMobileKeyboard}) {
  const tabs=new RemoteTabs(), root=document.getElementById('tab-workspace');
  const nav=document.getElementById('view-tabs'), body=document.getElementById('view-content');
  let switching=false, textSelection=null, fontDiagnostics=null, mountedTabs=[];
  // 桌面分屏（切片 2）：splitOn 只是本地布局意图；能否真的双面板由窗口宽度与标签数共同决定。
  // 分屏绝不发送 PTY resize——每个面板沿用自己连接时选定的观察画布（docs/05:137；transport 层已断言观察不含 resize）。
  let splitOn=false, splitPartnerId=null, lastWide=globalThis.window?.innerWidth>=900;
  const splitButton=document.getElementById('workbench-split');
  function isWide(){const width=globalThis.window?.innerWidth;return typeof width==='number' && width>=900;}
  function splitPartner(){if(!splitOn || !isWide())return null;const tab=tabs.get(splitPartnerId);return tab && tab.id!==tabs.activeId ? tab : null;}
  // 面板身份标记：单面板（未分屏）时 #view-content 自身就是唯一面板，标记挂在它身上；
  // 真分屏时标记只存在于各自的 section 包装层上。
  function markSinglePanel(tab){body.dataset.role='workbench-panel';body.dataset.tabId=tab.id;body.dataset.focus='true';}
  function clearPanelMark(){delete body.dataset.role;delete body.dataset.tabId;delete body.dataset.focus;}
  function boardEvent(tab,type) {if(tab.summaryIdentity && tab.token)onDashboard({type,hostId:tab.hostId,identity:tab.summaryIdentity,source:tab.token,board:tab.board});}
  function status(tab,message) {tab.message=message;tab.diagnosticView?.update(tab.diagnostics);if(tabs.activeId===tab.id || splitPartner()===tab)render();}
  function inputModeMessage(tab) {
    if(tab.unknown)return '输入结果待核实；输入已锁定。';
    if(tab.state!=='active')return '观察未运行；输入已关闭。';
    if(tab.inputEpoch!==null && tab.mode==='direct')return '逐键输入已启用；每次输入单独发送。';
    if(tab.inputEpoch!==null && tab.mode==='draft')return '草稿输入已启用；仅在核对并确认后发送。';
    return '观察模式；输入已关闭。';
  }
  function updateInputMode(tab) {const message=inputModeMessage(tab);if(tab.inputModeElement && tab.inputModeElement.textContent!==message)tab.inputModeElement.textContent=message;}
  function lease(tab) {return {token:tab.token,generation:tab.nativeGeneration,epoch:tab.epoch,revision:tab.inputRevision};}
  function sameLease(tab,old) {return current(tab,old.token) && tab.nativeGeneration===old.generation && tab.epoch===old.epoch && tab.inputRevision===old.revision;}
  function current(tab,token) {return tabs.get(tab.id)===tab && tabs.accepts(token);}
  function blockedMatches(tab,pane=tab.blockedIntent) {
    const intent=tab.blockedIntent;
    return !!intent && hostSummaryIdentity(hostInfo(tab.hostId))===intent.identity &&
      pane?.paneId===intent.paneId && pane?.terminalId===intent.terminalId &&
      tab.board.selectable && tab.board.panes.some(p=>p.paneId===intent.paneId && p.terminalId===intent.terminalId && p.agentStatus==='blocked');
  }
  function recheckBlocked(tab) {
    if(!tab.blockedIntent || tab.blockedVerified || !tab.board.selectable || tab.blockedFailed)return;
    if(!blockedMatches(tab)) {tab.blockedFailed=true;tab.message='原目标已不再明确受阻、已替换或资料已变化；没有接入观察，请返回清单重新核查。';void cancel(tab);return;}
    if(tab.selectionReady && !tab.selecting && !Number.isSafeInteger(tab.blockedSelectionRevision))void choosePane(tab,tab.blockedIntent,tab.board.epoch,tab.board.revision,tab.token);
  }
  function canChoose(tab,pane,epoch,revision,reviewToken) {
    return !document.hidden && tabs.activeId===tab.id && !switching && !tab.wantsPause && !tab.closing && !tab.selecting &&
      tab.token===reviewToken && current(tab,reviewToken) && tab.epoch===epoch && !['disconnected','paused','pausing'].includes(tab.state) &&
      (tab.target || tab.selectionReady) && tab.board.reviewed(pane,epoch,revision) &&
      (!tab.blockedIntent || tab.blockedVerified || !tab.blockedFailed && !Number.isSafeInteger(tab.blockedSelectionRevision) && blockedMatches(tab,pane));
  }
  function renderDashboard(tab) {
    tab.boardElement ??= document.createElement('div');tab.boardElement.className='session-dashboard';tab.boardElement.replaceChildren();
    const freshness=document.createElement('p');freshness.setAttribute('role','status');freshness.setAttribute('data-dashboard-phase',tab.board.phase);
    freshness.textContent=tab.board.label+(tab.board.capturedAt?` · 上次快照 ${new Date(tab.board.capturedAt).toLocaleTimeString()}`:'');tab.boardElement.append(freshness);
    const presentation=dashboardPresentation(tab.board.panes);
    const summary=document.createElement('p');summary.textContent=presentation.summary;tab.boardElement.append(summary);
    const list=document.createElement('div');list.className='remote-actions';
    const epoch=tab.board.epoch,revision=tab.board.revision,reviewToken=tab.token;
    for(const pane of presentation.panes){
      const intent=Object.freeze({paneId:pane.paneId,terminalId:pane.terminalId});const button=document.createElement('button');button.type='button';
      button.dataset.paneId=pane.paneId;button.dataset.terminalId=pane.terminalId;
      button.textContent=`${tab.target?'新标签：':'选择 '}${pane.paneId} · ${pane.terminalId} · ${paneStatusText(pane)}${pane.label?` · ${pane.label}`:''}`;
      button.disabled=!canChoose(tab,intent,epoch,revision,reviewToken);
      button.onpointerdown=()=>{if(tab.target && !button.disabled)tab.suppressBlur=true;};
      button.onpointercancel=()=>cancelPrepareHide();
      button.onclick=()=>void choosePane(tab,intent,epoch,revision,reviewToken);list.append(button);
    }
    if(!tab.board.panes.length && tab.board.selectable){const empty=document.createElement('p');empty.textContent='当前会话未发现 pane；不代表主机没有任务。';list.append(empty);}
    tab.boardElement.append(list);
  }
  async function choosePane(tab,intent,epoch,revision,reviewToken) {
    if(!canChoose(tab,intent,epoch,revision,reviewToken)){status(tab,'看板已变化，请核对当前快照后重新选择。');return;}
    if(tab.target){try{const id=create(tab.hostId,intent);await select(id);}catch{status(tab,'已达到八标签上限。');}return;}
    const token=tab.token,generation=tab.nativeGeneration;tab.selectionIntent=intent;tab.selecting=true;if(tab.blockedIntent && !tab.blockedVerified)tab.blockedSelectionRevision=revision;render();
    try {
      await invoke('remote_tab_select',{tabId:tab.id,clientGeneration:token.generation,generation,epoch,revision,paneId:intent.paneId,terminalId:intent.terminalId});
      if(current(tab,token) && tab.epoch===epoch){tab.selectionReady=false;}
    } catch {
      if(tab.blockedIntent && !tab.blockedVerified && current(tab,token)){tab.blockedFailed=true;tab.message='原受阻目标的选择未确认；已停止核查，请返回清单重新操作。';void cancel(tab);return;}
      if(current(tab,token) && tab.epoch===epoch){tab.message='选择未确认，请核对当前看板后重新选择；不会自动切换目标。';if(tab.messageElement)tab.messageElement.textContent=tab.message;}
    } finally {if(current(tab,token)){tab.selecting=false;renderDashboard(tab);}}
  }
  function keyboardEditor(tab) {
    if(fontDiagnostics?.valid() || document.hidden || switching || tabs.activeId!==tab.id || !current(tab,tab.token) || tab.state!=='active' || tab.wantsPause || tab.closing || tab.invalidated || tab.unknown || !tab.target || tab.inputEpoch===null)return null;
    if(tab.mode==='direct' && directCurrent(tab,directToken(tab)))return tab.terminal?.textarea || null;
    if(tab.mode==='draft')return tab.draftField || null;
    return null;
  }
  function refreshKeyboard(tab) {
    const editor=keyboardEditor(tab);
    const composing=tab.mode==='direct' ? !!tab.composition.token && !tab.composition.ended : tab.draftComposing;
    if(tab.keyboardShow)tab.keyboardShow.disabled=!editor || tab.inputBusy || !!textSelection?.valid() || composing;
    const pending=tab.directPending && !tab.directPending.invalidated && document.activeElement===tab.terminal?.textarea;
    if(tab.keyboardHide)tab.keyboardHide.disabled=!(editor && document.activeElement===editor) && !pending;
  }
  function render() {
    if(textSelection && !textSelection.valid()){textSelection.close();textSelection=null;}
    if(fontDiagnostics && !fontDiagnostics.valid()){fontDiagnostics.close(false);fontDiagnostics=null;}
    const focused=tabs.get(tabs.activeId);
    if(focused?.mode==='direct' && ownsInputFocus(focused,document.activeElement) && !focused.suppressBlur){renderDashboard(focused);return;}
    // 草稿输入法组合期间的整页重绘会丢组合缓冲——与 direct 焦点守卫同款：推迟到组合结束后的下一次刷新。
    // （分屏下副面板的状态刷新也走这里，焦点面板的输入过程不被另一侧打断。）
    if(focused && focused.draftComposing && document.activeElement===focused.draftField){renderDashboard(focused);return;}
    // Any unrelated full redraw removes focus from the review; revoke it first.
    if(focused?.pasteReview && !focused.focusPasteReview)focused.pasteReview=null;
    // Only the currently mounted viewports have visible geometry worth retaining.
    for(const mounted of mountedTabs)mounted.localViewport.detach();mountedTabs.length=0;
    root.hidden=tabs.list().length===0;nav.replaceChildren();body.replaceChildren();
    body.setAttribute('data-split',splitPartner()?'2':'1');
    updateSplitControl();
    for(const tab of tabs.list()) {
      const button=document.createElement('button');button.type='button';
      button.textContent=`${hostName(tab.hostId)} · ${tab.target?.paneId || '选择终端'}`;
      button.setAttribute('aria-pressed',String(tabs.activeId===tab.id));button.disabled=switching;
      button.onpointerdown=()=>{const active=tabs.get(tabs.activeId);if(active && active.id!==tab.id)active.suppressBlur=true;};button.onpointercancel=()=>cancelPrepareHide();button.onpointerup=()=>setTimeout(()=>{if(!switching)cancelPrepareHide();},0);
      button.onclick=()=>void select(tab.id);nav.append(button);
    }
    const tab=tabs.get(tabs.activeId);if(!tab){clearPanelMark();return;}
    const partner=splitPartner();
    if(partner)clearPanelMark();else markSinglePanel(tab);
    if(partner){const splitNote=document.createElement('p');splitNote.dataset.role='split-note';splitNote.textContent='分屏只变更本地布局：两个面板各自沿用连接时选定的观察画布，未发送 PTY resize。';body.append(splitNote);}
    else if(splitOn && !isWide() && splitPartnerId){
      // D2 窄窗回落：分屏意图保留，仅非焦点面板被收纳（上方 resize 监听在回到宽窗时恢复副面板）；全程不触发远端 resize。
      const stashed=tabs.get(splitPartnerId);
      if(stashed && stashed.id!==tabs.activeId){const stashNote=document.createElement('p');stashNote.dataset.role='split-stash-note';stashNote.textContent='分屏空间不足；已保留另一面板状态，窗口变宽后自动恢复。';body.append(stashNote);}
    }
    renderPanel(tab,true);
    if(partner)renderPanel(partner,false);
  }
  // 单个终端面板：focused 面板持有唯一输入焦点（docs/04:82）；非焦点面板保持观察，但输入入口全部禁用，不会静默 no-op。
  function renderPanel(tab,focused) {
    // 真分屏才包一层 section：单面板（全部移动端/模拟器路径）的内容直接挂在 #view-content 下——
    // 标题 <p> 必须是 #view-content 的直接子节点（android_gui.py 的测量按直接子节点取标题）。
    const split=!!splitPartner();
    let panel=body;
    if(split){const section=document.createElement('section');section.className='workbench-panel';section.dataset.role='workbench-panel';section.dataset.tabId=tab.id;section.dataset.focus=String(focused);panel=section;}
    if(split) {  // 分屏头部：面板标题 + 输入焦点归属（沿用 fixture #split 的面板头范式）
      const head=document.createElement('div');head.className='panel-head';
      const headTitle=document.createElement('span');headTitle.className='panel-title';
      const headName=document.createElement('strong');headName.textContent=`${hostName(tab.hostId)} · ${tab.target?.paneId || '选择终端'}`;
      const headMeta=document.createElement('small');headMeta.textContent=`${tab.target?.terminalId || '待选择'} · 画布 ${tab.activeCanvas.cols} × ${tab.activeCanvas.rows} · ${focused?'输入焦点':'观察'}`;
      headTitle.append(headName,headMeta);
      const focusButton=document.createElement('button');focusButton.type='button';focusButton.dataset.role='panel-focus';
      focusButton.textContent=focused?'当前输入焦点':'设为输入焦点';
      focusButton.setAttribute('aria-pressed',String(focused));
      focusButton.disabled=focused || switching;
      focusButton.onclick=()=>void select(tab.id);
      head.append(headTitle,focusButton);panel.append(head);
    }
    const title=document.createElement('p');title.textContent=`${hostName(tab.hostId)} · ${tab.target?.paneId || '选择终端'} · ${tab.target?.terminalId || '待选择'}`;panel.append(title);
    if(tab.blockedIntent && !tab.blockedVerified){const intent=document.createElement('p');intent.textContent=`待重新核查受阻目标：${tab.blockedIntent.paneId} · ${tab.blockedIntent.terminalId} · 原会话 ${tab.blockedSession || '未知'}`;panel.append(intent);}
    const info=hostInfo(tab.hostId);const details=document.createElement('p');
    details.textContent=info ? `${info.target.username}@${info.target.host}:${info.target.port} · 主机公钥 ${info.hostFingerprint} · 设备 ${info.deviceFingerprint || '未保存'} · ${info.networkProfileId?'已绑定网络':'系统连接'}` : '主机资料不可用；请先刷新看板。';panel.append(details);
    if(tab.state==='disconnected'){const review=document.createElement('label');const check=document.createElement('input');check.type='checkbox';check.checked=!!tab.reviewed;check.disabled=!focused;check.onchange=()=>{tab.reviewed=check.checked;tab.reviewedHost=check.checked && info ? JSON.stringify({target:info.target,deviceFingerprint:info.deviceFingerprint,networkProfileId:info.networkProfileId ?? null,networkRevision:info.networkRevision ?? null}) : null;render();};review.append(check);const caption=document.createElement('span');caption.textContent='我已核对当前主机、设备与连接路径。';review.append(caption);panel.append(review);}
    const canvasLabel=document.createElement('label');canvasLabel.textContent='此标签下次连接的观察画布 ';const canvasSelect=document.createElement('select');canvasSelect.dataset.role='tab-canvas';
    for(const value of canvasPresets){const option=document.createElement('option');option.value=value;option.textContent=value.replace('x',' × ');canvasSelect.append(option);}
    canvasSelect.value=tab.canvasChoice;canvasSelect.disabled=tab.state!=='disconnected' || tab.closing || switching || !focused;canvasSelect.onchange=()=>{if(tab.state==='disconnected' && parseCanvas(canvasSelect.value))tab.canvasChoice=canvasSelect.value;};canvasLabel.append(canvasSelect);panel.append(canvasLabel);
    const canvasHelp=document.createElement('p');canvasHelp.textContent=tab.state==='disconnected'?'仅影响此标签的下次连接；这是观察画布，不代表远端 PTY 原始尺寸。':`本次观察画布：${tab.activeCanvas.cols} × ${tab.activeCanvas.rows}；暂停恢复沿用本次选择。`;panel.append(canvasHelp);
    if(tab.diagnostics){tab.diagnosticView ??= createConnectionDiagnosticsView();tab.diagnosticView.update(tab.diagnostics);panel.append(tab.diagnosticView.element);}
    const msg=document.createElement('p');msg.setAttribute('role','status');msg.textContent=tab.message;tab.messageElement=msg;panel.append(msg);
    tab.inputModeElement ??= document.createElement('p');
    tab.inputModeElement.setAttribute('role','status');tab.inputModeElement.setAttribute('aria-live','polite');
    updateInputMode(tab);
    panel.append(tab.inputModeElement);
    const controls=document.createElement('div');controls.className='remote-actions';
    const add=(label,enabled,action)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=!enabled || switching || !focused;b.onclick=action;controls.append(b);};
    add('连接',native && !!info && tab.reviewed && !tab.invalidated && tab.state==='disconnected' && !tab.closing,()=>void connect(tab));
    add('恢复观察',tab.state==='paused' && !tab.closing,()=>void resume(tab));
    add('关闭此标签',!switching,()=>void close(tab));panel.append(controls);
    renderDashboard(tab);panel.append(tab.boardElement);
    if(focused && tab.pasteReview && !pasteReviewValid(tab,tab.pasteReview))tab.pasteReview=null;
    if(focused && tab.pasteReview) {
      const review=tab.pasteReview,group=document.createElement('section');group.setAttribute('aria-label','粘贴内容审查');
      const heading=document.createElement('p');
      heading.textContent=`粘贴到本地草稿 · ${hostName(tab.hostId)} · ${review.paneId} · ${review.terminalId}`;
      group.append(heading);
      const preview=document.createElement('pre');preview.className='paste-review-text';preview.textContent=previewPaste(review.text);group.append(preview);
      const actions=document.createElement('div');actions.className='remote-actions';
      const choice=(title,action)=>{
        const button=document.createElement('button');button.type='button';button.textContent=title;
        button.disabled=action!==null && applyPaste(tab.draft,review.text,action)===null;
        button.onclick=()=>{
          if(tab.pasteReview!==review || button.disabled)return;
          if(pasteReviewValid(tab,review) && action!==null) {
            const next=applyPaste(tab.draft,review.text,action);
            if(next===null)return;
            tab.draft=next;tab.draftRevision++;
          }
          tab.pasteReview=null;render();
        };
        actions.append(button);return button;
      };
      const append=choice('追加到草稿','append');
      const replace=choice('替换草稿','replace');
      choice('取消粘贴',null);group.append(actions);
      if(append.disabled) {
        const limit=document.createElement('p');
        limit.textContent='追加后超过 4096 个 UTF-8 字节，可替换或取消。';group.append(limit);
      }
      group.onfocusout=e=>{if(tab.pasteReview===review && !group.contains(e.relatedTarget)){tab.pasteReview=null;render();}};
      panel.append(group);if(tab.focusPasteReview){tab.focusPasteReview=false;(append.disabled?replace:append).focus?.();}
    }
    if(tab.inputReady) {
      const text=document.createElement('textarea');text.value=tab.draft;text.placeholder='输入草稿';text.setAttribute('aria-label','当前标签草稿');
      tab.draftField=text;text.disabled=!focused;
      tab.draftComposing=false;
      text.addEventListener('compositionstart',()=>{tab.pasteReadSequence++;tab.draftComposing=true;refreshKeyboard(tab);});
      text.addEventListener('compositionend',()=>{tab.draftComposing=false;refreshKeyboard(tab);});
      text.addEventListener('blur',()=>{if(!tab.suppressPasteBlur)tab.pasteFocusRevision++;});
      text.addEventListener('paste',event=>void reviewPaste(tab,event,text,tab.draftComposing),true);
      text.oninput=()=>{if(tab.draftField===text && tabs.activeId===tab.id){tab.draft=text.value;tab.draftRevision++;}};panel.append(text);
      const actions=document.createElement('div');actions.className='remote-actions';
      const direct=document.createElement('button');direct.type='button';direct.textContent='逐键输入';direct.disabled=!tab.target || tab.state!=='active' || tab.unknown || tab.inputBusy || !focused;direct.onclick=()=>void enableDirect(tab);actions.append(direct);
      const enable=document.createElement('button');enable.type='button';enable.textContent='启用草稿输入';enable.disabled=!tab.target || tab.state!=='active' || tab.unknown || tab.inputBusy || !focused;
      enable.onclick=()=>void enableInput(tab);actions.append(enable);
      const show=document.createElement('button');show.type='button';show.id='tab-keyboard-show';show.textContent='展开键盘';show.setAttribute('aria-label','展开键盘');
      const hide=document.createElement('button');hide.type='button';hide.id='tab-keyboard-hide';hide.textContent='收起键盘';hide.setAttribute('aria-label','收起键盘');
      show.onpointerdown=hide.onpointerdown=event=>event.preventDefault();
      const binding=lease(tab),target=tab.target;
      const currentButton=()=>tab.keyboardShow===show && tab.keyboardHide===hide && current(tab,binding.token) && tab.nativeGeneration===binding.generation && tab.epoch===binding.epoch && tab.target===target && !document.hidden && !switching && tabs.activeId===tab.id && tab.state==='active' && !tab.closing && !tab.wantsPause && !tab.invalidated;
      show.onclick=()=>{
        if(!currentButton())return;refreshKeyboard(tab);if(show.disabled)return;
        const editor=keyboardEditor(tab);if(!editor)return;
        const token=directToken(tab),mode=tab.mode,terminal=tab.terminal;
        if(editor===tab.terminal?.textarea)tab.terminal.focus();else editor.focus();
        keyboardRequest('show',editor,()=>currentButton() && keyboardEditor(tab)===editor && tab.terminal===terminal && tab.mode===mode && OnlineInputQueue.same(token,directToken(tab)) && document.activeElement===editor);
        tab.message='已请求展开键盘；是否显示由系统决定。';if(tab.messageElement)tab.messageElement.textContent=tab.message;refreshKeyboard(tab);
      };
      hide.onclick=()=>{
        if(!currentButton())return;refreshKeyboard(tab);if(hide.disabled)return;
        const editor=keyboardEditor(tab) || (tab.directPending ? tab.terminal?.textarea : null);
        if(!editor || document.activeElement!==editor)return;
        const revision=tab.inputRevision,terminal=tab.terminal;
        keyboardRequest('hide',editor,()=>currentButton() && tab.terminal===terminal && (tab.inputRevision===revision || tab.inputRevision===revision+1 && tab.mode==='observe') && (document.activeElement===editor || document.activeElement===document.body || document.activeElement==null));
        if(tab.directPending)tab.directPending.invalidated=true;
        editor.blur?.();if(tab.inputRevision===revision)void loseDirect(tab);
        tab.message='已收起输入焦点；重新输入请先选择输入模式。';if(tab.messageElement)tab.messageElement.textContent=tab.message;refreshKeyboard(tab);
      };
      tab.keyboardShow=show;tab.keyboardHide=hide;actions.append(show,hide);refreshKeyboard(tab);

      const paste=document.createElement('button');paste.type='button';paste.textContent='粘贴并审查';paste.disabled=!tab.target || tab.state!=='active' || tab.unknown || tab.inputBusy || !['draft','direct'].includes(tab.mode) || tab.inputEpoch==null || !focused;
      paste.onpointerdown=event=>event.preventDefault();paste.onclick=()=>void readPaste(tab);tab.pasteButton=paste;actions.append(paste);
      const send=document.createElement('button');send.type='button';send.textContent='发送草稿';send.disabled=!tab.target || tab.state!=='active' || tab.mode!=='draft' || tab.unknown || tab.inputBusy || tab.inputEpoch==null || !focused;
      send.onclick=()=>void sendDraft(tab);actions.append(send);
      if(tab.recoveryStatus==='pending'){const recover=document.createElement('button');recover.type='button';recover.textContent='已核实原目标结果，恢复输入';recover.disabled=!tab.target || tab.state!=='active' || tab.inputBusy || !focused;recover.onclick=()=>void recoverInput(tab);actions.append(recover);}
      panel.append(actions);
      tab.toolbarHost=document.createElement('div');panel.append(tab.toolbarHost);
      if(tab.mode==='direct' && tab.toolbar)tab.toolbarHost.append(tab.toolbar.element);
    }
    if(tab.rejectedDrafts.length){const heading=document.createElement('p');heading.textContent='服务器明确拒绝的原文（只读，不会自动发送）：';panel.append(heading);
      tab.rejectedDrafts.forEach((value,index)=>{const saved=document.createElement('textarea');saved.value=value;saved.readOnly=true;saved.setAttribute('aria-label','被拒绝的原文');panel.append(saved);const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='移除此找回原文';dismiss.onclick=()=>{tab.rejectedDrafts.splice(index,1);render();};panel.append(dismiss);});
    }
    if(tab.terminal && tab.target && tab.state==='active') {
      const selectText=document.createElement('button');selectText.type='button';selectText.disabled=!tab.selectionTextReady || !focused;tab.selectionTextButton=selectText;selectText.textContent='选择终端文本';selectText.onpointerdown=event=>event.preventDefault();
      selectText.onclick=()=>{
        const token=tab.token,generation=tab.nativeGeneration,epoch=tab.epoch,target=tab.target,terminal=tab.terminal;
        const currentSelection=()=>!document.hidden && !switching && tabs.activeId===tab.id && current(tab,token) && tab.nativeGeneration===generation && tab.epoch===epoch && tab.target===target && tab.terminal===terminal && tab.state==='active' && !tab.wantsPause && !tab.closing;
        if(!tab.selectionTextReady || !currentSelection())return;
        if(tab.inputBusy || tab.directPending){status(tab,'输入仍在处理，暂不能选择终端文本。');return;}
        fontDiagnostics?.close(false);fontDiagnostics=null;textSelection?.close();textSelection=null;void loseDirect(tab);
        try {textSelection=createTerminalSelection({terminal,current:currentSelection,label:`${hostName(tab.hostId)} · ${target.paneId} · ${target.terminalId}`});}
        catch(error) {status(tab,String(error).includes('snapshot_too_large')?'可见终端文本超过 64 KiB，无法选择；未复制内容。':'没有可安全测量的可见终端文本，请滚动终端到屏幕内后重试。');}
      };panel.append(selectText);
      const fontButton=document.createElement('button');fontButton.type='button';fontButton.textContent='字体与字符诊断';fontButton.disabled=!tab.selectionTextReady || !focused;fontButton.onpointerdown=event=>event.preventDefault();
      fontButton.onclick=()=>{
        const token=tab.token,generation=tab.nativeGeneration,epoch=tab.epoch,target=tab.target,terminal=tab.terminal;
        const currentDiagnostics=()=>!document.hidden && !switching && tabs.activeId===tab.id && current(tab,token) && tab.nativeGeneration===generation && tab.epoch===epoch && tab.target===target && tab.terminal===terminal && tab.state==='active' && !tab.wantsPause && !tab.closing;
        if(fontDiagnostics?.valid() || !tab.selectionTextReady || !currentDiagnostics())return;
        if(tab.inputBusy || tab.directPending){status(tab,'输入仍在处理，暂不能打开字体诊断。');return;}
        textSelection?.close();textSelection=null;fontDiagnostics?.close(false);fontDiagnostics=null;void loseDirect(tab);
        let view;try {view=createFontDiagnostics({current:currentDiagnostics,terminalFactory,fontSize:getFontSize(),theme:theme.terminal,returnFocus:fontButton,onClose:()=>{if(fontDiagnostics===view)fontDiagnostics=null;}});fontDiagnostics=view;}catch {status(tab,'字体诊断无法安全打开；输入已锁定。');}
      };tab.fontDiagnosticsButton=fontButton;panel.append(fontButton);

    }
    const viewport=document.createElement('div');viewport.className='term-scroll';
    if(tab.element)viewport.append(tab.element);panel.append(viewport);
    tab.localViewport.mount(viewport,tab.terminal,terminalViewportIdentity(tab.summaryIdentity || hostInfo(tab.hostId),tab.target),!!tab.selectionTextReady);
    mountedTabs.push(tab);
    if(split)body.append(panel);
  }
  function create(hostId,target) {
    if(!native || !hostId || (target && (!target.paneId || !target.terminalId))) throw Error('tab_target_invalid');
    const tab=tabs.create(hostId);tab.canvasChoice='80x24';tab.activeCanvas={cols:80,rows:24};tab.localViewport=new LocalTerminalViewport();tab.target=target ? Object.freeze({paneId:target.paneId,terminalId:target.terminalId}) : null;
    tab.selectionTextReady=false;tab.queue=new OnlineInputQueue();tab.composition=new InputComposition();tab.directPending=null;tab.pasteReview=null;tab.focusPasteReview=false;tab.pasteFocusRevision=0;tab.pasteReadSequence=0;tab.draftComposing=false;tab.draftRevision=0;tab.draftPending=0;tab.rejectedDrafts=[];tab.inputRevision=0;tab.controlRevision=0;tab.mode='observe';tab.board=new SessionDashboard();tab.selectionIntent=tab.target;tab.selectionReady=false;tab.selecting=false;tab.focusReset=Promise.resolve();tab.message=target?'目标已固定；请主动连接。':'请主动连接并从实际快照选择终端。';tab.state='disconnected';tab.closing=false;tab.nativeGeneration=null;tab.epoch=null;
    render();return tab.id;
  }
  function createBlocked(hostId,intent) {
    if(!intent || intent.hostId!==hostId || intent.identity!==hostSummaryIdentity(hostInfo(hostId)) || !validDashboard([intent]))throw Error('blocked_target_changed');
    const id=create(hostId,null),tab=tabs.get(id);tab.blockedIntent=Object.freeze({...intent});tab.blockedSession=hostInfo(hostId)?.target?.session;tab.blockedVerified=false;
    tab.message='请核对原主机、网络与会话后主动连接；只有新快照确认同一 pane 与 terminal 仍受阻才接入观察。';render();return id;
  }
  async function select(id) {
    if(switching || id===tabs.activeId)return;
    const swapping=splitPartner()?.id===id;
    switching=true;render();
    const previous=tabs.get(tabs.activeId);
    if(swapping && previous) {
      // 分屏内移动输入焦点：旧面板保持观察（不暂停），但其输入租约立即失效——
      // 与 src/gate.js 的 focus()/focusRevision 语义一致：焦点一旦离开，旧 token 全部过期（后端对非焦点标签返回 input_stale）。
      if(previous.mode!=='observe' || previous.inputEpoch!==null)await loseDirect(previous);
      else await previous.focusReset;
      previous.pasteReview=null;
      splitPartnerId=previous.id;
    }
    else if(previous && ['connecting','starting','active','resuming'].includes(previous.state)) await pause(previous);
    if(tabs.get(id))tabs.select(id);
    switching=false;render();
  }
  function retireDirectPending(tab) {if(tab.directPending){tab.directPending.invalidated=true;tab.directPending=null;}}
  async function pause(tab) {
    tab.diagnostics?.pause();tab.diagnosticView?.update(tab.diagnostics);
    retireDirectPending(tab);tab.wantsPause=true;tab.board.invalidate('paused');boardEvent(tab,'stale');tab.selectionReady=false;
    if(tab.visibilityPending){try {await tab.visibilityPending;}catch {await cancel(tab);return;}}
    if(tab.closing || tab.state==='disconnected')return;
    if(tab.nativeGeneration===null) {await cancel(tab);return;}
    const controlRevision=++tab.controlRevision;tab.suppressBlur=true;tab.queue.clear();tab.inputRevision++;tab.inputBusy=false;tab.inputEpoch=null;tab.mode='observe';if(tab.terminal)tab.terminal.options.disableStdin=true;
    tab.state='pausing';render();
    try {await invoke('remote_tab_control',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration,action:'pause'});if(tabs.get(tab.id)===tab && tab.controlRevision===controlRevision)status(tab,'观察已暂停，SSH 保留；需主动恢复。');}
    catch {if(tab.controlRevision!==controlRevision)return;await cancel(tab);status(tab,'暂停未确认，连接已取消；不会自动重连。');}
    finally {tab.suppressBlur=false;}
  }
  async function resume(tab) {
    if((tabs.activeId!==tab.id && splitPartner()!==tab) || tab.state!=='paused')return;
    tab.diagnostics?.resume();
    const controlRevision=++tab.controlRevision;tab.state='resuming';tab.wantsPause=false;tab.board.invalidate('resuming');boardEvent(tab,'starting');tab.selectionReady=false;render();
    try {const pending=invoke('remote_tab_visible',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration});tab.visibilityPending=pending;await pending;tab.visibilityPending=null;if(tab.wantsPause)return;await invoke('remote_tab_control',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration,action:'resume'});}
    catch(error) {if(String(error)==='control_superseded' || tab.controlRevision!==controlRevision)return;await cancel(tab);status(tab,'恢复未完成，连接已取消。');}
  }
  async function enableInput(tab) {
    if(tab.blockedIntent && !tab.blockedVerified)return;
    if(fontDiagnostics?.valid() || textSelection?.valid() || document.hidden || !tab.target || tabs.activeId!==tab.id || tab.state!=='active' || tab.unknown || tab.inputBusy)return;
    if(tab.mode==='direct')await loseDirect(tab);
    await tab.focusReset;
    if(document.hidden || !tab.target || tabs.activeId!==tab.id || tab.state!=='active' || tab.unknown)return;
    const binding=lease(tab);tab.inputBusy=true;render();
    try {const value=await invoke('remote_tab_input_mode',{tabId:tab.id,clientGeneration:binding.token.generation,generation:binding.generation,epoch:binding.epoch,mode:'draft'});if(sameLease(tab,binding) && tabs.activeId===tab.id && tab.state==='active'){tab.inputEpoch=value;tab.mode='draft';}}
    catch {if(sameLease(tab,binding))tab.message='草稿输入未启用，请核对当前标签。';}
    finally {if(sameLease(tab,binding)){tab.inputBusy=false;render();}}
  }
  function directToken(tab) {return {generation:tab.nativeGeneration,epoch:tab.inputEpoch,revision:tab.inputRevision};}
  function ownsInputFocus(tab,element) {
    return !!element && (element===tab.terminal?.textarea || tab.toolbar?.element.contains(element));
  }
  function directCurrent(tab,token) {
    return !fontDiagnostics?.valid() && !textSelection?.valid() && !document.hidden && !switching && !tab.wantsPause && !tab.closing && !tab.invalidated &&
      tabs.activeId===tab.id && current(tab,tab.token) && tab.state==='active' && tab.mode==='direct' &&
      !tab.unknown && tab.inputEpoch!==null && ownsInputFocus(tab,document.activeElement) && OnlineInputQueue.same(token,directToken(tab));
  }
  function enqueueDirect(tab,bytes) {
    const token=directToken(tab);
    if(!directCurrent(tab,token))return;
    if(!tab.queue.push(token,bytes)){tab.queue.clear();void loseDirect(tab);return;}
    void pumpDirect(tab);
  }
  function showToolbar(tab) {
    const authorized=directToken(tab);
    const toolbar=createTabInputToolbar({
      canSend:()=>directCurrent(tab,authorized) && !(tab.composition.token && !tab.composition.ended),
      send:bytes=>{if(directCurrent(tab,authorized))enqueueDirect(tab,bytes);},
      applicationCursorMode:()=>tab.terminal?.modes?.applicationCursorKeysMode===true,
    });
    toolbar.element.className='tab-input-toolbar';
    tab.toolbar=toolbar;
    toolbar.element.addEventListener('focusout',event=>{
      if(tab.toolbar===toolbar && tab.mode==='direct' && !tab.suppressBlur && !ownsInputFocus(tab,event.relatedTarget))void loseDirect(tab);
    });
    tab.toolbarHost.replaceChildren(toolbar.element);
    toolbar.refresh();
  }
  function pasteReviewValid(tab,review) {
    return !document.hidden && tabs.activeId===tab.id && !switching && tab.state==='active' && !tab.wantsPause && !tab.closing && tab.mode==='observe' && !tab.unknown && tab.draftRevision===review.draftRevision && tab.pasteFocusRevision===review.focusRevision && tab.target?.paneId===review.paneId && tab.target?.terminalId===review.terminalId && sameLease(tab,review.binding);
  }
  async function reviewPaste(tab,event,editor,composing) {
    event.preventDefault();event.stopImmediatePropagation();
    tab.pasteReadSequence++;
    const text=event.clipboardData?.types && !Array.from(event.clipboardData.types).includes('text/plain') ? '' : event.clipboardData?.getData('text/plain') || '';
    return reviewPasteText(tab,text,editor,composing);
  }
  async function reviewPasteText(tab,text,editor,composing) {
    if(tab.directPending || tab.inputBusy || tab.unknown || !tab.inputReady || !tab.target ||
        document.hidden || tabs.activeId!==tab.id || tab.state!=='active' || document.activeElement!==editor)return;
    if(editor===tab.terminal?.textarea ? tab.mode!=='direct' : editor!==tab.draftField)return;
    const report=message=>{tab.message=message;if(tab.messageElement)tab.messageElement.textContent=message;};
    if(composing){report('输入法组合尚未结束，请完成后再粘贴。');return;}
    if(applyPaste('',text,'replace')===null){report('粘贴内容须为 1 至 4096 个 UTF-8 字节。');return;}
    const {paneId,terminalId}=tab.target;
    const draftRevision=tab.draftRevision,focusRevision=tab.pasteFocusRevision;
    const reset=tab.mode==='observe'?tab.focusReset:loseDirect(tab);
    const review={text,draftRevision,focusRevision,paneId,terminalId,binding:lease(tab)};
    tab.pendingPaste=review;
    await reset;
    if(tab.pendingPaste!==review)return;
    tab.pendingPaste=null;
    if(document.activeElement!==editor || !pasteReviewValid(tab,review))return;
    tab.pasteReview=review;tab.focusPasteReview=true;tab.suppressPasteBlur=true;
    try {render();} finally {tab.suppressPasteBlur=false;}
  }
  async function readPaste(tab) {
    const mode=tab.mode, editor=mode==='direct'?tab.terminal?.textarea:tab.draftField;
    const binding=lease(tab), inputEpoch=tab.inputEpoch, target=tab.target, terminal=tab.terminal;
    const draftRevision=tab.draftRevision, original=tab.draft, focusRevision=tab.pasteFocusRevision;
    const sequence=++tab.pasteReadSequence;
    const valid=()=>sequence===tab.pasteReadSequence && sameLease(tab,binding) && tab.inputEpoch===inputEpoch && inputEpoch!==null &&
      tab.mode===mode && ['draft','direct'].includes(mode) && tab.target===target && !!target && tab.terminal===terminal &&
      tabs.activeId===tab.id && !switching && !document.hidden && tab.state==='active' && !tab.wantsPause && !tab.closing &&
      !tab.invalidated && !tab.unknown && !tab.inputBusy && !tab.directPending && tab.inputReady &&
      document.activeElement===editor && (mode==='direct' || tab.draftField===editor) && tab.draftRevision===draftRevision && tab.draft===original &&
      tab.pasteFocusRevision===focusRevision && !(mode==='direct' ? tab.composition.token && !tab.composition.ended : tab.draftComposing);
    const report=message=>{tab.message=message;if(tab.messageElement)tab.messageElement.textContent=message;};
    if(!valid()){report('请先启用输入模式并完成输入法组合，再粘贴。');return;}
    try {
      const text=await clipboardRead();
      if(!valid())return;
      if(typeof text!=='string' || !text){report('剪贴板没有可用的纯文本。');return;}
      await reviewPasteText(tab,text,editor,false);
    } catch (error) {if(valid())report(clipboardPasteMessage(error));}
  }
  async function loseDirect(tab) {
    const wasBusy=tab.inputBusy;tab.queue.clear();tab.inputRevision++;tab.mode='observe';tab.inputEpoch=null;
    if(tab.pasteButton)tab.pasteButton.disabled=true;refreshKeyboard(tab);tab.toolbar?.reset();tab.toolbar=null;tab.toolbarHost?.replaceChildren();
    if(tab.terminal){tab.terminal.options.disableStdin=true;tab.terminal.textarea.setAttribute('inputmode','none');}
    if(wasBusy){tab.unknown=true;updateInputMode(tab);tab.message='输入在途时焦点离开；请恢复观察后核实原目标。';await pause(tab);return;}
    updateInputMode(tab);
    if(tab.nativeGeneration!==null && tab.epoch!==null) {tab.focusReset=invoke('remote_tab_input_mode',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration,epoch:tab.epoch,mode:'observe'}).catch(()=>{});await tab.focusReset;}
  }
  async function enableDirect(tab) {
    if(tab.blockedIntent && !tab.blockedVerified)return;
    if(fontDiagnostics?.valid() || textSelection?.valid() || document.hidden || !tab.target || tabs.activeId!==tab.id || tab.state!=='active' || tab.unknown || tab.inputBusy || tab.directPending || !tab.terminal)return;
    tab.queue.clear();tab.inputRevision++;tab.inputEpoch=null;tab.mode='observe';updateInputMode(tab);
    const binding=lease(tab),terminal=tab.terminal,target=tab.target;
    const attempt={invalidated:false};tab.directPending=attempt;let invoked=false,granted=false;
    tab.message='正在核验逐键输入许可；请等待确认后输入。';if(tab.messageElement)tab.messageElement.textContent=tab.message;
    const currentAttempt=()=>tab.directPending===attempt && !attempt.invalidated && sameLease(tab,binding) && tab.target===target && tab.terminal===terminal && !document.hidden && tabs.activeId===tab.id && tab.state==='active' && !tab.unknown && document.activeElement===terminal.textarea;
    // xterm mirrors disableStdin into textarea.readOnly. Open the keyboard during
    // the user's gesture; observe mode and null inputEpoch still reject all input.
    try {
      terminal.options.disableStdin=false;terminal.textarea.setAttribute('inputmode','text');terminal.focus();refreshKeyboard(tab);
      if(!currentAttempt())return;
      await tab.focusReset;
      if(!currentAttempt())return;
      invoked=true;
      const inputEpoch=await invoke('remote_tab_input_mode',{tabId:tab.id,clientGeneration:binding.token.generation,generation:binding.generation,epoch:binding.epoch,mode:'direct'});
      if(!currentAttempt())return;
      if(!Number.isSafeInteger(inputEpoch) || inputEpoch<1)throw Error('input_lease_invalid');
      tab.inputEpoch=inputEpoch;tab.mode='direct';updateInputMode(tab);granted=true;tab.message='逐键输入已启用。';if(tab.messageElement)tab.messageElement.textContent=tab.message;
      if(tab.pasteButton)tab.pasteButton.disabled=false;
      showToolbar(tab);refreshKeyboard(tab);
    } catch {
      if(tab.directPending===attempt && current(tab,binding.token)){tab.message='逐键输入未启用。';if(tab.messageElement)tab.messageElement.textContent=tab.message;}
    } finally {
      if(tab.directPending===attempt) {
        if(!granted){terminal.options.disableStdin=true;terminal.textarea.setAttribute('inputmode','none');}
        // A rejected or late native reply might still have changed mode.
        // Keep this attempt's gate until an observe reset has settled.
        if(!granted && invoked && current(tab,binding.token) && tab.epoch===binding.epoch && tab.state==='active') {
          tab.focusReset=invoke('remote_tab_input_mode',{tabId:tab.id,clientGeneration:binding.token.generation,generation:binding.generation,epoch:binding.epoch,mode:'observe'}).catch(()=>{});
          await tab.focusReset;
        }
        if(tab.directPending===attempt)tab.directPending=null;
      }
    }
  }
  async function pumpDirect(tab) {
    if(tab.inputBusy)return;const key=directToken(tab);if(!directCurrent(tab,key)){tab.queue.clear();return;}
    const item=tab.queue.take(key);if(!item)return;const binding=lease(tab);tab.inputBusy=true;
    try {const result=await invoke('remote_tab_input_send',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration,epoch:tab.epoch,inputEpoch:key.epoch,bytes:[...item.bytes],draft:false});
      if(!directCurrent(tab,key))return;
      const receipt=result?.status==='accepted'?matchedReceipt(result.receipt,tab.target,item.bytes.length):null;
      if(!receipt || result.recoveryRequired){tab.unknown=result?.status!=='rejected' || !!result.recoveryRequired;tab.queue.clear();tab.inputBusy=false;await loseDirect(tab);if(tab.unknown)await cancel(tab);return;}
    }catch {if(sameLease(tab,binding)){tab.unknown=true;tab.queue.clear();await cancel(tab);}return;}
    finally {if(sameLease(tab,binding))tab.inputBusy=false;}
    if(directCurrent(tab,key))void pumpDirect(tab);else tab.queue.clear();
  }
  async function recoverInput(tab) {
    if(document.hidden || !tab.target || tabs.activeId!==tab.id || tab.state!=='active' || tab.recoveryStatus!=='pending' || tab.inputBusy)return;
    if(!window.confirm('已在此原目标核实上一笔发送结果？'))return;
    const binding=lease(tab);tab.inputBusy=true;render();const token=binding.token,epoch=binding.epoch;
    try {const inputEpoch=await invoke('remote_tab_input_mode',{tabId:tab.id,clientGeneration:token.generation,generation:binding.generation,epoch,mode:'observe',review:true});
      if(!sameLease(tab,binding))return;
      await invoke('remote_tab_input_recover',{tabId:tab.id,clientGeneration:token.generation,generation:binding.generation,epoch,inputEpoch});
      if(sameLease(tab,binding)){tab.unknown=false;tab.recoveryStatus='ready';tab.inputEpoch=null;tab.message='原目标结果已核实；请重新启用输入。';}
    } catch {if(sameLease(tab,binding))tab.message='无法恢复；请重新观察原目标并核实安全记录。';}
    finally {if(sameLease(tab,binding)){tab.inputBusy=false;render();}}
  }
  async function sendDraft(tab) {
    if(fontDiagnostics?.valid() || textSelection?.valid() || document.hidden || !tab.target || tabs.activeId!==tab.id || tab.state!=='active' || tab.mode!=='draft' || tab.unknown || tab.inputBusy || tab.inputEpoch==null || tab.draftComposing)return;
    if(tab.draftPending+tab.rejectedDrafts.length>=8){status(tab,'找回区已满，请先处理已拒绝原文。');return;}
    const text=tab.draft,bracketed=tab.terminal?.modes?.bracketedPasteMode===true;
    const bytes=draftBytes(text,bracketed);
    if(!bytes){status(tab,'草稿为空、超过 4096 字节或含不支持的粘贴结束序列。');return;}
    const binding=lease(tab),inputEpoch=tab.inputEpoch,version=tab.draftRevision;
    const framing=bracketed?'已包含括号粘贴标记':'普通文本';
    if(!window.confirm(`发送到 ${hostName(tab.hostId)} · ${tab.target.paneId} · ${tab.target.terminalId}？\n${bytes.length} 字节 · ${framing}\n\n${previewPaste(text)}`))return;
    if(!sameLease(tab,binding) || document.hidden || tabs.activeId!==tab.id || tab.mode!=='draft' ||
        tab.inputEpoch!==inputEpoch || tab.draftRevision!==version || tab.draft!==text ||
        tab.state!=='active' || tab.unknown || tab.inputBusy || tab.draftComposing || (tab.terminal?.modes?.bracketedPasteMode===true)!==bracketed)return;
    const epoch=binding.epoch,token=binding.token;tab.draft='';const draftRevision=++tab.draftRevision;tab.draftPending++;tab.inputBusy=true;render();
    try {const result=await invoke('remote_tab_input_send',{tabId:tab.id,clientGeneration:token.generation,generation:tab.nativeGeneration,epoch,inputEpoch,bytes:[...bytes],draft:true});
      let restored=false;
      if(result?.status==='rejected' && tabs.get(tab.id)===tab){
        if(!result.recoveryRequired && sameLease(tab,binding) && tab.draftRevision===draftRevision){tab.draft=text;tab.draftRevision++;restored=true;}
        else {tab.rejectedDrafts.push(text);}
      }
      if(!sameLease(tab,binding))return;
      const receipt=result?.status==='accepted'?matchedReceipt(result.receipt,tab.target,bytes.length):null;
      if(result?.status==='rejected'){tab.message=restored?'服务器明确拒绝；原草稿已恢复。':'服务器明确拒绝；原文已放入只读找回区。';if(result.recoveryRequired){tab.unknown=true;tab.inputEpoch=null;}}
      else if(receipt){tab.message=result.recoveryRequired?'服务器已接收入队，但安全记录待核查；输入已锁定。':`服务器已接收入队 ${receipt.acceptedBytes} 字节；执行结果请查看终端。`;if(result.recoveryRequired){tab.unknown=true;tab.inputEpoch=null;}}
      else {tab.unknown=true;tab.inputEpoch=null;tab.message='发送结果未知；请核查原目标，不会自动重发。';void cancel(tab);}
    } catch {if(sameLease(tab,binding)){tab.unknown=true;tab.inputEpoch=null;tab.message='发送结果未确认；请核查原目标，不会自动重发。';}}
    finally {if(tabs.get(tab.id)===tab){tab.draftPending--;if(sameLease(tab,binding))tab.inputBusy=false;render();}}
  }
  async function cancel(tab) {
    tab.diagnostics?.finish('cancelled');tab.diagnosticView?.update(tab.diagnostics);
    retireDirectPending(tab);
    const wasDisconnected=tab.state==='disconnected' && tab.nativeGeneration===null;
    tab.board.invalidate('disconnected');boardEvent(tab,'stale');tab.selectionReady=false;tab.suppressBlur=true;tab.closing=true;tab.controlRevision++;tab.inputRevision++;tab.inputBusy=false;tab.inputEpoch=null;tab.mode='observe';tab.queue.clear();if(tab.terminal)tab.terminal.options.disableStdin=true;tabs.invalidate(tab.id);render();tab.suppressBlur=false;
    if(tab.nativeGeneration!==null)try {await invoke('remote_tab_cancel',{tabId:tab.id,clientGeneration:tab.token.generation,generation:tab.nativeGeneration});}catch {}
    tab.state='disconnected';if(wasDisconnected)tab.closing=false;render();
  }
  async function close(tab) {
    await cancel(tab);tab.localViewport.detach();tab.terminal?.dispose();tabs.close(tab.id);
    if(splitPartnerId) {
      // 分屏的一侧被关闭即结束分屏：剩余面板升为唯一焦点面板，不留“无面板仍在观察”的隐藏流。
      if(splitPartnerId===tab.id){splitOn=false;splitPartnerId=null;}
      else if(tabs.activeId===null){tabs.select(splitPartnerId);splitOn=false;splitPartnerId=null;}
    }
    render();
  }
  async function connect(tab) {
    if(tabs.activeId!==tab.id || tab.state!=='disconnected' || tab.closing || tab.invalidated || !tab.reviewed || !hostInfo(tab.hostId))return;
    const reviewed=JSON.parse(tab.reviewedHost || 'null'),actual=hostInfo(tab.hostId);
    if(tab.blockedIntent && hostSummaryIdentity(actual)!==tab.blockedIntent.identity){tab.reviewed=false;status(tab,'原受阻目标的主机、设备、会话或网络已变化；请返回清单重新核查。');return;}
    if(!reviewed || JSON.stringify(reviewed)!==JSON.stringify({target:actual.target,deviceFingerprint:actual.deviceFingerprint,networkProfileId:actual.networkProfileId ?? null,networkRevision:actual.networkRevision ?? null})){tab.reviewed=false;status(tab,'主机资料已变化，请重新核对。');return;}
    const canvas=parseCanvas(tab.canvasChoice);if(!canvas)return;tab.activeCanvas=canvas;
    tab.diagnostics=new ConnectionDiagnostics({identity:connectionDiagnosticIdentity({hostId:tab.hostId,...actual}),host:hostName(tab.hostId),session:actual.target.session,network:!!actual.networkProfileId,device:true});
    if(tab.blockedIntent){tab.target=null;tab.blockedVerified=false;tab.blockedBound=false;tab.blockedFailed=false;tab.blockedSelectionRevision=null;if(tab.element)tab.element.hidden=true;}
    const token=tabs.begin(tab.id);tab.token=token;tab.summaryIdentity=actual;onDashboard({type:'starting',hostId:tab.hostId,identity:actual,source:token});tab.epoch=null;tab.selectionTextReady=false;tab.inputReady=false;tab.inputEpoch=null;tab.inputBusy=false;tab.selecting=false;tab.mode='observe';tab.inputRevision++;tab.queue.clear();const previousBoard=tab.board;tab.board=new SessionDashboard();tab.board.panes=previousBoard.panes;tab.board.capturedAt=previousBoard.capturedAt;tab.pasteReview=null;tab.selectionIntent=tab.target;tab.selectionReady=false;tab.wantsPause=false;tab.state='connecting';tab.message='正在连接并核验目标…';tab.frames=new RemoteFrameQueue();render();
    try {
      const generation=await invoke('remote_tab_reserve',{tabId:tab.id,clientGeneration:token.generation,hostId:tab.hostId,expectedTarget:reviewed.target,expectedDeviceFingerprint:reviewed.deviceFingerprint,expectedNetworkProfileId:reviewed.networkProfileId,expectedNetworkRevision:reviewed.networkRevision});
      if(!current(tab,token) || tab.closing) {await invoke('remote_tab_cancel',{tabId:tab.id,clientGeneration:token.generation,generation});return;}
      tab.nativeGeneration=generation;
      if(tabs.activeId!==tab.id && splitPartner()!==tab){await cancel(tab);return;}
      const pendingVisible=invoke('remote_tab_visible',{tabId:tab.id,clientGeneration:token.generation,generation});tab.visibilityPending=pendingVisible;await pendingVisible;tab.visibilityPending=null;
      if(!current(tab,token) || (tabs.activeId!==tab.id && splitPartner()!==tab) || tab.wantsPause){await cancel(tab);return;}
      const channel=channelFactory();
      // 分屏可见集：活动标签或分屏副面板都可继续接收事件（后端 visible 为集合语义，仅 focus 独占）。
      const paneVisible=()=>tabs.activeId===tab.id || splitPartner()===tab;
      channel.onmessage=event=>{
        if(!current(tab,token) || event.generation!==generation)return;
        if(tab.blockedIntent && hostSummaryIdentity(hostInfo(tab.hostId))!==tab.blockedIntent.identity){tab.message='原目标资料或网络已变化；观察已停止。';void cancel(tab);return;}
        if(event.kind==='dashboard_watch') {
          if(!paneVisible() || tab.wantsPause || document.hidden || ['paused','pausing'].includes(tab.state))return;
          const accepted=tab.board.accept(event.update,tab.epoch);
          if(accepted==='invalid'){void cancel(tab);return;}
          if(accepted==='accepted'){boardEvent(tab,Array.isArray(event.update.panes)?'snapshot':'stale');tab.diagnostics.dashboard(tab.board);tab.diagnosticView?.update(tab.diagnostics);renderDashboard(tab);recheckBlocked(tab);}return;
        }
        if(event.kind==='target_bound') {
          if(event.epoch!==tab.epoch || tab.wantsPause || document.hidden || !paneVisible())return;
          const target={paneId:event.pane_id,terminalId:event.terminal_id},intent=tab.target || tab.selectionIntent;
          if(!validDashboard([target]) || !intent || intent.paneId!==target.paneId || intent.terminalId!==target.terminalId){void cancel(tab);return;}
          if(tab.blockedIntent && !tab.blockedVerified){if(!blockedMatches(tab,target) || tab.blockedSelectionRevision!==tab.board.revision){tab.message='重新核查期间原目标或快照已变化；没有接入观察。';void cancel(tab);return;}tab.blockedBound=true;}
          tab.diagnostics.bind(target);tab.diagnosticView?.update(tab.diagnostics);const changed=tab.target===null;tab.target=Object.freeze(target);tab.selectionReady=false;if(changed)render();return;
        }
        if(event.kind==='selection_ready') {if(event.epoch===tab.epoch && paneVisible() && !tab.wantsPause){tab.selectionReady=true;renderDashboard(tab);recheckBlocked(tab);}return;}
        if(event.kind==='stage') {if(!tab.wantsPause && !document.hidden && paneVisible()){tab.diagnostics.stage(event.stage);const text=connectionStageText(event.stage);if(text)status(tab,text);}return;}
        if(event.kind==='observation') {if(!Number.isSafeInteger(event.snapshot?.epoch) || (tab.epoch!==null && event.snapshot.epoch<tab.epoch))return;if(event.snapshot.epoch!==tab.epoch){if(tab.blockedIntent && !tab.blockedVerified)tab.blockedBound=false;tab.selectionTextReady=false;retireDirectPending(tab);tab.suppressBlur=true;tab.board.advance(event.snapshot.epoch);boardEvent(tab,'stale');tab.selectionReady=false;tab.frames=new RemoteFrameQueue();tab.inputRevision++;tab.inputBusy=false;tab.inputReady=false;tab.inputEpoch=null;tab.mode='observe';tab.queue.clear();if(tab.terminal)tab.terminal.options.disableStdin=true;}tab.epoch=event.snapshot.epoch;tab.state=event.snapshot.phase;if(['paused','pausing','closed'].includes(tab.state)){tab.board.invalidate(tab.state);boardEvent(tab,'stale');tab.selectionReady=false;}status(tab,tab.state==='paused'?'观察已暂停，SSH 保留；需主动恢复。':tab.state==='active'?'观察已连接；输入状态见下方。':'正在切换观察状态…');tab.suppressBlur=false;return;}
        if(event.kind==='input_ready') {if(event.epoch!==tab.epoch || tab.blockedIntent && !tab.blockedVerified)return;tab.inputReady=true;tab.unknown=event.unknown;tab.recoveryStatus=event.recovery_status;tab.message=event.unknown?'存在未确认的发送结果，输入保持锁定；请核查原目标。':'已收到完整画面，可显式开启草稿输入。';render();return;}
        if(event.kind!=='frame' || event.epoch!==tab.epoch || !paneVisible())return;
        if(tab.blockedIntent && !tab.blockedVerified && (!tab.blockedBound || !event.frame?.full || !blockedMatches(tab,tab.target))){void cancel(tab);return;}
        if(!tab.frames.accept(event.frame)){void cancel(tab);return;}
        if(!tab.terminal) {
          tab.element=document.createElement('div');tab.element.className='terminal-host';tab.element.hidden=!!tab.blockedIntent && !tab.blockedVerified;
          tab.terminal=terminalFactory({cols:event.frame.cols,rows:event.frame.rows,fontSize:getFontSize(),fontFamily:'ProbeNerd, monospace',scrollback:0,disableStdin:true,theme:theme.terminal});
          tab.terminal.parser.registerOscHandler(52,()=>true);tab.terminal.parser.registerOscHandler(8,()=>true);
          render();tab.terminal.open(tab.element);tab.terminal.textarea.setAttribute('inputmode','none');
          tab.terminal.onData(data=>{if(document.activeElement===tab.terminal?.textarea && tab.mode==='direct' && tab.composition.accepts(directToken(tab)))enqueueDirect(tab,new TextEncoder().encode(data));});
          blockPendingKeys(tab.terminal.textarea,()=>tab.directPending && tab.mode!=='direct');
          tab.terminal.textarea.addEventListener('compositionstart',()=>{tab.pasteReadSequence++;tab.composition.begin(directToken(tab));tab.toolbar?.refresh();refreshKeyboard(tab);},true);
          tab.terminal.textarea.addEventListener('compositionend',()=>{tab.composition.end();tab.toolbar?.refresh();refreshKeyboard(tab);},true);
          tab.terminal.textarea.addEventListener('blur',event=>{if(!tab.suppressPasteBlur)tab.pasteFocusRevision++;if(!tab.suppressBlur && tab.directPending){tab.directPending.invalidated=true;tab.inputRevision++;tab.terminal.options.disableStdin=true;tab.terminal.textarea.setAttribute('inputmode','none');}if(!tab.suppressBlur && tab.mode==='direct' && !ownsInputFocus(tab,event?.relatedTarget))void loseDirect(tab);});
          tab.terminal.textarea.addEventListener('paste',event=>void reviewPaste(tab,event,tab.terminal.textarea,tab.composition.token && !tab.composition.ended),true);
        } else if(event.frame.full) {tab.selectionTextReady=false;if(tab.fontDiagnosticsButton)tab.fontDiagnosticsButton.disabled=true;tab.localViewport.capture();tab.terminal.reset();if(tab.terminal.cols!==event.frame.cols || tab.terminal.rows!==event.frame.rows)tab.terminal.resize(event.frame.cols,event.frame.rows);}
        const frame=event.frame;tab.terminal.write(Uint8Array.from(frame.bytes),()=>{
          if(!current(tab,token) || !paneVisible() || event.epoch!==tab.epoch)return;
          const firstBlockedFull=!!tab.blockedIntent && !tab.blockedVerified;
          if(firstBlockedFull && (!frame.full || !tab.blockedBound || !blockedMatches(tab,tab.target) || tab.wantsPause || tab.closing)){void cancel(tab);return;}
          if(!tab.frames.acknowledge(frame.seq)){void cancel(tab);return;}
          if(firstBlockedFull){tab.blockedVerified=true;tab.element.hidden=false;}
          if(frame.full){tab.localViewport.fullRendered();tab.diagnostics.full(tab.target);tab.diagnosticView?.update(tab.diagnostics);}
          tab.selectionTextReady=true;const focusedPane=tabs.activeId===tab.id;if(tab.selectionTextButton)tab.selectionTextButton.disabled=!focusedPane;if(tab.fontDiagnosticsButton)tab.fontDiagnosticsButton.disabled=!focusedPane;
          if(firstBlockedFull)render();
          void invoke('remote_tab_ack',{tabId:tab.id,clientGeneration:token.generation,generation,epoch:event.epoch,seq:frame.seq}).catch(()=>void cancel(tab));
        });
      };
      const pending=invoke('remote_tab_observe',{tabId:tab.id,clientGeneration:token.generation,generation,paneId:tab.target?.paneId || '',terminalId:tab.target?.terminalId || '',canvas,onEvent:channel});
      await pending;
    } catch(error) {if(current(tab,token)){tab.diagnostics.finish(error);status(tab,observationError(error));}}
    finally {if(tabs.get(tab.id)===tab && tab.token===token){tab.diagnostics?.finish();tab.diagnosticView?.update(tab.diagnostics);tab.board.invalidate('disconnected');boardEvent(tab,'stale');tab.selectionReady=false;tabs.invalidate(tab.id);tab.state='disconnected';tab.reviewed=false;tab.closing=false;tab.nativeGeneration=null;tab.inputEpoch=null;render();}}
  }
  function setFont(size) {for(const tab of tabs.list())if(tab.terminal){tab.localViewport.capture();tab.terminal.options.fontSize=size;}}
  function prepareAffected(ids) {const affected=tabs.affected(ids);for(const tab of affected){tab.diagnostics?.finish('host_selection_changed');retireDirectPending(tab);tab.board.invalidate('configuration_changed');boardEvent(tab,'stale');tab.selectionReady=false;tab.suppressBlur=true;tab.invalidated=true;tab.reviewed=false;tab.message='目标或网络配置已变更，请关闭此标签并新建。';tab.inputRevision++;tab.inputBusy=false;tab.inputEpoch=null;tab.mode='observe';tab.queue.clear();if(tab.terminal)tab.terminal.options.disableStdin=true;tabs.invalidate(tab.id);tab.closing=true;tab.state='disconnected';}render();for(const tab of affected)tab.suppressBlur=false;}
  function affected(ids) {for(const tab of tabs.affected(ids)){tab.diagnostics?.finish('host_selection_changed');tab.invalidated=true;tab.reviewed=false;tab.message='目标或网络配置已变更，请关闭此标签并新建。';void cancel(tab);}}
  function background() {for(const tab of tabs.list())tab.pasteReadSequence++;textSelection?.close();textSelection=null;fontDiagnostics?.close(false);fontDiagnostics=null;for(const tab of tabs.list()){tab.pasteReview=null;void cancel(tab);}}
  function prepareHide(){const active=tabs.get(tabs.activeId);if(active)active.pasteReadSequence++;textSelection?.close();textSelection=null;fontDiagnostics?.close(false);fontDiagnostics=null;const tab=tabs.get(tabs.activeId);if(tab)tab.suppressBlur=true;}
  function cancelPrepareHide(){const tab=tabs.get(tabs.activeId);if(tab){tab.suppressBlur=false;if(tab.mode==='direct' && document.activeElement!==tab.terminal?.textarea)void loseDirect(tab);}}
  async function hide() {textSelection?.close();textSelection=null;const tab=tabs.get(tabs.activeId);if(tab && ['connecting','starting','active','resuming'].includes(tab.state))await pause(tab);else if(tab)tab.suppressBlur=false;const partner=splitPartner();if(partner && ['connecting','starting','active','resuming'].includes(partner.state))await pause(partner);}
  globalThis.window?.addEventListener?.('blur',()=>{let changed=false;for(const tab of tabs.list()){tab.pasteFocusRevision++;if(tab.pasteReview){tab.pasteReview=null;changed=true;}}if(changed)render();});
  // ---- 桌面分屏（切片 2）：本地布局开关。沿用 fixture #split 的交互范式与诚实声明——
  // 只变更本地布局；未发送 PTY resize，各面板观察画布保持连接时的选定值（docs/05:137）。 ----
  function updateSplitControl() {
    if(!splitButton)return;
    splitButton.hidden=!(isWide() && tabs.list().length>=2);
    splitButton.setAttribute('aria-pressed',String(splitOn));
  }
  async function setSplit(on) {
    if(on===splitOn)return;
    if(on && (!isWide() || tabs.list().length<2))return;  // 窄窗或不足两个标签：分屏入口不可用
    splitOn=on;
    if(on) {
      splitPartnerId=tabs.list().find(candidate=>candidate.id!==tabs.activeId)?.id || null;
      const partner=tabs.get(splitPartnerId);
      if(partner && partner.state==='paused')await resume(partner);  // 后端可见集允许双观察，仅输入焦点独占
    } else {
      const partner=tabs.get(splitPartnerId);splitPartnerId=null;
      if(partner && ['connecting','starting','active','resuming'].includes(partner.state))await pause(partner);
    }
    render();
  }
  if(splitButton)splitButton.onclick=()=>void setSplit(!splitOn);
  globalThis.window?.addEventListener?.('resize',()=>{
    const wide=isWide();
    if(wide===lastWide)return;
    lastWide=wide;
    // 只在跨越 900px 边界时处理：窄窗回落单面板并暂停分屏侧；回到宽窗恢复副面板。全程不触发远端 resize。
    const partner=splitOn ? tabs.get(splitPartnerId) : null;
    if(!partner){render();return;}
    if(wide){if(partner.state==='paused')void resume(partner);else render();}
    else if(['connecting','starting','active','resuming'].includes(partner.state))void pause(partner);
    else render();
  });
  render();return {create,createBlocked,select,prepareAffected,affected,background,prepareHide,cancelPrepareHide,hide,setFont};
}
