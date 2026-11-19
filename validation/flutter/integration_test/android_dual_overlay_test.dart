import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'package:herdr_flutter_probe/main.dart' as app;

import 'android_pairing_observe_test.dart' as existing;
import 'dual_overlay_ui_steps.dart';

const enabled = bool.fromEnvironment('HERDR_ANDROID_DUAL_OVERLAY');
const runId = String.fromEnvironment('HERDR_ANDROID_DUAL_RUN_ID');
const firstStop = String.fromEnvironment('HERDR_ANDROID_DUAL_FIRST_STOP');
const sharedEasyTier = bool.fromEnvironment('HERDR_ANDROID_SHARED_EASYTIER');
const exchangePath = '/data/user/0/dev.herdr.herdr_flutter_probe/files/dual-overlay-exchange';

List<Map<String, Object>> safeFailureFrames(StackTrace stack) {
  final frames = <Map<String, Object>>[];
  final pattern = RegExp(r'(?:^|[/\\( ])(dual_overlay_ui_steps\.dart|android_dual_overlay_test\.dart|android_pairing_observe_test\.dart):(\d{1,6})(?::\d+)?');
  for (final line in stack.toString().split('\n')) {
    final match = pattern.firstMatch(line);
    if (match == null) continue;
    final number = int.parse(match.group(2)!);
    if (number < 1) continue;
    final frame = <String, Object>{'file': match.group(1)!, 'line': number};
    if (!frames.any((item) => item['file'] == frame['file'] && item['line'] == number)) frames.add(frame);
    if (frames.length == 6) break;
  }
  return frames;
}

Future<Map<String, Object>> observeSharedEasyTier(
  DualOverlayUiSteps steps, String networkId, String aProfile, String bProfile,
) async {
  final tester = steps.tester;
  final networks = tester.widget<NetworkProfilesPage>(find.byType(NetworkProfilesPage));
  final profile = networks.catalog.networkProfiles.single;
  expect(profile.id, networkId);
  expect(profile.provider, 'easytier');
  const runtime = NativeNetworkRuntime();
  final started = await runtime.profileStatus(profile);
  expect(started.state, 'engine-started');
  final originalBinding = started.binding!;
  await steps.navigation(0);
  final aHost = await steps.pairHost('et', aProfile);
  await tester.pageBack(); await tester.pump();
  await steps.bindHost(aHost, networkId, 'QA EasyTier', 'easytier');
  final bHost = await steps.pairHost('ts', bProfile, provider: 'easytier');
  await tester.pageBack(); await tester.pump();
  expect(bHost, isNot(aHost));
  await steps.bindHost(bHost, networkId, 'QA EasyTier', 'easytier');

  final aTab = await steps.openAndObserve('et', aHost);
  await steps.navigation(0);
  final bTab = await steps.openAndObserve('ts', bHost);
  expect(aTab, isNot(bTab));
  final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
  await steps.stage('shared_ready');
  expect(await steps.awaitFile('shared-ready.txt'), 'accepted');
  await steps.stage('shared_close_a');
  await steps.closeHostTab(aTab);
  final afterCloseSequence = existing.displayedSequence(tester);
  expect(afterCloseSequence, isNotNull);
  await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
    identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, terminal) &&
    (existing.displayedSequence(tester) ?? -1) > afterCloseSequence!);
  expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
  final afterA = await runtime.profileStatus(profile);
  expect(afterA.state, 'engine-started');
  expect(afterA.binding?.same(originalBinding), isTrue);
  await steps.stage('shared_a_released');
  expect(await steps.awaitFile('shared-a-released.txt'), 'accepted');

  await steps.stage('shared_close_b');
  await steps.closeHostTab(bTab);
  final afterB = await runtime.profileStatus(profile);
  expect(afterB.state, 'engine-started');
  expect(afterB.binding?.same(originalBinding), isTrue);
  await steps.stage('shared_b_released');
  expect(await steps.awaitFile('shared-b-released.txt'), 'accepted');
  await steps.stopNetwork('et', networkId);
  final stopped = await runtime.profileStatus(profile);
  expect(stopped.state, 'stopped');
  expect(stopped.binding, isNull);
  await steps.stage('shared_node_stopped');
  expect(await steps.awaitFile('shared-node-stopped.txt'), 'accepted');
  return {'status': 'passed', 'scenario': 'shared-easytier', 'sameReviewedBinding': true,
    'bothInitialFrames': true, 'survivorAdvancedOnOriginalView': true,
    'noAutomaticInput': true, 'bothTabsClosedBeforeNodeStop': true, 'nodeExplicitlyStopped': true};
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('two reviewed herdr targets retain provider boundaries on Android', (tester) async {
    if (!kDebugMode || !Platform.isAndroid || !enabled ||
        !RegExp(r'^[0-9]{1,20}$').hasMatch(runId) ||
        (sharedEasyTier ? firstStop.isNotEmpty : !{'et', 'ts'}.contains(firstStop))) {
      throw StateError('dual_device_fixture_required');
    }
    final exchange = Directory(exchangePath);
    final configFile = File('${exchange.path}/config.json');
    await existing.until(tester, configFile.existsSync, seconds: 90);
    final dynamic decoded = jsonDecode(configFile.readAsStringSync());
    if (decoded is! Map<String, dynamic> || decoded['runId'] != runId ||
        (sharedEasyTier ? decoded['scenario'] != 'shared-easytier' : decoded['firstStop'] != firstStop)) {
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
    try {
    await steps.stage('host_board');
    await app.main();
    await existing.until(tester, () => find.byType(HostCatalogPage).evaluate().length == 1 &&
      find.byKey(const ValueKey('hosts-add')).evaluate().length == 1);
    final home = tester.widget<HostCatalogPage>(find.byType(HostCatalogPage));
    expect(home.catalog, isNull); expect(home.keys, isNull); expect(home.adapterFactory, isNull);
    await steps.navigation(2);
    final etNetwork = await steps.createNetwork(role: 'et', label: 'QA EasyTier', controlUrl: '',
      networkName: value('networkName'), peerUrl: value('peerUrl'), networkSecret: value('networkSecret'));
    if (sharedEasyTier) {
      final result = await observeSharedEasyTier(steps, etNetwork, value('etProfile'), value('tsProfile'));
      existing.publish(exchange, 'result.json', jsonEncode(result));
      binding.reportData = result;
      return;
    }
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
    await steps.stopNetwork(survivor, survivor == 'et' ? etNetwork : tsNetwork);
    await steps.stage('both_stopped_audit');
    expect(await steps.awaitFile('both-stopped-audit.txt'), 'accepted');
    final result = {'status': 'passed', 'firstStop': firstStop,
      'twoReviewedTargets': true, 'observedBothUpdates': true, 'responseMarkersMatched': true,
      'explicitTsAuthorization': true,
      'newFullAfterResume': true, 'stoppedTabRetired': true,
      'initialInputsAccepted': true, 'survivorInputAccepted': true, 'survivorStopped': true};
    existing.publish(exchange, 'result.json', jsonEncode(result));
    binding.reportData = result;
    } catch (error, stack) {
      final kind = error is TestFailure ? 'test_failure'
        : error is FlutterError ? 'flutter_error'
        : error is StateError ? 'state_error'
        : error is AssertionError ? 'assertion_error' : 'other';
      await steps.captureFailureNotice();
      existing.publish(exchange, 'failure.json', jsonEncode({'stage': steps.currentStage, 'kind': kind,
        'responseReceived': steps.responseReceived, 'stackFrames': safeFailureFrames(stack),
        if (steps.responseCheck != null) 'responseCheck': steps.responseCheck!,
        if (steps.bindingCheck != null) 'bindingCheck': steps.bindingCheck!,
        if (steps.remoteCheck != null) 'remoteCheck': steps.remoteCheck!,
        if (steps.bindingSelectionMatches != null) 'bindingSelectionMatches': steps.bindingSelectionMatches!,
        if (steps.nodeDiagnostic != null) ...steps.nodeDiagnostic!}));
      rethrow;
    }
  });
}
