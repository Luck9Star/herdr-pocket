import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../integration_test/direct_ssh_ui_steps.dart' as steps;

void main() {
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
