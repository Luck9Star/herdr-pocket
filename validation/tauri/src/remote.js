import { Terminal } from '@xterm/xterm';
import { invoke, Channel } from '@tauri-apps/api/core';
import { RemoteViewGate, RemoteFrameQueue, validDashboard } from './remote-state.js';
import { normalizePrivateKeyInput } from './remote-key.js';
import { previewPairingResponse } from './pairing-view.js';

export function initRemote({ native, theme, onFixture }) {
  const $ = id => document.getElementById(id), gate = new RemoteViewGate();
  let terminal = null, showingRemote = true, pairState = 'none', previewResponse = '', pairBusy = false;
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
    $('remote-connect').disabled=!native || pairBusy || gate.pending || !gate.reviewed || ($('pair-mode').checked && !pairReady());
    $('pair-controls').hidden=!$('pair-mode').checked; $('manual-key-section').hidden=$('pair-mode').checked;
    $('remote-private-key').required=!$('pair-mode').checked;
    $('pair-create').disabled=!native || gate.pending || pairState!=='none' || !$('pair-target-review').checked;
    $('pair-accept').disabled=!native || gate.pending || !previewResponse || !$('pair-source-review').checked;
    $('pair-reset').disabled=!native || gate.pending || pairState==='none';
    $('pair-cancel').disabled=!native || gate.pending || pairState==='none' || pairState==='cancelled' || pairState==='revoked';
    $('remote-cancel').disabled=!gate.pending;
    $('remote-review').checked=gate.reviewed;
  }
  function clearSnapshot() { terminal?.dispose(); terminal=null; $('remote-terminal').replaceChildren(); $('remote-result').hidden=true; $('remote-dashboard').hidden=true; $('remote-panes').replaceChildren(); }
  function discardKey() { $('remote-private-key').value=''; }
  function cancel(reason='本次读取已取消。迟到结果不会显示。') {
    const clientGeneration=gate.pendingGeneration;
    gate.invalidate(); discardKey(); if ($('pair-mode').checked && gate.pending && pairState!=='paired') { pairState='cancelled'; pairStatus('已取消；主机授权状态可能未知，请核查清理。'); } $('remote-dashboard').hidden=true; if(terminal) $('remote-captured').textContent='观察已停止 · 画面陈旧'; status(reason); render();
    // Invalidating precedes asynchronous cleanup. Keep busy until the old invoke settles.
    if (gate.pending && native) void invoke('remote_cancel',{clientGeneration}).catch(()=>{if(gate.pendingGeneration===clientGeneration)status('正在结束旧连接；结束前不可开始新读取。','warning');});
  }
  $('remote-form').addEventListener('input', event => {
    if (pairTargetIds.includes(event.target.id) && pairState==='none') $('pair-target-review').checked=false;
    if (event.target.id==='pair-mode') { $('remote-private-key').required=!event.target.checked; }
    if (['pair-target-review','pair-source-review'].includes(event.target.id)) { render(); return; }
    if (event.target.id==='pair-response') { previewResponse=''; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; render(); return; }
    if (event.target.id==='remote-review') { gate.reviewed=event.target.checked; render(); return; }
    gate.invalidate(); clearSnapshot(); render();
  });
  async function pairOperation(work) {
    if (pairBusy) return;
    pairBusy=true; render();
    try { await work(); } finally { pairBusy=false; render(); }
  }
  $('pair-create').onclick=()=>pairOperation(async()=>{
    if (!$('pair-target-review').checked || !native) return;
    if (pairTargetIds.some(id=>!$(id).checkValidity() || !$(id).value)) { pairStatus('请先完整填写连接目标，再重新核对目标。'); $('pair-target-review').checked=false; return; }
    try { const config={schemaVersion:1,host:$('remote-host').value,port:Number($('remote-port').value),username:$('remote-user').value,expectedHostKey:$('remote-pin').value,privateKeyPem:'',socketPath:$('remote-socket').value,herdrPath:$('remote-herdr').value,session:$('remote-session').value,paneId:'',reviewConfirmed:true}; const p=await invoke('pair_create',{config,device:$('pair-device').value});
      $('pair-request').value=p.request; pairState=p.state; pairStatus(`等待主机响应 · 设备指纹 ${p.fingerprint} · 授权未知`);
    } catch(e) { pairStatus(`创建失败：${String(e)}。没有自动重建设备身份。`); }
  });
  $('pair-preview').onclick=()=>{
    previewResponse=''; $('pair-source-review').checked=false;
    try { const raw=$('pair-response').value; $('pair-response-preview').textContent=previewPairingResponse(raw); previewResponse=raw; }
    catch { $('pair-response-preview').textContent='响应格式无效；无法审查。'; }
    $('pair-response-preview').hidden=false; render();
  };
  $('pair-accept').onclick=()=>pairOperation(async()=>{
    if (!previewResponse || !$('pair-source-review').checked) return;
    try { const p=await invoke('pair_accept',{response:previewResponse,reviewed:true}); pairState=p.state; previewResponse=''; $('pair-source-review').checked=false;
      pairStatus(p.state==='revoked'?'已审查撤销响应；不会连接。':`授权响应已审查，尚未验证 SSH · ${p.fingerprint}`);
    } catch(e) { pairStatus(`响应拒绝：${String(e)}。请重新核对；请求未被消耗。`); }
  });
  $('pair-cancel').onclick=()=>pairOperation(async()=>{ try { await invoke('pair_cancel'); pairState='cancelled'; pairStatus('已取消；主机可能已授权，请核查或导入匹配的撤销响应。'); } catch(e) {pairStatus(`取消失败：${String(e)}`);} });
  $('pair-reset').onclick=()=>pairOperation(async()=>{ try { await invoke('pair_reset'); pairState='none'; $('pair-request').value=''; $('pair-response').value=''; previewResponse=''; $('pair-target-review').checked=false; $('pair-source-review').checked=false; $('pair-response-preview').hidden=true; pairStatus('本机身份已删除；请向主机核查或撤销可能存在的授权。'); } catch(e) {pairStatus(`删除失败：${String(e)}`);} });
  $('remote-cancel').onclick=()=>cancel();
  $('remote-clear-key').onclick=()=>{ cancel('临时私钥已从表单清除。'); };
  $('remote-hide-keyboard').onclick=()=>document.activeElement?.blur();
  $('show-fixture').onclick=()=>{
    cancel('已离开远端读取；没有后台连接或自动恢复。'); showingRemote=false;
    $('remote-page').hidden=true; $('fixture-workbench').hidden=false;
    $('show-fixture').setAttribute('aria-pressed','true'); $('show-remote').setAttribute('aria-pressed','false'); onFixture();
  };
  $('show-remote').onclick=()=>{
    showingRemote=true; $('remote-page').hidden=false; $('fixture-workbench').hidden=true;
    $('show-fixture').setAttribute('aria-pressed','false'); $('show-remote').setAttribute('aria-pressed','true');
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
      const onEvent=new Channel();
      const frames=new RemoteFrameQueue();
      onEvent.onmessage=event=>{
        if(!gate.accepts(generation,event.generation) || !showingRemote)return;
        if(event.kind==='stage') { if(event.stage==='authenticated' && $('pair-mode').checked){pairState='paired';pairStatus('已完成固定主机公钥核验与设备 SSH 认证。');} if(stages[event.stage])status(stages[event.stage]); return; }
        if(event.kind==='dashboard') {
          if(!validDashboard(event.panes)){cancel('会话看板无效，连接已停止。');return;}
          $('remote-dashboard').hidden=false; $('remote-panes').replaceChildren();
          for(const pane of event.panes) {
            const button=document.createElement('button'); button.type='button';
            button.textContent=`${pane.paneId} · ${pane.terminalId}`;
            button.onclick=()=>{ for(const item of $('remote-panes').children)item.disabled=true;
              void invoke('remote_select',{generation:event.generation,paneId:pane.paneId}).catch(()=>{if(gate.accepts(generation,event.generation))cancel('选择失败，连接已停止。');});
              $('remote-dashboard').hidden=true; status(`正在观察 ${pane.paneId} · ${pane.terminalId}`);
            };
            $('remote-panes').append(button);
          }
          status(event.panes.length?'请选择本次会话中的 pane。':'当前会话没有可观察的 pane；请停止连接。'); return;
        }
        if(event.kind!=='frame') { cancel('收到无效事件，连接已停止。'); return; }
        const frame=event.frame;
        if(!frames.accept(frame)) {cancel('画面顺序或内容异常，连接已停止，画面陈旧。');return;}
        if(!terminal) {
          $('remote-result').hidden=false;
          terminal=new Terminal({cols:80,rows:24,fontFamily:'ProbeNerd, monospace',fontSize:14,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme:theme.terminal,linkHandler:{activate:()=>{}}});
          terminal.parser.registerOscHandler(52,()=>true); terminal.parser.registerOscHandler(8,()=>true);
          terminal.open($('remote-terminal')); terminal.textarea.setAttribute('inputmode','none');
        } else if(frame.full) terminal.reset();
        const rendered=terminal;
        terminal.write(Uint8Array.from(frame.bytes),()=>{
          if(terminal!==rendered || !gate.accepts(generation,event.generation) || !showingRemote)return;
          $('remote-captured').textContent=`${new Date().toLocaleTimeString()} 更新 · 80 × 24 · 只读观察中`;
          status('只读观察中；停止或离开后画面标记为陈旧。','success');
          if(!frames.acknowledge(frame.seq)){cancel('渲染确认异常，连接已停止。');return;}
          void invoke('remote_ack',{generation:event.generation,seq:frame.seq}).catch(()=>{if(gate.accepts(generation,event.generation))cancel('渲染确认失败，连接已停止。');});
        });
      };
      if ($('pair-mode').checked) { pairState='connecting'; pairStatus('正在核验主机并认证设备；不会自动重试。'); }
      await invoke('remote_observe',{config,device:$('pair-mode').checked,clientGeneration:generation,onEvent});

    } catch(error) {
      if($('pair-mode').checked && pairState==='connecting') { pairState='waiting-connectivity'; pairStatus('连接或认证未完成；需手动重试，不会自动重放。'); }
      if(gate.accepts(generation)){ if(terminal) $('remote-captured').textContent='连接已结束 · 画面陈旧'; $('remote-dashboard').hidden=true; status(errors[String(error)] || '观察已结束，画面陈旧。重新连接需手动核验；没有自动重放。','warning'); }
    } finally { discardKey(); if(config)config.privateKeyPem=''; gate.finish(generation); gate.reviewed=false; render(); }
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel('应用进入后台，已取消读取并清除临时私钥。回到前台后需重新核验。');});
  window.addEventListener('pagehide',()=>cancel());
  // The browser never substitutes fixture output for a failed/missing native transport.
  $('remote-native-note').hidden=native;
  status(native?'待审查连接资料；没有建立远端连接。':'浏览器仅预览表单与布局，没有原生 SSH 功能。','info');render();
}
