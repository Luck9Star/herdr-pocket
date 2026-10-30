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
  String status = '手动接入实验 · 只获取一张真实远端画面';
  RemoteSnapshot? snapshot;
  DateTime? capturedAt;
  Terminal? terminal;

  @override
  void initState() { super.initState(); WidgetsBinding.instance.addObserver(this); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) stop('应用已暂停，连接已取消；请重新核验后主动连接');
  }
  void stop([String message = '已取消；不会重连或发送输入']) {
    request++; unawaited(adapter.cancel());
    fields['privateKeyPem']!.clear();
    if (mounted) setState(() { busy = false; reviewed = false; status = message; });
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
      setState(() { busy = true; snapshot = null; capturedAt = null; terminal?.dispose(); terminal = null; status = '正在连接并核验主机身份'; });
      final result = await adapter.read(config,onProgress:(generation,phase) {
        if (!mounted || ticket != request) return;
        setState(() { status = switch (phase) {
          'connecting' => '正在连接 · 尚未信任主机',
          'snapshot' => '主机身份与认证通过 · 读取会话看板',
          'snapshot_received' => '目标已绑定 · 准备获取只读快照',
          'observing' => '等待目标首张完整画面',
          'full_received' => '已收到完整画面 · 正在关闭连接',
          _ => '正在核验',
        }; });
      });
      if (!mounted || ticket != request) return;
      final view = Terminal(maxLines:2000,reflowEnabled:false);
      // No title, bell, OSC, clipboard, URL, output or resize callbacks.
      view.resize(80,24); view.write(result.ansi);
      setState(() { snapshot = result; terminal = view; capturedAt = DateTime.now();
        status = '只读快照 · 连接已关闭，画面不会实时更新'; busy = false; reviewed = false; });
    } catch (error) {
      if (!mounted || ticket != request) return;
      final code = error is RemoteFailure ? error.code : 'connection_failed';
      setState(() { busy = false; reviewed = false;
        status = switch (code) {
          'host_key_mismatch' => '主机指纹不符 · 已在认证前拒绝，请从可信渠道重新核验',
          'session_mismatch' || 'pane_missing' || 'invalid_terminal_id' => '指定会话或目标不匹配 · 已停止，请检查资料',
          'cancelled' => '已取消 · 不会自动重连',
          'invalid_private_key' => '仅支持内存中的未加密 OpenSSH Ed25519 测试私钥，请重新输入',
          'invalid_host_key' => '预期主机公钥格式无效 · 仅接受 ssh-ed25519 与 base64 两字段',
          'review_required' => '请重新审查目标与主机身份',
          'authentication_failed' || 'authentication_aborted' => 'SSH 认证未通过 · 请核验账号与临时公钥授权，不会尝试密码或其他身份',
          'connection_busy' => '上一连接仍在关闭 · 请稍后主动重试',
          'unsupported_protocol' => '此实验只支持 herdr 0.9.5 / protocol 22，未继续读取',
          'timeout' => '连接或读取超时 · 未自动重试',
          _ => '读取失败（$code）· 请检查资料，再主动连接',
        }; });
    } finally { if (mounted && ticket == request) fields['privateKeyPem']!.clear(); }
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
          Text('M1a 手动接入',style:Theme.of(context).textTheme.titleLarge),
          const SizedBox(height:8),
          const Text('仅用于隔离测试主机。先核验资料，再获取一个明确目标的真实快照。此入口没有扫码配对、组网或远端输入。'),
          const SizedBox(height:16),
          Text('1 · 连接目标',style:Theme.of(context).textTheme.titleMedium),
          const SizedBox(height:12),
          input('host','SSH 主机 / IP'),input('port','SSH 端口'),input('username','SSH 用户'),
          input('session','herdr 会话名（非 default）'),input('paneId','目标 pane ID',hint:'例如 w1:p1'),
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
            icon:const Icon(Icons.lock_outline),label:const Text('核验并获取只读快照')),
          if (busy) TextButton.icon(key:const ValueKey('remote-cancel'),onPressed:stop,
            icon:const Icon(Icons.close),label:const Text('取消连接')),
          const SizedBox(height:12),
          Semantics(liveRegion:true,child:Text(status,key:const ValueKey('remote-status'),
            style:TextStyle(color:widget.tokens.color('textSecondary')))),
          if (snapshot != null && terminal != null) ...[
            const SizedBox(height:12),
            Text('${snapshot!.session} / ${snapshot!.paneId}\n获取于 ${capturedAt!.toLocal().toIso8601String()} · 80×24 · 非实时'),
            const SizedBox(height:8),
            SizedBox(height:360,child:ClipRRect(borderRadius:BorderRadius.circular(12),
              child:TerminalView(terminal!,theme:widget.tokens.terminalTheme,
                autoResize:false,readOnly:true,simulateScroll:false,hardwareKeyboardOnly:true,
                textStyle:const TerminalStyle(fontFamily:'ProbeNerd',fontSize:14),shortcuts:const {},
                onKeyEvent:(node,event) => KeyEventResult.handled))),
          ],
        ])))));
}
