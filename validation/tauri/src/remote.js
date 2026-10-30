import { Terminal } from '@xterm/xterm';
import { invoke, Channel } from '@tauri-apps/api/core';
import { RemoteViewGate } from './remote-state.js';
import { normalizePrivateKeyInput } from './remote-key.js';

export function initRemote({ native, theme, onFixture }) {
  const $ = id => document.getElementById(id), gate = new RemoteViewGate();
  let terminal = null, showingRemote = true;
  const stages = { connecting:'连接 SSH，等待服务器身份核验…', 'host-key-verified':'预期主机公钥已匹配，开始临时公钥认证…', authenticated:'认证完成，读取指定 socket 的会话快照…', 'snapshot-received':'目标映射已核对，读取首个完整画面…', 'full-frame-received':'完整画面已校验，正在关闭连接…' };
  const errors = { host_key_mismatch:'主机公钥不匹配。认证未开始；请回到独立可信渠道核对。', authentication_failed:'临时公钥认证失败。未尝试其他凭据。', session_mismatch:'socket 与命名会话不一致。仅支持 release herdr 的 /herdr/sessions/<会话>/herdr.sock 路径。', pane_missing:'快照中没有指定 pane。请核对 pane 标识后重新审查。', invalid_private_key:'仅支持本轮实验用、未加密的 OpenSSH Ed25519 私钥。', invalid_host_key:'主机公钥应为 ssh-ed25519 与完整公钥数据两字段。', invalid_config:'资料不完整或格式不支持。核对后重新审查。', socket_unavailable:'指定 socket 不可用。请检查会话是否已启动及 SSH 转发权限。', timeout:'读取超时，连接已终止。不会自动重试。', connection_failed:'SSH 无法连接。请检查地址、端口和网络路径。', cancelled:'本次读取已取消。迟到结果不会显示。', unsupported_protocol:'服务器快照版本不支持；本轮仅验证 herdr 0.9.5。' };
  function status(message, tone='info') { $('remote-status').textContent=message; $('remote-status').dataset.tone=tone; }
  function render() {
    $('remote-fields').disabled=gate.pending;
    $('remote-connect').disabled=!native || gate.pending || !gate.reviewed;
    $('remote-cancel').disabled=!gate.pending;
    $('remote-review').checked=gate.reviewed;
  }
  function clearSnapshot() { terminal?.dispose(); terminal=null; $('remote-terminal').replaceChildren(); $('remote-result').hidden=true; }
  function discardKey() { $('remote-private-key').value=''; }
  function cancel(reason='本次读取已取消。迟到结果不会显示。') {
    gate.invalidate(); discardKey(); clearSnapshot(); status(reason); render();
    // Invalidating precedes asynchronous cleanup. Keep busy until the old invoke settles.
    if (gate.pending && native) void invoke('remote_cancel').catch(()=>status('正在结束旧连接；结束前不可开始新读取。','warning'));
  }
  $('remote-form').addEventListener('input', event => {
    if (event.target.id==='remote-review') { gate.reviewed=event.target.checked; render(); return; }
    gate.invalidate(); clearSnapshot(); render();
  });
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
      config={schemaVersion:1,host:value('remote-host'),port:Number(value('remote-port')),username:value('remote-user'),expectedHostKey:value('remote-pin'),privateKeyPem:normalizePrivateKeyInput(value('remote-private-key')),socketPath:value('remote-socket'),herdrPath:value('remote-herdr'),session:value('remote-session'),paneId:value('remote-pane'),reviewConfirmed:true};
      discardKey();
      const onEvent=new Channel();
      onEvent.onmessage=event=>{if(gate.accepts(generation,event.generation) && showingRemote && stages[event.stage])status(stages[event.stage]);};
      const result=await invoke('remote_read_once',{config,onEvent});
      if(!gate.accepts(generation,result.generation) || !showingRemote)return;
      const frame=result.snapshot;
      if(frame.columns!==80 || frame.rows!==24 || !Array.isArray(frame.bytes) || frame.bytes.length>1_048_576 || !frame.bytes.every(b=>Number.isInteger(b)&&b>=0&&b<=255)) throw 'invalid_full_frame';
      $('remote-result').hidden=false;
      terminal=new Terminal({cols:80,rows:24,fontFamily:'ProbeNerd, monospace',fontSize:14,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme:theme.terminal,linkHandler:{activate:()=>{}}});
      // Remote bytes never enter the fixture input gate; no onData transport is registered.
      terminal.parser.registerOscHandler(52,()=>true);
      terminal.parser.registerOscHandler(8,()=>true);
      terminal.open($('remote-terminal')); terminal.textarea.setAttribute('inputmode','none');
      const rendered=terminal;
      terminal.write(Uint8Array.from(frame.bytes),()=>{
        if(terminal!==rendered || generation!==gate.generation || !showingRemote)return;
        $('remote-captured').textContent=`${new Date().toLocaleTimeString()} 获取 · 80 × 24 · ${frame.terminalId} · 连接已关闭`;
      });
      status('只读快照已获取，连接已关闭。需要新画面时，请重新提供临时凭据、核验并手动读取。','success');
    } catch(error) {
      if(gate.accepts(generation))status(errors[String(error)] || '读取未完成，连接已终止。请核对资料后手动重试；没有自动重放。','warning');
    } finally { discardKey(); if(config)config.privateKeyPem=''; gate.finish(generation); gate.reviewed=false; render(); }
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel('应用进入后台，已取消读取并清除临时私钥。回到前台后需重新核验。');});
  window.addEventListener('pagehide',()=>cancel());
  // The browser never substitutes fixture output for a failed/missing native transport.
  $('remote-native-note').hidden=native;
  status(native?'待审查连接资料；没有建立远端连接。':'浏览器仅预览表单与布局，没有原生 SSH 功能。','info');render();
}
