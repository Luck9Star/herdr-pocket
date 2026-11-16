import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import '../test/remote_page_test.dart' show PendingAdapter, fillRemoteFixture;
import 'dual_overlay_ui_steps.dart';

void main() {
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
