import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/macos_secure_credential_field.dart';
import '../lib/direct_ssh_page.dart';
import '../lib/design_tokens.dart';

void macTestWidgets(String description, WidgetTesterCallback callback) =>
    testWidgets(
      description,
      callback,
      variant: TargetPlatformVariant.only(TargetPlatform.macOS),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const codec = StandardMethodCodec();
  final calls = <int, List<MethodCall>>{};
  var failSync = false;
  setUp(() {
    calls.clear();
    failSync = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform_views, (call) async {
          if (call.method == 'create') {
            final id = (call.arguments as Map)['id'] as int;
            calls[id] = [];
            TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
                .setMockMethodCallHandler(
                  MethodChannel('herdr.pocket/secure-field/$id'),
                  (event) async {
                    calls[id]!.add(event);
                    if (event.method == 'sync' && failSync)
                      throw PlatformException(code: 'secure_field_unavailable');
                    return null;
                  },
                );
          }
          return null;
        });
  });
  tearDown(() {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform_views, null);
    for (final id in calls.keys) {
      messenger.setMockMethodCallHandler(
        MethodChannel('herdr.pocket/secure-field/$id'),
        null,
      );
    }
  });

  Future<void> pumpField(
    WidgetTester tester,
    TextEditingController controller, {
    bool enabled = true,
    Brightness brightness = Brightness.light,
    String identifier = 'direct-secret',
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(brightness: brightness),
        home: Scaffold(
          body: Semantics(
            container: true,
            child: MacosSecureCredentialField(
              key: ValueKey(identifier),
              controller: controller,
              enabled: enabled,
              identifier: identifier,
              label: identifier == 'direct-secret' ? '密码（仅本次使用）' : '私钥口令（可选）',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  int revision(int id) =>
      (calls[id]!.lastWhere((c) => c.method == 'sync').arguments
              as Map)['revision']
          as int;
  Future<void> nativeEvent(
    WidgetTester tester,
    int id,
    MethodCall event,
  ) async {
    final done = Completer<void>();
    tester.binding.defaultBinaryMessenger.handlePlatformMessage(
      'herdr.pocket/secure-field/$id',
      codec.encodeMethodCall(event),
      (_) {
        done.complete();
      },
    );
    await done.future;
    await tester.pump();
  }

  Future<void> edit(WidgetTester tester, int id, int epoch, String text) =>
      nativeEvent(
        tester,
        id,
        MethodCall('changed', {'revision': epoch, 'text': text}),
      );

  macTestWidgets(
    'native edits reach the memory controller without Flutter EditableText',
    (tester) async {
      final controller = TextEditingController();
      await pumpField(tester, controller);
      final id = calls.keys.single, epoch = revision(calls.keys.single);
      final nonce = UniqueKey().toString();
      await edit(tester, id, epoch, nonce.substring(0, 2));
      await edit(tester, id, epoch, nonce);
      expect(controller.text == nonce, isTrue);
      expect(find.byType(EditableText), findsNothing);
      expect(tester.getSize(find.byType(AppKitView)).height, 40);
      expect(
        tester
            .widget<InputDecorator>(find.byType(InputDecorator))
            .decoration
            .floatingLabelBehavior,
        FloatingLabelBehavior.always,
      );
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  macTestWidgets(
    'clear, metadata updates, disable and rebuild reject stale secret callbacks',
    (tester) async {
      final controller = TextEditingController();
      await pumpField(tester, controller);
      final id = calls.keys.single, beforeClear = revision(calls.keys.single);
      final nonce = UniqueKey().toString();
      await edit(tester, id, beforeClear, nonce);
      controller.clear();
      await tester.pumpAndSettle();
      final clear = calls[id]!.last.arguments as Map;
      expect(clear['text'] == '', isTrue);
      await edit(tester, id, beforeClear, nonce);
      expect(controller.text.isEmpty, isTrue);
      await pumpField(tester, controller, brightness: Brightness.dark);
      expect((calls[id]!.last.arguments as Map).containsKey('text'), isFalse);
      await pumpField(
        tester,
        controller,
        enabled: false,
        brightness: Brightness.dark,
      );
      await edit(tester, id, revision(id), nonce);
      expect(controller.text.isEmpty, isTrue);
      await pumpField(tester, controller);
      expect((calls[id]!.last.arguments as Map).containsKey('text'), isFalse);
      await edit(tester, id, revision(id), '');
      expect(controller.text.isEmpty, isTrue);
      await pumpField(tester, controller, identifier: 'direct-passphrase');
      expect(calls[id]!.any((c) => c.method == 'retire'), isTrue);
      final newId = calls.keys.last;
      expect(newId != id, isTrue);
      await edit(tester, id, revision(id), nonce);
      expect(controller.text.isEmpty, isTrue);
      expect(
        ((calls[newId]!.last.arguments as Map)['text'] as String).isEmpty,
        isTrue,
      );
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  macTestWidgets(
    'unavailable native input clears memory and has no editable Flutter fallback',
    (tester) async {
      final controller = TextEditingController();
      await pumpField(tester, controller);
      final id = calls.keys.single;
      failSync = true;
      controller.text = UniqueKey().toString();
      await tester.pumpAndSettle();
      expect(controller.text.isEmpty, isTrue);
      expect(find.text('原生安全输入不可用，请重新打开此页。'), findsOneWidget);
      expect(find.byType(EditableText), findsNothing);
      await edit(tester, id, revision(id), UniqueKey().toString());
      expect(controller.text.isEmpty, isTrue);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  for (final staged in [false, true]) {
    macTestWidgets(
      'native passphrase focus collapses PEM in the ${staged ? 'staged' : 'legacy'} form',
      (tester) async {
        final semantics = tester.ensureSemantics();
        try {
          final tokens = (await tester.runAsync(DesignTokens.load))!;
          await tester.pumpWidget(
            MaterialApp(
              theme: tokens.theme,
              home: DirectSshPage(
                tokens: tokens,
                desktopFlowShell: staged
                    ? (page, select, [selected]) => page
                    : null,
              ),
            ),
          );
          await tester.pumpAndSettle();
          if (staged) {
            final dynamic page = tester.state(find.byType(DirectSshPage));
            page.setState(() {
              page.mobileAuth = true;
              page.fingerprint = 'synthetic host fingerprint';
              page.checkedTarget = page.target;
            });
            await tester.pumpAndSettle();
          }
          final toggle = staged
              ? find.byKey(const ValueKey('direct-auth-key'))
              : find.byType(SwitchListTile);
          await tester.ensureVisible(toggle);
          await tester.tap(toggle);
          await tester.pumpAndSettle();
          final pem = find.byKey(const ValueKey('direct-secret'));
          final summary = find.byKey(const ValueKey('direct-edit-pem'));
          final id = calls.keys.last;
          const draft = 'Synthetic preview\nLong enough to detect';
          bool draftExposed() =>
              tester.semantics.simulatedAccessibilityTraversal().any((node) {
                final data = node.getSemanticsData();
                return data.label.contains(draft) || data.value.contains(draft);
              });
          await tester.ensureVisible(pem);
          await tester.tap(pem);
          await tester.enterText(pem, draft);
          await tester.pumpAndSettle();
          final focus = tester.widget<TextField>(pem).focusNode!;
          expect(focus.hasPrimaryFocus, isTrue);
          expect(draftExposed(), isTrue);
          await nativeEvent(
            tester,
            id,
            MethodCall('focused', {'revision': revision(id) - 1}),
          );
          await nativeEvent(
            tester,
            id,
            MethodCall('focused', {
              'revision': revision(id),
              'text': 'unexpected',
            }),
          );
          expect(focus.hasPrimaryFocus, isTrue);
          await nativeEvent(
            tester,
            id,
            MethodCall('focused', {'revision': revision(id)}),
          );
          await tester.pumpAndSettle();
          expect(
            pem.evaluate().isEmpty,
            isTrue,
            reason: 'native focus must hide the PEM editor',
          );
          expect(summary, findsOneWidget);
          expect(draftExposed(), isFalse);
          await tester.ensureVisible(summary);
          await tester.tap(summary);
          await tester.pumpAndSettle();
          expect(
            tester.widget<TextField>(pem).focusNode!.hasPrimaryFocus,
            isTrue,
          );
          expect(
            tester.widget<TextField>(pem).controller!.text == draft,
            isTrue,
          );
          await nativeEvent(
            tester,
            id,
            MethodCall('focused', {'revision': revision(id)}),
          );
          await tester.pumpAndSettle();
          expect(
            pem.evaluate().isEmpty,
            isTrue,
            reason: 'native refocus must hide the PEM editor',
          );
          expect(summary, findsOneWidget);
          expect(draftExposed(), isFalse);
        } finally {
          semantics.dispose();
        }
      },
    );
  }

  macTestWidgets(
    'macOS form keeps PEM editable and retires secrets across authentication switches',
    (tester) async {
      final tokens = (await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(
        MaterialApp(
          theme: tokens.theme,
          home: DirectSshPage(tokens: tokens),
        ),
      );
      await tester.pumpAndSettle();
      final passwordId = calls.keys.single;
      final nonce = UniqueKey().toString();
      await edit(tester, passwordId, revision(passwordId), nonce);
      expect(
        tester
                .widget<MacosSecureCredentialField>(
                  find.byType(MacosSecureCredentialField),
                )
                .controller
                .text ==
            nonce,
        isTrue,
      );
      expect(find.byType(EditableText), findsNWidgets(3));
      await tester.ensureVisible(find.byType(SwitchListTile));
      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();
      final pem = tester
          .widget<TextField>(find.byKey(const ValueKey('direct-secret')))
          .controller!;
      expect(pem.text.isEmpty, isTrue);
      expect(find.byType(EditableText), findsNWidgets(4));
      final phraseId = calls.keys.last;
      expect(phraseId != passwordId, isTrue);
      await edit(tester, passwordId, revision(passwordId), nonce);
      expect(pem.text.isEmpty, isTrue);
      await edit(tester, phraseId, revision(phraseId), nonce);
      expect(
        tester
                .widget<MacosSecureCredentialField>(
                  find.byType(MacosSecureCredentialField),
                )
                .controller
                .text ==
            nonce,
        isTrue,
      );
      expect(pem.text.isEmpty, isTrue);
      await tester.ensureVisible(find.byType(SwitchListTile));
      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();
      final freshId = calls.keys.last;
      expect(freshId != phraseId && freshId != passwordId, isTrue);
      await edit(tester, phraseId, revision(phraseId), nonce);
      expect(
        tester
            .widget<MacosSecureCredentialField>(
              find.byType(MacosSecureCredentialField),
            )
            .controller
            .text
            .isEmpty,
        isTrue,
      );
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );
}
