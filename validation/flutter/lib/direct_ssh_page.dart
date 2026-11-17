import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb;
import 'package:flutter/services.dart' show Clipboard;
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'macos_secure_credential_field.dart';

String formatDirectSshTarget(String username, String host, int port) {
  final displayHost = host.contains(':') && !(host.startsWith('[') && host.endsWith(']')) ? '[$host]' : host;
  return '$username@$displayHost:$port';
}

enum DirectSshConnectPhase { idle, keyParse, socket, handshake, hostKeyVerified, passwordRequest, shellRequest, connected }
enum DirectSshConnectFailure { keyParse, socket, handshake, handshakeTimeout, authRejected, authAborted, authTimeout, timeout, hostKeyChanged, transport, cancelled, other }

/// Standalone SSH shell. Host key verification precedes every authentication.
class DirectSshPage extends StatefulWidget {
  const DirectSshPage({super.key, required this.tokens});
  final DesignTokens tokens;
  @override
  State<DirectSshPage> createState() => _DirectSshPageState();
}

class _DirectSshPageState extends State<DirectSshPage> with WidgetsBindingObserver {
  final host = TextEditingController(), port = TextEditingController(text: '22'), user = TextEditingController();
  final secret = TextEditingController(), passphrase = TextEditingController();
  final targetScroll = ScrollController();
  Terminal? terminal;
  SSHSocket? socket;
  SSHClient? client;
  SSHSession? shell;
  StreamSubscription<String>? stdout, stderr;
  int epoch = 0;
  int pasteRevision = 0;
  bool pastingKey = false;
  String? pasteStatus;
  String? fingerprint, algorithm, checkedTarget;
  String? pendingTarget, activeTarget;
  bool hostKeyReviewRequired = false;
  ({String oldAlgorithm, String oldFingerprint, String newAlgorithm, String newFingerprint, String target})? hostKeyChange;
  String status = '填写连接信息后先探测主机密钥。';
  bool busy = false, connected = false, keyAuth = false, foreground = true;
  DirectSshConnectPhase connectPhase = DirectSshConnectPhase.idle;
  DirectSshConnectFailure? connectFailure;
  bool connectHostKeyMatched = false, connectCredentialCaptured = false, connectPasswordRequested = false;
  Map<String, Object?> get connectionDiagnostic => {
    'phase': connectPhase.name, 'failureCode': connectFailure?.name,
    'hostKeyMatched': connectHostKeyMatched, 'credentialCaptured': connectCredentialCaptured,
    'passwordRequested': connectPasswordRequested,
  };
  String get target => '${user.text.trim()}@${host.text.trim()}:${port.text.trim()}';
  bool get valid => host.text.trim().isNotEmpty && user.text.trim().isNotEmpty &&
      (int.tryParse(port.text.trim()) ?? 0) > 0 && (int.tryParse(port.text.trim()) ?? 65536) <= 65535;

  bool get canConnect => valid && !busy && !hostKeyReviewRequired && fingerprint != null && checkedTarget == target && secret.text.isNotEmpty;
  void cancelKeyPaste() { pasteRevision++; pastingKey = false; pasteStatus = null; }
  void credentialsChanged() { cancelKeyPaste(); if (mounted) setState(() {}); }

  Future<void> pastePrivateKey() async {
    if (!keyAuth || busy || connected || pastingKey || !foreground) return;
    final revision = ++pasteRevision, generation = epoch;
    bool current() => mounted && revision == pasteRevision && generation == epoch &&
      keyAuth && !busy && !connected && foreground && (ModalRoute.of(context)?.isCurrent ?? true);
    setState(() { pastingKey = true; pasteStatus = null; });
    String? value;
    try { value = (await Clipboard.getData(Clipboard.kTextPlain))?.text; }
    catch (_) {
      if (current()) setState(() { pastingKey = false; pasteStatus = '无法读取剪贴板，请重试或手动输入私钥。'; });
      return;
    }
    if (!current()) return;
    if (value == null || value.trim().isEmpty) {
      setState(() { pastingKey = false; pasteStatus = '剪贴板中没有可粘贴的文本。'; });
      return;
    }
    secret.value = TextEditingValue(text: value, selection: TextSelection.collapsed(offset: value.length));
    setState(() { pastingKey = false; pasteStatus = '私钥已粘贴，仅本次使用。'; });
  }

  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this);
    for (final field in [host, port, user]) { field.addListener(changed); }
    secret.addListener(credentialsChanged); passphrase.addListener(credentialsChanged);
  }
  Terminal createTerminal(int generation) {
    final value = Terminal(maxLines: 2000);
    value.onOutput = (data) {
      final current = shell;
      if (generation == epoch && identical(value, terminal) && foreground && connected && current != null) current.write(Uint8List.fromList(utf8.encode(data)));
    };
    value.onResize = (cols, rows, px, py) {
      if (generation == epoch && identical(value, terminal) && foreground && connected) shell?.resizeTerminal(cols, rows, px, py);
    };
    return value;
  }
  void retireTerminal() {
    final current = terminal; terminal = null;
    if (current == null) return;
    current.onOutput = null; current.onResize = null; current.dispose();
  }
  void changed() {
    cancelKeyPaste();
    if (busy && pendingTarget != target) stop(message: '连接目标已更改；本次操作已取消。', notify: false);
    if (checkedTarget != target) { fingerprint = null; algorithm = null; checkedTarget = null; hostKeyReviewRequired = false; hostKeyChange = null; secret.clear(); passphrase.clear(); }
    if (mounted) setState(() {});
  }
  void stop({String? message, bool notify = true}) {
    cancelKeyPaste();
    if (busy && connectPhase != DirectSshConnectPhase.idle && connectFailure == null) connectFailure = DirectSshConnectFailure.cancelled;
    epoch++; connected = false; busy = false; pendingTarget = null; activeTarget = null;
    if (targetScroll.hasClients) targetScroll.jumpTo(0);
    retireTerminal();
    secret.clear(); passphrase.clear();
    unawaited(stdout?.cancel()); unawaited(stderr?.cancel()); stdout = null; stderr = null;
    shell?.close(); shell = null; client?.close(); client = null; socket?.destroy(); socket = null;
    if (message != null) status = message;
    if (notify && mounted) setState(() {});
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    if (!foreground) {
      cancelKeyPaste();
      if (connected || busy) stop(message: '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。');
      else if (mounted) setState(() {});
    }
  }
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (pastingKey && !(ModalRoute.of(context)?.isCurrent ?? true)) cancelKeyPaste();
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    secret.removeListener(credentialsChanged); passphrase.removeListener(credentialsChanged);
    stop(notify: false);
    targetScroll.dispose();
    for (final field in [host, port, user, secret, passphrase]) { field.dispose(); }
    super.dispose();
  }
  Future<void> probe() async {
    if (!valid || busy || !foreground) return;
    stop(); connectPhase = DirectSshConnectPhase.idle; connectFailure = null;
    connectHostKeyMatched = false; connectCredentialCaptured = false; connectPasswordRequested = false;
    final generation = ++epoch; final originalTarget = target;
    final originalHost = host.text.trim(), originalPort = int.parse(port.text.trim()), originalUser = user.text.trim();
    pendingTarget = originalTarget;
    setState(() { busy = true; status = '正在探测主机密钥，尚未发送认证信息。'; if (!hostKeyReviewRequired) fingerprint = null; });
    SSHSocket? localSocket; SSHClient? localClient;
    try {
      localSocket = await SSHSocket.connect(originalHost, originalPort, timeout: const Duration(seconds: 8));
      if (generation != epoch) { localSocket.destroy(); return; }
      socket = localSocket;
      final found = Completer<(String, String)>();
      localClient = SSHClient(localSocket, username: originalUser, keepAliveInterval: null,
        handshakeTimeout: const Duration(seconds: 8), authTimeout: const Duration(seconds: 8),
        onVerifyHostKey: (type, bytes) {
          if (generation == epoch && !found.isCompleted) found.complete((type, utf8.decode(bytes)));
          return false; // Probe never authorizes authentication.
        });
      client = localClient;
      unawaited(localClient.done.then<void>((_) {}, onError: (Object _, StackTrace __) {}));
      unawaited(localClient.authenticated.then<void>((_) {}, onError: (Object error, StackTrace stack) {
        if (!found.isCompleted) found.completeError(error, stack);
      }));
      final result = await found.future.timeout(const Duration(seconds: 10));
      if (generation != epoch || originalTarget != target) return;
      localClient.close(); localSocket.destroy(); client = null; socket = null;
      if (!mounted) return;
      final approved = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
        title: const Text('核对主机密钥'),
        content: SelectableText('目标 $originalTarget\n算法 ${result.$1}\n${result.$2}\n\n请通过可信的独立渠道核对完整指纹。确认后仅对本次页面有效。'),
        actions: [TextButton(key: const ValueKey('direct-trust-cancel'), onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(key: const ValueKey('direct-trust-key'), onPressed: () => Navigator.pop(context, true), child: const Text('已核对并确认'))]));
      if (generation != epoch || originalTarget != target || !mounted) return;
      setState(() { busy = false; pendingTarget = null; if (approved == true) { algorithm = result.$1; fingerprint = result.$2; checkedTarget = originalTarget; hostKeyReviewRequired = false; hostKeyChange = null; status = '已确认本次主机密钥；连接时将重新核对。'; } else { status = '未确认主机密钥，未发送认证。'; } });
    } catch (_) {
      if (generation == epoch && mounted) { stop(message: '探测失败或超时；未发送认证，请检查目标后重试。'); }
    } finally { if (generation != epoch) { localClient?.close(); localSocket?.destroy(); } }
  }
  Future<void> connect() async {
    if (!valid || busy || !foreground || hostKeyReviewRequired || fingerprint == null || checkedTarget != target || secret.text.isEmpty) return;
    cancelKeyPaste();
    final generation = ++epoch, expected = fingerprint!, expectedAlgorithm = algorithm!;
    final originalTarget = target;
    final originalHost = host.text.trim(), originalPort = int.parse(port.text.trim()), originalUser = user.text.trim();
    final displayTarget = formatDirectSshTarget(originalUser, originalHost, originalPort);
    pendingTarget = originalTarget; activeTarget = null;
    final password = keyAuth ? null : secret.text;
    final keyText = keyAuth ? secret.text : null, phrase = passphrase.text;
    connectPhase = keyText == null ? DirectSshConnectPhase.socket : DirectSshConnectPhase.keyParse; connectFailure = null;
    connectHostKeyMatched = false; connectPasswordRequested = false;
    connectCredentialCaptured = (password ?? keyText)?.isNotEmpty ?? false;
    secret.clear(); passphrase.clear();
    retireTerminal(); final sessionTerminal = createTerminal(generation); terminal = sessionTerminal;
    setState(() { busy = true; status = '正在重新核对主机密钥并连接…'; });
    var keyMismatch = false;
    String? presentedAlgorithm, presentedFingerprint;
    var parsingKey = keyText != null;
    try {
      final identities = keyText == null ? null : SSHKeyPair.fromPem(keyText, phrase.isEmpty ? null : phrase);
      parsingKey = false;
      connectPhase = DirectSshConnectPhase.socket;
      final localSocket = await SSHSocket.connect(originalHost, originalPort, timeout: const Duration(seconds: 8));
      if (generation != epoch) { localSocket.destroy(); return; }
      socket = localSocket; bool verified = false;
      connectPhase = DirectSshConnectPhase.handshake;
      final localClient = SSHClient(localSocket, username: originalUser, identities: identities,
        onPasswordRequest: password == null ? null : () {
          if (!verified || generation != epoch) return null;
          connectPasswordRequested = true; connectPhase = DirectSshConnectPhase.passwordRequest;
          return password;
        },
        onVerifyHostKey: (type, bytes) {
          verified = generation == epoch && type == expectedAlgorithm && utf8.decode(bytes) == expected;
          if (generation == epoch) {
            connectHostKeyMatched = verified;
            if (verified) connectPhase = DirectSshConnectPhase.hostKeyVerified;
          }
          keyMismatch = generation == epoch && !verified;
          if (keyMismatch) { presentedAlgorithm = type; presentedFingerprint = utf8.decode(bytes); }
          return verified;
        },
        keepAliveInterval: null, handshakeTimeout: const Duration(seconds: 8), authTimeout: const Duration(seconds: 8));
      client = localClient;
      unawaited(localClient.done.then<void>((_) {}, onError: (Object _, StackTrace __) {}));
      await localClient.authenticated.timeout(const Duration(seconds: 12));
      if (generation != epoch || !verified) return;
      connectPhase = DirectSshConnectPhase.shellRequest;
      final pendingShell = localClient.shell(pty: SSHPtyConfig(width: sessionTerminal.viewWidth, height: sessionTerminal.viewHeight));
      unawaited(pendingShell.then<void>((value) { if (generation != epoch) value.close(); }, onError: (Object _, StackTrace __) {}));
      final localShell = await pendingShell.timeout(const Duration(seconds: 12));
      if (generation != epoch) { localShell.close(); return; }
      connectPhase = DirectSshConnectPhase.connected;
      shell = localShell;
      stdout = localShell.stdout.cast<List<int>>().transform(const Utf8Decoder(allowMalformed: true)).listen((text) { if (generation == epoch && identical(sessionTerminal, terminal)) sessionTerminal.write(text); }, onError: (_) { if (generation == epoch) stop(message: '终端输出错误，连接已关闭。'); });
      stderr = localShell.stderr.cast<List<int>>().transform(const Utf8Decoder(allowMalformed: true)).listen((text) { if (generation == epoch && identical(sessionTerminal, terminal)) sessionTerminal.write(text); }, onError: (_) { if (generation == epoch) stop(message: '终端输出错误，连接已关闭。'); });
      unawaited(localShell.done.then((_) { if (generation == epoch) stop(message: '远端 shell 已结束（退出码 ${localShell.exitCode ?? '未知'}）。'); }, onError: (Object _, StackTrace __) { if (generation == epoch) stop(message: '连接中断，输入已停止。'); }));
      setState(() { busy = false; pendingTarget = null; activeTarget = displayTarget; connected = true; status = '已连接 · 输入直接发送到远端 shell'; });
    } catch (error) {
      if (generation == epoch) {
        connectFailure = parsingKey ? DirectSshConnectFailure.keyParse
          : keyMismatch ? DirectSshConnectFailure.hostKeyChanged
          : error is TimeoutException ? DirectSshConnectFailure.timeout
          : error is SSHHandshakeError ? (error.message == 'Handshake timed out'
              ? DirectSshConnectFailure.handshakeTimeout : DirectSshConnectFailure.handshake)
          : error is SSHAuthFailError ? DirectSshConnectFailure.authRejected
          : error is SSHAuthAbortError ? (error.message == 'Authentication timed out'
              ? DirectSshConnectFailure.authTimeout : DirectSshConnectFailure.authAborted)
          : connectPhase == DirectSshConnectPhase.socket ? DirectSshConnectFailure.socket
          : error is SSHError ? DirectSshConnectFailure.transport : DirectSshConnectFailure.other;
        if (keyMismatch && presentedFingerprint != null) {
          showHostKeyChange(expectedAlgorithm, expected, presentedAlgorithm!, presentedFingerprint!, originalTarget);
        } else {
          stop(message: parsingKey ? '私钥无法解析或解密；请检查完整 PEM 和私钥口令。尚未连接远端。' : keyMismatch ? '主机密钥不符，已阻止认证；请重新核对。' : error is SSHAuthFailError ? '认证失败，请检查凭据。' : '连接失败或超时，请检查网络、密钥与目标。');
        }
      }
    }
  }
  void showHostKeyChange(String oldAlgorithm, String oldFingerprint, String newAlgorithm, String newFingerprint, String originalTarget) {
    stop(notify: false);
    hostKeyReviewRequired = true;
    hostKeyChange = (oldAlgorithm: oldAlgorithm, oldFingerprint: oldFingerprint, newAlgorithm: newAlgorithm, newFingerprint: newFingerprint, target: originalTarget);
    status = '主机指纹发生变化，已阻止连接与输入；未发送认证。';
    if (mounted) setState(() {});
  }
  void reviewHostKeyChange() {
    setState(() { hostKeyChange = null; status = '重新探测并核对本目标的主机指纹；旧信任在重新批准前保留。'; });
    unawaited(probe());
  }
  void cancelHostKeyChange() {
    setState(() { hostKeyChange = null; status = '已保留旧信任；凭据与认证入口已锁定，重新探测并独立核验后才可连接。'; });
  }
  Widget hostKeyChangeView() {
    final change = hostKeyChange!, theme = Theme.of(context), tokens = widget.tokens;
    final brand = tokens.color('brand'), dangerText = tokens.color('dangerText');
    return ListView(key: const ValueKey('direct-host-key-change'), padding: const EdgeInsets.all(16), children: [
      Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('主机指纹发生变化', style: theme.textTheme.titleLarge?.copyWith(fontSize: 20, fontWeight: FontWeight.bold, color: tokens.color('textPrimary'))),
          const SizedBox(height: 16),
          Container(padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: tokens.color('dangerSoft'), borderRadius: BorderRadius.circular(12), border: Border.all(color: tokens.color('dangerBorder'))),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('已阻止连接与输入', style: TextStyle(color: dangerText, fontWeight: FontWeight.bold, fontSize: 14)),
              const SizedBox(height: 4),
              Text('实际 SSH host key 与已保存身份不同。不会自动接受新指纹，也不会继续认证或补发输入。', style: TextStyle(color: dangerText, fontSize: 13, height: 1.5)),
            ])),
          const SizedBox(height: 20),
          Container(padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: tokens.color('card'), borderRadius: BorderRadius.circular(16), border: Border.all(color: tokens.color('borderStrong'))),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('通过独立可信渠道核验', style: theme.textTheme.titleSmall?.copyWith(fontSize: 15, fontWeight: FontWeight.w600, color: tokens.color('textPrimary'))),
              const SizedBox(height: 12),
              SelectableText('旧：${change.oldAlgorithm}\n${change.oldFingerprint}', key: const ValueKey('direct-host-key-old'), style: TextStyle(fontSize: 13, height: 1.6, color: tokens.color('textPrimary'))),
              const SizedBox(height: 10),
              SelectableText('新：${change.newAlgorithm}\n${change.newFingerprint}', key: const ValueKey('direct-host-key-new'), style: TextStyle(fontSize: 13, height: 1.6, color: tokens.color('textPrimary'))),
              const SizedBox(height: 10),
              SelectableText('目标：${change.target}', style: TextStyle(fontSize: 13, height: 1.6, color: tokens.color('textPrimary'))),
              const SizedBox(height: 4),
              Text('联系主机操作者确认变更原因。', style: TextStyle(fontSize: 13, height: 1.5, color: tokens.color('textSecondary'))),
            ])),
          const SizedBox(height: 20),
          FilledButton(key: const ValueKey('direct-host-key-review'), style: FilledButton.styleFrom(backgroundColor: brand, foregroundColor: tokens.color('textInverse')), onPressed: reviewHostKeyChange, child: const Text('重新核对主机指纹')),
          const SizedBox(height: 8),
          OutlinedButton(key: const ValueKey('direct-host-key-cancel'), style: OutlinedButton.styleFrom(backgroundColor: tokens.color('card'), foregroundColor: tokens.color('textPrimary'), side: BorderSide(color: tokens.color('borderStrong'))), onPressed: cancelHostKeyChange, child: const Text('取消连接，保留旧信任')),
          const SizedBox(height: 12),
          Text('本页没有“忽略变化继续”出口。', style: TextStyle(fontSize: 12, color: tokens.color('textSecondary'))),
        ]))),
    ]);
  }
  Widget terminalKeys(Terminal current) => SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
    for (final item in {'Esc':'\u001b', 'Tab':'\t'}.entries)
      TextButton(onPressed: () => current.textInput(item.value), child: Text(item.key)),
    for (final item in {'↑':TerminalKey.arrowUp, '↓':TerminalKey.arrowDown, '←':TerminalKey.arrowLeft, '→':TerminalKey.arrowRight}.entries)
      TextButton(onPressed: () => current.keyInput(item.value), child: Text(item.key)),
    for (final item in {'Ctrl-C':'\u0003', 'Ctrl-D':'\u0004', 'Enter':'\r'}.entries)
      TextButton(onPressed: () => current.textInput(item.value), child: Text(item.key)),
  ]));
  @override
  Widget build(BuildContext context) => PopScope<void>(
    canPop: hostKeyChange == null,
    child: Scaffold(
      appBar: AppBar(title: const Text('普通 SSH'),
      automaticallyImplyLeading: hostKeyChange == null,
      leading: hostKeyChange == null && (ModalRoute.of(context)?.impliesAppBarDismissal ?? false)
        ? MergeSemantics(child: Semantics(identifier: 'direct-back', label: '返回主机列表', child: const BackButton())) : null,
      actions: [if (busy || connected) TextButton(onPressed: () => stop(message: '已断开；未重放输入。'), child: const Text('断开'))]),
    body: SafeArea(child: hostKeyChange != null ? hostKeyChangeView() : connected ? LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(primary: false, child: SizedBox(
        // Keyboard transitions can leave less room than the status and keys.
        // Keep a usable terminal and let the connected workspace scroll.
        height: constraints.maxHeight < 240 ? 240.0 : constraints.maxHeight,
        child: Column(children: [
      Padding(padding: const EdgeInsets.all(8), child: Text(status)),
      if (activeTarget != null) Padding(padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
        child: LayoutBuilder(builder: (context, constraints) {
          final painter = TextPainter(text: TextSpan(text: activeTarget!, style: DefaultTextStyle.of(context).style),
            textDirection: Directionality.of(context), textScaler: MediaQuery.textScalerOf(context), maxLines: 1)..layout();
          final scrollable = painter.width > constraints.maxWidth;
          painter.dispose();
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (scrollable) const Text('连接目标 · 左右滑动查看'),
            Scrollbar(controller: targetScroll, thumbVisibility: scrollable,
              child: SingleChildScrollView(key: const ValueKey('direct-target-scroll'), controller: targetScroll,
                scrollDirection: Axis.horizontal, padding: EdgeInsets.only(bottom: scrollable ? 8 : 0),
                child: Text(activeTarget!, key: const ValueKey('direct-active-target'), maxLines: 1, softWrap: false))),
          ]);
        })),
      Expanded(child: TerminalView(terminal!, theme: widget.tokens.terminalTheme, autoResize: true,
        textStyle: const TerminalStyle(fontFamily: 'ProbeNerd', fontSize: 14))),
      terminalKeys(terminal!),
    ])))) : ListView(key: const ValueKey('direct-form'), padding: const EdgeInsets.all(16), children: [
      Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: widget.tokens.theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(12)),
            child: Semantics(liveRegion: true, child: Text(status, key: const ValueKey('direct-status'))),
          ),
          const SizedBox(height: 20),
          Semantics(container: true, explicitChildNodes: true, label: '地址', child: TextField(key: const ValueKey('direct-host'), controller: host, enabled: !busy,
            decoration: const InputDecoration(label: ExcludeSemantics(child: Text('地址'))))),
          const SizedBox(height: 16),
          Semantics(container: true, explicitChildNodes: true, label: '端口', child: TextField(key: const ValueKey('direct-port'), controller: port, enabled: !busy,
            keyboardType: TextInputType.number, decoration: const InputDecoration(label: ExcludeSemantics(child: Text('端口'))))),
          const SizedBox(height: 16),
          Semantics(container: true, explicitChildNodes: true, label: '用户名', child: TextField(key: const ValueKey('direct-user'), controller: user, enabled: !busy,
            decoration: const InputDecoration(label: ExcludeSemantics(child: Text('用户名'))))),
          const SizedBox(height: 16),
          OutlinedButton(key: const ValueKey('direct-probe'), onPressed: valid && !busy ? probe : null, child: const Text('探测并核对主机密钥')),
          if (fingerprint != null) ...[
            const SizedBox(height: 12),
            SelectableText('$algorithm · $fingerprint'),
          ],
          const SizedBox(height: 16),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('使用私钥认证'), value: keyAuth,
            onChanged: busy || hostKeyReviewRequired ? null : (value) => setState(() { cancelKeyPaste(); keyAuth = value; secret.clear(); passphrase.clear(); })),
          const SizedBox(height: 12),
          Semantics(container: true, explicitChildNodes: true, label: keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）',
            child: !keyAuth && !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS
              ? MacosSecureCredentialField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy && !hostKeyReviewRequired,
                  label: '密码（仅本次使用）', identifier: 'direct-secret')
              : TextField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy && !hostKeyReviewRequired, obscureText: !keyAuth,
              minLines: keyAuth ? 2 : 1, maxLines: keyAuth ? 2 : 1, decoration: InputDecoration(label: ExcludeSemantics(child: Text(keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）'))))),
          if (keyAuth) ...[
            TextButton(key: const ValueKey('direct-paste-key'), onPressed: busy || pastingKey || !foreground || hostKeyReviewRequired ? null : pastePrivateKey,
              child: const Text('粘贴私钥')),
            if (pasteStatus != null) Semantics(liveRegion: true, child: Text(pasteStatus!, key: const ValueKey('direct-paste-status'))),
            const SizedBox(height: 16),
            Semantics(container: true, explicitChildNodes: true, label: '私钥口令（可选）',
              child: !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS
                ? MacosSecureCredentialField(key: const ValueKey('direct-passphrase'), controller: passphrase, enabled: !busy && !hostKeyReviewRequired,
                    label: '私钥口令（可选）', identifier: 'direct-passphrase')
                : TextField(key: const ValueKey('direct-passphrase'), controller: passphrase,
                    enabled: !busy && !hostKeyReviewRequired, obscureText: true, decoration: const InputDecoration(label: ExcludeSemantics(child: Text('私钥口令（可选）'))))),
          ],
          const SizedBox(height: 20),
          FilledButton(key: const ValueKey('direct-connect'), onPressed: canConnect ? connect : null, child: const Text('连接 SSH')),
          if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
        ],
      ))),
    ])),
    ),
  );
}
