import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/terminal_view.dart';
import 'package:herdr_flutter_probe/remote_horizontal_viewport.dart';
import 'package:herdr_flutter_probe/remote_vertical_viewport.dart';

void main() {
  test('vertical row anchors are finite, target-isolated, clamped and limited to 16 targets', () {
    final anchors = <String,double>{};
    expect(restoredRemoteVerticalOffset(anchors,'new',14,0,400),isNull);
    rememberRemoteVerticalAnchor(anchors,'a',5.5);
    expect(restoredRemoteVerticalOffset(anchors,'a',14,0,400),77);
    expect(restoredRemoteVerticalOffset(anchors,'a',20,0,400),110);
    expect(restoredRemoteVerticalOffset(anchors,'b',14,0,400),isNull);
    expect(restoredRemoteVerticalOffset(anchors,'a',14,0,50),50);
    expect(anchors['a'],5.5);
    expect(restoredRemoteVerticalOffset(anchors,'a',14,0,400),77);
    rememberRemoteVerticalAnchor(anchors,null,1); rememberRemoteVerticalAnchor(anchors,'',1);
    rememberRemoteVerticalAnchor(anchors,'bad',double.nan); rememberRemoteVerticalAnchor(anchors,'negative',-1);
    expect(anchors.keys,['a']);
    for (var i = 0; i < 20; i++) { rememberRemoteVerticalAnchor(anchors,'target-$i',i.toDouble()); }
    expect(anchors.length,16); expect(anchors.containsKey('a'),isFalse); expect(anchors.containsKey('target-0'),isFalse);
  });
  testWidgets('vertical restore waits for a fresh full and leaves first-target renderer defaults unchanged', (tester) async {
    final anchors = <String,double>{};
    final terminals = <Terminal>[];
    addTearDown(() { for (final terminal in terminals) { terminal.dispose(); } });
    Terminal screen({int rows=40}) { final terminal = Terminal(maxLines:rows < 24 ? 24 : rows,reflowEnabled:false)..resize(120,rows); terminals.add(terminal); return terminal; }
    Future<void> show(String? identity,Terminal terminal,{bool fresh=true,double fontSize=14,double height=200}) async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:Align(alignment:Alignment.topLeft,
        child:SizedBox(width:300,child:RemoteVerticalViewport(identity:identity,anchors:anchors,frame:terminal,fresh:fresh,
          builder:(scroll) => SizedBox(height:height,child:TerminalView(terminal,key:ObjectKey(terminal),
            scrollController:scroll,autoResize:false,readOnly:true,hardwareKeyboardOnly:true,
            textStyle:TerminalStyle(fontFamily:'monospace',fontSize:fontSize)))))))));
      await tester.pump(); await tester.pump();
    }
    ScrollController controller() => tester.widget<TerminalView>(find.byType(TerminalView)).scrollController!;
    final a = screen(); await show('a',a);
    expect(controller().offset,controller().position.maxScrollExtent); // terminal_view's initial sticky-bottom behavior.
    expect(anchors,isEmpty);
    tester.widget<Slider>(find.byKey(const ValueKey('remote-vertical-slider'))).onChanged!(.25);
    await tester.pump(); await tester.pump();
    final row = anchors['a']!,offset = controller().offset;
    final oldCallback = tester.widget<Slider>(find.byKey(const ValueKey('remote-vertical-slider'))).onChanged!;
    final b = screen(); await show('b',b);
    expect(controller().offset,controller().position.maxScrollExtent);
    expect(anchors.containsKey('b'),isFalse);
    oldCallback(0); await tester.pump();
    expect(controller().offset,controller().position.maxScrollExtent); expect(anchors.containsKey('b'),isFalse);
    final resumed = screen(); await show('a',resumed,fresh:false);
    expect(controller().offset,controller().position.maxScrollExtent); expect(anchors['a'],row);
    await show('a',resumed);
    expect(controller().offset,closeTo(offset,0.1));
    await show('a',resumed,fontSize:18,height:180);
    final render = tester.state<TerminalViewState>(find.byType(TerminalView)).renderTerminal;
    expect(controller().offset,closeTo(row * render.lineHeight,0.1));
    await show('a',screen(rows:8),fontSize:18,height:180);
    expect(controller().offset,0); expect(anchors['a'],row);
    await show('a',resumed,fontSize:18,height:180);
    final restored = tester.state<TerminalViewState>(find.byType(TerminalView)).renderTerminal;
    expect(controller().offset,closeTo(row * restored.lineHeight,0.1)); expect(anchors['a'],row);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('column anchor survives rebuild and geometry changes, isolated by target', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(2400,800);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final anchors = <String,double>{};
    Future<void> show(String target,double width,double fontSize,{int columns=80}) async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:Center(child:SizedBox(width:width,height:360,
        child:RemoteHorizontalViewport(identity:target,anchors:anchors,columns:columns,
          style:TerminalStyle(fontFamily:'monospace',fontSize:fontSize),
          child:const ColoredBox(key:ValueKey('fixture-terminal'),color:Colors.black)))))));
      await tester.pump();
    }
    ScrollController controller() => tester.widget<SingleChildScrollView>(
      find.byKey(const ValueKey('remote-horizontal-scroll'))).controller!;
    await show('host/session/pane/terminal-a',200,14);
    expect(find.byKey(const ValueKey('remote-horizontal-slider')),findsOneWidget);
    expect(tester.getSize(find.byKey(const ValueKey('fixture-terminal'))).height,312);
    expect(controller().position.maxScrollExtent,greaterThan(0));
    controller().jumpTo(controller().position.maxScrollExtent / 2); await tester.pump();
    final column = anchors['host/session/pane/terminal-a']!;
    expect(column,greaterThan(0));
    await show('host/session/pane/terminal-a',250,18);
    expect(anchors['host/session/pane/terminal-a']!,closeTo(column,0.01));
    await show('host/session/pane/terminal-b',200,14);
    expect(controller().offset,0);
    await show('host/session/pane/terminal-a',200,14);
    expect(anchors['host/session/pane/terminal-a']!,closeTo(column,0.01));
    final previousExtent = controller().position.maxScrollExtent;
    final previousWidth = tester.getSize(find.byKey(const ValueKey('fixture-terminal'))).width;
    await show('host/session/pane/terminal-a',200,14,columns:119);
    expect(tester.getSize(find.byKey(const ValueKey('fixture-terminal'))).width,closeTo(previousWidth * 119 / 80,0.01));
    expect(controller().position.maxScrollExtent,greaterThan(previousExtent));
    expect(anchors['host/session/pane/terminal-a']!,closeTo(column,0.01));
    controller().jumpTo(controller().position.maxScrollExtent); await tester.pump();
    await show('host/session/pane/terminal-a',200,14,columns:16);
    expect(controller().offset,controller().position.maxScrollExtent);
    expect(anchors['host/session/pane/terminal-a']!,lessThan(16));
    await show('host/session/pane/terminal-a',2000,14);
    expect(controller().offset,0);
    expect(anchors['host/session/pane/terminal-a'],0);
    expect(find.byKey(const ValueKey('remote-horizontal-slider')),findsNothing);
    expect(tester.getSize(find.byKey(const ValueKey('fixture-terminal'))).height,360);
  });
  testWidgets('missing identities are never shared and saved anchors are bounded', (tester) async {
    tester.view.devicePixelRatio = 1; tester.view.physicalSize = const Size(1000,800);
    addTearDown(tester.view.resetDevicePixelRatio); addTearDown(tester.view.resetPhysicalSize);
    final anchors = <String,double>{};
    Future<void> show(String? target) async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:Center(child:SizedBox(width:200,height:360,
        child:RemoteHorizontalViewport(identity:target,anchors:anchors,columns:80,
          style:const TerminalStyle(fontFamily:'monospace',fontSize:14),child:const ColoredBox(color:Colors.black)))))));
      await tester.pump();
    }
    ScrollController controller() => tester.widget<SingleChildScrollView>(find.byKey(const ValueKey('remote-horizontal-scroll'))).controller!;
    await show(null); controller().jumpTo(30); await tester.pump();
    expect(anchors,isEmpty);
    await show(''); expect(controller().offset,0); controller().jumpTo(30); await tester.pump();
    expect(anchors,isEmpty);
    for (var i = 0; i < 20; i++) { await show('target-$i'); controller().jumpTo(30); await tester.pump(); }
    expect(anchors.length,16); expect(anchors.containsKey('target-0'),isFalse);
    await show('target-0'); expect(controller().offset,0);
  });
}
