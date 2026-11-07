import {createUnicodeTerminal} from './terminal-unicode.js';
import {createTerminalSelection} from './terminal-selection.js';
import {createFontDiagnostics} from './terminal-font-diagnostics.js';
import { initNetworkUI } from './network-ui.js';
import { initTabWorkspace } from './tab-workspace.js';
import { Terminal } from '@xterm/xterm';
import { invoke, Channel } from '@tauri-apps/api/core';
import { RemoteViewGate, RemoteFrameQueue } from './remote-state.js';
import { SessionDashboard } from './dashboard-watch.js';
import { normalizePrivateKeyInput } from './remote-key.js';
import { previewPairingResponse } from './pairing-view.js';
import { InputComposition, blockPendingKeys } from './input-composition.js';
import { AuxiliaryModifiers, draftBytes, displayDraft } from './input-codec.js';
import { OnlineInputQueue } from './online-input-queue.js';
import { matchedReceipt } from './input-receipt.js';
import { NativeCameraReturn } from './native-camera-return.js';
import { pairingCameraRequest,validatePairingCameraResponse,pairingRequestSummary } from './pairing-camera.js';
import { writePublicRequest } from './public-request-clipboard.js';
import { invalidatePairReview } from './pairing-lifecycle.js';
import { dashboardPresentation, paneStatusText } from './dashboard-presentation.js';
import { initConfigTransfer } from './config-transfer-ui.js';
import { HostDashboardSummary, hostSummaryIdentity, hostSummaryText } from './host-dashboard-summary.js';
import { DirectDashboardSummary } from './direct-dashboard-summary.js';
import { previewPaste, applyPaste } from './paste-review.js';
import { readClipboardForPaste, clipboardPasteMessage } from './mobile-clipboard.js';
import { requestMobileKeyboard } from './mobile-soft-keyboard.js';
import { LocalTerminalViewport, terminalViewportIdentity } from './local-terminal-viewport.js';
import { observationError } from './observation-error.js';
import { initConnectionProfileUI } from './connection-profile-ui.js';

export function initRemote({ native, theme, onFixture, onLeaveFixture, clipboardRead=readClipboardForPaste, keyboardRequest=requestMobileKeyboard, clipboardWrite=writePublicRequest }) {
  const $ = id => document.getElementById(id), gate = new RemoteViewGate();
  let textSelection=null, fontDiagnostics=null, selectTextButton=null, selectionReady=false;
  let terminalFontSize=14, terminal = null, showingRemote = true, pairState = 'none', previewResponse = '', pairBusy = false, scanBusy = false;
  let inputGeneration=null, inputEpoch=null, inputMode='observe', inputBusy=null, inputUnknown=false, inputRevision=0, selectedTarget=null, draftPreview=null, switchingFocus=false;
  let inputComposition=new InputComposition(), focusReset=Promise.resolve(), pasteReview=null, draftRevision=0, draftComposing=false, pasteFocusEpoch=0, pasteReadSequence=0; const onlineInput=new OnlineInputQueue();
  const auxiliaryModifiers=new AuxiliaryModifiers();
  const localViewport=new LocalTerminalViewport();
  let networkRevisions=new Map();
  const hostSummaries=new HostDashboardSummary();
  let pairFingerprint=null;
  let connectionProfiles=null,profileProviderHint=null,pairCamera=null,revocationReview=false,pairReviewIdentity=null,handoffRevision=0,handoffBusy=false;
  const directSummary=new DirectDashboardSummary(event=>onWorkspaceDashboard(event));
  let hostRecords=[], activeHostId=null, hostNavigation=0, hostRefreshRevision=0, unsavedHostOpen=false;
  let draftKey=null, connectionDraftIdentity=null, connectionDraftLabel='', draftTargetLabel='', connectionDraftAuthenticated=false;
  let rejectedSequence=0;
  const runtimeRevokedHosts=new Set();
  const hostDrafts=new Map(), hostStatuses=new Map(), rejectedDrafts=new Map(), pendingDrafts=new Set();
  let hostInitialization=Promise.resolve(false), hostInitError='host_storage_unavailable';
  function initializeHostCatalog() {
    hostInitialization=invoke('host_init').then(()=>true,error=>{
      const known=['host_storage_busy','host_storage_corrupt','host_storage_lock_failed',
        'host_path_bridge_unavailable','host_path_invalid'];
      hostInitError=known.includes(error)?error:'host_storage_unavailable';
      return false;
    });
    return hostInitialization;
  }
  const pairTargetIds = ['remote-host','remote-port','remote-user','remote-session','remote-herdr','remote-socket','remote-pin','pair-device'];
  const pairStatus = message => { $('pair-status').textContent = message; };
  const pairReady = () => pairState === 'authorized-unverified' || pairState === 'waiting-connectivity' || pairState === 'paired';
  function currentRequestRecord() {
    if(!activeHostId || !pairFingerprint || !['awaiting-host','expired','cancelled','authorized-unverified','waiting-connectivity','paired','revoked'].includes(pairState))return null;
    try{return pairingCameraRequest($('pair-request').value,$('remote-user').value,Math.floor(Date.now()/1000),{allowExpired:true});}catch{return null;}
  }
  const forcedRevocation=()=>['expired','cancelled','revoked'].includes(pairState) || pairState==='awaiting-host' && !!currentRequestRecord() && Date.now()>=currentRequestRecord().expires_at*1000;
  const revocationMode=()=>revocationReview || forcedRevocation();
  const responseScope=()=>JSON.stringify({navigation:hostNavigation,activeHostId,target:targetConfig(),device:pairFingerprint,request:$('pair-request').value,pairState,revocation:revocationMode()});
  function validCurrentResponse(raw) {return validatePairingCameraResponse(raw,currentRequestRecord(),pairFingerprint,Math.floor(Date.now()/1000),{state:pairState,revocationOnly:revocationMode()});}
  const requestCopyAllowed=()=>!document.hidden && showingRemote && !$('remote-page').hidden && !gate.pending && !pairBusy && !revocationMode() && pairState==='awaiting-host' && !!currentRequestRecord() && Date.now()<currentRequestRecord().expires_at*1000;
  function clearHandoff() {handoffRevision++;$('pair-handoff-status').textContent='';}
  pairCamera=new NativeCameraReturn({purpose:'pairing-response',snapshot:responseScope,
    allowed:()=>showingRemote && !$('remote-page').hidden && !gate.pending && !pairBusy && pairState!=='revoked' && !!currentRequestRecord(),
    validate:validCurrentResponse,
    onExpire:()=>{pairStatus('本次响应扫描已过期；原记录仍可用于独立审查新鲜的匹配撤销回执。');render();}});

  const stages = { connecting:'连接 SSH，等待服务器身份核验…', 'host-key-verified':'预期主机公钥已匹配，开始临时公钥认证…', authenticated:'认证完成，读取指定 socket 的会话快照…', 'snapshot-received':'快照已读取，请选择目标 pane…', 'full-frame-received':'完整画面已校验，正在关闭连接…' };

  function status(message, tone='info') { $('remote-status').textContent=message; $('remote-status').dataset.tone=tone; }
  // Network intent survives target corrections; trust and preview leases do not.
  const currentProfileProvider=()=>profileProviderHint;
  const declaredProvider=()=>hostRecords.find(h=>h.id===activeHostId)?.provider || currentProfileProvider();
  const requiresNetworkBinding=()=>{
    const host=hostRecords.find(h=>h.id===activeHostId);
    return host ? host.requiresNetworkBinding===true && !host.networkProfileId : ['tailscale','easytier','zerotier'].includes(currentProfileProvider());
  };
  function render() {
    $('remote-fields').disabled=gate.pending || pairBusy;
    for(const id of pairTargetIds) $(id).readOnly=pairState!=='none';
    $('pair-target-review').disabled=pairState!=='none';
    $('pair-mode').disabled=pairState==='restore-required';
    $('remote-connect').disabled=revocationMode() || pairState==='revoked' || requiresNetworkBinding() || !native || pairBusy || gate.pending || !gate.reviewed || ($('pair-mode').checked && !pairReady());
    $('pair-controls').hidden=!$('pair-mode').checked; $('manual-key-section').hidden=$('pair-mode').checked;
    $('remote-private-key').required=!$('pair-mode').checked;
    $('pair-scan').disabled=!native || scanBusy || document.hidden || gate.pending || pairBusy || pairState==='revoked' || !currentRequestRecord();
    $('pair-preview').disabled=document.hidden || gate.pending || pairBusy;
    $('pair-preview').textContent=pairCamera?.held ? '重新查看本次响应扫描' : '查看响应内容';
    $('pair-create').disabled=revocationMode() || !native || gate.pending || pairState!=='none' || !$('pair-target-review').checked;
    let responseReady=false;try{responseReady=!!previewResponse && pairReviewIdentity===responseScope() && !!validCurrentResponse(previewResponse);}catch{}
    $('pair-accept').disabled=!native || gate.pending || pairBusy || document.hidden || !responseReady || !$('pair-source-review').checked;
    const record=currentRequestRecord();$('pair-request-summary').hidden=!record;
    $('pair-request-summary').textContent=record?pairingRequestSummary(record,pairFingerprint,pairState):'';
    $('pair-request-copy').disabled=handoffBusy || !requestCopyAllowed();$('pair-request-select').disabled=!requestCopyAllowed();
    $('pair-revocation-mode').checked=revocationMode();$('pair-revocation-mode').disabled=forcedRevocation() || gate.pending || pairBusy;
    $('pair-review-mode-note').textContent=pairState==='revoked'?'原设备已在本次运行登记撤销；只保留原记录供核对或显式清理，不能连接或重新授权。':revocationMode()?'当前仅可审查原记录的新鲜撤销回执；授权响应、创建设备和连接均已锁定。主机授权须由主机用户处理，本机取消或登记回执不会操作远端授权文件。':pairState==='awaiting-host'?'原请求有效期内可审查首次授权或撤销响应。':'原记录已处理；响应区只接受新鲜的匹配撤销回执。已授权设备的正常连接仍需单独审查并主动发起。';
    $('pair-reset').disabled=!native || gate.pending || pairState==='none' || pairState==='restore-required';
    $('host-save').disabled=!native || gate.pending || pairBusy; $('host-save-name').disabled=gate.pending || pairBusy;
    $('host-restore').disabled=!native || gate.pending || pairBusy || !$('host-restore-review').checked;
    $('pair-cancel').disabled=!native || gate.pending || pairState==='none' || pairState==='cancelled' || pairState==='revoked' || pairState==='restore-required' || pairState==='storage-failed';
    $('remote-cancel').disabled=!gate.pending;
    $('remote-review').checked=gate.reviewed;
    const overlay=requiresNetworkBinding();
    $('remote-profile-network-note').textContent=overlay
      ? `此资料声明 ${declaredProvider()}：请保存主机，在网络配置中独立审查并绑定本机网络，再返回配对页主动连接。未绑定时不会借用系统直连。`
      : '网络声明仅供核对，不会自动选择本机节点或绑定网络。Tailscale、EasyTier、ZeroTier 需在网络配置中单独审查、授权与绑定。';
    connectionProfiles?.render();
  }
  function clearSnapshot() { localViewport.detach(); invalidateInput(); selectTextButton?.remove?.(); selectTextButton=null; terminal?.dispose(); terminal=null; $('remote-terminal').replaceChildren(); $('remote-result').hidden=true; $('remote-dashboard').hidden=true; $('remote-panes').replaceChildren(); }
  function discardKey() { $('remote-private-key').value=''; }
  function cancel(reason='本次读取已取消。迟到结果不会显示。',nativeCameraBackground=false) {
    // Each camera purpose owns a bounded return lease for public bytes only.
    // SSH, authorization reviews, input and temporary keys still lose authority.
    if(!nativeCameraBackground){connectionProfiles?.invalidate();pairCamera?.discard();}
    clearHandoff();pairReviewIdentity=null;
    localViewport.capture();
    const clientGeneration=gate.pendingGeneration;
    directSummary.finish(clientGeneration);
    previewResponse=invalidatePairReview($('pair-source-review'),$('pair-response-preview')); if(pairState==='none') $('pair-target-review').checked=false; const discarded=invalidateInput(); recordUnsent(discarded.count); gate.invalidate(); discardKey(); if ($('pair-mode').checked && gate.pending && pairState!=='paired') { pairState='cancelled'; pairStatus('已取消；主机授权状态可能未知，请核查清理。'); } $('remote-dashboard').hidden=true; if(terminal) $('remote-captured').textContent='观察已停止 · 画面陈旧'; status(reason+(discarded.count?` ${discarded.count} 笔待发送输入已丢弃。`:'')); render();
    // Invalidating precedes asynchronous cleanup. Keep busy until the old invoke settles.
    if (gate.pending && native) void invoke('remote_cancel',{clientGeneration}).catch(()=>{if(gate.pendingGeneration===clientGeneration)status('正在结束旧连接；结束前不可开始新读取。','warning');});
  }
  $('remote-form').addEventListener('input', event => {
    clearHandoff();
    if(event.target.id==='pair-revocation-mode')revocationReview=event.target.checked;
    if(!['pair-target-review','pair-source-review','remote-review','host-restore-review'].includes(event.target.id)){pairReviewIdentity=null;previewResponse=invalidatePairReview($('pair-source-review'),$('pair-response-preview'));}
    if(!['pair-target-review','pair-source-review','remote-review','host-restore-review'].includes(event.target.id))pairCamera?.discard();
    if (event.target.id.startsWith('connection-profile-')) return;
    if (event.target.id==='host-save-name') return;
    if (pairTargetIds.includes(event.target.id) && pairState==='none') $('pair-target-review').checked=false;
    if (event.target.id==='pair-mode') { $('remote-private-key').required=!event.target.checked; }
    if (['pair-target-review','pair-source-review','host-restore-review'].includes(event.target.id)) { render(); return; }
    if (event.target.id==='pair-response') {  previewResponse=''; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; render(); return; }
    if (event.target.id==='remote-review') { gate.reviewed=event.target.checked; render(); return; }
    saveHostDraft(); clearDraftBinding(); gate.invalidate(); clearSnapshot(); render();
  });
  function recordUnsent(count) {if(!count)return; const box=$('remote-unsent-notices'), line=document.createElement('p'); const name=hostRecords.find(h=>h.id===activeHostId)?.name || '当前目标'; line.textContent=`${name}：${count} 笔输入未发送，未自动重放。`; box.append(line); while(box.children.length>10)box.firstElementChild.remove(); box.hidden=false;}
  function keyboardEditor() {
    if(fontDiagnostics?.valid() || document.hidden || !showingRemote || inputGeneration===null || !terminal || !selectedTarget || inputUnknown)return null;
    if(inputMode==='direct' && inputEpoch!==null)return terminal.textarea;
    if(inputMode==='draft' && inputEpoch!==null)return $('remote-input-draft');
    return null;
  }
  function renderKeyboardActions() {
    const editor=keyboardEditor();
    $('remote-keyboard-show').disabled=!editor || !!inputBusy || !!textSelection?.valid() || (inputMode==='direct' ? !!inputComposition.token && !inputComposition.ended : draftComposing);
    // A permission request can be cancelled by hiding before it resolves.
    const pendingEditor=terminal && !document.hidden && showingRemote && inputGeneration!==null && selectedTarget && (document.activeElement===terminal.textarea && terminal.options.disableStdin===false || document.activeElement===$('remote-input-draft') && !$('remote-input-draft-area').hidden);
    $('remote-keyboard-hide').disabled=!editor && !pendingEditor;
  }
  function inputStatus(text) { $('remote-input-status').textContent=text; renderAuxiliary();renderKeyboardActions(); }
  function auxiliaryAllowed() {return currentDirect(inputToken()) && !inputBusy;}
  function renderAuxiliary() {
    const allowed=auxiliaryAllowed();
    if(!allowed)auxiliaryModifiers.reset();
    for(const name of ['ctrl','alt']) {
      const button=$('remote-modifier-'+name); button.disabled=!allowed;
      button.setAttribute('aria-pressed',String(auxiliaryModifiers[name]));
    }
    $('remote-modifier-cancel').disabled=!allowed || !auxiliaryModifiers.held;
    $('remote-combination-bases').hidden=!auxiliaryModifiers.held;
    for(const button of $('remote-input-keys').querySelectorAll('button[data-remote-key]'))button.disabled=!allowed;
    $('remote-modifier-status').textContent=auxiliaryModifiers.held
      ? `${auxiliaryModifiers.ctrl?'Ctrl ':''}${auxiliaryModifiers.alt?'Alt ':''}保持；选择一个辅助基础键后释放。终端输入法文字不受影响。`
      : '组合键已释放；仅影响下一次辅助基础键。';
  }
  function releaseAuxiliary() {auxiliaryModifiers.reset();renderAuxiliary();}
  function clearPasteReview() {pasteReview=null;$('remote-paste-review').hidden=true;$('remote-paste-preview').textContent='';$('remote-paste-status').textContent='';}
  function invalidateInput() {
    textSelection?.close();textSelection=null;fontDiagnostics?.close(false);fontDiagnostics=null;selectionReady=false;$('remote-font-diagnostics').disabled=true;
    clearPasteReview();draftComposing=false;
    const discarded=onlineInput.clear(); inputRevision++; inputGeneration=null; inputEpoch=null; inputMode='observe'; draftPreview=null; inputBusy=null;
    releaseAuxiliary();
    $('remote-input-controls').hidden=true; $('remote-input-preview-area').hidden=true;
    if(terminal) {terminal.options.disableStdin=true; terminal.textarea?.setAttribute('inputmode','none');}
    renderKeyboardActions();return discarded;
  }
  function loseInputFocus() {
    clearPasteReview();
    auxiliaryModifiers.reset();
    if(inputGeneration===null)return;
    const generation=inputGeneration; const discarded=onlineInput.clear(); recordUnsent(discarded.count); inputRevision++; inputEpoch=null; inputMode='observe'; draftPreview=null;
    if(terminal) {terminal.options.disableStdin=true; terminal.textarea.setAttribute('inputmode','none');}
    if(inputBusy) {inputUnknown=true; $('remote-input-recover').hidden=false; inputStatus(`输入进行时失去焦点：结果未知，需重新连接原目标并核实。${discarded.count?` ${discarded.count} 笔未发送。`:''}`);}
    else inputStatus(`焦点已离开；输入已锁定。${discarded.count?` ${discarded.count} 笔未发送。`:''}`);
    focusReset=invoke('remote_input_mode',{generation,mode:'observe',focused:false}).catch(()=>{});
  }
  async function changeInputMode(mode) {
    clearPasteReview();
    releaseAuxiliary();
    if(fontDiagnostics?.valid() || textSelection?.valid() || document.hidden || inputGeneration===null || !terminal || (inputUnknown && mode!=='observe'))return;
    if(inputBusy) {loseInputFocus();return;}
    const discarded=onlineInput.clear(); recordUnsent(discarded.count);
    const generation=inputGeneration, revision=++inputRevision; inputEpoch=null; inputMode='observe'; draftPreview=null;
    renderAuxiliary();
    if(discarded.count)inputStatus(`${discarded.count} 笔未发送输入已丢弃。`);
    $('remote-input-preview-area').hidden=true; $('remote-input-draft-area').hidden=mode!=='draft';
    // Request the editable control within the user gesture. Until the native
    // reply, inputMode stays observe and compositions start without a lease.
    const expected=mode==='draft'?$('remote-input-draft'):terminal.textarea;
    terminal.options.disableStdin=mode!=='direct';
    terminal.textarea.setAttribute('inputmode',mode==='direct'?'text':'none');
    if(mode==='direct')inputStatus('正在核验逐键输入许可；请等待确认后输入。');
    switchingFocus=true;
    try {
      if(mode==='draft')expected.focus();else terminal.focus();
    } finally {switchingFocus=false;}
    renderKeyboardActions();
    const current=()=>revision===inputRevision && generation===inputGeneration;
    const focused=()=>!document.hidden && document.activeElement===expected;
    let timer;
    try {
      await Promise.race([focusReset,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('focus_reset_timeout')),5000);})]);
      if(!current())return;
      if(!focused())throw Error('focus_lost');
      const epoch=await invoke('remote_input_mode',{generation,mode,focused:true});
      if(!current())return;
      if(!focused() || !Number.isSafeInteger(epoch) || epoch<1)throw Error('input_lease_invalid');
      inputEpoch=epoch; inputMode=mode;
      inputStatus(mode==='direct'?'逐键输入已启用；每次输入单独发送。':mode==='draft'?'草稿仅在核对并确认后发送。':'观察模式不发送输入。');
    } catch {
      if(current()) {
        loseInputFocus();
        inputStatus('输入模式不可用；请重新选择。');
      }
    } finally {clearTimeout(timer);}
  }
  function inputToken() {return {generation:inputGeneration,epoch:inputEpoch,revision:inputRevision};}
  function currentDirect(token) {return !fontDiagnostics?.valid() && !textSelection?.valid() && !document.hidden && inputGeneration!==null && inputEpoch!==null && !inputUnknown && inputMode==='direct' && document.activeElement===terminal?.textarea && OnlineInputQueue.same(token,inputToken());}
  function queueDirect(bytes) {
    const token=inputToken();
    if(!currentDirect(token)) {inputStatus('本次输入未发送：焦点或输入许可已失效。');return;}
    if(!onlineInput.push(token,bytes)) {
      const discarded=onlineInput.clear(); recordUnsent(discarded.count+1);
      if(inputBusy) {inputUnknown=true; cancel(`输入队列达到上限；${discarded.count+1} 笔未发送，在途结果需核实。`);}
      else {loseInputFocus();inputStatus(`输入队列达到上限；${discarded.count+1} 笔未发送，请重新选择模式。`);}
      return;
    }
    void pumpDirect();
  }
  async function pumpDirect() {
    if(inputBusy)return;
    const token=inputToken(); if(!currentDirect(token)){const lost=onlineInput.clear();if(lost.count){recordUnsent(lost.count);inputStatus(`${lost.count} 笔未发送输入已丢弃。`);}return;}
    const item=onlineInput.take(token);if(!item)return;
    const sending=sendInput(item.bytes,false,item.token);renderAuxiliary();
    await sending;renderAuxiliary();
  }
  async function sendInput(bytes,draft,token=inputToken()) {
    if(textSelection?.valid() || inputGeneration===null || inputEpoch===null || inputUnknown || inputBusy || !bytes.length || bytes.length>4096 || !OnlineInputQueue.same(token,inputToken()) ||
       (draft ? inputMode!=='draft' || document.activeElement!==$('remote-input-draft') : !currentDirect(token))) {
      const lost=onlineInput.clear();recordUnsent(lost.count+1);inputStatus(`本次输入未发送：输入许可或字节上限不满足。${lost.count?` 另有 ${lost.count} 笔未发送。`:''}`);return;
    }
    if(draft && rejectedDrafts.size+pendingDrafts.size>=32) {
      inputStatus('未发送文本找回区已满；请先处理并移除一条，再发送草稿。');return;
    }
    const generation=token.generation, epoch=token.epoch, owner={}; inputBusy=owner; let proceed=false;
    // Remove the submitted text before the first await. A tab change can now
    // save only the still-unsent draft, even if the reply is lost.
    const editor = $('remote-input-draft');
    const submitted = draft ? { key:draftKey, text:editor.value, target:selectedTarget && {...selectedTarget}, label:draftTargetLabel, revision:draftRevision+1, removed:false } : null;
    if(submitted)pendingDrafts.add(submitted);
    if (draft) {
      editor.value = '';
      draftRevision++;
      if (draftKey) hostDrafts.delete(draftKey);
    }
    try {
      const result=await invoke('remote_input_send',{generation,epoch,bytes:Array.from(bytes),draft});
      if(result?.status==='rejected')recoverRejected(submitted, !result.recoveryRequired);
      if(generation!==inputGeneration || !OnlineInputQueue.same(token,inputToken()))return;
      const receipt=result?.status==='accepted'?matchedReceipt(result.receipt,selectedTarget,bytes.length):null;
      if (result?.recoveryRequired && (receipt || result.status === 'rejected')) {
        if (receipt) $('remote-input-status').dataset.receipt = JSON.stringify(receipt);
        inputUnknown = true;
        cancel((receipt ? '服务器已接收入队' : '服务器已明确拒绝') +
          ' · 本机发送记录待核实，输入已锁定。');
        return;
      }
      if(result?.status==='unknown') {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
      else if(result?.status==='rejected') {const lost=onlineInput.clear();recordUnsent(lost.count);if(inputBusy===owner)inputBusy=null;loseInputFocus();inputStatus(`服务器明确拒绝本笔；原文已恢复或可在未发送文本中找回。${lost.count?` ${lost.count} 笔后续输入未发送。`:''}`);}
      else if(receipt) {
        $('remote-input-status').dataset.receipt=JSON.stringify(receipt);
        proceed=!draft;inputStatus(`服务器已接收入队 · ${receipt.paneId} · ${receipt.acceptedBytes} 字节。执行结果请查看终端。`);
      }
      else {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
    } catch(error) {
      const knownUnsent=['input_stale','input_invalid_size','input_storage_unavailable','input_recovery_required'].includes(String(error));
      if(knownUnsent)recoverRejected(submitted, String(error)!=='input_recovery_required');
      if(generation!==inputGeneration || !OnlineInputQueue.same(token,inputToken()))return;
      if(knownUnsent) {const lost=onlineInput.clear();recordUnsent(lost.count+1);if(inputBusy===owner)inputBusy=null;loseInputFocus();inputStatus(`本次输入未发送或许可不可用；原文已恢复或可在未发送文本中找回。${lost.count?` ${lost.count} 笔后续输入未发送。`:''}`);}
      else {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
    } finally {if(submitted)pendingDrafts.delete(submitted);if(inputBusy===owner)inputBusy=null; if(proceed && inputGeneration===generation && OnlineInputQueue.same(token,inputToken())) {if(currentDirect(token))void pumpDirect();else {const lost=onlineInput.clear();if(inputGeneration!==null)loseInputFocus();if(lost.count){recordUnsent(lost.count);inputStatus(`${lost.count} 笔未发送输入已丢弃。`);}}}}
  }
  function showInputPreview() {
    if(fontDiagnostics?.valid())return;
    const text=$('remote-input-draft').value;
    if(draftComposing){inputStatus('输入法组合尚未结束，请完成后再预览。');return;}
    const bracketed=terminal?.modes.bracketedPasteMode===true;
    if(inputMode!=='draft' || !draftBytes(text,bracketed)) {inputStatus('草稿为空、超过 4096 字节或含不支持的粘贴结束序列。');return;}
    draftPreview={text,bracketed}; $('remote-input-preview-text').textContent=displayDraft(text); $('remote-input-preview-area').hidden=false;
    inputStatus(bracketed?'目标启用括号粘贴；确认后发送文本及保护序列。':'目标未启用括号粘贴；确认后直接发送文本。');
  }
  $('remote-input-observe').onclick=()=>void changeInputMode('observe');
  $('remote-input-direct').onclick=()=>void changeInputMode('direct');
  $('remote-input-draft-mode').onclick=()=>void changeInputMode('draft');
  for(const id of ['remote-keyboard-show','remote-keyboard-hide']) $(id).addEventListener('pointerdown',e=>e.preventDefault());
  $('remote-keyboard-show').onclick=()=>{
    renderKeyboardActions();if($('remote-keyboard-show').disabled)return;
    const editor=keyboardEditor();if(!editor)return;
    const token=inputToken(), mode=inputMode, target=selectedTarget, boundTerminal=terminal;
    if(editor===terminal?.textarea)terminal.focus();else editor.focus();
    keyboardRequest('show',editor,()=>keyboardEditor()===editor && terminal===boundTerminal && selectedTarget===target && inputMode===mode && OnlineInputQueue.same(token,inputToken()) && document.activeElement===editor);
    inputStatus('已请求展开键盘；是否显示由系统决定。');
  };
  $('remote-keyboard-hide').onclick=()=>{
    renderKeyboardActions();if($('remote-keyboard-hide').disabled)return;
    const active=document.activeElement, editor=keyboardEditor();
    if(active!==editor && active!==terminal?.textarea && active!==$('remote-input-draft'))return;
    const revision=inputRevision, generation=inputGeneration, clientGeneration=gate.pendingGeneration, target=selectedTarget, boundTerminal=terminal;
    keyboardRequest('hide',active,()=>!document.hidden && showingRemote && gate.accepts(clientGeneration,generation) && inputGeneration===generation && terminal===boundTerminal && selectedTarget===target && (inputRevision===revision || inputRevision===revision+1 && inputMode==='observe') && (document.activeElement===active || document.activeElement===document.body || document.activeElement==null));
    active.blur();
    if(inputRevision===revision)loseInputFocus();
    inputStatus('已收起输入焦点；重新输入请先选择输入模式。');
  };

  $('remote-input-draft').addEventListener('blur',()=>{if(!switchingFocus)loseInputFocus();});
  $('remote-input-draft').addEventListener('input',()=>{draftRevision++;clearPasteReview();draftPreview=null; $('remote-input-preview-area').hidden=true;});
  $('remote-input-draft').addEventListener('compositionstart',()=>{pasteReadSequence++;draftComposing=true;renderKeyboardActions();});
  $('remote-input-draft').addEventListener('compositionend',()=>{draftComposing=false;renderKeyboardActions();});
  $('remote-input-draft').addEventListener('paste',event=>{
    event.preventDefault();event.stopImmediatePropagation();
    pasteReadSequence++;
    const text=event.clipboardData?.types && !Array.from(event.clipboardData.types).includes('text/plain') ? '' : event.clipboardData?.getData('text/plain') || '';
    void reviewLocalPaste(terminal,text,$('remote-input-draft'));
  },true);
  window.addEventListener('blur',()=>{
    pasteFocusEpoch++;clearPasteReview();
    if(inputEpoch!==null || inputBusy)loseInputFocus();
  });
  window.addEventListener('offline',()=>{if(gate.pending)cancel('网络已断开，观察已停止；重新连接需主动核验。');});
  for(const id of ['remote-input-preview','remote-input-confirm', 'remote-input-recover','remote-read-paste']) $(id).addEventListener('pointerdown',e=>e.preventDefault());
  $('remote-read-paste').onclick=async()=>{
    const origin=inputMode==='direct'?terminal?.textarea:$('remote-input-draft');
    const mode=inputMode, boundTerminal=terminal, generation=inputGeneration, epoch=inputEpoch, revision=inputRevision;
    const target=selectedTarget, hostId=activeHostId, clientGeneration=gate.pendingGeneration;
    const draftVersion=draftRevision, original=$('remote-input-draft').value, focusEpoch=pasteFocusEpoch;
    const sequence=++pasteReadSequence;
    const valid=()=>sequence===pasteReadSequence && showingRemote && !document.hidden && terminal===boundTerminal &&
      selectedTarget===target && !!target && activeHostId===hostId && gate.accepts(clientGeneration,generation) &&
      inputGeneration===generation && inputEpoch===epoch && epoch!==null && inputRevision===revision && inputMode===mode &&
      ['draft','direct'].includes(mode) && !inputUnknown && !inputBusy && document.activeElement===origin &&
      draftRevision===draftVersion && $('remote-input-draft').value===original && pasteFocusEpoch===focusEpoch &&
      !(mode==='direct' ? inputComposition.token && !inputComposition.ended : draftComposing);
    if(!valid()){inputStatus('请先启用输入模式并完成输入法组合，再粘贴。');return;}
    try {
      const text=await clipboardRead();
      if(!valid())return;
      if(typeof text!=='string' || !text){inputStatus('剪贴板没有可用的纯文本。');return;}
      await reviewLocalPaste(boundTerminal,text,origin);
    } catch (error) {if(valid())inputStatus(clipboardPasteMessage(error));}
  };
  function pasteReviewCurrent(review) {
    return pasteReview===review && showingRemote && !document.hidden && gate.accepts(review.clientGeneration,review.generation) &&
      inputGeneration===review.generation && inputRevision===review.revision && inputMode==='observe' && !inputUnknown && !inputBusy &&
      terminal===review.terminal && selectedTarget===review.target && activeHostId===review.hostId &&
      draftRevision===review.draftRevision && pasteFocusEpoch===review.focusEpoch && $('remote-input-draft').value===review.original;
  }
  async function reviewLocalPaste(boundTerminal,text,origin) {
    const editor=$('remote-input-draft'), direct=origin===boundTerminal?.textarea;
    if(!selectedTarget || !boundTerminal || terminal!==boundTerminal || (direct ? inputMode!=='direct' : !['draft','observe'].includes(inputMode)) || inputBusy || inputUnknown)return;
    if(!text){inputStatus('剪贴板没有可用的纯文本。');return;}
    if((direct && inputComposition.token && !inputComposition.ended) || (!direct && draftComposing)){inputStatus('输入法组合尚未结束，请完成后再粘贴。');return;}
    if(typeof text!=='string' || text.length>4096 || new TextEncoder().encode(text).length>4096){inputStatus('粘贴内容超过 4096 字节；原草稿保留。');return;}
    const original=editor.value, revision=draftRevision, focusEpoch=pasteFocusEpoch, target=selectedTarget, hostId=activeHostId;
    const generation=inputGeneration, clientGeneration=gate.pendingGeneration;
    if(!target || document.activeElement!==origin || document.hidden || !gate.accepts(clientGeneration,generation))return;
    let preview;try {preview=previewPaste(text);} catch {inputStatus('粘贴内容不可审查。');return;}
    if(typeof preview!=='string'){inputStatus('粘贴内容不可审查。');return;}
    loseInputFocus();const nextRevision=inputRevision;
    await focusReset;
    if(terminal!==boundTerminal || selectedTarget!==target || activeHostId!==hostId || inputGeneration!==generation || inputRevision!==nextRevision ||
       !showingRemote || document.hidden || document.activeElement!==origin || pasteFocusEpoch!==focusEpoch || draftRevision!==revision ||
       $('remote-input-draft').value!==original || inputUnknown || inputBusy || !gate.accepts(clientGeneration,generation))return;
    pasteReview={terminal:boundTerminal,target,hostId,generation,clientGeneration,revision:nextRevision,draftRevision:revision,focusEpoch,original,text};
    $('remote-paste-preview').textContent=preview;
    $('remote-paste-target').textContent=`目标：${target.paneId} · ${target.terminalId}`;
    const appendAllowed=applyPaste(original,text,'append')!==null;
    const replaceAllowed=applyPaste(original,text,'replace')!==null;
    $('remote-paste-append').disabled=!appendAllowed;
    $('remote-paste-replace').disabled=!replaceAllowed;
    $('remote-paste-status').textContent=appendAllowed?'':'追加后超过 4096 字节或内容不可用；可替换或取消。';
    $('remote-paste-review').hidden=false;
    switchingFocus=true;try {$(appendAllowed?'remote-paste-append':replaceAllowed?'remote-paste-replace':'remote-paste-cancel').focus();} finally {switchingFocus=false;}
    inputStatus('请审查粘贴内容；尚未发送。');
  }
  function choosePaste(choice) {
    const review=pasteReview;
    if(!review || !pasteReviewCurrent(review)){clearPasteReview();return;}
    if(choice==='cancel'){clearPasteReview();inputStatus('已取消粘贴，原草稿保留。');return;}
    const updated=applyPaste(review.original,review.text,choice);
    if(updated===null){$('remote-paste-status').textContent='合并后草稿超过 4096 字节或内容不可用；原草稿保留。';return;}
    $('remote-input-draft').value=updated;draftRevision++;draftPreview=null;$('remote-input-preview-area').hidden=true;
    clearPasteReview();$('remote-input-draft-area').hidden=false;
    inputStatus('已更新本地草稿；请先选择草稿模式，再单独预览并确认发送。');
  }
  $('remote-paste-append').onclick=()=>choosePaste('append');
  $('remote-paste-replace').onclick=()=>choosePaste('replace');
  $('remote-paste-cancel').onclick=()=>choosePaste('cancel');
  $('remote-paste-review').addEventListener('focusout',event=>{if(pasteReview && !$('remote-paste-review').contains(event.relatedTarget))clearPasteReview();});
  $('remote-input-preview').onclick=showInputPreview;
  $('remote-input-confirm').onclick=()=>{if(fontDiagnostics?.valid())return;if(draftComposing){inputStatus('输入法组合尚未结束，请完成后再确认。');return;} if(draftPreview===null || draftPreview.text!==$('remote-input-draft').value || draftPreview.bracketed!==(terminal?.modes.bracketedPasteMode===true)) {draftPreview=null; $('remote-input-preview-area').hidden=true; inputStatus('终端粘贴模式或文本已变化，请重新预览。'); return;} const bytes=draftBytes(draftPreview.text,draftPreview.bracketed); draftPreview=null; $('remote-input-preview-area').hidden=true; if(bytes)void sendInput(bytes,true);};
  for(const name of 'abcdefghijklmnopqrstuvwxyz') {
    const button=document.createElement('button');button.type='button';button.dataset.remoteKey=name;
    button.textContent=name.toUpperCase();$('remote-combination-bases').append(button);
  }
  const space=document.createElement('button');space.type='button';space.dataset.remoteKey='space';space.textContent='Space';$('remote-combination-bases').append(space);
  for(const button of $('remote-input-keys').querySelectorAll('button'))button.addEventListener('pointerdown',e=>e.preventDefault());
  for(const name of ['ctrl','alt'])$('remote-modifier-'+name).onclick=()=>{auxiliaryModifiers.toggle(name,auxiliaryAllowed());renderAuxiliary();};
  $('remote-modifier-cancel').onclick=releaseAuxiliary;
  for(const button of $('remote-input-keys').querySelectorAll('button[data-remote-key]'))button.onclick=()=>{
    const allowed=auxiliaryAllowed();
    const key=auxiliaryModifiers.take(button.dataset.remoteKey,terminal?.modes.applicationCursorKeysMode===true,allowed);
    renderAuxiliary();if(key!==null)queueDirect(new TextEncoder().encode(key));
    else if(allowed)inputStatus('此辅助组合未定义，未发送；组合键已释放。');
  };
  renderAuxiliary();
  $('remote-input-recover').onclick=async()=>{
    if(!inputUnknown || inputBusy || inputGeneration===null || !terminal)return;
    await changeInputMode('observe'); if(inputEpoch===null)return;
    try {await invoke('remote_input_recover',{generation:inputGeneration,epoch:inputEpoch}); inputUnknown=false; inputEpoch=null; $('remote-input-recover').hidden=true; inputStatus('已核实原目标；请重新选择输入模式。');}
    catch {inputStatus('只能在重新连接并核实原目标后恢复。');}
  };
  function hostMessage(message) { $('host-home-status').textContent=message; if(!$('remote-page').hidden)status(message,'warning'); }
  function targetConfig() {return {schemaVersion:1,host:$('remote-host').value,port:Number($('remote-port').value),username:$('remote-user').value,expectedHostKey:$('remote-pin').value,privateKeyPem:'',socketPath:$('remote-socket').value,herdrPath:$('remote-herdr').value,session:$('remote-session').value,paneId:'',reviewConfirmed:true};}
  function draftOwner(key) {
    try {
      const identity=JSON.parse(key)[0];
      return identity[0]==='saved' ? JSON.parse(identity[1]).id : null;
    } catch { return null; }
  }
  function renderRejectedDrafts() {
    const section=$('remote-rejected-drafts'); section.replaceChildren();
    section.hidden=rejectedDrafts.size===0;
    for(const [id,entry] of rejectedDrafts) {
      const label=document.createElement('label');
      label.textContent=`未发送文本 · ${entry.label} · ${entry.target.paneId} · ${entry.target.terminalId}（只读，可复制）`;
      const text=document.createElement('textarea'); text.readOnly=true; text.value=entry.text;
      text.setAttribute('aria-label',label.textContent); label.append(text); section.append(label);
      const remove=document.createElement('button'); remove.type='button';
      remove.textContent='移除此条未发送文本';
      remove.setAttribute('aria-label',`移除 ${entry.label} · ${entry.target.paneId} · ${entry.target.terminalId} 的未发送文本`);
      remove.onclick=()=>{if(rejectedDrafts.get(id)===entry){rejectedDrafts.delete(id);renderRejectedDrafts();}};
      section.append(remove);
    }
  }
  function recoverRejected(submitted, allowEditor) {
    if(!submitted?.key || !submitted.text || !submitted.target || submitted.removed)return;
    if(allowEditor && draftKey===submitted.key && draftRevision===submitted.revision && !$('remote-input-draft').value) {
      $('remote-input-draft').value=submitted.text; draftRevision++;
      return;
    }
    // Each pending send reserved one slot; retain its exact text independently.
    rejectedDrafts.set(++rejectedSequence,submitted);
    renderRejectedDrafts();
  }
  function removeHostDrafts(hostId) {
    if(draftKey && draftOwner(draftKey)===hostId)clearDraftBinding();
    for(const key of hostDrafts.keys())if(draftOwner(key)===hostId)hostDrafts.delete(key);
    for(const [id,entry] of rejectedDrafts)if(draftOwner(entry.key)===hostId)rejectedDrafts.delete(id);
    for(const entry of pendingDrafts)if(draftOwner(entry.key)===hostId)entry.removed=true;
    renderRejectedDrafts();
  }
  function saveHostDraft() {
    if (draftKey && JSON.parse(draftKey)[0][0]==='saved') {
      const value=$('remote-input-draft').value;
      if(value)hostDrafts.set(draftKey,value);else hostDrafts.delete(draftKey);
    }
    if(activeHostId && !$('remote-page').hidden)hostStatuses.set(activeHostId,gate.pending || terminal ? '上次观察已停止，重新查看需主动连接。' : $('remote-status').textContent);
  }
  function clearDraftBinding() {
    draftKey=null; selectedTarget=null; $('remote-input-draft').value=''; draftRevision++;
    draftPreview=null; clearPasteReview(); $('remote-input-preview-area').hidden=true;
  }
  function bindDraft(pane) {
    saveHostDraft();
    const identity=connectionDraftAuthenticated ? connectionDraftIdentity : ['manual',gate.pendingGeneration];
    draftKey=JSON.stringify([identity,pane.paneId,pane.terminalId]);
    const origin=identity[0]==='saved' ? `已存主机 ${JSON.parse(identity[1]).id}` : `手动连接第 ${gate.pendingGeneration} 次`;
    draftTargetLabel=`${origin} ${connectionDraftLabel}`;
    $('remote-input-draft').value=hostDrafts.get(draftKey) || '';
    draftRevision++; draftPreview=null; clearPasteReview();
    $('remote-input-preview-area').hidden=true;
  }
  function reviewedDraftIdentity(config,generation) {
    const host=hostRecords.find(record=>record.id===activeHostId);
    const identity=host && hostSummaryIdentity(summaryHost(host));
    const keys=['host','port','username','expectedHostKey','socketPath','herdrPath','session'];
    if ($('pair-mode').checked && identity && pairFingerprint===host.deviceFingerprint &&
        keys.every(key=>host.target[key]===config[key])) return ['saved',identity];
    return ['manual',generation];
  }
  function fillHost(target) {
    profileProviderHint=null;$('remote-profile-provider').value='';
    for(const [field,key] of [['host','host'],['port','port'],['user','username'],['session','session'],['herdr','herdrPath'],['socket','socketPath'],['pin','expectedHostKey']]) $('remote-'+field).value=target[key] ?? '';
  }
  async function waitForOldConnection(revision) {
    if(gate.pending)cancel('切换主机，已停止旧观察；新目标需要主动连接。');
    const deadline=Date.now()+10000;
    while(gate.pending && Date.now()<deadline && revision===hostNavigation) await new Promise(resolve=>setTimeout(resolve,50));
    if(gate.pending || revision!==hostNavigation)throw Error('connection_active');
  }
  function showRemotePage() {closeConfigTransfer(); showingRemote=true; $('host-home').hidden=true; $('remote-page').hidden=false; $('fixture-workbench').hidden=true; $('show-remote').setAttribute('aria-pressed','true'); $('show-fixture').setAttribute('aria-pressed','false');}
  async function refreshHosts(refreshNetwork=true) {
    if(!native){hostMessage('浏览器预览不读取本机主机资料。');return;}
    const revision=++hostRefreshRevision;
    try {
      if(!await hostInitialization)throw Error(hostInitError);
      if(revision!==hostRefreshRevision)return;
      const nextHosts=await invoke('host_list');
      if(revision!==hostRefreshRevision)return;
      const catalog=await invoke('network_list');
      if(revision!==hostRefreshRevision)return;
      const nextNetworkRevisions=new Map(catalog.profiles.map(p=>[p.id,p.revision]));
      const nextFont=catalog.preferences.terminalFontSize;
      hostRecords=nextHosts;networkRevisions=nextNetworkRevisions;terminalFontSize=nextFont;
      hostSummaries.reconcile(hostRecords.map(summaryHost));workspace?.setFont(terminalFontSize);
      $('terminal-font-size').value=terminalFontSize;if(terminal)terminal.options.fontSize=terminalFontSize;
      renderHosts();render();if(refreshNetwork)networks?.refresh();hostMessage(hostRecords.length?'选择主机、管理资料，或新增主机。':'还没有已存主机。');
    } catch {
      if(revision!==hostRefreshRevision)return;
      hostSummaries.suspendAll();hostRecords=[];networkRevisions=new Map();renderHosts();
      hostMessage('本机资料不可用；仍可打开手动连接表单。');
    }
  }
  function renderHosts() {
    renderLiveSummary();
    $('host-open-remote').textContent=unsavedHostOpen && !activeHostId?'继续未保存的主机':'新增主机 / 手动连接';
    $('host-open-remote').disabled=pairBusy;
    $('host-list').replaceChildren(); $('host-tabs').replaceChildren();
    for(const host of hostSummaries.order(hostRecords.map(summaryHost))) {
      const card=document.createElement('article'); card.className='saved-host-card';
      const title=document.createElement('h3');title.textContent=host.name;card.append(title);
      const detail=document.createElement('p');detail.textContent=`${host.target.username}@${host.target.host}:${host.target.port} · ${host.retired?'已替换并停用，身份保留供删除或撤销':host.enabled?'已启用':'已停用'} · ${host.networkProfileId?'已绑定网络（连接需核验）':'系统连接'} · ${runtimeRevokedHosts.has(host.id) && host.pairingStatus!=='revoked'?'本次运行已停用，撤销回执保存未确认':host.pairingStatus==='revoked'?'已登记主机撤销，原设备记录保留待显式清理':host.pairingStatus==='awaiting-host'?'待主机响应':host.pairingStatus==='cancelled'?'配对已取消，需核查授权':host.deviceFingerprint?'设备资料已存':'未保存设备身份'} · ${hostStatuses.get(host.id) || '尚未在本次运行中连接'}`;card.append(detail);
      const taskSummary=document.createElement('p');taskSummary.textContent=hostSummaryText(hostSummaries.get(host));taskSummary.setAttribute('data-host-task-summary',host.id);card.append(taskSummary);
      const name=document.createElement('input');name.value=host.name;name.maxLength=96;name.setAttribute('aria-label',`重命名 ${host.name}`);card.append(name);
      const actions=document.createElement('div');actions.className='saved-host-actions';
      const button=(label,callback)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=callback;b.disabled=pairBusy;actions.append(b);return b;};
      const open=button('打开',()=>void openSavedHost(host.id));open.disabled=pairBusy || !host.enabled;
      const openTab=button('新终端标签',async()=>{try {await waitForOldConnection(++hostNavigation);const id=workspace.create(host.id,null);showRemotePage();await workspace.select(id);}catch{hostMessage('无法新建标签；请核对设备身份与八标签上限。');}});openTab.disabled=pairBusy || !host.enabled || !host.deviceFingerprint || host.pairingStatus==='revoked' || runtimeRevokedHosts.has(host.id);
      button('保存名称',async()=>{try {await invoke('host_update',{id:host.id,name:name.value,enabled:null});await refreshHosts();}catch {await refreshHosts();hostMessage('名称保存未确认，请核查。');}});
      if(!host.retired) button(host.enabled?'停用':'启用',async()=>{try {await waitForOldConnection(++hostNavigation);if(host.enabled)workspace.affected([host.id]);await invoke('host_update',{id:host.id,name:null,enabled:!host.enabled});await refreshHosts();}catch {await refreshHosts();hostMessage('操作未确认，请核查状态并确保连接已结束。');}});
      let confirming=false; const remove=button('移除',async()=>{if(!confirming){confirming=true;remove.textContent='确认移除本机资料';return;} try {await waitForOldConnection(++hostNavigation);workspace.affected([host.id]);const result=await invoke('host_remove',{id:host.id});if(activeHostId===host.id)activeHostId=null;removeHostDrafts(host.id);hostStatuses.delete(host.id);await refreshHosts();hostMessage(result.keyDeleted?'已移除本机资料；主机授权仍须另行处理。':'资料已移除，本机密钥删除未确认；请核查。');}catch {await refreshHosts();hostMessage('移除未确认；请核查本机状态。');}});
      card.append(actions);$('host-list').append(card);
      if(host.enabled) {const tab=document.createElement('button');tab.type='button';tab.textContent=host.name;tab.disabled=pairBusy;tab.setAttribute('aria-pressed',String(host.id===activeHostId));tab.onclick=()=>void openSavedHost(host.id);$('host-tabs').append(tab);}
    }
  }
  async function openSavedHost(id) {
    if(pairBusy)return;
    if(runtimeRevokedHosts.has(id) && hostRecords.find(host=>host.id===id)?.pairingStatus!=='revoked'){hostMessage('本次运行已停用此设备，撤销回执保存未确认；不能恢复旧授权，请保留原回执并核查或显式清理。');return;}
    connectionProfiles?.invalidate();pairCamera?.discard();clearHandoff();revocationReview=false;pairReviewIdentity=null;
    const revision=++hostNavigation; saveHostDraft();
    try {
      await waitForOldConnection(revision);const host=await invoke('host_select',{id});if(revision!==hostNavigation)return;
      clearSnapshot();pairFingerprint=null;activeHostId=id;unsavedHostOpen=false;fillHost(host.target);$('remote-profile-provider').value=host.provider || '';$('host-save-name').value=host.name;discardKey();
      $('pair-request').value='';$('pair-response').value='';previewResponse='';$('pair-source-review').checked=false;$('pair-target-review').checked=false;
      $('pair-mode').checked=!!host.deviceFingerprint;pairState=host.deviceFingerprint?'restore-required':'none';
      $('host-restore-panel').hidden=!host.deviceFingerprint;$('host-restore-review').checked=false;
      $('host-restore-description').textContent=`主机：${host.hostFingerprint} · 设备：${host.deviceFingerprint || '未保存'}。身份恢复只会验证本机公钥，不会建立连接。`;
      $('host-restore-status').textContent='';clearDraftBinding();gate.reviewed=false;showRemotePage();renderHosts();render();
      pairStatus(host.deviceFingerprint?'先核对指纹并恢复原设备；不会自动重建。':'此主机尚无设备身份，可新建配对或使用手动入口。');
      status((hostStatuses.get(id) || '已切换目标。')+' 重新核对后主动连接。');
    } catch(e) {hostMessage(String(e)==='unsaved_pairing'?'当前设备身份尚未保存；请先保存或删除后再切换。':'无法打开主机；资料或旧连接不可用。');}
  }
  async function openNewHost() {
    if(pairBusy)return;
    connectionProfiles?.invalidate();pairCamera?.discard();clearHandoff();revocationReview=false;pairReviewIdentity=null;
    const revision=++hostNavigation;saveHostDraft();
    try {await waitForOldConnection(revision);if(revision!==hostNavigation)return;
      if(unsavedHostOpen && !activeHostId) {showRemotePage();render();status('继续未保存的目标；重新核对后主动连接。');return;}
      if(native){await hostInitialization;await invoke('host_new');}if(revision!==hostNavigation)return;
      clearSnapshot();pairFingerprint=null;activeHostId=null;unsavedHostOpen=true;fillHost({port:22});$('host-save-name').value='';$('host-restore-panel').hidden=true;$('host-restore-review').checked=false;
      $('pair-mode').checked=false;pairState='none';$('pair-request').value='';$('pair-response').value='';clearDraftBinding();gate.reviewed=false;showRemotePage();renderHosts();render();status('填写并审查新目标；不会自动连接。');
    } catch(e) {hostMessage(String(e)==='unsaved_pairing'?'当前设备身份尚未保存；请先保存或删除后再切换。':'连接尚未结束，请稍后重试。');}
  }
  async function saveCurrentHost() {
    // A pre-write catalog read must not publish obsolete identity after this write starts.
    hostRefreshRevision++;
    // Re-open only on this explicit user write, never replay host_save or key creation.
    if(!await hostInitialization && !await initializeHostCatalog()) throw hostInitError;
    const hint=!activeHostId && currentProfileProvider();
    const view=await invoke('host_save',{id:activeHostId,name:$('host-save-name').value,config:targetConfig(),...(hint?{providerHint:hint}:{})});
    activeHostId=view.id;unsavedHostOpen=false;await refreshHosts();render();$('host-save-status').textContent='已保存本机公开资料；不代表主机已验证或仍授权。';return view;
  }
  function summaryHost(host) {return {...host,networkRevision:host.networkProfileId ? networkRevisions.get(host.networkProfileId) : null};}
  let summaryRenderPending=false;
  function renderLiveSummary() {
    const panel=$('host-task-board');panel.replaceChildren();panel.hidden=!hostRecords.length;
    if(panel.hidden)return;
    const heading=document.createElement('h2');heading.textContent='主机任务摘要';panel.append(heading);
    for(const host of hostSummaries.order(hostRecords.map(summaryHost))) {
      const line=document.createElement('p');line.textContent=`${host.name} · ${hostSummaryText(hostSummaries.get(host))}`;line.setAttribute('data-live-host-summary',host.id);panel.append(line);
    }
  }
  function renderSummaryChanges() {
    renderLiveSummary();
    if($('host-home').hidden)return;
    if($('host-list').contains(document.activeElement)){summaryRenderPending=true;return;}
    summaryRenderPending=false;renderHosts();
  }
  $('host-list').addEventListener('focusout',()=>queueMicrotask(()=>{if(summaryRenderPending && !$('host-list').contains(document.activeElement))renderSummaryChanges();}));
  function onWorkspaceDashboard(event) {
    const host=hostRecords.find(h=>h.id===event.hostId);if(!host)return;
    const current=summaryHost(host),identity=hostSummaryIdentity(current);
    if(!identity || identity!==hostSummaryIdentity(event.identity))return;
    let changed=false;
    if(event.type==='snapshot')changed=hostSummaries.publish(current,event.source,event.board);
    else if(event.type==='starting')changed=hostSummaries.begin(current,event.source);
    else if(event.type==='stale')changed=hostSummaries.invalidateSource(host.id,event.source);
    if(changed)renderSummaryChanges();
  }
  const workspace=initTabWorkspace({native,invoke,theme,channelFactory:()=>new Channel(),terminalFactory:options=>createUnicodeTerminal(Terminal,options),onDashboard:onWorkspaceDashboard,getFontSize:()=>terminalFontSize,hostInfo:id=>{const host=hostRecords.find(h=>h.id===id);if(!host || host.pairingStatus==='revoked' || runtimeRevokedHosts.has(id))return null;const networkRevision=host.networkProfileId ? networkRevisions.get(host.networkProfileId) : null;return networkRevision===undefined ? null : {...host,networkRevision};},hostName:id=>hostRecords.find(h=>h.id===id)?.name || '主机'});
  const networks=initNetworkUI({native,invoke,getHosts:()=>hostRecords,onAffected:async ids=>{workspace.affected(ids);if(ids.includes(activeHostId))cancel('网络操作涉及此主机；观察已停止，请重新核对当前配置。');await refreshHosts(false);}});
  $('terminal-font-save').disabled=!native;
  $('terminal-font-save').onclick=async()=>{const font=Number($('terminal-font-size').value);if(!Number.isInteger(font)||font<10||font>28){$('terminal-font-status').textContent='请输入 10 至 28 的整数。';return;}try{const catalog=await invoke('network_list');await invoke('preferences_save',{font,expectedCatalog:catalog.revision});localViewport.capture();terminalFontSize=font;workspace.setFont(font);if(terminal)terminal.options.fontSize=font;$('terminal-font-status').textContent='字号已保存；不改变远端终端尺寸。';}catch{$('terminal-font-status').textContent='字号保存未确认；请核查后重试。';await refreshHosts();}};
  connectionProfiles=initConnectionProfileUI({native,invoke,
    state:()=>({available:showingRemote && !$('remote-page').hidden && unsavedHostOpen && !activeHostId && pairState==='none' && !pairFingerprint && !$('pair-request').value && !gate.pending && !pairBusy,
      navigation:hostNavigation,activeHostId,pairState,pairFingerprint,request:$('pair-request').value,target:targetConfig(),device:$('pair-device').value}),
    apply:profile=>{
      // No invoke here: adopting public fields is separate from saving, creating
      // a device key, accepting host authorization, and connecting.
      saveHostDraft();clearDraftBinding();clearSnapshot();fillHost(profile);
      $('remote-profile-provider').value=profile.provider;profileProviderHint=profile.provider;discardKey();gate.invalidate();
      $('pair-mode').checked=true;$('pair-target-review').checked=false;$('pair-source-review').checked=false;
      $('remote-review').checked=false;$('host-restore-review').checked=false;
      $('pair-request').value='';$('pair-response').value='';previewResponse='';$('pair-response-preview').hidden=true;
      pairStatus('公开连接资料已填入；请独立核对用户名和主机公钥，再创建设备公开请求。');render();
    }});
  $('host-open-remote').onclick=()=>void openNewHost();
  const closeConfigTransfer=initConfigTransfer({native, invoke, getHosts:()=>hostRecords, refreshHosts, onAffected:ids=>{workspace.prepareAffected(ids);if(ids.includes(activeHostId))cancel('配置操作涉及此主机；观察已停止，请重新核对。');}, onSettled:ids=>workspace.affected(ids), onApplied:async result=>{
    const affected=[...result.removedIds,...result.retired.map(h=>h.id)];
    workspace.affected(affected);
    if(affected.includes(activeHostId)) { hostNavigation++; cancel('配置已替换；旧观察已停止，新目标需重新配对。'); activeHostId=null; clearSnapshot(); }
  }});
  $('host-return-home').addEventListener('pointerdown',()=>workspace.prepareHide());
  $('show-fixture').addEventListener('pointerdown',()=>workspace.prepareHide());
  $('show-remote').addEventListener('pointerdown',()=>workspace.prepareHide());
  for(const id of ['host-return-home','show-fixture','show-remote']) {$(id).addEventListener('pointercancel',()=>workspace.cancelPrepareHide());$(id).addEventListener('pointerup',()=>setTimeout(()=>workspace.cancelPrepareHide(),0));}
  $('host-return-home').onclick=()=>{void workspace.hide();saveHostDraft();hostNavigation++;cancel('已返回主机看板；观察已停止。');showingRemote=false;$('remote-page').hidden=true;$('fixture-workbench').hidden=true;$('host-home').hidden=false;void refreshHosts();};
  $('host-save').onclick=async()=>{try {await saveCurrentHost();}catch(e){await refreshHosts();$('host-save-status').textContent=`保存未确认：${String(e)}；请核查已存主机后再试。`;}};
  $('host-restore-review').addEventListener('input',render);
  $('host-restore').onclick=()=>pairOperation(async()=>{
    if(!activeHostId || !$('host-restore-review').checked)return;
    try {const p=await invoke('host_restore',{id:activeHostId,reviewed:true}); pairState=p.state;pairFingerprint=p.fingerprint; $('pair-request').value=p.request; $('host-restore-review').checked=false; $('host-restore-panel').hidden=true;gate.reviewed=false;pairStatus(p.state==='revoked'?`原设备记录已撤销 · ${p.fingerprint}；不能连接或重新授权。记录保留供核对和显式清理。`:p.state==='awaiting-host'?`原设备公钥匹配 · ${p.fingerprint}；继续等待同一请求的主机响应，需重新审查。`:p.state==='expired'?'原请求已过期；不能接受授权，请核查主机状态，可审查撤销响应或删除本机身份。':p.state==='cancelled'?'请求已取消；不能接受授权，请核查主机状态或审查撤销响应。':`原设备公钥匹配 · ${p.fingerprint}；尚未进行 SSH 认证。`);}
    catch(e){$('host-restore-status').textContent=`恢复失败：${String(e)}。不会自动生成替代身份。`;}
  });
  async function pairOperation(work) {
    if (pairBusy) return;
    hostRefreshRevision++;
    connectionProfiles?.invalidate();pairCamera?.discard();
    pairBusy=true; render(); renderHosts();
    try { await work(); } finally { pairBusy=false; render(); renderHosts(); }
  }
  $('pair-create').onclick=()=>pairOperation(async()=>{
    const phase = $('pair-status').dataset;
    phase.createPhase='review';
    if (revocationMode() || pairState!=='none' || !$('pair-target-review').checked || !native) return;
    if (pairTargetIds.some(id=>!$(id).checkValidity() || !$(id).value)) { pairStatus('请先完整填写连接目标，再重新核对目标。'); $('pair-target-review').checked=false; return; }
    try { const config={schemaVersion:1,host:$('remote-host').value,port:Number($('remote-port').value),username:$('remote-user').value,expectedHostKey:$('remote-pin').value,privateKeyPem:'',socketPath:$('remote-socket').value,herdrPath:$('remote-herdr').value,session:$('remote-session').value,paneId:'',reviewConfirmed:true};
      phase.createPhase='catalog';
      if(!activeHostId) {if(!$('host-save-name').value.trim()) $('host-save-name').value='待配对主机'; await saveCurrentHost();}
      phase.createPhase='device';
      const p=await invoke('pair_create',{config,device:$('pair-device').value,hostId:activeHostId});
      phase.createPhase=p.stored?'ready':'persist_failed';
      $('pair-request').value=p.request; pairState=p.state;pairFingerprint=p.stored?p.fingerprint:null; pairStatus(p.stored?`等待主机响应 · 设备指纹 ${p.fingerprint} · 授权未知`:'设备已创建但本地保存未确认；请求未公开。请删除此身份并检查存储，不会自动替换。'); await refreshHosts();
    } catch(e) {
      const known=['host_storage_unavailable','host_storage_busy','host_storage_corrupt','host_storage_lock_failed',
        'host_path_bridge_unavailable','host_path_invalid','invalid_host_name',
        'invalid_config','invalid_host_key','key_unavailable','invalid_device_key','pairing_busy',
        'host_pairing_exists','host_already_exists','host_restore_required','invalid_public_field'];
      const code=known.includes(e)?e:'unavailable';
      phase.createPhase+='_'+code;
      pairStatus(`配对请求未确认 · ${code}。请核验本机资料及设备解锁状态，再手动处理。`);
    }
  });
  $('pair-request-copy').onclick=async()=>{
    if(handoffBusy || !requestCopyAllowed()){render();return;}
    const raw=$('pair-request').value,key=responseScope(),revision=handoffRevision;handoffBusy=true;render();
    try{
      if(!requestCopyAllowed() || revision!==handoffRevision || key!==responseScope())return;
      await clipboardWrite(raw,{hostId:activeHostId,requestId:currentRequestRecord().request_id});
      if(revision===handoffRevision && key===responseScope() && requestCopyAllowed())$('pair-handoff-status').textContent='已复制本次原始公开请求；请通过双方确认的可信渠道交接，并核对主机用户的确认结果。';
    }catch{if(revision===handoffRevision && key===responseScope() && requestCopyAllowed())$('pair-handoff-status').textContent='本次复制未确认：系统剪贴板写入不可用、未获权限或返回状态不匹配；原始请求仍在上方，可点击“手选公开请求”后使用系统复制菜单。';}
    finally{handoffBusy=false;render();}
  };
  $('pair-request-select').onclick=()=>{if(!requestCopyAllowed())return;$('pair-request').focus();$('pair-request').select?.();$('pair-request').setSelectionRange?.(0,$('pair-request').value.length);$('pair-handoff-status').textContent='已选中本次原始公开请求；请使用系统复制菜单，通过可信渠道交接。';};
  $('pair-scan').onclick=async()=>{
    const request=currentRequestRecord();
    if(!native || scanBusy || document.hidden || !request || pairState==='revoked' || pairBusy || gate.pending)return;
    gate.invalidate();$('pair-target-review').checked=false;
    previewResponse=invalidatePairReview($('pair-source-review'),$('pair-response-preview'));
    const attempt=pairCamera.start(pairState==='awaiting-host' && !revocationMode()?Math.min(60000,request.expires_at*1000-Date.now()):60000);if(!attempt)return;
    scanBusy=true;render();
    try {
      const raw=await invoke('pair_scan_response');
      if(!pairCamera.receive(attempt,raw,document.hidden,{hold:true}))return;
      pairStatus('本次公开响应已返回；请在前台点“重新查看本次响应扫描”，再独立核验原请求、主机和设备。尚未接受授权。');
    } catch {if(pairCamera.current(attempt)){pairCamera.discard();pairStatus('扫描未完成、响应不匹配或已失效；可核查原请求后手动粘贴响应。');}}
    finally {scanBusy=false;render();}
  };
  $('pair-preview').onclick=()=>{
    if(document.hidden || gate.pending || pairBusy)return;
    const held=pairCamera.take(document.hidden);if(held!==null)$('pair-response').value=held;
    previewResponse='';pairReviewIdentity=null; $('pair-source-review').checked=false;
    try {
      const raw=$('pair-response').value,response=validCurrentResponse(raw);
      if(response.status==='revoked'){revocationReview=true;gate.invalidate();}
      $('pair-response-preview').textContent=previewPairingResponse(raw);previewResponse=raw;pairReviewIdentity=responseScope();
    } catch { $('pair-response-preview').textContent='响应无效、不匹配或已过期；此原记录当前仅可接受的新鲜回执类型也须一致。'; }
    $('pair-response-preview').hidden=false; render();
  };
  $('pair-accept').onclick=()=>pairOperation(async()=>{
    if (document.hidden || gate.pending || !previewResponse || pairReviewIdentity!==responseScope() || !$('pair-source-review').checked) return;
    try{validCurrentResponse(previewResponse);}catch{pairStatus('响应已失效或不适用于原记录；请重新独立审查。');return;}
    try { const p=await invoke('pair_accept',{response:previewResponse,reviewed:true}); pairState=p.state;pairFingerprint=p.fingerprint; previewResponse=''; $('pair-source-review').checked=false;
      pairReviewIdentity=null;
      if(p.state==='revoked'){
        revocationReview=true;if(activeHostId){runtimeRevokedHosts.add(activeHostId);workspace.affected([activeHostId]);}cancel('本机已登记原设备撤销；观察与输入已失效，不会自动重连。');
        await refreshHosts();const readback=hostRecords.find(host=>host.id===activeHostId);
        pairStatus(p.stored===false?'本次运行已停用原设备，但撤销回执记录保存未确认；重开后须核对原回执与原设备记录，不能视为已持久撤销。私钥未删除。':readback?.pairingStatus==='revoked'?'已审查匹配撤销回执，目录已确认撤销；原设备记录保留，不能连接。私钥仅可由你另行显式清理。':'撤销回执已接受，目录读回未确认；连接保持锁定，请核查本机记录。');
      }else{revocationReview=false;pairStatus(`授权响应已审查，尚未验证 SSH · ${p.fingerprint}`);}
      if(activeHostId && p.state==='authorized-unverified') {try {await saveCurrentHost();} catch { $('host-save-status').textContent='配对资料保存未确认；请核查后重试，切勿丢弃当前身份。'; }}
    } catch(e) { pairStatus(`响应拒绝：${String(e)}。请重新核对；请求未被消耗。`); }
  });
  $('pair-cancel').onclick=()=>pairOperation(async()=>{ if(activeHostId)workspace.affected([activeHostId]);try { await invoke('pair_cancel'); pairState='cancelled';revocationReview=true; pairStatus('已取消；主机可能已授权，请核查或导入匹配的撤销响应。'); } catch(e) {pairStatus(`取消失败：${String(e)}`);} });
  $('pair-reset').onclick=()=>pairOperation(async()=>{ if(activeHostId)workspace.affected([activeHostId]);try { await invoke('pair_reset');if(activeHostId)runtimeRevokedHosts.delete(activeHostId); pairState='none';pairFingerprint=null;revocationReview=false;pairReviewIdentity=null;clearHandoff(); $('pair-request').value=''; $('pair-response').value=''; previewResponse=''; $('pair-target-review').checked=false; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; pairStatus('本机身份已删除；请向主机核查或撤销可能存在的授权。');await refreshHosts(); } catch(e) {pairStatus(`删除失败：${String(e)}`);} });
  $('remote-cancel').onclick=()=>cancel();
  $('remote-clear-key').onclick=()=>{ cancel('临时私钥已从表单清除。'); };
  $('remote-hide-keyboard').onclick=()=>document.activeElement?.blur();
  $('show-fixture').onclick=()=>{
    closeConfigTransfer();
    void workspace.hide();cancel('已离开远端读取；没有后台连接或自动恢复。'); showingRemote=false;
    saveHostDraft(); hostNavigation++; $('host-home').hidden=true; $('remote-page').hidden=true; $('fixture-workbench').hidden=false;
    $('show-fixture').setAttribute('aria-pressed','true'); $('show-remote').setAttribute('aria-pressed','false'); onFixture();
  };
  $('show-remote').onclick=()=>{
    onLeaveFixture(); void workspace.hide();saveHostDraft(); hostNavigation++; cancel('已返回主机看板；观察已停止。'); showingRemote=false;
    $('remote-page').hidden=true; $('host-home').hidden=false; $('fixture-workbench').hidden=true;
    $('show-fixture').setAttribute('aria-pressed','false'); $('show-remote').setAttribute('aria-pressed','true'); void refreshHosts();
  };
  $('remote-form').addEventListener('submit',async event=>{
    event.preventDefault();if(revocationMode() || pairState==='revoked'){status('当前仅审查撤销或保留已撤销记录；不能发起连接。','warning');return;} if(requiresNetworkBinding()) {status('此主机声明组网连接：请先保存并在网络配置中独立审查、绑定，再返回主动连接。未绑定时不会使用系统直连。','warning');return;} if (!native) { status('浏览器预览没有原生 SSH 适配器。请使用测试安装包。','warning'); return; }
    const generation=gate.begin(); if(generation===null)return;
    let config=null;
    try {
      saveHostDraft(); clearDraftBinding(); clearSnapshot();render();
      const value=id=>$(id).value;
      config={schemaVersion:1,host:value('remote-host'),port:Number(value('remote-port')),username:value('remote-user'),expectedHostKey:value('remote-pin'),privateKeyPem:$('pair-mode').checked?'':normalizePrivateKeyInput(value('remote-private-key')),socketPath:value('remote-socket'),herdrPath:value('remote-herdr'),session:value('remote-session'),paneId:'',reviewConfirmed:true};
      discardKey();
      connectionDraftIdentity=reviewedDraftIdentity(config,generation);
      connectionDraftLabel=`${config.username}@${config.host}:${config.port} · 会话 ${config.session}`;
      connectionDraftAuthenticated=false;
      const reviewedHost=hostRecords.find(h=>h.id===activeHostId);
      const viewportConnection={target:config,deviceFingerprint:pairFingerprint,networkProfileId:reviewedHost?.networkProfileId ?? null,
        networkRevision:reviewedHost?.networkProfileId ? networkRevisions.get(reviewedHost.networkProfileId) : null};
      directSummary.begin({host:reviewedHost ? summaryHost(reviewedHost) : null,config,device:$('pair-mode').checked,pairFingerprint,generation});
      const onEvent=new Channel();
      const frames=new RemoteFrameQueue();
      const board=new SessionDashboard();
      let boardEpoch=null, boardSelectionReady=false, selectionIntent=null, boundConfirmed=false;
      function renderDirectBoard() {
        $('remote-dashboard').hidden=false; $('remote-panes').replaceChildren();
        const freshness=document.createElement('p');freshness.setAttribute('role','status');
        freshness.setAttribute('data-dashboard-phase',board.phase);freshness.textContent=board.label;
        $('remote-panes').append(freshness);
        const presentation=dashboardPresentation(board.panes);
        const caption=document.createElement('p');caption.textContent=presentation.summary;$('remote-panes').append(caption);
        const epoch=board.epoch,revision=board.revision;
        const canChoose=pane=>gate.accepts(generation) && showingRemote && !document.hidden && !selectedTarget && !selectionIntent && boardSelectionReady && boardEpoch===epoch && board.reviewed(pane,epoch,revision);
        for(const pane of presentation.panes) {
          const intent=Object.freeze({paneId:pane.paneId,terminalId:pane.terminalId});
          const button=document.createElement('button');button.type='button';button.textContent=`${pane.paneId} · ${pane.terminalId}`;
          const subtitle=[pane.label,paneStatusText(pane),[pane.workspace,pane.tab].filter(Boolean).join(' / ')].filter(Boolean).join(' · ');
          if(subtitle){const meta=document.createElement('small');meta.className='pane-summary';meta.textContent=subtitle;button.append(meta);}
          button.disabled=!canChoose(intent);
          button.onclick=async()=>{
            if(!canChoose(intent))return;
            selectionIntent=intent;renderDirectBoard();
            try {
              await invoke('remote_select',{generation:boardNativeGeneration,epoch,revision,paneId:intent.paneId,terminalId:intent.terminalId});
              if(!gate.accepts(generation,boardNativeGeneration) || !showingRemote || document.hidden)return;
              boardSelectionReady=false;
            } catch {if(gate.accepts(generation,boardNativeGeneration))cancel('选择未确认，连接已停止；请重新核对。');}
            finally {if(gate.accepts(generation,boardNativeGeneration) && showingRemote)renderDirectBoard();}
          };
          $('remote-panes').append(button);
          const newTab=document.createElement('button');newTab.type='button';newTab.textContent=`在新标签打开 ${pane.paneId}`;
          newTab.disabled=!activeHostId || !$('pair-mode').checked || !board.reviewed(intent,epoch,revision);
          newTab.onclick=async()=>{if(!gate.accepts(generation,boardNativeGeneration) || !showingRemote || document.hidden || !board.reviewed(intent,epoch,revision))return;const host=activeHostId;try {await waitForOldConnection(++hostNavigation);const id=workspace.create(host,intent);await workspace.select(id);status('目标已固定；请在标签中主动连接。');}catch {status('无法新建标签；请确认设备身份、连接状态和八标签上限。','warning');}};
          $('remote-panes').append(newTab);
        }
      }
      let boardNativeGeneration=null;
      let renderedFull = 0, renderedDeltas = 0;
      const captured = $('remote-captured');
      captured.dataset.fullFrames = captured.dataset.deltaFrames = '0';
      delete $('remote-input-status').dataset.receipt;
      onEvent.onmessage=event=>{
        if(!gate.accepts(generation,event.generation) || !showingRemote)return;
        if(event.kind==='input_ready') { if(event.epoch!==boardEpoch || !selectedTarget || !boundConfirmed)return; inputGeneration=event.generation; inputUnknown=event.unknown; inputMode='observe'; inputEpoch=null; $('remote-input-controls').hidden=false; $('remote-input-recover').hidden=event.recovery_status!=='pending'; $('remote-input-status').textContent=event.recovery_status==='unavailable'?'安全记录不可用或已损坏；输入保持锁定。':inputUnknown?'存在未确认的发送记录。重新观察原目标后，核实结果并确认。':'观察模式；显式选择输入模式才可发送。'; return; }
        if(event.kind==='stage') { if(event.stage==='authenticated' && $('pair-mode').checked){connectionDraftAuthenticated=true;directSummary.authenticated(generation);pairState='paired';pairStatus('已完成固定主机公钥核验与设备 SSH 认证。');} if(stages[event.stage])status(stages[event.stage]); return; }
        if(event.kind==='observation') {
          const epoch=event.snapshot?.epoch,phase=event.snapshot?.phase;
          if(!Number.isSafeInteger(epoch) || epoch<1 || !['starting','active','pausing','paused','resuming','closed'].includes(phase)){cancel('观察状态无效，连接已停止。');return;}
          if(boardEpoch!==null && epoch<boardEpoch)return;
          if(boardEpoch!==null && epoch>boardEpoch && (selectedTarget || selectionIntent)){cancel('观察代次变化，连接已停止。');return;}
          if(boardEpoch===null || epoch>boardEpoch){boardEpoch=epoch;board.advance(epoch);boardSelectionReady=false;directSummary.update(generation,board);}
          boardNativeGeneration=event.generation;
          if(['pausing','paused','closed'].includes(phase)){board.invalidate(phase);boardSelectionReady=false;directSummary.update(generation,board);}
          renderDirectBoard();return;
        }
        if(event.kind==='target_bound') {
          if(event.epoch!==boardEpoch)return;
          const expected = selectionIntent || selectedTarget;
          if(!expected || event.pane_id!==expected.paneId || event.terminal_id!==expected.terminalId){cancel('终端目标已变化，连接已停止。');return;}
          if(selectionIntent) {
            bindDraft(expected);selectedTarget=expected;selectionIntent=null;
            $('remote-input-target').textContent=`目标：${expected.paneId} · ${expected.terminalId}`;
            status(`正在观察 ${expected.paneId} · ${expected.terminalId}`);
          }
          boundConfirmed=true;return;
        }
        if(event.kind==='dashboard_watch') {
          if(!event.update || !Number.isSafeInteger(event.update.epoch) || event.update.epoch<1){cancel('会话看板无效，连接已停止。');return;}
          if(boardEpoch===null || event.update.epoch!==boardEpoch)return;
          boardNativeGeneration=event.generation;
          const accepted=board.accept(event.update,boardEpoch);
          if(accepted==='invalid'){cancel('会话看板无效，连接已停止。');return;}
          if(accepted==='accepted'){directSummary.update(generation,board);renderDirectBoard();}
          return;
        }
        if(event.kind==='selection_ready') {
          if(!Number.isSafeInteger(event.epoch) || event.epoch!==boardEpoch)return;
          boardNativeGeneration=event.generation;boardSelectionReady=true;renderDirectBoard();return;
        }
        if(event.kind!=='frame') { cancel('收到无效事件，连接已停止。'); return; }
        if(event.epoch!==boardEpoch || !boundConfirmed)return;
        const frame=event.frame;
        if(!frames.accept(frame)) {cancel('画面顺序或内容异常，连接已停止，画面陈旧。');return;}
        if(!terminal) {
          $('remote-result').hidden=false;
          terminal=createUnicodeTerminal(Terminal,{cols:80,rows:24,fontFamily:'ProbeNerd, monospace',fontSize:terminalFontSize,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme:theme.terminal,linkHandler:{activate:()=>{}}});
          terminal.parser.registerOscHandler(52,()=>true); terminal.parser.registerOscHandler(8,()=>true);
          terminal.open($('remote-terminal')); terminal.textarea.setAttribute('inputmode','none');
          localViewport.mount($('remote-terminal').parentElement,terminal,terminalViewportIdentity(viewportConnection,selectedTarget));
          const selectText=document.createElement('button');selectText.type='button';selectText.className='terminal-select-button';selectText.disabled=true;selectText.textContent='选择终端文本';selectText.onpointerdown=event=>event.preventDefault();
          $('remote-result').prepend(selectText);selectTextButton=selectText;
          $('remote-font-diagnostics').disabled=true;
          selectText.onclick=()=>{
            const bound=terminal,target=selectedTarget,host=activeHostId;
            const current=()=>!document.hidden && showingRemote && terminal===bound && selectedTarget===target && activeHostId===host && gate.accepts(generation,event.generation);
            if(!bound || !target || !selectionReady || !current())return;
            if(inputBusy){inputStatus('输入仍在处理，暂不能选择终端文本。');return;}
            fontDiagnostics?.close(false);fontDiagnostics=null;textSelection?.close();textSelection=null;loseInputFocus();
            try {textSelection=createTerminalSelection({terminal:bound,current,label:`${target.paneId} · ${target.terminalId}`});}
            catch(error) {status(String(error).includes('snapshot_too_large')?'可见终端文本超过 64 KiB，无法选择；未复制内容。':'没有可安全测量的可见终端文本，请滚动终端到屏幕内后重试。','warning');}
          };
          const boundTerminal=terminal; inputComposition=new InputComposition();
          $('remote-font-diagnostics').onpointerdown=event=>event.preventDefault();
          $('remote-font-diagnostics').onclick=()=>{
            const target=selectedTarget,host=activeHostId,nativeGeneration=event.generation;
            const current=()=>!document.hidden && showingRemote && terminal===boundTerminal && selectedTarget===target && activeHostId===host && gate.accepts(generation,nativeGeneration);
            if(fontDiagnostics?.valid() || !selectionReady || !target || !current())return;
            if(inputBusy || (inputEpoch===null && !boundTerminal.options.disableStdin)){inputStatus('输入仍在处理，暂不能打开字体诊断。');return;}
            textSelection?.close();textSelection=null;fontDiagnostics?.close();fontDiagnostics=null;loseInputFocus();
            let view;switchingFocus=true;try {view=createFontDiagnostics({current,terminalFactory:options=>createUnicodeTerminal(Terminal,options),fontSize:terminalFontSize,theme:theme.terminal,returnFocus:$('remote-font-diagnostics'),onClose:()=>{if(fontDiagnostics===view)fontDiagnostics=null;}});fontDiagnostics=view;} catch {inputStatus('字体诊断无法安全打开；输入已锁定。');} finally {switchingFocus=false;}
          };
          const keyboardPending=()=>terminal===boundTerminal && inputMode!=='direct' && !boundTerminal.options.disableStdin;
          blockPendingKeys(terminal.textarea,keyboardPending);
          terminal.onData(data=>{ if(terminal!==boundTerminal)return; const token={generation:inputGeneration,epoch:inputEpoch,revision:inputRevision}; if(!inputComposition.accepts(token)) {inputStatus('输入法提交已过期，本次未发送。');return;} renderAuxiliary();if(inputMode==='direct' && document.activeElement===terminal?.textarea) queueDirect(new TextEncoder().encode(data)); });
          terminal.textarea.addEventListener('compositionstart',()=>{if(terminal===boundTerminal){pasteReadSequence++;inputComposition.begin({generation:inputGeneration,epoch:inputEpoch,revision:inputRevision});renderKeyboardActions();}},true);
          terminal.textarea.addEventListener('compositionend',()=>{if(terminal===boundTerminal){inputComposition.end();renderKeyboardActions();}},true);
          terminal.textarea.addEventListener('blur',()=>{if(terminal===boundTerminal && !switchingFocus) loseInputFocus();});
          terminal.textarea.addEventListener('paste',event=>{
            if(terminal!==boundTerminal || (!keyboardPending() && inputMode!=='direct'))return;
            event.preventDefault(); event.stopImmediatePropagation();
            if(inputMode!=='direct')return;
            pasteReadSequence++;
            const text=event.clipboardData?.types && !Array.from(event.clipboardData.types).includes('text/plain') ? '' : event.clipboardData?.getData('text/plain') || '';
            void reviewLocalPaste(boundTerminal,text,boundTerminal.textarea);
          },true);
        } else if(frame.full) {selectionReady=false;if(selectTextButton)selectTextButton.disabled=true;$('remote-font-diagnostics').disabled=true;terminal.reset();}
        const rendered=terminal;
        terminal.write(Uint8Array.from(frame.bytes),()=>{
          if(terminal!==rendered || !gate.accepts(generation,event.generation) || !showingRemote || event.epoch!==boardEpoch)return;
          $('remote-captured').textContent=`${new Date().toLocaleTimeString()} 更新 · 80 × 24 · 只读观察中`;
          status('只读观察中；停止或离开后画面标记为陈旧。','success');
          if(!frames.acknowledge(frame.seq)){cancel('渲染确认异常，连接已停止。');return;}
          if(frame.full)localViewport.fullRendered();
          selectionReady=true;if(selectTextButton)selectTextButton.disabled=false;$('remote-font-diagnostics').disabled=false;
          if (frame.full) renderedFull++; else renderedDeltas++;
          captured.dataset.fullFrames = String(renderedFull);
          captured.dataset.deltaFrames = String(renderedDeltas);
          void invoke('remote_ack',{generation:event.generation,epoch:event.epoch,seq:frame.seq}).catch(()=>{if(gate.accepts(generation,event.generation))cancel('渲染确认失败，连接已停止。');});
        });
      };
      if ($('pair-mode').checked) { pairState='connecting'; pairStatus('正在核验主机并认证设备；不会自动重试。'); }
      await invoke('remote_observe',{config,device:$('pair-mode').checked,hostId:activeHostId,clientGeneration:generation,onEvent});

    } catch(error) {
      if($('pair-mode').checked && pairState==='connecting') { pairState='waiting-connectivity'; pairStatus('连接或认证未完成；需手动重试，不会自动重放。'); }
      if(gate.accepts(generation)){ if(terminal) $('remote-captured').textContent='连接已结束 · 画面陈旧'; $('remote-dashboard').hidden=true; status(observationError(error),'warning'); }
    } finally { directSummary.finish(generation);discardKey(); if(config)config.privateKeyPem=''; if(gate.finish(generation)){const lost=invalidateInput();recordUnsent(lost.count);} gate.reviewed=false; render(); }
  });
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden){
      pairCamera.background();workspace.background();
      cancel('应用进入后台，已取消读取并清除临时私钥。回到前台后需重新核验。',true);
    }else{pairCamera.foreground();render();}
  });
  window.addEventListener('pagehide',()=>{workspace.background();cancel();});
  // The browser never substitutes fixture output for a failed/missing native transport.
  $('remote-native-note').hidden=native;
  showingRemote=false; if(native)initializeHostCatalog(); void refreshHosts();
  $('host-open-remote').disabled=false; $('show-fixture').disabled=false;
  status(native?'待审查连接资料；没有建立远端连接。':'浏览器仅预览表单与布局，没有原生 SSH 功能。','info');render();
}
