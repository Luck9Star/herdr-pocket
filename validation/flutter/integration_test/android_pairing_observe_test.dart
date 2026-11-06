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
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_page.dart';

const packageName = 'dev.herdr.herdr_flutter_probe';
const fixtureEnabled = String.fromEnvironment('HERDR_ANDROID_NATIVE_PAIRING');
const runId = String.fromEnvironment('HERDR_ANDROID_RUN_ID');
const publicTarget = String.fromEnvironment('HERDR_ANDROID_TARGET_JSON');
const publicDirectory = String.fromEnvironment('HERDR_ANDROID_PUBLIC_DIR');
const guardedInput = bool.fromEnvironment('POCKET_GUARDED_INPUT');

/// Only public fixture target/request/response and typed evidence cross these
/// files. No injected DeviceKeys, catalog, adapter, frame or MethodChannel mock.
Map<String,dynamic> checkedTarget() {
  if (!Platform.isAndroid || !kDebugMode || fixtureEnabled != '1' ||
      !RegExp(r'^[0-9]+$').hasMatch(runId) || utf8.encode(publicTarget).length > 8192 ||
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
  return value;
}

Future<void> until(WidgetTester tester, bool Function() ready, {int seconds = 60}) async {
  final deadline = DateTime.now().add(Duration(seconds:seconds));
  while (!ready()) {
    if (DateTime.now().isAfter(deadline)) fail('android_public_ui_phase_timeout');
    await tester.pump(const Duration(milliseconds:100));
  }
}
Future<void> tap(WidgetTester tester, Finder finder) async {
  await until(tester,() => finder.evaluate().length == 1);
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds:150));
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds:350));
}
Future<void> tapKey(WidgetTester tester, String key) => tap(tester,find.byKey(ValueKey(key)));
/// Observe the real view after the editor's done action. Do not override view
/// metrics, assign review state, or retry the consent tap if it is not checked.
Future<Finder> sourceReviewCheckbox(WidgetTester tester) async {
  final tile = find.byKey(const ValueKey('pair-source-review'));
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
int? displayedSequence(WidgetTester tester) {
  final labels = tester.widgetList<Text>(find.byType(Text)).where((text) =>
    text.data?.contains('固定 80×24') == true && text.data?.contains(' · seq ') == true).toList();
  if (labels.length != 1) return null;
  final match = RegExp(r' · seq ([0-9]+)\n').firstMatch(labels.single.data!);
  return match == null ? null : int.tryParse(match.group(1)!);
}
void publish(Directory dir, String name, String text) {
  final pending = File('${dir.path}/$name.new');
  pending.writeAsStringSync(text,flush:true); pending.renameSync('${dir.path}/$name');
}

Map<String,Object> boundedFailure(Object error,StackTrace stack,String stage) {
  const classes = {'TestFailure','StateError','RemoteFailure','FormatException','TimeoutException'};
  final name = error.runtimeType.toString();
  final errorClass = error is TypeError ? 'TypeError' : classes.contains(name) ? name : 'other';
  final match = RegExp(r'android_pairing_observe_test\.dart:([0-9]+)(?::[0-9]+)?').firstMatch(stack.toString());
  final parsed = match == null ? 0 : int.tryParse(match.group(1)!) ?? 0;
  return {'stage':stage,'errorClass':errorClass,'line':parsed >= 1 && parsed <= 10000 ? parsed : 0};
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
    try {
    final target = checkedTarget();
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
    for (final name in ['host','port','username','session','socketPath','herdrPath','expectedHostKey']) {
      final field = find.byKey(ValueKey('pair-$name'));
      await tester.ensureVisible(field);
      await tester.enterText(field,target[name].toString()); await tester.pump();
    }
    await tapKey(tester,'pair-target-review');
    final createButton = tester.widget<FilledButton>(find.byKey(const ValueKey('pair-create')));
    if (createButton.onPressed == null) { stage('create_not_available'); fail('create_not_available'); }
    await tapKey(tester,'pair-create'); // The only create action uses native AndroidKeyStore.
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
    final sourceCheckbox = await sourceReviewCheckbox(tester);
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
    stage('ssh_and_dashboard');
    await tapKey(tester,'remote-review'); await tapKey(tester,'remote-connect');
    final pane = find.byKey(ValueKey('remote-pane-${target['paneId']}'));
    await until(tester,() => pane.evaluate().length == 1);
    expect(find.textContaining('状态 paired',skipOffstage:false),findsOneWidget);
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
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
    final inputReceipts = <Map<String,Object>>[];
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
      await tapKey(tester,'remote-mode-draft');
      final draftControl = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(draftControl); await tester.enterText(draftControl,'Pocket测');
      await tester.pump();
      await tapKey(tester,'hosts-board-tab');
      await tapKey(tester,'host-tab-$id');
      expect(find.textContaining('请主动审查连接并取得新 full'),findsOneWidget);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected,isTrue);
      stage('guarded_reconnect');
      await tapKey(tester,'remote-review'); await tapKey(tester,'remote-connect');
      await until(tester,() => pane.evaluate().length == 1 &&
        tester.widget<FilledButton>(pane).onPressed != null);
      await tap(tester,pane);
      await until(tester,() => find.textContaining('只读观察中').evaluate().isNotEmpty &&
        tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected != null);
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
    } else {
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
    }
    expect(tester.takeException(),isNull);
    stage('stop');
    await tapKey(tester,'remote-cancel');
    await until(tester,() => find.textContaining('旧画面 · 已停止').evaluate().isNotEmpty);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
    if (guardedInput) await tester.sendKeyEvent(LogicalKeyboardKey.keyX,character:'x');
    await tap(tester,find.byTooltip('返回离线验证')); // Production remote page's explicit back control.
    await tester.pump(const Duration(milliseconds:400));
    await tapKey(tester,'hosts-board-tab');
    stage('delete_local_identity');
    await tapKey(tester,'host-delete-$id');
    await tap(tester,find.widgetWithText(FilledButton,'仅删除本机'));
    await until(tester,() => hostOpen().evaluate().isEmpty &&
      find.textContaining('本机已删除 · 主机授权未因此撤销').evaluate().isNotEmpty);
    expect(tester.takeException(),isNull);
    stage('complete');
    final report = <String,Object?>{
      'case':guardedInput ? 'android-native-pairing-guarded-input' : 'android-native-pairing-observe','buildMode':'debug',
      'productionMain':true,'defaultHostCatalog':true,'uninjectedNativeDeviceKeys':true,
      'publicRequestShown':true,'pendingRequestReopened':true,'originalDeviceKeyRevalidated':true,
      'authorizationReviewed':true,'pairedStateVisible':true,'paneChosen':true,
      'fullRendered':true,'deltaRendered':true,'stoppedStale':true,'observeMode':true,
      'directModeDisabled':true,'draftModeDisabled':true,'localIdentityDeleted':true,
      'identityCreationActions':1,'firstSequence':firstSequence,'deltaSequence':deltaSequence,
      'frameCountLowerBound':2,'deltaCountLowerBound':1,
      if (guardedInput) ...{
        'guardedInput':true,'directInputAccepted':true,'draftInputAccepted':true,
        'hiddenTabStopped':true,'hiddenTabManualRecovery':true,'unsentDraftRestored':true,
        'postStopInputDisabled':true,'inputReceipts':inputReceipts,
        'acceptedByteCounts':[1,9],
      },
    };
    publish(exchange,'result.json',jsonEncode(report));
    binding.reportData = report;
    } catch (error,stack) {
      final directory = failureDirectory;
      if (directory != null) {
        try { publish(directory,'failure.json',jsonEncode(boundedFailure(error,stack,currentStage))); }
        catch (_) { /* Preserve the original test failure if diagnostics fail. */ }
      }
      rethrow;
    }
  },timeout:const Timeout(Duration(minutes:6)));
}
