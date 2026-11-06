import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'host_tabs_widget_test.dart' show TabFixtureAdapter;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

void main() {
  test('legacy preferences default to 14; schema4 rejects missing required roots and invalid preference fields',() async {
    final storage = MemoryCatalogStorage();
    storage.revision = List.filled(64,'a').join();
    storage.contents = jsonEncode({'schemaVersion':4,'profiles':[],'networkProfiles':[],'pendingCreation':null});
    final legacy = HostCatalog(storage:storage); await legacy.load();
    expect(legacy.ready,isTrue); expect(legacy.terminalFontSize,14); await legacy.updateTerminalFontSize(28);
    expect((jsonDecode(storage.contents)['preferences'] as Map)['terminalFontSize'],28); legacy.dispose();
    for (final prefs in [{'terminalFontSize':9},{'terminalFontSize':29},{'terminalFontSize':14.0},{'terminalFontSize':14,'secret':'rejected'},null]) {
      storage.contents = jsonEncode({'schemaVersion':4,'profiles':[],'networkProfiles':[],'pendingCreation':null,'preferences':prefs});
      final catalog = HostCatalog(storage:storage); await catalog.load(); expect(catalog.ready,isFalse); catalog.dispose();
    }
    storage.contents = jsonEncode({'schemaVersion':4,'profiles':[],'networkProfiles':[],'preferences':{'terminalFontSize':14}});
    final missing = HostCatalog(storage:storage); await missing.load(); expect(missing.ready,isFalse); missing.dispose();
  });
  testWidgets('normal mobile board exposes terminal display preference with durable save',(tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(360,780);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final storage = MemoryCatalogStorage();
    final active = HostCatalog(storage:storage,clock:() => 1000); await active.load();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:active,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'hosts-terminal-preferences'); await tester.pumpAndSettle();
    final slider = tester.widget<Slider>(find.byKey(const ValueKey('terminal-font-slider'))); slider.onChanged!(20);
    await tester.pump(); await tapVisible(tester,'terminal-font-save'); await tester.pumpAndSettle();
    expect(active.terminalFontSize,20); expect(find.textContaining('20 px'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); active.dispose();
    final reopened = HostCatalog(storage:storage,clock:() => 1000); await reopened.load(); expect(reopened.terminalFontSize,20); reopened.dispose();
  });
  testWidgets('font preference changes local TerminalStyle without reconnecting, replaying or resizing fixed PTY',(tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile = await saveCatalogProfile(catalog),adapter = TabFixtureAdapter();
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,
      pairedTarget:profile.target,deviceKeys:keys,keyHandle:profile.pairingRecord['handle'] as String,
      devicePublicKey:(profile.pairingRecord['request'] as Map)['public_key'] as String,networkBinding:catalog.freezeNetwork(profile))));
    await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
    adapter.publish(); await tester.pump(); await tapVisible(tester,'remote-pane-w1:p1');
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'LOCAL FONT TEST')); await tester.pump();
    final calls = adapter.calls,generation = adapter.generation;
    expect(tester.widget<TerminalView>(find.byType(TerminalView)).textStyle.fontSize,14);
    await catalog.updateTerminalFontSize(24); await tester.pump();
    final view = tester.widget<TerminalView>(find.byType(TerminalView));
    expect(view.textStyle.fontSize,24); expect(view.autoResize,isFalse);
    expect(adapter.calls,calls); expect(adapter.generation,generation); expect(keys.signCalls,0);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
