import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'remote_page_test.dart' as base;
import 'remote_test_data.dart';

/// Explicit widget transport double. No network, native key or input evidence.
class DashboardFixtureAdapter extends base.PendingAdapter {
  int writes = 0;
  @override
  Future<RemoteInputResult> sendInput(RemoteInputTarget target,Uint8List bytes,
      {required bool Function() stillCurrent}) async {
    writes++;
    return const RemoteInputResult.rejected('unexpected_dashboard_write');
  }
}

Future<void> connect(WidgetTester tester,DashboardFixtureAdapter adapter,double width) async {
  await base.prepare(tester,adapter,Size(width,640));
  tester.platformDispatcher.textScaleFactorTestValue = 1.3;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  tester.view.viewInsets = const FakeViewPadding(bottom:260);
  await tester.pump();
  await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
  await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
}

List<String> displayedPaneIds(WidgetTester tester) => tester.widgetList<FilledButton>(
  find.byWidgetPredicate((widget) => widget is FilledButton && widget.key is ValueKey<String> &&
    (widget.key! as ValueKey<String>).value.startsWith('remote-pane-')))
  .map((button) => (button.key! as ValueKey<String>).value.substring('remote-pane-'.length)).toList();

List<RemotePane> sharedFixturePanes(int generation) {
  final wire = jsonDecode(File('assets/shared/dashboard-snapshot.json').readAsStringSync()) as Map<String,dynamic>;
  final result = wire['result'] as Map<String,dynamic>, snapshot = result['snapshot'] as Map<String,dynamic>;
  final rows = snapshot['panes'] as List;
  final first = Map<String,dynamic>.from(rows[0] as Map);
  final anonymous = {...first}..remove('display_agent')..remove('agent');
  final noStatus = {...anonymous}..remove('agent_status');
  final config = RemoteConfig.fromJson({...fixtureConfig(),'paneId':''});
  return parseSnapshotDashboard(config,{'type':'session_snapshot','snapshot':{...snapshot,'panes':[
    ...rows,
    {...anonymous,'pane_id':'w1:p3','terminal_id':'term_ab3','label':'需要检查','agent_status':'blocked'},
    {...noStatus,'pane_id':'w1:p4','terminal_id':'term_ab4','label':'blocked approval in a label'},
    {...first,'pane_id':'w1:p5','terminal_id':'term_ab5','label':'另一受阻窗格','agent_status':'blocked'},
    {...anonymous,'pane_id':'w1:p6','terminal_id':'term_ab6','label':'future status','agent_status':'Blocked'},
  ]}},generation).panes;
}

void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('blocked priority at ${width}px preserves source identity and waits for explicit pane choice',(tester) async {
      final adapter = DashboardFixtureAdapter();
      await connect(tester,adapter,width);
      final panes = sharedFixturePanes(adapter.generation);
      final sourceIds = panes.map((pane) => pane.paneId).toList();
      final sourceTerminals = panes.map((pane) => pane.terminalId).toList();
      adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',panes)); await tester.pump();
      expect(displayedPaneIds(tester),['w1:p3','w1:p5','w1:p1','w1:p2','w1:p4','w1:p6']);
      expect(panes.map((pane) => pane.paneId),sourceIds);
      expect(panes.map((pane) => pane.terminalId),sourceTerminals);
      expect([panes[1].agentStatus,panes[3].agentStatus,panes[5].agentStatus],['unknown','unknown','unknown']);
      expect(find.text('窗格状态 · 受阻'),findsOneWidget);
      expect(find.text('窗格状态 · 状态未知'),findsNWidgets(3));
      expect(find.text('Codex · 受阻'),findsOneWidget);
      final summary = find.byKey(const ValueKey('remote-blocked-summary'));
      await tester.ensureVisible(summary); await tester.pumpAndSettle();
      final semantics = tester.widget<Semantics>(summary).properties;
      expect(semantics.label,'主机报告 2 个受阻窗格。待处理优先，同级保持原顺序。');
      expect(semantics.liveRegion,isTrue);
      expect(summary.hitTestable(),findsOneWidget);
      expect(adapter.selected,isNull); expect(adapter.calls,1); expect(adapter.writes,0);
      expect(find.byType(TerminalView),findsNothing);

      // Choose an unknown-status pane in the second group. Priority must not
      // redirect this explicit ID or allow another pane's frame to appear.
      final chosen = find.byKey(const ValueKey('remote-pane-w1:p2'));
      await tester.ensureVisible(chosen); await tester.tap(chosen); await tester.pump();
      expect(adapter.selected,'w1:p2');
      adapter.frame!(adapter.generation,'w1:p3',const RemoteFrame(0,true,'UNSELECTED BLOCKED FRAME'));
      await tester.pump(); expect(find.byType(TerminalView),findsNothing);
      adapter.frame!(adapter.generation,'w1:p2',const RemoteFrame(0,true,'EXPLICIT UNKNOWN PANE'));
      await tester.pump();
      expect(find.byType(TerminalView),findsOneWidget);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(adapter.writes,0); expect(adapter.calls,1);
      await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
      expect(summary,findsNothing);
      expect(displayedPaneIds(tester),sourceIds); // Stale statuses are not current pending work.
      expect(find.text('窗格状态 · 上次受阻（待确认）'),findsOneWidget);
      expect(adapter.selected,'w1:p2'); expect(adapter.calls,1); expect(adapter.writes,0);
      expect(tester.takeException(),isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('legacy pane-only fixture retains its order and unknown status without inventing agents',(tester) async {
    final adapter = DashboardFixtureAdapter();
    await connect(tester,adapter,360);
    adapter.publish(); await tester.pump();
    expect(displayedPaneIds(tester),['w1:p1','w1:p2']);
    expect(find.byKey(const ValueKey('remote-blocked-summary')),findsNothing);
    expect(find.text('窗格状态 · 状态未知'),findsNWidgets(2));
    expect(find.textContaining('Agent'),findsNothing);
    expect(adapter.selected,isNull); expect(adapter.writes,0); expect(adapter.calls,1);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
}
