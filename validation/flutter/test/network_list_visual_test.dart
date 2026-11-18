import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'herdr_workflow_visual_test.dart' as visual;
import 'host_catalog_test.dart' show MemoryCatalogStorage, saveCatalogProfile;
import 'network_profiles_test.dart' show testNetwork;
import 'network_profiles_widget_test.dart' show StoppedTailscaleRuntime;
import 'remote_test_data.dart' show fixtureConfig;
import 'pairing_gui_test.dart' show tapVisible;

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('network status list and explicit controls at $width', (tester) async {
      visual.size(tester, Size(width, 844));
      final tokens = await visual.loadVisualTokens(tester);
      final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
      await catalog.load();
      final work = NetworkProfile.fromJson({...testNetwork('tailscale').toJson(), 'label': '工作网络'});
      final team = NetworkProfile.fromJson({...testNetwork('easytier').toJson(), 'label': '团队网络', 'enabled': false});
      final lab = NetworkProfile.fromJson({...testNetwork('zerotier').toJson(), 'label': '实验网络'});
      await catalog.addNetwork(work); await catalog.addNetwork(team); await catalog.addNetwork(lab);
      final host = await saveCatalogProfile(catalog);
      await catalog.update(host.change(label:'工作站-01', networkProfileId: work.id, replaceNetwork: true, now: 1000));
      final runtime = StoppedTailscaleRuntime();
      await tester.pumpWidget(visual.visualApp(tokens, NetworkProfilesPage(catalog: catalog, closeTabs: (_) {}, runtime: runtime)));
      await tester.pumpAndSettle();
      expect(find.text('节点：状态未知 · 请刷新'), findsNWidgets(2));
      expect(find.text('设备与入网状态未读取'), findsOneWidget);
      expect(find.text('主机：工作站-01'), findsOneWidget);
      expect(find.text('工作网络 · Tailscale'), findsOneWidget);
      expect(find.text('团队网络 · EasyTier'), findsOneWidget);
      expect(find.text('实验网络 · ZeroTier'), findsOneWidget);
      final config=fixtureConfig();
      expect(find.textContaining(config['host'] as String), findsNothing);
      expect(find.textContaining(config['expectedHostKey'] as String), findsNothing);
      expect(find.textContaining(host.pairingRecord['handle'] as String), findsNothing);
      expect(find.byKey(const ValueKey('networks-add')).hitTestable(), findsOneWidget);
      expect(find.byKey(const ValueKey('networks-zerotier-device')).hitTestable(), findsOneWidget);
      final details = find.byKey(PageStorageKey('network-details-${work.id}'));
      final header=find.descendant(of:details, matching:find.byType(ListTile)).first;
      await tester.ensureVisible(header); await tester.tap(header); await tester.pumpAndSettle();
      await tapVisible(tester, 'network-node-refresh-${work.id}'); await tester.pumpAndSettle();
      expect(find.text('节点：已停止'), findsOneWidget);
      expect(runtime.statusCalls, 1);
      await tester.ensureVisible(header); await tester.tap(header); await tester.pumpAndSettle();
      expect(find.byKey(ValueKey('network-node-start-${work.id}')), findsNothing);
      await visual.top(tester, find.byKey(const ValueKey('networks-add')));
      await visual.save(tester, 'flutter-network-${width.toInt()}');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    });
  }
}
