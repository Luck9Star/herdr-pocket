import 'dart:async';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'remote_adapter.dart';
import 'remote_input.dart';
import 'remote_auxiliary.dart';
import 'remote_input_platform.dart';
import 'device_keys.dart';
import 'network_profiles.dart';
import 'network_runtime.dart';
import 'network_identity.dart';
import 'host_task_summary.dart';

String pemFromSingleLineInput(String text) {
  final normalized = text.replaceAll(r'\n','\n').trim();
  final match = RegExp(r'^-----BEGIN OPENSSH PRIVATE KEY-----\s*([A-Za-z0-9+/=\s]+)-----END OPENSSH PRIVATE KEY-----$').firstMatch(normalized);
  if (match == null) throw const RemoteFailure('invalid_private_key');
  final body = match.group(1)!.replaceAll(RegExp(r'\s'),'');
  return '-----BEGIN OPENSSH PRIVATE KEY-----\n$body\n-----END OPENSSH PRIVATE KEY-----\n';
}

class RemotePage extends StatefulWidget {
  const RemotePage({super.key,required this.tokens,this.adapter,this.pairedTarget,this.deviceKeys,this.keyHandle,this.devicePublicKey,this.onConnecting,this.onAuthenticated,this.onStopped,this.visibility,this.networkBinding,this.onViewState,this.requestedTarget,this.onOpenPane,this.summaryLease});
  final DesignTokens tokens;
  final NetworkConnectionBinding? networkBinding;
  final RemoteReadOnlyAdapter? adapter;
  final Map<String,dynamic>? pairedTarget;
  final DeviceKeys? deviceKeys;
  final String? keyHandle, devicePublicKey;
  final VoidCallback? onConnecting, onAuthenticated, onStopped;
  final ValueListenable<bool>? visibility;
  final void Function(String,String?,String?)? onViewState;
  final RemotePane? requestedTarget;
  final void Function(RemotePane)? onOpenPane;
  final HostDashboardLease? summaryLease;
  @override
  State<RemotePage> createState() => _RemotePageState();
}

class _RemotePageState extends State<RemotePage> with WidgetsBindingObserver {
  final runtime = const NativeNetworkRuntime();
  late final NetworkConnectionBinding? originalNetworkBinding;
  bool networkBindingInvalidated = false;
  NetworkNodeBinding? frozenNode;
  late final adapter = widget.networkBinding?.profile != null
    ? RemoteReadOnlyAdapter(inputJournal:const PlatformRemoteInputJournal(),connector:(host,port) async {
        final node = frozenNode;
        if (node == null || widget.networkBinding?.stillCurrent() != true) throw const RemoteFailure('network_binding_changed');
        final socket = await runtime.open(node,host,port);
        if (widget.networkBinding?.stillCurrent() != true || !identical(node,frozenNode)) {
          socket.destroy(); throw const RemoteFailure('network_binding_changed');
        }
        return socket;
      })
    : widget.adapter ?? RemoteReadOnlyAdapter(inputJournal:const PlatformRemoteInputJournal());
  final fields = <String,TextEditingController>{
    for (final name in ['host','port','username','expectedHostKey','privateKeyPem','socketPath','herdrPath','session','paneId'])
      name:TextEditingController(text:name == 'port' ? '22' : ''),
  };
  bool reviewed = false, busy = false,viewPaused = false,dashboardFresh = false;
  DeviceIdentityLease? identityLease;
  int request = 0;
  int observationEpoch = 0;
  HostDashboardAttempt? summaryAttempt;
  String status = '审查接入 → 会话 pane 看板 → 选择目标观察';
  RemoteDashboard? dashboard;
  String? selectedPane;
  RemotePane? selectedTarget;
  bool live = false;
  int? sequence;
  RemoteSnapshot? snapshot;
  DateTime? capturedAt;
  DateTime? dashboardSyncedAt;
  String? dashboardSyncSource;
  Terminal? terminal;
  final terminalFocus = FocusNode();
  final draft = TextEditingController();
  int draftRevision = 0;
  final rejectedDrafts = <({String target,String text})>[];
  bool rendering = false, previewOpen = false, acknowledgingInput = false;
  String? draftTarget;
  final drafts = <String,String>{};
  final draftOrigins = <String,RemoteInputTarget>{};
  final auxiliaryModifiers = AuxiliaryModifiers();
  late final RemoteInputGate inputGate = RemoteInputGate((target,bytes,current) =>
    adapter.sendInput(target,bytes,stillCurrent:current),onChanged:() {
      if (!inputGate.canInput || inputGate.mode != RemoteInputMode.direct || inputGate.sending) auxiliaryModifiers.reset();
      if (mounted) setState(() {});
      reportView();
    });

  void reportView() {
    widget.onViewState?.call(inputGate.unknown != null || adapter.pendingInput != null ? 'unknown' :
      viewPaused ? 'paused' : live ? 'live' : 'stale',selectedPane ?? widget.requestedTarget?.paneId,
      selectedTarget?.terminalId ?? widget.requestedTarget?.terminalId);
  }
  String targetKey(RemoteInputTarget target) => target.endpointKey;
  void draftChanged() { draftRevision++; }

  // Presentation only: retain the original pane objects and source order in
  // each group. Stopped snapshots cannot advertise current pending work.
  List<RemotePane> get displayPanes {
    final panes = dashboard?.panes ?? const <RemotePane>[];
    if (!busy || !dashboardFresh) return panes;
    return [for (final pane in panes) if (pane.agentStatus == 'blocked') pane,
      for (final pane in panes) if (pane.agentStatus != 'blocked') pane];
  }
  int get blockedPaneCount => busy && dashboardFresh
    ? dashboard?.panes.where((pane) => pane.agentStatus == 'blocked').length ?? 0 : 0;

  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this);
    widget.summaryLease?.registry.addListener(summaryChanged);
    originalNetworkBinding = widget.networkBinding;
    adapter.captureInputJournalReview = inputGate.captureJournalRefresh;
    draft.addListener(draftChanged);
    terminalFocus.addListener(terminalFocusChanged);
    widget.visibility?.addListener(visibilityChanged);
    widget.networkBinding?.changes?.addListener(networkChanged);
    if (widget.visibility?.value == false) status = '标签已隐藏 · 输入关闭；显示后需主动审查恢复';
    final target = widget.pairedTarget;
    if (target != null) for (final entry in fields.entries) {
      if (target[entry.key] != null) entry.value.text = target[entry.key].toString();
    }
  }
  void summaryChanged() { if (mounted) setState(() {}); }
  void terminalFocusChanged() {
    if (mounted) setState(() { if (!terminalFocus.hasFocus) auxiliaryModifiers.reset(); });
    // A preview owns a target-bound lease while its modal takes focus. All
    // other direct focus loss revokes the lease and any queued keystrokes.
    if (!terminalFocus.hasFocus && !previewOpen && inputGate.mode == RemoteInputMode.direct) {
      inputGate.setFocused(false); bindTerminalOutput();
    }
  }
  @override
  void didUpdateWidget(RemotePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.networkBinding,widget.networkBinding) || !identical(oldWidget.requestedTarget,widget.requestedTarget)) {
      networkBindingInvalidated = true;
      oldWidget.networkBinding?.changes?.removeListener(networkChanged);
      widget.networkBinding?.changes?.addListener(networkChanged);
      stop('网络绑定已改变 · 已停止，请关闭本页后重新审查');
    }
    if (!identical(oldWidget.visibility,widget.visibility)) {
      oldWidget.visibility?.removeListener(visibilityChanged);
      widget.visibility?.addListener(visibilityChanged);
      if (widget.visibility?.value == false || oldWidget.visibility?.value == false) visibilityChanged();
    }
  }
  void networkChanged() {
    if (widget.networkBinding?.stillCurrent() == false) {
      networkBindingInvalidated = true;
      stop('网络绑定已改变、停用或目录不可用 · 已停止，请关闭后重新审查');
    } else if (mounted) { setState(() {}); }
  }
  void visibilityChanged() {
    if (widget.visibility?.value == false) {
      widget.summaryLease?.invalidate(); summaryAttempt = null;
      inputGate.invalidate(); terminalFocus.unfocus(); if (mounted) FocusScope.of(context).unfocus();
      if (!adapter.pauseObservation()) {
        stop('标签已隐藏 · 未建立的连接已停止；返回后需主动审查');
      } else {
        if (!viewPaused) observationEpoch++;
        setState(() { viewPaused = true; live = false; dashboardFresh = false; status = '标签已隐藏 · 观察与输入暂停，SSH 可保留；返回后需主动恢复'; });
        reportView();
      }
    } else if (mounted) {
      setState(() { status = viewPaused ? '标签已显示 · 旧画面仅供参考，请主动恢复原目标并等待新 full' :
        '标签已显示 · 旧画面仅供参考，请主动审查连接并取得新 full'; });
    }
  }
  void resumeObservation() {
    if (!viewPaused || widget.visibility?.value == false || networkBindingInvalidated) return;
    summaryAttempt = widget.summaryLease?.begin();
    if (widget.networkBinding?.stillCurrent() == false || !adapter.resumeObservation()) {
      stop('原连接或网络绑定已失效 · 请关闭后重新审查'); return;
    }
    setState(() { viewPaused = false; live = false; status = '正在重新核验原目标 · 等待新 full，输入关闭'; });
    // Requested targets wait for the resumed watch's authoritative callback;
    // the board retained while hidden cannot authorize a new selection.
    reportView();
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) stop('应用已暂停，连接已取消；请重新核验后主动连接');
  }
  void stop([String message = '已取消；不会重连或发送输入']) {
    widget.summaryLease?.invalidate(); summaryAttempt = null;
    inputGate.invalidate(); terminalFocus.unfocus(); if (mounted) FocusScope.of(context).unfocus();
    request++; frozenNode = null; identityLease?.cancel(); unawaited(adapter.cancel());
    widget.onStopped?.call();
    fields['privateKeyPem']!.clear();
    if (mounted) setState(() { busy = false; live = false; reviewed = false; viewPaused = false; dashboardFresh = false; status = message; });
    reportView();
  }
  @override
  void dispose() {
    widget.summaryLease?.registry.removeListener(summaryChanged);
    widget.summaryLease?.close(); summaryAttempt = null;
    widget.visibility?.removeListener(visibilityChanged);
    widget.networkBinding?.changes?.removeListener(networkChanged);
    WidgetsBinding.instance.removeObserver(this); request++; identityLease?.cancel();
    adapter.captureInputJournalReview = null;
    inputGate.onChanged = null; inputGate.invalidate();
    terminalFocus.removeListener(terminalFocusChanged); terminalFocus.dispose(); draft.removeListener(draftChanged); draft.dispose();
    unawaited(adapter.cancel()); terminal?.dispose();
    widget.onViewState?.call(inputGate.unknown != null || adapter.pendingInput != null ? 'unknown' : 'stale',
      selectedPane ?? widget.requestedTarget?.paneId,widget.requestedTarget?.terminalId);
    for (final c in fields.values) { c.clear(); c.dispose(); }
    super.dispose();
  }

  Future<void> connect() async {
    if (networkBindingInvalidated || !identical(originalNetworkBinding,widget.networkBinding) ||
        !reviewed || busy || widget.visibility?.value == false) return;
    final ticket = ++request;
    observationEpoch = 0;
    summaryAttempt = widget.summaryLease?.begin();
    setState(() { busy = true; });
    try {
      final network = widget.networkBinding;
      if (network?.profile != null) {
        if (!network!.stillCurrent()) throw const RemoteFailure('network_binding_changed');
        frozenNode = await runtime.freeze(network.profile!,NativeNetworkIdentityStore());
        if (!mounted || ticket != request) return;
        network.requireTransport(overlayReady:true);
      } else { network?.requireTransport(); }
      widget.onConnecting?.call();
      final values = {
        'schemaVersion':1,for (final e in fields.entries) if (e.key != 'port' && e.key != 'privateKeyPem') e.key:e.value.text,
        'port':int.tryParse(fields['port']!.text),'reviewConfirmed':reviewed,
      };
      RemoteConfig config;
      if (widget.pairedTarget != null) {
        final publicKey = await widget.deviceKeys!.public(widget.keyHandle!);
        if (!mounted || ticket != request) return;
        widget.networkBinding?.requireTransport(overlayReady:frozenNode != null);
        if (publicKey != widget.devicePublicKey) throw const RemoteFailure('device_key_changed');
        identityLease = DeviceIdentityLease(widget.deviceKeys!,widget.keyHandle!,publicKey);
        config = RemoteConfig.fromDeviceJson(values,identityLease!.identity());
      } else {
        config = RemoteConfig.fromJson({...values,'privateKeyPem':pemFromSingleLineInput(fields['privateKeyPem']!.text)});
      }
      fields['privateKeyPem']!.clear();
      FocusScope.of(context).unfocus();
      inputGate.invalidate();
      setState(() { busy = true; live = false; dashboardFresh = false; dashboard = null; selectedPane = null; selectedTarget = null; sequence = null; snapshot = null; capturedAt = null; terminal?.dispose(); terminal = null; status = '正在连接并核验主机身份'; });
      await adapter.observe(config,onDashboard:(value) {
        if (!mounted || ticket != request || value.generation != adapter.generation ||
            (value.source != null && value.observationEpoch != observationEpoch) ||
            (dashboard != null && dashboard!.generation == value.generation && value.revision <= dashboard!.revision)) return;
        final requested = widget.requestedTarget;
        final canSelect = value.selectable && !viewPaused && widget.visibility?.value != false;
        if (requested != null && selectedTarget == null && canSelect && value.panes.where((p) => p.paneId == requested.paneId && p.terminalId == requested.terminalId).length != 1) {
          throw const RemoteFailure('resume_target_changed');
        }
        setState(() { dashboard = value; reviewed = false; dashboardFresh = value.freshness == DashboardFreshness.fresh && !viewPaused && widget.visibility?.value != false;
          if (value.syncedAt != null) {
            dashboardSyncedAt = value.syncedAt;
            dashboardSyncSource = '${config.username}@${config.host}:${config.port} / ${value.session}';
          }
          if (requested != null && selectedTarget == null && canSelect) selectedPane = requested.paneId;
          status = !value.selectable ? '看板正在重新核验 · 目标选择暂不可用' : requested != null ? '已核对原 pane 与 terminal · 等待新 full' : value.panes.isEmpty
            ? '会话看板为空 · 未发现 pane，不代表主机没有任务' : '会话看板已核验 · 请选择一个明确 pane 开始观察'; });
        if (!viewPaused && widget.visibility?.value != false && value.observationEpoch == observationEpoch) summaryAttempt?.publish(value);
        if (requested != null && selectedTarget == null && selectedPane == requested.paneId && canSelect) {
          adapter.selectTarget(value.generation,requested); selectedTarget = requested; reportView();
        }
      },onFrame:(generation,paneId,frame) {
        if (!mounted || ticket != request || widget.visibility?.value == false || viewPaused || frame.observationEpoch != observationEpoch ||
            dashboard?.generation != generation || selectedPane != paneId) return;
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
          final key = targetKey(target);
          if (draftTarget != key) {
            if (draftTarget != null) drafts[draftTarget!] = draft.text;
            draftTarget = key; draftOrigins.putIfAbsent(key,() => target);
            draft.text = drafts[key] ?? '';
          }
          final journalRead = frame.inputJournalRead;
          final reconciled = journalRead != null && adapter.isInputJournalReadCurrent(journalRead) &&
            inputGate.reconcileJournalRefresh(journalRead.review);
          inputGate.bind(target,adapter.inputCapability);
          if (reconciled && identical(inputGate.target,journalRead.target)) inputGate.lastResult = journalRead.review.knownResult;
          if (adapter.pendingInput != null) inputGate.restorePending(adapter.pendingInput!);
        }
        bindTerminalOutput();
        setState(() { snapshot = RemoteSnapshot(generation,config.session,paneId,frame.ansi);
          capturedAt = DateTime.now(); sequence = frame.seq; live = true;
          status = '正在只读观察 · 输入关闭'; });
        reportView();
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
      widget.summaryLease?.invalidate(); summaryAttempt = null;
      identityLease?.cancel(); widget.onStopped?.call();
      inputGate.invalidate(); terminalFocus.unfocus();
      final code = error is RemoteFailure ? error.code : 'connection_failed';
      setState(() { busy = false; live = false; reviewed = false; viewPaused = false; dashboardFresh = false;
        status = switch (code) {
          'provider_unavailable' => 'provider_unavailable · 此平台或网络的连接桥不可用，已停止；不会改走系统 TCP 或 DNS',
          'network_node_not_started' => '节点未确认以此配置与身份启动 · 请先在网络管理中刷新并明确启动，不代表入网成功',
          'network_identity_unavailable' => '本机网络身份不可用或当前无密码模式不受支持 · 已停止，请核对本机资料',
          'network_runtime_unavailable' => '节点状态或连接桥不可确认 · 已停止，请刷新状态后重新审查',
          'network_binding_changed' => '网络绑定已改变或停用 · 已停止，请关闭后重新审查',
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
          'watch_retry_exhausted' => '看板订阅连续失败 · 已停止连接；请重新审查后主动连接',
          'observe_ended' => '远端观察已结束／断线 · 已保留旧画面，请重新审查连接',
          'resume_target_changed' => '原 pane 或 terminal 已改变 · 不自动切换目标，请重新审查',
          _ => '连接或读取失败 · 已停止，请重新审查资料后主动连接',
        }; if (snapshot != null) status = '旧画面 · $status'; });
      reportView();
    } finally { if (mounted && ticket == request) fields['privateKeyPem']!.clear(); }
  }

  void selectPane(RemotePane pane) {
    final board = dashboard;
    if (!busy || viewPaused || widget.visibility?.value == false || board == null || selectedPane != null ||
        board.generation != adapter.generation ||
        !board.selectable ||
        board.panes.where((p) => p.paneId == pane.paneId && p.terminalId == pane.terminalId).length != 1) return;
    setState(() { selectedPane = pane.paneId; selectedTarget = pane; live = false; status = '目标已选择 · 等待新 full'; });
    reportView();
    try { adapter.selectTarget(board.generation,pane); }
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
    if (!live || viewPaused || widget.visibility?.value == false || !inputGate.fresh ||
        (mode != RemoteInputMode.observe && (inputGate.target == null || inputGate.capability == null || inputGate.unknown != null))) return;
    auxiliaryModifiers.reset();
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
    if (fromDraft && rejectedDrafts.length >= 8) {
      setState(() { status = '待找回的未发送草稿已达上限 · 请先处理后再发送'; }); return;
    }
    final previewEpoch = observationEpoch;
    setState(() { auxiliaryModifiers.reset(); previewOpen = true; });
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
    if (lease.mode == RemoteInputMode.direct && inputGate.current(lease)) terminalFocus.requestFocus();
    if (approved != true || observationEpoch != previewEpoch || widget.visibility?.value == false || viewPaused || !inputGate.current(lease)) return;
    final key = targetKey(lease.target);
    final taken = fromDraft && draftTarget == key && draft.text == text;
    if (taken) draft.clear(); // Quarantine submitted bytes before any asynchronous result.
    final revisionAfterClear = draftRevision;
    final result = await inputGate.submit(lease,text);
    if (!mounted) return;
    if (fromDraft && result.disposition == RemoteInputDisposition.rejected) {
      if (taken && observationEpoch == previewEpoch && inputGate.current(lease) && draftTarget == key &&
          draftRevision == revisionAfterClear && draft.text.isEmpty) {
        draft.text = text;
      } else {
        // Proven rejection can be inspected by its original target, but an old
        // completion never writes into the currently editable draft.
        rejectedDrafts.add((target:key,text:text));
        if (observationEpoch == previewEpoch && inputGate.current(lease)) setState(() {});
      }
    }
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

  bool get auxiliaryReady => live && inputGate.canInput && inputGate.mode == RemoteInputMode.direct &&
    terminalFocus.hasFocus && !previewOpen && !inputGate.sending;

  void auxiliaryInput(String name) {
    final lease = inputGate.capture();
    final allowed = auxiliaryReady && lease != null;
    final bytes = auxiliaryModifiers.take(name,applicationCursorMode:terminal?.cursorKeysMode == true,
      allowed:allowed);
    setState(() { if (allowed && bytes == null) status = '此辅助组合未定义 · 未发送；组合键已释放'; });
    if (bytes == null || lease == null) return;
    unawaited(inputGate.submit(lease,bytes));
  }

  Widget inputPanel() {
    final available = live && inputGate.capability != null && inputGate.fresh;
    final enabled = available && inputGate.unknown == null;
    final panelObservationEpoch = observationEpoch,panelInputEpoch = inputGate.epoch;
    final panelTarget = inputGate.target;
    bool panelCurrent() => observationEpoch == panelObservationEpoch && inputGate.epoch == panelInputEpoch &&
      identical(inputGate.target,panelTarget) && widget.visibility?.value != false && !viewPaused;
    final result = inputGate.lastResult;
    final reviewedUnknown = inputGate.unknown,reviewedRaw = inputGate.unknown?.pendingRaw;
    final receipt = reviewedUnknown != null ? reviewedUnknown.receipt : result?.receipt;
    final message = inputGate.unknown != null
      ? switch (inputGate.unknown!.knownDisposition) {
        RemoteInputDisposition.accepted => '服务端已接收 · 本机发送锁未清理，输入已锁定，不会重放',
        RemoteInputDisposition.rejected => '此次输入已确认未受理 · 本目标本机发送锁未清理，输入已锁定',
        _ => '发送结果待核实 · 仅本目标输入已锁定，不会重放',
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
      if (receipt != null) Text(receipt.label,key:const ValueKey('remote-input-receipt')),
      Wrap(spacing:8,runSpacing:8,children:[
        for (final entry in const {
          RemoteInputMode.observe:'观察',RemoteInputMode.direct:'逐键输入',RemoteInputMode.draft:'草稿编辑',
        }.entries) ChoiceChip(key:ValueKey('remote-mode-${entry.key.name}'),label:Text(entry.value),
          selected:inputGate.mode == entry.key,
          onSelected:entry.key == RemoteInputMode.observe || enabled
            ? (_) { if (panelCurrent()) setInputMode(entry.key); } : null),
      ]),
      if (inputGate.unknown != null) ...[
        Text('待核实目标：${inputGate.unknown!.target.label}\n发送于 ${inputGate.unknown!.at.toLocal().toIso8601String()}'),
        ExpansionTile(title:const Text('查看本机保留的待核实内容'),children:[
          SelectableText(inputGate.unknown!.bytes.isEmpty
            ? '上次进程仅持久保存了目标与尝试编号，正文未保存。请从远端画面核实。' : inputGate.unknown!.text)]),
        const Text('此记录只锁定同一远端目标，其他目标可独立输入。先停止并重新连接同一目标、取得新 full，查看远端后再人工确认。确认仅解除本条记录，不会重发。'),
        TextButton(key:const ValueKey('remote-input-acknowledge'),
          onPressed:reviewedRaw != null && inputGate.canAcknowledgeUnknown && !inputGate.sending && !acknowledgingInput ? () async {
            if (acknowledgingInput || !panelCurrent() || !identical(inputGate.unknown,reviewedUnknown)) return;
            final target = inputGate.target!;
            final ticket = observationEpoch,leaseEpoch = inputGate.epoch;
            setState(() { acknowledgingInput = true; });
            final cleared = await adapter.acknowledgeInputUnknown(target,reviewedRecord:reviewedRaw);
            if (!mounted) return;
            if (cleared && observationEpoch == ticket && inputGate.epoch == leaseEpoch && identical(inputGate.target,target)) {
              inputGate.acknowledgeUnknown(reviewed:reviewedUnknown);
            }
            setState(() { acknowledgingInput = false; });
          } : null,child:const Text('我已核实新画面，解除未知结果锁定')),
      ],
      Semantics(liveRegion:true,child:Text(auxiliaryModifiers.held
          ? '${auxiliaryModifiers.ctrl ? 'Ctrl ' : ''}${auxiliaryModifiers.alt ? 'Alt ' : ''}保持 · 选择一个辅助基础键后释放；终端输入法文字不受影响'
          : '组合键已释放 · 仅影响下一次辅助基础键',key:const ValueKey('remote-modifier-status'))),
        Wrap(spacing:8,runSpacing:8,children:[
          for (final name in const ['ctrl','alt']) FilterChip(key:ValueKey('remote-modifier-$name'),
            label:Text(name == 'ctrl' ? 'Ctrl' : 'Alt'),selected:name == 'ctrl' ? auxiliaryModifiers.ctrl : auxiliaryModifiers.alt,
            onSelected:auxiliaryReady ? (_) { if (panelCurrent()) setState(() { auxiliaryModifiers.toggle(name,allowed:auxiliaryReady); }); } : null),
          TextButton(key:const ValueKey('remote-modifier-cancel'),onPressed:auxiliaryReady && auxiliaryModifiers.held
            ? () { if (panelCurrent()) setState(auxiliaryModifiers.reset); } : null,child:const Text('取消组合键')),
        ]),
        if (auxiliaryModifiers.held) Wrap(spacing:8,runSpacing:8,children:[
          for (final name in [...'abcdefghijklmnopqrstuvwxyz'.split(''),'space'])
            OutlinedButton(key:ValueKey('remote-base-$name'),onPressed:auxiliaryReady ? () { if (panelCurrent()) auxiliaryInput(name); } : null,
              child:Text(name == 'space' ? 'Space' : name.toUpperCase())),
        ]),
      if (inputGate.mode == RemoteInputMode.direct) ...[
        Wrap(spacing:8,runSpacing:8,children:[
          for (final key in const {'Esc':'esc','Tab':'tab','Ctrl+C':'ctrl-c','Ctrl+D':'ctrl-d',
            'Ctrl+Z':'ctrl-z','Ctrl+A':'ctrl-a','Ctrl+E':'ctrl-e','Ctrl+L':'ctrl-l','Ctrl+R':'ctrl-r',
            'Ctrl+U':'ctrl-u','Ctrl+W':'ctrl-w','↑':'up','↓':'down','←':'left','→':'right',
            'Home':'home','End':'end','PgUp':'pgup','PgDn':'pgdn','Enter':'enter'}.entries)
            OutlinedButton(key:ValueKey('remote-key-${key.key}'),onPressed:auxiliaryReady ? () { if (panelCurrent()) auxiliaryInput(key.value); } : null,
              child:Text(key.key)),
        ]),
        OutlinedButton.icon(key:const ValueKey('remote-input-paste'),onPressed:enabled && !previewOpen && !inputGate.sending
          ? () { if (panelCurrent()) unawaited(pasteInput()); } : null,
          icon:const Icon(Icons.content_paste),label:const Text('粘贴并预览')),
      ],
      if (inputGate.mode == RemoteInputMode.draft) ...[
        KeyedSubtree(key:ValueKey('remote-draft-input-epoch-${inputGate.epoch}'),child:TextField(key:const ValueKey('remote-input-draft'),controller:draft,minLines:2,maxLines:5,
          maxLength:4096,
          enabled:enabled && !inputGate.sending && !previewOpen,autocorrect:false,enableSuggestions:false,
          enableIMEPersonalizedLearning:false,decoration:const InputDecoration(labelText:'此目标的本地草稿',
            helperText:'发送最多 4096 UTF-8 bytes；中文等字符可能占多个 byte'))),
        Wrap(spacing:8,children:[
          OutlinedButton(onPressed:enabled && !inputGate.sending && !previewOpen ? () { if (panelCurrent()) unawaited(pasteInput()); } : null,child:const Text('粘贴到草稿')),
          FilledButton(key:const ValueKey('remote-input-draft-send'),
            onPressed:enabled && !inputGate.sending && !previewOpen ? () {
              if (!panelCurrent()) return;
              final lease = inputGate.capture(); if (lease != null) unawaited(previewInput(draft.text,lease,fromDraft:true));
            } : null,child:const Text('预览并发送文本')),
        ]),
      ],
      for (var i = 0; i < rejectedDrafts.length; i++)
        if (rejectedDrafts[i].target == draftTarget) ExpansionTile(key:ValueKey('remote-rejected-draft-$i'),
          title:const Text('旧阶段明确未发送的草稿 · 可查看并手动复制'),
          children:[SelectableText(rejectedDrafts[i].text),TextButton(onPressed:() {
            if (panelCurrent() && i < rejectedDrafts.length) setState(() { rejectedDrafts.removeAt(i); });
          },child:const Text('移除此找回记录'))]),
    ]);
  }

  String? unsentText(String key) => draftTarget == key ? draft.text : drafts[key];
  bool sameUnsent(String key,String text,int revision) => mounted && draftRevision == revision && unsentText(key) == text;
  Future<void> clearUnsent(String key,String text,int revision,RemoteInputTarget origin) async {
    if (!sameUnsent(key,text,revision)) return;
    final confirmed = await showDialog<bool>(context:context,builder:(context) => AlertDialog(
      title:const Text('清除此原目标的未发送草稿？'),
      content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text(origin.label),const SizedBox(height:12),SelectableText(text),
        const SizedBox(height:12),const Text('只清除此处显示的本地未发送草稿，不清除未知发送记录，不会向任何终端发送。'),
      ])),actions:[TextButton(onPressed:() => Navigator.pop(context,false),child:const Text('保留草稿')),
        FilledButton(key:const ValueKey('remote-unsent-clear-confirm'),onPressed:() => Navigator.pop(context,true),child:const Text('明确清除此草稿'))]));
    if (confirmed != true || !sameUnsent(key,text,revision)) return;
    setState(() {
      drafts.remove(key);
      if (draftTarget == key) draft.clear();
      draftRevision++; // Consumes this clear review even for an archived target.
    });
  }
  Widget unsentDraftPanel() {
    final retained = <String,String>{...drafts,if (draftTarget != null) draftTarget!:draft.text};
    final entries = retained.entries.where((entry) => entry.value.isNotEmpty && draftOrigins.containsKey(entry.key) &&
      (entry.key != draftTarget || inputGate.mode != RemoteInputMode.draft)).toList();
    if (entries.isEmpty) return const SizedBox.shrink();
    return Column(key:const ValueKey('remote-unsent-shelf'),crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      const SizedBox(height:16),Text('找回未发送草稿 · 只读',style:Theme.of(context).textTheme.titleMedium),
      const Text('来源：本页按原目标保留的未发送编辑内容。仅在本页内存保留；复制不授予发送权限，不能自动转交给新目标。'),
      for (var index = 0; index < entries.length; index++) Builder(builder:(context) {
        final entry = entries[index],origin = draftOrigins[entries[index].key]!,revision = draftRevision;
        return Card(child:Padding(padding:const EdgeInsets.all(12),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
          Text('原目标：${origin.label}',key:ValueKey('remote-unsent-origin-$index')),
          Text('原网络：${origin.route == 'system' ? '系统路由' : origin.route}',softWrap:true),
          SelectableText('原主机指纹：${origin.hostFingerprint}'),
          SelectableText(entry.value,key:ValueKey('remote-unsent-text-$index')),
          Wrap(spacing:8,children:[
            TextButton(key:ValueKey('remote-unsent-copy-$index'),onPressed:() async {
              if (!sameUnsent(entry.key,entry.value,revision)) return;
              try { await Clipboard.setData(ClipboardData(text:entry.value)); }
              catch (_) {
                if (sameUnsent(entry.key,entry.value,revision)) ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content:Text('系统复制未确认 · 原草稿仍保留，可长按文本复制。')));
              }
            },child:const Text('复制原草稿')),
            TextButton(key:ValueKey('remote-unsent-clear-$index'),onPressed:() => clearUnsent(entry.key,entry.value,revision,origin),child:const Text('清除此草稿…')),
          ]),
        ])));
      }),
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
  Widget build(BuildContext context) {
    final terminalObservationEpoch = observationEpoch,terminalInputEpoch = inputGate.epoch;
    return PopScope(
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
          if (widget.networkBinding != null) Text('冻结网络：${widget.networkBinding!.label}',key:const ValueKey('remote-network-binding')),
          Semantics(liveRegion:true,child:Text(status,key:const ValueKey('remote-status'),
            style:TextStyle(color:widget.tokens.color('textSecondary')))),
          Text(dashboardSyncedAt == null ? '会话看板：尚无已确认的同步时间' :
            '上次已核验会话看板：$dashboardSyncSource\n同步于 ${dashboardSyncedAt!.toLocal().toIso8601String()} · 此时间不代表终端画面已更新',
            key:const ValueKey('remote-dashboard-sync')),
          if (widget.summaryLease != null) Builder(builder:(context) {
            final summary = widget.summaryLease!.registry.forHost(widget.summaryLease!.hostId);
            return Text('当前主机摘要 · ${summary?.label ?? '任务状态未知 · 尚无有效会话快照'}${summary == null ? '' : '\n${summary.detail}'}',
              key:const ValueKey('remote-host-task-summary'));
          }),
          if (viewPaused && widget.visibility?.value != false) FilledButton(key:const ValueKey('remote-resume'),
            onPressed:resumeObservation,child:const Text('恢复原目标观察')),
          if (busy) TextButton.icon(key:const ValueKey('remote-cancel'),onPressed:stop,
            icon:const Icon(Icons.stop_circle_outlined),label:const Text('停止并断开')),
          if (dashboard != null) ...[
            const SizedBox(height:12),
            Text('会话 ${dashboard!.session}',style:Theme.of(context).textTheme.titleMedium),
            Text('仅来自已核验 socket 的 snapshot · ${dashboard!.panes.length} 个 pane\n${busy && dashboardFresh ? '持续更新已核验' : dashboard!.freshness == DashboardFreshness.unavailable && busy ? '持续更新不可用 · 仅为单次快照' : dashboard!.freshness == DashboardFreshness.refreshing && busy ? '正在重新核验' : '看板已陈旧，等待重新核验'}'),
            if (blockedPaneCount > 0) Semantics(key:const ValueKey('remote-blocked-summary'),
              liveRegion:true,excludeSemantics:true,
              label:'主机报告 $blockedPaneCount 个受阻窗格。待处理优先，同级保持原顺序。',
              child:Text('待处理优先 · $blockedPaneCount 个受阻窗格（主机报告）')),
            if (dashboard!.panes.isEmpty) const Padding(padding:EdgeInsets.symmetric(vertical:16),
              child:Text('没有 pane · 不会回退到其他会话')),
            for (final pane in displayPanes) Card(child:Padding(padding:const EdgeInsets.all(12),
              child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
                Text(pane.label ?? pane.paneId,style:Theme.of(context).textTheme.titleMedium),
                Text('${pane.agent ?? '窗格状态'} · ${busy && dashboardFresh ? pane.statusLabel : '上次${pane.statusLabel}（待确认）'}'),
                if (pane.workspace != null || pane.tab != null) Text([pane.workspace,pane.tab].whereType<String>().join(' / ')),
                Text('${pane.paneId} · ${pane.terminalId}',softWrap:true),
                const SizedBox(height:8),
                FilledButton(key:ValueKey('remote-pane-${pane.paneId}'),
                  onPressed:busy && !viewPaused && selectedPane == null &&
                    dashboard!.selectable ? () => selectPane(pane) : null,
                  child:Text(selectedPane == pane.paneId ? '已选目标 · 只读' : '选择此 pane 观察')),
                if (widget.onOpenPane != null) TextButton(key:ValueKey('remote-pane-new-tab-${pane.paneId}'),
                  onPressed:busy && dashboardFresh && !viewPaused && widget.visibility?.value != false ? () {
                    final current = dashboard;
                    if (current != null && current.generation == adapter.generation && current.freshness == DashboardFreshness.fresh &&
                        current.panes.where((p) => p.paneId == pane.paneId && p.terminalId == pane.terminalId).length == 1) widget.onOpenPane!(pane);
                  } : null,
                  child:const Text('在新标签打开此目标')),
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
            value:reviewed,onChanged:busy || networkBindingInvalidated ? null : (value) => setState(() { reviewed = value ?? false; }),
            title:const Text('我已通过可信渠道核验主机公钥、账号与目标资料'),
            subtitle:const Text('输入或保存资料不等于信任；任何编辑都会清除此确认。')),
          const SizedBox(height:8),
          if (networkBindingInvalidated) const Text('网络绑定已改变 · 请关闭本页并重新打开，审查后才能连接。',key:ValueKey('remote-network-invalidated')),
          FilledButton.icon(key:const ValueKey('remote-connect'),onPressed:reviewed && !busy && !networkBindingInvalidated ? connect : null,
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
                textStyle:TerminalStyle(fontFamily:'ProbeNerd',fontSize:(widget.networkBinding?.terminalFontSize ?? 14).toDouble()),shortcuts:const {},
                onKeyEvent:(node,event) {
                  if (observationEpoch != terminalObservationEpoch || inputGate.epoch != terminalInputEpoch || viewPaused ||
                      widget.visibility?.value == false || !live || inputGate.mode != RemoteInputMode.direct || !inputGate.canInput || previewOpen) return KeyEventResult.handled;
                  if (event is KeyDownEvent && (HardwareKeyboard.instance.isControlPressed || HardwareKeyboard.instance.isMetaPressed) &&
                      event.logicalKey == LogicalKeyboardKey.keyV) {
                    unawaited(pasteInput()); return KeyEventResult.handled;
                  }
                  return KeyEventResult.ignored;
                }))),
          ],
          if (snapshot != null || inputGate.unknown != null) inputPanel(),
          unsentDraftPanel(),
        ])))));
  }
}
