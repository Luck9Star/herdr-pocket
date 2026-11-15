import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';
import 'package:herdr_flutter_probe/host_tabs.dart';
import 'package:herdr_flutter_probe/host_task_summary.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'host_catalog_test.dart' show MemoryCatalogStorage;
import 'host_tabs_widget_test.dart' show tabProfile;
import 'host_task_summary_test.dart' show summaryBoard;

void main() {
  testWidgets('four destinations preserve the board and expose real controls', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(390, 844);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final tokens = (await tester.runAsync(() async {
      final fontFile = File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf');
      if (fontFile.existsSync()) {
        final font = FontLoader('ScreenChinese')..addFont(fontFile.readAsBytes().then((b) => ByteData.view(b.buffer)));
        await font.load();
      }
      final icons = FontLoader('MaterialIcons')..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
      await icons.load();
      return DesignTokens.load();
    }))!;
    final catalog = HostCatalog(storage: MemoryCatalogStorage(), clock: () => 1000);
    final tabs = HostTabs();
    await catalog.load();
    await tester.pumpWidget(RepaintBoundary(key: const ValueKey('capture'), child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: tokens.theme.copyWith(textTheme: tokens.theme.textTheme.apply(fontFamily: 'ScreenChinese'),
        chipTheme: tokens.theme.chipTheme.copyWith(labelStyle: TextStyle(fontFamily: 'ScreenChinese', color: tokens.color('textPrimary')))),
      home: HostCatalogPage(tokens: tokens, catalog: catalog, tabs: tabs, offlineBuilder: (_) => const Text('实验室')))));
    await tester.pumpAndSettle();
    Future<void> capture(String name) async {
      if (!Platform.environment.containsKey('HERDR_S01_CAPTURE')) return;
      final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(const ValueKey('capture')));
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 1);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        File('/tmp/herdr-s01-$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    expect(find.textContaining('暂无已保存主机'), findsOneWidget);
    await capture('empty');
    await tester.tap(find.text('终端').last); await tester.pumpAndSettle();
    expect(find.textContaining('暂无打开的本地视图'), findsOneWidget);
    await tester.tap(find.text('网络').last); await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.textContaining('网络'), findsWidgets);
    await tester.tap(find.text('设置').last); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('hosts-terminal-preferences')), findsOneWidget);
    expect(find.byKey(const ValueKey('hosts-transfer')), findsOneWidget);
    await tester.tap(find.text('看板').last); await tester.pumpAndSettle();
    final profile = tabProfile('工作站', 'build-session', '100.64.0.1', 'direct', 'fixture');
    await catalog.add(profile); await tester.pumpAndSettle();
    expect(find.byKey(ValueKey('host-open-${profile.id}')), findsOneWidget);
    expect(find.textContaining('状态未知'), findsWidgets);
    for (final name in ['all', 'current', 'history']) {
      final chip = find.byKey(ValueKey('hosts-filter-$name'));
      expect(tester.getSize(chip).height, greaterThanOrEqualTo(44));
      expect(tester.widget<ChoiceChip>(chip).label, isA<Text>());
    }
    await capture('host');
    final dynamic state = tester.state(find.byType(HostCatalogPage));
    final registry = state.summaries as HostTaskSummaries;
    final lease = registry.open(profile);
    final attempt = lease.begin()!;
    attempt.publish(summaryBoard(profile));
    await tester.pump(); await tester.pump();
    expect(find.textContaining('受阻窗格'), findsOneWidget);
    expect(find.textContaining('w1:p0'), findsOneWidget);
    expect(find.text('待处理 1'), findsOneWidget);
    await capture('populated');
    attempt.publish(summaryBoard(profile, revision: 2, freshness: DashboardFreshness.unavailable));
    await tester.pump(); await tester.pump();
    final history = find.byKey(const ValueKey('hosts-filter-history'));
    await tester.ensureVisible(history); await tester.tap(history); await tester.pumpAndSettle();
    expect(tester.widget<ChoiceChip>(history).selected, isTrue);
    await capture('history');
    lease.close();
    await tester.ensureVisible(find.byKey(const ValueKey('hosts-direct-ssh')));
    await tester.tap(find.byKey(const ValueKey('hosts-direct-ssh'))); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('direct-probe')), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); tabs.dispose(); catalog.dispose();
  });
}
