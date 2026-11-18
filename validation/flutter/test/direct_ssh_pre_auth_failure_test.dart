import 'dart:io';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';
import 'direct_ssh_widget_test.dart' show waitFor;
import 'ios_layout_diagnostics.dart' show iosDiagnosticButtonEnabled;

// The server performs the real first host-key probe, then holds the next
// handshake until the test releases it. No host credentials or identities.
const _delayedPeer = r"""
import importlib.util, pathlib, socket, sys, threading, time
spec = importlib.util.spec_from_file_location('fixture', sys.argv[1])
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
release = pathlib.Path(sys.argv[2])
key = fixture.paramiko.RSAKey.generate(2048)
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0)); listener.listen(4)
    print('PORT', listener.getsockname()[1], flush=True)
    for number in (1, 2):
        conn, _ = listener.accept()
        if number == 2:
            print('HANDSHAKE_HELD', flush=True)
            while not release.exists(): time.sleep(0.01)
            print('HANDSHAKE_RELEASED', flush=True)
        threading.Thread(target=fixture.handle, args=(conn, key), daemon=True).start()
    time.sleep(3)
""";

Future<void> _untilPeer(WidgetTester tester, bool Function() ready) async {
  final deadline = DateTime.now().add(const Duration(seconds: 12));
  while (!ready() && DateTime.now().isBefore(deadline)) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 25)));
    await tester.pump();
  }
  expect(ready(), isTrue, reason: 'delayed peer did not reach expected stage');
}

void main() {
  for (final cancel in [false, true]) {
    testWidgets(
      'iOS pre-auth ${cancel ? 'cancel' : 'handshake timeout'} preserves control facts without retry',
      (tester) async {
        tester.view.physicalSize = const Size(414, 896);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final listener = (await tester.runAsync(
          () => ServerSocket.bind(InternetAddress.loopbackIPv4, 0),
        ))!;
        final sockets = <Socket>[];
        final accepted = listener.listen((socket) {
          sockets.add(socket);
          socket.listen((_) {}, onError: (_) {});
        });
        try {
          final tokens = (await tester.runAsync(DesignTokens.load))!;
          await tester.pumpWidget(
            MaterialApp(
              theme: tokens.theme,
              home: DirectSshPage(tokens: tokens),
            ),
          );
          final dynamic state = tester.state(find.byType(DirectSshPage));
          await tester.enterText(
            find.byKey(const ValueKey('direct-host')),
            '127.0.0.1',
          );
          await tester.enterText(
            find.byKey(const ValueKey('direct-port')),
            '${listener.port}',
          );
          await tester.enterText(
            find.byKey(const ValueKey('direct-user')),
            'fixture',
          );
          // Synthetic pin: this deliberately silent TCP peer cannot establish
          // SSH identity. It must never reach the password callback or a PTY.
          state.setState(() {
            state.fingerprint = 'SHA256:synthetic';
            state.algorithm = 'ssh-rsa';
            state.checkedTarget = state.target;
            state.mobileAuth = true;
          });
          await tester.pump();
          const credential = 'synthetic-ui-credential';
          final secret = find.byKey(const ValueKey('direct-secret'));
          await tester.enterText(secret, credential);
          await tester.pump();
          expect(tester.widget<TextField>(secret).controller!.text, credential);
          await tester.ensureVisible(
            find.byKey(const ValueKey('direct-connect')),
          );
          await tester.pumpAndSettle();
          expect(
            find.byKey(const ValueKey('direct-connect')).hitTestable(),
            findsOneWidget,
          );
          await tester.tap(find.byKey(const ValueKey('direct-connect')));
          for (
            var i = 0;
            i < 40 && state.connectPhase != DirectSshConnectPhase.handshake;
            i++
          ) {
            await tester.runAsync(
              () => Future<void>.delayed(const Duration(milliseconds: 10)),
            );
            await tester.pump();
          }
          expect(state.connectPhase, DirectSshConnectPhase.handshake);
          expect(state.secret.text, isEmpty);
          expect(state.connectionDiagnostic['credentialCaptured'], isTrue);
          if (cancel) {
            await tester.tap(find.widgetWithText(TextButton, '断开'));
            await tester.pump();
          } else {
            await tester.pump(const Duration(seconds: 8));
          }
          expect(state.connectionDiagnostic, {
            'phase': 'handshake',
            'failureCode': cancel ? 'cancelled' : 'handshakeTimeout',
            'hostKeyMatched': false,
            'credentialCaptured': true,
            'passwordRequested': false,
          });
          expect(state.terminal, isNull);
          expect(find.byType(TerminalView), findsNothing);
          await tester.pump(const Duration(seconds: 20));
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 20)),
          );
          expect(sockets, hasLength(1));
          expect(state.secret.text, isEmpty);
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox());
        } finally {
          for (final socket in sockets) {
            socket.destroy();
          }
          await tester.runAsync(() async {
            await accepted.cancel();
            await listener.close();
          });
        }
      },
      variant: TargetPlatformVariant.only(TargetPlatform.iOS),
    );
  }
  for (final via in ['button', 'system', 'edge', 'edge-cancel-then-button']) {
    testWidgets('return via $via cancels a held SSH handshake before authentication', (tester) async {
      tester.view.physicalSize = const Size(390, 844); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final directory = await tester.runAsync(() => Directory.systemTemp.createTemp('herdr-auth-back-'));
      final release = File('${directory!.path}/release');
      final process = await tester.runAsync(() => Process.start(Platform.environment['HERDR_FIXTURE_PYTHON']!,
        ['-u', '-c', _delayedPeer, File('test/direct_ssh_fixture.py').absolute.path, release.path]));
      final lines = <String>[];
      final output = process!.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(lines.add);
      final errors = process.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen(lines.add);
      try {
        await _untilPeer(tester, () => lines.any((line) => line.startsWith('PORT ')));
        final port = int.parse(lines.firstWhere((line) => line.startsWith('PORT ')).split(' ').last);
        final tokens = (await tester.runAsync(DesignTokens.load))!;
        await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: Builder(builder: (context) => Scaffold(
          body: TextButton(onPressed: () => Navigator.push<void>(context, MaterialPageRoute(builder: (_) => DirectSshPage(tokens: tokens))),
            child: const Text('打开'))))));
        await tester.tap(find.text('打开')); await tester.pumpAndSettle();
        Finder key(String id) => find.byKey(ValueKey(id));
        await tester.enterText(key('direct-host'), '127.0.0.1');
        await tester.enterText(key('direct-port'), '$port');
        await tester.enterText(key('direct-user'), 'fixture'); await tester.pump();
        await tester.tap(key('direct-probe')); await tester.pump(); await waitFor(tester, key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.tap(key('direct-trust-key')); await tester.pumpAndSettle();
        await tester.enterText(key('direct-secret'), 'temporary'); await tester.pump();
        final dynamic state = tester.state(find.byType(DirectSshPage));
        await tester.ensureVisible(key('direct-connect')); await tester.tap(key('direct-connect')); await tester.pump();
        await _untilPeer(tester, () => lines.contains('HANDSHAKE_HELD'));
        expect(state.busy, isTrue); expect(state.connectionDiagnostic['passwordRequested'], isFalse);
        final int runningEpoch = state.epoch;
        if (via.startsWith('edge')) {
          final gesture = await tester.startGesture(const Offset(1, 350)); await tester.pump();
          await gesture.moveBy(const Offset(20, 0)); await tester.pump();
          expect(Navigator.of(tester.element(key('direct-form'))).userGestureInProgress, isTrue);
          await gesture.moveBy(Offset(via == 'edge' ? 300 : 15, 0));
          await tester.pump(const Duration(milliseconds: 300)); await gesture.up(); await tester.pumpAndSettle();
          if (via != 'edge') { expect(state.busy, isTrue); expect(state.epoch, runningEpoch); }
        }
        if (via == 'button' || via == 'edge-cancel-then-button') { await tester.tap(find.byType(BackButton)); }
        if (via == 'system') { await tester.binding.handlePopRoute(); }
        await tester.pumpAndSettle();
        expect(state.epoch, greaterThan(runningEpoch));
        if (via == 'button' || via == 'edge-cancel-then-button') {
          expect(key('direct-host'), findsOneWidget);
        } else { expect(find.text('打开'), findsOneWidget); }
        await tester.runAsync(() => release.writeAsString('release'));
        await _untilPeer(tester, () => lines.contains('HANDSHAKE_RELEASED'));
        final settleUntil = DateTime.now().add(const Duration(seconds: 2));
        while (DateTime.now().isBefore(settleUntil)) {
          await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 25))); await tester.pump();
        }
        expect(lines.where((line) => line.startsWith('AUTH ') || line.startsWith('PUBLICKEY ') || line.startsWith('PTY ')), isEmpty,
          reason: 'return before handshake release must prevent authentication and PTY: ${lines.join(' | ')}');
        expect(find.byType(TerminalView), findsNothing);
        if (via == 'button' || via == 'edge-cancel-then-button') {
          expect(state.busy, isFalse); expect(state.secret.text, isEmpty);
          expect(state.terminal, isNull); expect(state.shell, isNull);
          expect(state.connectionDiagnostic['failureCode'], 'cancelled');
          expect(state.connectionDiagnostic['passwordRequested'], isFalse);
        }
        debugPrint('delayed-$via peer: ${lines.join(' | ')}; no authentication or PTY');
        expect(tester.takeException(), isNull);
      } finally {
        await tester.runAsync(() async {
          process.kill(); await process.exitCode;
          await output.cancel(); await errors.cancel(); await directory.delete(recursive: true);
        });
      }
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS), skip: Platform.environment['HERDR_FIXTURE_PYTHON'] == null);
  }

  for (final width in [390.0, 800.0]) {
    testWidgets('iOS diagnostic accepts actual probe button at width $width', (tester) async {
      tester.view.physicalSize = Size(width, 844); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
      final probe = find.byKey(const ValueKey('direct-probe'));
      expect(tester.widget<Widget>(probe), width < 600 ? isA<FilledButton>() : isA<OutlinedButton>());
      expect(iosDiagnosticButtonEnabled(tester.widget<Widget>(probe)), isFalse);
      await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
      await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture'); await tester.pump();
      expect(iosDiagnosticButtonEnabled(tester.widget<Widget>(probe)), isTrue);
      expect(iosDiagnosticButtonEnabled(const Text('not a button')), isNull);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
  }

}
