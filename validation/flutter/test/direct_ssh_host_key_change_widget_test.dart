import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'direct_ssh_widget_test.dart' show waitFor;
import 'herdr_workflow_visual_test.dart' show loadVisualTokens, visualApp, save, size;

/// Each case spawns its own rotation peer; a second key change uses a fresh peer
/// with new key material on the SAME port, so reruns never depend on shared state.
class RotationPeer {
  RotationPeer._(this.process, this.logs, this.port);
  final Process process;
  final List<String> logs;
  final int port;

  static Future<RotationPeer> start({int? fixedPort}) async {
    final python = Platform.environment['HERDR_FIXTURE_PYTHON']!;
    final script = File('test/direct_ssh_fixture.py').absolute.path;
    final process = await Process.start(python, [script], environment: {
      ...Platform.environment,
      'HERDR_FIXTURE_ROTATE_KEY': '1',
      if (fixedPort != null) 'HERDR_FIXTURE_PORT': '$fixedPort',
    });
    final logs = <String>[];
    var exited = false;
    process.exitCode.then((_) => exited = true);
    process.stdout.transform(utf8.decoder).listen(logs.add);
    process.stderr.transform(utf8.decoder).listen(logs.add);
    final deadline = DateTime.now().add(const Duration(seconds: 20));
    while (DateTime.now().isBefore(deadline) && !exited) {
      final match = RegExp(r'PORT (\d+)').firstMatch(logs.join());
      if (match != null) {
        final reported = int.parse(match.group(1)!);
        if (fixedPort != null && reported != fixedPort) {
          process.kill();
          throw StateError('rotation peer bound $reported instead of requested $fixedPort: ${logs.join()}');
        }
        return RotationPeer._(process, logs, reported);
      }
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    process.kill();
    throw StateError('rotation peer did not report its port: ${logs.join()}');
  }

  Future<void> stop() async {
    process.kill();
    await process.exitCode.timeout(const Duration(seconds: 5), onTimeout: () => -1);
  }

  bool get sawAuthentication => logs.any((line) => line.startsWith('AUTH') || line.startsWith('PUBLICKEY'));
}

Future<void> fillTarget(WidgetTester tester, int port) async {
  await tester.enterText(find.byKey(const ValueKey('direct-host')), '127.0.0.1');
  await tester.enterText(find.byKey(const ValueKey('direct-port')), '$port');
  await tester.enterText(find.byKey(const ValueKey('direct-user')), 'fixture');
  await tester.pump();
}

Future<void> probeAndTrust(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
  await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
  await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
}

void expectReviewLocked(WidgetTester tester, {required bool locked}) {
  final dynamic state = tester.state(find.byType(DirectSshPage));
  if (state.mobileLayout) {
    expect(find.byKey(const ValueKey('direct-secret')), locked ? findsNothing : findsOneWidget);
    expect(find.byKey(const ValueKey('direct-connect')), locked ? findsNothing : findsOneWidget);
    if (locked) expect(find.byKey(const ValueKey('direct-probe')), findsOneWidget);
  } else {
    expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-secret'))).enabled, !locked);
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).onChanged, locked ? isNull : isNotNull);
    expect(tester.widget<OutlinedButton>(find.byKey(const ValueKey('direct-probe'))).onPressed, isNotNull);
  }
}

Future<void> pushDirectSsh(WidgetTester tester, DesignTokens tokens) async {
  await tester.pumpWidget(visualApp(tokens, Builder(builder: (context) => Scaffold(
    body: Center(child: FilledButton(key: const ValueKey('s10-push-target'),
      onPressed: () => Navigator.push<void>(context, MaterialPageRoute(builder: (_) => DirectSshPage(tokens: tokens))),
      child: const Text('打开普通 SSH')))))));
  await tester.tap(find.byKey(const ValueKey('s10-push-target')));
  await tester.pumpAndSettle();
}
void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('S10 real rotation flow at $width', (tester) async {
      final peer1 = (await tester.runAsync(() => RotationPeer.start()))!;
      addTearDown(() => tester.runAsync(peer1.stop));
      size(tester, Size(width, 844));
      final tokens = await loadVisualTokens(tester);
      await pushDirectSsh(tester, tokens);
      expect(find.bySemanticsIdentifier('direct-back'), findsOneWidget);
      await fillTarget(tester, peer1.port);
      await probeAndTrust(tester);
      final dynamic state = tester.state(find.byType(DirectSshPage));
      final String oldAlgorithm = state.algorithm, oldFingerprint = state.fingerprint;
      await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
      await tester.ensureVisible(find.byKey(const ValueKey('direct-connect')));
      await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
      await waitFor(tester, find.byKey(const ValueKey('direct-host-key-change')));
      expect(find.text('主机指纹发生变化'), findsOneWidget);
      expect(find.text('已阻止连接与输入'), findsOneWidget);
      expect(find.byType(TerminalView), findsNothing);
      final first = state.hostKeyChange;
      expect(first.oldAlgorithm, oldAlgorithm);
      expect(first.oldFingerprint, oldFingerprint);
      expect(first.newFingerprint, isNot(oldFingerprint));
      expect(first.newFingerprint, startsWith('SHA256:'));
      expect(first.target, 'fixture@127.0.0.1:${peer1.port}');
      expect(state.secret.text, isEmpty);
      expect(state.hostKeyReviewRequired, isTrue);
      await tester.ensureVisible(find.byKey(const ValueKey('direct-host-key-old')));
      await tester.ensureVisible(find.byKey(const ValueKey('direct-host-key-new')));
      for (final key in ['direct-host-key-review', 'direct-host-key-cancel']) {
        await tester.ensureVisible(find.byKey(ValueKey(key))); await tester.pumpAndSettle();
        expect(find.byKey(ValueKey(key)).hitTestable(), findsOneWidget);
      }
      // Pushed-route regression: the refusal page exposes no back exit at all.
      if (find.bySemanticsIdentifier('direct-back').evaluate().isNotEmpty) {
        debugPrint(find.bySemanticsIdentifier('direct-back').evaluate().single.toStringDeep());
      }
      expect(find.bySemanticsIdentifier('direct-back'), findsNothing);
      expect(find.byType(BackButton), findsNothing);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(DirectSshPage), findsOneWidget);
      expect(find.byKey(const ValueKey('direct-host-key-change')), findsOneWidget);
      await tester.pumpAndSettle();
      await save(tester, 'flutter-s10-${width.toInt()}');
      final evidence = <String, Object?>{
        'width': width.toInt(), 'target': first.target,
        'source': 'real onVerifyHostKey values from independently spawned rotation peers; no synthetic fingerprints',
        'firstChange': {
          'oldAlgorithm': first.oldAlgorithm, 'oldFingerprint': first.oldFingerprint,
          'newAlgorithm': first.newAlgorithm, 'newFingerprint': first.newFingerprint,
        },
        'secretClearedAtChange': state.secret.text.isEmpty,
      };

      // Review must enter explicit probe/confirm for the SAME target, never pop away.
      await tester.tap(find.byKey(const ValueKey('direct-host-key-review'))); await tester.pump();
      await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
      expect(find.byType(DirectSshPage), findsOneWidget);
      expect(find.textContaining(first.newFingerprint), findsWidgets);
      evidence['reviewEntersProbeWithoutPop'] = true;

      // Refusing the re-probe keeps old trust and locks every credential entry.
      await tester.tap(find.byKey(const ValueKey('direct-trust-cancel'))); await tester.pumpAndSettle();
      expect(state.hostKeyReviewRequired, isTrue);
      expect(state.fingerprint, oldFingerprint);
      expectReviewLocked(tester, locked: true);
      if (!state.mobileLayout) expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
      evidence['refusedReprobeKeepsOldTrust'] = true;
      evidence['credentialsLockedWhileReviewPending'] = true;

      // Independent approval of the rotated key unlocks and reconnects.
      await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
      await waitFor(tester, find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
      expect(state.hostKeyReviewRequired, isFalse);
      expect(state.fingerprint, first.newFingerprint);
      expectReviewLocked(tester, locked: false);
      await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
      expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNotNull);
      await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
      await waitFor(tester, find.byType(TerminalView));
      evidence['independentReviewReconnects'] = true;
      await tester.tap(find.text('断开')); await tester.pumpAndSettle();
      expect(state.fingerprint, first.newFingerprint);

      // The mobile disconnected view requires another explicit probe before credentials.
      if (state.mobileLayout) {
        await tester.tap(find.byKey(const ValueKey('direct-probe'))); await tester.pump();
        await waitFor(tester, find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('direct-trust-key'))); await tester.pumpAndSettle();
        expect(state.fingerprint, first.newFingerprint);
      }
      // Second key change on the same target: new peer, new key material, same port.
      await tester.runAsync(peer1.stop);
      final peer2 = (await tester.runAsync(() => RotationPeer.start(fixedPort: peer1.port)))!;
      addTearDown(() => tester.runAsync(peer2.stop));
      await tester.enterText(find.byKey(const ValueKey('direct-secret')), 'temporary'); await tester.pump();
      await tester.tap(find.byKey(const ValueKey('direct-connect'))); await tester.pump();
      await waitFor(tester, find.byKey(const ValueKey('direct-host-key-change')));
      final second = state.hostKeyChange;
      expect(second.oldFingerprint, first.newFingerprint);
      expect(second.newFingerprint, isNot(first.newFingerprint));
      expect(second.newFingerprint, isNot(oldFingerprint));
      expect(state.secret.text, isEmpty);
      expect(state.hostKeyReviewRequired, isTrue);
      evidence['secondChange'] = {
        'oldFingerprint': second.oldFingerprint, 'newFingerprint': second.newFingerprint,
      };

      // Cancel preserves the latest old trust and keeps all entries locked.
      await tester.tap(find.byKey(const ValueKey('direct-host-key-cancel'))); await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('direct-form')), findsOneWidget);
      expect(state.fingerprint, first.newFingerprint);
      expectReviewLocked(tester, locked: true);
      if (state.mobileLayout) {
        expect(find.byKey(const ValueKey('direct-connect')), findsNothing);
        expect(find.byKey(const ValueKey('direct-paste-key')), findsNothing);
        expect(find.byKey(const ValueKey('direct-passphrase')), findsNothing);
      } else {
        expect(tester.widget<FilledButton>(find.byKey(const ValueKey('direct-connect'))).onPressed, isNull);
        state.setState(() { state.keyAuth = true; }); await tester.pump();
        expect(tester.widget<TextButton>(find.byKey(const ValueKey('direct-paste-key'))).onPressed, isNull);
        expect(tester.widget<TextField>(find.byKey(const ValueKey('direct-passphrase'))).enabled, isFalse);
      }
      evidence['cancelAfterSecondChangeKeepsOldTrust'] = true;
      expect(peer2.sawAuthentication, isFalse);
      evidence['secondChangeSentNoAuthentication'] = true;
      // Cancel restores the normal pushed-route back exit and navigation.
      final back = find.bySemanticsIdentifier('direct-back');
      expect(back, findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
      await tester.tap(back); await tester.pumpAndSettle();
      expect(find.byType(DirectSshPage), findsNothing);
      expect(find.byKey(const ValueKey('s10-push-target')), findsOneWidget);

      final directory = Platform.environment['HERDR_WORKFLOW_CAPTURE'];
      if (directory != null) {
        await tester.runAsync(() async {
          Directory(directory).createSync(recursive: true);
          await File('$directory/flutter-s10-${width.toInt()}.json').writeAsString(const JsonEncoder.withIndent('  ').convert(evidence));
        });
      }
      expect(tester.takeException(), isNull);
    }, skip: Platform.environment['HERDR_FIXTURE_PYTHON'] == null);
  }
}
