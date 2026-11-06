import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'host_catalog_test.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys, tapVisible;
import 'remote_test_data.dart';

void main() {
  testWidgets('restart board opens original identity for review without generating a key or connecting',(tester) async {
    final disk = MemoryCatalogStorage();
    final first = HostCatalog(storage:disk,clock:() => 1000); await first.load(); final profile = await saveCatalogProfile(first);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final reopened = HostCatalog(storage:disk,clock:() => 1001);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:reopened,keys:keys,
      offlineBuilder:(_) => const Scaffold(body:Text('Offline fixture')))));
    await tester.pumpAndSettle();
    expect(find.text('Fixture host'),findsOneWidget); expect(keys.creates,0); expect(keys.signCalls,0);
    await tapVisible(tester,'host-open-${profile.id}'); await tester.pumpAndSettle();
    expect(find.textContaining('本机原身份已匹配'),findsOneWidget);
    expect(find.byKey(const ValueKey('pair-create')),findsNothing);
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    expect(keys.creates,0); expect(keys.signCalls,0);
    await tester.pumpWidget(const SizedBox()); first.dispose(); reopened.dispose();
  });
  testWidgets('catalog reload revokes existing tabs before storage returns',(tester) async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:storage,clock:() => 1000); await catalog.load();
    final profile = await saveCatalogProfile(catalog);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
      keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'host-open-${profile.id}'); await tester.pumpAndSettle();
    final reload = catalog.load();
    await tester.pump();
    expect(find.byKey(ValueKey('host-tab-${profile.id}')),findsNothing);
    await reload; await tester.pumpAndSettle();
    expect(find.byKey(ValueKey('host-tab-${profile.id}')),findsNothing);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('missing or locked original key disables connection and offers only recheck or explicit deletion',(tester) async {
    final disk = MemoryCatalogStorage();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load(); final profile = await saveCatalogProfile(catalog);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String)..locked = true;
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
    await tapVisible(tester,'host-open-${profile.id}'); await tester.pumpAndSettle();
    expect(find.textContaining('原设备密钥丢失'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-connect'))).onPressed,isNull);
    expect(find.byKey(const ValueKey('pair-recheck-key')),findsOneWidget); expect(keys.creates,0); expect(keys.signCalls,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
