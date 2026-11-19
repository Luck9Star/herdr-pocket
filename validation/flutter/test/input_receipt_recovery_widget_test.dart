import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/main.dart' as product;
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/remote_input_platform.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:herdr_flutter_probe/remote_page.dart';

import 'remote_input_journal_test.dart' show MemoryTargetInputJournal;

// Only the dedicated local runner provisions the disposable peer and keys.
void main() {
  final workDirectory = Platform.environment['HERDR_INPUT_RECEIPT_FIXTURE'];
  if (workDirectory != null) {
    LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
        LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  }
  testWidgets(
    'M3-05 actual remote product widget and loopback SSH with one missing receipt',
    (tester) async {
      final run = Directory(workDirectory!);
      File file(String name) => File('${run.path}/$name');
      final port = int.parse(file('port').readAsStringSync().trim());
      expect(port, inInclusiveRange(1, 65535));
      // Exercise the default app adapter and Dart channel codec with the
      // existing test storage. No native persistence is claimed.
      final journal = MemoryTargetInputJournal();
      final calls = <String>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(PlatformRemoteInputJournal.channel, (
        call,
      ) async {
        calls.add(call.method);
        final args = call.arguments as Map?;
        switch (call.method) {
          case 'readAll':
            return journal.readAll();
          case 'prepare':
            return journal.prepare(args!['record'] as String);
          case 'complete':
            await journal.complete(
              args!['record'] as String,
              args['lease'] as String,
            );
          case 'abandon':
            await journal.abandon(
              args!['record'] as String,
              args['lease'] as String,
            );
          case 'resolve':
            await journal.resolve(args!['record'] as String);
          default:
            throw MissingPluginException(call.method);
        }
        return null;
      });
      addTearDown(
        () => messenger.setMockMethodCallHandler(
          PlatformRemoteInputJournal.channel,
          null,
        ),
      );
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(1100, 1000);
      await tester.binding.setSurfaceSize(const Size(1100, 1000));
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(() => tester.binding.setSurfaceSize(null));
      Finder key(String name) => find.byKey(ValueKey('remote-$name'));
      void stage(String name) =>
          file('ui-stages')
              .writeAsStringSync('$name\n', mode: FileMode.append, flush: true);
      List<Map<String, dynamic>> events() =>
          file('peer.jsonl')
              .readAsLinesSync()
              .where((line) => line.isNotEmpty)
              .map((line) => (jsonDecode(line) as Map<String, dynamic>))
              .toList();
      List<Map<String, dynamic>> writes() =>
          events().where((e) => e['kind'] == 'input').toList();
      Future<void> waitFor(String phase, bool Function() ready) async {
        final deadline = DateTime.now().add(const Duration(seconds: 12));
        while (!ready()) {
          if (DateTime.now().isAfter(deadline)) fail('Timed out at $phase');
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 35)),
          );
          await tester.pump();
        }
      }

      Future<void> tap(String name) async {
        final control = key(name);
        await waitFor(name, () => control.evaluate().length == 1);
        await tester.ensureVisible(control);
        await tester.pump();
        expect(control.hitTestable(), findsOneWidget, reason: name);
        await tester.tap(control);
        await tester.pump();
      }

      Future<void> enter(String name, String text) async {
        await tester.ensureVisible(key(name));
        await tester.pump();
        await tester.enterText(key(name), text);
        await tester.pump();
      }

      bool enabled(String name) =>
          key(name).evaluate().single.widget is FilledButton &&
          tester.widget<FilledButton>(key(name)).onPressed != null;
      final pem = file('client')
          .readAsStringSync()
          .trim()
          .replaceAll('\n', r'\n');
      final expectedLabel =
          'fixture@127.0.0.1:$port / m305 / w1:p1 / term_a001';
      final unknown = find.text('发送结果待核实 · 仅本目标输入已锁定，不会重放');
      final original = find.textContaining('待核实目标：$expectedLabel');
      bool reviewEnabled() =>
          key('input-acknowledge').evaluate().length == 1 &&
          tester.widget<TextButton>(key('input-acknowledge')).onPressed != null;

      await tester.runAsync(product.main);
      await tester.pumpAndSettle();
      expect(find.byType(HostCatalogPage), findsOneWidget);
      final settings = find.widgetWithText(ListTile, '设置').hitTestable();
      expect(settings, findsOneWidget);
      await tester.tap(settings);
      await tester.pumpAndSettle();
      final homeLink = find.byKey(const ValueKey('hosts-offline'));
      await tester.ensureVisible(homeLink);
      await tester.pump();
      expect(homeLink.hitTestable(), findsOneWidget);
      await tester.tap(homeLink);
      await tester.pumpAndSettle();
      final manual = find.text('手动实验');
      expect(manual.hitTestable(), findsOneWidget);
      await tester.tap(manual);
      await tester.pumpAndSettle();
      expect(find.byType(RemotePage), findsOneWidget);
      stage('product_home');
      String renderedLine(int row, int width) {
        final views = find.byType(TerminalView).evaluate();
        if (views.length != 1) return '';
        final terminal = tester
            .widget<TerminalView>(find.byType(TerminalView))
            .terminal;
        return String.fromCharCodes(
          List.generate(
            width,
            (i) => terminal.buffer.lines[row].getCodePoint(i),
          ),
        );
      }

      for (final entry in <String, String>{
        'host': '127.0.0.1',
        'port': port.toString(),
        'username': 'fixture',
        'session': 'm305',
        'socketPath': '/tmp/m305-sim/herdr/sessions/m305/herdr.sock',
        'herdrPath': '/tmp/m305-sim/herdr',
        'expectedHostKey': file('host.pub')
            .readAsStringSync()
            .trim()
            .split(' ')
            .take(2)
            .join(' '),
      }.entries) {
        await enter(entry.key, entry.value);
      }
      Future<void> connect(String pane, String terminal) async {
        await enter('privateKeyPem', pem);
        await tap('review');
        await tap('connect');
        await waitFor(
          'pane ready',
          () =>
              key('pane-$pane').evaluate().length == 1 && enabled('pane-$pane'),
        );
        await tap('pane-$pane');
        await waitFor(
          'live full and delta $terminal',
          () =>
              renderedLine(0, terminal.length) == terminal &&
              renderedLine(1, 14) == 'FIXTURE ONLINE',
        );
        expect(
          events().where((e) => e['kind'] == 'fixture_auth').length,
          events().where((e) => e['kind'] == 'observe').length,
        );
      }

      Future<void> stop() async {
        await tap('cancel');
        await waitFor('stop', () => key('connect').evaluate().isNotEmpty);
      }

      await connect('w1:p1', 'term_a001');
      expect(writes(), isEmpty);
      stage('initial_a_full_delta');
      await tap('mode-draft');
      await enter('input-draft', 'M3-one');
      await tap('input-draft-send');
      await tap('input-confirm');
      await waitFor('A unknown', () => unknown.evaluate().isNotEmpty);
      expect(unknown, findsOneWidget);
      expect(original, findsOneWidget);
      expect(renderedLine(1, 14), 'FIXTURE ONLINE');
      await tester.ensureVisible(unknown);
      await tester.pump();
      expect(unknown.hitTestable(), findsOneWidget);
      expect(tester.widget<ChoiceChip>(key('mode-direct')).onSelected, isNull);
      expect(tester.widget<ChoiceChip>(key('mode-draft')).onSelected, isNull);
      expect(reviewEnabled(), isFalse);
      expect(writes(), hasLength(1));
      final write = writes().single;
      expect(write['exactFixtureInput'], isTrue);
      expect(write['size'], utf8.encode('M3-one').length);
      final record = RemoteInputPending.parse(journal.records.values.single);
      expect(record.requestId, write['request']);
      expect(record.target.label, expectedLabel);
      expect(record.raw, isNot(contains('M3-one')));
      expect(record.raw, isNot(contains(base64Encode(utf8.encode('M3-one')))));
      stage('unknown_a_target_locked');
      await stop();
      await connect('w1:p2', 'term_b002');
      expect(writes(), hasLength(1));
      expect(reviewEnabled(), isFalse);
      expect(journal.records.values.single, record.raw);
      expect(
        tester.widget<ChoiceChip>(key('mode-direct')).onSelected,
        isNotNull,
      );
      stage('switch_b_a_lock_retained');
      await stop();
      await connect('w1:p1', 'term_a001');
      await waitFor(
        'A recovery',
        () => unknown.evaluate().isNotEmpty && reviewEnabled(),
      );
      expect(original, findsOneWidget);
      expect(tester.widget<ChoiceChip>(key('mode-direct')).onSelected, isNull);
      expect(writes(), hasLength(1));
      stage('reconnect_a_fresh_full');
      await tap('input-acknowledge');
      await waitFor(
        'manual review resolved',
        () => journal.records.isEmpty && unknown.evaluate().isEmpty,
      );
      expect(tester.widget<ChoiceChip>(key('mode-observe')).selected, isTrue);
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 750)),
      );
      await tester.pump();
      expect(writes(), hasLength(1));
      expect(calls.where((method) => method == 'prepare'), hasLength(1));
      expect(calls.where((method) => method == 'abandon'), hasLength(1));
      expect(calls.where((method) => method == 'resolve'), hasLength(1));
      expect(calls.where((method) => method == 'complete'), isEmpty);
      stage('manual_confirmation_no_replay');
      await stop();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      stage('stopped');
    },
    skip: workDirectory == null,
  );
}
