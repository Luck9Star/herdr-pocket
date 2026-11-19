import 'dart:async';
import 'dart:typed_data';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';

class _Session extends Fake implements SSHSession {
  _Session(this.events) {
    input.stream.listen(
      (bytes) => events.add('input:${bytes.join(',')}'),
      onDone: () => events.add('stdin-eof'),
    );
  }

  final List<String> events;
  final input = StreamController<Uint8List>();
  final peerClosed = Completer<void>();
  int? remoteExitCode;

  @override
  int? get exitCode => remoteExitCode;

  @override
  SSHSessionExitSignal? get exitSignal => null;

  @override
  StreamSink<Uint8List> get stdin => input.sink;

  @override
  Future<void> get done => peerClosed.future;

  @override
  void write(Uint8List bytes) => input.add(bytes);

  @override
  void resizeTerminal(
    int width,
    int height, [
    int pixelWidth = 0,
    int pixelHeight = 0,
  ]) {}

  @override
  void close() => events.add('channel-abort');
}

class _Client extends Fake implements SSHClient {
  _Client(this.events);

  final List<String> events;

  @override
  Future<void> close() async => events.add('client-close');
}

class _Socket extends Fake implements SSHSocket {
  _Socket(this.events);

  final List<String> events;

  @override
  void destroy() => events.add('socket-destroy');
}

Future<dynamic> _openPage(WidgetTester tester) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(390, 844);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(
    MaterialApp(
      theme: tokens.theme,
      home: DirectSshPage(tokens: tokens),
    ),
  );
  return tester.state(find.byType(DirectSshPage));
}

_Session _connect(dynamic state, List<String> events) {
  final session = _Session(events);
  state.setState(() {
    state.socket = _Socket(events);
    state.client = _Client(events);
    state.shell = session;
    state.terminal = state.createTerminal(state.epoch);
    state.activeTarget = 'fixture@127.0.0.1:22';
    state.connected = true;
  });
  return session;
}

const _mobile = TargetPlatformVariant({
  TargetPlatform.iOS,
  TargetPlatform.android,
});
final _disconnect = find.byKey(const ValueKey('direct-disconnect'));

void main() {
  for (final outcome in ['exit', 'no-exit', 'timeout']) {
    final confirmed = outcome == 'exit';
    testWidgets('desktop close reports only verified channel retirement: $outcome', (tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(980, 780);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      var notifications = 0;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme.copyWith(platform: TargetPlatform.macOS), home: Builder(builder: (context) =>
        TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => DirectSshPage(
          tokens: tokens, onReturnAfterDisconnect: () => notifications++))), child: const Text('open')))));
      await tester.tap(find.text('open')); await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(DirectSshPage));
      final events = <String>[]; final session = _connect(state, events); await tester.pump();
      await tester.tap(find.widgetWithText(TextButton, '断开')); await tester.pump();
      expect(find.text('正在关闭连接'), findsOneWidget);
      expect(find.byKey(const ValueKey('direct-return-home')).hitTestable(), findsOneWidget);
      if (confirmed) { session.remoteExitCode = 0; session.peerClosed.complete(); await tester.pump(); await tester.pump(); }
      else if (outcome == 'no-exit') { session.peerClosed.complete(); await tester.pump(); await tester.pump(); }
      else { await tester.pump(const Duration(seconds: 4)); }
      expect(find.text(confirmed ? '已断开连接' : '远端关闭未确认'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('direct-return-home'))); await tester.pumpAndSettle();
      expect(notifications, confirmed ? 1 : 0);
      if (outcome == 'timeout') session.peerClosed.complete();
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('unconfirmed desktop close stays unconfirmed after mobile resize and back', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(980, 780);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final tokens = (await tester.runAsync(DesignTokens.load))!; var notifications = 0;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme.copyWith(platform: TargetPlatform.iOS), home: Builder(builder: (context) =>
      TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => DirectSshPage(tokens: tokens,
        onReturnAfterDisconnect: () => notifications++))), child: const Text('open')))));
    await tester.tap(find.text('open')); await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(DirectSshPage));
    final session = _connect(state, <String>[]); await tester.pump();
    await tester.tap(find.widgetWithText(TextButton, '断开')); await tester.pump();
    session.peerClosed.complete(); await tester.pump(); await tester.pump();
    tester.view.physicalSize = const Size(390, 844); await tester.pumpAndSettle();
    expect(find.text('远端关闭未确认'), findsOneWidget);
    expect(find.byKey(const ValueKey('direct-return-home')).hitTestable(), findsOneWidget);
    await tester.binding.handlePopRoute(); await tester.pumpAndSettle();
    expect(notifications, 0); await tester.pumpWidget(const SizedBox());
    expect(tester.takeException(), isNull);
  });

  testWidgets('explicit disconnect drains only the retiring session', (
    tester,
  ) async {
    final state = await _openPage(tester);
    final old = <String>[];
    final first = _connect(state, old);
    await tester.pump();
    final lateOutput = state.terminal.onOutput! as void Function(String);
    state.terminal.textInput('z');
    await tester.tap(_disconnect);
    await tester.pump();
    expect(find.text('已断开连接'), findsOneWidget);
    expect(state.connected, isFalse);
    expect(state.socket, isNull);
    expect(old, ['input:122', 'stdin-eof']);
    lateOutput('retired');

    final latest = <String>[];
    final second = _connect(state, latest);
    await tester.pump();
    first.peerClosed.complete();
    await tester.pump();
    expect(old, ['input:122', 'stdin-eof', 'client-close']);
    expect(latest, isEmpty);
    expect(state.shell, same(second));
    expect(state.connected, isTrue);

    await tester.pumpWidget(const SizedBox());
    expect(latest, ['channel-abort', 'client-close', 'socket-destroy']);
    await second.input.close();
    expect(tester.takeException(), isNull);
  }, variant: _mobile);

  testWidgets('no peer EOF is bounded even after leaving the page', (
    tester,
  ) async {
    final state = await _openPage(tester);
    final events = <String>[];
    final session = _connect(state, events);
    await tester.pump();
    await tester.tap(_disconnect);
    await tester.pump();
    expect(events, ['stdin-eof']);
    expect(find.text('已断开连接'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    expect(events, ['stdin-eof']);
    await tester.pump(const Duration(seconds: 4));
    expect(events, ['stdin-eof', 'socket-destroy']);
    session.peerClosed.complete();
    await tester.pump();
    expect(events, ['stdin-eof', 'socket-destroy']);
    expect(tester.takeException(), isNull);
  }, variant: _mobile);

  testWidgets('background cancellation retires transport immediately', (
    tester,
  ) async {
    final state = await _openPage(tester);
    final events = <String>[];
    final session = _connect(state, events);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    expect(state.connected, isFalse);
    expect(events, ['channel-abort', 'client-close', 'socket-destroy']);
    await session.input.close();
    expect(tester.takeException(), isNull);
  }, variant: _mobile);
}
