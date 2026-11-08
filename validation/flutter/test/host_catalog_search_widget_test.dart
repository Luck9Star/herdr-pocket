import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_catalog_search.dart';
import 'package:herdr_flutter_probe/host_task_summary.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_search_cases.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'host_task_summary_test.dart' show summaryBoard;
import 'host_task_summary_widget_test.dart' as summary_ui;
import 'network_profiles_test.dart' show testNetwork;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible;
import 'remote_test_data.dart';

Future<void> mount(WidgetTester tester,HostCatalog catalog,HostTabs tabs,TestDeviceKeys keys,{double width=390}) async {
  tester.view.devicePixelRatio=1; tester.view.physicalSize=Size(width,844);
  addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
  final tokens=(await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,
    tabs:tabs,keys:keys,adapterFactory:(_) => throw StateError('search must not create an adapter'),
    offlineBuilder:(_) => const SizedBox())));
  await tester.pumpAndSettle();
}
Future<void> query(WidgetTester tester,String value) async {
  final field=find.byKey(const ValueKey('hosts-search'));
  await tester.ensureVisible(field); await tester.enterText(field,value); await tester.pump();
}
HostTaskSummaries pageSummaries(WidgetTester tester) {
  final dynamic state=tester.state(find.byType(HostCatalogPage));
  return state.summaries as HostTaskSummaries;
}
String count(WidgetTester tester) => tester.widget<Text>(find.byKey(const ValueKey('hosts-filter-count'))).data!;
Future<void> chooseStatus(WidgetTester tester,String label) async {
  await tapVisible(tester,'hosts-task-filter'); await tester.pumpAndSettle();
  await tester.tap(find.text(label).last); await tester.pumpAndSettle();
}

void main() {
  hostCatalogSearchCases((name,body) => test(name,body));
  testWidgets('rapid local search keeps IME composing and row identity without connecting',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a=tabProfile('Same host','Build-Session','100.64.0.1','tailscale','opaque-search-secret');
    final b=tabProfile('Same host','Other-Session','dev.example.test','direct','opaque-b');
    await catalog.add(a); await catalog.add(b);
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mount(tester,catalog,tabs,keys,width:320);
    for (final value in ['same','no-match','TAILSCALE','dev.example','Build-Session','opaque-search-secret']) {
      await query(tester,value);
      expect(tabs.tabs,isEmpty); expect(keys.signCalls,0); expect(keys.creates,0);
    }
    expect(find.byKey(const ValueKey('hosts-search-empty')),findsOneWidget);
    await query(tester,'same');
    final field=find.byKey(const ValueKey('hosts-search'));
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'Same',selection:TextSelection.collapsed(offset:4),composing:TextRange(start:0,end:4)));
    await tester.pump();
    expect(tester.widget<TextField>(field).controller!.value.composing,const TextRange(start:0,end:4));
    expect(find.byKey(ValueKey('host-open-${a.id}')),findsOneWidget);
    expect(find.byKey(ValueKey('host-open-${b.id}')),findsOneWidget);
    expect(find.byKey(ValueKey('host-card-${a.id}')),findsOneWidget);
    expect(find.textContaining('旧 provider 标签 tailscale 仅为资料'),findsOneWidget);
    await tapVisible(tester,'hosts-search-clear'); await tester.pump();
    expect(tester.widget<TextField>(field).controller!.text,isEmpty);
    expect(count(tester),'显示 2 / 2 台主机'); expect(tabs.tabs,isEmpty);
    expect(keys.signCalls,0); expect(keys.creates,0); expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('pending-only composes with search and changes with fresh dashboard authority',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final a=tabProfile('Same host','Build','100.64.0.1','direct','a');
    final b=tabProfile('Same host','Other','100.64.0.2','direct','b');
    await catalog.add(a); await catalog.add(b);
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mount(tester,catalog,tabs,keys);
    final registry=pageSummaries(tester),lease=registry.open(a),attempt=lease.begin()!;
    attempt.publish(summaryBoard(a)); await tester.pump(); await tester.pump();
    await chooseStatus(tester,'当前待处理（1）');
    expect(count(tester),'显示 1 / 2 台主机');
    await query(tester,'Other'); expect(count(tester),'显示 0 / 2 台主机');
    expect(find.text('当前待处理（1）'),findsWidgets);
    await tapVisible(tester,'hosts-search-clear'); await tester.pump();
    expect(tester.widget<DropdownButton<HostTaskFilter>>(find.byKey(const ValueKey('hosts-task-filter'))).value,HostTaskFilter.current);
    expect(count(tester),'显示 1 / 2 台主机');
    attempt.publish(summaryBoard(a,revision:2,freshness:DashboardFreshness.unavailable));
    await tester.pump(); await tester.pump();
    expect(count(tester),'显示 0 / 2 台主机'); expect(find.text('当前待处理（0）'),findsWidgets);
    await chooseStatus(tester,'上次受阻，待核查（1）');
    expect(count(tester),'显示 1 / 2 台主机');
    await query(tester,'no-match'); expect(count(tester),'显示 0 / 2 台主机');
    await tapVisible(tester,'hosts-search-clear'); await tester.pump();
    expect(tester.widget<DropdownButton<HostTaskFilter>>(find.byKey(const ValueKey('hosts-task-filter'))).value,HostTaskFilter.history);
    expect(count(tester),'显示 1 / 2 台主机');
    await chooseStatus(tester,'当前待处理（0）');
    attempt.publish(summaryBoard(a,revision:3)); await tester.pump(); await tester.pump();
    expect(count(tester),'显示 1 / 2 台主机');
    lease.invalidate(); await tester.pump(); await tester.pump();
    expect(count(tester),'显示 0 / 2 台主机');
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('hosts-add'))).onPressed,isNotNull);
    await tapVisible(tester,'hosts-filters-reset'); await tester.pump();
    expect(count(tester),'显示 2 / 2 台主机');
    expect(tester.widget<DropdownButton<HostTaskFilter>>(find.byKey(const ValueKey('hosts-task-filter'))).value,HostTaskFilter.all);
    expect(tabs.tabs,isEmpty); expect(keys.signCalls,0); expect(keys.creates,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('empty catalog preserves the ordinary add and network controls',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mount(tester,catalog,tabs,keys);
    expect(find.byKey(const ValueKey('hosts-search')),findsNothing);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('hosts-add'))).onPressed,isNotNull);
    expect(find.byKey(const ValueKey('hosts-networks')),findsOneWidget);
    expect(tabs.tabs,isEmpty); expect(keys.signCalls,0); expect(keys.creates,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('normal return home makes the exact blocked task searchable as history and recheckable',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Review host','Review-Work','100.64.0.1','direct','review'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,summary_ui.SummaryWidgetAdapter>{};
    await summary_ui.setup(tester,catalog,tabs,adapters,width:320);
    final adapter=await summary_ui.connectHost(tester,profile,adapters);
    adapter.emit(blocked:1); await summary_ui.pumpReports(tester);
    final original=tabs.active!.id;
    await tapVisible(tester,'hosts-board-tab'); await tester.pumpAndSettle();
    expect(adapter.pauses,1);
    await chooseStatus(tester,'上次受阻，待核查（1）');
    await query(tester,'review-work'); expect(count(tester),'显示 1 / 1 台主机');
    expect(tester.widget<DropdownButton<HostTaskFilter>>(find.byKey(const ValueKey('hosts-task-filter'))).value,HostTaskFilter.history);
    await tapVisible(tester,blockedSummaryGroupKey(profile.id)); await tester.pumpAndSettle();
    expect(find.text('上次报告 · 点击后重新核查此目标'),findsOneWidget);
    const pane=RemotePane('w1:p1','term_abcd',agentStatus:'blocked');
    await tapVisible(tester,blockedSummaryTargetKey(profile.id,pane)); await tester.pumpAndSettle();
    expect(tabs.tabs.length,2); expect(tabs.active!.id,isNot(original));
    expect(tabs.active!.requestedTarget!.paneId,pane.paneId);
    expect(tabs.active!.requestedTarget!.terminalId,pane.terminalId);
    expect(adapter.calls,1); expect(adapter.writes,0);
    expect(adapters[profile.id]!.calls,0); expect(adapters[profile.id]!.writes,0);
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('search follows current local network binding without opening a transport',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tail=testNetwork(),easy=testNetwork('easytier'); await catalog.addNetwork(tail); await catalog.addNetwork(easy);
    final profile=tabProfile('Neutral host','Build','100.64.0.1','direct','binding').change(
      networkProfileId:tail.id,replaceNetwork:true,now:1000);
    await catalog.add(profile);
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
    await mount(tester,catalog,tabs,keys);
    await query(tester,'tailscale'); expect(count(tester),'显示 1 / 1 台主机');
    await query(tester,'direct'); expect(count(tester),'显示 0 / 1 台主机');
    await catalog.update(profile.change(networkProfileId:easy.id,replaceNetwork:true,now:1000));
    await tester.pump();
    await query(tester,'tailscale'); expect(count(tester),'显示 0 / 1 台主机');
    await query(tester,'easytier'); expect(count(tester),'显示 1 / 1 台主机');
    // Simulate an unavailable binding record without mutating the saved host.
    catalog.networkProfiles=const [];
    await query(tester,'');
    expect(find.textContaining('网络绑定资料缺失'),findsOneWidget);
    expect(find.textContaining('无法确认实际路径'),findsOneWidget);
    expect(find.textContaining('网络绑定：null'),findsNothing);
    expect(tabs.tabs,isEmpty); expect(keys.signCalls,0); expect(keys.creates,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
