import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

import 'direct_ssh_widget_test.dart' show enableKeyMode, waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

const _viewports = [Size(1440, 900), Size(980, 780), Size(700, 900)];
const _sidebar = {
  'app-sidebar': 'app-sidebar',
  'sidebar-toggle': 'sidebar-toggle',
  'nav-board': 'ssh-flow-nav-0',
  'nav-terminal': 'ssh-flow-nav-1',
  'nav-network': 'ssh-flow-nav-2',
  'nav-settings': 'ssh-flow-nav-3',
};
const _target = {
  'page-header': 'direct-page-header',
  'back': 'direct-back-hit',
  'host': 'direct-host',
  'username': 'direct-user',
  'port': 'direct-port',
  'probe': 'direct-probe',
};
const _auth = {
  'page-header': 'direct-page-header',
  'back': 'direct-back-hit',
  'target-card': 'direct-target-card',
  'trust-approved': 'direct-trust-approved',
  'auth-password': 'direct-auth-password',
  'auth-key': 'direct-auth-key',
  'connect': 'direct-connect',
};

void main() {
  final env = Platform.environment;
  final port = env['HERDR_DIRECT_SSH_FIXTURE_PORT'];
  final output = env['HERDR_ENTRY_PIXELS'];
  final design = env['HERDR_ENTRY_DESIGN'];
  final stages = (env['HERDR_ENTRY_VERIFY'] ?? '').split(',');
  for (final size in _viewports) {
    testWidgets('ordinary SSH entry and auth at ${size.width.toInt()}px', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = size;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      const family = 'Snapshot Chinese';
      final tokens = (await tester.runAsync(() async {
        final bytes = await File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf').readAsBytes();
        await (FontLoader(family)..addFont(Future.value(bytes.buffer.asByteData()))).load();
        for (final entry in {
          'MaterialIcons': 'fonts/MaterialIcons-Regular.otf',
          'ProbeNerd': 'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf',
        }.entries) {
          await (FontLoader(entry.key)..addFont(rootBundle.load(entry.value))).load();
        }
        return DesignTokens.load();
      }))!;
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      final geometry = jsonDecode(File(design!).readAsStringSync())['boards'] as List;
      Finder key(String id) => find.byKey(ValueKey(id));
      Future<void> tap(Finder finder) async {
        await tester.ensureVisible(finder);
        await tester.pumpAndSettle();
        expect(finder.hitTestable(), findsOneWidget);
        await tester.tap(finder);
        await tester.pumpAndSettle();
      }
      Future<void> record(String stage, Map<String, String> anchors) async {
        final id = '$stage-${size.width.toInt()}';
        final expected = geometry.singleWhere((entry) => entry['id'] == id)['anchors'] as Map;
        for (final entry in anchors.entries) {
          final candidates = key(entry.value);
          final visible = candidates.hitTestable();
          final actual = visible.evaluate().isNotEmpty ? visible.first : candidates;
          final rect = visible.evaluate().isEmpty && _sidebar.containsKey(entry.key) ||
              actual.evaluate().isEmpty ? null : tester.getRect(actual);
          final measured = rect == null ? null : [rect.left, rect.top, rect.width, rect.height];
          final reference = expected[entry.key] as Map;
          final bounds = ['x', 'y', 'width', 'height'].map((field) => reference[field] as num).toList();
          print('ANCHOR $id ${entry.key} ${jsonEncode(measured)} ${jsonEncode(bounds)}');
          if (stages.contains(stage)) {
            expect(measured, isNotNull, reason: '$id ${entry.key}');
            for (var index = 0; index < bounds.length; index++) {
              expect(measured![index], closeTo(bounds[index], 2), reason: '$id ${entry.key}');
            }
            if (reference['role'] == 'hit') {
              expect(actual.hitTestable(), findsOneWidget, reason: '$id ${entry.key}');
            }
          }
        }
        if (output != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(key('entry-capture'));
          await tester.runAsync(() async {
            final image = await boundary.toImage(pixelRatio: 1);
            try {
              final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
              await File('$output/$id.png').writeAsBytes(bytes!.buffer.asUint8List());
            } finally {
              image.dispose();
            }
          });
        }
      }
      await tester.pumpWidget(MaterialApp(
        theme: tokens.theme.copyWith(
          platform: TargetPlatform.linux,
          textTheme: tokens.theme.textTheme.apply(fontFamily: family),
          appBarTheme: tokens.theme.appBarTheme.copyWith(
            titleTextStyle: tokens.theme.appBarTheme.titleTextStyle?.copyWith(fontFamily: family),
          ),
        ),
        builder: (_, child) => RepaintBoundary(key: const ValueKey('entry-capture'), child: child!),
        home: HostCatalogPage(tokens: tokens, catalog: catalog, offlineBuilder: (_) => const SizedBox()),
      ));
      await tester.pumpAndSettle();
      await tap(key('hosts-add'));
      await record('choose', {
        ..._sidebar,
        'page-header': 'choose-header',
        'back': 'choose-back',
        'choose-ssh': 'choose-ssh',
        'choose-herdr': 'choose-herdr',
      });
      if (stages.contains('choose')) {
        final sidebar = key('app-sidebar');
        final toggle = key('sidebar-toggle');
        await tap(toggle);
        expect(tester.getSize(sidebar).width, size.width == 700 ? 224 : 64);
        await tap(toggle);
        expect(tester.getSize(sidebar).width, size.width == 700 ? 64 : 224);
        for (final (index, destination) in [
          (0, key('home-board-title')),
          (1, key('terminal')),
          (2, find.text('网络配置')),
          (3, key('hosts-terminal-preferences')),
        ]) {
          await tap(key('ssh-flow-nav-$index'));
          expect(destination, findsOneWidget);
          if (index != 0) {
            await tap(key(size.width == 700 ? 'home-tab-0' : 'hosts-board-tab'));
          }
          await tap(key('hosts-add'));
        }
        await tap(key('choose-back'));
        expect(key('hosts-add').hitTestable(), findsOneWidget);
        await tap(key('hosts-add'));
      }
      await tap(key('choose-ssh'));
      if (stages.contains('target')) {
        expect(key('direct-secret'), findsNothing);
        await tap(key('direct-back-hit'));
        expect(key('choose-ssh').hitTestable(), findsOneWidget);
        await tap(key('choose-ssh'));
        expect(tester.widget<FilledButton>(key('direct-probe')).onPressed, isNull);
      }
      await record('target', {..._sidebar, ..._target});
      print('TARGET_CREDENTIAL_BEFORE_CONFIRM ${key('direct-secret').evaluate().isNotEmpty}');
      await tester.enterText(key('direct-host'), '127.0.0.1');
      await tester.enterText(key('direct-user'), 'fixture');
      if (stages.contains('target')) {
        final field = key('direct-port');
        await tester.enterText(field, '65536');
        await tester.pump();
        expect(tester.widget<FilledButton>(key('direct-probe')).onPressed, isNull);
        await tester.enterText(field, '');
        await tester.enterText(field, '65535a9');
        await tester.pump();
        expect(tester.widget<TextField>(field).controller!.text, '65535');
      }
      await tester.enterText(key('direct-port'), port!);
      await tap(key('direct-host'));
      await record('target-focused', {..._sidebar, ..._target});
      if (stages.contains('target')) {
        final fields = ['direct-host', 'direct-user', 'direct-port'];
        for (final (index, field) in fields.indexed) {
          if (index != 0) {
            await tester.sendKeyEvent(LogicalKeyboardKey.tab);
            await tester.pump();
          }
          final editable = find.descendant(of: key(field), matching: find.byType(EditableText));
          expect(tester.widget<EditableText>(editable).focusNode.hasFocus, isTrue,
            reason: 'keyboard focus after $index Tab presses should be $field');
        }
      }
      await tap(key('direct-probe'));
      await waitFor(tester, key('direct-trust-key'));
      await tester.pumpAndSettle();
      await record('trust', {
        ..._sidebar,
        'page-header': 'direct-trust-header',
        'back': 'direct-trust-back',
        'target-card': 'direct-target-card',
        'key-evidence': 'direct-key-evidence',
        'key-fingerprint': 'direct-key-fingerprint',
        'independent-verification': 'direct-independent-verification',
        'trust-confirm': 'direct-trust-key',
        'trust-cancel': 'direct-trust-cancel',
      });
      if (stages.contains('trust')) {
        expect(key('direct-secret').hitTestable(), findsNothing);
        final fingerprint = find.descendant(of: key('direct-key-fingerprint'), matching: find.byType(SelectableText));
        expect(tester.widget<SelectableText>(fingerprint).data, matches(r'^SHA256:[A-Za-z0-9+/]{43}$'));
        await tap(key('direct-trust-cancel'));
        expect(key('direct-secret'), findsNothing);
        await tap(key('direct-probe'));
        await waitFor(tester, key('direct-trust-key'));
      }
      await tap(key('direct-trust-key'));
      await tester.enterText(key('direct-secret'), 'temporary');
      await tester.pumpAndSettle();
      await record('password', {..._sidebar, ..._auth, 'password': 'direct-secret'});
      if (stages.contains('password')) {
        expect(tester.widget<TextField>(key('direct-secret')).obscureText, isTrue);
        await tap(key('ssh-flow-nav-3'));
        expect(key('hosts-terminal-preferences'), findsOneWidget);
        await tap(key('home-tab-1'));
        expect(tester.widget<TextField>(key('direct-secret')).controller!.text, isEmpty);
        expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
      }
      await enableKeyMode(tester);
      await tester.pumpAndSettle();
      await record('private-key', {
        ..._sidebar,
        ..._auth,
        'key-pem': 'direct-secret',
        'paste-key': 'direct-paste-key',
        'passphrase': 'direct-passphrase',
      });
      if (stages.contains('private-key')) {
        expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
        await tester.enterText(key('direct-secret'), 'incomplete PEM');
        await tester.pump();
        expect(tester.widget<FilledButton>(key('direct-connect')).onPressed, isNull);
        await tester.binding.handlePopRoute();
        await tester.pumpAndSettle();
        expect(key('direct-secret'), findsNothing);
        expect(key('direct-host').hitTestable(), findsOneWidget);
      }
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant.only(TargetPlatform.linux), skip: port == null || design == null);
  }
}
