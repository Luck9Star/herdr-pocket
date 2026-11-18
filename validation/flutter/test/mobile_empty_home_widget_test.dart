import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;

void main() {
  for (final size in [const Size(320, 640), const Size(390, 844)]) {
    testWidgets('empty mobile home and real connection routes at $size', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      final inset = size.width == 320 ? const FakeViewPadding(top: 24, bottom: 24)
          : const FakeViewPadding(top: 47, bottom: 34);
      tester.view.padding = inset; tester.view.viewPadding = inset;
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetPadding); addTearDown(tester.view.resetViewPadding);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
        tokens: tokens, catalog: catalog, offlineBuilder: (_) => const Text('实验室'))));
      await tester.pumpAndSettle();
      Finder key(String id) => find.byKey(ValueKey(id));
      void rect(String id, Rect expected) {
        final actual = tester.getRect(key(id));
        expect((actual.left - expected.left).abs(), lessThanOrEqualTo(2), reason: id);
        expect((actual.top - expected.top).abs(), lessThanOrEqualTo(2), reason: id);
        expect((actual.width - expected.width).abs(), lessThanOrEqualTo(2), reason: id);
        expect((actual.height - expected.height).abs(), lessThanOrEqualTo(2), reason: id);
      }
      final margin = size.width == 320 ? 16.0 : 24.0;
      final top = inset.top; final span = size.width - margin * 2;
      rect('home-brand', Rect.fromLTWH(margin, top + 16, span, 44));
      rect('home-empty-card', Rect.fromLTWH(margin, top + 88, span, 268));
      rect('hosts-add', Rect.fromLTWH(margin + 16, top + 232, span - 32, 48));
      rect('hosts-direct-ssh', Rect.fromLTWH(margin + 16, top + 292, span - 32, 48));
      rect('home-tabs', Rect.fromLTWH(0, size.height - inset.bottom - 56, size.width, 56));
      for (var i = 0; i < 4; i++) {
        final id = i == 2 ? 'hosts-networks' : 'home-tab-$i';
        rect(id, Rect.fromLTWH(i * size.width / 4, size.height - inset.bottom - 56, size.width / 4, 56));
        expect(key(id).hitTestable(), findsOneWidget);
      }
      await tester.tap(key('hosts-networks')); await tester.pumpAndSettle();
      expect(find.byType(NetworkProfilesPage), findsOneWidget);
      await tester.tap(find.widgetWithText(NavigationDestination, '看板')); await tester.pumpAndSettle();
      expect(key('hosts-add').hitTestable(), findsOneWidget);
      expect(key('hosts-direct-ssh').hitTestable(), findsOneWidget);
      await tester.tap(key('hosts-add')); await tester.pumpAndSettle();
      rect('choose-header', Rect.fromLTWH(0, top, size.width, 56));
      rect('choose-back', Rect.fromLTWH(margin - 8, top + 6, 44, 44));
      rect('choose-ssh', Rect.fromLTWH(margin, top + 124, span, 100));
      rect('choose-herdr', Rect.fromLTWH(margin, top + 236, span, 100));
      expect(key('choose-ssh').hitTestable(), findsOneWidget);
      expect(key('choose-herdr').hitTestable(), findsOneWidget);
      await tester.tap(key('choose-herdr')); await tester.pumpAndSettle();
      expect(find.text('设备配对'), findsOneWidget);
      await tester.pageBack(); await tester.pumpAndSettle();
      await tester.tap(key('hosts-add')); await tester.pumpAndSettle();
      await tester.tap(key('choose-ssh')); await tester.pumpAndSettle();
      expect(key('direct-host'), findsOneWidget);
      await tester.pageBack(); await tester.pumpAndSettle();
      await tester.tap(key('hosts-direct-ssh')); await tester.pumpAndSettle();
      expect(key('direct-host'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    });
  }
  testWidgets('320pt at 200% retains complete text and accessible routes', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320, 640);
    tester.view.padding = const FakeViewPadding(top: 24, bottom: 24);
    tester.view.viewPadding = const FakeViewPadding(top: 24, bottom: 24);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetPadding); addTearDown(tester.view.resetViewPadding);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
    await catalog.load();
    final scale = ValueNotifier<double>(2); addTearDown(scale.dispose);
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, builder: (context, child) => ValueListenableBuilder<double>(
      valueListenable: scale, builder: (context, value, _) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(value)), child: child!)),
      home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const Text('实验室'))));
    await tester.pumpAndSettle();
    Finder key(String id) => find.byKey(ValueKey(id));
    expect(find.text('添加主机后，在这里查看会话和任务状态。'), findsOneWidget);
    expect(tester.widget<Text>(find.text('添加主机后，在这里查看会话和任务状态。')).maxLines, isNull);
    await tester.ensureVisible(key('hosts-direct-ssh')); await tester.pumpAndSettle();
    expect(key('hosts-direct-ssh').hitTestable(), findsOneWidget);
    await tester.tap(key('hosts-direct-ssh')); await tester.pumpAndSettle();
    expect(key('direct-host'), findsOneWidget);
    await tester.pageBack(); await tester.pumpAndSettle();
    expect(tester.widget(key('hosts-networks')), isA<NavigationDestination>());
    await tester.tap(key('hosts-networks')); await tester.pumpAndSettle();
    expect(find.byType(NetworkProfilesPage), findsOneWidget);
    await tester.tap(find.widgetWithText(NavigationDestination, '看板')); await tester.pumpAndSettle();
    await tester.ensureVisible(key('hosts-add')); await tester.pumpAndSettle();
    expect(key('hosts-add').hitTestable(), findsOneWidget);
    await tester.tap(key('hosts-add')); await tester.pumpAndSettle();
    expect(find.text('使用服务器密码或已有私钥打开远程 Shell。'), findsOneWidget);
    expect(find.text('接入 herdr 工作台，查看会话和任务。'), findsOneWidget);
    expect(tester.widget<Text>(find.text('使用服务器密码或已有私钥打开远程 Shell。')).maxLines, isNull);
    expect(tester.widget<Text>(find.text('接入 herdr 工作台，查看会话和任务。')).maxLines, isNull);
    await tester.ensureVisible(key('choose-herdr')); await tester.pumpAndSettle();
    expect(key('choose-herdr').hitTestable(), findsOneWidget);
    await tester.ensureVisible(key('choose-ssh')); await tester.pumpAndSettle();
    expect(key('choose-ssh').hitTestable(), findsOneWidget);
    await tester.tap(key('choose-ssh')); await tester.pumpAndSettle();
    expect(key('direct-host'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });

}
