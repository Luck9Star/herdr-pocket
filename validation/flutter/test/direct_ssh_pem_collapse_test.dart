import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';

void main() {
  testWidgets('filled PEM collapses on blur and reopens intact', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final semantics = tester.ensureSemantics();
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    final boundary = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(key: boundary, child: MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens))));
    Future<void> capture(String name) async {
      final dir = Platform.environment['HERDR_PEM_EVIDENCE_DIR'];
      if (dir == null) return;
      await tester.runAsync(() async {
        final image = await (boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary).toImage();
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await File('$dir/$name.png').writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    final dynamic state = tester.state(find.byType(DirectSshPage));
    state.setState(() { state.mobileAuth = true; state.fingerprint = 'fixture'; state.checkedTarget = state.target; });
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    final field = find.byKey(const ValueKey('direct-secret'));
    const pem = 'synthetic line one\nsynthetic line two\nsynthetic line three';
    await tester.ensureVisible(field);
    await tester.tap(field);
    await tester.pumpAndSettle();
    await capture('empty-editor');
    await tester.enterText(field, pem);
    await tester.pump();
    final phrase = find.byKey(const ValueKey('direct-passphrase'));
    await tester.ensureVisible(phrase);
    await tester.tap(phrase);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
    expect(find.text('已填写私钥 · 重新编辑'), findsOneWidget);
    await capture('collapsed');
    expect(find.textContaining('synthetic line'), findsNothing);
    // The test view owns a child pipeline; inspect its semantics tree.
    // ignore: deprecated_member_use
    final nodes = tester.binding.pipelineOwner.semanticsOwner!.rootSemanticsNode!;
    var leaks = false;
    void inspect(SemanticsNode node) {
      final data = node.getSemanticsData();
      if ('${data.label} ${data.value}'.contains('synthetic line')) leaks = true;
      node.visitChildren((child) { inspect(child); return true; });
    }
    inspect(nodes);
    expect(leaks, isFalse);
    expect(tester.widget<TextField>(phrase).obscureText, isTrue);
    await tester.tap(find.text('已填写私钥 · 重新编辑'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text == pem, isTrue);
    expect(tester.widget<TextField>(field).focusNode!.hasFocus, isTrue);
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-edit-pem')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('direct-edit-pem')));
    await tester.pumpAndSettle();
    await tester.enterText(field, '');
    await tester.tap(phrase);
    await tester.pumpAndSettle();
    expect(field, findsOneWidget);
    expect(find.byKey(const ValueKey('direct-edit-pem')), findsNothing);
    await tester.tap(field);
    await tester.enterText(field, pem);
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-password')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-password')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text.isEmpty, isTrue);
    expect(find.byKey(const ValueKey('direct-edit-pem')), findsNothing);
    semantics.dispose();
  });

  testWidgets('re-tapping the selected auth choice is idempotent for PEM draft and passphrase', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    state.setState(() { state.mobileAuth = true; state.fingerprint = 'fixture'; state.checkedTarget = state.target; });
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    final field = find.byKey(const ValueKey('direct-secret'));
    const pem = 'synthetic line one\nsynthetic line two\nsynthetic line three';
    await tester.ensureVisible(field);
    await tester.tap(field);
    await tester.enterText(field, pem);
    final phrase = find.byKey(const ValueKey('direct-passphrase'));
    await tester.ensureVisible(phrase);
    await tester.enterText(phrase, 'draft-passphrase');
    await tester.pumpAndSettle();
    // Collapse the editor by focusing passphrase, then re-tap the SAME selected choice.
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-key')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-secret')), findsNothing);
    expect(find.text('已填写私钥 · 重新编辑'), findsOneWidget);
    expect(find.byKey(const ValueKey('direct-passphrase')), findsOneWidget);
    await tester.tap(find.text('已填写私钥 · 重新编辑'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text == pem, isTrue);
    expect(tester.widget<TextField>(phrase).controller!.text == 'draft-passphrase', isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('re-tapping the selected password choice keeps the typed password', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    state.setState(() { state.mobileAuth = true; state.fingerprint = 'fixture'; state.checkedTarget = state.target; });
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-auth-password')));
    await tester.pumpAndSettle();
    final field = find.byKey(const ValueKey('direct-secret'));
    await tester.ensureVisible(field);
    await tester.tap(field);
    await tester.enterText(field, 'draft-password');
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-password')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-password')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text == 'draft-password', isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('switching auth type still clears credentials; paste-in-flight on same choice is untouched', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    final dynamic state = tester.state(find.byType(DirectSshPage));
    state.setState(() { state.mobileAuth = true; state.fingerprint = 'fixture'; state.checkedTarget = state.target; });
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    // Paste in flight, then user re-taps the same choice: paste continues, no clear.
    final dynamic st = tester.state(find.byType(DirectSshPage));
    st.setState(() { st.pastingKey = true; });
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-key')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    expect((st.pastingKey as bool), isTrue);  // same-choice tap does not cancel the in-flight paste
    expect(st.pasteStatus, isNull);
    st.setState(() { st.pastingKey = false; st.pasteStatus = '私钥已粘贴，仅本次使用。'; });
    await tester.pumpAndSettle();
    // Real switch clears the draft.
    final field = find.byKey(const ValueKey('direct-secret'));
    await tester.ensureVisible(field);
    await tester.tap(field);
    await tester.enterText(field, 'old draft');
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-password')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-password')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text.isEmpty, isTrue);
    await tester.enterText(field, 'password draft');
    await tester.ensureVisible(find.byKey(const ValueKey('direct-auth-key')));
    await tester.tap(find.byKey(const ValueKey('direct-auth-key')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).controller!.text.isEmpty, isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('desktop outside tap reaches passphrase through collapse', (tester) async {
    tester.view.physicalSize = const Size(980, 780);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme: tokens.theme, home: DirectSshPage(tokens: tokens)));
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    final field = find.byKey(const ValueKey('direct-secret'));
    await tester.ensureVisible(field);
    await tester.tap(field);
    await tester.enterText(field, 'synthetic\nmultiline\nkey');
    await tester.pumpAndSettle();
    final phrase = find.byKey(const ValueKey('direct-passphrase'));
    await tester.ensureVisible(phrase);
    await tester.pumpAndSettle();
    final before = tester.getRect(phrase);
    final gesture = await tester.startGesture(before.center);
    await tester.pump();
    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-edit-pem')), findsOneWidget);
    expect(tester.getRect(phrase), before);
    expect(tester.testTextInput.isVisible, isTrue);
    expect(tester.widget<EditableText>(find.descendant(of: phrase, matching: find.byType(EditableText))).focusNode.hasFocus, isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.linux));

}
