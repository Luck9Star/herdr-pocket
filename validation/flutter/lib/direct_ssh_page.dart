import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb;
import 'package:flutter/services.dart' show Clipboard;
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'macos_secure_credential_field.dart';
import 'host_catalog.dart';
import 'config_transfer_page.dart';

String formatDirectSshTarget(String username, String host, int port) {
  final displayHost = host.contains(':') && !(host.startsWith('[') && host.endsWith(']')) ? '[$host]' : host;
  return '$username@$displayHost:$port';
}

enum DirectSshConnectPhase { idle, keyParse, socket, handshake, hostKeyVerified, passwordRequest, shellRequest, connected }
enum DirectSshConnectFailure { keyParse, socket, handshake, handshakeTimeout, authRejected, authAborted, authTimeout, timeout, hostKeyChanged, transport, cancelled, other }

/// Standalone SSH shell. Host key verification precedes every authentication.
class DirectSshPage extends StatefulWidget {
  const DirectSshPage({
    super.key,
    required this.tokens,
    this.onReturnAfterDisconnect,
    this.catalog,
    this.closeCatalogTabs,
    this.sessionVisible,
    this.onSelectDestination,
  });
  final DesignTokens tokens;
  final VoidCallback? onReturnAfterDisconnect;
  final HostCatalog? catalog;
  final void Function(Set<String>)? closeCatalogTabs;
  final ValueListenable<bool>? sessionVisible;
  final ValueChanged<int>? onSelectDestination;
  @override
  State<DirectSshPage> createState() => _DirectSshPageState();
}

class _DirectSshPageState extends State<DirectSshPage> with WidgetsBindingObserver {
  final host = TextEditingController(), port = TextEditingController(text: '22'), user = TextEditingController();
  final secret = TextEditingController(), passphrase = TextEditingController();
  final targetScroll = ScrollController();
  final terminalFocus = FocusNode();
  GlobalKey<TerminalViewState> terminalViewKey = GlobalKey<TerminalViewState>();
  final terminalFont = TextEditingController();
  bool settingsActive = false;
  String? settingsNotice;
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
  bool mobileAuth = false, userDisconnected = false;
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

  bool get canConnect => valid && !busy && !hostKeyReviewRequired && fingerprint != null && checkedTarget == target &&
    (mobileLayout ? mobileCredentialReady : secret.text.isNotEmpty);
  bool get mobileCredentialReady {
    if (!keyAuth) return secret.text.isNotEmpty;
    final input = secret.text.trim();
    final match = RegExp(r'^-----BEGIN ((?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY)-----\r?\n([\s\S]+?)\r?\n-----END \1-----$').firstMatch(input);
    if (match == null) return false;
    final body = match.group(2)!.split(RegExp(r'\r?\n')).where((line) => !line.contains(':')).join().replaceAll(RegExp(r'\s'), '');
    Uint8List bytes;
    try { bytes = base64.decode(base64.normalize(body)); } on FormatException { return false; }
    if (bytes.length < 32) return false;
    final kind = match.group(1)!;
    var encrypted = kind == 'ENCRYPTED PRIVATE KEY' || input.contains('Proc-Type: 4,ENCRYPTED');
    if (kind == 'OPENSSH PRIVATE KEY') {
      const magic = 'openssh-key-v1\x00';
      if (bytes.length < magic.length + 4 || ascii.decode(bytes.sublist(0, magic.length), allowInvalid: true) != magic) return false;
      final length = ByteData.sublistView(bytes).getUint32(magic.length);
      final start = magic.length + 4;
      if (length == 0 || start + length > bytes.length) return false;
      final cipher = ascii.decode(bytes.sublist(start, start + length), allowInvalid: true);
      encrypted = cipher != 'none';
    }
    return !encrypted || passphrase.text.isNotEmpty;
  }
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
    widget.catalog?.addListener(catalogChanged);
  }
  void catalogChanged() {
    if (mounted) setState(() {});
  }
  Terminal createTerminal(int generation) {
    final value = Terminal(maxLines: 2000);
    value.onOutput = (data) {
      final current = shell;
      if (generation == epoch && identical(value, terminal) && foreground && connected && !settingsActive && (widget.sessionVisible?.value ?? true) && current != null) current.write(Uint8List.fromList(utf8.encode(data)));
    };
    value.onResize = (cols, rows, px, py) {
      if (generation == epoch && identical(value, terminal) && foreground && connected && (widget.sessionVisible?.value ?? true)) shell?.resizeTerminal(cols, rows, px, py);
    };
    return value;
  }
  void retireTerminal() {
    final current = terminal; terminal = null;
    if (current == null) return;
    current.onOutput = null; current.onResize = null; current.dispose();
  }
  void changed() {
    userDisconnected = false;
    cancelKeyPaste();
    if (busy && pendingTarget != target) stop(message: '连接目标已更改；本次操作已取消。', notify: false);
    if (checkedTarget != target) { mobileAuth = false; fingerprint = null; algorithm = null; checkedTarget = null; hostKeyReviewRequired = false; hostKeyChange = null; secret.clear(); passphrase.clear(); }
    if (mounted) setState(() {});
  }
  void stop({String? message, bool notify = true}) {
    cancelKeyPaste();
    if (busy && connectPhase != DirectSshConnectPhase.idle && connectFailure == null) connectFailure = DirectSshConnectFailure.cancelled;
    epoch++; connected = false; busy = false; pendingTarget = null; activeTarget = null;
    settingsActive = false;
    terminalViewKey.currentState?.closeKeyboard();
    terminalFocus.unfocus();
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
      if (connected || busy) { mobileAuth = false; stop(message: '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。'); }
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
    widget.catalog?.removeListener(catalogChanged);
    secret.removeListener(credentialsChanged); passphrase.removeListener(credentialsChanged);
    stop(notify: false);
    targetScroll.dispose();
    terminalFocus.dispose();
    terminalFont.dispose();
    for (final field in [host, port, user, secret, passphrase]) { field.dispose(); }
    super.dispose();
  }
  Future<void> probe() async {
    if (!valid || busy || !foreground) return;
    userDisconnected = false;
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
      final approved = mobileLayout
        ? await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => mobileTrustPage(originalTarget, result.$1, result.$2)))
        : await showDialog<bool>(context: context, builder: (context) => AlertDialog(
        title: const Text('核对主机密钥'),
        content: SelectableText('目标 $originalTarget\n算法 ${result.$1}\n${result.$2}\n\n请通过可信的独立渠道核对完整指纹。确认后仅对本次页面有效。'),
        actions: [TextButton(key: const ValueKey('direct-trust-cancel'), onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(key: const ValueKey('direct-trust-key'), onPressed: () => Navigator.pop(context, true), child: const Text('已核对并确认'))]));
      if (generation != epoch || originalTarget != target || !mounted) return;
      setState(() { busy = false; pendingTarget = null; if (approved == true) { algorithm = result.$1; fingerprint = result.$2; checkedTarget = originalTarget; hostKeyReviewRequired = false; hostKeyChange = null; mobileAuth = true; status = '已确认本次主机密钥；连接时将重新核对。'; } else { status = '未确认主机密钥，未发送认证。'; } });
    } catch (_) {
      if (generation == epoch && mounted) { stop(message: '探测失败或超时；未发送认证，请检查目标后重试。'); }
    } finally { if (generation != epoch) { localClient?.close(); localSocket?.destroy(); } }
  }
  Future<void> connect() async {
    if (!valid || busy || !foreground || hostKeyReviewRequired || fingerprint == null || checkedTarget != target || secret.text.isEmpty) return;
    userDisconnected = false;
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
  bool get mobileLayout => !kIsWeb &&
    (Theme.of(context).platform == TargetPlatform.iOS || Theme.of(context).platform == TargetPlatform.android) &&
    MediaQuery.sizeOf(context).width < 600;

  bool get mobileLargeText => MediaQuery.textScalerOf(context).scale(1) > 1;
  double get mobileInputHeight => mobileLargeText ? 64 : 48;
  double get mobileButtonHeight => mobileLargeText ? 64 : 48;
  double get mobileMargin => MediaQuery.sizeOf(context).width < 360 ? 16 : 24;
  InputDecoration mobileInput(String hint) => InputDecoration(hintText: hint, hintStyle: TextStyle(color: widget.tokens.color('textMutedReadable')),
    contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12), isDense: true,
    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: widget.tokens.color('borderStrong'))),
    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: widget.tokens.color('brand'), width: 2)));
  Widget mobileField(String label, Widget field) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    SizedBox(height: mobileLargeText ? null : 18, child: Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, letterSpacing: 0))),
    const SizedBox(height: 4), Semantics(container: true, explicitChildNodes: true, label: label, child: field),
  ]);
  Widget mobileTargetCard(String value) => Container(key: const ValueKey('direct-target-card'),
    constraints: const BoxConstraints(minHeight: 52), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(color: widget.tokens.color('card'), borderRadius: BorderRadius.circular(10),
      border: Border.all(color: widget.tokens.color('border'))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('本次连接目标', style: TextStyle(fontSize: 12, color: widget.tokens.color('textSecondary'))),
      SelectableText(value, key: const ValueKey('direct-target-value'), style: const TextStyle(fontSize: 14, fontFamily: 'ProbeNerd')),
    ]));
  PreferredSizeWidget mobileHeader(String title, {VoidCallback? onBack, bool canGoBack = true, bool showStop = false}) => AppBar(
    centerTitle: false, titleSpacing: canGoBack ? 8 : mobileMargin, leadingWidth: mobileMargin + 36,
    toolbarHeight: mobileLargeText ? 80 : 56,
    backgroundColor: widget.tokens.color('canvas'),
    shape: Border(bottom: BorderSide(color: widget.tokens.color('border'))),
    title: Text(title, maxLines: mobileLargeText ? 2 : 1), automaticallyImplyLeading: false,
    actions: [if (showStop) TextButton(onPressed: () { mobileAuth = false; stop(message: '已断开；未重放输入。'); }, child: const Text('断开'))],
    leading: canGoBack ? Padding(padding: EdgeInsets.only(left: mobileMargin - 8), child: SizedBox(width: 44, height: 44,
      child: Center(child: SizedBox(width: 44, height: 44, child: MergeSemantics(child: Semantics(identifier: 'direct-back', label: '返回',
        child: Theme(data: Theme.of(context).copyWith(platform: TargetPlatform.android), child: BackButton(onPressed: onBack)))))))) : null);
  ButtonStyle get mobilePrimaryButton => FilledButton.styleFrom(textStyle: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600));
  ButtonStyle get mobileSecondaryButton => OutlinedButton.styleFrom(textStyle: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600), foregroundColor: widget.tokens.color('textPrimary'),
    side: BorderSide(color: widget.tokens.color('borderStrong')), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)));
  Widget mobileTrustPage(String originalTarget, String foundAlgorithm, String foundFingerprint) {
    final t = widget.tokens;
    final large = MediaQuery.textScalerOf(context).scale(1) > 1;
    Widget textLabel(String text) => Text(text, style: TextStyle(fontSize: 12, color: t.color('textSecondary')));
    final evidence = large ? Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      textLabel('主机密钥算法'), SelectableText(foundAlgorithm, key: const ValueKey('direct-key-algorithm'), style: const TextStyle(fontFamily: 'ProbeNerd')),
      const Divider(), textLabel('完整 SHA256 指纹'), SelectableText(foundFingerprint, key: const ValueKey('direct-key-fingerprint'), style: const TextStyle(fontSize: 13, fontFamily: 'ProbeNerd')),
    ])) : SizedBox(height: 120, child: Stack(children: [
      Positioned(left: 12, top: 6, child: textLabel('主机密钥算法')),
      Positioned(left: 12, right: 12, top: 24, child: SelectableText(foundAlgorithm, key: const ValueKey('direct-key-algorithm'), style: const TextStyle(fontFamily: 'ProbeNerd'))),
      Positioned(left: 12, right: 12, top: 53, child: Divider(height: 1, color: t.color('border'))),
      Positioned(left: 12, top: 57, child: textLabel('完整 SHA256 指纹')),
      Positioned(left: 12, right: 12, top: 76, child: SelectableText(foundFingerprint,
        key: const ValueKey('direct-key-fingerprint'), style: const TextStyle(fontSize: 13, height: 1.3, fontFamily: 'ProbeNerd'))),
    ]));
    return Scaffold(appBar: mobileHeader('核对主机密钥'),
      body: SafeArea(child: ListView(padding: EdgeInsets.fromLTRB(mobileMargin, 20, mobileMargin, 24), children: [
        mobileTargetCard(originalTarget), const SizedBox(height: 12),
        Container(key: const ValueKey('direct-key-evidence'),
          decoration: BoxDecoration(color: t.color('card'), borderRadius: BorderRadius.circular(16), border: Border.all(color: t.color('border'))),
          child: evidence),
        const SizedBox(height: 16), SizedBox(height: large ? null : 52, child: Text('请通过服务器控制台或向管理员独立核对。\n算法和完整指纹一致后，再确认继续。',
          style: TextStyle(fontSize: 13, height: 1.6, color: t.color('textSecondary')))),
        const SizedBox(height: 6), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-trust-key'),
          onPressed: () => Navigator.pop(context, true), child: const Text('指纹一致，确认继续'))),
        const SizedBox(height: 12), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-trust-cancel'),
          style: mobileSecondaryButton, onPressed: () => Navigator.pop(context, false), child: Text(hostKeyReviewRequired ? '取消核对，保留旧信任' : '取消核对'))),
      ])));
  }
  void returnAfterDisconnect() => Navigator.pop(context);
  void backFromMobileAuth() {
    if (busy) {
      stop(message: '连接已取消；已发送的数据无法撤回。', notify: false);
    } else {
      cancelKeyPaste(); secret.clear(); passphrase.clear();
    }
    setState(() { mobileAuth = false; });
  }
  Widget mobileTargetForm() => ListView(key: const ValueKey('direct-form'), padding: EdgeInsets.fromLTRB(mobileMargin, 20, mobileMargin, 24), children: [
    if (userDisconnected && !busy) ...[
      Container(key: const ValueKey('direct-closed-feedback'), constraints: const BoxConstraints(minHeight: 66),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: widget.tokens.color('brandSoft'), borderRadius: BorderRadius.circular(10),
          border: Border.all(color: widget.tokens.color('brandBorder'))),
        child: Semantics(liveRegion: true, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('已断开连接', key: const ValueKey('direct-status'), style: TextStyle(color: widget.tokens.color('brand'), fontWeight: FontWeight.bold)),
          Text('本次凭据已清空。重新连接时请重新填写。', style: TextStyle(fontSize: 13, color: widget.tokens.color('textSecondary'))),
        ]))), const SizedBox(height: 16),
    ] else if (hostKeyReviewRequired && !busy) ...[
      Container(key: const ValueKey('direct-trust-preserved'), constraints: const BoxConstraints(minHeight: 66),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: widget.tokens.color('brandSoft'), borderRadius: BorderRadius.circular(10),
          border: Border.all(color: widget.tokens.color('brandBorder'))),
        child: Semantics(liveRegion: true, label: status, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('已保留旧信任', key: const ValueKey('direct-status'), style: TextStyle(color: widget.tokens.color('brand'), fontWeight: FontWeight.bold)),
          Text('请重新探测并独立核对主机指纹。', style: TextStyle(fontSize: 13, color: widget.tokens.color('textSecondary'))),
        ]))), const SizedBox(height: 16),
    ] else if (status != '填写连接信息后先探测主机密钥。' && !busy) ...[
      Semantics(liveRegion: true, child: Text(status, key: const ValueKey('direct-status'))), const SizedBox(height: 16),
    ],
    SizedBox(height: mobileLargeText ? null : 28, child: Transform.translate(offset: Offset(0, mobileLargeText ? 0 : -4),
      child: const Text('填写连接目标', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, letterSpacing: 0)))),
    const SizedBox(height: 8),
    mobileField('主机地址', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-host'), controller: host, enabled: !busy,
      decoration: mobileInput('ssh.example.test')))),
    const SizedBox(height: 14),
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: mobileField('用户名', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-user'), controller: user, enabled: !busy,
        decoration: mobileInput('demo'))))),
      const SizedBox(width: 12), SizedBox(width: 84, child: mobileField('端口', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-port'),
        controller: port, enabled: !busy, keyboardType: TextInputType.number, decoration: mobileInput('22'))))),
    ]),
    const SizedBox(height: 20), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-probe'),
      onPressed: valid && !busy ? probe : null, child: const Text('探测并核对主机密钥'))),
    const SizedBox(height: 9), Text('探测时仅获取主机密钥，认证在核对之后进行。',
      style: TextStyle(fontSize: 12, color: widget.tokens.color('textMutedReadable'))),
    if (userDisconnected) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(
      key: const ValueKey('direct-return-home'), style: mobileSecondaryButton, onPressed: returnAfterDisconnect, child: const Text('返回首页')))],
    if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
  ]);
  Widget mobileAuthForm() {
    final t = widget.tokens;
    Widget choice(String text, bool value) => Expanded(child: SizedBox(height: mobileLargeText ? 60 : 44, child: OutlinedButton(
      key: ValueKey(value ? 'direct-auth-key' : 'direct-auth-password'),
      style: OutlinedButton.styleFrom(backgroundColor: t.color(keyAuth == value ? 'brandSoft' : 'card'),
        foregroundColor: t.color(keyAuth == value ? 'brand' : 'textSecondary'),
        side: BorderSide(color: t.color(keyAuth == value ? 'brand' : 'borderStrong')),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
      onPressed: busy || hostKeyReviewRequired ? null : () => setState(() { cancelKeyPaste(); keyAuth = value; secret.clear(); passphrase.clear(); }),
      child: Text(text))));
    return ListView(key: const ValueKey('direct-form'), padding: EdgeInsets.fromLTRB(mobileMargin, 20, mobileMargin, 24), children: [
      mobileTargetCard(checkedTarget ?? target), const SizedBox(height: 10),
      Container(height: 44, padding: const EdgeInsets.symmetric(horizontal: 12), alignment: Alignment.centerLeft,
        decoration: BoxDecoration(color: t.color('successSoft'), borderRadius: BorderRadius.circular(10), border: Border.all(color: t.color('successBorder'))),
        child: Text('本次主机密钥已确认', style: TextStyle(color: t.color('successText'), fontWeight: FontWeight.bold))),
      if (status != '已确认本次主机密钥；连接时将重新核对。') ...[const SizedBox(height: 10), Semantics(liveRegion: true, child: Text(status, key: const ValueKey('direct-status')))],
      SizedBox(height: MediaQuery.sizeOf(context).width < 360 ? 12 : 20),
      const Text('认证方式', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold)), const SizedBox(height: 4),
      Row(children: [choice('密码', false), const SizedBox(width: 8), choice('已有私钥', true)]), const SizedBox(height: 14),
      mobileField(keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）',
        SizedBox(height: keyAuth ? (mobileLargeText ? 110 : MediaQuery.sizeOf(context).width < 360 ? 68 : 84) : mobileInputHeight,
          child: TextField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy && !hostKeyReviewRequired,
            obscureText: !keyAuth, minLines: keyAuth ? 2 : 1, maxLines: keyAuth ? 2 : 1,
            decoration: mobileInput(keyAuth ? '粘贴已有私钥的完整 PEM' : '未填写')))),
      if (keyAuth) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-paste-key'),
        style: mobileSecondaryButton, onPressed: busy || pastingKey || !foreground || hostKeyReviewRequired ? null : pastePrivateKey, child: const Text('粘贴私钥'))),
        if (pasteStatus != null) Semantics(liveRegion: true, child: Text(pasteStatus!, key: const ValueKey('direct-paste-status'))),
        const SizedBox(height: 12), mobileField('私钥口令（加密私钥需要）', SizedBox(height: mobileInputHeight,
          child: TextField(key: const ValueKey('direct-passphrase'), controller: passphrase, enabled: !busy && !hostKeyReviewRequired,
            obscureText: true, decoration: mobileInput('未填写')))),
      ],
      const SizedBox(height: 14), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-connect'),
        onPressed: canConnect ? connect : null, child: const Text('连接 SSH'))),
      const SizedBox(height: 16), Text(keyAuth ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。',
        style: TextStyle(fontSize: 12, color: t.color('textMutedReadable'))),
      if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
    ]);
  }
  Widget mobileHostKeyChangeView() {
    final change = hostKeyChange!, t = widget.tokens;
    final sameAlgorithm = change.oldAlgorithm == change.newAlgorithm;
    Widget keyText(String key, String value) => SelectableText(value, key: ValueKey(key),
      style: const TextStyle(fontSize: 13, height: 1.3, fontFamily: 'ProbeNerd'));
    final keys = !mobileLargeText && sameAlgorithm ? SizedBox(height: 165, child: Stack(children: [
      Positioned(left: 12, right: 12, top: 4, child: Text('算法 · ${change.oldAlgorithm}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, fontFamily: 'ProbeNerd'))),
      Positioned(left: 12, top: 27, child: Text('旧指纹 · 已核对', style: TextStyle(fontSize: 12, color: t.color('textSecondary')))),
      Positioned(left: 12, right: 12, top: 52, child: keyText('direct-host-key-old', change.oldFingerprint)),
      Positioned(left: 12, right: 12, top: 92, child: Divider(height: 1, color: t.color('border'))),
      Positioned(left: 12, top: 98, child: Text('新指纹 · 待核对', style: TextStyle(fontSize: 12, color: t.color('dangerText')))),
      Positioned(left: 12, right: 12, top: 124, child: keyText('direct-host-key-new', change.newFingerprint)),
    ])) : Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('旧指纹 · 已核对 · ${change.oldAlgorithm}', style: TextStyle(fontSize: 12, color: t.color('textSecondary'))),
      keyText('direct-host-key-old', change.oldFingerprint), const Divider(),
      Text('新指纹 · 待核对 · ${change.newAlgorithm}', style: TextStyle(fontSize: 12, color: t.color('dangerText'))),
      keyText('direct-host-key-new', change.newFingerprint),
    ]));
    return ListView(key: const ValueKey('direct-host-key-change'), padding: EdgeInsets.fromLTRB(mobileMargin, 20, mobileMargin, 24), children: [
      Container(key: const ValueKey('direct-changed-warning'), constraints: const BoxConstraints(minHeight: 84),
        padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: t.color('dangerSoft'), borderRadius: BorderRadius.circular(10),
          border: Border.all(color: t.color('dangerBorder'))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('已阻止连接与输入', style: TextStyle(fontWeight: FontWeight.bold, color: t.color('dangerText'))),
          Text('主机密钥与上次核对结果不同。\n请联系管理员确认变更，再重新核验。',
            style: TextStyle(fontSize: 13, color: t.color('textSecondary'), height: 1.4)),
        ])), const SizedBox(height: 12),
      mobileTargetCard(change.target), const SizedBox(height: 12),
      Container(key: const ValueKey('direct-changed-keys'),
        decoration: BoxDecoration(color: t.color('card'), borderRadius: BorderRadius.circular(16), border: Border.all(color: t.color('border'))), child: keys),
      const SizedBox(height: 16), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-host-key-review'),
        onPressed: reviewHostKeyChange, child: const Text('重新核对主机指纹'))),
      const SizedBox(height: 12), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-host-key-cancel'),
        style: mobileSecondaryButton, onPressed: cancelHostKeyChange, child: const Text('取消连接，保留旧信任'))),
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
  void retireMobileInput() {
    terminalViewKey.currentState?.closeKeyboard();
    terminalFocus.unfocus();
    terminalViewKey = GlobalKey<TerminalViewState>();
  }

  void selectMobileTerminal(bool settings) {
    if (!connected) return;
    FocusScope.of(context).unfocus();
    retireMobileInput();
    setState(() {
      settingsActive = settings;
      settingsNotice = null;
      if (settings) {
        terminalFont.text = '${widget.catalog?.terminalFontSize ?? 14}';
      }
    });
  }

  Future<void> saveMobileTerminalFont() async {
    final catalog = widget.catalog;
    final size = int.tryParse(terminalFont.text.trim());
    if (catalog == null || size == null || size < 10 || size > 28) {
      setState(() => settingsNotice = '请输入 10–28 的终端字号。');
      return;
    }
    try {
      final revision = catalog.revision;
      await catalog.updateTerminalFontSize(size, expectedRevision: revision);
      if (mounted) setState(() => settingsNotice = '终端字号已保存。');
    } catch (_) {
      if (mounted) setState(() => settingsNotice = '字号保存未确认，请重新读取后重试。');
    }
  }

  Widget mobileConnectedNavigation() {
    final entries = [
      (Icons.dashboard_outlined, '看板'),
      (Icons.terminal, '终端'),
      (Icons.language, '网络'),
      (Icons.settings_outlined, '设置'),
    ];
    return Material(
      color: widget.tokens.color('card'),
      child: SafeArea(
        top: false,
        child: Container(
          key: const ValueKey('direct-terminal-tabs'),
          height: 56,
          foregroundDecoration: BoxDecoration(
            border: Border(
              top: BorderSide(color: widget.tokens.color('border')),
            ),
          ),
          child: Row(
            children: [
              for (var i = 0; i < entries.length; i++)
                Expanded(
                  child: InkWell(
                    key: ValueKey(
                      [
                        'direct-tab-board',
                        'direct-tab-terminal',
                        'direct-tab-network',
                        'direct-tab-settings',
                      ][i],
                    ),
                    onTap: i == 1
                        ? () => selectMobileTerminal(false)
                        : i == 3 && widget.catalog != null
                        ? () => selectMobileTerminal(true)
                        : (i == 0 || i == 2) && widget.onSelectDestination != null
                        ? () {
                            retireMobileInput();
                            setState(() => settingsActive = false);
                            widget.onSelectDestination!(i);
                          }
                        : null,
                    child: Semantics(
                      button: true,
                      enabled: i == 1 || (i == 3 && widget.catalog != null) ||
                          ((i == 0 || i == 2) && widget.onSelectDestination != null),
                      selected: settingsActive ? i == 3 : i == 1,
                      child: Stack(
                        alignment: Alignment.topCenter,
                        children: [
                          Positioned(
                            top: 4,
                            child: Container(
                              width: 40,
                              height: 28,
                              decoration: BoxDecoration(
                                color: (settingsActive ? i == 3 : i == 1)
                                    ? widget.tokens.color('brandSoft')
                                    : Colors.transparent,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: Icon(
                                entries[i].$1,
                                size: 24,
                                color: widget.tokens.color(
                                  (settingsActive ? i == 3 : i == 1)
                                      ? 'brand'
                                      : 'textSecondary',
                                ),
                              ),
                            ),
                          ),
                          Positioned(
                            top: 36,
                            child: Text(
                              entries[i].$2,
                              textScaler: TextScaler.noScaling,
                              style: TextStyle(
                                fontSize: 12,
                                height: 1,
                                color: widget.tokens.color(
                                  (settingsActive ? i == 3 : i == 1)
                                      ? 'brand'
                                      : 'textSecondary',
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  PreferredSizeWidget mobileActiveHeader() => AppBar(
    key: const ValueKey('direct-active-header'),
    automaticallyImplyLeading: false,
    centerTitle: false,
    titleSpacing: mobileMargin,
    backgroundColor: widget.tokens.color('canvas'),
    shape: Border(bottom: BorderSide(color: widget.tokens.color('border'))),
    title: Text(settingsActive ? '设置' : '普通 SSH'),
    actions: settingsActive
        ? null
        : [
            Padding(
              padding: EdgeInsets.only(right: mobileMargin),
              child: SizedBox(
                width: 60,
                height: 44,
                child: TextButton(
                  key: const ValueKey('direct-disconnect'),
                  style: TextButton.styleFrom(
                    backgroundColor: widget.tokens.color('dangerSoft'),
                    foregroundColor: widget.tokens.color('dangerText'),
                    padding: EdgeInsets.zero,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  onPressed: () {
                    userDisconnected = true;
                    mobileAuth = false;
                    stop(message: '已断开；未重放输入。');
                  },
                  child: const Text('断开'),
                ),
              ),
            ),
          ],
  );
  Widget mobileKey(
    String id,
    String label,
    VoidCallback action, {
    double width = 44,
  }) => SizedBox(
    width: width,
    height: 44,
    child: TextButton(
      key: ValueKey('direct-key-$id'),
      onPressed: action,
      style: TextButton.styleFrom(
        padding: EdgeInsets.zero,
        minimumSize: Size(width, 44),
        backgroundColor: widget.tokens.color('termKeyBg'),
        foregroundColor: widget.tokens.color('termText'),
        side: BorderSide(color: widget.tokens.color('termKeyBorder')),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      child: Text(
        label,
        style: const TextStyle(fontFamily: 'ProbeNerd', fontSize: 12),
      ),
    ),
  );
  Widget mobileTerminalKeys(Terminal current) {
    final keys = [
      mobileKey('esc', 'Esc', () => current.textInput('\u001b')),
      mobileKey('tab', 'Tab', () => current.textInput('\t')),
      mobileKey('up', '↑', () => current.keyInput(TerminalKey.arrowUp)),
      mobileKey('down', '↓', () => current.keyInput(TerminalKey.arrowDown)),
      mobileKey('left', '←', () => current.keyInput(TerminalKey.arrowLeft)),
      mobileKey('right', '→', () => current.keyInput(TerminalKey.arrowRight)),
      mobileKey(
        'ctrl-c',
        'Ctrl-C',
        () => current.textInput('\u0003'),
        width: 54,
      ),
      if (MediaQuery.sizeOf(context).width < 360)
        SizedBox(
          width: (MediaQuery.sizeOf(context).width - 2 * mobileMargin - 154)
              .clamp(0.0, double.infinity),
        ),
      mobileKey(
        'ctrl-d',
        'Ctrl-D',
        () => current.textInput('\u0004'),
        width: 54,
      ),
      mobileKey('enter', 'Enter', () => current.textInput('\r'), width: 54),
    ];
    Widget row(List<Widget> items) => SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (var i = 0; i < items.length; i++) ...[
            if (i > 0) const SizedBox(width: 4),
            items[i],
          ],
        ],
      ),
    );
    return SizedBox(
      key: const ValueKey('direct-terminal-keys'),
      width: double.infinity,
      height: MediaQuery.sizeOf(context).width < 360 ? 92 : 44,
      child: MediaQuery.sizeOf(context).width < 360
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                row(keys.take(4).toList()),
                const SizedBox(height: 4),
                row(keys.skip(4).toList()),
              ],
            )
          : row(keys),
    );
  }

  Widget mobileTerminalWorkspace() {
    final t = widget.tokens;
    final keyboardVisible = MediaQuery.viewInsetsOf(context).bottom > 0;
    final margin = mobileMargin;
    final minimumHeight =
        24.0 +
        44 +
        16 +
        80 +
        (MediaQuery.sizeOf(context).width < 360 ? 92 : 44);
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        primary: false,
        child: SizedBox(
          height: constraints.maxHeight < minimumHeight
              ? minimumHeight
              : constraints.maxHeight,
          child: Padding(
            padding: EdgeInsets.fromLTRB(margin, 12, margin, 12),
            child: Column(
              children: [
                SizedBox(
                  key: const ValueKey('direct-terminal-status'),
                  height: 44,
                  child: Row(
                    children: [
                      Container(
                        width: 62,
                        height: 24,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: t.color('successSoft'),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: t.color('successBorder')),
                        ),
                        child: Text(
                          '已连接',
                          textScaler: TextScaler.noScaling,
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                            color: t.color('successText'),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: LayoutBuilder(
                          builder: (context, constraints) {
                            final style = TextStyle(
                              fontFamily: 'ProbeNerd',
                              fontSize: MediaQuery.sizeOf(context).width < 360
                                  ? 11
                                  : 12,
                            );
                            final painter = TextPainter(
                              text: TextSpan(
                                text: activeTarget ?? '',
                                style: style,
                              ),
                              textDirection: Directionality.of(context),
                              textScaler: MediaQuery.textScalerOf(context),
                              maxLines: 1,
                            )..layout();
                            final longTarget =
                                painter.width > constraints.maxWidth;
                            painter.dispose();
                            return Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.start,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                if (longTarget)
                                  const Text(
                                    '连接目标 · 左右滑动查看',
                                    textScaler: TextScaler.noScaling,
                                    style: TextStyle(fontSize: 10),
                                  ),
                                Flexible(
                                  child: SingleChildScrollView(
                                    key: const ValueKey('direct-target-scroll'),
                                    controller: targetScroll,
                                    scrollDirection: Axis.horizontal,
                                    child: Text(
                                      activeTarget ?? '',
                                      key: const ValueKey(
                                        'direct-active-target',
                                      ),
                                      maxLines: 1,
                                      softWrap: false,
                                      style: style,
                                    ),
                                  ),
                                ),
                              ],
                            );
                          },
                        ),
                      ),
                      const SizedBox(width: 4),
                      SizedBox(
                        width: 44,
                        height: 44,
                        child: IconButton(
                          key: const ValueKey('direct-keyboard-toggle'),
                          tooltip: keyboardVisible ? '收起键盘' : '打开键盘',
                          padding: EdgeInsets.zero,
                          onPressed: () {
                            if (keyboardVisible) {
                              setState(retireMobileInput);
                            } else {
                              terminalViewKey.currentState?.requestKeyboard();
                            }
                          },
                          icon: Container(
                            width: 44,
                            height: 36,
                            decoration: BoxDecoration(
                              color: t.color('card'),
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                color: t.color('borderStrong'),
                              ),
                            ),
                            child: Icon(
                              keyboardVisible
                                  ? Icons.keyboard_hide_outlined
                                  : Icons.keyboard_outlined,
                              color: t.color('brand'),
                              size: 24,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: Container(
                    key: const ValueKey('direct-terminal-panel'),
                    foregroundDecoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: t.color('termBorder')),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: TerminalView(
                        terminal!,
                        key: terminalViewKey,
                        focusNode: terminalFocus,
                        theme: t.terminalTheme,
                        autoResize: true,
                        padding: const EdgeInsets.all(12),
                        textStyle: TerminalStyle(
                          fontFamily: 'ProbeNerd',
                          fontSize: (widget.catalog?.terminalFontSize ?? 14)
                              .toDouble(),
                          height: 20 / 14,
                          fontFamilyFallback: [
                            ...?Theme.of(context)
                                .textTheme
                                .bodyMedium
                                ?.fontFamilyFallback,
                            ...const TerminalStyle().fontFamilyFallback,
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                mobileTerminalKeys(terminal!),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget mobileActiveSettings() {
    final t = widget.tokens;
    final catalog = widget.catalog;
    return ListView(
      key: const ValueKey('direct-settings'),
      padding: EdgeInsets.fromLTRB(mobileMargin, 20, mobileMargin, 24),
      children: [
        Container(
          key: const ValueKey('direct-settings-active'),
          height: 44,
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: t.color('successSoft'),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: t.color('successBorder')),
          ),
          child: Text(
            '普通 SSH 会话保持连接',
            style: TextStyle(
              color: t.color('successText'),
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        const SizedBox(height: 10),
        mobileTargetCard(activeTarget ?? ''),
        const SizedBox(height: 16),
        mobileField(
          '终端字号（10–28）',
          SizedBox(
            height: 48,
            child: TextField(
              key: const ValueKey('direct-settings-font'),
              controller: terminalFont,
              keyboardType: TextInputType.number,
              decoration: mobileInput('14'),
            ),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 48,
          child: OutlinedButton(
            key: const ValueKey('direct-settings-save'),
            style: mobileSecondaryButton,
            onPressed: catalog?.ready == true && catalog?.writing == false
                ? saveMobileTerminalFont
                : null,
            child: const Text('保存字号'),
          ),
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: 48,
          child: OutlinedButton(
            key: const ValueKey('direct-settings-transfer'),
            style: mobileSecondaryButton,
            onPressed:
                catalog?.ready == true &&
                    catalog?.writing == false &&
                    catalog?.pendingCreation == null &&
                    widget.closeCatalogTabs != null
                ? () => Navigator.push<void>(
                    context,
                    MaterialPageRoute(
                      builder: (_) => ConfigTransferPage(
                        catalog: catalog!,
                        closeTabs: widget.closeCatalogTabs!,
                      ),
                    ),
                  )
                : null,
            child: const Text('导入 / 导出配置'),
          ),
        ),
        if (settingsNotice != null) ...[
          const SizedBox(height: 12),
          Semantics(liveRegion: true, child: Text(settingsNotice!)),
        ],
      ],
    );
  }
  @override
  Widget build(BuildContext context) => PopScope<void>(
    canPop: hostKeyChange == null && !settingsActive,
    onPopInvokedWithResult: (didPop, result) {
      if (!didPop && settingsActive && connected) {
        selectMobileTerminal(false);
      }
      if (didPop && busy) stop(notify: false);
      if (didPop && userDisconnected) { userDisconnected = false; widget.onReturnAfterDisconnect?.call(); }
    },
    child: Scaffold(
      bottomNavigationBar: mobileLayout && connected && MediaQuery.viewInsetsOf(context).bottom == 0 ? mobileConnectedNavigation() : null,
      appBar: mobileLayout && connected ? mobileActiveHeader() : mobileLayout && !connected ? mobileHeader(hostKeyChange != null ? '主机指纹发生变化' : mobileAuth && !hostKeyReviewRequired ? 'SSH 账号认证' : '普通 SSH',
        canGoBack: hostKeyChange == null && (ModalRoute.of(context)?.impliesAppBarDismissal ?? false), showStop: busy, onBack: mobileAuth && !hostKeyReviewRequired ? backFromMobileAuth
          : userDisconnected ? returnAfterDisconnect : null)
        : AppBar(title: const Text('普通 SSH'),
      automaticallyImplyLeading: hostKeyChange == null,
      leading: hostKeyChange == null && (ModalRoute.of(context)?.impliesAppBarDismissal ?? false)
        ? MergeSemantics(child: Semantics(identifier: 'direct-back', label: '返回主机列表', child: BackButton(onPressed: mobileLayout && mobileAuth && !connected
          ? backFromMobileAuth : null))) : null,
      actions: [if (busy || connected) TextButton(onPressed: () { userDisconnected = mobileLayout && connected; mobileAuth = false; stop(message: '已断开；未重放输入。'); }, child: const Text('断开'))]),
    body: SafeArea(child: hostKeyChange != null ? (mobileLayout ? mobileHostKeyChangeView() : hostKeyChangeView()) : connected && mobileLayout ? IndexedStack(
      index: settingsActive ? 1 : 0, children: [mobileTerminalWorkspace(), mobileActiveSettings()]) : connected ? LayoutBuilder(
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
    ])))) : mobileLayout ? (mobileAuth && !hostKeyReviewRequired ? mobileAuthForm() : mobileTargetForm()) : ListView(key: const ValueKey('direct-form'), padding: const EdgeInsets.all(16), children: [
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
