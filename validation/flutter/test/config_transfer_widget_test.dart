import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/config_transfer_page.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage,saveCatalogProfile;
import 'config_transfer_test.dart' show portable,transferGolden,unhex;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

class MemoryConfigDocuments implements ConfigDocuments {
  Uint8List? opened;
  int saves = 0,opens = 0;
  @override Future<Uint8List?> open() async { opens++; return opened; }
  @override Future<bool> save(Uint8List archive) async { saves++; return false; }
}

class ImportTestDeviceKeys extends TestDeviceKeys {
  ImportTestDeviceKeys() : super(OpenSSHEd25519KeyPair(
    Uint8List.fromList(List.filled(32, 1)), Uint8List(64), 'parser-only-import').toPem());

  @override Future<String> create() async {
    ready();
    creates++;
    return 'migration-test-fresh-handle';
  }
}

void main() {
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);
  for (final (width, saved) in [(390.0, false), (800.0, true), (1120.0, false)]) {
    testWidgets('host board imports public data before explicit pairing at ${width.toInt()} pt', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(width, 860);
      addTearDown(tester.view.reset);
      final disk = MemoryCatalogStorage(), tabs = HostTabs();
      final catalog = HostCatalog(storage:disk, clock:() => 1000);
      await catalog.load();
      final existing = saved ? await saveCatalogProfile(catalog) : null;
      final beforeImport = disk.writes, initialCount = catalog.profiles.length;
      final keys = ImportTestDeviceKeys();
      final fixture = transferGolden(), calls = <String>[];
      final messenger = tester.binding.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(NativeConfigDocuments.channel, (call) async {
        calls.add(call.method);
        expect(call.method, 'open');
        return unhex(fixture['archiveHex'] as String);
      });
      addTearDown(() => messenger.setMockMethodCallHandler(NativeConfigDocuments.channel, null));
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      Finder key(String name) => find.byKey(ValueKey(name));
      FilledButton button(String name) => tester.widget<FilledButton>(key(name));
      await tester.pumpWidget(MaterialApp(theme:tokens.theme, home:HostCatalogPage(
        tokens:tokens, catalog:catalog, tabs:tabs, keys:keys, offlineBuilder:(_) => const SizedBox())));
      await tester.pumpAndSettle();
      expect(key('home-empty-card'), saved ? findsNothing : findsOneWidget);
      await tapVisible(tester, 'home-tab-3');
      await tapVisible(tester, 'hosts-transfer');
      await tester.pumpAndSettle();
      expect(find.byType(ConfigTransferPage), findsOneWidget);
      await tapVisible(tester, 'transfer-open');
      await tester.enterText(key('transfer-password'), fixture['password'] as String);
      await tester.pump();
      await tapVisible(tester, 'transfer-decrypt');
      final preview = key('transfer-choice-0');
      // PBKDF2 runs in a real isolate while widget-test timers are simulated.
      for (var i = 0; i < 300 && preview.evaluate().isEmpty; i++) {
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
        await tester.pump();
      }
      expect(preview, findsOneWidget);
      expect(disk.writes, beforeImport);
      expect(button('transfer-apply').onPressed, isNull);
      await tapVisible(tester, 'transfer-choice-0');
      await tester.tap(find.text('添加新条目（不复用身份）').hitTestable());
      await tester.pumpAndSettle();
      expect(button('transfer-apply').onPressed, isNull);
      await tapVisible(tester, 'transfer-review');
      expect(button('transfer-apply').onPressed, isNotNull);
      await tapVisible(tester, 'transfer-apply');
      await tester.pumpAndSettle();
      expect(disk.writes, beforeImport + 1);
      expect(calls, ['open']);
      expect(catalog.profiles.length, initialCount + 1);
      final imported = catalog.profiles.singleWhere((profile) => profile.id != existing?.id);
      expect(imported.target['host'], 'fixture.invalid');
      expect(imported.hasIdentity, isFalse);
      expect(imported.toJson()['pairing'], isNull);

      await tester.pageBack();
      await tester.pumpAndSettle();
      if (width < 700) {
        final board = find.byWidgetPredicate((widget) => widget is NavigationDestination && widget.label == '看板');
        expect(board.hitTestable(), findsOneWidget);
        await tester.tap(board.hitTestable());
      } else {
        await tapVisible(tester, width < 960 ? 'home-tab-0' : 'hosts-board-tab');
      }
      await tester.pumpAndSettle();
      expect(key('home-empty-card'), findsNothing);
      expect(find.textContaining('导入未配对'), findsOneWidget);
      await tapVisible(tester, 'host-open-${imported.id}');
      await tester.pumpAndSettle();
      expect(tester.widget<PairingPage>(find.byType(PairingPage)).profileId, imported.id);
      for (final field in transferTargetFields) {
        expect(tester.widget<TextField>(key('pair-$field')).controller!.text, imported.target[field].toString());
      }
      expect(key('pair-request'), findsNothing);
      expect(key('pair-connect'), findsNothing);
      expect(button('pair-create').onPressed, isNull);
      expect(keys.creates, 0);
      expect(keys.signCalls, 0);
      expect(catalog.pendingCreation, isNull);
      expect(disk.writes, beforeImport + 1);
      expect(tabs.tabs, isEmpty);

      await tapVisible(tester, 'pair-target-review');
      expect(button('pair-create').onPressed, isNotNull);
      expect(keys.creates, 0);
      await tapVisible(tester, 'pair-create');
      await tester.pumpAndSettle();
      expect(key('pair-request'), findsOneWidget);
      expect(key('pair-connect'), findsNothing);
      expect(find.textContaining('等待主机审查 · 授权结果未知'), findsOneWidget);
      expect(keys.creates, 1);
      expect(keys.signCalls, 0);
      expect(tabs.tabs, isEmpty);
      expect(catalog.profiles.length, initialCount + 1);
      final paired = catalog.profiles.singleWhere((profile) => profile.id != existing?.id);
      expect(paired.hasIdentity, isTrue);
      final request = paired.pairingRecord['request'] as Map;
      expect(request['issued_at'], catalog.clock());
      expect(paired.id, isNot(imported.id));
      expect(catalog.pendingCreation, isNull);
      if (existing != null) {
        final retained = catalog.profiles.singleWhere((profile) => profile.id == existing.id);
        expect(retained.pairingRecord, existing.pairingRecord);
        expect(paired.pairingRecord['handle'], isNot(retained.pairingRecord['handle']));
        expect(request['public_key'], isNot((retained.pairingRecord['request'] as Map)['public_key']));
      }
      await tester.pumpWidget(const SizedBox());
      tabs.dispose();
      catalog.dispose();
    });
  }
  testWidgets('imported profile board disable, re-enable and delete never restore or delete an absent device identity', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final imported = HostProfile.imported(portable(),1000); await catalog.add(imported);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
    expect(catalog.profiles.single.hasIdentity,isFalse); expect(tester.takeException(),isNull);
    await tapVisible(tester,'host-management-${imported.id}'); await tester.pumpAndSettle();
    await tapVisible(tester,'host-disable-${imported.id}'); await tester.pumpAndSettle();
    expect(catalog.profiles.single.enabled,isFalse); expect(catalog.profiles.single.hasIdentity,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(ValueKey('host-open-${imported.id}'))).onPressed,isNull);
    await tapVisible(tester,'host-disable-${imported.id}'); await tester.pumpAndSettle();
    expect(catalog.profiles.single.enabled,isTrue); expect(catalog.profiles.single.hasIdentity,isFalse);
    await tapVisible(tester,'host-delete-${imported.id}'); await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton,'仅删除本机')); await tester.pumpAndSettle();
    expect(catalog.profiles,isEmpty); expect(keys.deleted,isFalse); expect(keys.creates,0); expect(keys.signCalls,0);
    expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('file cancellation and malformed envelope never create a plan, write catalog, or expose identity export', (tester) async {
    final disk = MemoryCatalogStorage(), documents = MemoryConfigDocuments();
    final catalog = HostCatalog(storage:disk,clock:() => 1000); await catalog.load();
    await catalog.add(HostProfile.imported(portable(),1000)); final writes = disk.writes;
    await tester.pumpWidget(MaterialApp(home:ConfigTransferPage(catalog:catalog,documents:documents,closeTabs:(_) {})));
    await tester.pumpAndSettle();
    final password = tester.widget<TextField>(find.byKey(const ValueKey('transfer-password')));
    expect(password.obscureText,isTrue); expect(password.enableIMEPersonalizedLearning,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('transfer-export'))).onPressed,isNull);
    await tapVisible(tester,'transfer-open'); await tester.pumpAndSettle();
    expect(find.textContaining('已取消打开文件'),findsOneWidget);
    documents.opened = Uint8List(51);
    await tapVisible(tester,'transfer-open'); await tester.pumpAndSettle();
    expect(find.textContaining('格式、大小或公开字段'),findsOneWidget);
    expect(find.byKey(const ValueKey('transfer-apply')),findsNothing);
    expect(documents.saves,0); expect(disk.writes,writes);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  testWidgets('pending identity creation disables the entire transfer path', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    await catalog.beginCreation(fixtureConfig(),'Unresolved creation');
    final documents = MemoryConfigDocuments();
    await tester.pumpWidget(MaterialApp(home:ConfigTransferPage(catalog:catalog,documents:documents,closeTabs:(_) {})));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('transfer-open'))).onPressed,isNull);
    expect(tester.widget<TextField>(find.byKey(const ValueKey('transfer-password'))).enabled,isFalse);
    expect(documents.opens,0); expect(find.textContaining('身份创建操作'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
}
