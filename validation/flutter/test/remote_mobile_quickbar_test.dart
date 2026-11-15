import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'herdr_workflow_visual_test.dart' as visual;
import 'remote_input_widget_test.dart' as input;
import 'remote_page_test.dart' as base;

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('mobile direct controls stay reachable with keyboard at $width', (tester) async {
      visual.size(tester, Size(width, 844));
      final tokens = await visual.loadVisualTokens(tester);
      final adapter = input.InputFixtureAdapter();
      await tester.pumpWidget(visual.visualApp(tokens, Scaffold(
        bottomNavigationBar: NavigationBar(destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard), label: '看板'),
          NavigationDestination(icon: Icon(Icons.terminal), label: '终端'),
          NavigationDestination(icon: Icon(Icons.language), label: '网络'),
          NavigationDestination(icon: Icon(Icons.settings), label: '设置'),
        ]), body: RemotePage(tokens: tokens, adapter: adapter))));
      await base.fillRemoteFixture(tester);
      for (final name in ['review', 'connect']) {
        await tester.ensureVisible(base.field(name)); await tester.tap(base.field(name)); await tester.pump();
      }
      adapter.publish(); await tester.pump();
      final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
      await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
      adapter.frame!(adapter.generation, 'w1:p1', const RemoteFrame(0, true,
        'SYNTHETIC MOBILE FIXTURE\r\n\$ git status\r\n M lib/main.dart\r\n\$ '));
      await tester.pumpAndSettle(); await input.mode(tester, 'direct');
      await visual.top(tester, find.byKey(const ValueKey('remote-mode-direct')));
      tester.view.viewInsets = const FakeViewPadding(bottom: 300); await tester.pumpAndSettle();
      tester.widget<Slider>(find.byKey(const ValueKey('remote-vertical-slider'))).onChanged?.call(0);
      await tester.pumpAndSettle();
      for (final key in ['remote-keyboard-hide', 'remote-key-Esc', 'remote-key-Tab',
          'remote-key-↑', 'remote-key-↓', 'remote-key-←', 'remote-key-→', 'remote-key-Enter']) {
        final finder = find.byKey(ValueKey(key));
        expect(finder.hitTestable(), findsOneWidget, reason: '$key must be reachable above the keyboard');
        expect(tester.getSize(finder).height, greaterThanOrEqualTo(44));
        expect(tester.getSize(finder).width, greaterThanOrEqualTo(44));
        expect(tester.getBottomRight(finder).dy, lessThanOrEqualTo(544));
      }
      expect(adapter.received, isEmpty);
      await visual.save(tester, 'flutter-direct-keyboard-${width.toInt()}');
      await tester.tap(find.byKey(const ValueKey('remote-key-Esc'))); await tester.pumpAndSettle();
      expect(adapter.received.single, [27]);
      await tester.tap(find.byKey(const ValueKey('remote-keyboard-hide'))); await tester.pumpAndSettle();
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
      expect(adapter.received.length, 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
