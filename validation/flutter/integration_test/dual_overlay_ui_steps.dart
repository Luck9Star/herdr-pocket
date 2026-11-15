import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/pairing_public_key.dart';
import 'package:terminal_view/terminal_view.dart';

import 'android_pairing_observe_test.dart' as existing;

/// Real UI actions shared by the two independently paired overlay targets.
/// Requests, responses and credentials stay in the app's private exchange.
class DualOverlayUiSteps {
  DualOverlayUiSteps(this.tester, this.exchange);
  final WidgetTester tester;
  final Directory exchange;

  Future<void> stage(String value) async {
    if (!RegExp(r'^[a-z][a-z0-9_]{0,50}$').hasMatch(value)) {
      throw StateError('dual_stage_invalid');
    }
    existing.publish(exchange, 'stage', value);
    await tester.pump();
  }

  Future<String> awaitFile(String name) async {
    if (!RegExp(r'^[a-z0-9-]+\.(json|txt)$').hasMatch(name)) {
      throw StateError('dual_exchange_name_invalid');
    }
    final file = File('${exchange.path}/$name');
    await existing.until(tester, file.existsSync, seconds: 90);
    final value = await file.readAsString();
    if (utf8.encode(value).length > 65536) throw StateError('dual_exchange_oversize');
    return value;
  }

  Future<void> enter(String key, String text) async {
    final field = find.byKey(ValueKey(key));
    await tester.ensureVisible(field);
    await tester.enterText(field, text);
    await tester.pump();
  }

  Future<void> choose(String key, String value) async {
    final field = find.byKey(ValueKey(key));
    final dropdown = find.descendant(of: field, matching: find.byType(DropdownButton<String>));
    await existing.tapStablePointer(tester, dropdown);
    final option = find.text(value).last;
    await existing.tapPopupOption(tester, option);
  }

  Future<String> createNetwork({required String role, required String label,
      required String controlUrl, required String networkName,
      required String peerUrl, required String networkSecret}) async {
    if (!{'et', 'ts'}.contains(role)) throw StateError('dual_role_invalid');
    await stage('${role}_network_create');
    await existing.tapKey(tester, 'networks-add');
    await enter('network-label', label);
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    if (role == 'et') {
      await choose('network-provider', 'easytier');
      await enter('network-networkName', networkName);
      await enter('network-peers', peerUrl);
    } else {
      await enter('network-controlUrl', controlUrl);
    }
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    await existing.tapKey(tester, 'network-save');
    final page = tester.widget<NetworkProfilesPage>(find.byType(NetworkProfilesPage));
    await existing.until(tester, () => page.catalog.networkProfiles.where((profile) => profile.label == label).length == 1);
    final matches = page.catalog.networkProfiles.where((profile) => profile.label == label).toList();
    final profile = matches.single;
    expect(profile.provider, role == 'et' ? 'easytier' : 'tailscale');
    await existing.tap(tester, find.byKey(PageStorageKey('network-details-${profile.id}')));
    await existing.tapKey(tester, 'network-identity-${profile.id}');
    await existing.until(tester, () => find.byKey(const ValueKey('network-identity-absent')).evaluate().length == 1);
    if (role == 'et') {
      await enter('network-identity-secret', networkSecret);
      await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    }
    final review = await existing.stableReviewCheckbox(tester, 'network-identity-review');
    await tester.tap(review); await tester.pump();
    await existing.tapKey(tester, 'network-identity-create');
    await existing.until(tester, () => find.byKey(const ValueKey('network-identity-present')).evaluate().length == 1);
    await existing.tap(tester, find.text('关闭').last);
    await existing.tapKey(tester, 'network-node-refresh-${profile.id}');
    await existing.until(tester, () {
      final control = find.byKey(ValueKey('network-node-start-${profile.id}'));
      return control.evaluate().length == 1 && tester.widget<TextButton>(control).onPressed != null;
    });
    await existing.tapKey(tester, 'network-node-start-${profile.id}');
    return profile.id;
  }

  Future<void> authorizeTailscale(String profileId) async {
    await stage('ts_login_open');
    final open = find.byKey(ValueKey('network-node-login-$profileId'));
    await existing.until(tester, () => open.evaluate().length == 1 &&
      tester.widget<TextButton>(open).onPressed != null);
    await existing.tap(tester, open);
    final review = await existing.stableReviewCheckbox(tester, 'tailscale-login-review');
    await tester.tap(review); await tester.pump();
    await existing.tapKey(tester, 'tailscale-login-authorize');
    final url = find.byKey(const ValueKey('tailscale-login-url'));
    await existing.until(tester, () => url.evaluate().length == 1);
    final raw = tester.widget<SelectableText>(url).data!;
    final parsed = Uri.tryParse(raw);
    if (parsed == null || parsed.scheme != 'https') throw StateError('dual_login_url_invalid');
    existing.publish(exchange, 'ts-url.txt', raw);
    await stage('ts_wait_authorization');
    expect(await awaitFile('ts-authorized.txt'), 'authorized');
    await existing.tapKey(tester, 'tailscale-login-refresh');
    await existing.until(tester, () => find.textContaining('可关闭此页，回到主机列表').evaluate().isNotEmpty);
    await existing.tapKey(tester, 'tailscale-login-close');
  }

  Future<void> navigation(int index) async {
    final bar = find.byType(NavigationBar);
    expect(bar, findsOneWidget);
    final destinations = find.descendant(of: bar, matching: find.byType(NavigationDestination));
    expect(destinations.evaluate().length, 4);
    await existing.tap(tester, destinations.at(index));
  }

  Future<void> stopNetwork(String role, String networkId) async {
    await stage('${role}_stop_network');
    await navigation(2);
    await existing.until(tester, () => find.byType(NetworkProfilesPage).evaluate().length == 1);
    if (find.byKey(ValueKey('network-node-refresh-$networkId')).evaluate().isEmpty) {
      await existing.tap(tester, find.byKey(PageStorageKey('network-details-$networkId')));
    }
    await existing.tapKey(tester, 'network-node-refresh-$networkId');
    final stop = find.byKey(ValueKey('network-node-stop-$networkId'));
    await existing.until(tester, () => stop.evaluate().length == 1 && tester.widget<TextButton>(stop).onPressed != null);
    await existing.tap(tester, stop);
    final status = find.byKey(ValueKey('network-node-status-$networkId'));
    await existing.until(tester, () => status.evaluate().length == 1 &&
      (tester.widget<Text>(status).data ?? '').contains('已停止'));
  }

  Future<void> bindHost(String hostId, String networkId, String label, String provider) async {
    await existing.tapKey(tester, 'host-management-$hostId');
    await existing.tapKey(tester, 'host-network-$hostId');
    await choose('host-network-choice', '$label · $provider');
    expect(tester.state<FormFieldState<String>>(find.byKey(const ValueKey('host-network-choice'))).value, networkId);
    await existing.tapKey(tester, 'host-network-preview');
    await existing.tapKey(tester, 'host-network-confirm');
  }

  Future<String> openAndObserve(String role, String hostId) async {
    await stage('${role}_open_host');
    await existing.tapKey(tester, 'host-open-$hostId');
    await existing.until(tester, () => find.byKey(const ValueKey('pair-connect')).evaluate().length == 1);
    await existing.tapKey(tester, 'pair-connect');
    await existing.until(tester, () => find.byKey(const ValueKey('remote-review')).evaluate().length == 1);
    await existing.tapKey(tester, 'remote-review');
    await existing.tapKey(tester, 'remote-connect');
    final pane = find.byWidgetPredicate((widget) => widget.key is ValueKey<String> &&
      (widget.key! as ValueKey<String>).value.startsWith('remote-pane-'));
    await existing.until(tester, () => pane.evaluate().length == 1);
    await existing.tap(tester, pane);
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      find.textContaining('只读观察中').evaluate().isNotEmpty && existing.displayedSequence(tester) != null);
    final firstSequence = existing.displayedSequence(tester)!;
    final terminal = tester.widget<TerminalView>(find.byType(TerminalView)).terminal;
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, terminal) &&
      (existing.displayedSequence(tester) ?? -1) > firstSequence &&
      existing.screenHasMarker(terminal, 'Synthetic observe tick'));
    final tab = existing.hostTab();
    expect(tab, findsOneWidget);
    return (tester.widget<TextButton>(tab).key! as ValueKey<String>).value;
  }

  Future<void> resumeTab(String role, String tabKey, Terminal previous) async {
    await stage('${role}_resume');
    await existing.tapKey(tester, tabKey);
    final resume = find.byKey(const ValueKey('remote-resume'));
    await existing.until(tester, () => resume.evaluate().length == 1);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
    await existing.tap(tester, resume);
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      existing.displayedSequence(tester) != null &&
      !identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, previous) &&
      existing.screenHasMarker(tester.widget<TerminalView>(find.byType(TerminalView)).terminal,
        'Synthetic ${role.toUpperCase()} ACK ONE') &&
      find.textContaining('只读观察中').evaluate().isNotEmpty);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('remote-mode-observe'))).selected, isTrue);
  }

  Future<void> commitCharacter(String role, String character) async {
    if (!{'et': {'E', 'e'}, 'ts': {'T', 't'}}[role]!.contains(character)) {
      throw StateError('dual_input_invalid');
    }
    final expectedAck = 'Synthetic ${role.toUpperCase()} ACK ${character == character.toUpperCase() ? 'ONE' : 'TWO'}';
    await stage('${role}_input');
    await existing.tapKey(tester, 'remote-mode-direct');
    final terminal = find.byType(TerminalView);
    await existing.tap(tester, terminal);
    await existing.until(tester, () => tester.widget<TerminalView>(terminal).focusNode!.hasFocus &&
      tester.state<TerminalViewState>(terminal).hasInputConnection);
    final activeTerminal = tester.widget<TerminalView>(terminal).terminal;
    final receipt = find.byKey(const ValueKey('remote-input-receipt'));
    final before = receipt.evaluate().isEmpty ? null : tester.widget<Text>(receipt).data;
    final previous = before == null ? null : RegExp(r'request ([0-9a-f]{32})').firstMatch(before)?.group(1);
    tester.testTextInput.enterText(character);
    await tester.pump();
    await existing.accepted(tester, previousRequest: previous);
    final sequenceAfterReceipt = existing.displayedSequence(tester)!;
    await existing.until(tester, () => find.byType(TerminalView).evaluate().length == 1 &&
      identical(tester.widget<TerminalView>(find.byType(TerminalView)).terminal, activeTerminal) &&
      (existing.displayedSequence(tester) ?? -1) > sequenceAfterReceipt &&
      existing.screenHasMarker(activeTerminal, expectedAck));
  }

  Future<String> pairHost(String role, String profileJson) async {
    if (!{'et', 'ts'}.contains(role)) throw StateError('dual_role_invalid');
    await stage('${role}_pair_profile');
    await existing.tapKey(tester, 'hosts-add');
    final page = tester.widget<PairingPage>(find.byType(PairingPage));
    expect(page.keys, isNull); expect(page.adapter, isNull);
    final before = page.catalog!.profiles.map((profile) => profile.id).toSet();
    final profile = jsonDecode(profileJson) as Map<String, dynamic>;
    final expectedFingerprint = pairingFingerprint(profile['expectedHostKey'] as String);
    expect(profile['provider'], role == 'et' ? 'easytier' : 'tailscale');
    await enter('profile-input', profileJson);
    await existing.until(tester, () => find.byKey(const ValueKey('profile-preview')).evaluate().length == 1);
    final preview = tester.widget<SelectableText>(find.byKey(const ValueKey('profile-preview'))).data!;
    expect(preview, contains(expectedFingerprint));
    for (final field in ['host', 'port', 'username', 'session', 'socketPath', 'herdrPath']) {
      expect(preview, contains(profile[field].toString()));
    }
    await existing.tapKey(tester, 'profile-fill');
    expect(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-target-fingerprint'))).data, expectedFingerprint);
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    final review = await existing.stableReviewCheckbox(tester, 'pair-target-review');
    await tester.tap(review); await tester.pump();
    await existing.tapStablePointer(tester, find.byKey(const ValueKey('pair-create')));
    final request = find.byKey(const ValueKey('pair-request'));
    await existing.until(tester, () => request.evaluate().length == 1);
    final requestWire = tester.widget<SelectableText>(request).data!;
    final requestData = jsonDecode(requestWire) as Map<String, dynamic>;
    existing.publish(exchange, '$role-request.json', requestWire);
    await stage('${role}_pair_review');
    final response = await awaitFile('$role-response.json');
    await enter('pair-response', response);
    await tester.testTextInput.receiveAction(TextInputAction.done); await tester.pump();
    final responsePreview = find.byKey(const ValueKey('pair-response-preview'));
    expect(responsePreview, findsOneWidget);
    final responseText = tester.widget<Text>(responsePreview).data!;
    for (final field in [requestData['request_id'], requestData['account'], expectedFingerprint,
      pairingFingerprint(requestData['public_key'] as String)]) {
      expect(responseText, contains(field.toString()));
    }
    final source = await existing.stableReviewCheckbox(tester, 'pair-source-review');
    await tester.tap(source); await tester.pump();
    await existing.tapStablePointer(tester, find.byKey(const ValueKey('pair-accept')));
    await existing.until(tester, () => find.textContaining('authorized-unverified').evaluate().isNotEmpty);
    final added = page.catalog!.profiles.where((profile) => !before.contains(profile.id)).toList();
    expect(added.length, 1);
    expect(added.single.requiresNetworkBinding, isTrue);
    return added.single.id;
  }
}
