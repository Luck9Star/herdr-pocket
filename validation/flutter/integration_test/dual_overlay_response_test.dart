import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/pairing_public_key.dart';
import '../test/host_catalog_test.dart' show MemoryCatalogStorage;
import '../test/pairing_accept_test.dart' show openPending;
import '../test/pairing_gui_test.dart' show authorizedResponse;
import '../test/remote_test_data.dart' show fixtureConfig;
import 'dual_overlay_ui_steps.dart';
import 'android_dual_overlay_test.dart' show safeFailureFrames;

void main() {
  test('stack summary emits only bounded approved source names and lines', () {
    final frames = safeFailureFrames(StackTrace.fromString(
      '#0 secret (file:///private/user/dual_overlay_ui_steps.dart:123:4)\n'
      '#1 secret (file:///secret/private.dart:42:3)\n'
      '#2 secret (package:herdr_flutter_probe/android_dual_overlay_test.dart:44:1)'));
    expect(frames, [{'file': 'dual_overlay_ui_steps.dart', 'line': 123},
                    {'file': 'android_dual_overlay_test.dart', 'line': 44}]);
  });
  testWidgets('response diagnostic distinguishes unchanged input and strict future window', (tester) async {
    final root = Directory.systemTemp.createTempSync('response-check-');
    addTearDown(() => root.deleteSync(recursive: true));
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000); await catalog.load();
    final fixture = await openPending(tester, catalog);
    final issued = DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3;
    final raw = jsonEncode({...authorizedResponse(fixture.request), 'issued_at': issued, 'expires_at': issued + 30});
    final field = find.byKey(const ValueKey('pair-response'));
    await tester.ensureVisible(field); await tester.enterText(field, raw); await tester.pump();
    final check = DualOverlayUiSteps(tester, root).inspectResponse(raw);
    expect(check['inputMatches'], isTrue); expect(check['fieldPresent'], isTrue);
    expect(check['pagePresent'], isTrue); expect(check['category'], 'future');
    expect(check['futureSeconds'], inInclusiveRange(1, 3));
    expect(DualOverlayUiSteps(tester, root).inspectResponse('$raw ')['inputMatches'], isFalse);
    await tester.pumpWidget(const SizedBox()); catalog.dispose();
  });
  for (final width in [320.0, 390.0]) {
    testWidgets('host-produced response is reviewed and persisted at $width', (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(width, 844);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final root = Directory.systemTemp.createTempSync('pairing-real-host-');
      addTearDown(() => root.deleteSync(recursive: true));
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      final fixture = await openPending(tester, catalog);
      final request = fixture.request;
      final input = File('${root.path}/request.json')..writeAsStringSync(jsonEncode(request));
      final hostKey = File('${root.path}/host.pub')..writeAsStringSync(fixtureConfig()['expectedHostKey'] as String);
      final script = '''
import json, pathlib, sys
from herdr_pocket_helper.store import Host
root = pathlib.Path(sys.argv[1]); raw = pathlib.Path(sys.argv[2]).read_bytes()
key = pathlib.Path(sys.argv[3]).read_text()
request = json.loads(raw)
host = Host(root, request['account'], key)
response = host.authorize(raw, request['request_id'], now=1000)
sys.stdout.write(response.decode())
''';
      final repo = Platform.environment['HP_PAIRING_REPO'];
      final python = Platform.environment['HP_PAIRING_PYTHON'];
      if (repo == null || python == null) throw StateError('isolated_fixture_environment_required');
      final result = await tester.runAsync(() => Process.run(python, ['-c', script, root.path, input.path, hostKey.path],
          environment: {...Platform.environment, 'PYTHONPATH': '$repo/helper'}));
      expect(result, isNotNull);
      expect(result!.exitCode, 0, reason: 'isolated host helper failed');
      final response = result.stdout as String;
      final steps = DualOverlayUiSteps(tester, root);
      await steps.acceptPairResponse('et', response, request, pairingFingerprint(fixtureConfig()['expectedHostKey'] as String));
      expect(catalog.profiles.single.restore(1000).state, 'authorized-unverified');
      expect(fixture.keys.signCalls, 0); // v2 responses are unsigned; SSH signs later.
      await tester.pumpWidget(const SizedBox());
      catalog.dispose();
    });
  }
}
