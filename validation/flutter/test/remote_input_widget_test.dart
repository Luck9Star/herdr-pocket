import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'remote_page_test.dart' as base;
import 'remote_input_test.dart' as fixtures show target;
import 'remote_test_data.dart';

class InputFixtureAdapter extends base.PendingAdapter {
  InputFixtureAdapter({this.supported = true});
  final bool supported;
  Object connection = Object();
  final received = <Uint8List>[];
  RemoteInputTarget? selectedTarget;
  @override Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    connection = Object();
    return super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
  }
  @override RemoteInputCapability? get inputCapability => supported ? const RemoteInputCapability(4096) : null;
  @override RemoteInputTarget? get inputTarget => selectedTarget;
  @override void selectPane(int expectedGeneration,String paneId) {
    super.selectPane(expectedGeneration,paneId);
    selectedTarget = fixtures.target(connection:connection,generation:expectedGeneration,pane:paneId,
      term:paneId == 'w1:p1' ? 'term_abcd' : 'term_1234');
  }
  @override Future<RemoteInputResult> sendInput(RemoteInputTarget target,Uint8List bytes,
      {bool Function()? stillCurrent}) async {
    if (stillCurrent?.call() != true || !identical(target,selectedTarget)) {
      return const RemoteInputResult.rejected('input_cancelled_before_write');
    }
    received.add(Uint8List.fromList(bytes)); return const RemoteInputResult.accepted();
  }
}

Future<void> start(WidgetTester tester,InputFixtureAdapter adapter,{double width=390,ValueListenable<bool>? visibility}) async {
  await base.prepare(tester,adapter,Size(width,844));
  if (visibility != null) {
    final page = tester.widget<RemotePage>(find.byType(RemotePage));
    await tester.pumpWidget(MaterialApp(theme:page.tokens.theme,
      home:RemotePage(tokens:page.tokens,adapter:adapter,visibility:visibility)));
  }
  await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
  await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
  adapter.publish(); await tester.pump();
  final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
  await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
  adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'SYNTHETIC INPUT FIXTURE'));
  await tester.pump();
}
Future<void> mode(WidgetTester tester,String value) async {
  final chip = find.byKey(ValueKey('remote-mode-$value'));
  await tester.ensureVisible(chip); await tester.tap(chip); await tester.pump(); await tester.pump();
}

void main() {
  testWidgets('stock server stays read-only after full and cannot be enabled by mode controls', (tester) async {
    final adapter = InputFixtureAdapter(supported:false); await start(tester,adapter);
    final chip = find.byKey(const ValueKey('remote-mode-direct'));
    await tester.ensureVisible(chip);
    expect(tester.widget<ChoiceChip>(chip).onSelected,isNull);
    expect(find.textContaining('原厂 herdr 0.9.5 保持只读'),findsOneWidget);
    expect(adapter.received,isEmpty);
  });
  testWidgets('real terminal component keeps composing local and sends committed Unicode once', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter); await mode(tester,'direct');
    expect(tester.testTextInput.isRegistered,isTrue);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',
      selection:TextSelection.collapsed(offset:2),composing:TextRange(start:0,end:2)));
    await tester.pump(); expect(adapter.received,isEmpty);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',
      selection:TextSelection.collapsed(offset:2),composing:TextRange.empty));
    await tester.pump(); expect(adapter.received.map((b) => b.toList()),[utf8.encode('中文')]);
    await mode(tester,'observe'); await tester.sendKeyEvent(LogicalKeyboardKey.keyX); await tester.pump();
    expect(adapter.received.length,1);
  });
  testWidgets('paste and draft use target-bound preview and preserve newline without adding Enter', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter); await mode(tester,'direct');
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform,(call) async =>
      call.method == 'Clipboard.getData' ? {'text':'A中文\nsecond'} : null);
    addTearDown(() { messenger.setMockMethodCallHandler(SystemChannels.platform,null); });
    final paste = find.byKey(const ValueKey('remote-input-paste'));
    await tester.ensureVisible(paste); await tester.tap(paste); await tester.pumpAndSettle();
    expect(adapter.received,isEmpty); expect(find.text('预览发送文本'),findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pumpAndSettle();
    expect(adapter.received.single,utf8.encode('A中文\nsecond'));
    await mode(tester,'draft'); final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'local draft'); await tester.pump();
    expect(adapter.received.length,1);
    final send = find.byKey(const ValueKey('remote-input-draft-send'));
    await tester.ensureVisible(send); await tester.tap(send); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pumpAndSettle();
    expect(adapter.received.last,utf8.encode('local draft'));
    expect(tester.widget<TextField>(draft).controller!.text,isEmpty);
  });
  testWidgets('disconnect while paste preview is open invalidates confirmation and never sends', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter); await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'keep unsent');
    final send = find.byKey(const ValueKey('remote-input-draft-send'));
    await tester.ensureVisible(send); await tester.tap(send); await tester.pumpAndSettle();
    adapter.pending.completeError(const RemoteFailure('observe_ended')); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pumpAndSettle();
    expect(adapter.received,isEmpty); expect(find.textContaining('旧画面'),findsWidgets);
    await mode(tester,'observe'); expect(adapter.received,isEmpty);
  });
  testWidgets('auxiliary buttons produce explicit bytes and rendering device-query replies are not writes', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter,width:320); await mode(tester,'direct');
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(1,false,'\x1b[6n'));
    await tester.pump(); expect(adapter.received,isEmpty);
    final key = find.byKey(const ValueKey('remote-key-Ctrl+C'));
    await tester.ensureVisible(key); await tester.tap(key); await tester.pump();
    expect(adapter.received.single,[3]);
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    expect(adapter.received.last,[13]); expect(tester.takeException(),isNull);
  });
  testWidgets('hidden tab stops input and late frames; explicit reconnect restores only its unsent draft', (tester) async {
    final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = InputFixtureAdapter(); await start(tester,adapter,visibility:visibility);
    await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'tab-owned unsent draft');
    final oldGeneration = adapter.generation;
    visibility.value = false; await tester.pump();
    expect(adapter.cancels,greaterThan(0)); expect(adapter.received,isEmpty);
    adapter.frame!(oldGeneration,'w1:p1',const RemoteFrame(1,false,'LATE HIDDEN FRAME'));
    visibility.value = true; await tester.pump();
    expect(adapter.calls,1); expect(find.textContaining('请主动审查连接并取得新 full'),findsOneWidget);
    await tester.ensureVisible(base.field('privateKeyPem'));
    await tester.enterText(base.field('privateKeyPem'),fixtureConfig()['privateKeyPem'] as String);
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    adapter.publish(); await tester.pump();
    final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW FULL AFTER TAB RESTORE'));
    await tester.pump(); expect(adapter.calls,2);
    await mode(tester,'draft');
    expect(tester.widget<TextField>(draft).controller!.text,'tab-owned unsent draft');
    expect(adapter.received,isEmpty);
  });
}
