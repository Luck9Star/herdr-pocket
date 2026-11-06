import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer.dart';
import 'package:herdr_flutter_probe/config_transfer_page.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'config_transfer_test.dart' show portable;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

class MemoryConfigDocuments implements ConfigDocuments {
  Uint8List? opened;
  int saves = 0,opens = 0;
  @override Future<Uint8List?> open() async { opens++; return opened; }
  @override Future<bool> save(Uint8List archive) async { saves++; return false; }
}
void main() {
  testWidgets('normal host board opens imported metadata in formal explicit pairing without inheriting identity', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final imported = HostProfile.imported(portable(),1000); await catalog.add(imported);
    final keys = TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,keys:keys,
      offlineBuilder:(_) => const SizedBox()))); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('hosts-transfer')),findsOneWidget);
    expect(find.textContaining('导入未配对'),findsOneWidget); expect(keys.creates,0); expect(keys.signCalls,0);
    await tapVisible(tester,'host-open-${imported.id}'); await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const ValueKey('pair-host'))).controller!.text,'fixture.invalid');
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('pair-request')),findsOneWidget); expect(keys.creates,1); expect(keys.signCalls,0);
    expect(catalog.profiles.length,1); expect(catalog.profiles.single.hasIdentity,isTrue);
    expect(catalog.profiles.single.id,isNot(imported.id)); expect(catalog.pendingCreation,isNull);
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
