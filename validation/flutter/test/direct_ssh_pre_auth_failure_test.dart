import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';

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
}
