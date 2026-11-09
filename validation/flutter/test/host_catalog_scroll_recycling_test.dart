import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'pairing_gui_test.dart' show TestDeviceKeys;
import 'remote_test_data.dart' show fixtureConfig;

/// The board is a lazy ListView: scrolling a host card into view evicts the
/// header controls (search field, task filter, add and network buttons) from
/// the widget tree. A caller that waits for one of those controls without
/// scrolling back sees it never appear. These cases pin the recovery the
/// on-device integration test relies on: every header control stays
/// reachable through scrollUntilVisible, and the completion notice at the
/// list top is readable again after the list is scrolled away.
Future<void> mountBoard(WidgetTester tester, HostCatalog catalog, HostTabs tabs,
    TestDeviceKeys keys) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(390, 844);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final tokens = (await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme: tokens.theme,
    home: HostCatalogPage(tokens: tokens, catalog: catalog, tabs: tabs,
      keys: keys, adapterFactory: (_) => throw StateError('search must not create an adapter'),
      offlineBuilder: (_) => const SizedBox())));
  await tester.pumpAndSettle();
}

Finder boardList() => find.byKey(const ValueKey('host-catalog-list'));
Finder byKeyOf(String key) => find.byKey(ValueKey(key));
Finder boardScrollable() =>
    find.descendant(of: boardList(), matching: find.byType(Scrollable)).first;

void main() {
  testWidgets('header controls stay reachable after the board scrolls deep',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a=tabProfile('Host A','Build-Session','100.64.0.1','direct','opaque-a');
    final b=tabProfile('Host B','Other-Session','100.64.0.2','direct','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mountBoard(tester,catalog,tabs,keys);

    // Scroll a host card into view, which evicts the header rows.
    tester.state<ScrollableState>(boardScrollable()).position.jumpTo(400);
    await tester.pump();
    for (final key in ['hosts-add','hosts-networks','hosts-search','hosts-task-filter']) {
      expect(byKeyOf(key).evaluate().length,0,
        reason:'$key should be recycled once the board scrolled away');
    }
    // Each header control comes back through the same scroll the device test uses.
    for (final key in ['hosts-add','hosts-networks','hosts-search','hosts-task-filter']) {
      await tester.scrollUntilVisible(byKeyOf(key),-300,scrollable:boardScrollable());
      await tester.pump();
      expect(byKeyOf(key).evaluate().length,1,
        reason:'$key must be reachable again after scrolling back');
    }
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });

  testWidgets('the completion notice at the list top is readable again after scrolling away',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    // Two hosts make the board tall enough that the delete button sits below
    // the fold and the completion notice (rendered at the list top) is
    // recycled while the board is scrolled down.
    final a=tabProfile('Host A','Build-Session','100.64.0.1','direct','opaque-a');
    final b=tabProfile('Host B','Other-Session','100.64.0.2','direct','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mountBoard(tester,catalog,tabs,keys);

    // Scroll the delete button into view, which leaves the list top recycled.
    final deleteControl=find.byKey(ValueKey('host-delete-${a.id}'));
    await tester.scrollUntilVisible(deleteControl,300,scrollable:boardScrollable());
    await tester.pump();
    await tester.tap(deleteControl); await tester.pumpAndSettle();
    expect(find.text('删除本机资料与设备身份'),findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton,'仅删除本机'));
    await tester.pumpAndSettle();
    // The deletion itself has completed...
    expect(catalog.profiles.any((profile) => profile.id == a.id),isFalse);
    // ...but its notice row is still out of the tree while the board stays
    // scrolled; a caller that waits for the text without scrolling spins.
    expect(find.textContaining('本机已删除 · 主机授权未因此撤销').evaluate().isEmpty,isTrue,
      reason:'the notice must be recycled while the board is scrolled away');
    // Scrolling back to the top rebuilds the notice row.
    tester.state<ScrollableState>(boardScrollable()).position.jumpTo(0);
    await tester.pump();
    expect(find.textContaining('本机已删除 · 主机授权未因此撤销'),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
