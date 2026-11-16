import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'android_pairing_observe_test.dart' as existing;
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import '../test/remote_page_test.dart' show PendingAdapter, fillRemoteFixture;
import 'dual_overlay_ui_steps.dart';

void main() {
  testWidgets('stale initial pane cannot consume the one selection before fresh watch', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320, 844);
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final adapter = PendingAdapter();
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: RemotePage(
      tokens: tokens, adapter: adapter, onOpenPane: (_) {})));
    await fillRemoteFixture(tester);
    for (final key in ['remote-review', 'remote-connect']) {
      final control = find.byKey(ValueKey(key));
      await tester.ensureVisible(control); await tester.tap(control); await tester.pump();
    }
    const target = RemotePane('w1:p1', 'term_abcd');
    adapter.dashboard!(RemoteDashboard(adapter.generation, 'probe', const [target], revision: 1));
    await tester.pump();
    final pane = remotePaneChoices();
    expect(pane, findsOneWidget);
    expect(tester.widget<FilledButton>(pane).onPressed, isNull);
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    expect(adapter.selected, isNull); // Old quantity-only tap did nothing.
    Timer(const Duration(milliseconds: 350), () {
      adapter.dashboard!(RemoteDashboard(adapter.generation, 'probe', const [target],
        freshness: DashboardFreshness.fresh, revision: 2));
    });
    final root = Directory.systemTemp.createTempSync('pane-ready-');
    addTearDown(() => root.deleteSync(recursive: true));
    final steps = DualOverlayUiSteps(tester, root);
    await steps.selectUniquePane();
    expect(adapter.selected, target.paneId);
    expect(steps.selectionAttempted, isTrue);
    final diagnostic = steps.inspectRemote();
    expect(diagnostic['selectedMatches'], isTrue);
    adapter.frame!(adapter.generation, target.paneId, const RemoteFrame(0, true, 'Synthetic observe tick'));
    await tester.pump();
    expect(find.byType(TerminalView), findsOneWidget);
    expect(existing.screenHasMarker(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, 'Synthetic observe tick'), isTrue);
    expect(steps.inspectRemote()['sequencePresent'], isTrue);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('real remote page distinguishes pane selection from new tab controls', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 844);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final adapter = PendingAdapter();
    var opened = 0;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: RemotePage(
      tokens: tokens, adapter: adapter, onOpenPane: (_) { opened++; })));
    await fillRemoteFixture(tester);
    final review = find.byKey(const ValueKey('remote-review'));
    await tester.ensureVisible(review); await tester.tap(review); await tester.pump();
    final connect = find.byKey(const ValueKey('remote-connect'));
    await tester.ensureVisible(connect); await tester.tap(connect); await tester.pump();
    adapter.dashboard!(RemoteDashboard(adapter.generation, 'probe', const [RemotePane('w1:p1', 'term_abcd')],
      freshness: DashboardFreshness.fresh, revision: 1));
    await tester.pump();
    final oldFinder = find.byWidgetPredicate((w) => w.key is ValueKey<String> &&
      (w.key! as ValueKey<String>).value.startsWith('remote-pane-'));
    expect(oldFinder, findsNWidgets(2));
    expect(remotePaneChoices(), findsOneWidget);
    final root = Directory.systemTemp.createTempSync('remote-diagnostic-');
    addTearDown(() => root.deleteSync(recursive: true));
    final diagnostic = DualOverlayUiSteps(tester, root).inspectRemote();
    expect(diagnostic['pagePresent'], isTrue);
    expect(diagnostic['dashboardPresent'], isTrue);
    expect(diagnostic['paneCount'], 1);
    expect(diagnostic['paneControlCount'], 1);
    expect(find.byKey(const ValueKey('remote-pane-new-tab-w1:p1')), findsOneWidget);
    final openTab = find.byKey(const ValueKey('remote-pane-new-tab-w1:p1'));
    await tester.ensureVisible(openTab); await tester.tap(openTab); await tester.pump();
    expect(opened, 1); expect(adapter.selected, isNull);
    final select = remotePaneChoices();
    await tester.ensureVisible(select); await tester.tap(select); await tester.pump();
    expect(adapter.selected, 'w1:p1'); expect(opened, 1);
    adapter.dashboard!(RemoteDashboard(adapter.generation, 'probe',
      const [RemotePane('w1:p1', 'term_abcd'), RemotePane('w1:p2', 'term_1234')],
      freshness: DashboardFreshness.fresh, revision: 2));
    await tester.pump();
    expect(remotePaneChoices(), findsNWidgets(2));
    await tester.pumpWidget(const SizedBox());
  });
}
