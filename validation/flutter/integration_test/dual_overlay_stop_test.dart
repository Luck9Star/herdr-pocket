import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/network_profiles.dart';
import 'package:herdr_flutter_probe/network_profiles_page.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import '../test/host_catalog_test.dart' show MemoryCatalogStorage;
import '../test/network_profiles_test.dart' show testNetwork;
import '../test/network_identity_test.dart' show MemoryNetworkIdentity;
import 'dual_overlay_ui_steps.dart';

class TwoRunningNetworks extends NativeNetworkRuntime {
  final stopped = <String>[];
  @override bool get supported => true;
  @override Future<NetworkNodeSnapshot> profileStatus(NetworkProfile p) async {
    final binding = NetworkNodeBinding(p.id, p.revision, 'fixture', 'opaque', provider:p.provider);
    return NetworkNodeSnapshot(stopped.contains(p.id) ? 'stopped' :
      p.provider == 'easytier' ? 'engine-started' : 'running', binding);
  }
  @override Future<NetworkNodeSnapshot> stop(NetworkNodeBinding binding) async {
    stopped.add(binding.profileId);
    return const NetworkNodeSnapshot('stopped', null);
  }
}

void main() {
  for (final role in ['et','ts']) {
   for (final initiallyExpanded in [false,true]) {
    testWidgets('stop $role from opposite scroll position, initially expanded: $initiallyExpanded', (tester) async {
      tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(320,600);
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final root = Directory.systemTemp.createTempSync('network-stop-');
      addTearDown(() => root.deleteSync(recursive:true));
      final catalog = HostCatalog(storage:MemoryCatalogStorage(),clock:() => 1000); await catalog.load();
      final et = testNetwork('easytier'), ts = testNetwork('tailscale');
      await catalog.addNetwork(et); await catalog.addNetwork(ts);
      final runtime = TwoRunningNetworks();
      final steps = DualOverlayUiSteps(tester,root);
      await tester.pumpWidget(MaterialApp(home:Scaffold(
        body:NetworkProfilesPage(catalog:catalog,closeTabs:(_){},identityStore:MemoryNetworkIdentity(),runtime:runtime),
        bottomNavigationBar:NavigationBar(selectedIndex:2,onDestinationSelected:(_){},destinations:const [
          NavigationDestination(icon:Icon(Icons.home),label:'主页'),
          NavigationDestination(icon:Icon(Icons.terminal),label:'终端'),
          NavigationDestination(icon:Icon(Icons.network_check),label:'网络'),
          NavigationDestination(icon:Icon(Icons.settings),label:'设置'),
        ]))));
      final target = role == 'et' ? et : ts, other = role == 'et' ? ts : et;
      if (initiallyExpanded) await steps.showNetworkControls(target.id);
      await steps.showNetworkControls(other.id);
      final page = find.byType(NetworkProfilesPage);
      final scroll = find.descendant(of:page,matching:find.byType(Scrollable)).first;
      if (role == 'et') {
        await tester.drag(scroll,const Offset(0,-800));
      } else {
        await tester.drag(scroll,const Offset(0,800));
      }
      await tester.pumpAndSettle();
      await steps.stopNetwork(role,target.id);
      final tile = find.byKey(PageStorageKey('network-details-${target.id}'));
      final header = find.descendant(of:tile, matching:find.byType(ListTile)).first;
      expect(ExpansibleController.of(tester.element(header)).isExpanded, isTrue);
      expect(runtime.stopped,[target.id]);
      expect(runtime.stopped.contains(other.id),isFalse);
      await tester.pumpWidget(const SizedBox()); catalog.dispose();
    });
   }
  }
}
