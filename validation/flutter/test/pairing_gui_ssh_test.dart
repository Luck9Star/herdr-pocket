import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'pairing_gui_test.dart' as helpers;

/// Opt-in only: helper authorizes the public request after the real widget emits
/// it. PEM lives exclusively in this explicit test signer; production has no
/// PEM-to-device-key import. No production Keychain/Keystore claim is made.
void main() {
  final env = Platform.environment;
  setUp(PairingPage.resetMemorySession);
  tearDown(PairingPage.resetMemorySession);
  testWidgets('isolated real SSH GUI pairing and continuous observe',(tester) async {
    final config = jsonDecode(File(env['HERDR_PAIRING_GUI_CONFIG']!).readAsStringSync()) as Map<String,dynamic>;
    final dir = Directory(env['HERDR_PAIRING_GUI_DIR']!);
    final keys = helpers.TestDeviceKeys(File(env['HERDR_PAIRING_GUI_TEST_KEY']!).readAsStringSync());
    final adapter = RemoteReadOnlyAdapter();
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
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:PairingPage(tokens:tokens,keys:keys,adapter:adapter,
      onRequest:(request) {
        final temp = File('${dir.path}/request.json.new');
        temp.writeAsStringSync(jsonEncode(request),flush:true); temp.renameSync('${dir.path}/request.json');
      })));
    await helpers.fillPairTarget(tester,config);
    await helpers.tapVisible(tester,'pair-target-review'); await helpers.tapVisible(tester,'pair-create');
    await until(() => File('${dir.path}/response.json').existsSync());
    final response = jsonDecode(File('${dir.path}/response.json').readAsStringSync()) as Map<String,dynamic>;
    await helpers.acceptResponse(tester,response);
    expect(find.textContaining('authorized-unverified'),findsOneWidget);
    await helpers.tapVisible(tester,'pair-connect'); await tester.pumpAndSettle();
    await helpers.tapVisible(tester,'remote-review'); await helpers.tapVisible(tester,'remote-connect');
    final pane = 'remote-pane-${config['paneId']}';
    await until(() => find.byKey(ValueKey(pane)).evaluate().isNotEmpty);
    expect(adapter.evidence.hostKeyMatched,isTrue); expect(adapter.evidence.authStarted,isTrue);
    expect(keys.signCalls,greaterThan(0));
    await helpers.tapVisible(tester,pane);
    await until(() => adapter.evidence.frameCount >= 1 && find.textContaining('只读观察中').evaluate().isNotEmpty);
    final firstSeq = adapter.evidence.lastSeq;
    await until(() => adapter.evidence.deltaFrames >= 1 && adapter.evidence.lastSeq != firstSeq);
    expect(find.textContaining('seq ${adapter.evidence.lastSeq}'),findsOneWidget);
    await helpers.tapVisible(tester,'remote-cancel'); await tester.pump();
    expect(find.textContaining('旧画面 · 已停止'),findsOneWidget);
    expect(adapter.evidence.connectionCount,1);
    final report = {'paired':adapter.evidence.hostKeyMatched && adapter.evidence.authStarted,
      'paneChosen':true,'fullRendered':true,'deltaRendered':true,'stoppedStale':true,'signCalls':keys.signCalls,
      'frameCount':adapter.evidence.frameCount,'deltaFrames':adapter.evidence.deltaFrames,
      'connectionCount':adapter.evidence.connectionCount,'scope':'real widget and isolated SSH; explicit memory test signer; system storage NOT RUN'};
    File('${dir.path}/result.json').writeAsStringSync(jsonEncode(report),flush:true);
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(adapter.cancel);
  },skip:!env.containsKey('HERDR_PAIRING_GUI_CONFIG'),timeout:const Timeout(Duration(minutes:2)));
}
