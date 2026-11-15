import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  late int baseline;
  setUpAll(() {
    baseline = binding.debugOutstandingSemanticsHandles;
    binding.platformDispatcher.semanticsEnabledTestValue = true;
  });
  tearDownAll(() {
    binding.platformDispatcher.clearSemanticsEnabledTestValue();
    expect(
      binding.platformDispatcher.semanticsEnabled,
      ui.PlatformDispatcher.instance.semanticsEnabled,
    );
    expect(binding.debugOutstandingSemanticsHandles, baseline);
  });

  testWidgets('stable semantics baseline is preserved', (tester) async {
    expect(binding.platformDispatcher.semanticsEnabled, isTrue);
    final owned = tester.ensureSemantics();
    await tester.pumpWidget(const MaterialApp(home: Text('fixture')));
    owned.dispose();
  });

  testWidgets('additional leaked handle remains detectable', (tester) async {
    final extra = tester.ensureSemantics();
    addTearDown(extra.dispose);
    await tester.pumpWidget(const MaterialApp(home: Text('fixture')));
  });
}
