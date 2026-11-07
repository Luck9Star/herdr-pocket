import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'remote_page_test.dart' as base;
import 'remote_test_data.dart';

void main() {
  test('unknown legacy snapshot time stays unknown and stale transitions preserve authority time',() {
    const legacy = RemoteDashboard(1,'probe',[]);
    expect(legacy.syncedAt,isNull);
    final at = DateTime.utc(2026,11,7,10),board = RemoteDashboard(1,'probe',const [RemotePane('w1:p1','term_abcd')],syncedAt:at);
    for (final phase in DashboardFreshness.values) {
      final next = board.withFreshness(phase,revision:4);
      expect(next.syncedAt,at); expect(next.freshness,phase); expect(next.revision,4);
      expect(identical(next.panes,board.panes),isTrue);
    }
  });
  test('failed connection cannot invoke the snapshot clock or manufacture a synchronized board',() async {
    var clockReads = 0;
    final adapter = RemoteReadOnlyAdapter(connector:(_,__) => Future.error(const RemoteFailure('synthetic_connection')),
      clock:() { clockReads++; return DateTime.utc(2026,11,7); });
    await expectLater(adapter.read(RemoteConfig.fromJson(fixtureConfig())),throwsA(isA<RemoteFailure>()));
    expect(clockReads,0); expect(adapter.currentDashboard,isNull);
  });
  testWidgets('board time is independent of frames and survives stale, failed reconnect and late callbacks',(tester) async {
    final adapter = base.PendingAdapter(); await base.prepare(tester,adapter,const Size(390,844));
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    final sync = find.byKey(const ValueKey('remote-dashboard-sync'));
    expect(tester.widget<Text>(sync).data,contains('尚无已确认'));
    final at = DateTime.utc(2026,11,7,10),next = DateTime.utc(2026,11,7,11);
    const pane = RemotePane('w1:p1','term_abcd');
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [pane],freshness:DashboardFreshness.fresh,revision:1,syncedAt:at)); await tester.pump();
    final first = tester.widget<Text>(sync).data;
    expect(first,contains(at.toLocal().toIso8601String())); expect(first,contains('fixture@127.0.0.1:2222 / probe'));
    final select = find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(select); await tester.tap(select); await tester.pump();
    adapter.frame!(adapter.generation,pane.paneId,const RemoteFrame(0,true,'FULL DOES NOT SYNC BOARD')); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [pane],freshness:DashboardFreshness.stale,revision:2,syncedAt:at)); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [pane],freshness:DashboardFreshness.fresh,revision:1,syncedAt:next));
    adapter.dashboard!(RemoteDashboard(adapter.generation-1,'probe',const [pane],freshness:DashboardFreshness.fresh,revision:3,syncedAt:next)); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    // Beginning a new attempt clears the current board, but retains the last
    // successful time with its original source rather than relabelling it now.
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    adapter.pending.completeError(const RemoteFailure('synthetic_connection')); await tester.pump();
    expect(tester.widget<Text>(sync).data,first);
    expect(adapter.calls,2); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('only a newer accepted authoritative dashboard advances displayed sync time',(tester) async {
    final adapter = base.PendingAdapter(); await base.prepare(tester,adapter,const Size(390,844));
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    final first = DateTime.utc(2026,11,7,10),second = DateTime.utc(2026,11,7,10,1);
    final board = RemoteDashboard(adapter.generation,'probe',const [],freshness:DashboardFreshness.fresh,revision:1,syncedAt:first);
    adapter.dashboard!(board); await tester.pump();
    adapter.dashboard!(board.withFreshness(DashboardFreshness.refreshing,revision:2)); await tester.pump();
    final sync = find.byKey(const ValueKey('remote-dashboard-sync'));
    expect(tester.widget<Text>(sync).data,contains(first.toLocal().toIso8601String()));
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [],freshness:DashboardFreshness.unavailable,revision:3,syncedAt:second)); await tester.pump();
    expect(tester.widget<Text>(sync).data,contains(second.toLocal().toIso8601String()));
    expect(tester.widget<Text>(sync).data,isNot(contains(first.toLocal().toIso8601String())));
    await tester.pumpWidget(const SizedBox());
  });
}
