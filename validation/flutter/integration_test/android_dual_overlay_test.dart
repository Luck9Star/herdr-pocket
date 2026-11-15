import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/main.dart' as app;

import 'android_pairing_observe_test.dart' as existing;
import 'dual_overlay_ui_steps.dart';

const enabled = bool.fromEnvironment('HERDR_ANDROID_DUAL_OVERLAY');
const runId = String.fromEnvironment('HERDR_ANDROID_DUAL_RUN_ID');
const firstStop = String.fromEnvironment('HERDR_ANDROID_DUAL_FIRST_STOP');
const exchangePath = '/data/user/0/dev.herdr.herdr_flutter_probe/files/dual-overlay-exchange';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('two reviewed herdr targets retain provider boundaries on Android', (tester) async {
    if (!kDebugMode || !Platform.isAndroid || !enabled ||
        !RegExp(r'^[0-9]{1,20}$').hasMatch(runId) || !{'et', 'ts'}.contains(firstStop)) {
      throw StateError('dual_device_fixture_required');
    }
    final exchange = Directory(exchangePath);
    final configFile = File('${exchange.path}/config.json');
    await existing.until(tester, configFile.existsSync, seconds: 90);
    final dynamic decoded = jsonDecode(configFile.readAsStringSync());
    if (decoded is! Map<String, dynamic> || decoded['runId'] != runId || decoded['firstStop'] != firstStop) {
      throw StateError('dual_device_config_invalid');
    }
    String value(String key) {
      final result = decoded[key];
      if (result is! String || result.isEmpty || utf8.encode(result).length > 65536) {
        throw StateError('dual_device_config_invalid');
      }
      return result;
    }
    final steps = DualOverlayUiSteps(tester, exchange);
    await steps.stage('host_board');
    await app.main();
    await existing.until(tester, () => find.byType(HostCatalogPage).evaluate().length == 1 &&
      find.byKey(const ValueKey('hosts-add')).evaluate().length == 1);
    final home = tester.widget<HostCatalogPage>(find.byType(HostCatalogPage));
    expect(home.catalog, isNull); expect(home.keys, isNull); expect(home.adapterFactory, isNull);
    await steps.navigation(2);
    final etNetwork = await steps.createNetwork(role: 'et', label: 'QA EasyTier', controlUrl: '',
      networkName: value('networkName'), peerUrl: value('peerUrl'), networkSecret: value('networkSecret'));
    final tsNetwork = await steps.createNetwork(role: 'ts', label: 'QA Tailscale', controlUrl: value('controlUrl'),
      networkName: '', peerUrl: '', networkSecret: '');
    await steps.authorizeTailscale(tsNetwork);
    await steps.navigation(0);
    final etHost = await steps.pairHost('et', value('etProfile'));
    await tester.pageBack(); await tester.pump();
    await steps.bindHost(etHost, etNetwork, 'QA EasyTier', 'easytier');
    final tsHost = await steps.pairHost('ts', value('tsProfile'));
    await tester.pageBack(); await tester.pump();
    await steps.bindHost(tsHost, tsNetwork, 'QA Tailscale', 'tailscale');

    final etTab = await steps.openAndObserve('et', etHost);
    await steps.commitCharacter('et', 'E');
    final etPrevious = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    await steps.stage('et_baseline');
    expect(await steps.awaitFile('et-audit.txt'), 'accepted');
    await steps.navigation(0);
    final tsTab = await steps.openAndObserve('ts', tsHost);
    await steps.commitCharacter('ts', 'T');
    await steps.stage('ts_baseline');
    expect(await steps.awaitFile('ts-audit.txt'), 'accepted');

    final survivor = firstStop == 'et' ? 'ts' : 'et';
    final survivorTab = survivor == 'et' ? etTab : tsTab;
    if (survivor == 'et') await steps.resumeTab('et', etTab, etPrevious);
    final beforeNetworkPage = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    await steps.stopNetwork(firstStop, firstStop == 'et' ? etNetwork : tsNetwork);
    await steps.stage('stopped_audit');
    expect(await steps.awaitFile('stopped-audit.txt'), 'accepted');
    await steps.navigation(1);
    expect(find.byKey(ValueKey(firstStop == 'et' ? etTab : tsTab)), findsNothing);
    await steps.resumeTab(survivor, survivorTab, beforeNetworkPage);
    await steps.commitCharacter(survivor, survivor == 'et' ? 'e' : 't');
    await steps.stage('final_audit');
    expect(await steps.awaitFile('final-audit.txt'), 'accepted');
    final result = {'status': 'passed', 'firstStop': firstStop,
      'twoReviewedTargets': true, 'observedBothUpdates': true, 'responseMarkersMatched': true,
      'explicitTsAuthorization': true,
      'newFullAfterResume': true, 'stoppedTabRetired': true,
      'initialInputsAccepted': true, 'survivorInputAccepted': true};
    existing.publish(exchange, 'result.json', jsonEncode(result));
    binding.reportData = result;
  });
}
