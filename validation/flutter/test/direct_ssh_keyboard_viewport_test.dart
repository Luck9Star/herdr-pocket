import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_widget_test.dart' show CapturingShell;
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'ios_layout_diagnostics.dart';

class ClosingShell extends CapturingShell {
  int closeCalls = 0;
  @override
  void close() {
    closeCalls++;
  }
}

void main() {
  testWidgets(
    'overflow projection identifies the project constructor without exporting widget text',
    (tester) async {
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(
        MaterialApp(
          theme: tokens.theme,
          home: DirectSshPage(tokens: tokens),
        ),
      );
      final dynamic state = tester.state(find.byType(DirectSshPage));
      final previous = FlutterError.onError;
      Map<String, Object?>? diagnostic;
      FlutterError.onError = (details) {
        diagnostic = iosOverflowDiagnostic(
          details,
          stage: 'input',
          view: tester.view,
        );
        previous?.call(details);
      };
      try {
        state.setState(() {
          state.terminal = state.createTerminal(state.epoch);
          state.shell = ClosingShell();
          state.connected = true;
          state.status = 'synthetic-secret ' * 300;
          state.activeTarget = 'fixture@127.0.0.1:2222';
        });
        await tester.pump();
        expect(tester.takeException(), isFlutterError);
        expect(diagnostic?['owner'], 'DirectSshPage');
        expect(diagnostic?['file'], 'direct_ssh_page.dart');
        expect(diagnostic?['line'], greaterThan(0));
        expect(diagnostic?['routeCurrent'], isTrue);
        expect(jsonEncode(diagnostic), isNot(contains('synthetic-secret')));
        state.stop(message: '已断开；未重放输入。');
        await tester.pump();
        await tester.pumpWidget(const SizedBox());
      } finally {
        FlutterError.onError = previous;
      }
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );
  testWidgets(
    'overflow diagnostics preserve direction and pixels and forward the original error',
    (tester) async {
      final previous = FlutterError.onError;
      Map<String, Object?>? diagnostic;
      FlutterError.onError = (details) {
        diagnostic = iosOverflowDiagnostic(
          details,
          stage: 'input',
          view: tester.view,
        );
        previous?.call(details);
      };
      try {
        await tester.pumpWidget(
          const Directionality(
            textDirection: TextDirection.ltr,
            child: Center(
              child: SizedBox(
                width: 100,
                height: 10,
                child: Column(children: [SizedBox(height: 68)]),
              ),
            ),
          ),
        );
        expect(tester.takeException(), isFlutterError);
        expect(diagnostic?['direction'], 'bottom');
        expect(diagnostic?['pixels'], 58);
        expect(diagnostic?['stage'], 'input');
        expect(diagnostic?['file'], 'unknown');
        expect(diagnostic?.containsKey('stack'), isFalse);
        expect(
          iosOverflowDiagnostic(
            FlutterErrorDetails(exception: StateError('synthetic-secret')),
            stage: 'input',
            view: tester.view,
          ),
          isNull,
        );
      } finally {
        FlutterError.onError = previous;
      }
    },
  );
  testWidgets(
    'iOS keyboard height transitions keep an active SSH viewport valid without replay',
    (tester) async {
      tester.view.physicalSize = const Size(414, 896);
      tester.view.devicePixelRatio = 1;
      tester.view.viewPadding = const FakeViewPadding(top: 44, bottom: 34);
      tester.view.padding = const FakeViewPadding(top: 44, bottom: 34);
      addTearDown(tester.view.reset);
      final semantics = tester.ensureSemantics();
      final handles = tester.binding.debugOutstandingSemanticsHandles;
      final catalog = HostCatalog(
        storage: MemoryCatalogStorage(),
        clock: () => 1,
      );
      try {
        final tokens = (await tester.runAsync(DesignTokens.load))!;
        await catalog.load();
        await tester.pumpWidget(
          MaterialApp(
            theme: tokens.theme,
            home: HostCatalogPage(
              tokens: tokens,
              catalog: catalog,
              offlineBuilder: (_) => const SizedBox(),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('hosts-direct-ssh')));
        await tester.pumpAndSettle();
        final direct = tester.element(find.byType(DirectSshPage));
        expect(ModalRoute.of(direct)?.isCurrent, isTrue);
        expect(
          find.byKey(const ValueKey('hosts-direct-ssh')).hitTestable(),
          findsNothing,
        );
        final dynamic state = tester.state(find.byType(DirectSshPage));
        final shell = ClosingShell();
        state.setState(() {
          state.terminal = state.createTerminal(state.epoch);
          state.shell = shell;
          state.connected = true;
          state.status = '已连接 · 输入直接发送到远端 shell';
          state.activeTarget = 'fixture@127.0.0.1:2222';
          state.secret.text = 'synthetic-credential';
        });
        await tester.pump();
        await tester.tap(find.byType(TerminalView));
        await tester.pump(const Duration(milliseconds: 300));
        tester.testTextInput.enterText('hp-check');
        await tester.pump();
        final enter = find.widgetWithText(TextButton, 'Enter');
        await tester.ensureVisible(enter);
        await tester.tap(enter);
        await tester.pump();
        expect(shell.writes.join(), 'hp-check\r');
        for (final inset in [336.0, 640.0, 742.0, 756.0, 0.0, 756.0]) {
          tester.view.viewInsets = FakeViewPadding(bottom: inset);
          tester.view.padding = FakeViewPadding(
            top: 44,
            bottom: inset == 0 ? 34 : 0,
          );
          await tester.pump();
          expect(tester.takeException(), isNull, reason: 'bottom inset $inset');
          expect(
            tester.getSize(find.byType(TerminalView)).height,
            greaterThan(0),
          );
          expect(shell.writes.join(), 'hp-check\r');
          expect(find.text('断开').hitTestable(), findsOneWidget);
          await tester.ensureVisible(enter);
          await tester.pump();
          expect(enter.hitTestable(), findsOneWidget);
          expect(tester.takeException(), isNull);
        }
        await tester.tap(find.text('断开'));
        await tester.pump();
        expect(find.byType(TerminalView), findsNothing);
        expect(state.secret.text, isEmpty);
        expect(shell.closeCalls, 1);
        expect(find.textContaining('已断开'), findsOneWidget);
        expect(shell.writes.join(), 'hp-check\r');
        expect(tester.takeException(), isNull);
        tester.view.viewInsets = const FakeViewPadding();
        await tester.pump();
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
        expect(tester.binding.debugOutstandingSemanticsHandles, handles);
      } finally {
        catalog.dispose();
        semantics.dispose();
      }
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );
}
