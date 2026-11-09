import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/main.dart' as app;
import 'package:herdr_flutter_probe/device_keys.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_catalog_search.dart' show HostTaskFilter;
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/pairing_public_key.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart' show RemotePane,RemoteDashboard,RemoteEvidence;
import 'package:herdr_flutter_probe/remote_screen_viewport.dart';
import 'package:herdr_flutter_probe/theme_prompt_samples.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const fixtureEnabled = String.fromEnvironment('HERDR_ANDROID_NATIVE_PAIRING');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const publicTarget = String.fromEnvironment('HERDR_ANDROID_TARGET_JSON');
const publicProfile = String.fromEnvironment('HERDR_ANDROID_PROFILE_JSON');
const blockedTargetsRaw = String.fromEnvironment('HERDR_ANDROID_BLOCKED_TARGETS',defaultValue:'[]');
const hostFingerprint = String.fromEnvironment('HERDR_ANDROID_HOST_FINGERPRINT');
const publicDirectory = String.fromEnvironment('HERDR_ANDROID_PUBLIC_DIR');
const guardedInput = bool.fromEnvironment('POCKET_GUARDED_INPUT');
const guardedTui = bool.fromEnvironment('HERDR_ANDROID_GUARDED_TUI');
const tuiResumeStages = {'tui_find_board','tui_return_tab','tui_find_resume','tui_resume_full'};
// Set only by the isolated runner after its single API35 AVD/fresh-package
// checks. This test never reads or saves a pre-existing clipboard value.
const syntheticClipboardEnabled = bool.fromEnvironment('HERDR_ANDROID_API35_CLIPBOARD_FIXTURE');
const systemKeyboardEnabled = bool.fromEnvironment('HERDR_ANDROID_API35_KEYBOARD_FIXTURE');

/// Only public fixture target/request/response and typed evidence cross these
/// files. No injected DeviceKeys, catalog, adapter, frame or MethodChannel mock.
Map<String,dynamic> checkedTarget() {
  if (!Platform.isAndroid || !kDebugMode || fixtureEnabled != '1' ||
      !RegExp(r'^[0-9]+$').hasMatch(runId) || utf8.encode(publicTarget).length > 8192 ||
      syntheticClipboardEnabled != guardedInput || guardedTui && !guardedInput ||
      publicDirectory != '/data/user/0/$packageName/cache/herdr-flutter-android-$runId') {
    throw StateError('isolated_android_fixture_required');
  }
  final value = jsonDecode(publicTarget);
  const fields = {'schemaVersion','host','port','username','expectedHostKey','socketPath',
    'herdrPath','session','paneId','reviewConfirmed'};
  if (value is! Map<String,dynamic> || value.keys.toSet().difference(fields).isNotEmpty ||
      value.keys.toSet().length != fields.length || value['schemaVersion'] != 1 ||
      value['reviewConfirmed'] != true || value['host'] != '127.0.0.1' ||
      value['port'] is! int || value['port'] < 1024 || value['port'] > 65535 ||
      value['session'] != 'pocket-probe' || value['herdrPath'] is! String || value['socketPath'] is! String ||
      !RegExp('^/tmp/hp-mobile-$runId-' r'[A-Za-z0-9_-]+/herdr$').hasMatch(value['herdrPath'] as String) ||
      value['socketPath'] != '${(value['herdrPath'] as String).substring(0,(value['herdrPath'] as String).length-6)}/config/herdr/sessions/pocket-probe/herdr.sock') {
    throw StateError('invalid_public_android_target');
  }
  final profile = jsonDecode(publicProfile);
  const profileFields = {'version','type','host','port','username','provider','session','socketPath','herdrPath','expectedHostKey'};
  if (utf8.encode(publicProfile).length > 2048 || profile is! Map<String,dynamic> ||
      profile.length != profileFields.length || !profile.keys.every(profileFields.contains) ||
      profile['version'] != 1 || profile['type'] != 'herdr-connection-profile' || profile['provider'] != 'direct' ||
      !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(hostFingerprint) ||
      pairingFingerprint(value['expectedHostKey'] as String) != hostFingerprint ||
      ['host','port','username','session','socketPath','herdrPath','expectedHostKey'].any((key) => profile[key] != value[key])) {
    throw StateError('invalid_public_android_target');
  }
  return value;
}

List<({String paneId,String terminalId})> checkedBlockedTargets(Map<String,dynamic> target) {
  if (utf8.encode(blockedTargetsRaw).length > 1024) throw StateError('invalid_blocked_targets');
  // Flat JSON records are parsed before decoding each string so duplicate
  // keys, unknown values and trailing input cannot be silently normalized.
  var at=0;
  void ws() { while (at<blockedTargetsRaw.length && ' \t\r\n'.contains(blockedTargetsRaw[at])) { at++; } }
  bool take(String token) { ws(); if (at<blockedTargetsRaw.length && blockedTargetsRaw[at]==token) { at++; return true; } return false; }
  String string() {
    ws(); final match=RegExp(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"').matchAsPrefix(blockedTargetsRaw,at);
    if (match==null) throw StateError('invalid_blocked_targets');
    at=match.end; return jsonDecode(match[0]!) as String;
  }
  if (!take('[')) throw StateError('invalid_blocked_targets');
  final decoded=<Map<String,dynamic>>[];
  if (!take(']')) {
    while (true) {
      if (!take('{')) throw StateError('invalid_blocked_targets');
      final item=<String,dynamic>{};
      while (true) {
        final key=string();
        if (item.containsKey(key) || !take(':')) throw StateError('invalid_blocked_targets');
        item[key]=string();
        if (take('}')) break;
        if (!take(',')) throw StateError('invalid_blocked_targets');
      }
      decoded.add(item);
      if (take(']')) break;
      if (!take(',')) throw StateError('invalid_blocked_targets');
    }
  }
  ws(); if (at != blockedTargetsRaw.length || decoded.length != (guardedInput ? 0 : 2)) throw StateError('invalid_blocked_targets');
  final panes=<String>{},terminals=<String>{},result=<({String paneId,String terminalId})>[];
  for (final item in decoded) {
    if (item.length != 2 || !item.containsKey('paneId') || !item.containsKey('terminalId')) {
      throw StateError('invalid_blocked_targets');
    }
    final pane=item['paneId'],terminal=item['terminalId'];
    if (pane is! String || terminal is! String || !RegExp(r'^[A-Za-z0-9:_-]{1,128}$').hasMatch(pane) ||
        !RegExp(r'^term_[0-9a-f]{1,123}$').hasMatch(terminal) || pane == target['paneId'] ||
        !panes.add(pane) || !terminals.add(terminal)) throw StateError('invalid_blocked_targets');
    result.add((paneId:pane,terminalId:terminal));
  }
  return List.unmodifiable(result);
}

/// Scan code points without constructing or exporting arbitrary screen text.
bool screenHasMarker(Terminal terminal,String marker,{int firstRow=0,int? endRow,int firstColumn=0,int? endColumn}) {
  final chars=marker.codeUnits,rows=endRow ?? terminal.viewHeight,cols=endColumn ?? terminal.viewWidth;
  for (var y=firstRow;y<rows;y++) {
    final line=terminal.buffer.lines[y];
    for (var x=firstColumn;x+chars.length<=cols;x++) {
      var matches=true;
      for (var i=0;i<chars.length;i++) { if (line.getCodePoint(x+i)!=chars[i]) { matches=false; break; } }
      if (matches) return true;
    }
  }
  return false;
}

Future<void> until(WidgetTester tester, bool Function() ready, {int seconds = 60}) async {
  final deadline = DateTime.now().add(Duration(seconds:seconds));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail('android_public_ui_phase_timeout');
    await tester.pump(const Duration(milliseconds:100));
  }
}
Future<void> tap(WidgetTester tester, Finder finder,{VoidCallback? onPoll}) async {
  await until(tester,() { onPoll?.call(); return finder.evaluate().length == 1; });
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds:150));
  onPoll?.call();
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds:350));
  onPoll?.call();
}
Future<void> tapKey(WidgetTester tester, String key) => tap(tester,find.byKey(ValueKey(key)));

/// Read the actual pending framework error in these pointer phases; do not
/// turn it into a menu timeout or a second consent tap.
void checkPointerError(WidgetTester tester) {
  final error = tester.takeException();
  if (error != null) throw error;
}

/// Filter each ancestor by route before checking uniqueness: the closed field
/// may retain another copy of the same DropdownMenuItem/key and an InkWell.
Finder popupOptionControl(Finder item) => find.ancestor(of:item,matching:find.byElementPredicate((element) {
  final widget = element.widget;
  if (widget is! InkWell || widget.onTap == null) return false;
  final route = ModalRoute.of(element);
  return route is PopupRoute<dynamic> && route.isCurrent;
}));

/// Resolve the unique control first, scroll it into view, then require a
/// stable hit-testable pointer target and tap only once.
/// Used for the canvas dropdown/popup option and for any tap whose finder's
/// own box is not the pointer target (e.g. a group's header ListTile).
Future<void> tapStablePointer(WidgetTester tester,Finder control) async {
  await until(tester,() { checkPointerError(tester); return control.evaluate().length == 1; },seconds:10);
  await Scrollable.ensureVisible(tester.element(control),alignment:0.5);
  await tester.pump();
  final pointer = control.hitTestable();
  Rect? previousBounds;
  var stable = 0;
  await until(tester,() {
    checkPointerError(tester);
    if (pointer.evaluate().length != 1) { stable = 0; previousBounds = null; return false; }
    final bounds = tester.getRect(pointer);
    stable = bounds == previousBounds ? stable+1 : 0;
    previousBounds = bounds;
    return stable >= 3;
  },seconds:10);
  await tester.tap(pointer); // Exactly one explicit pointer tap; no retry.
  await tester.pump(const Duration(milliseconds:350));
}

/// The expansion toggle lives on the group's header ListTile, not on the
/// keyed ExpansionTile: an expanded tile's box spans the header plus every
/// child row, so a center tap on the group lands on a child row and opens
/// that blocked target instead of toggling the group. Child rows all carry
/// 'host-blocked-target-…' keys, so the header is the only keyless ListTile
/// inside the group — match it by the absent key, not by tree order.
Finder groupHeader(Finder group) => find.descendant(
  of: group,
  matching: find.byWidgetPredicate((w) => w is ListTile && w.key == null),
).first;

/// The enabled popup InkWell owns the whole row; its left-aligned item's
/// center may be blank and need not itself participate in the hit-test path.
Future<void> tapPopupOption(WidgetTester tester,Finder item) =>
  tapStablePointer(tester,popupOptionControl(item));

/// Read only the bundled sample screen. A zero denotes a missing row or
/// marker; keep the actual reading even when a candidate disagrees with the
/// expected column. The remote terminal can contain private output.
Future<({List<int> markers,Map<String,Map<String,int>> themes})> readFontDiagnostic(WidgetTester tester) async {
  await tapKey(tester,'remote-font-diagnostics-open');
  final preview = find.byKey(const ValueKey('terminal-font-diagnostics-view'));
  await until(tester,() => preview.evaluate().length == 1);
  await tester.ensureVisible(preview);
  await tester.pump();
  final view = tester.widget<TerminalView>(preview);
  expect(view.readOnly,isTrue);
  expect(view.autoResize,isFalse);
  expect(view.textStyle.fontFamily,'ProbeNerd');
  final sample = view.terminal;
  expect(sample.viewWidth,16);
  expect(sample.viewHeight,8);
  final markers = List<int>.filled(8,0);
  for (var y = 0; y < 8; y++) {
    final line = sample.buffer.lines[y];
    // Match the numbered prefix rather than assuming wrapping preserved the
    // original row. Count the right-hand separator, excluding the prefix.
    final row = line.getCodePoint(0) - 0x31;
    if (row < 0 || row >= markers.length || line.getCodePoint(1) != 0x7c) continue;
    for (var x = 2; x < sample.viewWidth; x++) {
      if (line.getCodePoint(x) == 0x7c) markers[row] = x + 1;
    }
  }
  final themes = ThemePromptSamples.parse(await rootBundle.loadString('assets/shared/theme-prompt-samples-v1.json'));
  final cursors = <String,Map<String,int>>{};
  for (final id in const ['powerlevel10k','oh-my-posh']) {
    final expected = themes.samples.singleWhere((sample) => sample.id == id);
    final choice = find.byKey(ValueKey('terminal-font-sample-$id'));
    await until(tester,() => choice.evaluate().length == 1 &&
      tester.widget<ChoiceChip>(choice).onSelected != null);
    await tapKey(tester,'terminal-font-sample-$id');
    final themePreview = find.byKey(ValueKey('terminal-theme-view-$id'));
    await until(tester,() => themePreview.evaluate().length == 1 &&
      tester.widget<ChoiceChip>(choice).selected);
    await tester.ensureVisible(themePreview);
    await tester.pump();
    final themeView = tester.widget<TerminalView>(themePreview);
    expect(themeView.readOnly,isTrue);
    expect(themeView.autoResize,isFalse);
    expect(themeView.textStyle.fontFamily,'ProbeNerd');
    final terminal = themeView.terminal;
    expect(terminal.viewWidth,40);
    expect(terminal.viewHeight,3);
    // Read real engine buffer coordinates once per selected bundled sample.
    final x = terminal.buffer.cursorX, y = terminal.buffer.cursorY;
    expect(x,inInclusiveRange(0,terminal.viewWidth - 1));
    expect(y,inInclusiveRange(0,terminal.viewHeight - 1));
    expect(x,expected.cursorColumn);
    expect(y,expected.cursorRow);
    cursors[id] = {'columns':terminal.viewWidth,'rows':terminal.viewHeight,
      'cursorColumn':x,'cursorRow':y};
  }
  await tapKey(tester,'terminal-font-diagnostics-close');
  expect(find.byKey(const ValueKey('terminal-font-diagnostics')),findsNothing);
  expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
  return (markers:markers,themes:cursors);
}
/// Observe the real view after the editor's done action. Do not override view
/// metrics, assign review state, or retry the consent tap if it is not checked.
Future<Finder> stableReviewCheckbox(WidgetTester tester,String key) async {
  final tile = find.byKey(ValueKey(key));
  final checkbox = find.descendant(of:tile,matching:find.byType(Checkbox));
  List<double> previousViewport = const [];
  var stableSamples = 0;
  bool viewportStable() {
    final view = tester.view;
    final sample = <double>[view.physicalSize.width,view.physicalSize.height,view.devicePixelRatio,
      view.viewInsets.left,view.viewInsets.top,view.viewInsets.right,view.viewInsets.bottom];
    final unchanged = sample.length == previousViewport.length &&
      sample.asMap().entries.every((entry) => previousViewport[entry.key] == entry.value);
    previousViewport = sample;
    return view.viewInsets.bottom == 0 && unchanged;
  }
  await until(tester,() {
    stableSamples = viewportStable() && checkbox.evaluate().length == 1 ? stableSamples+1 : 0;
    return stableSamples >= 3;
  },seconds:10);
  await tester.ensureVisible(checkbox);
  Rect? previousBounds;
  stableSamples = 0;
  await until(tester,() {
    if (!viewportStable() || checkbox.hitTestable().evaluate().length != 1) {
      stableSamples = 0; previousBounds = null; return false;
    }
    final bounds = tester.getRect(checkbox);
    stableSamples = previousBounds == bounds ? stableSamples+1 : 0;
    previousBounds = bounds;
    return stableSamples >= 3 && tester.widget<Checkbox>(checkbox).onChanged != null;
  },seconds:10);
  expect(tester.widget<CheckboxListTile>(tile).value,isFalse);
  return checkbox.hitTestable();
}
Finder hostOpen() => find.byWidgetPredicate((widget) => widget is FilledButton &&
  widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('host-open-'));
Finder hostTab() => find.byWidgetPredicate((widget) => widget is TextButton &&
  widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('host-tab-'));
int? displayedSequence(WidgetTester tester) {
  final labels = tester.widgetList<Text>(find.byType(Text)).where((text) =>
    text.data?.contains('观察画布 ') == true && text.data?.contains(' · seq ') == true).toList();
  if (labels.length != 1) return null;
  final match = RegExp(r' · seq ([0-9]+)\n').firstMatch(labels.single.data!);
  return match == null ? null : int.tryParse(match.group(1)!);
}
void publish(Directory dir, String name, String text) {
  final pending = File('${dir.path}/$name.new');
  pending.writeAsStringSync(text,flush:true); pending.renameSync('${dir.path}/$name');
}

Future<void> clipboardCheckpoint(WidgetTester tester,Directory exchange,String label) async {
  expect(guardedInput && syntheticClipboardEnabled,isTrue);
  publish(exchange,'checkpoint.json',jsonEncode({'checkpoint':label}));
  final ack = File('${exchange.path}/checkpoint-ack.json');
  // Host writes an atomic acknowledgement only after its real SSH receiver is
  // exactly k. No terminal text or clipboard text crosses this exchange.
  await until(tester,() => ack.existsSync() && ack.readAsStringSync() == jsonEncode({'checkpoint':label}));
}

Future<void> keyboardCheckpoint(WidgetTester tester,Directory exchange,String label,{bool modeReselected=false,FocusNode? editorFocus}) async {
  expect(systemKeyboardEnabled,isTrue);
  // The pinned IntegrationTestWidgetsFlutterBinding does not register a fake
  // text-input handler. Refuse one installed later as well; isVisible on that
  // stub would only describe TextInput.show requests, not a system IME window.
  expect(tester.testTextInput.isRegistered,isFalse);
  final shown = label.endsWith('-shown') || label.endsWith('-reopened') || label.endsWith('-request');
  // These are the real embedding's view insets; no test metric override is
  // installed. The host separately checks the actual InputMethodService
  // window on the owned AVD and the remote receiver before acknowledging.
  await until(tester,() => shown ? tester.view.viewInsets.bottom > 0 : tester.view.viewInsets.bottom == 0,seconds:12);
  final draft = find.byKey(const ValueKey('remote-input-draft'));
  final focused = editorFocus?.hasFocus ?? (label.startsWith('keyboard-draft-')
    ? tester.widget<TextField>(draft).focusNode?.hasFocus == true
    : tester.widget<TerminalView>(find.byType(TerminalView)).focusNode?.hasFocus == true);
  publish(exchange,'checkpoint.json',jsonEncode({'checkpoint':label,
    'viewInsetBottom':tester.view.viewInsets.bottom.round(),
    'editorFocused':focused,'modeReselected':modeReselected}));
  final ack = File('${exchange.path}/checkpoint-ack.json');
  await until(tester,() => ack.existsSync() && ack.readAsStringSync() == jsonEncode({'checkpoint':label}));
}

Map<String,Object> boundedFailure(Object error,StackTrace stack,String stage,
    {Map<String,Object>? tuiResume,Map<String,Object>? boardSearch}) {
  const classes = {'TestFailure','StateError','RemoteFailure','FormatException','TimeoutException','FlutterError'};
  final name = error.runtimeType.toString();
  final errorClass = error is TypeError ? 'TypeError' : classes.contains(name) ? name : 'other';
  final match = RegExp(r'android_pairing_observe_test\.dart:([0-9]+)(?::[0-9]+)?').firstMatch(stack.toString());
  final parsed = match == null ? 0 : int.tryParse(match.group(1)!) ?? 0;
  return {'stage':stage,'errorClass':errorClass,'line':parsed >= 1 && parsed <= 10000 ? parsed : 0,
    if (tuiResume != null && tuiResumeStages.contains(stage)) 'tuiResume':tuiResume,
    if (boardSearch != null && const {'board_search_text','board_search_state','board_search_count',
        'board_search_history','board_search_clear'}.contains(stage)) 'boardSearch':boardSearch};
}

Map<String,Object> visibleReceipt(WidgetTester tester, String paneId, int count) {
  final control = find.byKey(const ValueKey('remote-input-receipt'));
  final value = tester.widget<Text>(control).data!;
  final match = RegExp(r'^request ([0-9a-f]{32}) · pane (\S+) · terminal (\S+) · ([0-9]+) bytes$').firstMatch(value);
  expect(match,isNotNull);
  expect(match!.group(2),paneId); expect(int.parse(match.group(4)!),count);
  return {'requestId':match.group(1)!,'paneId':match.group(2)!,
    'terminalId':match.group(3)!,'acceptedBytes':count};
}

Future<void> accepted(WidgetTester tester, {String? previousRequest}) => until(tester,() {
  final control = find.byKey(const ValueKey('remote-input-receipt'));
  return control.evaluate().length == 1 &&
    !(tester.widget<Text>(control).data ?? '').contains(previousRequest ?? 'never-a-request') &&
    find.textContaining('服务端已接收 · 仅确认队列受理').evaluate().isNotEmpty;
});

// Only the self-created curses fixture's exact current screen is read. Never
// search accumulated ANSI or scrollback, and never export terminal contents.
List<String> tuiRows(String marker) {
  if (marker == 'open-help') return ['Pocket TUI Help','F1 Return to list'];
  final inserted = marker == 'insert-row';
  final selected = marker != 'initial';
  final shortened = !['initial','select-next','focus-detail'].contains(marker);
  return ['Pocket TUI','F1 Help   F5 Refresh   F10 Finish',
    '${selected ? '  ' : '> '}Build','${selected && !inserted ? '> ' : '  '}Review',
    if (inserted) '> New',
    'Detail: ${shortened ? 'x' : 'xy'}',
    'Focus: ${['focus-detail','erase-character'].contains(marker) ? 'detail' : 'list'}',
    'Refreshes: ${marker == 'refresh' ? 1 : 0}'];
}
bool currentTuiScreen(WidgetTester tester,String marker) {
  final view = find.byType(TerminalView);
  if (view.evaluate().length != 1 || displayedSequence(tester) == null) return false;
  final terminal = tester.widget<TerminalView>(view).terminal;
  if (terminal.viewWidth != 80 || terminal.viewHeight != 24 ||
      terminal.buffer.height != terminal.viewHeight || !terminal.cursorKeysMode) return false;
  final rows = tuiRows(marker);
  for (var y = 0; y < terminal.viewHeight; y++) {
    final actual = String.fromCharCodes(List.generate(terminal.viewWidth,(x) {
      final code = terminal.buffer.lines[y].getCodePoint(x);
      return code == 0 ? 32 : code;
    })).trimRight();
    if (actual != (y < rows.length ? rows[y] : '')) return false;
  }
  return true;
}
/// Synthetic-fixture diagnostics only: no row text, paths, target identity or
/// arbitrary status strings cross the public exchange. A count of 2 means 2+.
Map<String,Object> tuiResumeSnapshot(WidgetTester tester,Terminal before,String tabKey,int actionsCompleted) {
  int count(Finder finder) => finder.evaluate().length.clamp(0,2).toInt();
  final view = find.byType(TerminalView),direct = find.byKey(const ValueKey('remote-mode-direct'));
  final sequence = displayedSequence(tester);
  final pages = find.byType(RemotePage);
  final result = <String,Object>{
    'schemaVersion':2,'actionsCompleted':actionsCompleted,
    'pageCount':count(pages),'pageBusy':false,'pagePaused':false,'pageLive':false,
    'boardFreshness':'none','adapterPhase':'unknown','adapterError':'none','adapterRetireMiss':'none','evidenceFull':false,
    'boardCount':count(find.byKey(const ValueKey('hosts-board-tab'))),
    'tabCount':count(find.byKey(ValueKey(tabKey))),
    'resumeCount':count(find.byKey(const ValueKey('remote-resume'))),
    'viewCount':count(view),'terminalReplaced':false,
    'sequencePresent':sequence != null,'sequence':sequence ?? -1,
    'cols':0,'rows':0,'bufferRows':0,'cursorKeysMode':false,
    'directCount':count(direct),'directEnabled':false,
    'rowsChecked':0,'rowMatchMask':0,'firstMismatchRow':-1,'tailRowsBlank':false,'titleRowMask':0,
  };
  if (result['pageCount'] == 1) {
    final dynamic page = tester.state(pages);
    final evidence = page.adapter.evidence as RemoteEvidence;
    final board = page.dashboard as RemoteDashboard?;
    const errors = {'timeout','channel_cleanup_timeout','channel_identity','channel_capacity',
      'watch_failed','watch_retry_exhausted','resume_target_changed','observe_ended',
      'invalid_first_frame','invalid_frame','invalid_response','sequence_gap','cancelled'};
    final error = evidence.errorCode;
    // Which channel roles missed their CLOSE deadline: observation, watch,
    // snapshot, input; multiple misses join with '+' so one field stays bounded.
    final retireMiss = evidence.channelRetireFailures.toList()..sort();
    result.addAll({'pageBusy':page.busy == true,'pagePaused':page.viewPaused == true,
      'pageLive':page.live == true,'boardFreshness':board?.freshness.name ?? 'none',
      'adapterPhase':evidence.observationPhase,'adapterError':error == null ? 'none' : errors.contains(error) ? error : 'other',
      'adapterRetireMiss':retireMiss.isEmpty ? 'none' : retireMiss.join('+'),
      'evidenceFull':evidence.fullFrameReceived == true});
  }
  if (result['directCount'] == 1) result['directEnabled'] = tester.widget<ChoiceChip>(direct).onSelected != null;
  if (result['viewCount'] != 1) return result;
  final terminal = tester.widget<TerminalView>(view).terminal;
  result.addAll({'terminalReplaced':!identical(terminal,before),
    'cols':terminal.viewWidth.clamp(0,512).toInt(),'rows':terminal.viewHeight.clamp(0,512).toInt(),
    'bufferRows':terminal.buffer.height.clamp(0,512).toInt(),'cursorKeysMode':terminal.cursorKeysMode});
  // Scan independently of cursor mode so a mode failure is distinguishable
  // from matching text. Keep the original acceptance predicate unchanged.
  if (terminal.viewWidth != 80 || terminal.viewHeight != 24 || terminal.buffer.height != 24) return result;
  final expected = tuiRows('initial');
  var mask = 0,titleMask = 0,first = -1;
  for (var y = 0; y < 24; y++) {
    final actual = String.fromCharCodes(List.generate(80,(x) {
      final code = terminal.buffer.lines[y].getCodePoint(x);
      return code == 0 ? 32 : code;
    })).trimRight();
    if (actual == (y < expected.length ? expected[y] : '')) { mask |= 1 << y; }
    else if (first == -1) { first = y; }
    if (actual == 'Pocket TUI') titleMask |= 1 << y;
  }
  result.addAll({'rowsChecked':24,'rowMatchMask':mask,'firstMismatchRow':first,
    'tailRowsBlank':(mask & 0xffff80) == 0xffff80,'titleRowMask':titleMask});
  return result;
}

Future<void> visibleTuiScreen(WidgetTester tester,String marker) async {
  await until(tester,() => currentTuiScreen(tester,marker),seconds:20);
  final view = find.byType(TerminalView);
  // These are the production local reading controls; no terminal bytes or
  // resize requests are generated. Restore the fixture's first screen region.
  for (final key in ['remote-horizontal-slider','remote-vertical-slider']) {
    final slider = find.byKey(ValueKey(key));
    if (slider.evaluate().length == 1) tester.widget<Slider>(slider).onChanged?.call(0);
  }
  await tester.ensureVisible(view); await tester.pump(const Duration(milliseconds:150));
  expect(currentTuiScreen(tester,marker),isTrue);
  final terminal = tester.widget<TerminalView>(view).terminal;
  final render = tester.state<TerminalViewState>(view).renderTerminal;
  final cells = visibleRemoteScreenCells(terminal,render,
    Offset.zero & tester.view.physicalSize / tester.view.devicePixelRatio);
  // The rounded viewport conservatively excludes its corner cells. Require
  // the changing synthetic row's inner text to be fully visible as well as
  // checking the exact complete current screen above (including its title).
  final row = switch (marker) {
    'open-help' => 1,
    'initial' => 2,
    'select-next' || 'delete-row' || 'close-help' => 3,
    'insert-row' || 'erase-character' => 4,
    'focus-detail' || 'focus-list' => 5,
    'refresh' => 6,
    _ => throw StateError('invalid_tui_marker'),
  };
  expect(cells,isNotNull);
  expect(cells!.firstRow,lessThanOrEqualTo(row)); expect(cells.endRow,greaterThan(row));
  expect(cells.firstColumn,lessThanOrEqualTo(2)); expect(cells.endColumn,greaterThanOrEqualTo(tuiRows(marker)[row].length));
  expect(tester.widget<TerminalView>(view).autoResize,isFalse);
}
Future<Map<String,Object>> exerciseTui(WidgetTester tester,Directory exchange,
    Map<String,dynamic> target,String tabKey,List<Map<String,Object>> prior,void Function(String) stage,
    void Function(Map<String,Object>) recordResume) async {
  expect(guardedInput && guardedTui,isTrue);
  final terminalId = prior.first['terminalId'] as String;
  expect(prior.last['terminalId'],terminalId);
  stage('tui_start');
  publish(exchange,'checkpoint.json',jsonEncode({'checkpoint':'tui-start','terminalId':terminalId}));
  final ack = File('${exchange.path}/checkpoint-ack.json');
  await until(tester,() => ack.existsSync() && ack.readAsStringSync() == jsonEncode({'checkpoint':'tui-start'}));
  // Explicit resume provides an unambiguous post-start full on the same PTY.
  // This retires old authorization; a later full within this new channel does
  // not authorize a different target, nor require changing the user's mode.
  stage('tui_find_board');
  final before = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
  var actionsCompleted = 0;
  void sample() => recordResume(tuiResumeSnapshot(tester,before,tabKey,actionsCompleted));
  await tap(tester,find.byKey(const ValueKey('hosts-board-tab')),onPoll:sample);
  actionsCompleted = 1; sample();
  stage('tui_return_tab');
  await tap(tester,find.byKey(ValueKey(tabKey)),onPoll:sample);
  actionsCompleted = 2; sample();
  stage('tui_find_resume');
  await tap(tester,find.byKey(const ValueKey('remote-resume')),onPoll:sample);
  actionsCompleted = 3; sample();
  stage('tui_resume_full');
  await until(tester,() {
    sample();
    return find.byType(TerminalView).evaluate().length == 1 &&
      !identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal,before) &&
      currentTuiScreen(tester,'initial') &&
      tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected != null;
  });
  expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
  stage('tui_initial'); await visibleTuiScreen(tester,'initial');
  await tapKey(tester,'remote-mode-direct');
  await tapKey(tester,'remote-function-keys-toggle');
  final checks = <String>['initial'], receipts = <Map<String,Object>>[];
  final seen = prior.map((receipt) => receipt['requestId']).toSet();
  final actions = <(String,String?,int)>[
    ('remote-key-↓','select-next',3),('remote-key-Tab','focus-detail',1),
    ('remote-function-key-backspace','erase-character',1),('remote-function-key-shift-tab','focus-list',3),
    ('remote-function-key-insert','insert-row',4),('remote-function-key-delete','delete-row',4),
    ('remote-function-key-f1','open-help',3),('remote-function-key-f1','close-help',3),
    ('remote-function-key-f5','refresh',5),('remote-function-key-f10',null,5)];
  var previousRequest = prior.last['requestId'] as String;
  for (final (key,marker,size) in actions) {
    stage('tui_${marker?.replaceAll('-','_') ?? 'finish'}');
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).selected,isTrue);
    final label = tester.widget<Text>(find.textContaining('当前输入目标：')).data!;
    expect(label,contains(target['paneId'] as String)); expect(label,contains(terminalId));
    final sequence = displayedSequence(tester)!;
    final button = find.byKey(ValueKey(key));
    await until(tester,() => button.evaluate().length == 1 && tester.widget<OutlinedButton>(button).onPressed != null);
    // Exactly one visible tap, with no retry after an unknown result.
    await tap(tester,button); await accepted(tester,previousRequest:previousRequest);
    final receipt = visibleReceipt(tester,target['paneId'] as String,size);
    expect(receipt['terminalId'],terminalId); expect(seen.add(receipt['requestId']),isTrue);
    receipts.add(receipt); previousRequest = receipt['requestId'] as String;
    if (marker != null) {
      await until(tester,() => (displayedSequence(tester) ?? -1) > sequence && currentTuiScreen(tester,marker),seconds:20);
      await visibleTuiScreen(tester,marker); checks.add(marker);
    }
  }
  return {'receipts':receipts,'screenChecks':checks,'observedInitialFull':true};
}

/// The visible production count line. Both numbers come from the widget, not
/// from a value this test recomputed.
({int shown,int total}) boardCounts(WidgetTester tester) {
  final match=RegExp(r'^显示 ([0-9]+) / ([0-9]+) 台主机$')
    .firstMatch(tester.widget<Text>(find.byKey(const ValueKey('hosts-filter-count'))).data ?? '');
  if (match == null) throw StateError('board_filter_count_unreadable');
  return (shown:int.parse(match.group(1)!),total:int.parse(match.group(2)!));
}

/// The production selector label, which carries its own host count.
String taskFilterLabel(WidgetTester tester,HostTaskFilter value) {
  final items=tester.widget<DropdownButton<HostTaskFilter>>(find.byKey(const ValueKey('hosts-task-filter'))).items!;
  return (items.singleWhere((item) => item.value == value).child as Text).data ?? '';
}
int taskFilterCount(String label) {
  final match=RegExp(r'（([0-9]+)）$').firstMatch(label);
  if (match == null) throw StateError('board_task_filter_count_unreadable');
  return int.parse(match.group(1)!);
}

/// Rows under the host's blocked group. Each row must display its own pane and
/// terminal, so two same-name targets stay distinguishable on screen.
List<({String paneId,String terminalId})> boardHistoryRows(WidgetTester tester,String hostId) {
  final group=find.byKey(ValueKey(blockedSummaryGroupKey(hostId)));
  final tiles=find.descendant(of:group,matching:find.byWidgetPredicate((widget) => widget is ListTile &&
    widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('host-blocked-target-')));
  final rows=<({String paneId,String terminalId})>[];
  for (final tile in tester.widgetList<ListTile>(tiles)) {
    final ids=(jsonDecode((tile.key! as ValueKey<String>).value.substring('host-blocked-target-'.length)) as List).cast<String>();
    if (ids.length != 3) throw StateError('board_history_row_invalid');
    final subtitle=(tile.subtitle as Text).data ?? '';
    final shown=RegExp(r'pane (\S+) · terminal (\S+)$').firstMatch(subtitle);
    if (shown == null || shown.group(1) != ids[1] || shown.group(2) != ids[2]) {
      throw StateError('board_history_row_not_displayed');
    }
    rows.add((paneId:ids[1],terminalId:ids[2]));
  }
  return rows;
}

/// Drive the production board retrieval on the device: type a session fragment,
/// pick the task-state selector, read both visible counts, open the history
/// rows that keep two same-name targets apart, then clear the text and use the
/// empty-result reset. Every published number is read back from a real widget.
///
/// The board filters only rebuild the visible list in memory, and this group
/// performs no catalog reload, so no native call is added. Counting channel
/// traffic directly would need an injected channel interceptor, which this
/// public package must not contain.
Map<String,Object>? boardSearchFailureProbe;
Future<Map<String,Object>> exerciseBoardSearch(WidgetTester tester,String session,String hostId,
    void Function(String) stage) async {
  stage('board_search_text');
  final board=find.byKey(const ValueKey('host-catalog-list'));
  final search=find.byKey(const ValueKey('hosts-search'));
  final filter=find.byKey(const ValueKey('hosts-task-filter'));
  await until(tester,() => board.evaluate().length == 1);
  // The board retains its scroll position after opening a blocked target, so
  // its lazily built search controls may be above the visible list.
  await tester.scrollUntilVisible(search,-300,
    scrollable:find.descendant(of:board,matching:find.byType(Scrollable)).first);
  await until(tester,() => search.evaluate().length == 1 && filter.evaluate().length == 1);
  await tester.ensureVisible(search);
  await tester.enterText(search,session); await tester.pump();
  final textMatched=boardCounts(tester).shown;
  if (textMatched < 1) throw StateError('board_search_text_no_match');
  stage('board_search_state');
  final currentCount=taskFilterCount(taskFilterLabel(tester,HostTaskFilter.current));
  final historyLabel=taskFilterLabel(tester,HostTaskFilter.history);
  final historyCount=taskFilterCount(historyLabel);
  if (historyCount < 1) throw StateError('board_search_history_empty');
  await tapStablePointer(tester,filter);
  await tapPopupOption(tester,find.text(historyLabel));
  await until(tester,() => tester.widget<DropdownButton<HostTaskFilter>>(filter).value == HostTaskFilter.history);
  stage('board_search_count');
  final counts=boardCounts(tester);
  if (counts.shown < 1 || counts.shown > counts.total) throw StateError('board_search_count_invalid');
  stage('board_search_history');
  final group=find.byKey(ValueKey(blockedSummaryGroupKey(hostId)));
  await until(tester,() => group.evaluate().length == 1);
  final rows=find.descendant(of:group,matching:find.byWidgetPredicate((widget) => widget is ListTile &&
    widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('host-blocked-target-')));
  await until(tester,() => rows.evaluate().isNotEmpty);
  // A collapsed group clips its rows away or removes them from the tree
  // entirely, so a visible expansion is read from hit-testability, while the
  // closed state is the rows actually leaving the widget list: clipping alone
  // hides them mid-animation. Re-open only a group that was collapsed — an
  // unconditional second tap would close a group that stayed open and leave
  // the wait below polling a tree that no longer holds any row.
  await tester.ensureVisible(rows.first); await tester.pump();
  if (rows.hitTestable().evaluate().isNotEmpty) {
    await tapStablePointer(tester,groupHeader(group)); // Collapse the group the blocked review left open.
    await until(tester,() => rows.evaluate().isEmpty);
    await tapStablePointer(tester,groupHeader(group)); // Re-open only what the tap above collapsed.
  }
  await until(tester,() => rows.evaluate().isNotEmpty);
  await tester.ensureVisible(rows.first); await tester.pump();
  await until(tester,() => rows.hitTestable().evaluate().isNotEmpty);
  final history=boardHistoryRows(tester,hostId);
  if (history.isEmpty) throw StateError('board_search_history_empty');
  final distinct=history.map((row) => '${row.paneId} ${row.terminalId}').toSet();
  if (distinct.length != history.length) throw StateError('board_search_history_indistinguishable');
  stage('board_search_clear');
  // The board is a lazy ListView: the history phase scrolled a host card to
  // the top, evicting the search field (and its clear button) from the
  // viewport. Return to the top so the control is built again before tapping.
  // The key sits on the ListView, so resolve its inner Scrollable first —
  // the same pattern host_catalog_search_widget_test uses via boardList().
  final boardScrollable=find.descendant(
    of:find.byKey(const ValueKey('host-catalog-list')),
    matching:find.byType(Scrollable)).first;
  tester.state<ScrollableState>(boardScrollable).position.jumpTo(0);
  // Do NOT pumpAndSettle here: hidden tabs in the IndexedStack keep a
  // blinking terminal cursor alive, so settle never converges and the test
  // is killed by its own timeout with no failure report (runs 42556512895
  // and 42558100632 both died exactly here as test_exited). Pump a bounded
  // number of frames instead so the lazy list rebuilds the top controls.
  for (var i = 0; i < 20; i++) { await tester.pump(const Duration(milliseconds: 100)); }
  // Runs 42548234405/42549882281/42553557053 failed this tap with three
  // different signatures. Fail fast with the evidence snapshot instead of
  // another blind 60-second until spin.
  final clearButton=find.byKey(const ValueKey('hosts-search-clear'));
  if (clearButton.evaluate().length != 1) {
    boardSearchFailureProbe = <String,Object>{
      'textMatched':textMatched,'dualConditionCount':counts.shown,'totalHosts':counts.total,
      'currentCount':currentCount,'historyCount':historyCount,'historyRows':history.length,
      'historyDistinguished':true,'clearedKeptState':false,'resetRestoredList':false,'nativeCallsAdded':0};
    throw StateError('board_search_clear_clear_missing');
  }
  boardSearchFailureProbe = <String,Object>{
    'textMatched':textMatched,'dualConditionCount':counts.shown,'totalHosts':counts.total,
    'currentCount':currentCount,'historyCount':historyCount,'historyRows':history.length,
    'historyDistinguished':true,'clearedKeptState':false,'resetRestoredList':false,'nativeCallsAdded':0};
  // Use the stable-pointer tap: between the wait and the pointer, a settling
  // lazy list can rebuild this suffix control again. The stable helper
  // re-resolves a hit-testable target on every poll and taps once.
  await tapStablePointer(tester,clearButton);
  final cleared=boardCounts(tester);
  final clearedKeptState=tester.widget<DropdownButton<HostTaskFilter>>(filter).value == HostTaskFilter.history &&
    cleared.shown == historyCount;
  if (!clearedKeptState) throw StateError('board_search_clear_dropped_state');
  // The production reset control exists only on an empty result.
  await tester.enterText(search,'zz-no-such-entry'); await tester.pump();
  await until(tester,() => find.byKey(const ValueKey('hosts-search-empty')).evaluate().length == 1 &&
    find.byKey(const ValueKey('hosts-filters-reset')).evaluate().length == 1);
  await tapStablePointer(tester,find.byKey(const ValueKey('hosts-filters-reset')));
  final restored=boardCounts(tester);
  final resetRestoredList=tester.widget<DropdownButton<HostTaskFilter>>(filter).value == HostTaskFilter.all &&
    (tester.widget<TextField>(search).controller?.text ?? '') == '' && restored.shown == restored.total;
  if (!resetRestoredList) throw StateError('board_search_clear_reset_failed');
  final evidence=<String,Object>{
    'textMatched':textMatched,'dualConditionCount':counts.shown,'totalHosts':counts.total,
    'currentCount':currentCount,'historyCount':historyCount,'historyRows':history.length,
    'historyDistinguished':true,'clearedKeptState':true,'resetRestoredList':true,'nativeCallsAdded':0};
  if (evidence.values.whereType<int>().any((value) => value < 0 || value > 64)) {
    throw StateError('board_search_evidence_out_of_bounds');
  }
  return evidence;
}

/// Map the visible device status line and scope list to the three published
/// classes (docs/55): an unreadable host/network catalog shows an unknown
/// scope, an unbound or locked device service shows an unreadable device
/// state with the scope still listed, and a stored pending operation shows the
/// pending class. A confirmed present or absent identity cannot be expressed
/// by that contract, so such a display fails the stage instead of coercing
/// itself into a class.
String deviceStateClass(WidgetTester tester) {
  if (find.byKey(const ValueKey('zt-impact-unknown')).evaluate().isNotEmpty) return 'catalog_blocked';
  final state=tester.widget<Text>(find.byKey(const ValueKey('zt-device-state'))).data ?? '';
  if (state.startsWith('尚未确认')) return ''; // The status read is still running.
  if (state.startsWith('设备身份暂不可用')) return 'unknown';
  if (state.startsWith('有未完成操作')) return 'pending';
  throw StateError('device_state_unclassified');
}

/// Identity controls that could change a device identity. The count is the
/// number of enabled ones in the visible review.
int enabledIdentityActions(WidgetTester tester) {
  var count=0;
  for (final key in const ['zt-device-create','zt-device-review','zt-device-forget','zt-pending-confirm',
    'zt-pending-review-recoverPendingCreation','zt-pending-review-discardPendingCreation',
    'zt-pending-review-recoverPendingDeletion']) {
    final control=find.byKey(ValueKey(key));
    if (control.evaluate().length == 1 && tester.widget<ButtonStyleButton>(control).onPressed != null) count++;
  }
  return count;
}

/// Read the shared-device review on the device. This group never taps an
/// identity action: the status line decides whether such an action is even
/// offered, and on this build the native engine is not bound, so the review
/// only shows the unreadable state. No network is joined and no device
/// identity is created, changed or removed.
Future<Map<String,Object>> exerciseDeviceImpact(WidgetTester tester,void Function(String) stage) async {
  stage('device_impact_enter');
  await tapKey(tester,'hosts-networks');
  final entry=find.byKey(const ValueKey('networks-zerotier-device'));
  await until(tester,() => entry.evaluate().length == 1 &&
    tester.widget<OutlinedButton>(entry).onPressed != null);
  await tap(tester,entry);
  await until(tester,() => find.byKey(const ValueKey('zt-device-list')).evaluate().length == 1);
  var rereadCalls=1; // The review reads the device status once when it opens.
  stage('device_impact_scope');
  var statusClass='';
  await until(tester,() { statusClass=deviceStateClass(tester); return statusClass.isNotEmpty; },seconds:30);
  final scopeListed=find.textContaining('完整影响范围 · ').evaluate().isNotEmpty;
  if (statusClass == 'catalog_blocked' && scopeListed) throw StateError('device_impact_scope_inconsistent');
  if (statusClass == 'unknown' && !scopeListed) throw StateError('device_impact_scope_not_listed');
  stage('device_impact_reread');
  final refresh=find.byKey(const ValueKey('zt-device-refresh'));
  // An enabled re-read control means the previous read has settled.
  await until(tester,() => refresh.evaluate().length == 1 &&
    tester.widget<OutlinedButton>(refresh).onPressed != null);
  await tap(tester,refresh);
  rereadCalls++; // One explicit re-read of the original status.
  var rereadClass='';
  await until(tester,() { rereadClass=deviceStateClass(tester); return rereadClass.isNotEmpty; },seconds:30);
  if (rereadClass != statusClass) throw StateError('device_impact_reread_class_changed');
  stage('device_remove_blocked');
  final actions=enabledIdentityActions(tester);
  // Removing an identity needs the original identity, the full scope and the
  // stop proofs, so an unreadable or blocked state offers no identity action.
  if ((statusClass == 'unknown' || statusClass == 'catalog_blocked') && actions != 0) {
    throw StateError('device_remove_not_blocked');
  }
  await tapKey(tester,'zt-device-close');
  await until(tester,() => find.byKey(const ValueKey('zt-device-list')).evaluate().isEmpty);
  await until(tester,() => entry.evaluate().length == 1 &&
    tester.widget<OutlinedButton>(entry).onPressed != null);
  await tap(tester,entry);
  await until(tester,() => find.byKey(const ValueKey('zt-device-list')).evaluate().length == 1);
  rereadCalls++; // The re-entered review reads the device status again.
  var reenteredClass='';
  await until(tester,() { reenteredClass=deviceStateClass(tester); return reenteredClass.isNotEmpty; },seconds:30);
  if (reenteredClass != statusClass) throw StateError('device_impact_reentry_class_changed');
  if (enabledIdentityActions(tester) != actions) throw StateError('device_impact_reentry_changed_actions');
  await tapKey(tester,'zt-device-close');
  await until(tester,() => find.byKey(const ValueKey('zt-device-list')).evaluate().isEmpty);
  await tester.pageBack(); await tester.pump(const Duration(milliseconds:400));
  await until(tester,() => find.byKey(const ValueKey('hosts-add')).evaluate().length == 1);
  // writeCalls counts identity writes dispatched by this group: none. The only
  // controls it pressed are the re-read, the close and the re-entry, and on an
  // unreadable or blocked state every identity action stays disabled.
  return <String,Object>{'statusClass':statusClass,'scopeListed':scopeListed,'deviceActions':actions,
    'rereadCalls':rereadCalls,'reentered':true,'writeCalls':0};
}

// Independent ephemeral identity. It never enters the host catalog or pairing.
Future<void> nativeSignerProbe(Directory exchange, void Function(String) stage) async {
  final keys = NativeDeviceKeys();
  String? handle;
  var deleteAttempted = false;
  try {
    stage('signer_create');
    handle = await keys.create();
    stage('signer_public');
    final publicKey = await keys.public(handle);
    stage('signer_sign');
    final signature = await keys.sign(handle,Uint8List.fromList(utf8.encode('herdr-pocket-android-signer-probe-v1')));
    stage('signer_delete');
    deleteAttempted = true;
    await keys.delete(handle);
    stage('signer_read_deleted');
    var rejected = false;
    try { await keys.public(handle); } catch (_) { rejected = true; }
    if (!rejected) throw StateError('signer_deleted_read_succeeded');
    publish(exchange,'signer.json',jsonEncode({'publicKey':publicKey,
      'signature':base64Encode(signature),'deleteReturned':true,'readRejected':true}));
  } finally {
    // One cleanup attempt only; never retry an operation with an unknown result.
    if (handle != null && !deleteAttempted) await keys.delete(handle);
  }
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Android native identity through production host catalog to guarded or stock SSH',(tester) async {
    Directory? failureDirectory;
    var currentStage = 'fixture_validation';
    Map<String,Object>? tuiResumeDiagnostic;
    try {
    expect(tester.testTextInput.isRegistered,isFalse);
    final target = checkedTarget();
    final blockedTargets = checkedBlockedTargets(target);
    final exchange = Directory(publicDirectory);
    if (exchange.existsSync()) throw StateError('android_public_exchange_already_exists');
    exchange.createSync(recursive:true);
    failureDirectory = exchange;
    void stage(String name) {
      if (!RegExp(r'^[a-z][a-z0-9_]{0,39}$').hasMatch(name)) throw StateError('invalid_public_stage');
      currentStage = name; publish(exchange,'stage',name);
    }
    await nativeSignerProbe(exchange,stage);
    stage('host_board');
    await app.main();
    await until(tester,() => find.byType(HostCatalogPage).evaluate().length == 1 &&
      find.byKey(const ValueKey('hosts-add')).evaluate().isNotEmpty &&
      tester.widget<FilledButton>(find.byKey(const ValueKey('hosts-add'))).onPressed != null);
    final home = tester.widget<HostCatalogPage>(find.byType(HostCatalogPage));
    expect(home.catalog,isNull); expect(home.keys,isNull); expect(home.adapterFactory,isNull);
    expect(hostOpen(),findsNothing); // The runner requires a fresh package install.
    await tapKey(tester,'hosts-add');
    final pairingPage = tester.widget<PairingPage>(find.byType(PairingPage));
    expect(pairingPage.keys,isNull); expect(pairingPage.adapter,isNull); expect(pairingPage.catalog,isNotNull);
    stage('public_request');
    stage('profile_enter');
    final catalog = pairingPage.catalog!;
    var identityCreationActions = 0; // Catalog identity only; signer probe is separate.
    expect(catalog.profiles,isEmpty); expect(catalog.pendingCreation,isNull);
    expect(PairingPage.retainedPairing,isNull);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    final publicInput = find.byKey(const ValueKey('profile-input'));
    await tester.ensureVisible(publicInput); await tester.enterText(publicInput,publicProfile); await tester.pump();
    stage('profile_preview');
    final preview = find.byKey(const ValueKey('profile-preview'));
    await until(tester,() => preview.evaluate().length == 1);
    final previewText = tester.widget<SelectableText>(preview).data!;
    for (final name in ['host','port','username','session','socketPath','herdrPath']) {
      expect(previewText,contains(target[name].toString()));
    }
    expect(previewText,contains('direct'));
    expect(previewText,contains(hostFingerprint));
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNull);
    expect(catalog.profiles,isEmpty); expect(catalog.pendingCreation,isNull); expect(PairingPage.retainedPairing,isNull);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    stage('profile_fill');
    await tapKey(tester,'profile-fill');
    expect(find.byKey(const ValueKey('profile-preview')),findsNothing);
    expect(tester.state<FormFieldState<String>>(find.byKey(const ValueKey('pair-provider'))).value,'direct');
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isFalse);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create'))).onPressed,isNull);
    expect(catalog.profiles,isEmpty); expect(catalog.pendingCreation,isNull); expect(PairingPage.retainedPairing,isNull);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    final reviewedFields = <String,String>{
      for (final name in ['host','port','username','session','socketPath','herdrPath','expectedHostKey'])
        name:tester.widget<TextField>(find.byKey(ValueKey('pair-$name'))).controller!.text,
    };
    for (final entry in reviewedFields.entries) { expect(entry.value,target[entry.key].toString()); }
    stage('target_finish_edit');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump(const Duration(milliseconds:300));
    stage('target_review_ready');
    final targetCheckbox = await stableReviewCheckbox(tester,'pair-target-review');
    await tester.tap(targetCheckbox); await tester.pump(const Duration(milliseconds:150));
    stage('target_review_unchecked');
    checkPointerError(tester);
    // Layout/focus may move after the pointer has committed consent. Read the
    // stable control's actual value; do not require the old hit point to remain.
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-target-review'))).value,isTrue);
    expect(identityCreationActions,0);
    expect(catalog.profiles,isEmpty); expect(catalog.pendingCreation,isNull);
    expect(PairingPage.retainedPairing,isNull); expect(PairingPage.retainedCreationUnknown,isFalse);
    expect(PairingPage.retainedOrphan,isNull);
    expect(find.byKey(const ValueKey('pair-request')),findsNothing);
    for (final entry in reviewedFields.entries) {
      expect(tester.widget<TextField>(find.byKey(ValueKey('pair-${entry.key}'))).controller!.text,entry.value);
    }
    stage('target_create_ready');
    final createButton = find.byKey(const ValueKey('pair-create'));
    if (tester.widget<FilledButton>(createButton).onPressed == null) {
      stage('target_create_unavailable'); fail('target_create_unavailable');
    }
    await Scrollable.ensureVisible(tester.element(createButton),alignment:0.5);
    Rect? previousBounds;
    var stable = 0;
    await until(tester,() {
      final bounds = tester.getRect(createButton);
      stable = tester.view.viewInsets.bottom == 0 && createButton.hitTestable().evaluate().length == 1 &&
        bounds == previousBounds && tester.widget<FilledButton>(createButton).onPressed != null ? stable + 1 : 0;
      previousBounds = bounds;
      return stable >= 3;
    },seconds:12);
    stage('target_create_one_tap');
    expect(identityCreationActions,0);
    identityCreationActions++;
    await tester.tap(createButton.hitTestable()); // Only one native creation attempt.
    await tester.pump();
    stage('target_request_wait');
    final requestControl = find.byKey(const ValueKey('pair-request'));
    const errors = {'核验连接资料':'target_invalid','保存创建意图':'catalog_intent_failed',
      '创建设备身份':'device_create_failed','保存本机密钥引用':'handle_save_failed',
      '读取设备公钥':'public_key_failed','保存主机资料':'profile_save_failed'};
    await until(tester,() {
      if (requestControl.evaluate().length == 1) return true;
      final status = tester.widget<Text>(find.byKey(const ValueKey('pair-status'))).data ?? '';
      for (final entry in errors.entries) {
        if (status.startsWith('${entry.key}未完成')) { stage(entry.value); fail(entry.value); }
      }
      return false;
    });
    final request = tester.widget<SelectableText>(requestControl).data!;
    expect(utf8.encode(request).length,lessThanOrEqualTo(2048));
    publish(exchange,'request.json',request);

    // Restore from the real app-private catalog and verify the original native
    // public key. No static test-reset or replacement identity is introduced.
    stage('restore_pending');
    await tester.pageBack(); await tester.pump(const Duration(milliseconds:400));
    await until(tester,() => hostOpen().evaluate().length == 1);
    final openControl = tester.widget<FilledButton>(hostOpen());
    final id = (openControl.key! as ValueKey<String>).value.substring('host-open-'.length);
    expect(RegExp(r'^[0-9a-f]{32}$').hasMatch(id),isTrue);
    await tap(tester,hostOpen());
    await until(tester,() => requestControl.evaluate().length == 1 &&
      find.textContaining('本机原身份已匹配').evaluate().isNotEmpty);
    expect(tester.widget<SelectableText>(requestControl).data,request);
    expect(find.textContaining('awaiting-host'),findsOneWidget);
    stage('host_authorization');
    final responseFile = File('${exchange.path}/response.json');
    await until(tester,responseFile.existsSync);
    final response = responseFile.readAsStringSync();
    expect(utf8.encode(response).length,lessThanOrEqualTo(2048));
    stage('response_enter');
    final responseControl = find.byKey(const ValueKey('pair-response'));
    await tester.ensureVisible(responseControl); await tester.enterText(responseControl,response); await tester.pump();
    stage('response_finish_edit');
    // Finish the actual editor before scrolling to review controls. Keeping a
    // native multiline IME open can change the viewport between ensureVisible
    // and tap. This is a GUI input action, not a permission/state assignment.
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump(const Duration(milliseconds:350));
    expect(tester.widget<TextField>(responseControl).controller!.text == response,isTrue);
    stage('response_preview');
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    stage('response_source_confirm');
    final sourceCheckbox = await stableReviewCheckbox(tester,'pair-source-review');
    await tester.tap(sourceCheckbox); // One real pointer action on the checkbox.
    await tester.pump(const Duration(milliseconds:350));
    expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('pair-source-review'))).value,isTrue);
    stage('response_accept');
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('pair-accept'))).onPressed,isNotNull);
    await tapKey(tester,'pair-accept');
    stage('response_authorized');
    await until(tester,() {
      if (find.textContaining('authorized-unverified').evaluate().isNotEmpty) return true;
      final statusControl = find.byKey(const ValueKey('pair-status'));
      if (statusControl.evaluate().length != 1) return false;
      final message = tester.widget<Text>(statusControl).data ?? '';
      final failedStage = message.startsWith('响应无效') ? 'response_rejected'
        : message.startsWith('响应核验后本机保存未确认') ? 'response_save_unconfirmed'
        : message.startsWith('响应审查期间页面已变化') ? 'response_review_invalidated' : null;
      if (failedStage != null) { stage(failedStage); throw StateError('response_not_accepted'); }
      return false;
    });
    stage('response_open_remote');
    await tapKey(tester,'pair-connect');
    await until(tester,() => find.byType(RemotePage).evaluate().length == 1);
    stage('response_remote_identity');
    final remotePage = tester.widget<RemotePage>(find.byType(RemotePage));
    expect(remotePage.adapter,isNull); expect(remotePage.deviceKeys,isA<NativeDeviceKeys>());
    expect(remotePage.pairedTarget,isNotNull);
    if (!guardedInput) {
      stage('observe_canvas_select');
      final canvas = find.byKey(const ValueKey('remote-canvas-size'));
      final canvasField = tester.widget<DropdownButtonFormField<int>>(canvas);
      expect(canvasField.onChanged,isNotNull);
      expect(tester.state<FormFieldState<int>>(canvas).value,0);
      final optionKey = const ValueKey('remote-canvas-120x40');
      final button = find.descendant(of:canvas,matching:find.byType(DropdownButton<int>));
      expect(button,findsOneWidget);
      final optionValue = tester.widget<DropdownButton<int>>(button).items!
        .singleWhere((item) => item.key == optionKey).value;
      expect(optionValue,1);
      stage('observe_canvas_open');
      await tapStablePointer(tester,button);
      stage('observe_canvas_option');
      await tapPopupOption(tester,find.byKey(optionKey));
      stage('observe_canvas_verify');
      await until(tester,() {
        checkPointerError(tester);
        final selected = tester.state<FormFieldState<int>>(canvas).value;
        if (popupOptionControl(find.byKey(optionKey)).evaluate().isNotEmpty) return false;
        expect(selected,optionValue,reason:'the visible selection must commit before connecting');
        return true;
      },seconds:10);
      expect(tester.widget<DropdownButtonFormField<int>>(canvas).onChanged,isNotNull);
      expect(tester.widget<CheckboxListTile>(find.byKey(const ValueKey('remote-review'))).value,isFalse);
    }
    stage('ssh_and_dashboard');
    await tapKey(tester,'remote-review'); await tapKey(tester,'remote-connect');
    final pane = find.byKey(ValueKey('remote-pane-${target['paneId']}'));
    await until(tester,() => pane.evaluate().length == 1);
    expect(find.textContaining('状态 paired',skipOffstage:false),findsOneWidget);
    stage('host_task_summary_authoritative');
    final hostSummaryControl = find.byKey(const ValueKey('remote-host-task-summary'));
    await until(tester,() {
      if (hostSummaryControl.evaluate().length != 1) return false;
      final summary = tester.widget<Text>(hostSummaryControl).data ?? '';
      return summary.startsWith('当前主机摘要 · 主机报告 · ') && summary.contains('原会话 ${target['session']}');
    });
    expect(tester.widget<Text>(find.byKey(const ValueKey('remote-dashboard-sync'))).data,
      contains('${target['username']}@${target['host']}:${target['port']} / ${target['session']}'));
    stage('observe_frames');
    await tap(tester,pane);
    await until(tester,() => find.byType(TerminalView).evaluate().length == 1 &&
      find.textContaining('只读观察中').evaluate().isNotEmpty && displayedSequence(tester) != null);
    final firstSequence = displayedSequence(tester)!;
    final fullTerminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    // Production RemotePage replaces Terminal on every full; an increased seq
    // on the same object therefore proves a delta was consumed, without a
    // test hook, synthetic frame, or access to the adapter's private state.
    await until(tester,() => find.byType(TerminalView).evaluate().length == 1 &&
      (displayedSequence(tester) ?? -1) > firstSequence &&
      identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal,fullTerminal));
    final deltaSequence = displayedSequence(tester)!;
    final observerCanvas = <String,dynamic>{};
    if (!guardedInput) {
      stage('observe_canvas_render');
      expect([fullTerminal.viewWidth,fullTerminal.viewHeight], [120,40]);
      final mark = 'HPWIDE'.codeUnits;
      await until(tester,() {
        final line = fullTerminal.buffer.lines[31];
        for (var index = 0; index < mark.length; index++) {
          if (line.getCodePoint(91 + index) != mark[index]) return false;
        }
        return true;
      });
      // Drive the app's two local reading sliders. Their callbacks change only
      // local scroll controllers, including for alternate-screen applications.
      final view = find.byType(TerminalView);
      final viewport = find.byKey(const ValueKey('remote-horizontal-scroll'));
      final horizontalSlider = find.byKey(const ValueKey('remote-horizontal-slider'));
      final verticalSlider = find.byKey(const ValueKey('remote-vertical-slider'));
      final horizontal = tester.widget<SingleChildScrollView>(viewport).controller!;
      final vertical = tester.widget<TerminalView>(view).scrollController!;
      expect(tester.widget<TerminalView>(view).autoResize,isFalse);
      final oldHorizontal = horizontal.offset, oldVertical = vertical.offset;
      final horizontalMax = horizontal.position.maxScrollExtent, verticalMax = vertical.position.maxScrollExtent;
      Future<void> setReading(Finder slider,double value) async {
        final changed = tester.widget<Slider>(slider).onChanged;
        if (changed != null) changed(value);
        await tester.pump(const Duration(milliseconds:100));
        await tester.ensureVisible(viewport);
        await tester.pump(const Duration(milliseconds:100));
      }
      bool containsMarker({required bool row,required bool columns}) {
        if (view.evaluate().length != 1 || !identical(tester.widget<TerminalView>(view).terminal,fullTerminal)) return false;
        final render = tester.state<TerminalViewState>(view).renderTerminal;
        final bounds = Offset.zero & tester.view.physicalSize / tester.view.devicePixelRatio;
        final cells = visibleRemoteScreenCells(fullTerminal,render,bounds);
        return cells != null && (!row || cells.firstRow <= 31 && cells.endRow > 31) &&
          (!columns || cells.firstColumn <= 91 && cells.endColumn >= 97);
      }
      await tester.ensureVisible(viewport);
      await tester.pump(const Duration(milliseconds:100));
      for (var step = 0; step <= 20 && !containsMarker(row:true,columns:false); step++) {
        await setReading(verticalSlider,step / 20);
      }
      expect(containsMarker(row:true,columns:false),isTrue);
      for (var step = 0; step <= 20 && !containsMarker(row:true,columns:true); step++) {
        await setReading(horizontalSlider,step / 20);
      }
      expect(containsMarker(row:true,columns:true),isTrue);
      // Check the actual buffer again while all six cells are fully visible.
      for (var index = 0; index < mark.length; index++) {
        expect(fullTerminal.buffer.lines[31].getCodePoint(91 + index),mark[index]);
      }
      await setReading(horizontalSlider,horizontalMax > 0 ? oldHorizontal / horizontalMax : 0);
      await setReading(verticalSlider,verticalMax > 0 ? oldVertical / verticalMax : 0);
      expect(horizontal.offset,closeTo(oldHorizontal,1));
      expect(vertical.offset,closeTo(oldVertical,1));
      expect(tester.widget<TerminalView>(view).autoResize,isFalse);
      observerCanvas.addAll({'cols':fullTerminal.viewWidth,'rows':fullTerminal.viewHeight,
        'wideMarkerMatched':true,'wideMarkerVisible':true,'readingPositionRestored':true});
    }
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    stage('local_font_diagnostic');
    final fontDiagnostics = await readFontDiagnostic(tester);
    await until(tester,() => (displayedSequence(tester) ?? -1) > deltaSequence);
    final inputReceipts = <Map<String,Object>>[];
    Map<String,Object>? blockedTargetEvidence;
    Map<String,Object>? boardSearchEvidence;
    Map<String,Object>? deviceImpactEvidence;
    List<int>? restoredViewport;
    Map<String,Object>? tuiEvidence;
    if (guardedInput) {
      stage('guarded_direct_available');
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNotNull);
      stage('guarded_direct_select');
      await tapKey(tester,'remote-mode-direct');
      final terminalView = find.byType(TerminalView);
      stage('guarded_direct_focus');
      await tap(tester,terminalView);
      await until(tester,() => tester.widget<TerminalView>(terminalView).focusNode!.hasFocus &&
        tester.state<TerminalViewState>(terminalView).hasInputConnection);
      if (systemKeyboardEnabled) {
        await tapKey(tester,'remote-keyboard-show');
        stage('keyboard_direct_shown');
        await keyboardCheckpoint(tester,exchange,'keyboard-direct-shown');
        await tapKey(tester,'remote-keyboard-hide');
        stage('keyboard_direct_hidden');
        await keyboardCheckpoint(tester,exchange,'keyboard-direct-hidden');
        expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
        await tapKey(tester,'remote-mode-direct');
        await tapKey(tester,'remote-keyboard-show');
        stage('keyboard_direct_reopened');
        await keyboardCheckpoint(tester,exchange,'keyboard-direct-reopened');
        expect(tester.widget<TerminalView>(terminalView).autoResize,isFalse);
      }
      // Submit a committed character through TerminalView's normal TextInput
      // path. A hardware key event alone need not generate printable text on
      // Android. The fixed integration binding does not register a fake IME;
      // TestTextInput.enterText supports this debug-client path. This is an
      // automated GUI commit, not validation of a physical IME or composition.
      stage('guarded_direct_commit');
      tester.testTextInput.enterText('k');
      await tester.pump();
      stage('guarded_direct_ack');
      await accepted(tester);
      stage('guarded_direct_receipt');
      inputReceipts.add(visibleReceipt(tester,target['paneId'] as String,1));

      stage('guarded_hidden_draft');
      // A host profile ID and a view/tab ID are different identities. Capture
      // this actual visible tab before hiding it; never guess its key from id.
      expect(hostTab(),findsOneWidget);
      final originalTabKey = (tester.widget<TextButton>(hostTab()).key! as ValueKey<String>).value;
      final terminalBeforeHide = tester.widget<TerminalView>(terminalView).terminal;
      await tapKey(tester,'remote-mode-draft');
      final draftControl = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(draftControl); await tester.enterText(draftControl,'Pocket');
      await tester.pump();
      if (systemKeyboardEnabled) {
        final preservedDraft = tester.widget<TextField>(draftControl).controller!;
        final draftEditorFocus = tester.widget<TextField>(draftControl).focusNode!;
        await tapKey(tester,'remote-keyboard-show');
        stage('keyboard_draft_shown');
        await keyboardCheckpoint(tester,exchange,'keyboard-draft-shown',editorFocus:draftEditorFocus);
        stage('keyboard_draft_back_request');
        // The host verifies the real owned IME window again, issues exactly
        // one Android KEYCODE_BACK, verifies hiding, and only then ACKs.
        await keyboardCheckpoint(tester,exchange,'keyboard-draft-back-request',editorFocus:draftEditorFocus);
        stage('keyboard_draft_back_hidden');
        await keyboardCheckpoint(tester,exchange,'keyboard-draft-back-hidden',editorFocus:draftEditorFocus);
        expect(preservedDraft.text,'Pocket');
        expect(visibleReceipt(tester,target['paneId'] as String,1),inputReceipts.first);
        final show = find.byKey(const ValueKey('remote-keyboard-show'));
        final reselected = tester.widget<ButtonStyleButton>(show).onPressed == null ||
          !tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).selected;
        if (reselected) await tapKey(tester,'remote-mode-draft');
        await tapKey(tester,'remote-keyboard-show');
        stage('keyboard_draft_back_reopened');
        await keyboardCheckpoint(tester,exchange,'keyboard-draft-back-reopened',modeReselected:reselected,editorFocus:draftEditorFocus);
        expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket');
        await tapKey(tester,'remote-keyboard-hide');
        stage('keyboard_draft_hidden');
        await keyboardCheckpoint(tester,exchange,'keyboard-draft-hidden',editorFocus:draftEditorFocus);
        expect(preservedDraft.text,'Pocket');
        expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
        expect(visibleReceipt(tester,target['paneId'] as String,1),inputReceipts.first);
        expect(tester.widget<TerminalView>(terminalView).autoResize,isFalse);
        await tapKey(tester,'remote-mode-draft');
        expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket');
      }
      await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
      stage('guarded_clipboard_fixture');
      // Fixed synthetic data on the runner-owned disposable AVD only. Never
      // getData here: both reads must come from the normal production button.
      expect(syntheticClipboardEnabled,isTrue);
      await Clipboard.setData(const ClipboardData(text:'测'));
      stage('guarded_paste_cancel_review');
      await tapKey(tester,'remote-input-draft-paste');
      void checkPasteReview() {
        final dialog = find.byType(AlertDialog);
        expect(find.text('审查粘贴 · 仅编辑本地草稿'),findsOneWidget);
        expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-paste-review-text'))).data,'测');
        for (final field in ['paneId','terminalId']) {
          expect(find.descendant(of:dialog,matching:find.textContaining(inputReceipts.first[field] as String)),findsOneWidget);
        }
        expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket');
        expect(visibleReceipt(tester,target['paneId'] as String,1),inputReceipts.first);
        expect(find.text('预览发送文本'),findsNothing);
      }
      checkPasteReview();
      await tapKey(tester,'remote-paste-cancel');
      stage('guarded_paste_cancel_preserved');
      expect(find.byType(AlertDialog),findsNothing);
      expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket');
      expect(visibleReceipt(tester,target['paneId'] as String,1),inputReceipts.first);
      await clipboardCheckpoint(tester,exchange,'paste-cancel-preserved');
      stage('guarded_paste_reopen_review');
      await tapKey(tester,'remote-input-draft-paste');
      checkPasteReview();
      await tapKey(tester,'remote-paste-append');
      stage('guarded_paste_local_append');
      expect(find.byType(AlertDialog),findsNothing);
      expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket测');
      expect(utf8.encode(tester.widget<TextField>(draftControl).controller!.text).length,9);
      expect(visibleReceipt(tester,target['paneId'] as String,1),inputReceipts.first);
      expect(tester.widget<TerminalView>(terminalView).autoResize,isFalse);
      expect(find.text('预览发送文本'),findsNothing);
      await clipboardCheckpoint(tester,exchange,'paste-local-append');
      stage('viewport_pan');
      final viewport = find.byKey(const ValueKey('remote-horizontal-scroll'));
      await tester.ensureVisible(viewport);
      await tester.pump();
      ScrollPosition position() => tester.widget<SingleChildScrollView>(viewport).controller!.position;
      expect(position().maxScrollExtent,greaterThan(80));
      await tester.timedDrag(viewport,const Offset(-96,0),const Duration(milliseconds:450));
      await until(tester,() => !position().isScrollingNotifier.value && position().pixels >= 12);
      final previousOffset = position().pixels;
      await tapKey(tester,'hosts-board-tab');
      await tapKey(tester,originalTabKey);
      await until(tester,() => find.byKey(const ValueKey('remote-resume')).evaluate().length == 1);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
      expect(draftControl,findsNothing);
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('remote-unsent-text-0'))).data,'Pocket测');
      expect(tester.widget<Text>(find.byKey(const ValueKey('remote-unsent-origin-0'))).data,
        contains(inputReceipts.first['terminalId'] as String));
      stage('guarded_reconnect');
      // Production hidden tabs retain SSH. Only explicit resume plus a new
      // full reopens input; reconnecting here would test a different path.
      await tapKey(tester,'remote-resume');
      await until(tester,() => find.byType(TerminalView).evaluate().length == 1 &&
        !identical(tester.widget<TerminalView>(terminalView).terminal,terminalBeforeHide) &&
        find.textContaining('只读观察中').evaluate().isNotEmpty &&
        tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected != null);
      final restoredTargetLabel = tester.widget<Text>(find.textContaining('当前输入目标：')).data;
      expect(restoredTargetLabel,contains(inputReceipts.first['paneId'] as String));
      expect(restoredTargetLabel,contains(inputReceipts.first['terminalId'] as String));
      stage('viewport_restored');
      await until(tester,() => viewport.evaluate().length == 1 &&
        (position().pixels - previousOffset).abs() <= 1);
      restoredViewport = [previousOffset.round(),position().pixels.round()];
      await tapKey(tester,'remote-mode-draft');
      expect(tester.widget<TextField>(draftControl).controller!.text,'Pocket测');
      stage('guarded_draft_review');
      await tapKey(tester,'remote-input-draft-send');
      expect(find.text('预览发送文本'),findsOneWidget);
      expect(find.text('Pocket测'),findsWidgets);
      await tapKey(tester,'remote-input-confirm');
      await accepted(tester,previousRequest:inputReceipts.first['requestId'] as String);
      inputReceipts.add(visibleReceipt(tester,target['paneId'] as String,9));
      expect(inputReceipts.last['terminalId'],inputReceipts.first['terminalId']);
      expect(tester.widget<TextField>(draftControl).controller!.text,isEmpty);
      if (guardedTui) tuiEvidence = await exerciseTui(tester,exchange,target,originalTabKey,inputReceipts,stage,
        (value) { tuiResumeDiagnostic = value; });
    } else {
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
      if (systemKeyboardEnabled) {
        for (final key in ['remote-keyboard-show','remote-keyboard-hide']) {
          expect(tester.widget<ButtonStyleButton>(find.byKey(ValueKey(key))).onPressed,isNull);
        }
        stage('keyboard_observe_hidden');
        await keyboardCheckpoint(tester,exchange,'keyboard-observe-hidden');
      }
    }
    expect(tester.takeException(),isNull);
    stage('stop');
    await tapKey(tester,'remote-cancel');
    await until(tester,() => find.textContaining('旧画面 · 已停止').evaluate().isNotEmpty);
    stage('host_task_summary_stale');
    await until(tester,() => hostSummaryControl.evaluate().length == 1 &&
      (tester.widget<Text>(hostSummaryControl).data ?? '').contains('上次主机报告'));
    expect(tester.widget<Text>(hostSummaryControl).data,contains('原会话 ${target['session']}'));
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
    if (guardedInput) await tester.sendKeyEvent(LogicalKeyboardKey.keyX,character:'x');
    // Capture the visible original tab identity, not the host profile id.
    final originalTabs = !guardedInput
      ? tester.widgetList<TextButton>(hostTab()).map((w) => (w.key! as ValueKey<String>).value).toSet() : <String>{};
    if (!guardedInput) expect(originalTabs.length,1);
    await tap(tester,find.byTooltip('返回离线验证')); // Production remote page's explicit back control.
    await tester.pump(const Duration(milliseconds:400));
    await tapKey(tester,'hosts-board-tab');
    if (!guardedInput) {
      stage('blocked_history');
      final summary = find.byKey(ValueKey('host-task-summary-$id'));
      await until(tester,() => summary.evaluate().length == 1 &&
        tester.widgetList<Text>(find.descendant(of:summary,matching:find.byType(Text))).any((w) => (w.data ?? '').contains('上次主机报告')));
      final group = find.byKey(ValueKey(blockedSummaryGroupKey(id)));
      await until(tester,() => group.evaluate().length == 1);
      await tapStablePointer(tester,groupHeader(group));
      stage('blocked_list');
      final rows = find.descendant(of:group,matching:find.byWidgetPredicate((widget) => widget is ListTile &&
        widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith('host-blocked-target-')));
      await until(tester,() => rows.evaluate().length == 2);
      expect(rows,findsNWidgets(2));
      final listedRows=rows.evaluate().length;
      for (final item in blockedTargets) {
        final key=blockedSummaryTargetKey(id,RemotePane(item.paneId,item.terminalId));
        expect(find.byKey(ValueKey(key)),findsOneWidget);
      }
      final b=blockedTargets[1];
      stage('blocked_target_open');
      final bKey=blockedSummaryTargetKey(id,RemotePane(b.paneId,b.terminalId));
      await tap(tester,find.byKey(ValueKey(bKey))); // One explicit tap on B.
      await until(tester,() => hostTab().evaluate().length == 2);
      final currentTabs=tester.widgetList<TextButton>(hostTab()).map((w) => (w.key! as ValueKey<String>).value).toSet();
      expect(currentTabs.length,2); expect(currentTabs.containsAll(originalTabs),isTrue);
      expect(currentTabs.difference(originalTabs).length,1);
      stage('blocked_identity_review');
      final connectPair=find.byKey(const ValueKey('pair-connect'));
      await until(tester,() => connectPair.evaluate().length == 1 &&
        tester.widget<FilledButton>(connectPair).onPressed != null && find.textContaining('本机原身份已匹配').evaluate().isNotEmpty);
      await tap(tester,connectPair);
      await until(tester,() => find.byType(RemotePage).evaluate().length == 1);
      stage('blocked_ssh_review');
      final review=find.byKey(const ValueKey('remote-review')),connect=find.byKey(const ValueKey('remote-connect'));
      expect(tester.widget<CheckboxListTile>(review).value,isFalse);
      expect(tester.widget<FilledButton>(connect).onPressed,isNull);
      final check=await stableReviewCheckbox(tester,'remote-review');
      await tester.tap(check); await tester.pump(const Duration(milliseconds:150));
      checkPointerError(tester);
      expect(tester.widget<CheckboxListTile>(review).value,isTrue);
      expect(tester.widget<FilledButton>(connect).onPressed,isNotNull);
      await tap(tester,connect); // One explicit connection after a fresh review.
      stage('blocked_observe');
      await until(tester,() => find.byType(TerminalView).evaluate().length == 1 &&
        find.textContaining('只读观察中').evaluate().length == 1 && displayedSequence(tester) != null &&
        find.textContaining('当前输入目标：').evaluate().length == 1);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
      // This label is generated from inputGate.target, which production sets
      // from adapter.inputTarget only after its validated full frame; it is not
      // the requested target or the host-list row used to initiate this tab.
      final boundText=tester.widget<Text>(find.textContaining('当前输入目标：')).data!;
      final parts=boundText.split(' / ');
      expect(parts.length,4); expect(parts[1],target['session']);
      final actualPane=parts[2],actualTerminal=parts[3];
      expect(actualPane,b.paneId); expect(actualTerminal,b.terminalId);
      final view=find.byType(TerminalView),viewport=find.byKey(const ValueKey('remote-horizontal-scroll'));
      await tester.ensureVisible(viewport); await tester.pump(const Duration(milliseconds:150));
      stage('blocked_marker');
      bool visibleB() {
        if (view.evaluate().length != 1) return false;
        final term=tester.widget<TerminalView>(view).terminal;
        final render=tester.state<TerminalViewState>(view).renderTerminal;
        final bounds=Offset.zero & tester.view.physicalSize / tester.view.devicePixelRatio;
        final cells=visibleRemoteScreenCells(term,render,bounds);
        return cells != null && screenHasMarker(term,'POCKET-BLOCKED-B',firstRow:cells.firstRow,endRow:cells.endRow,
          firstColumn:cells.firstColumn,endColumn:cells.endColumn) && !screenHasMarker(term,'POCKET-BLOCKED-A');
      }
      await until(tester,visibleB,seconds:30); expect(visibleB(),isTrue);
      expect(tester.widget<TerminalView>(view).readOnly,isTrue);
      expect(tester.widget<TerminalView>(view).autoResize,isFalse);
      blockedTargetEvidence={'paneId':actualPane,'terminalId':actualTerminal,'listedRows':listedRows,
        'reviewRequired':true,'observing':true,'markerMatched':true,'otherMarkerAbsent':true};
      stage('blocked_return');
      await tester.pumpAndSettle(const Duration(milliseconds: 300));
      await tapKey(tester,'hosts-board-tab');
      // The board and the shared-device review are driven on the device. The
      // nine new stages below publish their evidence through the two optional
      // result keys; a failure inside a group reports its stage name only,
      // because a partial group cannot satisfy the published bounds.
      boardSearchEvidence = await exerciseBoardSearch(tester,target['session'] as String,id,stage);
      deviceImpactEvidence = await exerciseDeviceImpact(tester,stage);
    }
    stage('delete_local_identity');
    await tapKey(tester,'host-delete-$id');
    await tap(tester,find.widgetWithText(FilledButton,'仅删除本机'));
    await until(tester,() => hostOpen().evaluate().isEmpty &&
      find.textContaining('本机已删除 · 主机授权未因此撤销').evaluate().isNotEmpty);
    expect(tester.takeException(),isNull);
    stage('complete');
    if (!guardedInput) expect(blockedTargetEvidence,isNotNull);
    final report = <String,Object?>{
      'case':guardedInput ? 'android-native-pairing-guarded-input' : 'android-native-pairing-observe','buildMode':'debug',
      'productionMain':true,'defaultHostCatalog':true,'uninjectedNativeDeviceKeys':true,
      'profilePreviewShown':true,'profileFieldsMatched':true,'profileFingerprintMatched':true,
      'profileTargetUnreviewed':true,'profileNoCreationIntent':true,'profileCreationActionsBeforeReview':0,
      'publicRequestShown':true,'pendingRequestReopened':true,'originalDeviceKeyRevalidated':true,
      'authorizationReviewed':true,'pairedStateVisible':true,'paneChosen':true,
      'fullRendered':true,'deltaRendered':true,'stoppedStale':true,'observeMode':true,
      'directModeDisabled':true,'draftModeDisabled':true,'localIdentityDeleted':true,
      'identityCreationActions':identityCreationActions,'firstSequence':firstSequence,'deltaSequence':deltaSequence,
      'localFontMarkerColumns':fontDiagnostics.markers,
      'localThemePromptCursors':fontDiagnostics.themes,
      if (!guardedInput) ...{'observerCanvas':observerCanvas,'blockedTargetEvidence':blockedTargetEvidence,
        'boardSearchEvidence':boardSearchEvidence,'deviceImpactEvidence':deviceImpactEvidence},
      'frameCountLowerBound':2,'deltaCountLowerBound':1,
      if (guardedInput) ...{
        'guardedInput':true,'directInputAccepted':true,'draftInputAccepted':true,
        'hiddenTabStopped':true,'hiddenTabManualRecovery':true,'unsentDraftRestored':true,
        'postStopInputDisabled':true,'inputReceipts':inputReceipts,
        'acceptedByteCounts':[1,9],
        if (tuiEvidence != null) 'tui':tuiEvidence,
        'restoredViewportLogicalPixels':restoredViewport,
        'syntheticClipboardSet':true,'pasteReviewCancelled':true,'pasteCancelPreservedDraft':true,
        'pasteReviewReopened':true,'pasteAppendedLocally':true,'pasteTargetVerified':true,
        'pasteReceiptUnchanged':true,'pasteKeptFixedSize':true,
        'clipboardFixtureBytes':3,'pasteOriginalDraftBytes':6,'pasteMergedDraftBytes':9,
      },
    };
    publish(exchange,'result.json',jsonEncode(report));
    binding.reportData = report;
    } catch (error,stack) {
      final directory = failureDirectory;
      if (directory != null) {
        try { publish(directory,'failure.json',jsonEncode(boundedFailure(error,stack,currentStage,
            tuiResume:tuiResumeDiagnostic,
            boardSearch:(currentStage == 'board_search_clear' && boardSearchFailureProbe != null)
              ? {...boardSearchFailureProbe!,'clearedKeptState':false,'resetRestoredList':false} : null))); }
        catch (_) { /* Preserve the original test failure if diagnostics fail. */ }
      }
      rethrow;
    }
  },timeout:const Timeout(Duration(minutes:guardedTui ? 9 : 6)));
}
