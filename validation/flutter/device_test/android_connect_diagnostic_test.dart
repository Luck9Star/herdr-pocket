import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import '../integration_test/android_direct_ssh_test.dart'
    show encryptedFailure, target;
import '../integration_test/direct_ssh_ui_steps.dart'
    show finishAndroidEncryptedPassphrase, tapControl;

Future<void> expectNotReady(Future<void> Function() action) async {
  var failed = false;
  try {
    await action();
  } on TestFailure {
    failed = true;
  }
  expect(failed, isTrue);
}

class MovingAuthForm extends StatefulWidget {
  const MovingAuthForm({super.key, required this.onPressed});
  final VoidCallback onPressed;

  @override
  State<MovingAuthForm> createState() => _MovingAuthFormState();
}

class _MovingAuthFormState extends State<MovingAuthForm>
    with SingleTickerProviderStateMixin {
  late final AnimationController animation = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1300),
  )..repeat(reverse: true);

  @override
  void dispose() {
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(
        child: Column(
          children: [
            const SizedBox(height: 360),
            const TextField(),
            const TextField(obscureText: true),
            AnimatedBuilder(
              animation: animation,
              builder: (context, child) => Transform.translate(
                offset: Offset(animation.value * .3, 0),
                child: child,
              ),
              child: FilledButton(
                key: const ValueKey('connect'),
                onPressed: widget.onPressed,
                child: const Text('connect'),
              ),
            ),
            const SizedBox(height: 80),
          ],
        ),
      ),
    ),
  );
}

void main() {
  test('Android device errors export only bounded source locations', () {
    final locations = encryptedFailure(
      'encrypted_review',
      TestFailure('secret-exception-body'),
      StackTrace.fromString('''
#0      TestInput (file:///secret-path/secret-source.dart:12:27)
secret-body (file:///direct_ssh_ui_steps.dart:666:1)
#1      tap (file:///secret-path/direct_ssh_ui_steps.dart:112:27)
#2      tap (file:///secret-path/direct_ssh_ui_steps.dart:112:27)
#3      runEncryptedDirectSshUi (package:herdr_flutter_probe/integration_test/direct_ssh_ui_steps.dart:717:3)
#4      main.<anonymous closure> (file:///secret-path/android_direct_ssh_test.dart:241:17)
#5      main.<anonymous closure> (file:///secret-path/android_direct_ssh_test.dart:251:17)
#6      main.<anonymous closure> (file:///secret-path/android_direct_ssh_test.dart:260:17)
'''),
    );
    expect(locations, {
      'stage': 'encrypted_review',
      'code': 'direct_ssh_android_ui_failed',
      'exceptionClass': 'TestFailure',
      'sourceLocations': [
        {'file': 'direct_ssh_ui_steps.dart', 'line': 112},
        {'file': 'direct_ssh_ui_steps.dart', 'line': 717},
        {'file': 'android_direct_ssh_test.dart', 'line': 241},
        {'file': 'android_direct_ssh_test.dart', 'line': 251},
      ],
    });
  });

  test('an actual Dart exception keeps its Android entry source line', () {
    try {
      target();
    } on StateError catch (error, stack) {
      final diagnostic = encryptedFailure('fixture_validation', error, stack);
      expect(diagnostic['exceptionClass'], 'StateError');
      expect(diagnostic['sourceLocations'], [
        {'file': 'android_direct_ssh_test.dart', 'line': isPositive},
      ]);
      return;
    }
    fail('Android fixture guard did not reject the widget test runtime');
  });

  for (final reveal in [false, true]) {
    testWidgets(
      'fractional movement in scrollable auth form remains clickable reveal=$reveal',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(393, 873);
        tester.view.viewInsets = const FakeViewPadding(bottom: 182);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetViewInsets);
        var clicks = 0;
        final seen = <String>[];
        await tester.pumpWidget(MovingAuthForm(onPressed: () => clicks++));
        await tapControl(
          tester,
          find.byKey(const ValueKey('connect')),
          'connect',
          requireEnabled: true,
          stableHitPoint: true,
          reveal: reveal,
          timeout: const Duration(milliseconds: 150),
          onObservation: (status, _) => seen.add(status),
        );
        expect(seen, contains('ready'));
        expect(clicks, 1);
      },
    );
  }

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
        stableHitPoint: true,
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
        stableHitPoint: true,
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
        stableHitPoint: true,
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
      stableHitPoint: true,
      timeout: const Duration(seconds: 1),
      onObservation: (status, _) => seen.add(status),
    );
    expect(seen, contains('ready'));
    expect(clicks, 1);
  });

  testWidgets(
    'Android waits for a late keyboard resize before one connect tap',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(393, 851);
      addTearDown(tester.view.reset);
      final events = <String>[];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ListView(
              children: [
                const SizedBox(height: 560),
                const TextField(
                  key: ValueKey('direct-passphrase'),
                  obscureText: true,
                ),
                const SizedBox(height: 14),
                FilledButton(
                  key: const ValueKey('direct-connect'),
                  onPressed: () => events.add('tap'),
                  child: const Text('connect'),
                ),
              ],
            ),
          ),
        ),
      );
      await tester.enterText(
        find.byKey(const ValueKey('direct-passphrase')),
        'fixture-passphrase',
      );
      expect(tester.view.viewInsets.bottom, 0);
      Timer(const Duration(milliseconds: 250), () {
        events.add('ime_open');
        tester.view.viewInsets = const FakeViewPadding(bottom: 312);
      });
      final input = tester.testTextInput;
      input.log.clear();
      void closeImeAfterEdit(Duration _) {
        if (!input.log.any((call) => call.method == 'TextInput.clearClient')) {
          tester.binding.addPostFrameCallback(closeImeAfterEdit);
          return;
        }
        events.add('editing_done');
        Timer(const Duration(milliseconds: 150), () {
          events.add('ime_closed');
          tester.view.viewInsets = const FakeViewPadding();
        });
      }

      tester.binding.addPostFrameCallback(closeImeAfterEdit);
      await finishAndroidEncryptedPassphrase(tester);
      await tapControl(
        tester,
        find.byKey(const ValueKey('direct-connect')),
        'direct-connect',
        requireEnabled: true,
        stableHitPoint: true,
        onObservation: (status, _) => events.add(status),
      );
      expect(events, [
        'ime_open',
        'editing_done',
        'ime_closed',
        'unstable',
        'ready',
        'tap',
      ]);
    },
  );

  for (final mutation in ['moved', 'action replaced', 'element replaced']) {
    testWidgets('stable point never taps a button $mutation between frames', (
      tester,
    ) async {
      var clicks = 0;
      var changed = false;
      final seen = <String>[];
      late StateSetter update;
      VoidCallback original = () => clicks++;
      VoidCallback replacement = () => clicks += 100;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) {
                update = setState;
                return Transform.translate(
                  key: ValueKey(changed && mutation == 'element replaced'),
                  offset: Offset(changed && mutation == 'moved' ? 300 : 0, 0),
                  child: FilledButton(
                    key: const ValueKey('connect'),
                    onPressed: changed && mutation == 'action replaced'
                        ? replacement
                        : original,
                    child: const Text('connect'),
                  ),
                );
              },
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
          stableHitPoint: true,
          timeout: const Duration(seconds: 1),
          onObservation: (status, _) {
            seen.add(status);
            if (status == 'unstable') {
              Timer(const Duration(milliseconds: 150), () {
                update(() => changed = true);
              });
            }
          },
        ),
      );
      expect(changed, isTrue);
      expect(clicks, 0);
      if (mutation == 'element replaced') expect(seen.last, 'replaced');
    });
  }

  testWidgets('stable point rechecks interception immediately before tapping', (
    tester,
  ) async {
    var clicks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Stack(
            children: [
              FilledButton(
                key: const ValueKey('connect'),
                onPressed: () => clicks++,
                child: const Text('connect'),
              ),
              const Positioned.fill(
                child: IgnorePointer(
                  key: ValueKey('cover'),
                  ignoring: true,
                  child: ColoredBox(color: Colors.black),
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
        stableHitPoint: true,
        timeout: const Duration(seconds: 1),
        beforeTap: () {
          tester
                  .renderObject<RenderIgnorePointer>(
                    find.byKey(const ValueKey('cover')),
                  )
                  .ignoring =
              false;
        },
      ),
    );
    expect(clicks, 0);
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
      stableHitPoint: true,
      timeout: const Duration(seconds: 1),
      onObservation: (status, _) => seen.add(status),
    );
    expect(seen, containsAllInOrder(['unstable', 'ready']));
    expect(clicks, 1);
  });
}
