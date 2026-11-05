import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_input.dart';
import 'pairing_gui_test.dart' as helpers;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

/// Explicit public-marker memory double, never a production fallback. This
/// exercises the production adapter's prepare/clear ordering and exact-record
/// matching; it does not establish file durability or native storage behavior.
class GuiSshMemoryInputJournal implements RemoteInputJournal {
  String? marker, lastPrepared;
  int reads = 0, prepares = 0, clears = 0;
  @override
  Future<String?> read() async { reads++; return marker; }
  @override
  Future<void> prepare(String record) async {
    RemoteInputPending.parse(record);
    if (marker != null) throw StateError('test journal is not empty');
    prepares++; marker = record; lastPrepared = record;
  }
  @override
  Future<void> clear(String record) async {
    RemoteInputPending.parse(record);
    if (marker != record) throw StateError('test journal record mismatch');
    clears++; marker = null;
  }
}

/// Opt-in only: helper authorizes the public request after the real widget emits
/// it. PEM lives exclusively in this explicit test signer; production has no
/// PEM-to-device-key import. No production Keychain/Keystore claim is made.
void main() {
  final env = Platform.environment;
  final expectInput = env['HERDR_PAIRING_GUI_EXPECT_INPUT'] == '1';
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);
  testWidgets(expectInput ? 'isolated real SSH GUI pairing, observe and guarded draft input'
    : 'isolated real SSH GUI pairing and continuous observe',(tester) async {
    final config = jsonDecode(File(env['HERDR_PAIRING_GUI_CONFIG']!).readAsStringSync()) as Map<String,dynamic>;
    final dir = Directory(env['HERDR_PAIRING_GUI_DIR']!);
    final keys = helpers.TestDeviceKeys(File(env['HERDR_PAIRING_GUI_TEST_KEY']!).readAsStringSync());
    final inputJournal = GuiSshMemoryInputJournal();
    final adapter = RemoteReadOnlyAdapter(inputJournal:inputJournal);
    final catalog = HostCatalog(storage:MemoryCatalogStorage());
    addTearDown(catalog.dispose);
    void stage(String name) => File('${dir.path}/stage').writeAsStringSync(name,flush:true);
    final tokens = (await tester.runAsync(DesignTokens.load))!;
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(390,844);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    Future<void> until(bool Function() predicate) async {
      final deadline = DateTime.now().add(const Duration(seconds:25));
      while (!predicate()) {
        if (DateTime.now().isAfter(deadline)) fail('isolated GUI phase timeout');
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds:50)));
        await tester.pump();
      }
    }
    stage('host_board');
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:HostCatalogPage(tokens:tokens,
      catalog:catalog,keys:keys,adapterFactory:(_) => adapter,offlineBuilder:(_) => const SizedBox())));
    await tester.pumpAndSettle();
    await helpers.tapVisible(tester,'hosts-add'); await tester.pumpAndSettle();
    stage('public_request');
    await helpers.fillPairTarget(tester,config);
    await helpers.tapVisible(tester,'pair-target-review'); await helpers.tapVisible(tester,'pair-create');
    final wire = find.byKey(const ValueKey('pair-request'));
    await until(() => wire.evaluate().isNotEmpty && catalog.profiles.length == 1);
    final temp = File('${dir.path}/request.json.new');
    temp.writeAsStringSync(tester.widget<SelectableText>(wire).data!,flush:true);
    temp.renameSync('${dir.path}/request.json');
    stage('host_authorization');
    await until(() => File('${dir.path}/response.json').existsSync());
    final response = jsonDecode(File('${dir.path}/response.json').readAsStringSync()) as Map<String,dynamic>;
    final id = catalog.profiles.single.id;
    // Return to the ordinary board while authorization is pending. Reopening
    // must recover the same request/key and cannot start SSH or issue a new key.
    await tester.pageBack(); await tester.pumpAndSettle();
    stage('restore_pending');
    await helpers.tapVisible(tester,'host-open-$id'); await tester.pumpAndSettle();
    expect(find.textContaining('awaiting-host'),findsOneWidget);
    expect(keys.creates,1); expect(keys.signCalls,0);
    expect(tester.widget<SelectableText>(wire).data,File('${dir.path}/request.json').readAsStringSync());
    stage('response_review');
    await helpers.acceptResponse(tester,response);
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    await helpers.tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    stage('ssh_and_dashboard');
    await helpers.tapVisible(tester,'remote-review'); await helpers.tapVisible(tester,'remote-connect');
    final pane = 'remote-pane-${config['paneId']}';
    await until(() => find.byKey(ValueKey(pane)).evaluate().isNotEmpty);
    expect(adapter.evidence.hostKeyMatched,isTrue); expect(adapter.evidence.authStarted,isTrue);
    expect(keys.signCalls,greaterThan(0));
    expect(find.textContaining('状态 paired',skipOffstage:false),findsOneWidget);
    stage('observe_frames');
    await helpers.tapVisible(tester,pane);
    await until(() => adapter.evidence.frameCount >= 1 && find.textContaining('只读观察中').evaluate().isNotEmpty);
    expect(find.byType(TerminalView),findsOneWidget);
    expect(tester.takeException(),isNull);
    final firstSeq = adapter.evidence.lastSeq;
    await until(() => adapter.evidence.deltaFrames >= 1 && adapter.evidence.lastSeq != firstSeq);
    expect(find.textContaining('seq ${adapter.evidence.lastSeq}'),findsOneWidget);
    var inputQueueAccepted = false;
    final draftMode = find.byKey(const ValueKey('remote-mode-draft'));
    final directMode = find.byKey(const ValueKey('remote-mode-direct'));
    if (expectInput) {
      stage('guarded_input');
      // The opt-in branch requires the real guarded-server capability. A stock
      // server or a missing capability must fail this branch, never downgrade.
      expect(adapter.inputCapability,isNotNull);
      expect(adapter.inputTarget,isNotNull);
      expect(tester.widget<ChoiceChip>(draftMode).onSelected,isNotNull);
      expect(tester.widget<ChoiceChip>(directMode).onSelected,isNotNull);
      expect(inputJournal.reads,1);
      await helpers.tapVisible(tester,'remote-mode-draft');
      final draft = find.byKey(const ValueKey('remote-input-draft'));
      await tester.ensureVisible(draft);
      await tester.enterText(draft,'Pocket测'); await tester.pump();
      expect(inputJournal.prepares,0); // Editing is local; no write without confirmation.
      await helpers.tapVisible(tester,'remote-input-draft-send');
      expect(find.text('预览发送文本'),findsOneWidget);
      final preview = find.descendant(of:find.byType(AlertDialog),matching:find.byType(SelectableText));
      expect(preview,findsOneWidget); expect(tester.widget<SelectableText>(preview).data,'Pocket测');
      expect(inputJournal.prepares,0);
      await helpers.tapVisible(tester,'remote-input-confirm');
      await until(() {
        final status = find.byKey(const ValueKey('remote-input-status'));
        return status.evaluate().isNotEmpty && tester.widget<Text>(status).data ==
          '服务端已接收 · 仅确认队列受理，请查看终端反馈';
      });
      expect(inputJournal.prepares,1); expect(inputJournal.clears,1);
      expect(inputJournal.marker,isNull);
      final marker = RemoteInputPending.parse(inputJournal.lastPrepared!);
      expect(marker.target.paneId,config['paneId']);
      expect(marker.target.terminalId,adapter.inputTarget!.terminalId);
      expect(marker.target.generation,adapter.generation);
      expect(tester.widget<TextField>(draft).controller!.text,isEmpty);
      expect(find.textContaining('发送结果待核实'),findsNothing);
      // The GUI sends only the preview text. The runner independently checks
      // raw PTY bytes equal utf8.encode('Pocket测'), including no appended CR/LF.
      inputQueueAccepted = true;
    } else {
      // Preserve and strengthen the original stock read-only case, even with
      // a functional test journal present: server capability is mandatory.
      expect(adapter.inputCapability,isNull);
      expect(tester.widget<ChoiceChip>(draftMode).onSelected,isNull);
      expect(tester.widget<ChoiceChip>(directMode).onSelected,isNull);
      expect(inputJournal.reads,0); expect(inputJournal.prepares,0); expect(inputJournal.clears,0);
      expect(inputJournal.marker,isNull);
    }
    expect(tester.takeException(),isNull);
    stage('stop');
    await helpers.tapVisible(tester,'remote-cancel'); await tester.pump();
    expect(find.textContaining('旧画面 · 已停止'),findsOneWidget);
    expect(adapter.evidence.connectionCount,1);
    final report = {'paired':adapter.evidence.hostKeyMatched && adapter.evidence.authStarted,
      'paneChosen':true,'fullRendered':true,'deltaRendered':true,'stoppedStale':true,'signCalls':keys.signCalls,
      'reopenedPendingRequest':true,'identityCreations':keys.creates,
      'frameCount':adapter.evidence.frameCount,'deltaFrames':adapter.evidence.deltaFrames,
      'connectionCount':adapter.evidence.connectionCount,
      'inputRequested':expectInput,'inputQueueAccepted':inputQueueAccepted,
      'stockReadOnlyConfirmed':!expectInput,'inputExpectedBytes':expectInput ? utf8.encode('Pocket测').length : 0,
      'inputJournal':{'backend':'explicit public-marker memory test double','reads':inputJournal.reads,
        'prepares':inputJournal.prepares,'clears':inputJournal.clears,'pending':inputJournal.marker != null},
      'scope':'real widget and isolated SSH; explicit memory test signer and public-marker journal double; '
        'system storage and journal durability NOT RUN; input acknowledgement means runtime queue acceptance, '
        'raw PTY bytes are checked separately by the runner'};
    File('${dir.path}/result.json').writeAsStringSync(jsonEncode(report),flush:true);
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(adapter.cancel);
  },skip:!env.containsKey('HERDR_PAIRING_GUI_CONFIG'),timeout:const Timeout(Duration(minutes:2)));
}
