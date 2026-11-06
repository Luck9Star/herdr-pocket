import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
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
  RemoteInputResult nextResult = const RemoteInputResult.accepted();
  Completer<RemoteInputResult>? delayedResult;
  Completer<bool>? delayedAcknowledgement;
  int acknowledgements = 0;
  final pendingRecords = <String,RemoteInputPending>{};
  final reviewedRecords = <String>[];
  int journalRevision = 0;
  RemoteInputJournalReadTicket? beginJournalFull({int observationEpoch=0}) {
    final current = selectedTarget;
    if (current == null) return null;
    final review = captureInputJournalReview?.call(current);
    final revision = ++journalRevision;
    return review == null ? null : RemoteInputJournalReadTicket(review,current,observationEpoch,revision);
  }
  @override bool isInputJournalReadCurrent(RemoteInputJournalReadTicket ticket) =>
    !paused && identical(selectedTarget,ticket.target) && ticket.revision == journalRevision &&
    pendingRecords[ticket.target.endpointKey] == null;
  @override RemoteInputPending? get pendingInput => selectedTarget == null ? null : pendingRecords[selectedTarget!.endpointKey];
  RemoteInputTarget? selectedTarget;
  RemoteInputTarget? pausedTarget;
  int pauses = 0,resumes = 0;
  bool paused = false;
  @override Future<RemoteSnapshot> observe(RemoteConfig config,{required DashboardConsumer onDashboard,
      required FrameConsumer onFrame,RemoteProgress? onProgress}) {
    connection = Object();
    return super.observe(config,onDashboard:onDashboard,onFrame:onFrame,onProgress:onProgress);
  }
  @override RemoteInputCapability? get inputCapability => supported ? const RemoteInputCapability(4096) : null;
  @override RemoteInputTarget? get inputTarget => selectedTarget;
  @override bool pauseObservation() {
    if (calls == 0) return false;
    if (!paused) { pauses++; paused = true; pausedTarget = selectedTarget; selectedTarget = null; }
    return true;
  }
  @override bool resumeObservation() {
    if (!paused) return false;
    paused = false; resumes++;
    final old = pausedTarget;
    if (old != null) selectedTarget = fixtures.target(connection:connection,generation:old.generation,pane:old.paneId,term:old.terminalId);
    return true;
  }
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
    received.add(Uint8List.fromList(bytes));
    final result = delayedResult == null ? nextResult : await delayedResult!.future;
    if (result.disposition == RemoteInputDisposition.unknown || result.requiresJournalRecovery) {
      final pending = RemoteInputPending.create(received.length.toRadixString(16).padLeft(32,'0'),target);
      pendingRecords[target.endpointKey] = pending;
      return result.withPending(pending);
    }
    return result;
  }
  @override Future<bool> acknowledgeInputUnknown(RemoteInputTarget target,{required String reviewedRecord}) async {
    acknowledgements++; reviewedRecords.add(reviewedRecord);
    if (!identical(target,selectedTarget) || pendingRecords[target.endpointKey]?.raw != reviewedRecord) return false;
    final allowed = delayedAcknowledgement == null ? true : await delayedAcknowledgement!.future;
    if (!allowed || pendingRecords[target.endpointKey]?.raw != reviewedRecord) return false;
    pendingRecords.remove(target.endpointKey); return true;
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
  for (final disposition in [RemoteInputDisposition.accepted,RemoteInputDisposition.rejected]) {
    testWidgets('MT10 late $disposition receipt cannot modify a new epoch draft or status', (tester) async {
      final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
      final adapter = InputFixtureAdapter()..delayedResult = Completer<RemoteInputResult>();
      await start(tester,adapter,visibility:visibility); await mode(tester,'draft');
      final draft = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(draft); await tester.enterText(draft,'same text'); await tester.pump();
      final controller = tester.widget<TextField>(draft).controller!;
      final send = find.byKey(const ValueKey('remote-input-draft-send'));
      await tester.ensureVisible(send); await tester.tap(send); await tester.pump();
      await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pump();
      expect(controller.text,isEmpty); expect(adapter.received.length,1);
      visibility.value = false; await tester.pump(); visibility.value = true; await tester.pump();
      final resume = find.byKey(const ValueKey('remote-resume'));
      await tester.ensureVisible(resume); await tester.tap(resume); await tester.pump();
      adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW EPOCH',observationEpoch:1)); await tester.pump();
      await mode(tester,'draft'); controller.text = 'same text'; await tester.pump();
      adapter.delayedResult!.complete(disposition == RemoteInputDisposition.accepted
        ? const RemoteInputResult.accepted() : const RemoteInputResult.rejected('pocket_input_rejected'));
      await tester.pump(); await tester.pump();
      expect(controller.text,'same text'); expect(adapter.received.length,1);
      expect(find.textContaining('已明确拒绝'),findsNothing);
      if (disposition == RemoteInputDisposition.rejected) expect(find.byKey(const ValueKey('remote-rejected-draft-0')),findsOneWidget);
    });
  }
  testWidgets('MT10 a stale mode callback cannot enable input in a new observation epoch', (tester) async {
    final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = InputFixtureAdapter(); await start(tester,adapter,visibility:visibility);
    final old = tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected!;
    visibility.value = false; await tester.pump(); visibility.value = true; await tester.pump();
    final resume = find.byKey(const ValueKey('remote-resume'));
    await tester.ensureVisible(resume); await tester.tap(resume); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'FRESH',observationEpoch:1)); await tester.pump();
    old(true); await tester.pump();
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    expect(adapter.received,isEmpty);
  });
  testWidgets('MT10 late unknown acknowledgement cannot unlock a later observation epoch', (tester) async {
    final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await start(tester,adapter,visibility:visibility); await mode(tester,'direct');
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
    await tester.ensureVisible(base.field('privateKeyPem'));
    await tester.enterText(base.field('privateKeyPem'),fixtureConfig()['privateKeyPem'] as String);
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    adapter.publish(); await tester.pump();
    final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'RECONNECTED')); await tester.pump();
    final acknowledge = find.byKey(const ValueKey('remote-input-acknowledge'));
    expect(tester.widget<TextButton>(acknowledge).onPressed,isNotNull);
    adapter.delayedAcknowledgement = Completer<bool>();
    await tester.ensureVisible(acknowledge); await tester.tap(acknowledge); await tester.pump();
    visibility.value = false; await tester.pump(); visibility.value = true; await tester.pump();
    final resume = find.byKey(const ValueKey('remote-resume'));
    await tester.ensureVisible(resume); await tester.tap(resume); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'LATER EPOCH',observationEpoch:1)); await tester.pump();
    adapter.delayedAcknowledgement!.complete(true); await tester.pump();
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    expect(adapter.received.length,1); expect(adapter.acknowledgements,1);
  });
  testWidgets('a new full coordinates an exact marker resolved by another adapter; delta and old read cannot unlock it', (tester) async {
    final adapter = InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await start(tester,adapter); await mode(tester,'direct');
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    final old = adapter.beginJournalFull()!;
    final current = adapter.beginJournalFull()!;
    adapter.pendingRecords.remove(adapter.inputTarget!.endpointKey); // Explicit resolution in the other adapter fixture.
    adapter.frame!(adapter.generation,'w1:p1',RemoteFrame(1,false,'DELTA',inputJournalRead:current)); await tester.pump();
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    adapter.frame!(adapter.generation,'w1:p1',RemoteFrame(2,true,'STALE READ',inputJournalRead:old)); await tester.pump();
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    adapter.frame!(adapter.generation,'w1:p1',RemoteFrame(3,true,'AUTHORITATIVE FULL',inputJournalRead:current)); await tester.pump();
    expect(find.textContaining('发送结果待核实'),findsNothing);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNotNull);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    expect(adapter.received.length,1); await tester.pumpWidget(const SizedBox());
  });
  testWidgets('known receipt survives authoritative full coordination and does not remain an unknown lock', (tester) async {
    final receipt = RemoteInputReceipt('1'.padLeft(32,'0'),'w1:p1','term_abcd',1);
    final adapter = InputFixtureAdapter()..nextResult = RemoteInputResult.journalLocked(RemoteInputDisposition.accepted,receipt:receipt);
    await start(tester,adapter); await mode(tester,'direct');
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    final read = adapter.beginJournalFull()!; adapter.pendingRecords.remove(adapter.inputTarget!.endpointKey);
    adapter.frame!(adapter.generation,'w1:p1',RemoteFrame(1,true,'KNOWN FULL',inputJournalRead:read)); await tester.pump();
    expect(find.byKey(const ValueKey('remote-input-acknowledge')),findsNothing);
    expect(find.text(receipt.label),findsOneWidget); expect(adapter.received.length,1);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('IJ03 human resolution keeps the clicked original raw when a new pending record arrives', (tester) async {
    final adapter = InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await start(tester,adapter); await mode(tester,'direct');
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
    await tester.ensureVisible(base.field('privateKeyPem'));
    await tester.enterText(base.field('privateKeyPem'),fixtureConfig()['privateKeyPem'] as String);
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    adapter.publish(); await tester.pump();
    final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW CONNECTION')); await tester.pump();
    final oldRaw = adapter.pendingInput!.raw;
    adapter.delayedAcknowledgement = Completer<bool>();
    final acknowledge = find.byKey(const ValueKey('remote-input-acknowledge'));
    await tester.ensureVisible(acknowledge); await tester.tap(acknowledge); await tester.pump();
    expect(adapter.reviewedRecords,[oldRaw]);
    final replacement = RemoteInputPending.create('f'*32,adapter.inputTarget!);
    adapter.pendingRecords[adapter.inputTarget!.endpointKey] = replacement;
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(1,true,'NEW PENDING RECORD')); await tester.pump();
    adapter.delayedAcknowledgement!.complete(true); await tester.pump();
    expect(adapter.reviewedRecords,[oldRaw]); expect(adapter.pendingInput!.raw,replacement.raw);
    expect(find.textContaining('发送结果待核实'),findsOneWidget); expect(adapter.received.length,1);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('Ctrl and Alt hold only explicit auxiliary input, then release; cancel and focus loss send nothing', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter); await mode(tester,'direct');
    Future<void> press(String name) async {
      final button = find.byKey(ValueKey(name)); await tester.ensureVisible(button);
      await tester.tap(button); await tester.pump(); await tester.pump();
    }
    await press('remote-modifier-ctrl'); await press('remote-modifier-alt');
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isTrue);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).selected,isTrue);
    expect(adapter.received,isEmpty);
    await press('remote-base-c');
    expect(adapter.received.single,[27,3]);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).selected,isFalse);
    await press('remote-modifier-ctrl'); await press('remote-modifier-cancel');
    expect(adapter.received.length,1);
    await press('remote-modifier-alt');
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',
      selection:TextSelection.collapsed(offset:2),composing:TextRange(start:0,end:2)));
    await tester.pump(); expect(adapter.received.length,1);
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'中文',
      selection:TextSelection.collapsed(offset:2),composing:TextRange.empty));
    await tester.pump(); expect(adapter.received.last,utf8.encode('中文'));
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-alt'))).selected,isFalse);
    await press('remote-modifier-ctrl');
    tester.widget<TerminalView>(find.byType(TerminalView)).focusNode!.unfocus(); await tester.pump();
    await mode(tester,'direct');
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).selected,isFalse);
    expect(adapter.received.length,2);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(1,false,'\x1b[?1h'));
    await tester.pump(); await press('remote-key-↑');
    expect(adapter.received.last,[27,79,65]);
    await mode(tester,'draft');
    expect(tester.widget<FilterChip>(find.byKey(const ValueKey('remote-modifier-ctrl'))).onSelected,isNull);
    expect(tester.takeException(),isNull);
  });
  testWidgets('direct focus loss revokes mode and refocusing cannot send until explicit selection', (tester) async {
    final adapter = InputFixtureAdapter(); await start(tester,adapter); await mode(tester,'direct');
    final focus = tester.widget<TerminalView>(find.byType(TerminalView)).focusNode!;
    expect(focus.hasFocus,isTrue); focus.unfocus(); await tester.pump();
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    focus.requestFocus(); await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.keyX,character:'x'); await tester.pump();
    expect(adapter.received,isEmpty);
    await mode(tester,'direct');
    tester.testTextInput.updateEditingValue(const TextEditingValue(text:'k',
      selection:TextSelection.collapsed(offset:1),composing:TextRange.empty));
    await tester.pump(); expect(adapter.received.map((bytes) => utf8.decode(bytes)),['k']);
  });
  testWidgets('unknown draft is quarantined; only manual same-target new full recovery unlocks without replay', (tester) async {
    final adapter = InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await start(tester,adapter); await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'Pocket测');
    final send = find.byKey(const ValueKey('remote-input-draft-send'));
    await tester.ensureVisible(send); await tester.tap(send); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('remote-input-confirm'))); await tester.pumpAndSettle();
    expect(adapter.received.map((bytes) => utf8.decode(bytes)),['Pocket测']);
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    final acknowledge = find.byKey(const ValueKey('remote-input-acknowledge'));
    expect(tester.widget<TextButton>(acknowledge).onPressed,isNull);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
    await tester.ensureVisible(base.field('cancel')); await tester.tap(base.field('cancel')); await tester.pump();
    await tester.ensureVisible(base.field('privateKeyPem'));
    await tester.enterText(base.field('privateKeyPem'),fixtureConfig()['privateKeyPem'] as String);
    await tester.ensureVisible(base.field('review')); await tester.tap(base.field('review')); await tester.pump();
    await tester.ensureVisible(base.field('connect')); await tester.tap(base.field('connect')); await tester.pump();
    adapter.publish(); await tester.pump();
    final pane = find.byKey(const ValueKey('remote-pane-w1:p1'));
    await tester.ensureVisible(pane); await tester.tap(pane); await tester.pump();
    expect(tester.widget<TextButton>(acknowledge).onPressed,isNull);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW VERIFIED FULL'));
    await tester.pump();
    expect(tester.widget<TextButton>(acknowledge).onPressed,isNotNull);
    expect(adapter.received.length,1); expect(adapter.acknowledgements,0);
    await tester.ensureVisible(acknowledge); await tester.tap(acknowledge); await tester.pumpAndSettle();
    expect(adapter.acknowledgements,1); expect(adapter.received.length,1);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    await mode(tester,'draft'); expect(tester.widget<TextField>(draft).controller!.text,isEmpty);
    expect(adapter.received.length,1);
  });
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
  testWidgets('MT03 MT09 hidden tab stops input, retains connection and requires explicit resume plus full', (tester) async {
    final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = InputFixtureAdapter(); await start(tester,adapter,visibility:visibility);
    await mode(tester,'draft');
    final draft = find.byKey(const ValueKey('remote-input-draft'));
    await tester.ensureVisible(draft); await tester.enterText(draft,'tab-owned unsent draft');
    final oldGeneration = adapter.generation;
    visibility.value = false; await tester.pump();
    expect(adapter.pauses,1); expect(adapter.cancels,0); expect(adapter.received,isEmpty);
    adapter.frame!(oldGeneration,'w1:p1',const RemoteFrame(1,false,'LATE HIDDEN FRAME'));
    visibility.value = true; await tester.pump();
    expect(adapter.calls,1); expect(find.textContaining('请主动恢复原目标并等待新 full'),findsOneWidget);
    final resume = find.byKey(const ValueKey('remote-resume'));
    await tester.ensureVisible(resume); await tester.tap(resume); await tester.pump();
    expect(adapter.resumes,1); expect(adapter.received,isEmpty);
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'NEW FULL AFTER TAB RESTORE',observationEpoch:1));
    await tester.pump(); expect(adapter.calls,1);
    await mode(tester,'draft');
    expect(tester.widget<TextField>(draft).controller!.text,'tab-owned unsent draft');
    expect(adapter.received,isEmpty);
  });
  testWidgets('MT08 unknown submitted input remains locked after same-SSH resume and is never resent', (tester) async {
    final visibility = ValueNotifier(true); addTearDown(visibility.dispose);
    final adapter = InputFixtureAdapter()..nextResult = const RemoteInputResult.unknown();
    await start(tester,adapter,visibility:visibility); await mode(tester,'direct');
    final enter = find.byKey(const ValueKey('remote-key-Enter'));
    await tester.ensureVisible(enter); await tester.tap(enter); await tester.pump();
    expect(adapter.received.length,1); expect(find.textContaining('发送结果待核实'),findsOneWidget);
    visibility.value = false; await tester.pump(); visibility.value = true; await tester.pump();
    final resume = find.byKey(const ValueKey('remote-resume'));
    await tester.ensureVisible(resume); await tester.tap(resume); await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,'AFTER UNKNOWN',observationEpoch:1)); await tester.pump();
    expect(find.textContaining('发送结果待核实'),findsOneWidget);
    expect(tester.widget<TextButton>(find.byKey(const ValueKey('remote-input-acknowledge'))).onPressed,isNull);
    expect(adapter.received.length,1); expect(adapter.acknowledgements,0);
  });
}
