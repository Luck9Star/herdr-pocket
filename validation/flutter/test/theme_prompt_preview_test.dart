import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/terminal_font_diagnostics.dart';

class ThemeTestBundle extends CachingAssetBundle {
  ThemeTestBundle(this.raw);
  final String raw;
  @override Future<ByteData> load(String key) async {
    if (key.endsWith('theme-prompt-samples-v1.json')) return ByteData.sublistView(Uint8List.fromList(utf8.encode(raw)));
    return rootBundle.load(key);
  }
}
String fixture() => jsonEncode({'schemaVersion':1,'id':'theme-prompt-samples-v1','columns':40,'rows':3,'samples':[
  {'id':'powerlevel10k','label':'Powerlevel10k','ansi':'\u001b[31mfoo\u001b[0m','cursorColumn':3,'cursorRow':0},
  {'id':'oh-my-posh','label':'Oh My Posh','ansi':'first\r\nsecond','cursorColumn':6,'cursorRow':1},
]});
void main() {
  for (final width in [320.0,390.0]) {
    testWidgets('theme selection remains a separate read-only local terminal at $width px',(tester) async {
      tester.view.devicePixelRatio=1; tester.view.physicalSize=Size(width,844);
      addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
      final tokens=(await tester.runAsync(DesignTokens.load))!;
      await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:Scaffold(body:SingleChildScrollView(child:
        TerminalFontDiagnostics(tokens:tokens,registeredFontFamily:'ProbeNerd',fontSize:14,onClose:(){},assetBundle:ThemeTestBundle(fixture()))))));
      await tester.runAsync(() => Future<void>.delayed(Duration.zero)); await tester.pumpAndSettle();
      expect(tester.widget<TerminalView>(find.byKey(const ValueKey('terminal-font-diagnostics-view'))).terminal.viewWidth,16);
      await tester.tap(find.byKey(const ValueKey('terminal-font-sample-powerlevel10k'))); await tester.pumpAndSettle();
      final view=tester.widget<TerminalView>(find.byKey(const ValueKey('terminal-theme-view-powerlevel10k')));
      expect(view.readOnly,isTrue); expect(view.autoResize,isFalse); expect(view.hardwareKeyboardOnly,isTrue);
      expect(view.terminal.viewWidth,40); expect(view.terminal.viewHeight,3);
      expect(view.terminal.buffer.cursorX,3); expect(view.terminal.buffer.cursorY,0);
      expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor'))).data,contains('第 4 列、第 1 行'));
      expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor-actual'))).data,contains('第 4 列、第 1 行'));
      expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor-comparison'))).data,contains('一致'));
      final scroll=find.byKey(const ValueKey('terminal-theme-horizontal'));
      await tester.drag(scroll,const Offset(-180,0)); await tester.pumpAndSettle();
      expect(tester.state<ScrollableState>(find.descendant(of:scroll,matching:find.byType(Scrollable))).position.pixels,greaterThan(0));
      await tester.tap(find.byKey(const ValueKey('terminal-font-sample-oh-my-posh'))); await tester.pumpAndSettle();
      final other=tester.widget<TerminalView>(find.byKey(const ValueKey('terminal-theme-view-oh-my-posh')));
      expect(other.terminal.buffer.cursorX,6); expect(other.terminal.buffer.cursorY,1);
      await tester.tap(find.byKey(const ValueKey('terminal-font-sample-columns'))); await tester.pumpAndSettle();
      expect(tester.widget<TerminalView>(find.byKey(const ValueKey('terminal-font-diagnostics-view'))).terminal.viewHeight,8);
      expect(tester.takeException(),isNull);
    });
  }
  testWidgets('cursor mismatch is visible without disabling the local sample',(tester) async {
    final tokens=(await tester.runAsync(DesignTokens.load))!;
    final mismatch=fixture().replaceFirst('"cursorColumn":3','"cursorColumn":4');
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:Scaffold(body:SingleChildScrollView(child:
      TerminalFontDiagnostics(tokens:tokens,registeredFontFamily:'ProbeNerd',fontSize:14,onClose:(){},assetBundle:ThemeTestBundle(mismatch))))));
    await tester.runAsync(() => Future<void>.delayed(Duration.zero)); await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('terminal-font-sample-powerlevel10k'))); await tester.pumpAndSettle();
    expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor'))).data,contains('第 5 列'));
    expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor-actual'))).data,contains('第 4 列'));
    expect(tester.widget<Text>(find.byKey(const ValueKey('terminal-theme-cursor-comparison'))).data,contains('不一致'));
  });
  testWidgets('bad sample disables themes without breaking 16 by 8 diagnostic',(tester) async {
    final tokens=(await tester.runAsync(DesignTokens.load))!;
    await tester.pumpWidget(MaterialApp(theme:tokens.theme,home:Scaffold(body:SingleChildScrollView(child:
      TerminalFontDiagnostics(tokens:tokens,registeredFontFamily:'ProbeNerd',fontSize:14,onClose:(){},assetBundle:ThemeTestBundle('{}'))))));
    await tester.runAsync(() => Future<void>.delayed(Duration.zero)); await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('terminal-theme-samples-error')),findsOneWidget);
    expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('terminal-font-sample-powerlevel10k'))).onSelected,isNull);
    expect(tester.widget<TerminalView>(find.byKey(const ValueKey('terminal-font-diagnostics-view'))).terminal.viewWidth,16);
  });
}
