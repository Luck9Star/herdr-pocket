import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'config_transfer_test.dart' show portable;
import 'network_profiles_test.dart' show testNetwork;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,authorizedResponse;
import 'remote_page_test.dart' show PendingAdapter;
import 'remote_test_data.dart';

void main() {
  testWidgets('normal 360px host board exposes network manager and creates a reusable profile',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(360,780);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'hosts-networks'); await tester.pumpAndSettle();
    expect(find.byType(NetworkProfilesPage),findsOneWidget);
    await tapVisible(tester,'networks-add'); await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('network-label')),'Phone mesh');
    await tapVisible(tester,'network-save'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.label,'Phone mesh');
    expect(catalog.networkProfiles.single.provider,'tailscale');
    expect(catalog.networkProfiles.single.settings,{'controlUrl':'','hostname':''});
    expect(find.textContaining('provider_unavailable'),findsWidgets);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('network impact lists referenced host and refusing delete preserves its binding',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = testNetwork(),original = await saveCatalogProfile(catalog); await catalog.addNetwork(network);
    await catalog.update(original.change(networkProfileId:network.id,replaceNetwork:true,now:1000));
    final closed = <String>{};
    await tester.pumpWidget(MaterialApp(home:NetworkProfilesPage(catalog:catalog,closeTabs:closed.addAll)));
    await tapVisible(tester,'network-delete-${network.id}'); await tester.pumpAndSettle();
    expect(find.textContaining('Fixture host'),findsOneWidget);
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.id,network.id); expect(closed,isEmpty);
    expect(find.textContaining('此网络仍被主机引用'),findsOneWidget);
    await tapVisible(tester,'network-toggle-${network.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'network-confirm'); await tester.pumpAndSettle();
    expect(catalog.networkProfiles.single.enabled,isFalse); expect(closed,{original.id});
    expect(catalog.profiles.single.networkProfileId,network.id);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('disabled overlay without a bridge still permits offline pairing and helper response review after reopening',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final network = NetworkProfile.fromJson({...testNetwork().toJson(),'enabled':false}); await catalog.addNetwork(network);
    final imported = HostProfile.imported(portable(),1000,networkProfileId:network.id); await catalog.add(imported);
    final tokens = (await tester.runAsync(DesignTokens.load))!,keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final adapters = <PendingAdapter>[];
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      adapterFactory:(_) { final adapter = PendingAdapter(); adapters.add(adapter); return adapter; },offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${imported.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pumpAndSettle();
    expect(keys.creates,1); expect(find.byKey(const ValueKey('pair-request')),findsOneWidget);
    final paired = catalog.profiles.single;
    await tester.pageBack(); await tester.pumpAndSettle();
    await tapVisible(tester,'host-open-${paired.id}'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-request')),findsOneWidget);
    final response = jsonEncode(authorizedResponse(Map<String,dynamic>.from(paired.pairingRecord['request'] as Map)));
    final input = find.byKey(const ValueKey('pair-response')); await tester.ensureVisible(input); await tester.enterText(input,response); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    await tapVisible(tester,'pair-source-review'); await tapVisible(tester,'pair-accept'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
    expect(find.textContaining('网络绑定已改变或停用'),findsOneWidget);
    expect(keys.creates,1); expect(keys.signCalls,0); expect(adapters.every((adapter) => adapter.calls == 0),isTrue);
    expect(catalog.profiles.single.networkProfileId,network.id); expect(catalog.networkProfiles.single.enabled,isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('every overlay stops before SSH adapter or device signing; explicit revision is displayed',(tester) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    for (final provider in overlayProviders) {
      final adapter = PendingAdapter(),keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
      final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      final network = testNetwork(provider),original = await saveCatalogProfile(catalog); await catalog.addNetwork(network);
      final bound = original.change(networkProfileId:network.id,replaceNetwork:true,now:1000); await catalog.update(bound);
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
        pairedTarget:bound.target,deviceKeys:keys,keyHandle:bound.pairingRecord['handle'] as String,
        devicePublicKey:fixtureConfig()['expectedHostKey'] as String,networkBinding:catalog.freezeNetwork(bound))));
      await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect'); await tester.pumpAndSettle();
      expect(find.textContaining('provider_unavailable'),findsOneWidget);
      expect(find.textContaining(network.label),findsOneWidget);
      expect(adapter.calls,0); expect(keys.signCalls,0); expect(keys.creates,0);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    }
  });
}
