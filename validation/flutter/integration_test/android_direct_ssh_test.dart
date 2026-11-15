import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const enabled = String.fromEnvironment('HERDR_ANDROID_DIRECT_SSH');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const targetJson = String.fromEnvironment('HERDR_ANDROID_DIRECT_TARGET');
const directory = '/data/user/0/$packageName/cache/herdr-direct-ssh-$runId';

Map<String, dynamic> target() {
  if (!Platform.isAndroid ||
      !kDebugMode ||
      enabled != '1' ||
      !RegExp(r'^\d+$').hasMatch(runId)) {
    throw StateError('direct_ssh_android_isolated_fixture_required');
  }
  final value = jsonDecode(targetJson);
  const keys = {'host', 'port', 'username', 'password', 'fingerprint'};
  if (value is! Map<String, dynamic> ||
      value.keys.toSet().difference(keys).isNotEmpty ||
      value.length != keys.length ||
      value['host'] != '127.0.0.1' ||
      value['port'] is! int ||
      value['port'] < 1024 ||
      value['port'] > 65535 ||
      value['username'] != 'fixture' ||
      value['password'] is! String ||
      !RegExp(r'^[0-9a-f]{32}$').hasMatch(value['password']) ||
      value['fingerprint'] is! String ||
      !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(value['fingerprint'])) {
    throw StateError('direct_ssh_android_invalid_target');
  }
  return value;
}

void publish(String name, Object value) {
  final dir = Directory(directory)..createSync(recursive: true);
  final pending = File('${dir.path}/$name.pending')
    ..writeAsStringSync(jsonEncode(value), flush: true);
  pending.renameSync('${dir.path}/$name');
}

Future<void> until(WidgetTester tester, bool Function() ready) async {
  final deadline = DateTime.now().add(const Duration(seconds: 45));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail('direct_ssh_android_ui_timeout');
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> tap(WidgetTester tester, String key) async {
  final finder = find.byKey(ValueKey(key));
  await until(tester, () => finder.evaluate().length == 1);
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 200));
  expect(finder.hitTestable(), findsOneWidget);
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds: 200));
}

bool hasMarker(Terminal terminal, String marker) {
  final bytes = marker.codeUnits;
  for (var y = 0; y < terminal.viewHeight; y++) {
    final line = terminal.buffer.lines[y];
    for (var x = 0; x + bytes.length <= terminal.viewWidth; x++) {
      if (List.generate(
            bytes.length,
            (i) => line.getCodePoint(x + i),
          ).join(',') ==
          bytes.join(','))
        return true;
    }
  }
  return false;
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Android normal homepage to ordinary SSH fingerprint, actual input, echo and disconnect',
    (tester) async {
      var stage = 'fixture_validation';
      var fixtureValidated = false;
      try {
        final config = target();
        fixtureValidated = true;
        expect(tester.testTextInput.isRegistered, isFalse);
        if (Directory(directory).existsSync())
          throw StateError('direct_ssh_android_exchange_exists');
        void step(String next) {
          stage = next;
          publish('stage.json', {'stage': next});
        }

        step('home');
        await app.main();
        await until(
          tester,
          () =>
              find.byType(HostCatalogPage).evaluate().length == 1 &&
              find
                  .byKey(const ValueKey('hosts-direct-ssh'))
                  .evaluate()
                  .isNotEmpty,
        );
        final home = tester.widget<HostCatalogPage>(
          find.byType(HostCatalogPage),
        );
        expect(home.catalog, isNull);
        expect(home.adapterFactory, isNull);
        expect(home.keys, isNull);
        await binding.convertFlutterSurfaceToImage();
        await tester.pump();
        Future<void> capture(String name) async {
          final bytes = await binding.takeScreenshot(name);
          File('$directory/$name.png').writeAsBytesSync(bytes, flush: true);
        }

        await capture('home');
        await tap(tester, 'hosts-direct-ssh');
        expect(find.byType(DirectSshPage), findsOneWidget);
        step('target');
        for (final entry in {
          'direct-host': '127.0.0.1',
          'direct-port': '${config['port']}',
          'direct-user': 'fixture',
        }.entries) {
          final field = find.byKey(ValueKey(entry.key));
          await tester.ensureVisible(field);
          await tester.enterText(field, entry.value);
          await tester.pump();
        }
        expect(
          tester
              .widget<FilledButton>(
                find.byKey(const ValueKey('direct-connect')),
              )
              .onPressed,
          isNull,
        );
        step('probe');
        await tap(tester, 'direct-probe');
        await until(
          tester,
          () =>
              find
                  .byKey(const ValueKey('direct-trust-key'))
                  .evaluate()
                  .length ==
              1,
        );
        expect(
          find.textContaining(config['fingerprint'] as String),
          findsOneWidget,
        );
        await tap(tester, 'direct-trust-key');
        step('authenticate');
        final secret = find.byKey(const ValueKey('direct-secret'));
        await tester.ensureVisible(secret);
        await tester.enterText(secret, config['password'] as String);
        await tester.pump();
        await tap(tester, 'direct-connect');
        await until(
          tester,
          () => find.byType(TerminalView).evaluate().length == 1,
        );
        final terminalView = find.byType(TerminalView);
        final terminal = tester.widget<TerminalView>(terminalView).terminal;
        await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-READY'));
        step('input');
        await tester.tap(terminalView);
        await tester.pump(const Duration(milliseconds: 300));
        // Normal TerminalView debug-client commit, not terminal.onOutput injection
        // and not evidence of physical IME touch/composition.
        tester.testTextInput.enterText('hp-check');
        await tester.pump();
        final enter = find.widgetWithText(TextButton, 'Enter');
        await tester.ensureVisible(enter);
        await tester.tap(enter);
        await tester.pump();
        await until(tester, () => hasMarker(terminal, 'POCKET-ANDROID-SSH-OK'));
        await capture('connected');
        step('disconnect');
        final disconnect = find.widgetWithText(TextButton, '断开');
        expect(disconnect, findsOneWidget);
        await tester.tap(disconnect);
        await until(tester, () => find.byType(TerminalView).evaluate().isEmpty);
        expect(
          tester
              .widget<TextField>(find.byKey(const ValueKey('direct-secret')))
              .controller!
              .text,
          isEmpty,
        );
        expect(find.textContaining('已断开'), findsOneWidget);
        await capture('disconnected');
        expect(tester.takeException(), isNull);
        final report = {
          'schemaVersion': 1,
          'platform': 'android-api35-emulator',
          'homepageEntry': true,
          'fingerprintMatched': true,
          'explicitTrustRequired': true,
          'realTerminalView': true,
          'normalTextInputCommit': true,
          'remoteEchoVisible': true,
          'disconnectUiConfirmed': true,
          'credentialsCleared': true,
          'physicalImeVerified': false,
        };
        publish('result.json', report);
        // Keep the driver alive until the runner independently confirms that
        // the UI closed the peer, rather than count driver shutdown as close.
        final confirmation = File('$directory/peer-confirmed.json');
        await until(tester, () => confirmation.existsSync());
        expect(jsonDecode(confirmation.readAsStringSync()), {
          'protocolAccepted': true,
          'peerClosedBeforeDriverExit': true,
        });
        binding.reportData = report;
      } catch (_) {
        if (fixtureValidated) {
          publish('failure.json', {
            'stage': stage,
            'code': 'direct_ssh_android_ui_failed',
          });
        }
        rethrow;
      }
    },
  );
}
