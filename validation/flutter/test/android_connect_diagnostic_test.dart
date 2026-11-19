import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../integration_test/direct_ssh_ui_steps.dart' show tapControl;

Future<void> expectNotReady(Future<void> Function() action) async {
  var failed = false;
  try {
    await action();
  } on TestFailure {
    failed = true;
  }
  expect(failed, isTrue);
}

void main() {
  testWidgets('connect observation distinguishes absent and disabled buttons', (
    tester,
  ) async {
    final seen = <String>[];
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: SizedBox())),
    );
    final finder = find.byKey(const ValueKey('connect'));
    await expectNotReady(
      () => tapControl(
        tester,
        finder,
        'connect',
        requireEnabled: true,
        timeout: const Duration(milliseconds: 80),
        onObservation: (status, _) => seen.add(status),
      ),
    );
    expect(seen, contains('missing'));
    seen.clear();
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: FilledButton(
            key: ValueKey('connect'),
            onPressed: null,
            child: Text('connect'),
          ),
        ),
      ),
    );
    await expectNotReady(
      () => tapControl(
        tester,
        finder,
        'connect',
        requireEnabled: true,
        timeout: const Duration(milliseconds: 80),
        onObservation: (status, _) => seen.add(status),
      ),
    );
    expect(seen, contains('disabled'));
  });

  testWidgets('connect observation detects a covered button', (tester) async {
    final seen = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Stack(
            children: [
              FilledButton(
                key: const ValueKey('connect'),
                onPressed: () {},
                child: const Text('connect'),
              ),
              Positioned.fill(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () {},
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await expectNotReady(
      () => tapControl(
        tester,
        find.byKey(const ValueKey('connect')),
        'connect',
        requireEnabled: true,
        timeout: const Duration(milliseconds: 80),
        onObservation: (status, _) => seen.add(status),
      ),
    );
    expect(seen, contains('not_hit'));
  });

  testWidgets('connect observation scrolls an offscreen button into view', (
    tester,
  ) async {
    final seen = <String>[];
    var clicks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: Column(
              children: [
                const SizedBox(height: 1000),
                FilledButton(
                  key: const ValueKey('connect'),
                  onPressed: () => clicks++,
                  child: const Text('connect'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tapControl(
      tester,
      find.byKey(const ValueKey('connect')),
      'connect',
      requireEnabled: true,
      timeout: const Duration(seconds: 1),
      onObservation: (status, _) => seen.add(status),
    );
    expect(seen, contains('ready'));
    expect(clicks, 1);
  });

  testWidgets('connect observation confirms stable hit and clicks once', (
    tester,
  ) async {
    final seen = <String>[];
    var clicks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FilledButton(
            key: const ValueKey('connect'),
            onPressed: () => clicks++,
            child: const Text('connect'),
          ),
        ),
      ),
    );
    await tapControl(
      tester,
      find.byKey(const ValueKey('connect')),
      'connect',
      requireEnabled: true,
      timeout: const Duration(seconds: 1),
      onObservation: (status, _) => seen.add(status),
    );
    expect(seen, containsAllInOrder(['unstable', 'ready']));
    expect(clicks, 1);
  });
}
