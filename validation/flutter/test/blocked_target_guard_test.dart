import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'remote_page_test.dart' show PendingAdapter,field,fillRemoteFixture;
import 'remote_test_data.dart';

void main() {
  test('adapter internal fresh snapshot validates exact blocked identity and route',() {
    final source=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'system');
    final selected=BlockedSummaryTarget(const RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),source.endpointKey);
    RemoteDashboard board(List<RemotePane> panes,{RemoteDashboardSource? from}) => RemoteDashboard(1,'probe',panes,source:from ?? source);
    const blocked=RemotePane('w1:p1','term_abcd',agentStatus:'blocked');
    expect(() => requireInitialBlockedObservation(selected,board([blocked])),returnsNormally);
    for (final panes in [<RemotePane>[],[const RemotePane('w1:p1','term_abcd',agentStatus:'done')],
      [const RemotePane('w1:p1','term_other',agentStatus:'blocked')],[blocked,blocked]]) {
      expect(() => requireInitialBlockedObservation(selected,board(panes)),throwsA(isA<RemoteFailure>()));
    }
    final other=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'tailscale:other');
    expect(() => requireInitialBlockedObservation(selected,board([blocked],from:other)),throwsA(isA<RemoteFailure>()));
    // Ordinary target selection retains its prior behavior.
    expect(() => requireInitialBlockedObservation(blocked,board(const [])),returnsNormally);
  });

  for (final status in ['done','working','idle','unknown','blocked']) {
    testWidgets('blocked summary target rechecks status $status on new board',(tester) async {
      final adapter=PendingAdapter(),tokens=(await tester.runAsync(DesignTokens.load))!;
      final source=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'system');
      final requested=BlockedSummaryTarget(const RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),source.endpointKey);
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,requestedTarget:requested)));
      await fillRemoteFixture(tester);
      await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
      await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
      void publish() => adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',
        [RemotePane('w1:p1','term_abcd',agentStatus:status)],freshness:DashboardFreshness.fresh,revision:1,source:source));
      if (status == 'blocked') { publish(); expect(adapter.selected,'w1:p1'); }
      else { expect(publish,throwsA(isA<RemoteFailure>().having((e) => e.code,'code','resume_target_changed'))); expect(adapter.selected,isNull); }
      await tester.pumpWidget(const SizedBox());
    });
  }
  for (final candidate in [
    const <RemotePane>[],
    const <RemotePane>[RemotePane('w1:p1','term_other',agentStatus:'blocked')],
    const <RemotePane>[RemotePane('w1:p2','term_abcd',agentStatus:'blocked')],
    const <RemotePane>[RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),RemotePane('w1:p1','term_abcd',agentStatus:'blocked')],
  ]) {
    testWidgets('blocked summary does not select a missing or ambiguous identity ${(candidate.length)}',(tester) async {
      final adapter=PendingAdapter(),tokens=(await tester.runAsync(DesignTokens.load))!;
      final source=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'system');
      final requested=BlockedSummaryTarget(const RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),source.endpointKey);
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,requestedTarget:requested)));
      await fillRemoteFixture(tester);
      await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
      await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
      expect(() => adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',candidate,
        freshness:DashboardFreshness.fresh,revision:1,source:source)),throwsA(isA<RemoteFailure>().having((e) => e.code,'code','resume_target_changed')));
      expect(adapter.selected,isNull); await tester.pumpWidget(const SizedBox());
    });
  }

  for (final change in ['done','replacement','source','refreshing']) {
    testWidgets('changed $change before first full refuses blocked target',(tester) async {
      final adapter=PendingAdapter(),tokens=(await tester.runAsync(DesignTokens.load))!;
      final source=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'system');
      final requested=BlockedSummaryTarget(const RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),source.endpointKey);
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,requestedTarget:requested)));
      await fillRemoteFixture(tester);
      await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
      await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
      final original=RemotePane('w1:p1','term_abcd',agentStatus:'blocked');
      adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',[original],freshness:DashboardFreshness.fresh,revision:1,source:source));
      expect(adapter.selected,'w1:p1');
      final next=RemoteDashboard(adapter.generation,'probe',[
        RemotePane('w1:p1',change == 'replacement' ? 'term_other' : 'term_abcd',agentStatus:change == 'done' ? 'done' : 'blocked')
      ],freshness:change == 'refreshing' ? DashboardFreshness.refreshing : DashboardFreshness.fresh,revision:2,
        source:change == 'source' ? RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'tailscale:different') : source);
      if (change == 'refreshing') {
        adapter.dashboard!(next);
      } else {
        expect(() => adapter.dashboard!(next),throwsA(isA<RemoteFailure>()));
      }
      expect(() => adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'SHOULD NOT APPEAR')),
        throwsA(isA<RemoteFailure>()));
      await tester.pump(); expect(find.textContaining('SHOULD NOT APPEAR'),findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('after first full later task status changes do not revoke the observation',(tester) async {
    final adapter=PendingAdapter(),tokens=(await tester.runAsync(DesignTokens.load))!;
    final source=RemoteDashboardSource.connected(RemoteConfig.fromJson(fixtureConfig()),'system');
    final requested=BlockedSummaryTarget(const RemotePane('w1:p1','term_abcd',agentStatus:'blocked'),source.endpointKey);
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:RemotePage(tokens:tokens,adapter:adapter,requestedTarget:requested)));
    await fillRemoteFixture(tester);
    await tester.ensureVisible(field('review')); await tester.tap(field('review')); await tester.pump();
    await tester.ensureVisible(field('connect')); await tester.tap(field('connect')); await tester.pump();
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [RemotePane('w1:p1','term_abcd',agentStatus:'blocked')],freshness:DashboardFreshness.fresh,revision:1,source:source));
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'FIRST FULL')); await tester.pump();
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [RemotePane('w1:p1','term_abcd',agentStatus:'done')],freshness:DashboardFreshness.fresh,revision:2,source:source));
    await tester.pump(); expect(tester.takeException(),isNull); expect(adapter.selected,'w1:p1');
    await tester.pumpWidget(const SizedBox());
  });

}
