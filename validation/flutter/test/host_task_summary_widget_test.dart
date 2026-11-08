import 'dart:typed_data';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show TabFixtureAdapter,tabProfile;
import 'pairing_gui_test.dart' show TestDeviceKeys,tapVisible,fillPairTarget,acceptResponse,authorizedResponse;
import 'host_task_summary_test.dart' show summaryBoard;
import 'remote_page_test.dart' show restoreResumedLifecycle;
import 'remote_test_data.dart';

/// Explicit public-source UI double; no native loader, SSH or external host.
class SummaryWidgetAdapter extends TabFixtureAdapter {
  int writes=0;
  @override Future<RemoteInputResult> sendInput(RemoteInputTarget target,Uint8List bytes,{required bool Function() stillCurrent}) async {
    writes++; return const RemoteInputResult.rejected('unexpected_summary_write');
  }
  void emit({int blocked=2,bool empty=false,bool unknown=false,DashboardFreshness freshness=DashboardFreshness.fresh,int observationEpoch=0,DateTime? at}) {
    latestDashboard=RemoteDashboard(generation,config.session,empty ? const [] : [
      RemotePane('w1:p1','term_abcd',agentStatus:blocked>0 ? 'blocked' : 'idle'),
      for(var i=1;i<blocked;i++) RemotePane('w1:p${i+1}','term_extra$i',agentStatus:'blocked'),
      if(unknown) const RemotePane('w1:p99','term_unknown'),
    ],freshness:freshness,revision:++boardRevision,syncedAt:at ?? DateTime.utc(2026,11,7,10),
      source:RemoteDashboardSource.connected(config,'system'),observationEpoch:observationEpoch);
    dashboard!(latestDashboard!);
  }
}
Future<void> pumpReports(WidgetTester tester) async { await tester.pump(); await tester.pump(); }
Future<void> setup(WidgetTester tester,HostCatalog catalog,HostTabs tabs,Map<String,SummaryWidgetAdapter> adapters,{double width=390}) async {
  tester.view.devicePixelRatio=1; tester.view.physicalSize=Size(width,844);
  addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
  final tokens=(await tester.runAsync(DesignTokens.load))!;
  await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,
    keys:TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),adapterFactory:(profile) {
      final adapter=SummaryWidgetAdapter(); adapters[profile.id]=adapter; return adapter;
    },offlineBuilder:(_) => const SizedBox())));
  await tester.pumpAndSettle();
}
Future<SummaryWidgetAdapter> connectHost(WidgetTester tester,HostProfile profile,Map<String,SummaryWidgetAdapter> adapters) async {
  await tapVisible(tester,'host-open-${profile.id}'); await tester.pumpAndSettle();
  await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
  await tapVisible(tester,'remote-review'); await tapVisible(tester,'remote-connect');
  return adapters[profile.id]!;
}
String workspaceTitle(WidgetTester tester) => (tester.widget<ExpansionTile>(find.byKey(const ValueKey('workspace-task-summaries'))).title as Text).data!;
String summaryText(WidgetTester tester,String hostId) => tester.widgetList<Text>(find.descendant(
  of:find.byKey(ValueKey('host-task-summary-$hostId')),matching:find.byType(Text))).map((w) => w.data).join('\n');
Future<void> revealHost(WidgetTester tester,String hostId) async {
  final scrollable=find.descendant(of:find.byKey(const ValueKey('host-catalog-list')),matching:find.byType(Scrollable)).first;
  tester.state<ScrollableState>(scrollable).position.jumpTo(0); await tester.pump();
  await tester.scrollUntilVisible(find.byKey(ValueKey('host-task-summary-$hostId')),200,scrollable:scrollable); await tester.pump();
}
void main() {
  for(final width in [320.0,390.0]) {
    testWidgets('normal saved-host entry at ${width}px shows visible fresh workspace and historical list without extra connection',(tester) async {
      final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      final a=tabProfile('Host A','probeA','127.0.0.1','direct','summary-a'),b=tabProfile('Host B','probeB','127.0.0.2','direct','summary-b');
      await catalog.add(a); await catalog.add(b); final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{};
      await setup(tester,catalog,tabs,adapters,width:width); await revealHost(tester,a.id);
      expect(summaryText(tester,a.id),contains('任务状态未知')); expect(summaryText(tester,a.id),isNot(contains('受阻 0')));
      final adapter=await connectHost(tester,a,adapters); adapter.emit(unknown:true); await pumpReports(tester);
      expect(workspaceTitle(tester),contains('Host A · 主机报告 · 受阻至少 2 个＋1 个状态未知'));
      expect(find.byKey(const ValueKey('workspace-task-summaries')).hitTestable(),findsOneWidget);
      final expansion=tester.widget<ExpansionTile>(find.byKey(const ValueKey('workspace-task-summaries')));
      expect((expansion.subtitle as Text).data,contains('原会话 probeA'));
      // Viewing all host summaries does not hide the active terminal/watch.
      await tester.tap(find.byKey(const ValueKey('workspace-task-summaries'))); await tester.pumpAndSettle();
      expect(find.byKey(ValueKey('workspace-task-summary-${a.id}')),findsOneWidget); expect(adapter.pauses,0);
      await tapVisible(tester,'hosts-board-tab'); await tester.pumpAndSettle(); await revealHost(tester,a.id);
      expect(summaryText(tester,a.id),contains('上次主机报告')); expect(summaryText(tester,a.id),contains('受阻至少 2'));
      expect(summaryText(tester,a.id),contains(DateTime.utc(2026,11,7,10).toLocal().toIso8601String()));
      adapter.emit(blocked:99); await pumpReports(tester); expect(summaryText(tester,a.id),isNot(contains('99')));
      expect(adapter.calls,1); expect(adapter.pauses,1); expect(adapter.writes,0); expect(adapters.length,1);
      expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
    });
  }
  testWidgets('stale blocked row opens a separate review-only tab for the exact target',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final original=await connectHost(tester,profile,adapters); original.emit(blocked:2); await pumpReports(tester);
    final oldTab=tabs.active!.id;
    await tapVisible(tester,'hosts-board-tab'); await tester.pumpAndSettle(); await revealHost(tester,profile.id);
    await tapVisible(tester,'host-blocked-${profile.id}'); await tester.pumpAndSettle();
    expect(find.textContaining('上次报告 · 点击后重新核查此目标'),findsOneWidget);
    await tapVisible(tester,blockedSummaryTargetKey(profile.id,const RemotePane('w1:p1','term_abcd'))); await tester.pumpAndSettle();
    expect(tabs.tabs.length,2); expect(tabs.active!.id,isNot(oldTab));
    expect(tabs.active!.requestedTarget,isA<BlockedSummaryTarget>());
    expect(tabs.active!.requestedTarget!.paneId,'w1:p1'); expect(tabs.active!.requestedTarget!.terminalId,'term_abcd');
    expect(original.calls,1); expect(original.writes,0);
    final second=adapters[profile.id]!; expect(second.calls,0); expect(second.writes,0);
    expect(find.byKey(const ValueKey('pair-connect')),findsOneWidget);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('compact workspace exposes stable exact target and reports the tab limit',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{};
    // Mount first: HostCatalogPage reloads the catalog and deliberately
    // invalidates tabs while its authority is unavailable.
    await setup(tester,catalog,tabs,adapters);
    for (var i=0;i<maxOpenHostTabs-1;i++) { expect(tabs.open(profile),isTrue); }
    tabs.select(null); await tester.pumpAndSettle();
    final adapter=await connectHost(tester,profile,adapters); adapter.emit(blocked:2); await pumpReports(tester);
    expect(tabs.tabs.length,maxOpenHostTabs);
    await tester.tap(find.byKey(const ValueKey('workspace-task-summaries'))); await tester.pumpAndSettle();
    await tapVisible(tester,blockedSummaryGroupKey(profile.id,compact:true)); await tester.pumpAndSettle();
    const pane=RemotePane('w1:p1','term_abcd',label:'same',agentStatus:'blocked');
    final key=blockedSummaryTargetKey(profile.id,pane,compact:true);
    expect(key,blockedSummaryTargetKey(profile.id,const RemotePane('w1:p1','term_abcd',label:'renamed'),compact:true));
    expect(key,isNot(blockedSummaryTargetKey(profile.id,const RemotePane('w1:p1','different'),compact:true)));
    await tapVisible(tester,key); await tester.pump();
    expect(tabs.tabs.length,maxOpenHostTabs); expect(tabs.notice,contains('最多保留'));
    expect(adapter.calls,1); expect(adapter.writes,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('empty authority differs from unknown, while stale failure retains prior count and time',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters);
    adapter.emit(empty:true); await pumpReports(tester); expect(workspaceTitle(tester),contains('受阻 0 个 · 快照确认为空'));
    adapter.emit(blocked:1); await pumpReports(tester); expect(workspaceTitle(tester),contains('主机报告 · 受阻 1 个'));
    adapter.emit(blocked:99,freshness:DashboardFreshness.refreshing,at:DateTime.utc(2026,11,7,11)); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('上次主机报告 · 受阻 1 个')); expect(workspaceTitle(tester),isNot(contains('99')));
    adapter.pending.completeError(const RemoteFailure('observe_ended')); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('上次主机报告')); expect(adapter.calls,1); expect(adapter.writes,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('single authoritative snapshot remains visible with continuous-update-unavailable label',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters);
    adapter.emit(blocked:1,freshness:DashboardFreshness.unavailable); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('主机报告 · 受阻 1 个'));
    expect(workspaceTitle(tester),contains('持续更新不可用（单次快照）'));
    expect(find.textContaining('当前主机摘要 · 主机报告 · 受阻 1 个'),findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('workspace-task-summaries'))); await tester.pumpAndSettle();
    expect(find.text('持续更新不可用 · 单次确认报告，打开前重新核查此目标'),findsOneWidget);
    expect(adapter.calls,1); expect(adapter.writes,0); await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('fresh workspace summary tolerates landscape and keyboard-constrained height',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters); adapter.emit(); await pumpReports(tester);
    addTearDown(tester.view.resetViewInsets);
    for(final size in [const Size(844,390),const Size(640,320)]) {
      tester.view.physicalSize=size; tester.view.viewInsets=const FakeViewPadding(bottom:160); await tester.pumpAndSettle();
      expect(tester.takeException(),isNull); expect(workspaceTitle(tester),contains('主机报告 · 受阻 2 个'));
      expect(adapter.calls,1); expect(adapter.writes,0);
    }
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('background revokes source and resume requires explicit connection, not a late dashboard',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters); adapter.emit(); await pumpReports(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive); await pumpReports(tester);
    restoreResumedLifecycle(tester); await pumpReports(tester); adapter.emit(blocked:99); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('上次主机报告 · 受阻 2 个')); expect(workspaceTitle(tester),isNot(contains('99')));
    expect(adapter.calls,1); expect(adapter.writes,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('same-SSH explicit resume rejects prior observation epoch before accepting new metadata',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters); adapter.emit(); await pumpReports(tester); final id=tabs.active!.id;
    await tapVisible(tester,'hosts-board-tab'); await tapVisible(tester,'host-tab-$id'); await tapVisible(tester,'remote-resume');
    adapter.emit(blocked:99,observationEpoch:0); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('上次主机报告 · 受阻 2 个'));
    adapter.emit(blocked:1,observationEpoch:1); await pumpReports(tester);
    expect(workspaceTitle(tester),contains('主机报告 · 受阻 1 个')); expect(adapter.calls,1); expect(adapter.resumes,1); expect(adapter.writes,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('deletion and same-ID recreation cannot inherit a retired page report',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final profile=tabProfile('Host','probe','127.0.0.1','direct','summary'); await catalog.add(profile);
    final tabs=HostTabs(),adapters=<String,SummaryWidgetAdapter>{}; await setup(tester,catalog,tabs,adapters);
    final adapter=await connectHost(tester,profile,adapters); adapter.emit(); await pumpReports(tester);
    await catalog.remove(profile.id); await catalog.add(profile); await tester.pumpAndSettle();
    adapter.emit(blocked:99); await pumpReports(tester); await revealHost(tester,profile.id);
    expect(summaryText(tester,profile.id),contains('任务状态未知')); expect(summaryText(tester,profile.id),isNot(contains('99')));
    expect(tabs.tabs,isEmpty); expect(adapter.calls,1); expect(adapter.writes,0);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
  testWidgets('new pairing root-Navigator entry receives a summary lease and current-page presentation',(tester) async {
    final catalog=HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
    final tabs=HostTabs(),keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String),tokens=(await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,catalog:catalog,tabs:tabs,keys:keys,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle(); await tapVisible(tester,'hosts-add'); await tester.pumpAndSettle();
    await fillPairTarget(tester,fixtureConfig()); await tapVisible(tester,'pair-target-review'); await tapVisible(tester,'pair-create'); await tester.pumpAndSettle();
    final request=jsonDecode(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-request'))).data!) as Map<String,dynamic>;
    await acceptResponse(tester,authorizedResponse(request)); await tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    final page=tester.widget<RemotePage>(find.byType(RemotePage)); expect(page.summaryLease,isNotNull);
    expect(find.byKey(const ValueKey('remote-host-task-summary')),findsOneWidget);
    // Exercise only the real navigation's lease/presentation with a synthetic
    // authoritative report. No remote-connect control is invoked in this case.
    final profile=catalog.profiles.single;
    page.summaryLease!.begin()!.publish(summaryBoard(profile,blocked:1)); await pumpReports(tester);
    expect(find.textContaining('当前主机摘要 · 主机报告 · 受阻至少 1 个'),findsOneWidget);
    await tester.tap(find.byTooltip('返回离线验证')); await tester.pumpAndSettle(); await tester.pageBack(); await tester.pumpAndSettle();
    await revealHost(tester,profile.id); expect(summaryText(tester,profile.id),contains('上次主机报告'));
    expect(keys.signCalls,0); expect(tabs.tabs,isEmpty);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
