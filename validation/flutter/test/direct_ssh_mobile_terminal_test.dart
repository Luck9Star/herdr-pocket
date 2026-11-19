import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/config_transfer_page.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_widget_test.dart' show waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

Future<void> waitForLog(
  WidgetTester tester,
  File log,
  bool Function(String) ready,
) async {
  final deadline = DateTime.now().add(const Duration(seconds: 8));
  while (!ready(log.readAsStringSync()) && DateTime.now().isBefore(deadline)) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 25)),
    );
    await tester.pump();
  }
  expect(ready(log.readAsStringSync()), isTrue);
}

bool terminalContains(Terminal terminal, String text) {
  final expected = text.codeUnits;
  for (var y = 0; y < terminal.viewHeight; y++) {
    final line = terminal.buffer.lines[y];
    for (var x = 0; x + expected.length <= terminal.viewWidth; x++) {
      if (List.generate(
            expected.length,
            (i) => line.getCodePoint(x + i),
          ).join(',') ==
          expected.join(','))
        return true;
    }
  }
  return false;
}

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets(
      'real SSH terminal and active settings at $width',
      (tester) async {
        final port = Platform.environment['HERDR_TERMINAL_PORT']!;
        final log = File(Platform.environment['HERDR_TERMINAL_LOG']!);
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = Size(width, width == 320 ? 640 : 844);
        final inset = width == 320
            ? const FakeViewPadding(top: 24, bottom: 24)
            : const FakeViewPadding(top: 47, bottom: 34);
        tester.view.padding = inset;
        tester.view.viewPadding = inset;
        addTearDown(tester.view.reset);
        final catalog = HostCatalog(
          storage: MemoryCatalogStorage(),
          clock: () => 1000,
        );
        await catalog.load();
        final tokens = (await tester.runAsync(DesignTokens.load))!;
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
        Finder key(String id) => find.byKey(ValueKey(id));
        await tester.tap(key('hosts-direct-ssh'));
        await tester.pumpAndSettle();
        await tester.enterText(key('direct-host'), '127.0.0.1');
        await tester.enterText(key('direct-port'), port);
        await tester.enterText(key('direct-user'), 'fixture');
        await tester.pump();
        await tester.tap(key('direct-probe'));
        await tester.pump();
        await waitFor(tester, key('direct-trust-key'));
        await tester.pumpAndSettle();
        await tester.tap(key('direct-trust-key'));
        await tester.pumpAndSettle();
        await tester.enterText(key('direct-secret'), 'temporary');
        await tester.pump();
        await tester.ensureVisible(key('direct-connect'));
        await tester.tap(key('direct-connect'));
        await tester.pump();
        await waitFor(tester, find.byType(TerminalView));
        await tester.pumpAndSettle();
        final dynamic state = tester.state(find.byType(DirectSshPage));
        final Terminal terminal = state.terminal;
        final Object liveShell = state.shell;
        final logAtConnect = log.readAsStringSync();
        final accepted = RegExp(r'ACCEPT (\d+)')
            .allMatches(logAtConnect)
            .last
            .group(1)!;
        expect(logAtConnect, contains('AUTH fixture'));
        expect(logAtConnect, contains('PTY '));
        expect(logAtConnect, isNot(contains('PEER_CLOSED $accepted')));
        expect(
          tester.widget<TerminalView>(find.byType(TerminalView)).padding,
          const EdgeInsets.all(12),
        );
        final closedWidth = terminal.viewWidth;
        final closedHeight = terminal.viewHeight;
        expect(closedWidth, greaterThan(0));
        expect(closedHeight, greaterThan(0));
        void rect(String id, Rect expected) {
          final actual = tester.getRect(key(id));
          for (final delta in [
            actual.left - expected.left,
            actual.top - expected.top,
            actual.width - expected.width,
            actual.height - expected.height,
          ]) {
            expect(
              delta.abs(),
              lessThanOrEqualTo(2),
              reason: '$id at $width: $actual vs $expected',
            );
          }
        }

        final margin = width == 320 ? 16.0 : 24.0;
        final safeTop = inset.top;
        rect(
          'direct-disconnect',
          Rect.fromLTWH(width - margin - 60, safeTop + 6, 60, 44),
        );
        rect(
          'direct-terminal-status',
          Rect.fromLTWH(margin, safeTop + 68, width - margin * 2, 44),
        );
        rect(
          'direct-keyboard-toggle',
          Rect.fromLTWH(width - margin - 44, safeTop + 68, 44, 44),
        );
        rect(
          'direct-terminal-panel',
          Rect.fromLTWH(
            margin,
            safeTop + 120,
            width - margin * 2,
            width == 320 ? 304 : 523,
          ),
        );
        rect(
          'direct-terminal-keys',
          Rect.fromLTWH(
            margin,
            width == 320 ? 456 : 698,
            width - margin * 2,
            width == 320 ? 92 : 44,
          ),
        );
        for (final id in [
          'esc',
          'tab',
          'up',
          'down',
          'left',
          'right',
          'ctrl-c',
        ]) {
          expect(key('direct-key-$id').hitTestable(), findsOneWidget);
        }
        expect(tester.widget<InkWell>(key('direct-tab-board')).onTap, isNull);
        expect(tester.widget<InkWell>(key('direct-tab-network')).onTap, isNull);
        await tester.tap(key('direct-keyboard-toggle'));
        await tester.pump();
        expect(tester.testTextInput.isVisible, isTrue);
        tester.view.viewInsets = FakeViewPadding(
          bottom: width == 320 ? 238 : 291,
        );
        tester.view.padding = FakeViewPadding(top: inset.top);
        await tester.pumpAndSettle();
        rect(
          'direct-terminal-panel',
          Rect.fromLTWH(
            margin,
            safeTop + 120,
            width - margin * 2,
            width == 320 ? 146 : 322,
          ),
        );
        rect(
          'direct-terminal-keys',
          Rect.fromLTWH(
            margin,
            width == 320 ? 298 : 497,
            width - margin * 2,
            width == 320 ? 92 : 44,
          ),
        );
        expect(terminal.viewHeight, lessThan(closedHeight));
        final previousClient =
            (tester.testTextInput.log
                            .lastWhere(
                              (call) => call.method == 'TextInput.setClient',
                            )
                            .arguments
                        as List)
                    .first
                as int;
        final before = 'before${width.toInt()}';
        tester.testTextInput.enterText(before);
        await tester.pump();
        await waitForLog(tester, log, (text) => text.contains(before));
        for (var i = 0; i < 60 && !terminalContains(terminal, before); i++) {
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 25)),
          );
          await tester.pump();
        }
        expect(terminalContains(terminal, before), isTrue);
        await tester.testTextInput.receiveAction(TextInputAction.done);
        await tester.pump();
        await tester.tap(key('direct-keyboard-toggle'));
        await tester.pump();
        expect(tester.testTextInput.isVisible, isFalse);
        tester.view.resetViewInsets();
        tester.view.padding = inset;
        await tester.pumpAndSettle();
        await tester.tap(key('direct-tab-settings'));
        await tester.pumpAndSettle();
        expect(key('direct-settings'), findsOneWidget);
        expect(identical(state.shell, liveShell), isTrue);
        expect(identical(state.terminal, terminal), isTrue);
        expect(
          log.readAsStringSync(),
          isNot(contains('PEER_CLOSED $accepted')),
        );
        terminal.textInput('blocked${width.toInt()}');
        await tester.pump();
        await tester.enterText(key('direct-settings-font'), '18');
        await tester.tap(key('direct-settings-save'));
        await tester.pumpAndSettle();
        expect(catalog.terminalFontSize, 18);
        await tester.tap(key('direct-settings-transfer'));
        await tester.pumpAndSettle();
        expect(find.byType(ConfigTransferPage), findsOneWidget);
        expect(identical(state.shell, liveShell), isTrue);
        await tester.pageBack();
        await tester.pumpAndSettle();
        if (width == 320) {
          await tester.binding.handlePopRoute();
        } else {
          await tester.tap(key('direct-tab-terminal'));
        }
        await tester.pumpAndSettle();
        expect(find.byType(TerminalView), findsOneWidget);
        expect(identical(state.shell, liveShell), isTrue);
        expect(identical(state.terminal, terminal), isTrue);
        await tester.tap(key('direct-keyboard-toggle'));
        await tester.pump();
        expect(tester.testTextInput.isVisible, isTrue);
        final stale = TextEditingValue(
          text: 'stale${width.toInt()}',
          selection: const TextSelection.collapsed(offset: 0),
        );
        tester.binding.defaultBinaryMessenger.handlePlatformMessage(
          SystemChannels.textInput.name,
          SystemChannels.textInput.codec.encodeMethodCall(
            MethodCall('TextInputClient.updateEditingState', [
              previousClient,
              stale.toJSON(),
            ]),
          ),
          (ByteData? _) {},
        );
        await tester.pump();
        final after = 'after${width.toInt()}';
        tester.testTextInput.enterText(after);
        await tester.pump();
        await waitForLog(tester, log, (text) => text.contains(after));
        final captured = log.readAsStringSync();
        expect(captured, isNot(contains('stale${width.toInt()}')));
        expect(captured, isNot(contains('blocked${width.toInt()}')));
        for (var i = 0; i < 60 && !terminalContains(terminal, after); i++) {
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 25)),
          );
          await tester.pump();
        }
        expect(terminalContains(terminal, after), isTrue);
        expect(captured, isNot(contains('PEER_CLOSED $accepted')));
        debugPrint(
          'terminal-$width PTY closed=$closedWidth x $closedHeight; current=${terminal.viewWidth} x ${terminal.viewHeight}; peer=$accepted',
        );
        await tester.tap(key('direct-disconnect'));
        await tester.pumpAndSettle();
        await waitForLog(
          tester,
          log,
          (text) => text.contains('PEER_CLOSED $accepted'),
        );
        expect(find.byType(TerminalView), findsNothing);
        expect(state.secret.text, isEmpty);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        catalog.dispose();
      },
      variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip:
          Platform.environment['HERDR_TERMINAL_PORT'] == null ||
          Platform.environment['HERDR_TERMINAL_LOG'] == null,
    );
  }
}
