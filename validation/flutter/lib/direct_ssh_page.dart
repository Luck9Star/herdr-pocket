import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:terminal_view/terminal_view.dart';
import 'design_tokens.dart';

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
  final terminal = Terminal(maxLines: 2000);
  SSHSocket? socket;
  SSHClient? client;
  SSHSession? shell;
  StreamSubscription<String>? stdout, stderr;
  int epoch = 0;
  String? fingerprint, algorithm, checkedTarget;
  String status = '填写连接信息后先探测主机密钥。';
  bool busy = false, connected = false, keyAuth = false, foreground = true;
  String get target => '${user.text.trim()}@${host.text.trim()}:${port.text.trim()}';
  bool get valid => host.text.trim().isNotEmpty && user.text.trim().isNotEmpty &&
      (int.tryParse(port.text.trim()) ?? 0) > 0 && (int.tryParse(port.text.trim()) ?? 65536) <= 65535;

  @override
  void initState() {
    super.initState(); WidgetsBinding.instance.addObserver(this);
    for (final field in [host, port, user]) { field.addListener(changed); }
    terminal.onOutput = (data) {
      final current = shell;
      if (foreground && connected && current != null) current.write(Uint8List.fromList(utf8.encode(data)));
    };
    terminal.onResize = (cols, rows, px, py) {
      if (foreground && connected) shell?.resizeTerminal(cols, rows, px, py);
    };
  }
  void changed() {
    if (checkedTarget != target) { fingerprint = null; algorithm = null; checkedTarget = null; secret.clear(); passphrase.clear(); }
    if (mounted) setState(() {});
  }
  void stop({String? message, bool notify = true}) {
    epoch++; connected = false; busy = false;
    secret.clear(); passphrase.clear();
    unawaited(stdout?.cancel()); unawaited(stderr?.cancel()); stdout = null; stderr = null;
    shell?.close(); shell = null; client?.close(); client = null; socket?.destroy(); socket = null;
    if (message != null) status = message;
    if (notify && mounted) setState(() {});
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    if (!foreground && (connected || busy)) stop(message: '应用进入后台，连接已关闭；返回后需重新连接，不会重放输入。');
  }
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this); stop(notify: false); terminal.dispose();
    for (final field in [host, port, user, secret, passphrase]) { field.dispose(); }
    super.dispose();
  }
  Future<void> probe() async {
    if (!valid || busy || !foreground) return;
    stop(); final generation = ++epoch; final originalTarget = target;
    setState(() { busy = true; status = '正在探测主机密钥，尚未发送认证信息。'; fingerprint = null; });
    SSHSocket? localSocket; SSHClient? localClient;
    try {
      localSocket = await SSHSocket.connect(host.text.trim(), int.parse(port.text.trim()), timeout: const Duration(seconds: 8));
      if (generation != epoch) { localSocket.destroy(); return; }
      socket = localSocket;
      final found = Completer<(String, String)>();
      localClient = SSHClient(localSocket, username: user.text.trim(), keepAliveInterval: null,
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
        actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(key: const ValueKey('direct-trust-key'), onPressed: () => Navigator.pop(context, true), child: const Text('已核对并确认'))]));
      if (generation != epoch || originalTarget != target || !mounted) return;
      setState(() { busy = false; if (approved == true) { algorithm = result.$1; fingerprint = result.$2; checkedTarget = originalTarget; status = '已确认本次主机密钥；连接时将重新核对。'; } else { status = '未确认主机密钥，未发送认证。'; } });
    } catch (_) {
      if (generation == epoch && mounted) { stop(message: '探测失败或超时；未发送认证，请检查目标后重试。'); }
    } finally { if (generation != epoch) { localClient?.close(); localSocket?.destroy(); } }
  }
  Future<void> connect() async {
    if (!valid || busy || !foreground || fingerprint == null || checkedTarget != target || secret.text.isEmpty) return;
    final generation = ++epoch, expected = fingerprint!, expectedAlgorithm = algorithm!;
    final password = keyAuth ? null : secret.text;
    final keyText = keyAuth ? secret.text : null, phrase = passphrase.text;
    secret.clear(); passphrase.clear();
    terminal.fullReset();
    setState(() { busy = true; status = '正在重新核对主机密钥并连接…'; });
    var keyMismatch = false;
    try {
      final identities = keyText == null ? null : SSHKeyPair.fromPem(keyText, phrase.isEmpty ? null : phrase);
      final localSocket = await SSHSocket.connect(host.text.trim(), int.parse(port.text.trim()), timeout: const Duration(seconds: 8));
      if (generation != epoch) { localSocket.destroy(); return; }
      socket = localSocket; bool verified = false;
      final localClient = SSHClient(localSocket, username: user.text.trim(), identities: identities,
        onPasswordRequest: password == null ? null : () => verified && generation == epoch ? password : null,
        onVerifyHostKey: (type, bytes) {
          verified = generation == epoch && type == expectedAlgorithm && utf8.decode(bytes) == expected;
          keyMismatch = generation == epoch && !verified;
          return verified;
        },
        keepAliveInterval: null, handshakeTimeout: const Duration(seconds: 8), authTimeout: const Duration(seconds: 8));
      client = localClient;
      unawaited(localClient.done.then<void>((_) {}, onError: (Object _, StackTrace __) {}));
      await localClient.authenticated.timeout(const Duration(seconds: 12));
      if (generation != epoch || !verified) return;
      final pendingShell = localClient.shell(pty: SSHPtyConfig(width: terminal.viewWidth, height: terminal.viewHeight));
      unawaited(pendingShell.then<void>((value) { if (generation != epoch) value.close(); }, onError: (Object _, StackTrace __) {}));
      final localShell = await pendingShell.timeout(const Duration(seconds: 12));
      if (generation != epoch) { localShell.close(); return; }
      shell = localShell;
      stdout = localShell.stdout.cast<List<int>>().transform(const Utf8Decoder(allowMalformed: true)).listen((text) { if (generation == epoch) terminal.write(text); }, onError: (_) { if (generation == epoch) stop(message: '终端输出错误，连接已关闭。'); });
      stderr = localShell.stderr.cast<List<int>>().transform(const Utf8Decoder(allowMalformed: true)).listen((text) { if (generation == epoch) terminal.write(text); }, onError: (_) { if (generation == epoch) stop(message: '终端输出错误，连接已关闭。'); });
      unawaited(localShell.done.then((_) { if (generation == epoch) stop(message: '远端 shell 已结束（退出码 ${localShell.exitCode ?? '未知'}）。'); }, onError: (Object _, StackTrace __) { if (generation == epoch) stop(message: '连接中断，输入已停止。'); }));
      setState(() { busy = false; connected = true; status = '已连接 · 输入直接发送到远端 shell'; });
    } catch (error) { if (generation == epoch) stop(message: keyMismatch ? '主机密钥不符，已阻止认证；请重新核对。' : error is SSHAuthFailError ? '认证失败，请检查凭据。' : '连接失败或超时，请检查网络、密钥与目标。'); }
  }
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('普通 SSH'), actions: [if (busy || connected) TextButton(onPressed: () => stop(message: '已断开；未重放输入。'), child: const Text('断开'))]),
    body: SafeArea(child: connected ? Column(children: [
      Padding(padding: const EdgeInsets.all(8), child: Text(status)),
      Expanded(child: TerminalView(terminal, theme: widget.tokens.terminalTheme, autoResize: true,
        textStyle: const TerminalStyle(fontFamily: 'ProbeNerd', fontSize: 14))),
      SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
        for (final item in {'Esc':'\u001b', 'Tab':'\t', '↑':'\u001b[A', '↓':'\u001b[B', '←':'\u001b[D', '→':'\u001b[C', 'Ctrl-C':'\u0003', 'Ctrl-D':'\u0004', 'Enter':'\r'}.entries)
          TextButton(onPressed: () { if (foreground && connected) shell?.write(Uint8List.fromList(utf8.encode(item.value))); }, child: Text(item.key)),
      ])),
    ]) : ListView(key: const ValueKey('direct-form'), padding: const EdgeInsets.all(16), children: [
      Text(status, key: const ValueKey('direct-status')),
      TextField(key: const ValueKey('direct-host'), controller: host, enabled: !busy, decoration: const InputDecoration(labelText: '地址')),
      TextField(key: const ValueKey('direct-port'), controller: port, enabled: !busy, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: '端口')),
      TextField(key: const ValueKey('direct-user'), controller: user, enabled: !busy, decoration: const InputDecoration(labelText: '用户名')),
      const SizedBox(height: 8),
      OutlinedButton(key: const ValueKey('direct-probe'), onPressed: valid && !busy ? probe : null, child: const Text('探测并核对主机密钥')),
      if (fingerprint != null) SelectableText('$algorithm · $fingerprint'),
      SwitchListTile(title: const Text('使用私钥认证'), value: keyAuth, onChanged: busy ? null : (value) => setState(() { keyAuth = value; secret.clear(); passphrase.clear(); })),
      TextField(key: const ValueKey('direct-secret'), controller: secret, enabled: !busy, obscureText: !keyAuth,
        minLines: 1, maxLines: keyAuth ? 6 : 1, decoration: InputDecoration(labelText: keyAuth ? '私钥 PEM（仅本次使用）' : '密码（仅本次使用）')),
      if (keyAuth) TextField(key: const ValueKey('direct-passphrase'), controller: passphrase, enabled: !busy, obscureText: true, decoration: const InputDecoration(labelText: '私钥口令（可选）')),
      FilledButton(key: const ValueKey('direct-connect'), onPressed: !busy && fingerprint != null ? connect : null, child: const Text('连接 SSH')),
      if (busy) TextButton(onPressed: () => stop(message: '已取消，未重放操作。'), child: const Text('取消')),
    ])),
  );
}
