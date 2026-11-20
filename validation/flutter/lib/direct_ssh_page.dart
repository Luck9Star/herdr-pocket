import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb;
import 'package:flutter/services.dart' show Clipboard, FilteringTextInputFormatter, LengthLimitingTextInputFormatter;
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';
import 'macos_secure_credential_field.dart';
import 'host_catalog.dart';
import 'host_tabs.dart';
import 'config_transfer_page.dart';

String formatDirectSshTarget(String username, String host, int port) {
  final displayHost = host.contains(':') && !(host.startsWith('[') && host.endsWith(']')) ? '[$host]' : host;
  return '$username@$displayHost:$port';
}

enum DirectSshConnectPhase { idle, keyParse, socket, handshake, hostKeyVerified, passwordRequest, shellRequest, connected }
enum DirectSshConnectFailure { keyParse, socket, handshake, handshakeTimeout, authRejected, authAborted, authTimeout, timeout, hostKeyChanged, transport, cancelled, other }
enum DirectSshRouteExit { targetBack }

/// Standalone SSH shell. Host key verification precedes every authentication.
class DirectSshPage extends StatefulWidget {
  const DirectSshPage({
    super.key,
    required this.tokens,
    this.onReturnAfterDisconnect,
    this.catalog,
    this.catalogTabs,
    this.closeCatalogTabs,
    this.sessionVisible,
    this.onSelectDestination,
    this.desktopFlowShell,
    this.desktopDestination,
    this.onConnectionChanged,
  });
  final DesignTokens tokens;
  final ValueChanged<bool>? onReturnAfterDisconnect;
  final HostCatalog? catalog;
  final HostTabs? catalogTabs;
  final FutureOr<void> Function(Set<String>)? closeCatalogTabs;
  final ValueListenable<bool>? sessionVisible;
  final ValueChanged<int>? onSelectDestination;
  final Widget Function(Widget page, ValueChanged<int> select, [int? selected])? desktopFlowShell;
  final ValueListenable<int>? desktopDestination;
  final ValueChanged<bool>? onConnectionChanged;
  @override
  State<DirectSshPage> createState() => _DirectSshPageState();
}

class _DirectSshPageState extends State<DirectSshPage> with WidgetsBindingObserver {
  final host = TextEditingController(), port = TextEditingController(text: '22'), user = TextEditingController();
  final secret = TextEditingController(), passphrase = TextEditingController();
  final targetScroll = ScrollController();
  final terminalFocus = FocusNode();
  final pemFocus = FocusNode();
  bool editingPem = false;
  final pemLayoutKey = GlobalKey();
  double? pemEditorHeight;
  GlobalKey<TerminalViewState> terminalViewKey = GlobalKey<TerminalViewState>();
  final desktopTerminalFocus = FocusNode(debugLabel: 'ordinary SSH desktop input');
  final desktopTerminalScroll = ScrollController();
  GlobalKey<TerminalViewState> desktopTerminalKey = GlobalKey<TerminalViewState>();
  bool restoreDesktopFocus = false;
  double? parkedDesktopScroll;
  bool hadDesktopLayout = false;
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
  bool closeLocalConfirmed = false;
  bool closeRemoteReported = false;
  bool closeCleanupFailed = false;
  int? closeReturnEpoch;
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

  bool get closePending => userDisconnected && !closeLocalConfirmed && !closeCleanupFailed;
  bool get canProbe => valid && !busy && !closePending;
  bool get canConnect => valid && !busy && !closePending && !hostKeyReviewRequired && fingerprint != null && checkedTarget == target &&
    (mobileLayout || desktopEntryLayout(context) ? mobileCredentialReady : secret.text.isNotEmpty);
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
  void rememberPemHeight() { pemEditorHeight = pemLayoutKey.currentContext?.size?.height ?? pemEditorHeight; }
  void credentialsChanged() { rememberPemHeight(); cancelKeyPaste(); if (mounted) setState(() {}); }
  void pemFocusChanged() { if (mounted) { rememberPemHeight(); setState(() { editingPem = pemFocus.hasFocus; }); } }
  bool blurPemForNativePassphrase() {
    if (!pemFocus.hasFocus) return false;
    pemFocus.unfocus();
    return true;
  }
  void editPem() {
    setState(() { editingPem = true; });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && keyAuth && editingPem) pemFocus.requestFocus();
    });
  }
  Widget collapsedPem({required bool enabled}) => OutlinedButton(
    key: const ValueKey('direct-edit-pem'), onPressed: enabled ? editPem : null,
    child: const Text('已填写私钥 · 重新编辑'));
  bool get pemCollapsed => keyAuth && secret.text.isNotEmpty && !editingPem;


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
    pemFocus.addListener(pemFocusChanged);
    widget.catalog?.addListener(catalogChanged);
    widget.desktopDestination?.addListener(desktopDestinationChanged);
  }
  void catalogChanged() {
    if (mounted) setState(() {});
  }

  void desktopDestinationChanged() {
    if (!connected || !desktopEntryLayout(context)) return;
    updateDesktopDestination(widget.desktopDestination!.value);
  }

  void selectDesktopDestination(int destination) {
    if (widget.desktopDestination?.value == destination) updateDesktopDestination(destination);
    widget.onSelectDestination!(destination);
  }

  void parkDesktopTerminal() {
    if (desktopTerminalScroll.hasClients && parkedDesktopScroll == null) {
      final position = desktopTerminalScroll.position;
      parkedDesktopScroll = position.pixels < position.maxScrollExtent ? position.pixels : null;
    }
    if (desktopTerminalFocus.hasFocus) {
      restoreDesktopFocus = true;
      desktopTerminalKey.currentState?.closeKeyboard();
      desktopTerminalFocus.unfocus();
      // Retire the old editing client so its composition cannot be resumed.
      desktopTerminalKey = GlobalKey<TerminalViewState>();
    }
  }

  void restoreDesktopTerminal() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !foreground || !connected || !desktopEntryLayout(context) ||
          settingsActive || widget.sessionVisible?.value == false || !desktopTerminalScroll.hasClients) return;
      if (parkedDesktopScroll case final offset?) {
        final position = desktopTerminalScroll.position;
        desktopTerminalScroll.jumpTo(offset.clamp(position.minScrollExtent, position.maxScrollExtent));
        parkedDesktopScroll = null;
      }
      if (restoreDesktopFocus) {
        restoreDesktopFocus = false;
        desktopTerminalFocus.requestFocus();
      }
    });
  }

  void updateDesktopDestination(int destination) {
    if (destination != 1) parkDesktopTerminal();
    setState(() {
      settingsActive = destination == 3;
      if (settingsActive) {
        terminalFont.text = '${widget.catalog?.terminalFontSize ?? 14}';
        settingsNotice = null;
      }
    });
    if (destination == 1) restoreDesktopTerminal();
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
  void resetCloseOutcome() {
    closeLocalConfirmed = false;
    closeRemoteReported = false;
    closeCleanupFailed = false;
    closeReturnEpoch = null;
  }
  void changed() {
    // The target draft is independent of the retiring session's receipt.
    cancelKeyPaste();
    if (busy && pendingTarget != target) stop(message: '连接目标已更改；本次操作已取消。', notify: false);
    if (checkedTarget != target) { mobileAuth = false; fingerprint = null; algorithm = null; checkedTarget = null; hostKeyReviewRequired = false; hostKeyChange = null; secret.clear(); passphrase.clear(); }
    if (mounted) setState(() {});
  }
  Future<({bool localClosed, bool remoteReported})> _retireActiveSession(SSHSession session, SSHClient transport, SSHSocket connection) async {
    const limit = Duration(seconds: 3);
    final elapsed = Stopwatch()..start();
    try {
      // Close stdin after delivering its queued bytes. Keep the original
      // transport reading until the peer closes the channel.
      await Future.wait<void>([session.stdin.close(), session.done], eagerError: true).timeout(limit);
      // A remote exit report is independent evidence; local closure is the
      // acceptance condition, so both outcomes are returned separately.
      final remoteReported = session.exitCode != null || session.exitSignal != null;
      await transport.close().timeout(limit - elapsed.elapsed);
      return (localClosed: true, remoteReported: remoteReported);
    } catch (_) {
      final remoteReported = session.exitCode != null || session.exitSignal != null;
      try {
        connection.destroy();
        return (localClosed: true, remoteReported: remoteReported);
      } catch (_) {
        return (localClosed: false, remoteReported: remoteReported);
      }
    }
  }

  void disconnect() {
    final wasConnected = connected;
    userDisconnected = wasConnected;
    resetCloseOutcome();
    mobileAuth = false;
    stop(message: wasConnected ? '正在断开本机连接；未重放输入。' : '已断开；未重放输入。', drainInput: wasConnected, reportCloseOutcome: wasConnected);
  }

  void observeShellEnd(SSHSession session, int generation) {
    unawaited(session.done.then<void>((_) {
      if (generation == epoch) disconnect();
    }, onError: (Object _, StackTrace __) {
      if (generation == epoch) stop(message: '连接中断，输入已停止。');
    }));
  }

  void stop({String? message, bool notify = true, bool drainInput = false, bool reportCloseOutcome = false}) {
    final wasConnected = connected;
    cancelKeyPaste();
    if (busy && connectPhase != DirectSshConnectPhase.idle && connectFailure == null) connectFailure = DirectSshConnectFailure.cancelled;
    epoch++; connected = false; busy = false; pendingTarget = null; activeTarget = null;
    settingsActive = false;
    terminalViewKey.currentState?.closeKeyboard();
    terminalFocus.unfocus();
    desktopTerminalKey.currentState?.closeKeyboard();
    desktopTerminalFocus.unfocus();
    restoreDesktopFocus = false;
    parkedDesktopScroll = null;
    if (targetScroll.hasClients) targetScroll.jumpTo(0);
    retireTerminal();
    secret.clear(); passphrase.clear();
    final credentialsCleared = secret.text.isEmpty && passphrase.text.isEmpty;
    final retiredStdout = stdout, retiredStderr = stderr;
    final session = shell, transport = client, connection = socket;
    stdout = null; stderr = null; shell = null; client = null; socket = null;
    void cancelOutput() {
      unawaited(retiredStdout?.cancel()); unawaited(retiredStderr?.cancel());
    }
    if (drainInput && session != null && transport != null && connection != null) {
      final retiringEpoch = epoch;
      unawaited(_retireActiveSession(session, transport, connection).then((outcome) {
        cancelOutput();
        // Disposing a popped route advances epoch before its retirement may finish.
        final returned = closeReturnEpoch == retiringEpoch;
        if (reportCloseOutcome && ((epoch == retiringEpoch && userDisconnected) || returned)) {
          final confirmed = outcome.localClosed && credentialsCleared;
          closeLocalConfirmed = confirmed;
          closeRemoteReported = outcome.remoteReported;
          closeCleanupFailed = !confirmed;
          final nextStatus = closeCleanupFailed ? '本机连接关闭失败；未重放输入。'
            : closeRemoteReported ? '本机已断开；远端已报告结束，凭据已清空。重连时请重新填写。'
            : '本机已断开；凭据已清空，重连时请重新填写。';
          if (mounted) setState(() => status = nextStatus); else status = nextStatus;
          if (returned) {
            closeReturnEpoch = null;
            userDisconnected = false;
            widget.onReturnAfterDisconnect?.call(confirmed);
          }
        }
      }));
    } else {
      cancelOutput();
      if (reportCloseOutcome) {
        closeLocalConfirmed = false;
        closeRemoteReported = false;
        closeCleanupFailed = true;
        status = '本机连接关闭失败；未重放输入。';
        message = null;
      }
      session?.close();
      unawaited(transport?.close().catchError((Object _, StackTrace __) {}));
      connection?.destroy();
    }
    if (message != null) status = message;
    if (notify && mounted) setState(() {});
    if (wasConnected && notify) widget.onConnectionChanged?.call(false);
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
    final desktop = desktopEntryLayout(context);
    if (desktop != hadDesktopLayout && connected) {
      if (desktop) {
        restoreDesktopTerminal();
      } else {
        parkDesktopTerminal();
      }
    }
    hadDesktopLayout = desktop;
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.desktopDestination?.removeListener(desktopDestinationChanged);
    widget.catalog?.removeListener(catalogChanged);
    secret.removeListener(credentialsChanged); passphrase.removeListener(credentialsChanged);
    stop(notify: false);
    pemFocus.removeListener(pemFocusChanged); pemFocus.dispose();
    targetScroll.dispose();
    terminalFocus.dispose();
    desktopTerminalFocus.dispose();
    desktopTerminalScroll.dispose();
    terminalFont.dispose();
    for (final field in [host, port, user, secret, passphrase]) { field.dispose(); }
    super.dispose();
  }
  Future<void> probe() async {
    if (!canProbe || !foreground) return;
    userDisconnected = false;
    resetCloseOutcome();
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
      final approved = mobileLayout || desktopEntryLayout(context)
        ? await Navigator.push<bool>(context, MaterialPageRoute(builder: (routeContext) =>
            mobileTrustPage(routeContext, originalTarget, result.$1, result.$2)))
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
    if (!valid || busy || closePending || !foreground || hostKeyReviewRequired || fingerprint == null || checkedTarget != target || secret.text.isEmpty) return;
    userDisconnected = false;
    resetCloseOutcome();
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
      observeShellEnd(localShell, generation);
      setState(() { busy = false; pendingTarget = null; activeTarget = displayTarget; connected = true; status = '已连接 · 输入直接发送到远端 shell'; });
      widget.onConnectionChanged?.call(true);
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

  bool desktopEntryLayout(BuildContext context) =>
    widget.desktopFlowShell != null && MediaQuery.sizeOf(context).width >= 700;

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
    actions: [if (showStop) TextButton(onPressed: disconnect, child: const Text('断开'))],
    leading: canGoBack ? Padding(padding: EdgeInsets.only(left: mobileMargin - 8), child: SizedBox(width: 44, height: 44,
      child: Center(child: SizedBox(width: 44, height: 44, child: MergeSemantics(child: Semantics(identifier: 'direct-back', label: '返回',
        child: Theme(data: Theme.of(context).copyWith(platform: TargetPlatform.android), child: BackButton(onPressed: onBack)))))))) : null);
  ButtonStyle get mobilePrimaryButton => FilledButton.styleFrom(textStyle: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600));
  ButtonStyle get mobileSecondaryButton => OutlinedButton.styleFrom(textStyle: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600), foregroundColor: widget.tokens.color('textPrimary'),
    side: BorderSide(color: widget.tokens.color('borderStrong')), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)));

  Widget entryList({required bool desktop, Key? key, required List<Widget> children}) => ListView(
    key: key,
    padding: EdgeInsets.fromLTRB(desktop ? 40 : mobileMargin, 20, desktop ? 40 : mobileMargin, 24),
    children: desktop ? [
      Align(alignment: Alignment.topLeft, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560),
        child: SizedBox(width: double.infinity, child: FocusTraversalGroup(policy: WidgetOrderTraversalPolicy(),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children))))),
    ] : children,
  );

  void showCatalogDestination(int index) {
    FocusScope.of(context).unfocus();
    if (busy) stop(message: '已取消，未重放操作。');
    cancelKeyPaste();
    secret.clear();
    passphrase.clear();
    widget.onSelectDestination?.call(index);
  }

  Widget desktopEntryPage({
    required String title,
    required String headerKey,
    required String backKey,
    required Widget body,
    required VoidCallback? back,
    required ValueChanged<int> selectDestination,
    bool showStop = false,
  }) => widget.desktopFlowShell!(Scaffold(body: SafeArea(child: Column(children: [
    Container(key: ValueKey(headerKey), height: mobileLargeText ? 80 : 56,
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: widget.tokens.color('border')))),
      child: Row(children: [
        SizedBox(width: back == null ? 40 : 8),
        if (back != null) ...[
          SizedBox.square(dimension: 44, child: MergeSemantics(child: Semantics(identifier: 'direct-back',
            label: '返回', child: BackButton(key: ValueKey(backKey), onPressed: back)))),
          const SizedBox(width: 12),
        ],
        Expanded(child: Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600))),
        if (showStop) TextButton(onPressed: disconnect, child: const Text('断开')),
        const SizedBox(width: 40),
      ])),
    Expanded(child: body),
  ]))), selectDestination);

  Widget mobileTrustPage(BuildContext routeContext, String originalTarget, String foundAlgorithm, String foundFingerprint) {
    final t = widget.tokens;
    final desktop = desktopEntryLayout(routeContext);
    final large = MediaQuery.textScalerOf(routeContext).scale(1) > 1;
    final evidenceRadius = BorderRadius.circular(16);
    final evidenceBorder = Border.all(color: t.color('border'));
    Widget textLabel(String text) => Text(text, style: TextStyle(fontSize: 12, color: t.color('textSecondary')));
    final evidence = large ? Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      textLabel('主机密钥算法'), SelectableText(foundAlgorithm, key: const ValueKey('direct-key-algorithm'), style: const TextStyle(fontFamily: 'ProbeNerd')),
      const Divider(), textLabel('完整 SHA256 指纹'), SelectableText(foundFingerprint, key: const ValueKey('direct-key-fingerprint'), style: const TextStyle(fontSize: 13, fontFamily: 'ProbeNerd')),
    ])) : SizedBox(height: desktop ? 122 : 120, child: Stack(children: [
      Positioned(left: 12, top: 6, child: textLabel('主机密钥算法')),
      Positioned(left: 12, right: 12, top: 24, child: SelectableText(foundAlgorithm, key: const ValueKey('direct-key-algorithm'), style: const TextStyle(fontFamily: 'ProbeNerd'))),
      Positioned(left: 12, right: 12, top: 53, child: Divider(height: 1, color: t.color('border'))),
      Positioned(left: 12, top: 57, child: textLabel('完整 SHA256 指纹')),
      Positioned(left: 12, right: 12, top: desktop ? 79 : 76, child: desktop
        ? SizedBox(key: const ValueKey('direct-key-fingerprint'), height: 34,
          child: Align(alignment: Alignment.topLeft, child: SizedBox(width: 220, child: SelectableText(foundFingerprint,
            style: const TextStyle(fontSize: 13, height: 1.3, fontFamily: 'ProbeNerd')))))
        : SelectableText(foundFingerprint, key: const ValueKey('direct-key-fingerprint'),
            style: const TextStyle(fontSize: 13, height: 1.3, fontFamily: 'ProbeNerd'))),
    ]));
    final body = entryList(desktop: desktop, children: [
        mobileTargetCard(originalTarget), const SizedBox(height: 12),
        Container(key: const ValueKey('direct-key-evidence'),
          decoration: BoxDecoration(color: t.color('card'), borderRadius: evidenceRadius, border: desktop ? null : evidenceBorder),
          foregroundDecoration: desktop ? BoxDecoration(borderRadius: evidenceRadius, border: evidenceBorder) : null,
          child: evidence),
        const SizedBox(height: 16), SizedBox(key: desktop ? const ValueKey('direct-independent-verification') : null,
          height: large ? null : 52, child: Text('请通过服务器控制台或向管理员独立核对。\n算法和完整指纹一致后，再确认继续。',
          style: TextStyle(fontSize: 13, height: 1.6, color: t.color('textSecondary')))),
        const SizedBox(height: 6), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-trust-key'),
          onPressed: () => Navigator.pop(context, true), child: const Text('指纹一致，确认继续'))),
        const SizedBox(height: 12), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-trust-cancel'),
          style: mobileSecondaryButton, onPressed: () => Navigator.pop(context, false), child: Text(hostKeyReviewRequired ? '取消核对，保留旧信任' : '取消核对'))),
      ]);
    if (!desktop) return Scaffold(appBar: mobileHeader('核对主机密钥'), body: SafeArea(child: body));
    return desktopEntryPage(title: '核对主机密钥', headerKey: 'direct-trust-header', backKey: 'direct-trust-back',
      body: body, back: () => Navigator.pop(routeContext, false), selectDestination: (index) {
        Navigator.pop(routeContext, false);
        showCatalogDestination(index);
      });
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
  ({String title, String detail}) get disconnectOutcomeCopy {
    if (closeCleanupFailed) return (title: '本机连接关闭失败', detail: '会话可能仍在。可返回首页。');
    if (!closeLocalConfirmed) return (title: '正在断开本机连接', detail: '正在关闭本机会话；未重放输入。');
    if (closeRemoteReported) return (title: '本机已断开', detail: '远端已报告结束，凭据已清空。重连时请重新填写。');
    return (title: '本机已断开', detail: '凭据已清空，重连时请重新填写。');
  }
  Widget desktopDisconnectedForm() {
    final t = widget.tokens;
    final outcome = disconnectOutcomeCopy;
    final failed = closeCleanupFailed;
    final viewportWidth = MediaQuery.sizeOf(context).width;
    final left = viewportWidth < 700 ? 16.0 : viewportWidth < 960 ? 104.0 : 264.0;
    final width = (viewportWidth - left - (viewportWidth < 700 ? 16 : 40)).clamp(0.0, 560.0);
    return ListView(key: const ValueKey('direct-form'), padding: EdgeInsets.fromLTRB(left, 20, 16, 24), children: [
      Align(alignment: Alignment.topLeft, child: SizedBox(width: width, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(key: const ValueKey('direct-closed-feedback'), height: 66, padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(color: t.color(failed ? 'dangerSoft' : 'brandSoft'), borderRadius: BorderRadius.circular(10), border: Border.all(color: t.color(failed ? 'dangerBorder' : 'brandBorder'))),
          child: Semantics(liveRegion: true, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(outcome.title, key: const ValueKey('direct-status'), style: TextStyle(color: t.color(failed ? 'dangerText' : 'brand'), fontWeight: FontWeight.bold)),
            Text(outcome.detail, style: TextStyle(fontSize: 13, color: t.color('textSecondary'))),
          ]))),
        const SizedBox(height: 16), const Text('填写连接目标', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)), const SizedBox(height: 27),
        SizedBox(height: 48, child: TextField(key: const ValueKey('direct-host'), controller: host, enabled: !closePending, decoration: const InputDecoration(labelText: '主机地址'))),
        const SizedBox(height: 36), Row(children: [
          Expanded(child: SizedBox(height: 48, child: TextField(key: const ValueKey('direct-user'), controller: user, enabled: !closePending, decoration: const InputDecoration(labelText: '用户名')))),
          const SizedBox(width: 12), SizedBox(width: 84, height: 48, child: TextField(key: const ValueKey('direct-port'), controller: port, enabled: !closePending, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: '端口'))),
        ]),
        const SizedBox(height: 20), SizedBox(height: 48, child: FilledButton(key: const ValueKey('direct-probe'), onPressed: canProbe ? probe : null, child: const Text('探测并核对主机密钥'))),
        const SizedBox(height: 36), SizedBox(height: 48, child: OutlinedButton(key: const ValueKey('direct-return-home'), onPressed: returnAfterDisconnect, child: const Text('返回首页'))),
      ]))),
    ]);
  }
  Widget mobileTargetForm({bool desktop = false}) {
    final outcome = disconnectOutcomeCopy;
    final failed = closeCleanupFailed;
    final minFeedbackHeight = !desktop && closeLocalConfirmed && closeRemoteReported &&
        MediaQuery.sizeOf(context).width < 360 ? 84.0 : 66.0;
    return entryList(desktop: desktop, key: const ValueKey('direct-form'), children: [
    if (userDisconnected && !busy) ...[
      Container(key: const ValueKey('direct-closed-feedback'), constraints: BoxConstraints(minHeight: minFeedbackHeight),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: widget.tokens.color(failed ? 'dangerSoft' : 'brandSoft'), borderRadius: BorderRadius.circular(10),
          border: Border.all(color: widget.tokens.color(failed ? 'dangerBorder' : 'brandBorder'))),
        child: Semantics(liveRegion: true, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(outcome.title, key: const ValueKey('direct-status'), style: TextStyle(color: widget.tokens.color(failed ? 'dangerText' : 'brand'), fontWeight: FontWeight.bold)),
          Text(outcome.detail, style: TextStyle(fontSize: 13, color: widget.tokens.color('textSecondary'))),
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
    mobileField('主机地址', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-host'), controller: host, enabled: !busy && !closePending,
      decoration: mobileInput('ssh.example.test')))),
    const SizedBox(height: 14),
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: mobileField('用户名', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-user'), controller: user, enabled: !busy && !closePending,
        decoration: mobileInput('demo'))))),
      const SizedBox(width: 12), SizedBox(width: 84, child: mobileField('端口', SizedBox(height: mobileInputHeight, child: TextField(key: const ValueKey('direct-port'),
        controller: port, enabled: !busy && !closePending, keyboardType: TextInputType.number,
        inputFormatters: desktop ? [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(5)] : null,
        decoration: mobileInput('22'))))),
    ]),
    const SizedBox(height: 20), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-probe'),
      onPressed: canProbe ? probe : null, child: const Text('探测并核对主机密钥'))),
    const SizedBox(height: 9), Text('探测时仅获取主机密钥，认证在核对之后进行。',
      style: TextStyle(fontSize: 12, color: widget.tokens.color('textMutedReadable'))),
    if (userDisconnected) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(
      key: const ValueKey('direct-return-home'), style: mobileSecondaryButton, onPressed: returnAfterDisconnect, child: const Text('返回首页')))],
    if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
    ]);
  }
  Widget mobileAuthForm({bool desktop = false}) {
    final t = widget.tokens;
    final credentialEnabled = !busy && !hostKeyReviewRequired;
    final nativeCredentials = desktop && !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS;
    const passwordLabel = '密码（仅本次使用）', passphraseLabel = '私钥口令（加密私钥需要）';
    Widget credential(String id, String label, TextEditingController controller, {required double height, bool pem = false}) {
      if (nativeCredentials && !pem) {
        return ConstrainedBox(constraints: BoxConstraints(minHeight: height), child: MacosSecureCredentialField(
          key: ValueKey(id), controller: controller,
          enabled: credentialEnabled, label: label, identifier: id,
          onNativeFocus: id == 'direct-passphrase' ? blurPemForNativePassphrase : null,
          decoration: mobileInput('').copyWith(contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3))));
      }
      if (pem && pemCollapsed) return SizedBox(height: height, child: collapsedPem(enabled: credentialEnabled));
      return SizedBox(height: height, child: TextField(key: ValueKey(id), controller: controller, focusNode: pem ? pemFocus : null, onTapOutside: pem ? (_) => pemFocus.unfocus() : null, enabled: credentialEnabled,
        obscureText: !pem, minLines: pem ? 2 : 1, maxLines: pem ? 2 : 1,
        decoration: mobileInput(pem ? '粘贴已有私钥的完整 PEM' : '未填写')));
    }
    Widget choice(String text, bool value) => Expanded(child: SizedBox(height: mobileLargeText ? 60 : 44, child: OutlinedButton(
      key: ValueKey(value ? 'direct-auth-key' : 'direct-auth-password'),
      style: OutlinedButton.styleFrom(backgroundColor: t.color(keyAuth == value ? 'brandSoft' : 'card'),
        foregroundColor: t.color(keyAuth == value ? 'brand' : 'textSecondary'),
        side: BorderSide(color: t.color(keyAuth == value ? 'brand' : 'borderStrong')),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
      onPressed: busy || hostKeyReviewRequired ? null : () { if (keyAuth == value) return; setState(() { cancelKeyPaste(); keyAuth = value; secret.clear(); passphrase.clear(); }); },
      child: Text(text))));
    return entryList(desktop: desktop, key: const ValueKey('direct-form'), children: [
      mobileTargetCard(checkedTarget ?? target), const SizedBox(height: 10),
      Container(key: desktop ? const ValueKey('direct-trust-approved') : null,
        height: 44, padding: const EdgeInsets.symmetric(horizontal: 12), alignment: Alignment.centerLeft,
        decoration: BoxDecoration(color: t.color('successSoft'), borderRadius: BorderRadius.circular(10), border: Border.all(color: t.color('successBorder'))),
        child: Text('本次主机密钥已确认', style: TextStyle(color: t.color('successText'), fontWeight: FontWeight.bold))),
      if (status != '已确认本次主机密钥；连接时将重新核对。') ...[const SizedBox(height: 10), Semantics(liveRegion: true, child: Text(status, key: const ValueKey('direct-status')))],
      SizedBox(height: MediaQuery.sizeOf(context).width < 360 ? 12 : 20),
      SizedBox(height: desktop && !mobileLargeText ? 18 : null,
        child: const Text('认证方式', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold))),
      const SizedBox(height: 4),
      Row(children: [choice('密码', false), const SizedBox(width: 8), choice('已有私钥', true)]), const SizedBox(height: 14),
      mobileField(keyAuth ? '私钥 PEM（仅本次使用）' : passwordLabel,
        credential('direct-secret', passwordLabel, secret, pem: keyAuth,
          height: keyAuth ? (mobileLargeText ? 110 : MediaQuery.sizeOf(context).width < 360 ? 68 : 84) : mobileInputHeight)),
      if (keyAuth) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-paste-key'),
        style: mobileSecondaryButton, onPressed: busy || pastingKey || !foreground || hostKeyReviewRequired ? null : pastePrivateKey, child: const Text('粘贴私钥'))),
        // Keep the credential field and button at the same sliver indices.
        pasteStatus == null ? const SizedBox.shrink()
          : Semantics(liveRegion: true, child: Text(pasteStatus!, key: const ValueKey('direct-paste-status'))),
        const SizedBox(height: 12), mobileField(passphraseLabel,
          credential('direct-passphrase', passphraseLabel, passphrase, height: mobileInputHeight)),
      ],
      const SizedBox(height: 14), SizedBox(height: mobileButtonHeight, child: FilledButton(style: mobilePrimaryButton, key: const ValueKey('direct-connect'),
        onPressed: canConnect ? connect : null, child: const Text('连接 SSH'))),
      const SizedBox(height: 16), Text(keyAuth ? '填写完整私钥后才能连接。' : '断开或取消后，本次密码会清空。',
        style: TextStyle(fontSize: 12, color: t.color('textMutedReadable'))),
      if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
    ]);
  }
  Widget mobileHostKeyChangeView({bool desktop = false}) {
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
    return entryList(desktop: desktop, key: const ValueKey('direct-host-key-change'), children: [
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
                  onPressed: disconnect,
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

  Widget desktopActivePage() {
    final tokens = widget.tokens;
    return widget.desktopFlowShell!(Scaffold(body: SafeArea(child: Column(children: [
      Container(key: const ValueKey('direct-live-header'), height: 56, width: double.infinity,
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: tokens.color('border')))),
        child: Stack(children: [
          Positioned.fill(left: 40, right: 124, child: Align(alignment: Alignment.centerLeft,
            child: Text(settingsActive ? '设置' : '普通 SSH',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)))),
          if (!settingsActive)
            Positioned(top: 4, right: 40, width: 76, height: 44, child: TextButton(
              key: const ValueKey('direct-desktop-disconnect'),
              style: TextButton.styleFrom(foregroundColor: tokens.color('dangerText'),
                backgroundColor: tokens.color('dangerSoft'), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
              onPressed: disconnect, child: const Text('断开'))),
        ])),
      Expanded(child: IndexedStack(index: settingsActive ? 1 : 0, sizing: StackFit.expand, children: [
        ExcludeFocus(excluding: settingsActive, child: desktopTerminalWorkspace()),
        ExcludeFocus(excluding: !settingsActive, child: mobileActiveSettings(desktop: true)),
      ])),
    ]))), selectDesktopDestination, settingsActive ? 3 : 1);
  }

  Widget desktopTerminalWorkspace() {
    final tokens = widget.tokens;
    return LayoutBuilder(builder: (context, available) => SingleChildScrollView(primary: false, child: SizedBox(
      height: available.maxHeight < 152 ? 152 : available.maxHeight,
      child: Padding(padding: const EdgeInsets.fromLTRB(40, 12, 40, 16), child: Column(children: [
        SizedBox(key: const ValueKey('direct-terminal-status'), height: 44,
          child: Semantics(label: status, child: Row(children: [
            Container(width: 62, height: 24, alignment: Alignment.center,
              decoration: BoxDecoration(color: tokens.color('successSoft'), borderRadius: BorderRadius.circular(8),
                border: Border.all(color: tokens.color('successBorder'))),
              child: Text('已连接', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: tokens.color('successText')))),
            const SizedBox(width: 10),
            Expanded(child: SingleChildScrollView(key: const ValueKey('direct-target-scroll'), controller: targetScroll,
              scrollDirection: Axis.horizontal, child: Text(activeTarget ?? '', key: const ValueKey('direct-active-target'),
                maxLines: 1, softWrap: false, style: const TextStyle(fontSize: 12, fontFamily: 'ProbeNerd')))),
          ]))),
        const SizedBox(height: 8),
        Expanded(
          child: Container(
            key: const ValueKey('direct-terminal-panel'),
            foregroundDecoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: tokens.color('termBorder')),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: RawScrollbar(
                key: const ValueKey('direct-terminal-scrollbar'),
                controller: desktopTerminalScroll,
                thumbVisibility: true,
                trackVisibility: true,
                interactive: true,
                scrollbarOrientation: ScrollbarOrientation.right,
                thickness: 6,
                minThumbLength: 40,
                radius: const Radius.circular(3),
                trackRadius: const Radius.circular(3),
                trackColor: tokens.color('cardSubtle'),
                thumbColor: tokens.color('textSecondary'),
                padding: const EdgeInsets.fromLTRB(0, 4, 4, 4),
                child: ScrollConfiguration(
                  behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
                  child: TerminalView(
                    terminal!,
                    key: desktopTerminalKey,
                    focusNode: desktopTerminalFocus,
                    scrollController: desktopTerminalScroll,
                    theme: tokens.terminalTheme,
                    padding: const EdgeInsets.fromLTRB(12, 12, 16, 12),
                    textStyle: TerminalStyle(
                      fontFamily: 'ProbeNerd',
                      height: 20 / 14,
                      fontSize: (widget.catalog?.terminalFontSize ?? 14).toDouble(),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ])),
    )));
  }

  Widget mobileActiveSettings({bool desktop = false}) {
    final t = widget.tokens;
    final catalog = widget.catalog;
    return entryList(desktop: desktop,
      key: const ValueKey('direct-settings'),
      children: [
        Container(
          key: const ValueKey('direct-settings-active'),
          constraints: BoxConstraints(minHeight: desktop ? 66 : 44),
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: t.color('successSoft'),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: t.color('successBorder')),
          ),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('普通 SSH 会话保持连接', style: TextStyle(color: t.color('successText'), fontWeight: FontWeight.bold)),
            if (desktop) Text('切到看板、网络或设置不会断开；显式断开后才结束。',
              style: TextStyle(fontSize: 13, color: t.color('textSecondary'))),
          ]),
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
                        tabs: widget.catalogTabs,
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
  void backFromDesktopEntry() {
    if (mobileAuth && !hostKeyReviewRequired) {
      backFromMobileAuth();
    } else {
      Navigator.pop(context, DirectSshRouteExit.targetBack);
    }
  }

  @override
  Widget build(BuildContext context) {
    final desktopEntry = desktopEntryLayout(context) && !connected && !userDisconnected;
    final desktopActive = desktopEntryLayout(context) && connected && widget.onSelectDestination != null;
    final authenticating = mobileAuth && !hostKeyReviewRequired;
    return PopScope(
    canPop: hostKeyChange == null && !settingsActive && !desktopEntry && !desktopActive,
    onPopInvokedWithResult: (didPop, result) {
      if (!didPop && settingsActive && connected) {
        if (desktopActive) {
          selectDesktopDestination(1);
        } else {
          selectMobileTerminal(false);
        }
      }
      if (!didPop && desktopEntry && hostKeyChange == null) backFromDesktopEntry();
      if (didPop && busy) stop(notify: false);
      if (didPop && userDisconnected) {
        if (closeCleanupFailed || closeLocalConfirmed) {
          final confirmed = closeLocalConfirmed;
          userDisconnected = false;
          widget.onReturnAfterDisconnect?.call(confirmed);
        } else {
          closeReturnEpoch = epoch;
        }
      }
    },
    child: desktopActive ? desktopActivePage() : desktopEntry ? desktopEntryPage(
      title: hostKeyChange != null ? '主机指纹发生变化' : authenticating ? 'SSH 账号认证' : '普通 SSH',
      headerKey: 'direct-page-header', backKey: 'direct-back-hit',
      body: hostKeyChange != null ? mobileHostKeyChangeView(desktop: true)
        : authenticating ? mobileAuthForm(desktop: true) : mobileTargetForm(desktop: true),
      back: hostKeyChange == null ? backFromDesktopEntry : null,
      selectDestination: showCatalogDestination,
      showStop: busy,
    ) : Scaffold(
      bottomNavigationBar: mobileLayout && connected && MediaQuery.viewInsetsOf(context).bottom == 0 ? mobileConnectedNavigation() : null,
      appBar: mobileLayout && connected ? mobileActiveHeader() : mobileLayout && !connected ? mobileHeader(hostKeyChange != null ? '主机指纹发生变化' : mobileAuth && !hostKeyReviewRequired ? 'SSH 账号认证' : '普通 SSH',
        canGoBack: hostKeyChange == null && (ModalRoute.of(context)?.impliesAppBarDismissal ?? false), showStop: busy, onBack: mobileAuth && !hostKeyReviewRequired ? backFromMobileAuth
          : userDisconnected ? returnAfterDisconnect : null)
        : AppBar(title: const Text('普通 SSH'),
      automaticallyImplyLeading: hostKeyChange == null,
      leading: hostKeyChange == null && (ModalRoute.of(context)?.impliesAppBarDismissal ?? false)
        ? MergeSemantics(child: Semantics(identifier: 'direct-back', label: '返回主机列表', child: BackButton(onPressed: mobileLayout && mobileAuth && !connected
          ? backFromMobileAuth : null))) : null,
      actions: [if (busy || connected) TextButton(onPressed: disconnect, child: const Text('断开'))]),
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
    ])))) : userDisconnected && !mobileLayout ? desktopDisconnectedForm() : mobileLayout ? (mobileAuth && !hostKeyReviewRequired ? mobileAuthForm() : mobileTargetForm()) : ListView(key: const ValueKey('direct-form'), padding: const EdgeInsets.all(16), children: [
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
          OutlinedButton(key: const ValueKey('direct-probe'), onPressed: canProbe ? probe : null, child: const Text('探测并核对主机密钥')),
          if (fingerprint != null) ...[
            const SizedBox(height: 12),
            SelectableText('$algorithm · $fingerprint'),
          ],
          const SizedBox(height: 16),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('使用私钥认证'), value: keyAuth,
            onChanged: busy || hostKeyReviewRequired ? null : (value) { if (keyAuth == value) return; setState(() { cancelKeyPaste(); keyAuth = value; secret.clear(); passphrase.clear(); }); }),
          const SizedBox(height: 12),
          Semantics(container: true, explicitChildNodes: true, label: keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）',
            child: pemCollapsed ? SizedBox(height: pemEditorHeight, child: collapsedPem(enabled: !busy && !hostKeyReviewRequired)) : !keyAuth && !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS
              ? MacosSecureCredentialField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy && !hostKeyReviewRequired,
                  label: '密码（仅本次使用）', identifier: 'direct-secret')
              : KeyedSubtree(key: keyAuth ? pemLayoutKey : null, child: TextField(key: const ValueKey('direct-secret'), controller: secret, focusNode: keyAuth ? pemFocus : null, onTapOutside: keyAuth ? (_) => pemFocus.unfocus() : null, enabled: !busy && !hostKeyReviewRequired, obscureText: !keyAuth,
              minLines: keyAuth ? 2 : 1, maxLines: keyAuth ? 2 : 1, decoration: InputDecoration(label: ExcludeSemantics(child: Text(keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）')))))),
          if (keyAuth) ...[
            TextButton(key: const ValueKey('direct-paste-key'), onPressed: busy || pastingKey || !foreground || hostKeyReviewRequired ? null : pastePrivateKey,
              child: const Text('粘贴私钥')),
            if (pasteStatus != null) Semantics(liveRegion: true, child: Text(pasteStatus!, key: const ValueKey('direct-paste-status'))),
            const SizedBox(height: 16),
            Semantics(container: true, explicitChildNodes: true, label: '私钥口令（可选）',
              child: !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS
                ? MacosSecureCredentialField(key: const ValueKey('direct-passphrase'), controller: passphrase, enabled: !busy && !hostKeyReviewRequired,
                    label: '私钥口令（可选）', identifier: 'direct-passphrase', onNativeFocus: blurPemForNativePassphrase)
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
}
