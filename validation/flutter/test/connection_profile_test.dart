import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/connection_profile.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final fixtureFile = File('assets/shared/connection-profile-v1.json').existsSync()
    ? File('assets/shared/connection-profile-v1.json') : File('../shared/connection-profile-v1.json');
  final vectors = jsonDecode(fixtureFile.readAsStringSync()) as Map<String,dynamic>;
  test('shared public profile vectors and host fingerprints', () {
    for (final item in vectors['valid'] as List) {
      final profile = ConnectionProfile.parse(item['raw'] as String);
      expect(profile.fingerprint,item['fingerprint'],reason:item['name']);
    }
    for (final item in vectors['invalid'] as List) {
      expect(() => ConnectionProfile.parse(item['raw'] as String),throwsFormatException,reason:item['name']);
    }
  });
  testWidgets('manual profile only fills after explicit preview and remains unreviewed',(tester) async {
    PairingPage.resetMemorySession();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:keys)));
    final raw = (vectors['valid'] as List).first['raw'] as String;
    await tester.enterText(find.byKey(const ValueKey('profile-input')),raw); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    await tapVisible(tester,'profile-fill'); await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,jsonDecode(raw)['host']);
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNull);
    await tester.pumpWidget(const SizedBox()); PairingPage.resetMemorySession();
  });
  testWidgets('late camera result after form edit cannot overwrite or preview',(tester) async {
    PairingPage.resetMemorySession();
    final pending = Completer<Object?>();
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),(_) => pending.future);
    addTearDown(() { messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),null); PairingPage.resetMemorySession(); });
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String))));
    await tapVisible(tester,'profile-scan');
    await tester.enterText(find.byKey(const ValueKey('pair-host')),'edited.example');
    pending.complete((vectors['valid'] as List).first['raw']); await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,'edited.example');
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:const TargetPlatformVariant({TargetPlatform.android}));
  testWidgets('cancel, invalid scan and hidden late result leave form untouched',(tester) async {
    PairingPage.resetMemorySession();
    final visibility = ValueNotifier(true), pending = Completer<Object?>();
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    var calls = 0;
    messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),(_) {
      calls++;
      if (calls == 1) return Future.value(null);
      if (calls == 2) return Future.value('{"version":1}');
      return pending.future;
    });
    addTearDown(() { messenger.setMockMethodCallHandler(const MethodChannel('herdr.pocket/pair_scan'),null); visibility.dispose(); PairingPage.resetMemorySession(); });
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,visibility:visibility,keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String))));
    await tapVisible(tester,'profile-scan'); await tester.pump();
    await tapVisible(tester,'profile-scan'); await tester.pump();
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    await tapVisible(tester,'profile-scan'); visibility.value = false; await tester.pump();
    pending.complete((vectors['valid'] as List).first['raw']); await tester.pump();
    visibility.value = true; await tester.pump();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,isEmpty);
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  },variant:const TargetPlatformVariant({TargetPlatform.android}));

  testWidgets('overlay public profile is saved pending binding while offline pairing continues',(tester) async {
    PairingPage.resetMemorySession();
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tokens = (await tester.runAsync(DesignTokens.load))!, cfg = fixtureConfig();
    final keys = TestDeviceKeys(cfg['privateKeyPem'] as String);
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,keys:keys,catalog:catalog)));
    final raw = jsonEncode({'version':1,'type':'herdr-connection-profile',
      for (final key in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) key:cfg[key],
      'provider':'tailscale'});
    await tester.enterText(find.byKey(const ValueKey('profile-input')),raw); await tester.pump();
    await tapVisible(tester,'profile-fill');
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pump();
    expect(keys.creates,1); expect(catalog.profiles.single.requiresNetworkBinding,isTrue);
    expect(catalog.profiles.single.provider,'tailscale'); expect(catalog.profiles.single.networkProfileId,isNull);
    expect(find.byKey(const ValueKey('pair-network-required')),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose(); PairingPage.resetMemorySession();
  });

}
