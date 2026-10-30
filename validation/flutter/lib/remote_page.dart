import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'remote_adapter.dart';

String pemFromSingleLineInput(String text) {
  final normalized = text.replaceAll(r'\n','\n').trim();
  final match = RegExp(r'^-----BEGIN OPENSSH PRIVATE KEY-----\s*([A-Za-z0-9+/=\s]+)-----END OPENSSH PRIVATE KEY-----$').firstMatch(normalized);
  if (match == null) throw const RemoteFailure('invalid_private_key');
  final body = match.group(1)!.replaceAll(RegExp(r'\s'),'');
  return '-----BEGIN OPENSSH PRIVATE KEY-----\n$body\n-----END OPENSSH PRIVATE KEY-----\n';
}

class RemotePage extends StatefulWidget {
  const RemotePage({super.key,required this.tokens,this.adapter});
  final DesignTokens tokens;
  final RemoteReadOnlyAdapter? adapter;
  @override
  State<RemotePage> createState() => _RemotePageState();
}

class _RemotePageState extends State<RemotePage> with WidgetsBindingObserver {
  late final adapter = widget.adapter ?? RemoteReadOnlyAdapter();
  final fields = <String,TextEditingController>{
    for (final name in ['host','port','username','expectedHostKey','privateKeyPem','socketPath','herdrPath','session','paneId'])
      name:TextEditingController(text:name == 'port' ? '22' : ''),
  };
  bool reviewed = false, busy = false;
  int request = 0;
  String status = '审查接入 → 会话 pane 看板 → 选择目标观察';
  RemoteDashboard? dashboard;
  String? selectedPane;
  bool live = false;
  int? sequence;
  RemoteSnapshot? snapshot;
  DateTime? capturedAt;
  Terminal? terminal;

  @override
  void initState() { super.initState(); WidgetsBinding.instance.addObserver(this); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) stop('应用已暂停，连接已取消；请重新核验后主动连接');
  }
  void stop([String message = '已取消；不会重连或发送输入']) {
    request++; unawaited(adapter.cancel());
    fields['privateKeyPem']!.clear();
    if (mounted) setState(() { busy = false; live = false; reviewed = false; status = message; });
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this); request++;
    unawaited(adapter.cancel()); terminal?.dispose();
    for (final c in fields.values) { c.clear(); c.dispose(); }
    super.dispose();
  }

  Future<void> connect() async {
    if (!reviewed || busy) return;
    final ticket = ++request;
    try {
      final config = RemoteConfig.fromJson({
        'schemaVersion':1,for (final e in fields.entries) if (e.key != 'port' && e.key != 'privateKeyPem') e.key:e.value.text,
        'port':int.tryParse(fields['port']!.text),
        'privateKeyPem':pemFromSingleLineInput(fields['privateKeyPem']!.text),
        'reviewConfirmed':reviewed,
      });
      fields['privateKeyPem']!.clear();
      FocusScope.of(context).unfocus();
      setState(() { busy = true; live = false; dashboard = null; selectedPane = null; sequence = null; snapshot = null; capturedAt = null; terminal?.dispose(); terminal = null; status = '正在连接并核验主机身份'; });
      await adapter.observe(config,onDashboard:(value) {
        if (!mounted || ticket != request) return;
        setState(() { dashboard = value; reviewed = false;
          status = value.panes.isEmpty ? '会话看板为空 · 未发现 pane，不代表主机没有任务' : '会话看板已核验 · 请选择一个明确 pane 开始观察'; });
      },onFrame:(generation,paneId,frame) {
        if (!mounted || ticket != request || dashboard?.generation != generation || selectedPane != paneId) return;
        if (frame.full) {
          terminal?.dispose();
          terminal = Terminal(maxLines:24,reflowEnabled:false)..resize(80,24);
        }
        terminal!.write(frame.ansi);
        setState(() { snapshot = RemoteSnapshot(generation,config.session,paneId,frame.ansi);
          capturedAt = DateTime.now(); sequence = frame.seq; live = true;
          status = '正在只读观察 · 输入关闭'; });
      },onProgress:(generation,phase) {
        if (!mounted || ticket != request) return;
        if (phase == 'snapshot_received' || phase == 'full_received') return;
        setState(() { status = switch (phase) {
          'connecting' => '正在连接 · 尚未信任主机',
          'snapshot' => '主机身份与认证通过 · 读取会话看板',
          'observing' => '目标已绑定 · 等待首张完整画面',
          _ => '正在核验',
        }; });
      });
    } catch (error) {
      if (!mounted || ticket != request) return;
      final code = error is RemoteFailure ? error.code : 'connection_failed';
      setState(() { busy = false; live = false; reviewed = false;
        status = switch (code) {
          'host_key_mismatch' => '主机指纹不符 · 已在认证前拒绝，请从可信渠道重新核验',
          'session_mismatch' || 'pane_missing' || 'invalid_terminal_id' || 'invalid_snapshot' || 'stale_selection' => '指定会话或目标不匹配 · 已停止，请检查资料',
          'cancelled' => '已取消 · 不会自动重连',
          'invalid_private_key' => '仅支持内存中的未加密 OpenSSH Ed25519 测试私钥，请重新输入',
          'invalid_host_key' => '预期主机公钥格式无效 · 仅接受 ssh-ed25519 与 base64 两字段',
          'review_required' => '请重新审查目标与主机身份',
          'authentication_failed' || 'authentication_aborted' => 'SSH 认证未通过 · 请核验账号与临时公钥授权，不会尝试密码或其他身份',
          'connection_busy' => '上一连接仍在关闭 · 请稍后主动重试',
          'unsupported_protocol' => '此实验只支持 herdr 0.9.5 / protocol 22，未继续读取',
          'timeout' => '连接或读取超时 · 未自动重试',
          'sequence_gap' => '观察序号不连续 · 已停止，旧画面不可视为当前状态',
          'invalid_first_frame' || 'invalid_frame' || 'invalid_response' || 'truncated_response' => '观察数据不完整或格式异常 · 已停止，请重新审查连接',
          'output_limit' => '观察缓冲超过上限 · 已停止，不能跳过增量继续',
          'observe_ended' => '远端观察已结束／断线 · 已保留旧画面，请重新审查连接',
          _ => '连接或读取失败 · 已停止，请重新审查资料后主动连接',
        }; if (snapshot != null) status = '旧画面 · $status'; });
    } finally { if (mounted && ticket == request) fields['privateKeyPem']!.clear(); }
  }

  void selectPane(RemotePane pane) {
    final board = dashboard;
    if (!busy || board == null || selectedPane != null) return;
    setState(() { selectedPane = pane.paneId; live = false; status = '目标已选择 · 等待新 full'; });
    try { adapter.selectPane(board.generation,pane.paneId); }
    on RemoteFailure { stop('目标选择已失效 · 请重新审查连接'); }
  }

  Future<void> pastePrivateKey() async {
    if (busy) return;
    final ticket = request;
    ClipboardData? data;
    try { data = await Clipboard.getData(Clipboard.kTextPlain); } catch (_) {
      if (mounted && ticket == request) setState(() { status = '系统剪贴板不可用，可手动输入临时私钥'; });
      return;
    }
    if (!mounted || busy || ticket != request || data?.text == null) return;
    if (data!.text!.length > 16384) {
      setState(() { status = '临时私钥超过大小限制，未粘贴'; }); return;
    }
    fields['privateKeyPem']!.text = data.text!.replaceAll('\r\n','\n').replaceAll('\n',r'\n');
    setState(() { reviewed = false; request++; });
  }

  Widget input(String name,String label,{bool secret=false,String? hint}) => Padding(
    padding:const EdgeInsets.only(bottom:14),child:TextField(
      key:ValueKey('remote-$name'),controller:fields[name],enabled:!busy,
      obscureText:secret,enableSuggestions:!secret,autocorrect:false,
      enableIMEPersonalizedLearning:!secret,enableInteractiveSelection:!secret,
      keyboardType:name == 'port' ? TextInputType.number : TextInputType.text,
      maxLength:secret ? 16384 : name == 'expectedHostKey' ? 4096 : 1024,
      maxLines:1,decoration:InputDecoration(labelText:label,hintText:hint,counterText:'',
        helperText:secret ? '仅内存使用，连接/取消后清空；尚未实现设备安全存储' : null,
        suffixIcon:secret ? IconButton(tooltip:'粘贴临时私钥',onPressed:busy ? null : pastePrivateKey,
          icon:const Icon(Icons.content_paste)) : null),
      onChanged:(_) { request++; if (reviewed) setState(() { reviewed = false; }); },
    ));

  @override
  Widget build(BuildContext context) => PopScope(
    onPopInvokedWithResult:(didPop,result) { if (didPop) stop(); },
    child:Scaffold(appBar:AppBar(title:const Text('远端接入 · 只读'),
      leading:IconButton(tooltip:'返回离线验证',icon:const Icon(Icons.arrow_back),
        onPressed:() { stop(); Navigator.pop(context); })),
      body:SafeArea(child:SingleChildScrollView(padding:const EdgeInsets.all(16),
        child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
          Text('M1b 手机只读看板',style:Theme.of(context).textTheme.titleLarge),
          const SizedBox(height:8),
          const Text('仅用于隔离测试主机。审查接入后查看当前命名会话，选择明确 pane 观察。布局只改变本地视口，不调整共享 PTY。'),
          const SizedBox(height:12),
          Semantics(liveRegion:true,child:Text(status,key:const ValueKey('remote-status'),
            style:TextStyle(color:widget.tokens.color('textSecondary')))),
          if (busy) TextButton.icon(key:const ValueKey('remote-cancel'),onPressed:stop,
            icon:const Icon(Icons.stop_circle_outlined),label:const Text('停止并断开')),
          if (dashboard != null) ...[
            const SizedBox(height:12),
            Text('会话 ${dashboard!.session}',style:Theme.of(context).textTheme.titleMedium),
            Text('仅来自已核验 socket 的 snapshot · ${dashboard!.panes.length} 个 pane\n${busy ? '连接保持，等待选择或正在观察' : '看板已陈旧，需重新审查连接'}'),
            if (dashboard!.panes.isEmpty) const Padding(padding:EdgeInsets.symmetric(vertical:16),
              child:Text('没有 pane · 不会回退到其他会话')),
            for (final pane in dashboard!.panes) Card(child:Padding(padding:const EdgeInsets.all(12),
              child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
                Text(pane.paneId,style:Theme.of(context).textTheme.titleMedium),
                Text(pane.terminalId,softWrap:true),
                const SizedBox(height:8),
                FilledButton(key:ValueKey('remote-pane-${pane.paneId}'),
                  onPressed:busy && selectedPane == null ? () => selectPane(pane) : null,
                  child:Text(selectedPane == pane.paneId ? '已选目标 · 只读' : '选择此 pane 观察')),
              ]))),
          ],
          if (dashboard == null || !busy) ...[
          const SizedBox(height:16),
          Text('1 · 连接目标',style:Theme.of(context).textTheme.titleMedium),
          const SizedBox(height:12),
          input('host','SSH 主机 / IP'),input('port','SSH 端口'),input('username','SSH 用户'),
          input('session','herdr 会话名（非 default）'),
          input('socketPath','远端命名会话 socket 绝对路径',hint:'/.../herdr/sessions/会话/herdr.sock'),
          input('herdrPath','远端 herdr 可执行文件绝对路径'),
          Text('2 · 主机身份核验',style:Theme.of(context).textTheme.titleMedium),
          const SizedBox(height:12),
          input('expectedHostKey','预期主机 Ed25519 公钥',hint:'ssh-ed25519 BASE64（无注释）'),
          Text('3 · 内存临时凭据',style:Theme.of(context).textTheme.titleMedium),
          const SizedBox(height:12),
          input('privateKeyPem','临时 Ed25519 私钥',secret:true),
          CheckboxListTile(key:const ValueKey('remote-review'),contentPadding:EdgeInsets.zero,
            value:reviewed,onChanged:busy ? null : (value) => setState(() { reviewed = value ?? false; }),
            title:const Text('我已通过可信渠道核验主机公钥、账号与目标资料'),
            subtitle:const Text('输入或保存资料不等于信任；任何编辑都会清除此确认。')),
          const SizedBox(height:8),
          FilledButton.icon(key:const ValueKey('remote-connect'),onPressed:reviewed && !busy ? connect : null,
            icon:const Icon(Icons.lock_outline),label:Text(dashboard == null ? '核验并读取会话看板' : '重新审查并连接')),
          ],
          if (snapshot != null && terminal != null) ...[
            const SizedBox(height:12),
            Text('${snapshot!.session} / ${snapshot!.paneId}\n${live ? '只读观察中' : '旧画面 · 已停止'} · seq $sequence\n更新于 ${capturedAt!.toLocal().toIso8601String()} · 固定 80×24'),
            const SizedBox(height:8),
            SizedBox(height:360,child:ClipRRect(borderRadius:BorderRadius.circular(12),
              child:TerminalView(terminal!,theme:widget.tokens.terminalTheme,
                autoResize:false,readOnly:true,simulateScroll:false,hardwareKeyboardOnly:true,
                textStyle:const TerminalStyle(fontFamily:'ProbeNerd',fontSize:14),shortcuts:const {},
                onKeyEvent:(node,event) => KeyEventResult.handled))),
          ],
        ])))));
}
