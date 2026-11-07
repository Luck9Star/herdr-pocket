import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/connection_profile.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'host_catalog_test.dart' show catalogPairing;
import 'pairing_gui_test.dart' show TestDeviceKeys,fillPairTarget,tapVisible,acceptResponse,authorizedResponse;
import 'remote_test_data.dart';

void main() {
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);

  test('connection profiles accept IPv6 but reject URI IPvFuture literals', () {
    final config = fixtureConfig();
    final profile = {'version':1,'type':'herdr-connection-profile','provider':'direct',
      for (final key in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) key:config[key]};
    for (final host in ['::1','2001:db8::1','::ffff:192.0.2.1']) {
      expect(ConnectionProfile.parse(jsonEncode({...profile,'host':host})).values['host'],host);
    }
    for (final host in ['v1.fe:abc','vF.example:1234','v1.!:a','v1.:','[::1]','fe80::1%eth0','::ffff:192.00.2.1']) {
      expect(() => ConnectionProfile.parse(jsonEncode({...profile,'host':host})),throwsFormatException,reason:host);
    }
  });

  for (final restricted in [false, true]) {
    testWidgets('retained identity keeps its own binding guard when another target replaces process memory ($restricted)', (tester) async {
      final config = fixtureConfig();
      PairingPage.retainedPairing = catalogPairing(authorized:true);
      PairingPage.retainedTarget = Map.unmodifiable(config);
      PairingPage.retainedRequiresNetworkBinding = restricted;
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final visibility = ValueNotifier(true);
      addTearDown(visibility.dispose);
      await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,
        keys:TestDeviceKeys(config['privateKeyPem'] as String),visibility:visibility,clock:() => 1000)));
      expect(find.byKey(const ValueKey('pair-network-required')),restricted ? findsOneWidget : findsNothing);

      // A separate page finishes creating a different identity/target while
      // this mounted page still owns its original frozen pairing and target.
      PairingPage.retainedPairing = catalogPairing(authorized:true);
      PairingPage.retainedTarget = Map.unmodifiable({...config,'host':'other.example'});
      PairingPage.retainedRequiresNetworkBinding = !restricted;
      visibility.value = false;
      await tester.pump();
      expect(find.byKey(const ValueKey('pair-network-required')),restricted ? findsOneWidget : findsNothing);
      if (restricted) {
        expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-connect'))).onPressed,isNull);
      }
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('accepting a restored response retains the same identity target and binding restriction together', (tester) async {
    final config = fixtureConfig(), original = catalogPairing();
    PairingPage.retainedPairing = original;
    PairingPage.retainedTarget = Map.unmodifiable(config);
    PairingPage.retainedRequiresNetworkBinding = true;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,
      keys:TestDeviceKeys(config['privateKeyPem'] as String),clock:() => 1000)));
    PairingPage.retainedPairing = PendingDevicePairing(handle:'other-opaque-handle',
      publicKey:config['expectedHostKey'] as String,account:config['username'] as String,
      hostKey:pairingFingerprint(config['expectedHostKey'] as String),device:'Other phone',now:1000);
    PairingPage.retainedTarget = Map.unmodifiable({...config,'host':'other.example'});
    PairingPage.retainedRequiresNetworkBinding = false;

    await acceptResponse(tester,authorizedResponse(original.request));
    expect(PairingPage.retainedPairing!.handle,original.handle);
    expect(PairingPage.retainedPairing!.authorization,'authorized');
    expect(PairingPage.retainedTarget,config);
    expect(PairingPage.retainedRequiresNetworkBinding,isTrue);
    expect(find.byKey(const ValueKey('pair-network-required')),findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('deleting an older page identity does not clear another retained identity target or restriction', (tester) async {
    final config = fixtureConfig();
    PairingPage.retainedPairing = catalogPairing(authorized:true);
    PairingPage.retainedTarget = Map.unmodifiable(config);
    PairingPage.retainedRequiresNetworkBinding = true;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,
      keys:TestDeviceKeys(config['privateKeyPem'] as String),clock:() => 1000)));
    final other = PendingDevicePairing(handle:'other-opaque-handle',
      publicKey:config['expectedHostKey'] as String,account:config['username'] as String,
      hostKey:pairingFingerprint(config['expectedHostKey'] as String),device:'Other phone',now:1000);
    final otherTarget = Map<String,dynamic>.unmodifiable({...config,'host':'other.example'});
    PairingPage.retainedPairing = other;
    PairingPage.retainedTarget = otherTarget;
    PairingPage.retainedRequiresNetworkBinding = false;

    await tapVisible(tester,'pair-delete');
    expect(identical(PairingPage.retainedPairing,other),isTrue);
    expect(PairingPage.retainedTarget,otherTarget);
    expect(PairingPage.retainedRequiresNetworkBinding,isFalse);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a new manual page does not inherit an orphan binding flag', (tester) async {
    PairingPage.retainedRequiresNetworkBinding = true;
    final config = fixtureConfig(), keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(home:PairingPage(tokens:tokens,
      keys:keys,clock:() => 1000)));
    expect(find.byKey(const ValueKey('pair-host')),findsOneWidget);
    await fillPairTarget(tester,config);
    await tapVisible(tester,'pair-target-review');
    await tapVisible(tester,'pair-create');
    expect(keys.creates,1);
    expect(find.byKey(const ValueKey('pair-request')),findsOneWidget);
    expect(find.byKey(const ValueKey('pair-network-required')),findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
