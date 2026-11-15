import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:dartssh2/dartssh2.dart' show SSHClient, SSHSession;
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/macos_secure_credential_field.dart';
import 'package:terminal_view/terminal_view.dart';

void portableTestWidgets(String description, WidgetTesterCallback callback, {bool? skip}) => testWidgets(
  description, callback, skip: skip, variant: TargetPlatformVariant.only(TargetPlatform.android));

Future<void> waitFor(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 120 && finder.evaluate().isEmpty; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pump();
  }
  expect(finder, findsOneWidget);
}

Future<void> pumpOrdinaryHome(WidgetTester tester, DesignTokens tokens) => tester.pumpWidget(
  MaterialApp(theme: tokens.theme, home: Builder(builder: (context) => Scaffold(
    body: FilledButton(onPressed: () => Navigator.push<void>(context, MaterialPageRoute<void>(
      builder: (_) => DirectSshPage(tokens: tokens))), child: const Text('Open ordinary SSH'))))));

void mockSecureFields(WidgetTester tester) {
  final messenger = tester.binding.defaultBinaryMessenger;
  final nativeIds = <int>[];
  messenger.setMockMethodCallHandler(SystemChannels.platform_views, (call) async {
    if (call.method == 'create') {
      final id = (call.arguments as Map)['id'] as int;
      nativeIds.add(id);
      messenger.setMockMethodCallHandler(MethodChannel('herdr.pocket/secure-field/$id'), (_) async => null);
    }
    return null;
  });
  addTearDown(() {
    messenger.setMockMethodCallHandler(SystemChannels.platform_views, null);
    for (final id in nativeIds) messenger.setMockMethodCallHandler(MethodChannel('herdr.pocket/secure-field/$id'), null);
  });
}

void mockClipboard(WidgetTester tester, Future<Object?> Function() read) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
    if (call.method == 'Clipboard.getData') { expect(call.arguments, 'text/plain'); return read(); }
    return null;
  });
  addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
}

Future<void> enableKeyMode(WidgetTester tester) async {
  await tester.ensureVisible(find.byType(SwitchListTile));
  await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
}

Future<void> tapPasteKey(WidgetTester tester) async {
  final button = find.byKey(const ValueKey('direct-paste-key'));
  await tester.ensureVisible(button); await tester.pumpAndSettle(); await tester.tap(button); await tester.pump();
}

class CapturingShell extends Fake implements SSHSession {
  final writes = <String>[];
  int resizes = 0;
  @override void write(Uint8List bytes) { writes.add(utf8.decode(bytes)); }
  @override void resizeTerminal(int cols, int rows, [int width = 0, int height = 0]) { resizes++; }
  @override void close() {}
}

void main() {
  const clipboardPem = '-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-body\n-----END OPENSSH PRIVATE KEY-----\n';
  testWidgets('explicit private key paste preserves multiline text and exposes an accessible button', (tester) async {
    mockSecureFields(tester);
    final semantics = tester.ensureSemantics();
    var reads = 0;
    mockClipboard(tester, () async { reads++; return {'text': clipboardPem}; });
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    expect(find.text('粘贴私钥'), findsNothing); expect(reads, 0);
    await enableKeyMode(tester);
    expect(reads, 0);
    final data = tester.getSemantics(find.bySemanticsLabel('粘贴私钥')).getSemanticsData();
    expect(data.flagsCollection.isButton, isTrue); expect(data.hasAction(SemanticsAction.tap), isTrue);
    await tapPasteKey(tester); await tester.pump();
    expect(reads, 1);
    final field = tester.widget<TextField>(find.byKey(const ValueKey('direct-secret')));
    expect(field.controller!.text, clipboardPem);
    expect(field.controller!.selection.baseOffset, clipboardPem.length);
    expect(tester.widget<Text>(find.byKey(const ValueKey('direct-paste-status'))).data, '私钥已粘贴，仅本次使用。');
    expect(tester.takeException(), isNull); semantics.dispose();
  }, variant: TargetPlatformVariant({TargetPlatform.android, TargetPlatform.macOS}));

  for (final outcome in ['empty', 'denied']) {
    portableTestWidgets('private key paste $outcome preserves manual input without exposing errors', (tester) async {
      mockClipboard(tester, () async {
        if (outcome == 'denied') throw PlatformException(code: 'denied', message: clipboardPem);
        return {'text': ' \n'};
      });
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
      await enableKeyMode(tester);
      await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'manual-key');
      await tapPasteKey(tester); await tester.pump();
      expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).controller!.text, 'manual-key');
      final message = tester.widget<Text>(find.byKey(const ValueKey('direct-paste-status'))).data!;
      expect(message, outcome == 'empty' ? '剪贴板中没有可粘贴的文本。' : '无法读取剪贴板，请重试或手动输入私钥。');
      expect(message.contains(clipboardPem), isFalse); expect(tester.takeException(), isNull);
    });
  }

  for (final change in ['target', 'mode', 'manual', 'background', 'route', 'dispose']) {
    portableTestWidgets('late private key paste is cancelled by $change', (tester) async {
      final pending = Completer<Object?>();
      mockClipboard(tester, () => pending.future);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await pumpOrdinaryHome(tester, tokens);
      await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
      await enableKeyMode(tester);
      final key = find.byKey(const ValueKey('direct-secret'));
      await tester.enterText(key, 'existing-key');
      await tapPasteKey(tester);
      expect(tester.widget<TextButton>(find.byKey(const ValueKey('direct-paste-key'))).onPressed, isNull);
      var expected = 'existing-key';
      switch (change) {
        case 'target': await tester.enterText(find.byKey(const ValueKey('direct-host')), 'changed.invalid'); expected = ''; break;
        case 'mode': await enableKeyMode(tester); expected = ''; break;
        case 'manual': await tester.enterText(key, 'typed-after-paste'); expected = 'typed-after-paste'; break;
        case 'background':
          tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
          tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
          break;
        case 'route':
          unawaited(Navigator.of(tester.element(find.byType(DirectSshPage))).push<void>(MaterialPageRoute<void>(
            builder: (_) => const Scaffold(body: Text('covered')))));
          await tester.pumpAndSettle();
          Navigator.of(tester.element(find.text('covered'))).pop(); await tester.pumpAndSettle();
          break;
        case 'dispose':
          await tester.tap(find.byType(BackButton)); await tester.pumpAndSettle();
          await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle(); expected = '';
          break;
      }
      pending.complete({'text': clipboardPem}); await tester.pump(); await tester.pump();
      expect(tester.widget<TextField>(key).controller!.text, expected);
      expect(find.byKey(const ValueKey('direct-paste-status')), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  portableTestWidgets('ordinary SSH replaces parser state and rejects retired output and resize callbacks', (tester) async {
    tester.view.physicalSize = const Size(800, 1000); tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final server = (await tester.runAsync(() => ServerSocket.bind(InternetAddress.loopbackIPv4, 0)))!;
    final sockets = <Socket>[];
    final listener = server.listen(sockets.add);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    try {
      state.terminal ??= state.createTerminal(state.epoch);
      await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
      await tester.enterText(find.byKey(const ValueKey('direct-port')), '${server.port}');
      await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
      // Seed only the already-reviewed pin; the real connect button starts a
      // new attempt against a temporary TCP listener that never authenticates.
      state.fingerprint = 'SHA256:synthetic'; state.algorithm = 'ssh-ed25519'; state.checkedTarget = state.target;
      await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'synthetic-password'); await tester.pump();
      final Terminal previous = state.terminal;
      previous.write('\x1b[31');
      final previousOutput = previous.onOutput!, previousResize = previous.onResize!;
      await tester.ensureVisible(find.byKey(const ValueKey('direct-connect'))); await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
      final Terminal current = state.terminal;
      current.write('mZ'); expect(current.buffer.getText().trimRight(), 'mZ');
      expect(identical(previous, current), isFalse);
      expect(previous.onOutput, isNull); expect(previous.onResize, isNull);
      current.write('\x1b[31'); current.write('mC');
      expect(current.buffer.getText().trimRight(), 'mZC', reason: 'same-session CSI chunks still continue');
      final nextShell = CapturingShell(); state.shell = nextShell; state.connected = true;
      previousOutput('retired'); previousResize(100, 30, 0, 0);
      expect(nextShell.writes, isEmpty); expect(nextShell.resizes, 0);
      current.textInput('current'); current.onResize!(100, 30, 0, 0);
      expect(nextShell.writes, ['current']); expect(nextShell.resizes, 1);
    } finally {
      state.stop(); await tester.pump();
      expect(state.terminal, isNull);
      for (final socket in sockets) { socket.destroy(); }
      await tester.runAsync(() async { await listener.cancel(); await server.close(); });
    }
    expect(tester.takeException(), isNull);
  });

  portableTestWidgets('ordinary SSH arrow buttons follow remote cursor-key mode', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    final shell = CapturingShell();
    state.setState(() { state.terminal = state.createTerminal(state.epoch); state.shell = shell; state.connected = true; }); await tester.pump();
    final Terminal terminal = state.terminal;
    final oldButtons = [for (final label in ['Esc', 'Tab', '↑', '↓', '←', '→', 'Ctrl-C', 'Ctrl-D', 'Enter'])
      tester.widget<TextButton>(find.widgetWithText(TextButton, label)).onPressed!];
    for (final mode in [false, true, false]) {
      terminal.write(mode ? '\x1b[?1h' : '\x1b[?1l');
      for (final label in ['↑', '↓', '←', '→']) { await tester.tap(find.text(label)); }
      expect(shell.writes.sublist(shell.writes.length - 4),
        mode ? ['\x1bOA', '\x1bOB', '\x1bOD', '\x1bOC'] : ['\x1b[A', '\x1b[B', '\x1b[D', '\x1b[C']);
    }
    await tester.tap(find.text('Ctrl-C')); expect(shell.writes.last, '\x03');
    state.stop(); expect(state.terminal, isNull);
    final nextShell = CapturingShell();
    state.setState(() { state.terminal = state.createTerminal(state.epoch); state.shell = nextShell; state.connected = true; }); await tester.pump();
    for (final pressed in oldButtons) { pressed(); }
    expect(nextShell.writes, isEmpty, reason: 'retired helper buttons cannot address a new session');
    await tester.tap(find.text('↑')); expect(nextShell.writes, ['\x1b[A']);
    state.stop(); await tester.pump(); expect(tester.takeException(), isNull);
  });
  // Portable EditableText path; native macOS has separate view/channel and AX tests.
  portableTestWidgets('portable passphrase remains obscured in Flutter semantics while focused and unfocused', (tester) async {
    final semantics = tester.ensureSemantics();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:DirectSshPage(tokens:tokens)));
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.tap(find.byType(SwitchListTile)); await tester.pump();
    final field = find.byKey(const ValueKey('direct-passphrase'));
    await tester.ensureVisible(field); await tester.enterText(field,'fixture-secret'); await tester.pump();
    expect(tester.widget<TextField>(field).obscureText,isTrue);
    void verify() {
      final root = tester.getSemantics(find.bySemanticsLabel('私钥口令（可选）'));
      var fields = 0;
      void inspect(SemanticsNode node) {
        final data = node.getSemanticsData();
        if (data.flagsCollection.isTextField) {
          fields++; expect(data.flagsCollection.isObscured,isTrue); expect(data.value.contains('fixture-secret'),isFalse);
        }
        node.visitChildren((child) { inspect(child); return true; });
      }
      inspect(root); expect(fields,1);
    }
    verify();
    final address = find.byKey(const ValueKey('direct-host'));
    await tester.ensureVisible(address); await tester.pumpAndSettle(); await tester.tap(address); await tester.pump();
    verify(); semantics.dispose();
  });
  portableTestWidgets('ordinary SSH requires explicit fingerprint confirmation', (tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    expect(find.bySemanticsIdentifier('direct-back'), findsNothing);
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('direct-probe'))).onPressed, isNull);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('direct-probe'))).onPressed, isNotNull);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
  });

  testWidgets('returning from ordinary SSH with unsubmitted credentials disposes its listeners safely', (tester) async {
    final semantics = tester.ensureSemantics();
    mockSecureFields(tester);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await pumpOrdinaryHome(tester, tokens);
    await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
    final credential = find.byWidgetPredicate((widget) => widget.key == const ValueKey('direct-secret') &&
      (widget is TextField || widget is MacosSecureCredentialField));
    if (tester.widget(credential) is MacosSecureCredentialField) {
      tester.widget<MacosSecureCredentialField>(credential).controller.text = 'unsubmitted-temporary-credential';
    } else {
      await tester.enterText(credential, 'unsubmitted-temporary-credential');
    }
    await tester.pump();
    final back = find.bySemanticsIdentifier('direct-back');
    expect(back, findsOneWidget);
    final data = tester.getSemantics(back).getSemanticsData();
    expect(data.label, contains('返回主机列表'));
    expect(data.flagsCollection.isButton, isTrue);
    expect(data.hasAction(SemanticsAction.tap), isTrue);
    if (tester.widget(credential) is MacosSecureCredentialField) expect(data.label, '返回主机列表');
    await tester.tap(back); await tester.pumpAndSettle();
    expect(find.byType(DirectSshPage), findsNothing); expect(find.text('Open ordinary SSH'), findsOneWidget);
    await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
    final reopened = tester.widget(credential);
    final controller = reopened is MacosSecureCredentialField ? reopened.controller : (reopened as TextField).controller!;
    expect(controller.text, isEmpty);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-host'))).controller!.text, isEmpty);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    await tester.binding.handlePopRoute(); await tester.pumpAndSettle();
    expect(find.byType(DirectSshPage), findsNothing); expect(find.text('Open ordinary SSH'), findsOneWidget);
    expect(tester.takeException(), isNull);
    semantics.dispose();
  }, variant: TargetPlatformVariant({TargetPlatform.android, TargetPlatform.macOS}));

  portableTestWidgets('loopback probe, confirm, password, PTY and background disconnect', (tester) async {
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'];
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort!);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    expect(find.textContaining('SHA256:'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    final connect = find.byKey(const ValueKey('direct-connect'));
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    expect(tester.widget<FilledButton>(connect).onPressed, isNotNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), ''); await tester.pump();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(connect).onPressed, isNull);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    terminal.textInput('你好\n');
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 150)));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await tester.pump();
    expect(find.textContaining('应用进入后台'), findsOneWidget);
    expect(find.byType(TerminalView), findsNothing);
    await tester.pumpWidget(const SizedBox());
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  }, skip: Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'] == null);
  portableTestWidgets('changed host key blocks the second connection before authentication', (tester) async {
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_ROTATE_PORT']!;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture'); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNotNull);
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.textContaining('主机密钥不符'));
    expect(find.byType(TerminalView), findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).controller!.text, isEmpty);
  }, skip: Platform.environment['HERDR_DIRECT_SSH_ROTATE_PORT'] == null);

  portableTestWidgets('encrypted private key authenticates to the isolated shell', (tester) async {
    final semantics = tester.ensureSemantics();
    final fixturePort = Platform.environment['HERDR_DIRECT_SSH_KEY_PORT']!;
    final keyPath = Platform.environment['HERDR_DIRECT_SSH_KEY_PATH']!;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final key = await tester.runAsync(() => File(keyPath).readAsString());
    await pumpOrdinaryHome(tester, tokens);
    await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), fixturePort);
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture'); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
    await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
    await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
    await tester.ensureVisible(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile)); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'invalid-pem'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect'))); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    expect(find.text('私钥无法解析或解密；请检查完整 PEM 和私钥口令。尚未连接远端。'), findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).controller!.text.isEmpty, isTrue);
    await tester.enterText(find.byKey(const ValueKey('direct-secret')), key!);
    await tester.enterText(find.byKey(const ValueKey('direct-passphrase')), 'fixture-passphrase'); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNotNull);
    final pendingPaste = Completer<Object?>();
    mockClipboard(tester, () => pendingPaste.future);
    await tapPasteKey(tester);
    await tester.ensureVisible(find.byKey(const ValueKey('direct-connect'))); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
    await waitFor(tester, find.byType(TerminalView));
    pendingPaste.complete({'text': clipboardPem}); await tester.pump(); await tester.pump();
    final dynamic state = tester.state(find.byType(DirectSshPage));
    expect((state.secret as TextEditingController).text.isEmpty, isTrue, reason: 'late paste cannot refill credentials after connect');
    final client = state.client as SSHClient;
    await tester.tap(find.bySemanticsIdentifier('direct-back')); await tester.pumpAndSettle();
    await tester.runAsync(() => client.done);
    expect(client.isClosed, isTrue);
    expect(find.byType(DirectSshPage), findsNothing);
    expect(find.text('Open ordinary SSH'), findsOneWidget);
    await tester.tap(find.text('Open ordinary SSH')); await tester.pumpAndSettle();
    expect(find.byType(TerminalView), findsNothing);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).controller!.text, isEmpty);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    expect(tester.takeException(), isNull);
    semantics.dispose();
  }, skip: Platform.environment['HERDR_DIRECT_SSH_KEY_PORT'] == null || Platform.environment['HERDR_DIRECT_SSH_KEY_PATH'] == null);

  portableTestWidgets('ordinary SSH form constrains width and exposes named editable fields', (tester) async {
    final semantics = tester.ensureSemantics();
    tester.view.physicalSize = const Size(800, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    for (final item in {'direct-host':'地址', 'direct-port':'端口', 'direct-user':'用户名', 'direct-secret':'密码（仅本次使用）'}.entries) {
      final semanticField=find.bySemanticsLabel(item.value);
      expect(semanticField, findsOneWidget);
      var containsEditable=false;
      tester.getSemantics(semanticField).visitChildren((node) {
        containsEditable=containsEditable || node.flagsCollection.isTextField;
        return true;
      });
      expect(containsEditable, isTrue);
      expect(tester.getSize(find.byKey(ValueKey(item.key))).width, lessThanOrEqualTo(560));
    }
    await tester.enterText(find.byKey(const ValueKey('direct-host')), 'fixture.example');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();
    final host = tester.getRect(find.byKey(const ValueKey('direct-host')));
    final port = tester.getRect(find.byKey(const ValueKey('direct-port')));
    final user = tester.getRect(find.byKey(const ValueKey('direct-user')));
    expect(port.top - host.bottom, greaterThanOrEqualTo(16));
    expect(user.top - port.bottom, greaterThanOrEqualTo(16));
    expect(find.text('fixture.example'), findsOneWidget);
    expect(tester.takeException(), isNull);
    semantics.dispose();
  });

  for (final width in [320.0, 390.0]) {
    portableTestWidgets('ordinary SSH controls remain reachable at width $width with keyboard inset', (tester) async {
      final semantics = tester.ensureSemantics();
        tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetViewInsets);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
      for (final id in ['direct-host','direct-port','direct-user','direct-probe','direct-secret','direct-connect']) {
        final field=find.byKey(ValueKey(id));
        await tester.ensureVisible(field);await tester.pumpAndSettle();
        expect(tester.getRect(field).intersect(Rect.fromLTWH(0, 0, width, 544)).height, greaterThan(0));
      }
      await tester.ensureVisible(find.byType(SwitchListTile));await tester.pumpAndSettle();
      await tester.tap(find.byType(SwitchListTile));await tester.pumpAndSettle();
      final phrase=find.byKey(const ValueKey('direct-passphrase'));
      await tester.ensureVisible(phrase);await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('私钥口令（可选）'), findsWidgets);
      expect(tester.takeException(), isNull);
      semantics.dispose();
    });
  }

  portableTestWidgets('probe error remains readable and fields retain accessible names', (tester) async {
    final semantics=tester.ensureSemantics();
    final socket=await tester.runAsync(()=>ServerSocket.bind(InternetAddress.loopbackIPv4, 0));
    final closedPort=socket!.port;
    await tester.runAsync(socket.close);
    final tokens=(await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
    await tester.enterText(find.byKey(const ValueKey('direct-port')), '$closedPort');
    await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
    await tester.pump();await tester.tap(find.byKey(const ValueKey('direct-probe')));await tester.pump();
    await waitFor(tester, find.textContaining('探测失败或超时'));
    expect(find.bySemanticsLabel('地址'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
    semantics.dispose();
  });

}
