import 'dart:async';
import 'dart:io';

import 'package:herdr_flutter_probe/host_catalog.dart';
import '../test/host_catalog_test.dart' show MemoryCatalogStorage, catalogPairing;
import '../test/network_profiles_test.dart' show testNetwork;
import '../test/remote_test_data.dart' show fixtureConfig;

import 'package:flutter_test/flutter_test.dart';
import 'dual_overlay_ui_steps.dart';

void main() {
  test('binding is not ready until delayed persistence and add control are ready', () async {
    final storage = MemoryCatalogStorage();
    final catalog = HostCatalog(storage: storage, clock: () => 1000);
    await catalog.load();
    final network = testNetwork();
    await catalog.addNetwork(network);
    final host = HostProfile.create('fixture', fixtureConfig(), catalogPairing(), 1000, provider: 'tailscale');
    await catalog.add(host);
    storage.beforeWrite = Completer<void>();
    final pending = catalog.update(host.change(networkProfileId: network.id, replaceNetwork: true, now: 1000));
    await Future<void>.delayed(Duration.zero);
    expect(hostBindingReady(catalog, host.id, network.id, true), isFalse);
    storage.beforeWrite!.complete();
    await pending;
    expect(hostBindingReady(catalog, host.id, network.id, false), isFalse);
    expect(hostBindingReady(catalog, host.id, network.id, true), isTrue);
    expect(hostBindingReady(catalog, host.id, 'different', true), isFalse);
    catalog.dispose();
  });
  testWidgets('node diagnostic is discarded when later UI stages start', (tester) async {
    final directory = Directory.systemTemp.createTempSync('dual-stage-test-');
    addTearDown(() => directory.deleteSync(recursive: true));
    final steps = DualOverlayUiSteps(tester, directory);
    steps.nodeDiagnostic = {'nodeState': 'needs_login'};
    await steps.stage('ts_node_ready_refresh');
    expect(steps.nodeDiagnostic, isNotNull);
    await steps.stage('ts_pair_profile');
    expect(steps.nodeDiagnostic, isNull);
    expect(File('${directory.path}/stage').readAsStringSync(), 'ts_pair_profile');
  });
}
