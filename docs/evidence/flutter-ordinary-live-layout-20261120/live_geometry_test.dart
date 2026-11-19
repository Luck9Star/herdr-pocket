import 'dart:convert';
import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:terminal_view/terminal_view.dart';

import 'direct_ssh_widget_test.dart' show tapAndWaitForOrdinaryDisconnect, waitFor;
import 'herdr_workflow_visual_test.dart' show loadVisualTokens, save, size, visualApp;
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;

Finder key(String value) => find.byKey(ValueKey(value)).hitTestable();

const sidebarAnchors = {
  'app-sidebar': 'app-sidebar',
  'sidebar-toggle': 'sidebar-toggle',
  'nav-board': 'ssh-flow-nav-0',
  'nav-terminal': 'ssh-flow-nav-1',
  'nav-network': 'ssh-flow-nav-2',
  'nav-settings': 'ssh-flow-nav-3',
};

void main() {
  final port = Platform.environment['HERDR_DIRECT_SSH_FIXTURE_PORT'];
  final geometryPath = Platform.environment['HERDR_ENTRY_DESIGN'];
  final verify = Platform.environment['HERDR_LIVE_VERIFY'] == '1';
  for (final viewport in [const Size(1440, 900), const Size(980, 780), const Size(700, 900)]) {
    testWidgets('desktop ordinary SSH session at ${viewport.width.toInt()}px', (tester) async {
      size(tester, viewport);
      final tokens = await loadVisualTokens(tester);
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      await tester.pumpWidget(visualApp(tokens, HostCatalogPage(
        tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox(),
      )));
      await tester.pumpAndSettle();

      Future<void> tap(String id) async {
        final control = key(id);
        expect(control, findsOneWidget);
        await tester.tap(control);
        await tester.pumpAndSettle();
      }

      final boards = jsonDecode(File(geometryPath!).readAsStringSync())['boards'] as List;
      Future<void> record(String stage, Map<String, String> anchors) async {
        final id = '$stage-${viewport.width.toInt()}';
        final expected = boards.singleWhere((entry) => entry['id'] == id)['anchors'] as Map;
        for (final entry in anchors.entries) {
          final control = key(entry.value);
          Rect? rect;
          if (control.evaluate().length == 1) {
            rect = tester.getRect(control);
            if (entry.key == 'terminal-scrollbar') {
              final bar = tester.widget<RawScrollbar>(control);
              final padding = bar.padding!.resolve(TextDirection.ltr);
              rect = Rect.fromLTWH(rect.right - padding.right - bar.thickness!,
                rect.top + padding.top, bar.thickness!, rect.height - padding.vertical);
            }
          } else if (!verify && entry.key == 'terminal-panel') {
            rect = tester.getRect(find.byType(TerminalView));
          } else if (!verify && entry.key == 'disconnect') {
            rect = tester.getRect(find.widgetWithText(TextButton, '断开'));
          }
          final actual = rect == null ? null : [rect.left, rect.top, rect.width, rect.height];
          final reference = expected[entry.key] as Map;
          final target = ['x', 'y', 'width', 'height'].map((field) => reference[field] as num).toList();
          print('ANCHOR $id ${entry.key} ${jsonEncode(actual)} ${jsonEncode(target)}');
          if (verify) {
            expect(actual, isNotNull, reason: '$id ${entry.key}');
            for (var index = 0; index < target.length; index++) {
              expect(actual![index], closeTo(target[index], 2), reason: '$id ${entry.key}');
            }
          }
        }
        await save(tester, id);
      }

      await tap('hosts-direct-ssh');
      await tester.enterText(key('direct-host'), '127.0.0.1');
      await tester.enterText(key('direct-port'), port!);
      await tester.enterText(key('direct-user'), 'fixture');
      await tester.pumpAndSettle();
      await tap('direct-probe');
      await waitFor(tester, find.byKey(const ValueKey('direct-trust-key')));
      await tester.pumpAndSettle();
      await tap('direct-trust-key');
      await tester.enterText(key('direct-secret'), 'temporary');
      await tester.pumpAndSettle();
      await tap('direct-connect');
      final view = find.byType(TerminalView).hitTestable();
      await waitFor(tester, view);
      final terminal = tester.widget<TerminalView>(view).terminal;
      Future<void> waitForPeerText(String marker) async {
        for (var attempt = 0; attempt < 120 && !terminal.buffer.getText().contains(marker); attempt++) {
          await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 25)));
          await tester.pump();
        }
        expect(terminal.buffer.getText(), contains(marker));
      }

      await waitForPeerText('SCROLLBACK-READY');
      await tester.pumpAndSettle();
      await record('terminal', {
        ...sidebarAnchors, 'page-header': 'direct-live-header', 'disconnect': 'direct-desktop-disconnect',
        'terminal-status': 'direct-terminal-status', 'terminal-panel': 'direct-terminal-panel',
        'terminal-scrollbar': 'direct-terminal-scrollbar',
      });

      if (verify) {
        expect(key('direct-keyboard-toggle'), findsNothing);
        expect(find.widgetWithText(TextButton, 'Enter').hitTestable(), findsNothing);
        if (viewport.width == 700) {
          await tap('sidebar-toggle');
          expect(tester.getSize(key('app-sidebar')).width, 224);
          expect(tester.widget<TerminalView>(view).terminal, same(terminal));
          await tap('sidebar-toggle');
          expect(tester.getSize(key('app-sidebar')).width, 64);
        }
        await tester.tap(view);
        await tester.pumpAndSettle();
        final focus = tester.widget<TerminalView>(view).focusNode!;
        expect(FocusManager.instance.primaryFocus, same(focus));
        final position = tester.widget<TerminalView>(view).scrollController!;
        await tester.sendEventToBinding(PointerScrollEvent(position: tester.getCenter(view), scrollDelta: const Offset(0, -240)));
        await tester.pumpAndSettle();
        final offset = position.offset;
        expect(offset, lessThan(position.position.maxScrollExtent));
        for (final stage in [
          ('board-active', 0, {'active-ssh': 'desktop-ssh-active', 'home-empty-card': 'home-empty-card',
            'home-add': 'hosts-add', 'home-direct-ssh': 'hosts-direct-ssh'}),
          ('network-active', 2, {'active-ssh': 'desktop-ssh-active', 'network-empty-card': 'network-empty-card',
            'network-add': 'networks-add'}),
          ('settings-active', 3, {'page-header': 'direct-live-header', 'active-ssh': 'direct-settings-active',
            'target-card': 'direct-target-card', 'font-size': 'direct-settings-font',
            'save-font-size': 'direct-settings-save', 'transfer-settings': 'direct-settings-transfer'}),
        ]) {
          await tap('ssh-flow-nav-${stage.$2}');
          expect(view, findsNothing);
          expect(focus.hasPrimaryFocus, isFalse);
          expect(tester.getSize(key('ssh-flow-online')), const Size(8, 8));
          await record(stage.$1, {...sidebarAnchors, ...stage.$3});
          if (stage.$2 == 2) {
            await tap('networks-add');
            expect(key('network-label'), findsOneWidget);
            await tester.tap(find.widgetWithText(TextButton, '取消').hitTestable());
            await tester.pumpAndSettle();
          }
          if (stage.$2 == 3) {
            await tap('direct-settings-save');
            expect(find.text('终端字号已保存。'), findsOneWidget);
            await tap('direct-settings-transfer');
            expect(find.text('加密迁移公开配置'), findsOneWidget);
            await tester.pageBack();
            await tester.pumpAndSettle();
          }
          await tap('ssh-flow-nav-1');
          expect(tester.widget<TerminalView>(view).terminal, same(terminal));
          expect(tester.widget<TerminalView>(view).focusNode, same(focus));
          expect(FocusManager.instance.primaryFocus, same(focus));
          expect(position.offset, closeTo(offset, .01));
        }
        if (viewport.width == 1440) {
          await catalog.add(tabProfile('Saved workstation', 'saved', '127.0.0.1', 'direct', 'fixture'));
          await tester.pumpAndSettle();
          expect(find.text('Saved workstation').hitTestable(), findsOneWidget);
          expect(find.text('还没有主机 · 从看板添加').hitTestable(), findsNothing);
        }
        tester.testTextInput.enterText('Q');
        await waitForPeerText('ECHO:Q');
        await tap('direct-desktop-disconnect');
        await waitFor(tester, find.text('本机已断开'));
      } else {
        await tapAndWaitForOrdinaryDisconnect(tester);
      }
      expect(find.text('本机已断开'), findsOneWidget);
      await tap('direct-return-home');
      expect(key('home-ssh-closed'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant.only(TargetPlatform.linux), skip: port == null || geometryPath == null);
  }
}
