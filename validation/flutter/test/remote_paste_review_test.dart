import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'remote_input_widget_test.dart' as input;

void mockClipboard(Future<Object?> Function(MethodCall) handler) {
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  messenger.setMockMethodCallHandler(SystemChannels.platform,handler);
  addTearDown(() => messenger.setMockMethodCallHandler(SystemChannels.platform,null));
}
void clipboardText(String text) => mockClipboard((call) async => switch (call.method) {
  'Clipboard.getData' => {'text':text},'Clipboard.hasStrings' => {'value':true},_ => null,
});
Future<void> press(WidgetTester tester,String key) async {
  final button = find.byKey(ValueKey(key)); await tester.ensureVisible(button);
  await tester.tap(button); await tester.pumpAndSettle();
}
Future<TextEditingController> startDraft(WidgetTester tester,input.InputFixtureAdapter adapter,String text) async {
  await input.start(tester,adapter); await input.mode(tester,'draft');
  final field = find.byKey(const ValueKey('remote-input-draft'));
  await tester.ensureVisible(field); await tester.enterText(field,text); await tester.pump();
  return tester.widget<TextField>(field).controller!;
}
void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('direct paste at ${width}px reviews inert controls, edits locally, and needs a separate send confirmation',(tester) async {
      const raw = 'A中文\n\x1b[31m\u202eB'; clipboardText(raw);
      final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,width:width); await input.mode(tester,'direct');
      await press(tester,'remote-input-paste');
      expect(adapter.received,isEmpty); expect(find.text('预览发送文本'),findsNothing);
      final review = tester.widget<SelectableText>(find.byKey(const ValueKey('remote-paste-review-text'))).data!;
      expect(review,contains('[LF]\n[ESC][31m[U+202E]B')); expect(review, isNot(contains('\u202e')));
      await press(tester,'remote-paste-append');
      final field = find.byKey(const ValueKey('remote-input-draft'));
      expect(tester.widget<TextField>(field).controller!.text,raw); expect(adapter.received,isEmpty);
      await press(tester,'remote-input-draft-send');
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-input-review-text'))).data,review);
      expect(adapter.received,isEmpty); await press(tester,'remote-input-confirm');
      expect(adapter.received.map((bytes) => utf8.decode(bytes)),[raw]);
      expect(tester.widget<TextField>(field).controller!.text,isEmpty);
      expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  for (final choice in ['append','replace','cancel']) {
    testWidgets('draft paste $choice is explicit local editing and preserves original newline bytes',(tester) async {
      clipboardText('CLIP\n'); final adapter = input.InputFixtureAdapter();
      final controller = await startDraft(tester,adapter,'ORIGINAL');
      await press(tester,'remote-input-draft-paste'); expect(controller.text,'ORIGINAL'); expect(adapter.received,isEmpty);
      await press(tester,'remote-paste-$choice');
      expect(controller.text,choice == 'append' ? 'ORIGINALCLIP\n' : choice == 'replace' ? 'CLIP\n' : 'ORIGINAL');
      expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('oversized UTF8 draft disables append but permits explicit replacement without truncation',(tester) async {
    clipboardText('replacement'); final adapter = input.InputFixtureAdapter();
    final original = List.filled(1366,'中').join(),controller = await startDraft(tester,adapter,List.filled(1366,'中').join());
    expect(utf8ByteLength(original),4098); await press(tester,'remote-input-draft-paste');
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('remote-paste-append'))).onPressed,isNull);
    expect(tester.widget<TextButton>(find.byKey(const ValueKey('remote-paste-replace'))).onPressed,isNotNull);
    expect(controller.text,original); await press(tester,'remote-paste-replace');
    expect(controller.text,'replacement'); expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('oversized clipboard is visible and cannot append or replace the original draft',(tester) async {
    clipboardText(List.filled(4097,'x').join()); final adapter = input.InputFixtureAdapter();
    final controller = await startDraft(tester,adapter,'original'); await press(tester,'remote-input-draft-paste');
    expect(find.textContaining('剪贴板文本超过 4096'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('remote-paste-append'))).onPressed,isNull);
    expect(tester.widget<TextButton>(find.byKey(const ValueKey('remote-paste-replace'))).onPressed,isNull);
    await press(tester,'remote-paste-cancel'); expect(controller.text,'original'); expect(adapter.received,isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
  for (final route in ['intent','menu']) {
    testWidgets('draft platform $route paste uses the same review instead of changing text immediately',(tester) async {
      clipboardText('CLIP'); final adapter = input.InputFixtureAdapter(); final controller = await startDraft(tester,adapter,'original');
      final field = find.byKey(const ValueKey('remote-input-draft')); await tester.showKeyboard(field); await tester.pump();
      final editable = find.descendant(of:field,matching:find.byType(EditableText));
      final state = tester.state<EditableTextState>(editable);
      if (route == 'intent') {
        Actions.invoke(state.widget.focusNode.context!,const PasteTextIntent(SelectionChangedCause.keyboard)); await tester.pumpAndSettle();
      } else {
        expect(state.showToolbar(),isTrue); await tester.pumpAndSettle();
        await tester.tap(find.text('审查粘贴')); await tester.pumpAndSettle();
      }
      expect(controller.text,'original'); expect(find.byKey(const ValueKey('remote-paste-append')),findsOneWidget);
      await press(tester,'remote-paste-append'); expect(controller.text,'originalCLIP'); expect(adapter.received,isEmpty);
      expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('clipboard completion after a same-target ABA edit cannot open or apply an old review',(tester) async {
    final read = Completer<Object?>(); mockClipboard((call) async => call.method == 'Clipboard.getData' ? read.future : null);
    final adapter = input.InputFixtureAdapter(); final controller = await startDraft(tester,adapter,'original');
    await press(tester,'remote-input-draft-paste'); controller.text = 'changed'; controller.text = 'original';
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('remote-input-draft-send'))).onPressed,isNotNull);
    read.complete({'text':'late'}); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('remote-paste-append')),findsNothing); expect(controller.text,'original');
    expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('direct focus loss during a pending clipboard read revokes input before a modal exists',(tester) async {
    final read = Completer<Object?>(); mockClipboard((call) async => call.method == 'Clipboard.getData' ? read.future : null);
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    final focus = tester.widget<TerminalView>(find.byType(TerminalView)).focusNode!;
    await press(tester,'remote-input-paste'); expect(find.byKey(const ValueKey('remote-paste-append')),findsNothing);
    expect(focus.hasFocus,isTrue);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).selected,isTrue);
    focus.unfocus(); await tester.pump(); await tester.pump();
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    read.complete({'text':'late'}); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('remote-paste-append')),findsNothing); expect(adapter.received,isEmpty);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('committed multiline IME text supersedes a pending clipboard read without losing its preview or focus ownership',(tester) async {
    final read = Completer<Object?>(); mockClipboard((call) async => call.method == 'Clipboard.getData' ? read.future : null);
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    final focus = tester.widget<TerminalView>(find.byType(TerminalView)).focusNode!;
    await press(tester,'remote-input-paste'); expect(focus.hasFocus,isTrue);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'A\nB',
      selection:TextSelection.collapsed(offset:3),composing:TextRange.empty)); await tester.pumpAndSettle();
    expect(find.text('预览发送文本'),findsOneWidget); expect(adapter.received,isEmpty);
    read.complete({'text':'old clipboard'}); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('remote-paste-append')),findsNothing);
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-input-review-text'))).data,'A[LF]\nB');
    expect(focus.hasFocus,isFalse); expect(adapter.received,isEmpty);
    await press(tester,'remote-input-confirm'); expect(adapter.received.map((bytes) => utf8.decode(bytes)),['A\nB']);
    expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('explicit mode change retires a pending read and its late result cannot disturb a newer paste review',(tester) async {
    final first = Completer<Object?>(); var reads = 0;
    mockClipboard((call) async {
      if (call.method != 'Clipboard.getData') return null;
      return ++reads == 1 ? first.future : {'text':'new clipboard'};
    });
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter); await input.mode(tester,'direct');
    await press(tester,'remote-input-paste'); await input.mode(tester,'observe'); await input.mode(tester,'direct');
    await press(tester,'remote-input-paste'); expect(reads,2);
    first.complete({'text':'old clipboard'}); await tester.pumpAndSettle();
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-paste-review-text'))).data,'new clipboard');
    await press(tester,'remote-paste-append');
    expect(tester.widget<TextField>(find.byKey(const ValueKey('remote-input-draft'))).controller!.text,'new clipboard');
    expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('ABA edit while paste review is open invalidates the local append',(tester) async {
    clipboardText('CLIP'); final adapter = input.InputFixtureAdapter(); final controller = await startDraft(tester,adapter,'original');
    await press(tester,'remote-input-draft-paste'); controller.text = 'changed'; controller.text = 'original'; await tester.pump();
    await press(tester,'remote-paste-append'); expect(controller.text,'original'); expect(adapter.received,isEmpty);
    // A new explicit review can use the current original draft.
    await press(tester,'remote-input-draft-paste'); await press(tester,'remote-paste-append');
    expect(controller.text,'originalCLIP'); expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('hidden tab invalidates an open paste review and cannot change its retained original draft',(tester) async {
    clipboardText('CLIP'); final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,visibility:visibility); await input.mode(tester,'draft');
    final field = find.byKey(const ValueKey('remote-input-draft')); await tester.ensureVisible(field); await tester.enterText(field,'original');
    final controller = tester.widget<TextField>(field).controller!; await press(tester,'remote-input-draft-paste');
    visibility.value = false; await tester.pump(); await press(tester,'remote-paste-replace');
    expect(controller.text,'original'); expect(adapter.received,isEmpty); expect(adapter.resumes,0);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('same-draft ABA edit invalidates send confirmation without submitting or clearing text',(tester) async {
    final adapter = input.InputFixtureAdapter(); final controller = await startDraft(tester,adapter,'reviewed');
    await press(tester,'remote-input-draft-send'); controller.text = 'changed'; controller.text = 'reviewed'; await tester.pump();
    await press(tester,'remote-input-confirm'); expect(controller.text,'reviewed'); expect(adapter.received,isEmpty);
    expect(find.textContaining('原草稿已变化'),findsOneWidget); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('clipboard error preserves the draft and permits an explicit later review',(tester) async {
    var fail = true;
    mockClipboard((call) async {
      if (call.method != 'Clipboard.getData') return null;
      if (fail) throw PlatformException(code:'clipboard_unavailable');
      return {'text':'CLIP'};
    });
    final adapter = input.InputFixtureAdapter(); final controller = await startDraft(tester,adapter,'original');
    await press(tester,'remote-input-draft-paste'); expect(controller.text,'original'); expect(find.textContaining('系统粘贴未确认'),findsOneWidget);
    fail = false; await press(tester,'remote-input-draft-paste'); await press(tester,'remote-paste-append');
    expect(controller.text,'originalCLIP'); expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });
}
