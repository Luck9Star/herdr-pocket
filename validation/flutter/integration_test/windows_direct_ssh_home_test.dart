import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

import '../integration_test/direct_ssh_ui_steps.dart'
    show control, openDirectSshFromHome;
import '../integration_test/windows_direct_ssh_test.dart'
    show
        WindowsKeyTarget,
        runWindowsDirectSshPublicKey,
        windowsDirectSshHomeReady;

void configureCatalogFixture(WidgetTester tester, {required bool available}) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(1024, 705);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  messenger.setMockMethodCallHandler(NativeHostCatalogStorage.channel, (
    call,
  ) async {
    expect(call.method, 'load');
    if (!available) throw PlatformException(code: 'catalog_unavailable');
    return <String, String>{'revision': '', 'contents': ''};
  });
  addTearDown(
    () => messenger.setMockMethodCallHandler(
      NativeHostCatalogStorage.channel,
      null,
    ),
  );
}

Future<void> pumpCatalog(WidgetTester tester, {required bool available}) async {
  configureCatalogFixture(tester, available: available);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(
    MaterialApp(
      theme: tokens.theme.copyWith(platform: TargetPlatform.windows),
      home: HostCatalogPage(
        tokens: tokens,
        offlineBuilder: (_) => const SizedBox(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  final home = find.byType(HostCatalogPage);
  final entry = control('hosts-direct-ssh').hitTestable();
  for (final available in [true, false]) {
    testWidgets(
      'Windows ordinary SSH enters once with catalog available=$available',
      (tester) async {
        await pumpCatalog(tester, available: available);
        expect(home, findsOneWidget);
        expect(entry, findsOneWidget);
        final warning = find.textContaining('资料损坏、存储锁定或不可用');
        expect(warning, available ? findsNothing : findsOneWidget);
        expect(
          control('home-empty-card'),
          available ? findsOneWidget : findsNothing,
        );
        expect(windowsDirectSshHomeReady(tester, home), isTrue);

        await openDirectSshFromHome(tester);
        final page = find.byType(DirectSshPage, skipOffstage: false);
        expect(page, findsOneWidget);
        expect(control('direct-form').hitTestable(), findsOneWidget);
        expect(Theme.of(tester.element(page)).platform, TargetPlatform.windows);
        expect(control('direct-secret'), findsNothing);
        expect(control('direct-connect'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'Windows ordinary SSH rejects another page with the same control key',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Center(
            child: TextButton(
              key: const ValueKey('hosts-direct-ssh'),
              onPressed: () => fail('tapped wrong route'),
              child: const Text('普通 SSH'),
            ),
          ),
        ),
      );
      expect(entry, findsOneWidget);
      expect(windowsDirectSshHomeReady(tester, home), isFalse);
    },
  );

  testWidgets(
    'Windows ordinary SSH rejects the catalog settings page without the entrance',
    (tester) async {
      await pumpCatalog(tester, available: false);
      await tester.tap(control('home-tab-3').hitTestable());
      await tester.pumpAndSettle();
      expect(home, findsOneWidget);
      expect(entry, findsNothing);
      expect(windowsDirectSshHomeReady(tester, home), isFalse);
    },
  );

  const fixturePath = String.fromEnvironment(
    'HERDR_WINDOWS_PUBLICKEY_WIDGET_FIXTURE',
  );
  testWidgets(
    'Windows public-key lane verifies the key, echoes once and returns home',
    (tester) async {
      configureCatalogFixture(tester, available: false);
      final fixture = jsonDecode(File(fixturePath).readAsStringSync()) as Map;
      final checkpoints = <String>[];
      await runWindowsDirectSshPublicKey(
        tester,
        WindowsKeyTarget(
          fixture['port'] as int,
          fixture['fingerprint'] as String,
        ),
        fixture['privateKey'] as String,
        step: (_) {},
        checkpoint: (phase, evidence) async {
          if (phase == 'key_entry') {
            expect(evidence, {
              'privateKeyExact': true,
              'passphraseEmpty': true,
            });
          }
          checkpoints.add(phase);
        },
      );
      expect(checkpoints, [
        'probe',
        'key_entry',
        'connected',
        'capture',
        'disconnect',
        'complete',
      ]);
      expect(home, findsOneWidget);
      expect(entry, findsOneWidget);
      expect(find.textContaining('资料损坏、存储锁定或不可用'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
    skip: fixturePath.isEmpty,
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );
}
