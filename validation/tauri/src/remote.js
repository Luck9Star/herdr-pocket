import { initNetworkUI } from './network-ui.js';
import { initTabWorkspace } from './tab-workspace.js';
import { Terminal } from '@xterm/xterm';
import { invoke, Channel } from '@tauri-apps/api/core';
import { RemoteViewGate, RemoteFrameQueue, validDashboard } from './remote-state.js';
import { normalizePrivateKeyInput } from './remote-key.js';
import { previewPairingResponse } from './pairing-view.js';
import { InputComposition, blockPendingKeys } from './input-composition.js';
import { AuxiliaryModifiers, draftBytes, displayDraft } from './input-codec.js';
import { OnlineInputQueue } from './online-input-queue.js';
import { matchedReceipt } from './input-receipt.js';
import { scanCurrent } from './scan-lease.js';
import { invalidatePairReview } from './pairing-lifecycle.js';
import { dashboardPresentation, paneStatusText } from './dashboard-presentation.js';
import { initConfigTransfer } from './config-transfer-ui.js';
import { HostDashboardSummary, hostSummaryIdentity, hostSummaryText } from './host-dashboard-summary.js';
import { DirectDashboardSummary } from './direct-dashboard-summary.js';

export function initRemote({ native, theme, onFixture, onLeaveFixture }) {
  const $ = id => document.getElementById(id), gate = new RemoteViewGate();
  let terminalFontSize=14, terminal = null, showingRemote = true, pairState = 'none', previewResponse = '', pairBusy = false, scanBusy = false, scanRevision = 0;
  let inputGeneration=null, inputEpoch=null, inputMode='observe', inputBusy=false, inputUnknown=false, inputRevision=0, selectedTarget=null, draftPreview=null, switchingFocus=false;
  let inputComposition=new InputComposition(), focusReset=Promise.resolve(); const onlineInput=new OnlineInputQueue();
  const auxiliaryModifiers=new AuxiliaryModifiers();
  let networkRevisions=new Map();
  const hostSummaries=new HostDashboardSummary();
  let pairFingerprint=null;
  const directSummary=new DirectDashboardSummary(event=>onWorkspaceDashboard(event));
  let hostRecords=[], activeHostId=null, hostNavigation=0, hostRefreshRevision=0, unsavedHostOpen=false; const hostDrafts=new Map(), hostStatuses=new Map();
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
  const stages = { connecting:'连接 SSH，等待服务器身份核验…', 'host-key-verified':'预期主机公钥已匹配，开始临时公钥认证…', authenticated:'认证完成，读取指定 socket 的会话快照…', 'snapshot-received':'快照已读取，请选择目标 pane…', 'full-frame-received':'完整画面已校验，正在关闭连接…' };
  const errors = { host_key_mismatch:'主机公钥不匹配。认证未开始；请回到独立可信渠道核对。', authentication_failed:'临时公钥认证失败。未尝试其他凭据。', session_mismatch:'socket 与命名会话不一致。仅支持 release herdr 的 /herdr/sessions/<会话>/herdr.sock 路径。', pane_missing:'快照中没有指定 pane。请核对 pane 标识后重新审查。', invalid_private_key:'仅支持本轮实验用、未加密的 OpenSSH Ed25519 私钥。', invalid_host_key:'主机公钥应为 ssh-ed25519 与完整公钥数据两字段。', invalid_config:'资料不完整或格式不支持。核对后重新审查。', socket_unavailable:'指定 socket 不可用。请检查会话是否已启动及 SSH 转发权限。', timeout:'读取超时，连接已终止。不会自动重试。', connection_failed:'SSH 无法连接。请检查地址、端口和网络路径。', cancelled:'本次读取已取消。迟到结果不会显示。', unsupported_protocol:'服务器快照版本不支持；本轮仅验证 herdr 0.9.5。' };
  function status(message, tone='info') { $('remote-status').textContent=message; $('remote-status').dataset.tone=tone; }
  function render() {
    $('remote-fields').disabled=gate.pending || pairBusy;
    for(const id of pairTargetIds) $(id).readOnly=pairState!=='none';
    $('pair-target-review').disabled=pairState!=='none';
    $('pair-mode').disabled=pairState==='restore-required';
    $('remote-connect').disabled=!native || pairBusy || gate.pending || !gate.reviewed || ($('pair-mode').checked && !pairReady());
    $('pair-controls').hidden=!$('pair-mode').checked; $('manual-key-section').hidden=$('pair-mode').checked;
    $('remote-private-key').required=!$('pair-mode').checked;
    $('pair-scan').disabled=!native || scanBusy || gate.pending || !$('pair-request').value;
    $('pair-create').disabled=!native || gate.pending || pairState!=='none' || !$('pair-target-review').checked;
    $('pair-accept').disabled=!native || gate.pending || !previewResponse || !$('pair-source-review').checked;
    $('pair-reset').disabled=!native || gate.pending || pairState==='none' || pairState==='restore-required';
    $('host-save').disabled=!native || gate.pending || pairBusy; $('host-save-name').disabled=gate.pending || pairBusy;
    $('host-restore').disabled=!native || gate.pending || pairBusy || !$('host-restore-review').checked;
    $('pair-cancel').disabled=!native || gate.pending || pairState==='none' || pairState==='cancelled' || pairState==='revoked' || pairState==='restore-required' || pairState==='storage-failed';
    $('remote-cancel').disabled=!gate.pending;
    $('remote-review').checked=gate.reviewed;
  }
  function clearSnapshot() { invalidateInput(); terminal?.dispose(); terminal=null; $('remote-terminal').replaceChildren(); $('remote-result').hidden=true; $('remote-dashboard').hidden=true; $('remote-panes').replaceChildren(); }
  function discardKey() { $('remote-private-key').value=''; }
  function cancel(reason='本次读取已取消。迟到结果不会显示。') {
    const clientGeneration=gate.pendingGeneration;
    directSummary.finish(clientGeneration);
    scanRevision++; previewResponse=invalidatePairReview($('pair-source-review'),$('pair-response-preview')); if(pairState==='none') $('pair-target-review').checked=false; const discarded=invalidateInput(); recordUnsent(discarded.count); gate.invalidate(); discardKey(); if ($('pair-mode').checked && gate.pending && pairState!=='paired') { pairState='cancelled'; pairStatus('已取消；主机授权状态可能未知，请核查清理。'); } $('remote-dashboard').hidden=true; if(terminal) $('remote-captured').textContent='观察已停止 · 画面陈旧'; status(reason+(discarded.count?` ${discarded.count} 笔待发送输入已丢弃。`:'')); render();
    // Invalidating precedes asynchronous cleanup. Keep busy until the old invoke settles.
    if (gate.pending && native) void invoke('remote_cancel',{clientGeneration}).catch(()=>{if(gate.pendingGeneration===clientGeneration)status('正在结束旧连接；结束前不可开始新读取。','warning');});
  }
  $('remote-form').addEventListener('input', event => {
    if (event.target.id==='host-save-name') return;
    if (pairTargetIds.includes(event.target.id) && pairState==='none') $('pair-target-review').checked=false;
    if (event.target.id==='pair-mode') { $('remote-private-key').required=!event.target.checked; }
    if (['pair-target-review','pair-source-review','host-restore-review'].includes(event.target.id)) { render(); return; }
    if (event.target.id==='pair-response') { scanRevision++; previewResponse=''; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; render(); return; }
    if (event.target.id==='remote-review') { gate.reviewed=event.target.checked; render(); return; }
    gate.invalidate(); clearSnapshot(); render();
  });
  function recordUnsent(count) {if(!count)return; const box=$('remote-unsent-notices'), line=document.createElement('p'); const name=hostRecords.find(h=>h.id===activeHostId)?.name || '当前目标'; line.textContent=`${name}：${count} 笔输入未发送，未自动重放。`; box.append(line); while(box.children.length>10)box.firstElementChild.remove(); box.hidden=false;}
  function inputStatus(text) { $('remote-input-status').textContent=text; renderAuxiliary(); }
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
  function invalidateInput() {
    const discarded=onlineInput.clear(); inputRevision++; inputGeneration=null; inputEpoch=null; inputMode='observe'; draftPreview=null;
    releaseAuxiliary();
    $('remote-input-controls').hidden=true; $('remote-input-preview-area').hidden=true;
    if(terminal) {terminal.options.disableStdin=true; terminal.textarea?.setAttribute('inputmode','none');}
    return discarded;
  }
  function loseInputFocus() {
    auxiliaryModifiers.reset();
    if(inputGeneration===null)return;
    const generation=inputGeneration; const discarded=onlineInput.clear(); recordUnsent(discarded.count); inputRevision++; inputEpoch=null; inputMode='observe'; draftPreview=null;
    if(terminal) {terminal.options.disableStdin=true; terminal.textarea.setAttribute('inputmode','none');}
    if(inputBusy) {inputUnknown=true; $('remote-input-recover').hidden=false; inputStatus(`输入进行时失去焦点：结果未知，需重新连接原目标并核实。${discarded.count?` ${discarded.count} 笔未发送。`:''}`);}
    else inputStatus(`焦点已离开；输入已锁定。${discarded.count?` ${discarded.count} 笔未发送。`:''}`);
    focusReset=invoke('remote_input_mode',{generation,mode:'observe',focused:false}).catch(()=>{});
  }
  async function changeInputMode(mode) {
    releaseAuxiliary();
    if(document.hidden || inputGeneration===null || !terminal || (inputUnknown && mode!=='observe'))return;
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
  function currentDirect(token) {return !document.hidden && inputGeneration!==null && inputEpoch!==null && !inputUnknown && inputMode==='direct' && document.activeElement===terminal?.textarea && OnlineInputQueue.same(token,inputToken());}
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
    if(inputGeneration===null || inputEpoch===null || inputUnknown || inputBusy || !bytes.length || bytes.length>4096 || !OnlineInputQueue.same(token,inputToken()) ||
       (draft ? inputMode!=='draft' || document.activeElement!==$('remote-input-draft') : !currentDirect(token))) {
      const lost=onlineInput.clear();recordUnsent(lost.count+1);inputStatus(`本次输入未发送：输入许可或字节上限不满足。${lost.count?` 另有 ${lost.count} 笔未发送。`:''}`);return;
    }
    const generation=token.generation, epoch=token.epoch; inputBusy=true; let proceed=false;
    // Remove the submitted text before the first await. A tab change can now
    // save only the still-unsent draft, even if the reply is lost.
    const editor = $('remote-input-draft');
    const submittedText = draft ? editor.value : '';
    if (draft) editor.value = '';
    const restoreRejectedDraft = () => {
      if (draft && !editor.value && generation === inputGeneration && OnlineInputQueue.same(token, inputToken())) {
        editor.value = submittedText;
      }
    };
    try {
      const result=await invoke('remote_input_send',{generation,epoch,bytes:Array.from(bytes),draft});
      if(generation!==inputGeneration || !OnlineInputQueue.same(token,inputToken()))return;
      const receipt=result?.status==='accepted'?matchedReceipt(result.receipt,selectedTarget,bytes.length):null;
      if (result?.recoveryRequired && (receipt || result.status === 'rejected')) {
        if (receipt) $('remote-input-status').dataset.receipt = JSON.stringify(receipt);
        else restoreRejectedDraft();
        inputUnknown = true;
        cancel((receipt ? '服务器已接收入队' : '服务器已明确拒绝') +
          ' · 本机发送记录待核实，输入已锁定。');
        return;
      }
      if(result?.status==='unknown') {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
      else if(result?.status==='rejected') {restoreRejectedDraft();const lost=onlineInput.clear();recordUnsent(lost.count);inputBusy=false;loseInputFocus();inputStatus(`服务器明确拒绝本笔。${lost.count?` ${lost.count} 笔后续输入未发送。`:''}`);}
      else if(receipt) {
        $('remote-input-status').dataset.receipt=JSON.stringify(receipt);
        proceed=!draft;inputStatus(`服务器已接收入队 · ${receipt.paneId} · ${receipt.acceptedBytes} 字节。执行结果请查看终端。`);
      }
      else {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
    } catch(error) {
      if(generation!==inputGeneration || !OnlineInputQueue.same(token,inputToken()))return;
      if(['input_stale','input_invalid_size','input_storage_unavailable','input_recovery_required'].includes(String(error))) {restoreRejectedDraft();const lost=onlineInput.clear();recordUnsent(lost.count+1);inputBusy=false;loseInputFocus();inputStatus(`本次输入未发送或许可不可用。${lost.count?` ${lost.count} 笔后续输入未发送。`:''}`);}
      else {inputUnknown=true; cancel('发送结果未知；连接已停止，不自动重放。');}
    } finally {inputBusy=false; if(proceed) {if(currentDirect(token))void pumpDirect();else {const lost=onlineInput.clear();if(inputGeneration!==null)loseInputFocus();if(lost.count){recordUnsent(lost.count);inputStatus(`${lost.count} 笔未发送输入已丢弃。`);}}}}
  }
  function showInputPreview() {
    const text=$('remote-input-draft').value;
    const bracketed=terminal?.modes.bracketedPasteMode===true;
    if(inputMode!=='draft' || !draftBytes(text,bracketed)) {inputStatus('草稿为空、超过 4096 字节或含不支持的粘贴结束序列。');return;}
    draftPreview={text,bracketed}; $('remote-input-preview-text').textContent=displayDraft(text); $('remote-input-preview-area').hidden=false;
    inputStatus(bracketed?'目标启用括号粘贴；确认后发送文本及保护序列。':'目标未启用括号粘贴；确认后直接发送文本。');
  }
  $('remote-input-observe').onclick=()=>void changeInputMode('observe');
  $('remote-input-direct').onclick=()=>void changeInputMode('direct');
  $('remote-input-draft-mode').onclick=()=>void changeInputMode('draft');
  $('remote-input-draft').addEventListener('blur',()=>{if(!switchingFocus)loseInputFocus();});
  $('remote-input-draft').addEventListener('input',()=>{draftPreview=null; $('remote-input-preview-area').hidden=true;});
  for(const id of ['remote-input-preview','remote-input-confirm', 'remote-input-recover']) $(id).addEventListener('pointerdown',e=>e.preventDefault());
  $('remote-input-preview').onclick=showInputPreview;
  $('remote-input-confirm').onclick=()=>{if(draftPreview===null || draftPreview.text!==$('remote-input-draft').value || draftPreview.bracketed!==(terminal?.modes.bracketedPasteMode===true)) {draftPreview=null; $('remote-input-preview-area').hidden=true; inputStatus('终端粘贴模式或文本已变化，请重新预览。'); return;} const bytes=draftBytes(draftPreview.text,draftPreview.bracketed); draftPreview=null; $('remote-input-preview-area').hidden=true; if(bytes)void sendInput(bytes,true);};
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
  function saveHostDraft() {if(activeHostId) {hostDrafts.set(activeHostId,$('remote-input-draft').value);if(!$('remote-page').hidden)hostStatuses.set(activeHostId,gate.pending || terminal ? '上次观察已停止，重新查看需主动连接。' : $('remote-status').textContent);}}
  function fillHost(target) {
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
      renderHosts();if(refreshNetwork)networks?.refresh();hostMessage(hostRecords.length?'选择主机、管理资料，或新增主机。':'还没有已存主机。');
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
      const detail=document.createElement('p');detail.textContent=`${host.target.username}@${host.target.host}:${host.target.port} · ${host.retired?'已替换并停用，身份保留供删除或撤销':host.enabled?'已启用':'已停用'} · ${host.networkProfileId?'已绑定网络（连接需核验）':'系统连接'} · ${host.pairingStatus==='awaiting-host'?'待主机响应':host.pairingStatus==='cancelled'?'配对已取消，需核查授权':host.deviceFingerprint?'设备资料已存':'未保存设备身份'} · ${hostStatuses.get(host.id) || '尚未在本次运行中连接'}`;card.append(detail);
      const taskSummary=document.createElement('p');taskSummary.textContent=hostSummaryText(hostSummaries.get(host));taskSummary.setAttribute('data-host-task-summary',host.id);card.append(taskSummary);
      const name=document.createElement('input');name.value=host.name;name.maxLength=96;name.setAttribute('aria-label',`重命名 ${host.name}`);card.append(name);
      const actions=document.createElement('div');actions.className='saved-host-actions';
      const button=(label,callback)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=callback;b.disabled=pairBusy;actions.append(b);return b;};
      const open=button('打开',()=>void openSavedHost(host.id));open.disabled=pairBusy || !host.enabled;
      const openTab=button('新终端标签',async()=>{try {await waitForOldConnection(++hostNavigation);const id=workspace.create(host.id,null);showRemotePage();await workspace.select(id);}catch{hostMessage('无法新建标签；请核对设备身份与八标签上限。');}});openTab.disabled=pairBusy || !host.enabled || !host.deviceFingerprint;
      button('保存名称',async()=>{try {await invoke('host_update',{id:host.id,name:name.value,enabled:null});await refreshHosts();}catch {await refreshHosts();hostMessage('名称保存未确认，请核查。');}});
      if(!host.retired) button(host.enabled?'停用':'启用',async()=>{try {await waitForOldConnection(++hostNavigation);if(host.enabled)workspace.affected([host.id]);await invoke('host_update',{id:host.id,name:null,enabled:!host.enabled});await refreshHosts();}catch {await refreshHosts();hostMessage('操作未确认，请核查状态并确保连接已结束。');}});
      let confirming=false; const remove=button('移除',async()=>{if(!confirming){confirming=true;remove.textContent='确认移除本机资料';return;} try {await waitForOldConnection(++hostNavigation);workspace.affected([host.id]);const result=await invoke('host_remove',{id:host.id});if(activeHostId===host.id)activeHostId=null;hostDrafts.delete(host.id);hostStatuses.delete(host.id);await refreshHosts();hostMessage(result.keyDeleted?'已移除本机资料；主机授权仍须另行处理。':'资料已移除，本机密钥删除未确认；请核查。');}catch {await refreshHosts();hostMessage('移除未确认；请核查本机状态。');}});
      card.append(actions);$('host-list').append(card);
      if(host.enabled) {const tab=document.createElement('button');tab.type='button';tab.textContent=host.name;tab.disabled=pairBusy;tab.setAttribute('aria-pressed',String(host.id===activeHostId));tab.onclick=()=>void openSavedHost(host.id);$('host-tabs').append(tab);}
    }
  }
  async function openSavedHost(id) {
    if(pairBusy)return;
    const revision=++hostNavigation; saveHostDraft();
    try {
      await waitForOldConnection(revision);const host=await invoke('host_select',{id});if(revision!==hostNavigation)return;
      clearSnapshot();scanRevision++;pairFingerprint=null;activeHostId=id;unsavedHostOpen=false;fillHost(host.target);$('host-save-name').value=host.name;discardKey();
      $('pair-request').value='';$('pair-response').value='';previewResponse='';$('pair-source-review').checked=false;$('pair-target-review').checked=false;
      $('pair-mode').checked=!!host.deviceFingerprint;pairState=host.deviceFingerprint?'restore-required':'none';
      $('host-restore-panel').hidden=!host.deviceFingerprint;$('host-restore-review').checked=false;
      $('host-restore-description').textContent=`主机：${host.hostFingerprint} · 设备：${host.deviceFingerprint || '未保存'}。身份恢复只会验证本机公钥，不会建立连接。`;
      $('host-restore-status').textContent='';$('remote-input-draft').value=hostDrafts.get(id) || '';gate.reviewed=false;showRemotePage();renderHosts();render();
      pairStatus(host.deviceFingerprint?'先核对指纹并恢复原设备；不会自动重建。':'此主机尚无设备身份，可新建配对或使用手动入口。');
      status((hostStatuses.get(id) || '已切换目标。')+' 重新核对后主动连接。');
    } catch(e) {hostMessage(String(e)==='unsaved_pairing'?'当前设备身份尚未保存；请先保存或删除后再切换。':'无法打开主机；资料或旧连接不可用。');}
  }
  async function openNewHost() {
    if(pairBusy)return;
    const revision=++hostNavigation;saveHostDraft();
    try {await waitForOldConnection(revision);if(revision!==hostNavigation)return;
      if(unsavedHostOpen && !activeHostId) {showRemotePage();render();status('继续未保存的目标；重新核对后主动连接。');return;}
      if(native){await hostInitialization;await invoke('host_new');}if(revision!==hostNavigation)return;
      clearSnapshot();pairFingerprint=null;activeHostId=null;unsavedHostOpen=true;fillHost({port:22});$('host-save-name').value='';$('host-restore-panel').hidden=true;$('host-restore-review').checked=false;
      $('pair-mode').checked=false;pairState='none';$('pair-request').value='';$('pair-response').value='';$('remote-input-draft').value='';gate.reviewed=false;showRemotePage();renderHosts();render();status('填写并审查新目标；不会自动连接。');
    } catch(e) {hostMessage(String(e)==='unsaved_pairing'?'当前设备身份尚未保存；请先保存或删除后再切换。':'连接尚未结束，请稍后重试。');}
  }
  async function saveCurrentHost() {
    // A pre-write catalog read must not publish obsolete identity after this write starts.
    hostRefreshRevision++;
    // Re-open only on this explicit user write, never replay host_save or key creation.
    if(!await hostInitialization && !await initializeHostCatalog()) throw hostInitError;
    const view=await invoke('host_save',{id:activeHostId,name:$('host-save-name').value,config:targetConfig()});
    activeHostId=view.id;unsavedHostOpen=false;await refreshHosts();$('host-save-status').textContent='已保存本机公开资料；不代表主机已验证或仍授权。';return view;
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
  const workspace=initTabWorkspace({native,invoke,theme,channelFactory:()=>new Channel(),terminalFactory:options=>new Terminal(options),onDashboard:onWorkspaceDashboard,getFontSize:()=>terminalFontSize,hostInfo:id=>{const host=hostRecords.find(h=>h.id===id);if(!host)return null;const networkRevision=host.networkProfileId ? networkRevisions.get(host.networkProfileId) : null;return networkRevision===undefined ? null : {...host,networkRevision};},hostName:id=>hostRecords.find(h=>h.id===id)?.name || '主机'});
  const networks=initNetworkUI({native,invoke,getHosts:()=>hostRecords,onAffected:async ids=>{workspace.affected(ids);if(ids.includes(activeHostId))cancel('网络操作涉及此主机；观察已停止，请重新核对当前配置。');await refreshHosts(false);}});
  $('terminal-font-save').disabled=!native;
  $('terminal-font-save').onclick=async()=>{const font=Number($('terminal-font-size').value);if(!Number.isInteger(font)||font<10||font>28){$('terminal-font-status').textContent='请输入 10 至 28 的整数。';return;}try{const catalog=await invoke('network_list');await invoke('preferences_save',{font,expectedCatalog:catalog.revision});terminalFontSize=font;workspace.setFont(font);if(terminal)terminal.options.fontSize=font;$('terminal-font-status').textContent='字号已保存；不改变远端终端尺寸。';}catch{$('terminal-font-status').textContent='字号保存未确认；请核查后重试。';await refreshHosts();}};
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
    scanRevision++;
    if(!activeHostId || !$('host-restore-review').checked)return;
    try {const p=await invoke('host_restore',{id:activeHostId,reviewed:true}); pairState=p.state;pairFingerprint=p.fingerprint; $('pair-request').value=p.request; $('host-restore-review').checked=false; $('host-restore-panel').hidden=true;gate.reviewed=false;pairStatus(p.state==='awaiting-host'?`原设备公钥匹配 · ${p.fingerprint}；继续等待同一请求的主机响应，需重新审查。`:p.state==='expired'?'原请求已过期；不能接受授权，请核查主机状态，可审查撤销响应或删除本机身份。':p.state==='cancelled'?'请求已取消；不能接受授权，请核查主机状态或审查撤销响应。':`原设备公钥匹配 · ${p.fingerprint}；尚未进行 SSH 认证。`);}
    catch(e){$('host-restore-status').textContent=`恢复失败：${String(e)}。不会自动生成替代身份。`;}
  });
  async function pairOperation(work) {
    if (pairBusy) return;
    hostRefreshRevision++;
    pairBusy=true; render(); renderHosts();
    try { await work(); } finally { pairBusy=false; render(); renderHosts(); }
  }
  $('pair-create').onclick=()=>pairOperation(async()=>{
    scanRevision++;
    const phase = $('pair-status').dataset;
    phase.createPhase='review';
    if (!$('pair-target-review').checked || !native) return;
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
  $('pair-scan').onclick=async()=>{
    if(!native || scanBusy || pairState==='none' || !$('pair-request').value)return;
    const revision=++scanRevision, request=$('pair-request').value; scanBusy=true; render();
    try {
      const raw=await invoke('pair_scan_response');
      if(!scanCurrent({revision,request},{revision:scanRevision,request:$('pair-request').value,showingRemote,hidden:document.hidden,pending:gate.pending}))return;
      if(typeof raw!=='string' || new TextEncoder().encode(raw).length>2048) throw Error('invalid_scan');
      $('pair-response').value=raw; $('pair-response').dispatchEvent(new Event('input',{bubbles:true})); $('pair-preview').click();
      pairStatus('已扫描公开响应；请独立核验预览和来源后再决定是否接受。');
    } catch {if(revision===scanRevision)pairStatus('扫描未完成；可继续手动粘贴响应。');}
    finally {scanBusy=false; render();}
  };
  $('pair-preview').onclick=()=>{
    previewResponse=''; $('pair-source-review').checked=false;
    try { const raw=$('pair-response').value; $('pair-response-preview').textContent=previewPairingResponse(raw); previewResponse=raw; }
    catch { $('pair-response-preview').textContent='响应格式无效；无法审查。'; }
    $('pair-response-preview').hidden=false; render();
  };
  $('pair-accept').onclick=()=>pairOperation(async()=>{
    scanRevision++;
    if (!previewResponse || !$('pair-source-review').checked) return;
    try { const p=await invoke('pair_accept',{response:previewResponse,reviewed:true}); pairState=p.state;pairFingerprint=p.fingerprint; previewResponse=''; $('pair-source-review').checked=false;
      pairStatus(p.state==='revoked'?'已审查撤销响应；不会连接。':`授权响应已审查，尚未验证 SSH · ${p.fingerprint}`);
      if(activeHostId && p.state==='authorized-unverified') {try {await saveCurrentHost();} catch { $('host-save-status').textContent='配对资料保存未确认；请核查后重试，切勿丢弃当前身份。'; }}
    } catch(e) { pairStatus(`响应拒绝：${String(e)}。请重新核对；请求未被消耗。`); }
  });
  $('pair-cancel').onclick=()=>pairOperation(async()=>{ scanRevision++; if(activeHostId)workspace.affected([activeHostId]);try { await invoke('pair_cancel'); pairState='cancelled';pairFingerprint=null; pairStatus('已取消；主机可能已授权，请核查或导入匹配的撤销响应。'); } catch(e) {pairStatus(`取消失败：${String(e)}`);} });
  $('pair-reset').onclick=()=>pairOperation(async()=>{ scanRevision++; if(activeHostId)workspace.affected([activeHostId]);try { await invoke('pair_reset'); pairState='none';pairFingerprint=null; $('pair-request').value=''; $('pair-response').value=''; previewResponse=''; $('pair-target-review').checked=false; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; pairStatus('本机身份已删除；请向主机核查或撤销可能存在的授权。'); } catch(e) {pairStatus(`删除失败：${String(e)}`);} });
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
    event.preventDefault(); if (!native) { status('浏览器预览没有原生 SSH 适配器。请使用测试安装包。','warning'); return; }
    const generation=gate.begin(); if(generation===null)return;
    let config=null;
    try {
      clearSnapshot();render();
      const value=id=>$(id).value;
      config={schemaVersion:1,host:value('remote-host'),port:Number(value('remote-port')),username:value('remote-user'),expectedHostKey:value('remote-pin'),privateKeyPem:$('pair-mode').checked?'':normalizePrivateKeyInput(value('remote-private-key')),socketPath:value('remote-socket'),herdrPath:value('remote-herdr'),session:value('remote-session'),paneId:'',reviewConfirmed:true};
      discardKey();
      const reviewedHost=hostRecords.find(h=>h.id===activeHostId);
      directSummary.begin({host:reviewedHost ? summaryHost(reviewedHost) : null,config,device:$('pair-mode').checked,pairFingerprint,generation});
      const onEvent=new Channel();
      const frames=new RemoteFrameQueue();
      let renderedFull = 0, renderedDeltas = 0;
      const captured = $('remote-captured');
      captured.dataset.fullFrames = captured.dataset.deltaFrames = '0';
      delete $('remote-input-status').dataset.receipt;
      onEvent.onmessage=event=>{
        if(!gate.accepts(generation,event.generation) || !showingRemote)return;
        if(event.kind==='input_ready') { inputGeneration=event.generation; inputUnknown=event.unknown; inputMode='observe'; inputEpoch=null; $('remote-input-controls').hidden=false; $('remote-input-recover').hidden=event.recovery_status!=='pending'; $('remote-input-status').textContent=event.recovery_status==='unavailable'?'安全记录不可用或已损坏；输入保持锁定。':inputUnknown?'存在未确认的发送记录。重新观察原目标后，核实结果并确认。':'观察模式；显式选择输入模式才可发送。'; return; }
        if(event.kind==='stage') { if(event.stage==='authenticated' && $('pair-mode').checked){directSummary.authenticated(generation);pairState='paired';pairStatus('已完成固定主机公钥核验与设备 SSH 认证。');} if(stages[event.stage])status(stages[event.stage]); return; }
        if(event.kind==='dashboard') {
          if(!validDashboard(event.panes)){cancel('会话看板无效，连接已停止。');return;}
          directSummary.snapshot(generation,event.panes);
          $('remote-dashboard').hidden=false; $('remote-panes').replaceChildren();
          const presentation=dashboardPresentation(event.panes);
          for(const pane of presentation.panes) {
            const button=document.createElement('button'); button.type='button';
            button.textContent=`${pane.paneId} · ${pane.terminalId}`;
            const details=[pane.label,paneStatusText(pane)];
            details.push([pane.workspace,pane.tab].filter(Boolean).join(' / '));
            const subtitle=details.filter(Boolean).join(' · ');
            if (subtitle) {
              const meta=document.createElement('small'); meta.className='pane-summary';
              meta.textContent=subtitle; button.append(meta);
            }
            button.onclick=()=>{ directSummary.finish(generation); selectedTarget=pane; $('remote-input-target').textContent=`目标：${pane.paneId} · ${pane.terminalId}`; for(const item of $('remote-panes').children)item.disabled=true;
              void invoke('remote_select',{generation:event.generation,paneId:pane.paneId}).catch(()=>{if(gate.accepts(generation,event.generation))cancel('选择失败，连接已停止。');});
              $('remote-dashboard').hidden=true; status(`正在观察 ${pane.paneId} · ${pane.terminalId}`);
            };
            $('remote-panes').append(button);
            const newTab=document.createElement('button');newTab.type='button';newTab.textContent=`在新标签打开 ${pane.paneId}`;
            newTab.disabled=!activeHostId || !$('pair-mode').checked;
            newTab.onclick=async()=>{const host=activeHostId;try {await waitForOldConnection(++hostNavigation);const id=workspace.create(host,pane);await workspace.select(id);status('目标已固定；请在标签中主动连接。');}catch {status('无法新建标签；请确认设备身份、连接状态和八标签上限。','warning');}};
            $('remote-panes').append(newTab);
          }
          status(presentation.summary); return;
        }
        if(event.kind!=='frame') { cancel('收到无效事件，连接已停止。'); return; }
        const frame=event.frame;
        if(!frames.accept(frame)) {cancel('画面顺序或内容异常，连接已停止，画面陈旧。');return;}
        if(!terminal) {
          $('remote-result').hidden=false;
          terminal=new Terminal({cols:80,rows:24,fontFamily:'ProbeNerd, monospace',fontSize:terminalFontSize,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme:theme.terminal,linkHandler:{activate:()=>{}}});
          terminal.parser.registerOscHandler(52,()=>true); terminal.parser.registerOscHandler(8,()=>true);
          terminal.open($('remote-terminal')); terminal.textarea.setAttribute('inputmode','none');
          const boundTerminal=terminal; inputComposition=new InputComposition();
          const keyboardPending=()=>terminal===boundTerminal && inputMode!=='direct' && !boundTerminal.options.disableStdin;
          blockPendingKeys(terminal.textarea,keyboardPending);
          terminal.onData(data=>{ if(terminal!==boundTerminal)return; const token={generation:inputGeneration,epoch:inputEpoch,revision:inputRevision}; if(!inputComposition.accepts(token)) {inputStatus('输入法提交已过期，本次未发送。');return;} renderAuxiliary();if(inputMode==='direct' && document.activeElement===terminal?.textarea) queueDirect(new TextEncoder().encode(data)); });
          terminal.textarea.addEventListener('compositionstart',()=>{if(terminal===boundTerminal)inputComposition.begin({generation:inputGeneration,epoch:inputEpoch,revision:inputRevision});},true);
          terminal.textarea.addEventListener('compositionend',()=>{if(terminal===boundTerminal)inputComposition.end();},true);
          terminal.textarea.addEventListener('blur',()=>{if(terminal===boundTerminal && !switchingFocus) loseInputFocus();});
          terminal.textarea.addEventListener('paste',event=>{
            if(terminal!==boundTerminal || (!keyboardPending() && inputMode!=='direct'))return;
            event.preventDefault(); event.stopImmediatePropagation();
            if(inputMode!=='direct')return;
            const text=event.clipboardData?.getData('text/plain') || '';
            if(!text)return;
            $('remote-input-draft').value=text; void changeInputMode('draft').then(()=>showInputPreview());
          },true);
        } else if(frame.full) terminal.reset();
        const rendered=terminal;
        terminal.write(Uint8Array.from(frame.bytes),()=>{
          if(terminal!==rendered || !gate.accepts(generation,event.generation) || !showingRemote)return;
          $('remote-captured').textContent=`${new Date().toLocaleTimeString()} 更新 · 80 × 24 · 只读观察中`;
          status('只读观察中；停止或离开后画面标记为陈旧。','success');
          if(!frames.acknowledge(frame.seq)){cancel('渲染确认异常，连接已停止。');return;}
          if (frame.full) renderedFull++; else renderedDeltas++;
          captured.dataset.fullFrames = String(renderedFull);
          captured.dataset.deltaFrames = String(renderedDeltas);
          void invoke('remote_ack',{generation:event.generation,seq:frame.seq}).catch(()=>{if(gate.accepts(generation,event.generation))cancel('渲染确认失败，连接已停止。');});
        });
      };
      if ($('pair-mode').checked) { pairState='connecting'; pairStatus('正在核验主机并认证设备；不会自动重试。'); }
      await invoke('remote_observe',{config,device:$('pair-mode').checked,hostId:activeHostId,clientGeneration:generation,onEvent});

    } catch(error) {
      if($('pair-mode').checked && pairState==='connecting') { pairState='waiting-connectivity'; pairStatus('连接或认证未完成；需手动重试，不会自动重放。'); }
      if(gate.accepts(generation)){ if(['provider_unavailable','overlay_provider_unavailable'].includes(String(error))) errors[String(error)]='网络桥接不可用；没有使用系统网络回退。'; if(String(error)==='mobile_node_not_started') errors.mobile_node_not_started='请先启动此网络的本机节点；不会回退到系统网络。'; if(String(error)==='network_public_mode_unsupported') errors.network_public_mode_unsupported='公开无秘密模式暂不支持节点启动。'; if(String(error)==='network_identity_missing') errors.network_identity_missing='本机网络身份尚未配置。'; if(['network_identity_changed','mobile_node_binding_mismatch','overlay_stale_revision'].includes(String(error))) errors[String(error)]='网络配置或本机身份已变化；请核对节点后重新连接。'; if(String(error)==='network_profile_disabled') errors.network_profile_disabled='网络配置已停用；无法连接。'; if(terminal) $('remote-captured').textContent='连接已结束 · 画面陈旧'; $('remote-dashboard').hidden=true; status(errors[String(error)] || '观察已结束，画面陈旧。重新连接需手动核验；没有自动重放。','warning'); }
    } finally { directSummary.finish(generation);discardKey(); if(config)config.privateKeyPem=''; if(gate.finish(generation)){const lost=invalidateInput();recordUnsent(lost.count);} gate.reviewed=false; render(); }
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden){workspace.background();cancel('应用进入后台，已取消读取并清除临时私钥。回到前台后需重新核验。');}});
  window.addEventListener('pagehide',()=>{workspace.background();cancel();});
  // The browser never substitutes fixture output for a failed/missing native transport.
  $('remote-native-note').hidden=native;
  showingRemote=false; if(native)initializeHostCatalog(); void refreshHosts();
  $('host-open-remote').disabled=false; $('show-fixture').disabled=false;
  status(native?'待审查连接资料；没有建立远端连接。':'浏览器仅预览表单与布局，没有原生 SSH 功能。','info');render();
}
