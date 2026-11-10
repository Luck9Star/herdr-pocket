import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show SemanticsAction,SemanticsNode;
import 'dart:ui' show Tristate;
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_input_widget_test.dart' as input;
import 'remote_test_data.dart';

/// Static semantics assertions only: no SSH, device store, network or IME claim.
void main() {
  setUp(PairingPage.resetMemorySession); tearDown(PairingPage.resetMemorySession);

  testWidgets('host tab strip stays reachable and exposes selected state to semantics', (tester) async {
    final handle = tester.ensureSemantics();
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final host = tabProfile('A11y tab host','probe','127.0.0.1','direct','opaque-a11y-tab');
    await catalog.add(host);
    final tabs = HostTabs();
    addTearDown(catalog.dispose); addTearDown(tabs.dispose);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,
      offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    final boardSelected = find.semantics.byPredicate((node) {
      final data = node.getSemanticsData();
      return data.label.contains('主机列表') && data.flagsCollection.isSelected == Tristate.isTrue;
    });
    expect(boardSelected,findsOneWidget,reason:'看板 ChoiceChip 激活态需带 selected 语义');
    await tapVisible(tester,'host-open-${host.id}'); await tester.pumpAndSettle();
    // The nested tab navigator's modal barrier must not drop the tab strip.
    expect(find.semantics.byLabel('主机列表'),findsOneWidget,
      reason:'docs/08 按钮有可读名称：打开标签后标签条仍需对读屏可达');
    expect(find.byKey(ValueKey('host-tab-${tabs.tabs.single.id}')),findsOneWidget);
    final tabNode = find.semantics.byPredicate((node) {
      final data = node.getSemanticsData();
      return data.label.contains('A11y tab host') && data.flagsCollection.isSelected == Tristate.isTrue;
    });
    expect(tabNode,findsOneWidget,reason:'docs/08 状态不只靠颜色：激活标签需能被辅助技术读到');
    final tabData = tabNode.evaluate().single.getSemanticsData();
    expect(tabData.hasAction(SemanticsAction.tap),isTrue,reason:'激活标签需可经辅助技术切换');
    expect(tabData.label.trim(),isNotEmpty);
    expect(find.semantics.byPredicate((node) {
      final data = node.getSemanticsData();
      return data.label.contains('主机列表') && data.flagsCollection.isSelected == Tristate.isTrue;
    }),findsNothing,reason:'看板 ChoiceChip 在标签激活后应失去 selected');
    expect(tester.takeException(),isNull);
    handle.dispose();
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('one-shot auxiliary rows keep 48px touch targets at 320px width', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final adapter = input.InputFixtureAdapter();
    await input.start(tester,adapter,width:320);
    await input.mode(tester,'direct');
    for (final name in ['remote-key-Esc','remote-key-Enter','remote-key-Ctrl+C']) {
      final key = find.byKey(ValueKey(name)); await tester.ensureVisible(key); await tester.pump();
      expect(key.hitTestable(),findsOneWidget);
      expect(tester.getSize(key).height,greaterThanOrEqualTo(48),
        reason:'docs/08 触控空间可用：辅助键栏需满足最小可点面积');
    }
    final modifier = find.byKey(const ValueKey('remote-modifier-ctrl'));
    await tester.ensureVisible(modifier); await tester.tap(modifier); await tester.pump(); await tester.pump();
    for (final name in ['remote-base-a','remote-base-space']) {
      final key = find.byKey(ValueKey(name)); await tester.ensureVisible(key); await tester.pump();
      expect(key.hitTestable(),findsOneWidget);
      expect(tester.getSize(key).height,greaterThanOrEqualTo(48));
    }
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });

  testWidgets('auxiliary touch targets survive 1.3x text scale without layout break', (tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 1.3;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final adapter = input.InputFixtureAdapter();
    await input.start(tester,adapter,width:320);
    await input.mode(tester,'direct');
    final key = find.byKey(const ValueKey('remote-key-Esc'));
    await tester.ensureVisible(key); await tester.pump();
    expect(tester.getSize(key).height,greaterThanOrEqualTo(48),
      reason:'docs/08 文字放大与触控空间可用：放大字号后仍需保持最小触控面积');
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });

  testWidgets('catalog add button states its disabled reason at the profile cap', (tester) async {
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    for (var i = 0; i < maxHostProfiles; i++) {
      await catalog.add(tabProfile('Cap host $i','probe','127.0.0.1','direct','opaque-cap-$i'));
    }
    addTearDown(catalog.dispose);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
      offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('hosts-add'))).onPressed,isNull);
    expect(find.byKey(const ValueKey('hosts-add-limit-notice')),findsOneWidget,
      reason:'docs/08 禁用给原因：达到上限而禁用时页面需给出可读原因');
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });

  testWidgets('interactive controls on shell pages expose readable names to semantics', (tester) async {
    final handle = tester.ensureSemantics();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    List<String> unlabeledTaps() {
      final offenders = <String>[];
      bool visit(SemanticsNode node) {
        final data = node.getSemanticsData();
        final parentLabel = node.parent?.getSemanticsData().label.trim() ?? '';
        // A merged control (e.g. CheckboxListTile) nests its inner focus target
        // under the labelled merged node; the name is announced from the parent.
        if (data.hasAction(SemanticsAction.tap) && data.label.trim().isEmpty &&
            data.tooltip.trim().isEmpty && parentLabel.isEmpty) {
          offenders.add('id=${node.id}');
        }
        node.visitChildren(visit);
        return true;
      }
      visit(tester.binding.renderViews.first.owner!.semanticsOwner!.rootSemanticsNode!);
      return offenders;
    }
    final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    await catalog.addNetwork(NetworkProfile.create('a11y-net','tailscale',{'controlUrl':'','hostname':''}));
    addTearDown(catalog.dispose);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
      offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    expect(unlabeledTaps(),isEmpty,reason:'docs/08 按钮有可读名称：主机列表页的可点控件需带可读名称');
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,
      home:NetworkProfilesPage(catalog:catalog,closeTabs:(_) {})));
    await tester.pumpAndSettle();
    expect(unlabeledTaps(),isEmpty,reason:'docs/08 按钮有可读名称：网络管理页的可点控件需带可读名称');
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,
      home:RemotePage(tokens:tokens)));
    await tester.pumpAndSettle();
    expect(unlabeledTaps(),isEmpty,reason:'docs/08 按钮有可读名称：远端接入表单的可点控件需带可读名称');
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,
      home:PairingPage(tokens:tokens,keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String))));
    await tester.pumpAndSettle();
    expect(unlabeledTaps(),isEmpty,reason:'docs/08 按钮有可读名称：配对页的可点控件需带可读名称');
    handle.dispose();
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
}
