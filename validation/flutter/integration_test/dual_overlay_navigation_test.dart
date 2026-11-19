import 'dart:async';
import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';

import '../test/host_catalog_test.dart' show MemoryCatalogStorage, saveCatalogProfile;
import 'dual_overlay_ui_steps.dart';

class DeferredCatalogStorage extends MemoryCatalogStorage {
  final finishLoad = Completer<void>();

  @override
  Future<({String revision, String contents})> load() async {
    await finishLoad.future;
    return super.load();
  }
}

void main() {
  for (final size in [const Size(320, 640), const Size(390, 844)]) {
    testWidgets('home navigation reaches visible destinations once at ${size.width}px', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      final insets = size.width == 320 ? const FakeViewPadding(top: 24, bottom: 24)
          : const FakeViewPadding(top: 47, bottom: 34);
      tester.view.padding = insets;
      tester.view.viewPadding = insets;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetPadding);
      addTearDown(tester.view.resetViewPadding);

      final exchange = Directory.systemTemp.createTempSync('dual-overlay-nav-');
      addTearDown(() => exchange.deleteSync(recursive: true));
      final storage = DeferredCatalogStorage();
      final catalog = HostCatalog(storage: storage, clock: () => 1000);
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: HostCatalogPage(
        catalog: catalog, tokens: tokens, offlineBuilder: (_) => const SizedBox(),
      )));
      final steps = DualOverlayUiSteps(tester, exchange);
      final networks = find.byKey(const ValueKey('hosts-networks'));
      final home = find.byKey(const ValueKey('host-catalog-list'));
      final networkPage = find.byType(NetworkProfilesPage);
      final networkTitle = find.descendant(of: networkPage, matching: find.text('网络配置'));
      final settings = find.byKey(const ValueKey('hosts-terminal-preferences'));
      final terminals = find.text('暂无打开的本地视图 · 请先在看板选择主机');
      var pointerDowns = 0;
      void recordPointer(PointerEvent event) {
        if (event is PointerDownEvent) pointerDowns++;
      }
      GestureBinding.instance.pointerRouter.addGlobalRoute(recordPointer);
      addTearDown(() => GestureBinding.instance.pointerRouter.removeGlobalRoute(recordPointer));
      Future<void> go(int index, Finder destination) async {
        final before = pointerDowns;
        await steps.navigation(index);
        expect(pointerDowns, before + 1);
        expect(destination.hitTestable(), findsOneWidget);
      }

      expect(catalog.ready, isFalse);
      expect(tester.widget(networks), isA<NavigationDestination>());
      expect(networkTitle.hitTestable(), findsNothing);
      // Load while the driver's initial pointer target is being resolved.
      Timer(const Duration(milliseconds: 10), storage.finishLoad.complete);
      await go(2, networkTitle);
      expect(catalog.ready, isTrue);
      expect(tester.widget<NetworkProfilesPage>(networkPage).catalog, same(catalog));
      await go(0, home);
      expect(tester.widget(networks), isA<InkWell>());
      await go(2, networkTitle);
      await go(0, home);
      await go(1, terminals);
      await go(0, home);
      await go(3, settings);
      await go(0, home);

      await saveCatalogProfile(catalog);
      await tester.pump();
      expect(catalog.profiles, hasLength(1));
      expect(tester.widget(networks), isA<NavigationDestination>());
      await go(2, networkTitle);
      await go(0, home);
      await go(1, terminals);
      await go(3, settings);
      await go(0, home);
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
    });
  }
}
