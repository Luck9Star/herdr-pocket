import 'dart:async';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'remote_adapter.dart';
import 'remote_input.dart';
import 'remote_input_platform.dart';
import 'device_keys.dart';

String pemFromSingleLineInput(String text) {
  final normalized = text.replaceAll(r'\n','\n').trim();
  final match = RegExp(r'^-----BEGIN OPENSSH PRIVATE KEY-----\s*([A-Za-z0-9+/=\s]+)-----END OPENSSH PRIVATE KEY-----$').firstMatch(normalized);
  if (match == null) throw const RemoteFailure('invalid_private_key');
  final body = match.group(1)!.replaceAll(RegExp(r'\s'),'');
  return '-----BEGIN OPENSSH PRIVATE KEY-----\n$body\n-----END OPENSSH PRIVATE KEY-----\n';
}

class RemotePage extends StatefulWidget {
  const RemotePage({super.key,required this.tokens,this.adapter,this.pairedTarget,this.deviceKeys,this.keyHandle,this.devicePublicKey,this.onConnecting,this.onAuthenticated,this.onStopped,this.visibility});
  final DesignTokens tokens;
  final RemoteReadOnlyAdapter? adapter;
  final Map<String,dynamic>? pairedTarget;
  final DeviceKeys? deviceKeys;
  final String? keyHandle, devicePublicKey;
  final VoidCallback? onConnecting, onAuthenticated, onStopped;
  final ValueListenable<bool>? visibility;
  @override
  State<RemotePage> createState() => _RemotePageState();
}

class _RemotePageState extends State<RemotePage> with WidgetsBindingObserver {
  late final adapter = widget.adapter ?? RemoteReadOnlyAdapter(inputJournal:const PlatformRemoteInputJournal());
  final fields = <String,TextEditingController>{
    for (final name in ['host','port','username','expectedHostKey','privateKeyPem','socketPath','herdrPath','session','paneId'])
      name:TextEditingController(text:name == 'port' ? '22' : ''),
  };
  bool reviewed = false, busy = false;
  DeviceIdentityLease? identityLease;
  int request = 0;
  String status = '审查接入 → 会话 pane 看板 → 选择目标观察';
  RemoteDashboard? dashboard;
  String? selectedPane;
  bool live = false;
  int? sequence;
  RemoteSnapshot? snapshot;
  DateTime? capturedAt;
  Terminal? terminal;
  final terminalFocus = FocusNode();
  final draft = TextEditingController();
  bool rendering = false, previewOpen = false, acknowledgingInput = false;
  String? draftTarget;
  final drafts = <String,String>{};
  late final inputGate = RemoteInputGate((target,bytes,current) =>
    adapter.sendInput(target,bytes,stillCurrent:current),onChanged:() {
      if (mounted) setState(() {});
    });

  // Presentation only: retain the original pane objects and source order in
  // each group. Stopped snapshots cannot advertise current pending work.
  List<RemotePane> get displayPanes {
    final panes = dashboard?.panes ?? const <RemotePane>[];
    if (!busy) return panes;
    return [for (final pane in panes) if (pane.agentStatus == 'blocked') pane,
      for (final pane in panes) if (pane.agentStatus != 'blocked') pane];
  }
  int get blockedPaneCount => busy
    ? dashboard?.panes.where((pane) => pane.agentStatus == 'blocked').length ?? 0 : 0;

  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this);
    widget.visibility?.addListener(visibilityChanged);
    if (widget.visibility?.value == false) status = '标签已隐藏 · 输入关闭；显示后需主动审查恢复';
    final target = widget.pairedTarget;
    if (target != null) for (final entry in fields.entries) {
      if (target[entry.key] != null) entry.value.text = target[entry.key].toString();
    }
  }
  @override
  void didUpdateWidget(RemotePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.visibility,widget.visibility)) {
      oldWidget.visibility?.removeListener(visibilityChanged);
      widget.visibility?.addListener(visibilityChanged);
      if (widget.visibility?.value == false || oldWidget.visibility?.value == false) visibilityChanged();
    }
  }
  void visibilityChanged() {
    if (widget.visibility?.value == false) {
      stop('标签已隐藏 · 连接与输入已停止；未发送草稿保留，显示后需主动审查恢复');
    } else if (mounted) {
      setState(() { status = '标签已显示 · 旧画面仅供参考，请主动审查连接并取得新 full'; });
    }
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) stop('应用已暂停，连接已取消；请重新核验后主动连接');
  }
  void stop([String message = '已取消；不会重连或发送输入']) {
    inputGate.invalidate(); terminalFocus.unfocus();
    request++; identityLease?.cancel(); unawaited(adapter.cancel());
    widget.onStopped?.call();
    fields['privateKeyPem']!.clear();
    if (mounted) setState(() { busy = false; live = false; reviewed = false; status = message; });
  }
  @override
  void dispose() {
    widget.visibility?.removeListener(visibilityChanged);
    WidgetsBinding.instance.removeObserver(this); request++; identityLease?.cancel();
    inputGate.onChanged = null; inputGate.invalidate(); terminalFocus.dispose(); draft.dispose();
    unawaited(adapter.cancel()); terminal?.dispose();
    for (final c in fields.values) { c.clear(); c.dispose(); }
    super.dispose();
  }

  Future<void> connect() async {
    if (!reviewed || busy || widget.visibility?.value == false) return;
    final ticket = ++request;
    setState(() { busy = true; });
    try {
      widget.onConnecting?.call();
      final values = {
        'schemaVersion':1,for (final e in fields.entries) if (e.key != 'port' && e.key != 'privateKeyPem') e.key:e.value.text,
        'port':int.tryParse(fields['port']!.text),'reviewConfirmed':reviewed,
      };
      RemoteConfig config;
      if (widget.pairedTarget != null) {
        final publicKey = await widget.deviceKeys!.public(widget.keyHandle!);
        if (!mounted || ticket != request) return;
        if (publicKey != widget.devicePublicKey) throw const RemoteFailure('device_key_changed');
        identityLease = DeviceIdentityLease(widget.deviceKeys!,widget.keyHandle!,publicKey);
        config = RemoteConfig.fromDeviceJson(values,identityLease!.identity());
      } else {
        config = RemoteConfig.fromJson({...values,'privateKeyPem':pemFromSingleLineInput(fields['privateKeyPem']!.text)});
      }
      fields['privateKeyPem']!.clear();
      FocusScope.of(context).unfocus();
      inputGate.invalidate();
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
        // Parser-generated responses to remote device queries must never become
        // user input, including while an interactive mode is selected.
        rendering = true;
        try { terminal!.write(frame.ansi); } finally { rendering = false; }
        if (frame.full && adapter.inputTarget != null) {
          final target = adapter.inputTarget!;
          final key = '${target.hostFingerprint}\u0000${target.host}:${target.port}\u0000${target.username}\u0000${target.socketPath}\u0000${target.paneId}\u0000${target.terminalId}';
          if (draftTarget != key) {
            if (draftTarget != null) drafts[draftTarget!] = draft.text;
            draft.text = drafts[key] ?? ''; draftTarget = key;
          }
          inputGate.bind(target,adapter.inputCapability);
          if (adapter.pendingInput != null) inputGate.restorePending(adapter.pendingInput!);
        }
        bindTerminalOutput();
        setState(() { snapshot = RemoteSnapshot(generation,config.session,paneId,frame.ansi);
          capturedAt = DateTime.now(); sequence = frame.seq; live = true;
          status = '正在只读观察 · 输入关闭'; });
      },onProgress:(generation,phase) {
        if (!mounted || ticket != request) return;
        if (phase == 'snapshot') widget.onAuthenticated?.call();
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
      identityLease?.cancel(); widget.onStopped?.call();
      inputGate.invalidate(); terminalFocus.unfocus();
      final code = error is RemoteFailure ? error.code : 'connection_failed';
      setState(() { busy = false; live = false; reviewed = false;
        status = switch (code) {
          'device_key_unavailable' || 'device_key_changed' => '设备密钥锁定、丢失或不可用 · 已停止，不会生成替代身份或使用明文',
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

  void bindTerminalOutput() {
    final source = terminal;
    final lease = inputGate.capture();
    if (source == null) return;
    source.onOutput = (text) {
      if (!mounted || rendering || previewOpen || !identical(source,terminal) || !terminalFocus.hasFocus ||
          lease == null || lease.mode != RemoteInputMode.direct || !inputGate.current(lease)) return;
      // An IME/multiline insertion also goes through preview. Enter generated
      // by the terminal component is CR and remains an explicit key action.
      if (text.contains('\n')) { unawaited(previewInput(text,lease)); }
      else { unawaited(inputGate.submit(lease,text)); }
    };
  }

  void setInputMode(RemoteInputMode mode) {
    terminalFocus.unfocus(); FocusScope.of(context).unfocus();
    inputGate.setFocused(true); inputGate.setMode(mode); bindTerminalOutput();
    final lease = inputGate.capture();
    if (mode == RemoteInputMode.direct && lease != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && inputGate.current(lease)) terminalFocus.requestFocus();
      });
    }
  }

  Future<void> previewInput(String text, RemoteInputLease lease, {bool fromDraft = false}) async {
    if (previewOpen || inputGate.sending || !inputGate.current(lease) || text.isEmpty) return;
    if (utf8ByteLength(text) > 4096) {
      setState(() { status = '文本超过 4096 bytes · 未发送'; }); return;
    }
    setState(() { previewOpen = true; });
    final approved = await showDialog<bool>(context:context,builder:(context) => AlertDialog(
      title:const Text('预览发送文本'),
      content:SingleChildScrollView(child:Column(crossAxisAlignment:CrossAxisAlignment.start,
        mainAxisSize:MainAxisSize.min,children:[
          Text(lease.target.label),const SizedBox(height:12),SelectableText(text),
          const SizedBox(height:12),
          const Text('保留全部换行，不额外附加回车。换行可能被终端解释为执行输入。服务端接收不表示命令已执行。'),
        ])),actions:[
        TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('取消')),
        FilledButton(key:const ValueKey('remote-input-confirm'),
          onPressed:() => Navigator.pop(context,true),child:const Text('发送文本')),
      ]));
    if (!mounted) return;
    setState(() { previewOpen = false; });
    if (approved != true || !inputGate.current(lease)) return;
    final result = await inputGate.submit(lease,text);
    if (!mounted) return;
    // Unknown submitted bytes are quarantined in the local record, never put
    // back into the sendable draft. A proven rejection preserves the draft.
    if (fromDraft && draft.text == text && result.disposition != RemoteInputDisposition.rejected) draft.clear();
  }

  Future<void> pasteInput() async {
    final lease = inputGate.capture();
    if (lease == null || previewOpen || inputGate.sending) return;
    final value = await Clipboard.getData(Clipboard.kTextPlain);
    if (!mounted || !inputGate.current(lease) || value?.text == null) return;
    if (lease.mode == RemoteInputMode.draft) {
      if (utf8ByteLength(draft.text + value!.text!) <= 4096) draft.text += value.text!;
    } else { await previewInput(value!.text!,lease); }
  }

  void auxiliaryInput(String bytes) {
    final lease = inputGate.capture();
    if (lease == null || lease.mode != RemoteInputMode.direct || previewOpen || inputGate.sending) return;
    terminalFocus.requestFocus(); unawaited(inputGate.submit(lease,bytes));
  }

  Widget inputPanel() {
    final available = live && inputGate.capability != null && inputGate.fresh;
    final enabled = available && inputGate.unknown == null;
    final result = inputGate.lastResult;
    final message = inputGate.unknown != null
      ? switch (inputGate.unknown!.knownDisposition) {
        RemoteInputDisposition.accepted => '服务端已接收 · 本机发送锁未清理，输入已锁定，不会重放',
        RemoteInputDisposition.rejected => '服务端已明确拒绝 · 本机发送锁未清理，输入已锁定',
        _ => '发送结果待核实 · 输入已锁定，不会重放',
      }
      : inputGate.sending ? '正在发送 · 同一动作不会重复提交'
      : result?.disposition == RemoteInputDisposition.accepted ? '服务端已接收 · 仅确认队列受理，请查看终端反馈'
      : result?.disposition == RemoteInputDisposition.rejected ? '未发送成功 · 已明确拒绝；请主动修正后再操作'
      : inputGate.mode == RemoteInputMode.direct ? '逐键输入 · 当前焦点目标；输入法提交后才发送'
      : inputGate.mode == RemoteInputMode.draft ? '本地草稿 · 预览确认后发送，不补回车'
      : '观察模式 · 输入关闭';
    return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      const SizedBox(height:12),
      Text('当前输入目标：${inputGate.target?.label ?? '尚未取得新 full'}'),
      if (!available) const Padding(padding:EdgeInsets.symmetric(vertical:8),child:Text(
        '原厂 herdr 0.9.5 保持只读。输入需要已核验的原子 terminal ID 保护扩展；不会改用 pane 名称写入或自动接管尺寸。')),
      Semantics(liveRegion:true,child:Text(message,key:const ValueKey('remote-input-status'))),
      Wrap(spacing:8,runSpacing:8,children:[
        for (final entry in const {
          RemoteInputMode.observe:'观察',RemoteInputMode.direct:'逐键输入',RemoteInputMode.draft:'草稿编辑',
        }.entries) ChoiceChip(key:ValueKey('remote-mode-${entry.key.name}'),label:Text(entry.value),
          selected:inputGate.mode == entry.key,
          onSelected:entry.key == RemoteInputMode.observe || enabled
            ? (_) => setInputMode(entry.key) : null),
      ]),
      if (inputGate.unknown != null) ...[
        Text('待核实目标：${inputGate.unknown!.target.label}\n发送于 ${inputGate.unknown!.at.toLocal().toIso8601String()}'),
        ExpansionTile(title:const Text('查看本机保留的待核实内容'),children:[
          SelectableText(inputGate.unknown!.bytes.isEmpty
            ? '上次进程仅持久保存了目标与尝试编号，正文未保存。请从远端画面核实。' : inputGate.unknown!.text)]),
        const Text('先停止并重新连接同一目标、取得新 full，查看远端后再人工确认。确认只解除锁定，不会重发。'),
        TextButton(key:const ValueKey('remote-input-acknowledge'),
          onPressed:inputGate.canAcknowledgeUnknown && !inputGate.sending && !acknowledgingInput ? () async {
            if (acknowledgingInput) return;
            final target = inputGate.target!;
            setState(() { acknowledgingInput = true; });
            final cleared = await adapter.acknowledgeInputUnknown(target);
            if (!mounted) return;
            if (cleared && identical(inputGate.target,target)) inputGate.acknowledgeUnknown();
            setState(() { acknowledgingInput = false; });
          } : null,child:const Text('我已核实新画面，解除未知结果锁定')),
      ],
      if (inputGate.mode == RemoteInputMode.direct) ...[
        Wrap(spacing:8,runSpacing:8,children:[
          for (final key in const {'Esc':'\x1b','Tab':'\t','Ctrl+C':'\x03','Ctrl+D':'\x04',
            'Ctrl+Z':'\x1a','Ctrl+A':'\x01','Ctrl+E':'\x05','Ctrl+L':'\x0c','Ctrl+R':'\x12',
            'Ctrl+U':'\x15','Ctrl+W':'\x17','↑':'\x1b[A','↓':'\x1b[B','←':'\x1b[D','→':'\x1b[C',
            'Home':'\x1b[H','End':'\x1b[F','PgUp':'\x1b[5~','PgDn':'\x1b[6~','Enter':'\r'}.entries)
            OutlinedButton(key:ValueKey('remote-key-${key.key}'),onPressed:enabled && !previewOpen && !inputGate.sending ? () => auxiliaryInput(key.value) : null,
              child:Text(key.key)),
        ]),
        OutlinedButton.icon(key:const ValueKey('remote-input-paste'),onPressed:enabled && !previewOpen && !inputGate.sending ? pasteInput : null,
          icon:const Icon(Icons.content_paste),label:const Text('粘贴并预览')),
      ],
      if (inputGate.mode == RemoteInputMode.draft) ...[
        TextField(key:const ValueKey('remote-input-draft'),controller:draft,minLines:2,maxLines:5,
          maxLength:4096,
          enabled:enabled && !inputGate.sending && !previewOpen,autocorrect:false,enableSuggestions:false,
          enableIMEPersonalizedLearning:false,decoration:const InputDecoration(labelText:'此目标的本地草稿',
            helperText:'发送最多 4096 UTF-8 bytes；中文等字符可能占多个 byte')),
        Wrap(spacing:8,children:[
          OutlinedButton(onPressed:enabled && !inputGate.sending && !previewOpen ? pasteInput : null,child:const Text('粘贴到草稿')),
          FilledButton(key:const ValueKey('remote-input-draft-send'),
            onPressed:enabled && !inputGate.sending && !previewOpen ? () {
              final lease = inputGate.capture(); if (lease != null) unawaited(previewInput(draft.text,lease,fromDraft:true));
            } : null,child:const Text('预览并发送文本')),
        ]),
      ],
    ]);
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
      key:ValueKey('remote-$name'),controller:fields[name],enabled:!busy && widget.pairedTarget == null,
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
          Text('手机看板 · 默认观察',style:Theme.of(context).textTheme.titleLarge),
          const SizedBox(height:8),
          const Text('仅用于隔离测试主机。审查接入后查看当前命名会话，选择明确 pane 观察。支持保护扩展与持久锁时可显式输入；布局不调整共享 PTY。'),
          const SizedBox(height:12),
          Semantics(liveRegion:true,child:Text(status,key:const ValueKey('remote-status'),
            style:TextStyle(color:widget.tokens.color('textSecondary')))),
          if (busy) TextButton.icon(key:const ValueKey('remote-cancel'),onPressed:stop,
            icon:const Icon(Icons.stop_circle_outlined),label:const Text('停止并断开')),
          if (dashboard != null) ...[
            const SizedBox(height:12),
            Text('会话 ${dashboard!.session}',style:Theme.of(context).textTheme.titleMedium),
            Text('仅来自已核验 socket 的 snapshot · ${dashboard!.panes.length} 个 pane\n${busy ? '连接保持，等待选择或正在观察' : '看板已陈旧，需重新审查连接'}'),
            if (blockedPaneCount > 0) Semantics(key:const ValueKey('remote-blocked-summary'),
              liveRegion:true,excludeSemantics:true,
              label:'主机报告 $blockedPaneCount 个受阻窗格。待处理优先，同级保持原顺序。',
              child:Text('待处理优先 · $blockedPaneCount 个受阻窗格（主机报告）')),
            if (dashboard!.panes.isEmpty) const Padding(padding:EdgeInsets.symmetric(vertical:16),
              child:Text('没有 pane · 不会回退到其他会话')),
            for (final pane in displayPanes) Card(child:Padding(padding:const EdgeInsets.all(12),
              child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
                Text(pane.label ?? pane.paneId,style:Theme.of(context).textTheme.titleMedium),
                Text('${pane.agent ?? '窗格状态'} · ${busy ? pane.statusLabel : '上次${pane.statusLabel}（待确认）'}'),
                if (pane.workspace != null || pane.tab != null) Text([pane.workspace,pane.tab].whereType<String>().join(' / ')),
                Text('${pane.paneId} · ${pane.terminalId}',softWrap:true),
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
          if (widget.pairedTarget == null) ...[
          Text('3 · 内存临时凭据',style:Theme.of(context).textTheme.titleMedium),
          const SizedBox(height:12),
          input('privateKeyPem','临时 Ed25519 私钥',secret:true),
          ] else const Padding(padding:EdgeInsets.symmetric(vertical:12),child:Text('设备独立身份 · 私钥不进入表单；密钥不可用时停止')),
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
            Text('${snapshot!.session} / ${snapshot!.paneId}\n${live ? inputGate.mode == RemoteInputMode.observe ? '只读观察中' : '实时终端 · 显式输入模式' : '旧画面 · 已停止'} · seq $sequence\n更新于 ${capturedAt!.toLocal().toIso8601String()} · 固定 80×24'),
            const SizedBox(height:8),
            SizedBox(height:360,child:ClipRRect(borderRadius:BorderRadius.circular(12),
              child:TerminalView(terminal!,key:ValueKey('remote-terminal-${inputGate.epoch}'),
                focusNode:terminalFocus,theme:widget.tokens.terminalTheme,
                autoResize:false,readOnly:!live || inputGate.mode != RemoteInputMode.direct || !inputGate.canInput,
                simulateScroll:false,hardwareKeyboardOnly:inputGate.mode != RemoteInputMode.direct,
                keyboardType:TextInputType.text,
                textStyle:const TerminalStyle(fontFamily:'ProbeNerd',fontSize:14),shortcuts:const {},
                onKeyEvent:(node,event) {
                  if (!live || inputGate.mode != RemoteInputMode.direct || !inputGate.canInput || previewOpen) return KeyEventResult.handled;
                  if (event is KeyDownEvent && (HardwareKeyboard.instance.isControlPressed || HardwareKeyboard.instance.isMetaPressed) &&
                      event.logicalKey == LogicalKeyboardKey.keyV) {
                    unawaited(pasteInput()); return KeyEventResult.handled;
                  }
                  return KeyEventResult.ignored;
                }))),
          ],
          if (snapshot != null || inputGate.unknown != null) inputPanel(),
        ])))));
}
