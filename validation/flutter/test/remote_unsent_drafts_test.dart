import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'remote_page_test.dart' as base;
import 'remote_input_widget_test.dart' as input;
import 'remote_input_test.dart' as fixtures show target;
import 'remote_dashboard_time_test.dart' show IndependentObserveAttempts,reviewManualReconnect;

class _ReconnectInputAdapter extends input.InputFixtureAdapter with IndependentObserveAttempts {
  @override Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    connection=Object(); return super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
  }
  @override Future<void> cancel() {
    selectedTarget=null; pausedTarget=null; paused=false; return super.cancel();
  }
}

Future<TextEditingController> writeDraft(WidgetTester tester,String value) async {
  await input.mode(tester,'draft');
  final field = find.byKey(const ValueKey('remote-input-draft'));
  await tester.ensureVisible(field); await tester.enterText(field,value); await tester.pump();
  return tester.widget<TextField>(field).controller!;
}
Future<void> tapShelf(WidgetTester tester,String name) async {
  final control = find.byKey(ValueKey(name));
  await tester.ensureVisible(control); await tester.tap(control); await tester.pumpAndSettle();
}
void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('observation at ${width}px can copy unsent original draft and clear only after confirmation',(tester) async {
      final copied = <String>[];
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
        if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
        return null;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(SystemChannels.platform,null));
      final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter,width:width);
      final controller = await writeDraft(tester,'原目标未发送\n第二行'); await input.mode(tester,'observe');
      expect(find.byKey(const ValueKey('remote-input-draft')),findsNothing);
      expect(find.textContaining('来源：本页按原目标保留'),findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const ValueKey('remote-unsent-origin-0'))).data,contains('term_abcd'));
      await tapShelf(tester,'remote-unsent-copy-0');
      expect(copied,['原目标未发送\n第二行']); expect(controller.text,'原目标未发送\n第二行'); expect(adapter.received,isEmpty);
      await tapShelf(tester,'remote-unsent-clear-0');
      await tester.tap(find.text('保留草稿')); await tester.pumpAndSettle(); expect(controller.text,'原目标未发送\n第二行');
      await tapShelf(tester,'remote-unsent-clear-0');
      await tester.tap(find.byKey(const ValueKey('remote-unsent-clear-confirm'))); await tester.pumpAndSettle();
      expect(controller.text,isEmpty); expect(find.byKey(const ValueKey('remote-unsent-shelf')),findsNothing);
      expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  for (final failure in ['observe_ended','resume_target_changed']) {
    testWidgets('$failure keeps original unsent draft readable without reopening input',(tester) async {
      final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter);
      await writeDraft(tester,'keep original draft');
      adapter.pending.completeError(RemoteFailure(failure)); await tester.pump(); await tester.pump();
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'keep original draft');
      expect(tester.widget<Text>(find.byKey(const ValueKey('remote-unsent-origin-0'))).data,contains('w1:p1 / term_abcd'));
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
      expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('same pane with a new terminal never inherits the original draft; clearing original preserves new editor',(tester) async {
    final copied = <String>[];
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
      if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
      return null;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(SystemChannels.platform,null));
    final adapter = _ReconnectInputAdapter(); await input.start(tester,adapter); await writeDraft(tester,'ORIGINAL ONLY');
    await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
    await reviewManualReconnect(tester,adapter);
    adapter.dashboard!(RemoteDashboard(adapter.generation,'probe',const [RemotePane('w1:p1','term_9876')],freshness:DashboardFreshness.fresh)); await tester.pump();
    final pane = find.byKey(const ValueKey('remote-pane-w1:p1')); await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    adapter.selectedTarget = fixtures.target(connection:adapter.connection,generation:adapter.generation,pane:'w1:p1',term:'term_9876');
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'REPLACEMENT TERMINAL')); await tester.pump();
    await input.mode(tester,'draft');
    final editor = tester.widget<TextField>(find.byKey(const ValueKey('remote-input-draft'))).controller!;
    expect(editor.text,isEmpty);
    await tester.ensureVisible(find.byKey(const ValueKey('remote-input-draft')));
    await tester.enterText(find.byKey(const ValueKey('remote-input-draft')),'NEW TERMINAL DRAFT'); await tester.pump();
    expect(tester.widget<Text>(find.byKey(const ValueKey('remote-unsent-origin-0'))).data,contains('term_abcd'));
    await tapShelf(tester,'remote-unsent-copy-0'); expect(copied,['ORIGINAL ONLY']);
    await tapShelf(tester,'remote-unsent-clear-0');
    expect(find.text('清除此原目标的未发送草稿？'),findsOneWidget);
    // Editing B after reviewing A must neither invalidate A's confirmation nor
    // let A's confirmation clear the controller now owned by B.
    editor.text = 'NEW TERMINAL EDITED DURING REVIEW'; await tester.pump();
    await tester.tap(find.byKey(const ValueKey('remote-unsent-clear-confirm'))); await tester.pumpAndSettle();
    expect(editor.text,'NEW TERMINAL EDITED DURING REVIEW');
    expect(find.byKey(const ValueKey('remote-unsent-shelf')),findsNothing);
    expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('stale clear confirmation cannot remove a newly edited draft for the same endpoint',(tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter);
    final controller = await writeDraft(tester,'reviewed text'); await input.mode(tester,'observe');
    await tapShelf(tester,'remote-unsent-clear-0');
    controller.text = 'new text after review';
    await tester.tap(find.byKey(const ValueKey('remote-unsent-clear-confirm'))); await tester.pumpAndSettle();
    expect(controller.text,'new text after review'); await input.mode(tester,'observe');
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'new text after review');
    expect(adapter.received,isEmpty); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('same-target ABA editing invalidates an open clear confirmation even when visible text returns',(tester) async {
    final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter);
    final controller = await writeDraft(tester,'reviewed text'); await input.mode(tester,'observe');
    await tapShelf(tester,'remote-unsent-clear-0');
    controller.text = 'different text'; controller.text = 'reviewed text'; await tester.pump();
    await tester.tap(find.byKey(const ValueKey('remote-unsent-clear-confirm'))); await tester.pumpAndSettle();
    expect(controller.text,'reviewed text');
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'reviewed text');
    // A new explicit click reviews the current version and can clear it.
    await tapShelf(tester,'remote-unsent-clear-0');
    await tester.tap(find.byKey(const ValueKey('remote-unsent-clear-confirm'))); await tester.pumpAndSettle();
    expect(controller.text,isEmpty); expect(find.byKey(const ValueKey('remote-unsent-shelf')),findsNothing);
    expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
  });
  for (final action in ['copy','clear']) {
    testWidgets('a $action click cannot act on text that changed since the visible shelf was built',(tester) async {
      final copied = <String>[];
      final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(SystemChannels.platform,(call) async {
        if (call.method == 'Clipboard.setData') copied.add((call.arguments as Map)['text'] as String);
        return null;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(SystemChannels.platform,null));
      final adapter = input.InputFixtureAdapter(); await input.start(tester,adapter);
      final controller = await writeDraft(tester,'visible old text'); await input.mode(tester,'observe');
      final control = find.byKey(ValueKey('remote-unsent-$action-0'));
      await tester.ensureVisible(control); await tester.pumpAndSettle();
      // No frame between the edit and the real click: the old displayed value
      // cannot be combined with the new entry's token to authorize an action.
      controller.text = 'new text awaiting a frame';
      await tester.tap(control); await tester.pumpAndSettle();
      expect(copied,isEmpty); expect(find.byKey(const ValueKey('remote-unsent-clear-confirm')),findsNothing);
      expect(controller.text,'new text awaiting a frame');
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'new text awaiting a frame');
      expect(adapter.received,isEmpty); expect(tester.takeException(),isNull); await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('unknown submitted bytes remain in recovery record and never become an unsent draft',(tester) async {
    final adapter = input.InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await input.start(tester,adapter); final controller = await writeDraft(tester,'SUBMITTED UNKNOWN');
    final send = find.byKey(const ValueKey('remote-input-draft-send')); await tester.ensureVisible(send); await tester.tap(send); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pumpAndSettle();
    expect(controller.text,isEmpty); expect(adapter.received.length,1);
    expect(find.byKey(const ValueKey('remote-unsent-shelf')),findsNothing);
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    expect(find.byKey(const ValueKey('remote-input-acknowledge')),findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
