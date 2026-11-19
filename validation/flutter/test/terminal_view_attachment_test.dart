import 'dart:ui' show Scene, SemanticsUpdate;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';

class _TerminalView extends TestFlutterView {
  _TerminalView(TestFlutterView parent)
    : super(
        view: parent,
        platformDispatcher: parent.platformDispatcher,
        display: parent.display,
      );

  @override
  int get viewId => 91;

  // The test engine has only one real view. Test the secondary view's widget
  // tree and platform request without rendering it into the primary view.
  @override
  void render(Scene scene, {Size? size}) {}

  @override
  void updateSemantics(SemanticsUpdate update) {}
}

void main() {
  testWidgets('terminal attaches text input to its own Flutter view', (
    tester,
  ) async {
    final view = _TerminalView(tester.view);
    final focus = FocusNode();
    final terminal = Terminal();
    final attachedViews = <Object?>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.textInput, (call) async {
      if (call.method == 'TextInput.setClient') {
        final config = (call.arguments as List<Object?>)[1] as Map;
        final viewId = config['viewId'];
        attachedViews.add(viewId);
        // Flutter 3.47.9's Windows engine rejects an absent or non-integer ID.
        if (viewId is! int) throw PlatformException(code: 'Bad Arguments');
      }
      return null;
    });
    try {
      await tester.pumpWidget(
        View(
          view: view,
          child: MaterialApp(
            home: Scaffold(body: TerminalView(terminal, focusNode: focus)),
          ),
        ),
        wrapWithView: false,
      );
      focus.requestFocus();
      await tester.pumpAndSettle();
      final error = tester.takeException();
      expect(attachedViews, [view.viewId]);
      expect(error, isNull);
    } finally {
      await tester.pumpWidget(const SizedBox());
      messenger.setMockMethodCallHandler(SystemChannels.textInput, null);
      focus.dispose();
      terminal.dispose();
    }
  });
}
