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
}
