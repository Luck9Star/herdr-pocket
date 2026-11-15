import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/pairing_page.dart';
import 'package:herdr_flutter_probe/remote_adapter.dart';
import 'package:herdr_flutter_probe/remote_page.dart';
import 'pairing_gui_test.dart' show TestDeviceKeys, fillPairTarget;
import 'remote_input_widget_test.dart' as input;
import 'remote_page_test.dart' as base;
import 'remote_test_data.dart';

const capture = ValueKey('herdr-workflow-capture');
Future<DesignTokens> loadVisualTokens(WidgetTester tester) async =>
  (await tester.runAsync(() async {
    if (Platform.environment.containsKey('HERDR_WORKFLOW_CAPTURE')) {
      final file = File('/System/Library/Fonts/Supplemental/Arial Unicode.ttf');
      if (file.existsSync()) {
        final font = FontLoader('WorkflowChinese')..addFont(file.readAsBytes().then((b) => ByteData.view(b.buffer)));
        await font.load();
      }
      for (final entry in {'MaterialIcons':'fonts/MaterialIcons-Regular.otf',
        'ProbeNerd':'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'}.entries) {
        final font = FontLoader(entry.key)..addFont(rootBundle.load(entry.value)); await font.load();
      }
    }
    return DesignTokens.load();
  }))!;
Widget visualApp(DesignTokens tokens, Widget page) => RepaintBoundary(key:capture,
  child:MaterialApp(debugShowCheckedModeBanner:false,
    theme:Platform.environment.containsKey('HERDR_WORKFLOW_CAPTURE')
      ? tokens.theme.copyWith(
          textTheme:tokens.theme.textTheme.apply(fontFamily:'WorkflowChinese'),
          appBarTheme:tokens.theme.appBarTheme.copyWith(titleTextStyle:tokens.theme.appBarTheme.titleTextStyle?.copyWith(fontFamily:'WorkflowChinese')),
          chipTheme:tokens.theme.chipTheme.copyWith(labelStyle:tokens.theme.chipTheme.labelStyle?.copyWith(fontFamily:'WorkflowChinese'))) : tokens.theme,
    home:page));
Future<void> save(WidgetTester tester, String name) async {
  final directory = Platform.environment['HERDR_WORKFLOW_CAPTURE']; if (directory == null) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(capture));
  await tester.runAsync(() async {
    Directory(directory).createSync(recursive:true);
    final image = await boundary.toImage(pixelRatio:1);
    final bytes = await image.toByteData(format:ui.ImageByteFormat.png);
    File('$directory/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List()); image.dispose();
  });
}
void size(WidgetTester tester, Size value) {
  tester.view.devicePixelRatio=1; tester.view.physicalSize=value;
  addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetViewInsets);
}
Future<void> top(WidgetTester tester, Finder element) async {
  Scrollable.of(tester.element(element)).position.jumpTo(0); await tester.pumpAndSettle();
}
void main() {
  setUp(PairingPage.resetMemorySession); tearDown(PairingPage.resetMemorySession);
  for (final width in [320.0,390.0,1200.0]) {
    testWidgets('pairing steps and fingerprint remain reachable at $width without creating identity', (tester) async {
      size(tester,Size(width,844)); final tokens=await loadVisualTokens(tester);
      final keys=TestDeviceKeys(fixtureConfig()['privateKeyPem'] as String);
      await tester.pumpWidget(visualApp(tokens,PairingPage(tokens:tokens,keys:keys)));
      await tester.pumpAndSettle(); if (width==390) await save(tester,'flutter-pairing-390');
      await fillPairTarget(tester,fixtureConfig());
      await tester.ensureVisible(find.byKey(const ValueKey('pair-target-fingerprint'))); await tester.pumpAndSettle();
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('pair-target-fingerprint'))).data,startsWith('SHA256:'));
      if (width==390) await save(tester,'flutter-fingerprint-390');
      await tester.ensureVisible(find.byKey(const ValueKey('pair-target-review'))); await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('pair-target-review')).hitTestable(),findsOneWidget);
      expect(keys.creates,0); expect(tester.takeException(),isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('actual herdr terminal widgets expose three modes without sending on mode switches', (tester) async {
    size(tester,const Size(390,844)); final tokens=await loadVisualTokens(tester);
    final adapter=input.InputFixtureAdapter();
    await tester.pumpWidget(visualApp(tokens,RemotePage(tokens:tokens,adapter:adapter)));
    await base.fillRemoteFixture(tester);
    for (final name in ['review','connect']) {await tester.ensureVisible(base.field(name));await tester.tap(base.field(name));await tester.pump();}
    adapter.publish();await tester.pump();
    final pane=find.byKey(const ValueKey('remote-pane-w1:p1'));await tester.ensureVisible(pane);await tester.tap(pane);await tester.pump();
    adapter.frame!(adapter.generation,'w1:p1',const RemoteFrame(0,true,
      '\x1b[90mSYNTHETIC UI FIXTURE / NO LIVE HOST\x1b[0m\r\n\r\n'
      '\x1b[32mfixture@workstation\x1b[0m \x1b[34m~/project\x1b[0m\r\n'
      '\$ herdr status\r\n\x1b[32m●\x1b[0m agent-a  running\r\n  task: terminal interface review\r\n\r\n'
      '\$ flutter test\r\n\x1b[32mAll tests passed!\x1b[0m\r\n\r\n\$ '));
    await tester.pumpAndSettle();await top(tester,find.byKey(const ValueKey('remote-mode-observe')));
    expect(find.byKey(const ValueKey('remote-tab-w1:p1')),findsOneWidget);await save(tester,'flutter-observe-390');
    await input.mode(tester,'direct');await top(tester,find.byKey(const ValueKey('remote-mode-direct')));
    expect(adapter.received,isEmpty);await save(tester,'flutter-direct-390');
    await input.mode(tester,'draft');
    await tester.ensureVisible(find.byKey(const ValueKey('remote-input-draft')));
    await tester.enterText(find.byKey(const ValueKey('remote-input-draft')),'git status\ngit diff --check');
    await tester.testTextInput.receiveAction(TextInputAction.done);await tester.pumpAndSettle();
    await top(tester,find.byKey(const ValueKey('remote-mode-draft')));
    expect(adapter.received,isEmpty);await save(tester,'flutter-draft-390');
    tester.view.physicalSize=const Size(1200,844);await tester.pumpAndSettle();
    expect(tester.takeException(),isNull);await tester.pumpWidget(const SizedBox());
  });
}
