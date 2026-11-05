import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
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

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Android native identity through production host catalog to read-only SSH observe',(tester) async {
    final target = checkedTarget();
    final exchange = Directory(publicDirectory);
    if (exchange.existsSync()) throw StateError('android_public_exchange_already_exists');
    exchange.createSync(recursive:true);
    void stage(String name) => publish(exchange,'stage',name);
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
    await tapKey(tester,'pair-create'); // The only create action uses native AndroidKeyStore.
    final requestControl = find.byKey(const ValueKey('pair-request'));
    await until(tester,() => requestControl.evaluate().length == 1);
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
    stage('response_review');
    final responseControl = find.byKey(const ValueKey('pair-response'));
    await tester.ensureVisible(responseControl); await tester.enterText(responseControl,response); await tester.pump();
    expect(find.byKey(const ValueKey('pair-response-preview')),findsOneWidget);
    await tapKey(tester,'pair-source-review'); await tapKey(tester,'pair-accept');
    await until(tester,() => find.textContaining('authorized-unverified').evaluate().isNotEmpty);
    await tapKey(tester,'pair-connect');
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
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-direct'))).onSelected,isNull);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-draft'))).onSelected,isNull);
    expect(tester.takeException(),isNull);
    stage('stop');
    await tapKey(tester,'remote-cancel');
    await until(tester,() => find.textContaining('旧画面 · 已停止').evaluate().isNotEmpty);
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
      'case':'android-native-pairing-observe','buildMode':'debug',
      'productionMain':true,'defaultHostCatalog':true,'uninjectedNativeDeviceKeys':true,
      'publicRequestShown':true,'pendingRequestReopened':true,'originalDeviceKeyRevalidated':true,
      'authorizationReviewed':true,'pairedStateVisible':true,'paneChosen':true,
      'fullRendered':true,'deltaRendered':true,'stoppedStale':true,'observeMode':true,
      'directModeDisabled':true,'draftModeDisabled':true,'localIdentityDeleted':true,
      'identityCreationActions':1,'firstSequence':firstSequence,'deltaSequence':deltaSequence,
      'frameCountLowerBound':2,'deltaCountLowerBound':1,
    };
    publish(exchange,'result.json',jsonEncode(report));
    binding.reportData = report;
  },timeout:const Timeout(Duration(minutes:6)));
}
