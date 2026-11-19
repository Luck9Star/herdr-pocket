import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';

import '../integration_test/direct_ssh_ui_steps.dart' as steps;

void main() {
  testWidgets('one home tap waits for the delayed SSH route and form', (
    tester,
  ) async {
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    var clicks = 0;
    var pageWasAbsentBeforePush = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: TextButton(
                key: const ValueKey('hosts-direct-ssh'),
                onPressed: () async {
                  clicks++;
                  await Future<void>.delayed(const Duration(milliseconds: 450));
                  if (context.mounted) {
                    pageWasAbsentBeforePush = find
                        .byType(DirectSshPage)
                        .evaluate()
                        .isEmpty;
                    Navigator.of(context).push<void>(
                      MaterialPageRoute(
                        builder: (_) => DirectSshPage(tokens: tokens),
                      ),
                    );
                  }
                },
                child: const Text('普通 SSH'),
              ),
            ),
          ),
        ),
      ),
    );

    await steps.openDirectSshFromHome(tester);
    final page = find.byType(DirectSshPage);
    expect(page, findsOneWidget);
    expect(find.byKey(const ValueKey('direct-form')), findsOneWidget);
    expect(ModalRoute.of(tester.element(page))?.animation?.isCompleted, isTrue);
    expect(pageWasAbsentBeforePush, isTrue);
    expect(clicks, 1);
  });

  testWidgets('waits for an uncovered stable enabled button and clicks once', (
    tester,
  ) async {
    var clicks = 0;
    final covered = ValueNotifier(true);
    addTearDown(covered.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Stack(
            children: [
              Center(
                child: FilledButton(
                  key: const ValueKey('connect'),
                  onPressed: () => clicks++,
                  child: const Text('Connect'),
                ),
              ),
              ValueListenableBuilder<bool>(
                valueListenable: covered,
                builder: (_, value, __) => value
                    ? const Positioned.fill(
                        child: ColoredBox(color: Colors.black),
                      )
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ),
    );
    Future<void>.delayed(
      const Duration(milliseconds: 350),
      () => covered.value = false,
    );
    await steps.tap(tester, 'connect', requireEnabled: true);
    expect(clicks, 1);
  });

  testWidgets('never clicks when the button remains covered', (tester) async {
    var clicks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Stack(
            children: [
              Center(
                child: FilledButton(
                  key: const ValueKey('connect'),
                  onPressed: () => clicks++,
                  child: const Text('Connect'),
                ),
              ),
              const Positioned.fill(child: ColoredBox(color: Colors.black)),
            ],
          ),
        ),
      ),
    );
    await expectLater(
      steps.tap(
        tester,
        'connect',
        requireEnabled: true,
        timeout: const Duration(milliseconds: 100),
      ),
      throwsA(isA<TestFailure>()),
    );
    expect(clicks, 0);
  });

  testWidgets(
    'finishes the iOS passphrase edit before one stable connect tap',
    (tester) async {
      tester.view.devicePixelRatio = 2;
      tester.view.physicalSize = const Size(828, 1792);
      addTearDown(tester.view.reset);
      final passphrase = steps.control('direct-passphrase');
      final connect = steps.control('direct-connect');
      final events = <String>[];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ListView(
              children: [
                const SizedBox(height: 430),
                TextField(
                  key: const ValueKey('direct-passphrase'),
                  obscureText: true,
                  onSubmitted: (_) {
                    expect(connect, findsNothing);
                    expect(tester.view.viewInsets.bottom, 692);
                    events.add('done');
                    Future<void>.delayed(const Duration(milliseconds: 150), () {
                      tester.view.viewInsets = const FakeViewPadding();
                      events.add('keyboard_closed');
                    });
                  },
                ),
                const SizedBox(height: 345),
                FilledButton(
                  key: const ValueKey('direct-connect'),
                  onPressed: () => events.add('tap'),
                  child: const Text('Connect'),
                ),
              ],
            ),
          ),
        ),
      );
      Future<void>.delayed(const Duration(milliseconds: 250), () {
        tester.view.viewInsets = const FakeViewPadding(bottom: 692);
        events.add('keyboard_open');
      });

      await steps.enterEncryptedPassphrase(
        tester,
        passphrase,
        'synthetic-passphrase',
        finishIosEditing: true,
      );
      expect(events, ['keyboard_open', 'done', 'keyboard_closed']);
      await steps.tap(
        tester,
        'direct-connect',
        requireEnabled: true,
        stableHitPoint: true,
      );
      expect(events, ['keyboard_open', 'done', 'keyboard_closed', 'tap']);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.iOS),
  );

  testWidgets('Android entry leaves the edit for its existing keyboard step', (
    tester,
  ) async {
    var submissions = 0;
    final passphrase = steps.control('direct-passphrase');
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TextField(
            key: const ValueKey('direct-passphrase'),
            obscureText: true,
            onSubmitted: (_) => submissions++,
          ),
        ),
      ),
    );
    await steps.enterEncryptedPassphrase(
      tester,
      passphrase,
      'synthetic-passphrase',
      finishIosEditing: false,
    );
    final editor = find.descendant(
      of: passphrase,
      matching: find.byType(EditableText),
    );
    expect(tester.widget<EditableText>(editor).focusNode.hasFocus, isTrue);
    expect(submissions, 0);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));
}
