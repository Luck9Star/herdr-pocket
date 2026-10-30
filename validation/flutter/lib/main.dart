import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';
import 'probe_gate.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final fixture = jsonDecode(await rootBundle.loadString('assets/shared/fixture.json')) as Map<String, dynamic>;
  final load = await rootBundle.loadString('assets/shared/load-chunk.txt');
  runApp(MaterialApp(debugShowCheckedModeBanner: false, theme: ThemeData.dark(useMaterial3: true),
      home: ProbePage(fixture: fixture, load: load)));
}

class ProbePane {
  ProbePane(String id) : gate = ProbeGate(id);
  final ProbeGate gate;
  final draft = TextEditingController();
  final selection = TerminalController();
  final focusNode = FocusNode();
  void Function(String)? render;
  VoidCallback? copy;
}

class ProbePage extends StatefulWidget {
  const ProbePage({super.key, required this.fixture, required this.load});
  final Map<String, dynamic> fixture;
  final String load;
  @override
  State<ProbePage> createState() => _ProbePageState();
}

class _ProbePageState extends State<ProbePage> with WidgetsBindingObserver {
  late final panes = [ProbePane('demo-ts/session-a/pane-1'), ProbePane('demo-et/session-b/pane-2')];
  int selected = 0;
  bool split = false, loading = false, wideLayout = false;
  String info = '本地 fixture；SSH / 三网络 / 真机能力尚未验证';
  ProbePane get active => panes[selected];
  String get full => (widget.fixture['frames'] as List).first['data'] as String;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    panes.first.gate.select(true);
    for (final p in panes) { p.gate.enqueue(Frame(p.gate.ticket, full, full: true)); p.gate.consume(); }
    panes.last.gate.hide();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final nextWide = MediaQuery.sizeOf(context).width >= 960;
    if (wideLayout && !nextWide && split) {
      for (final p in panes) {
        if (p != active) { p.gate.hide(); p.focusNode.unfocus(); }
      }
    } else if (!wideLayout && nextWide && split) {
      // Reveal only stale content. Explicit full is required before input.
      for (final p in panes) { if (p != active) p.gate.visible = true; }
    }
    wideLayout = nextWide;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) {
      setState(() { for (final p in panes) { p.gate.invalidate(disconnect: true); p.focusNode.unfocus(); } });
    }
    // Foregrounding never resumes input or replays bytes. User requests a new full.
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    for (final p in panes) { p.draft.dispose(); p.selection.dispose(); p.focusNode.dispose(); }
    super.dispose();
  }

  void select(int i) {
    setState(() {
      for (final p in panes) { p.focusNode.unfocus(); p.gate.select(false); }
      if (!split && i != selected) panes[selected].gate.hide();
      selected = i;
      active.gate.select(true);
      if (!active.gate.visible) {
        active.gate.visible = true;
        info = '隐藏标签恢复：旧画面仅参考，请获取新 full';
      }
    });
  }

  void setMode(InputMode mode) {
    setState(() {
      active.focusNode.unfocus();
      active.gate.setMode(mode);
    });
    final p = active, captured = active.gate.ticket;
    if (mode == InputMode.direct) {
      WidgetsBinding.instance.addPostFrameCallback((_) { if (mounted && p.gate.current(captured) && p.gate.active) p.focusNode.requestFocus(); });
    }
  }

  void restore() {
    setState(() {
      final p = active;
      p.gate.resume();
      p.gate.enqueue(Frame(p.gate.ticket, full, full: true)); p.gate.consume();
      info = '取得新 fixture full；保持观察，未重放任何输入';
    });
  }

  Future<void> preview(String text, {required bool draft}) async {
    final p = active, ticket = active.gate.ticket;
    final mode = draft ? InputMode.draft : InputMode.direct;
    if (!p.gate.canInput || p.gate.mode != mode) return;
    if (utf8.encode(text).length > 4096) { setState(() { info = '输入超过 4096 bytes；未发送'; }); return; }
    final approved = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: Text('发送到 ${p.gate.target}'),
      content: SingleChildScrollView(child: Text('$text\n\n不额外附加回车。仅进入本地字节记录器。')),
      actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('发送文本'))]));
    if (!mounted || approved != true) return;
    setState(() {
      final accepted = p.gate.send(ticket, text, mode);
      if (accepted && draft) p.draft.clear();
      info = accepted ? p.gate.lastResult : '目标或状态已经变化；未发送';
    });
  }

  Future<void> paste() async {
    final p = active, ticket = active.gate.ticket;
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (!mounted || !p.gate.current(ticket) || p != active || data?.text == null) return;
    if (p.gate.mode == InputMode.draft) {
      if (utf8.encode(p.draft.text + data!.text!).length > 4096) return;
      p.draft.text += data.text!;
    } else { await preview(data!.text!, draft: false); }
  }

  Future<void> load({required bool burst}) async {
    if (loading) return;
    final p = active, captured = active.gate.ticket;
    if (!p.gate.fresh || !p.gate.connected) return;
    setState(() { loading = true; });
    final count = (widget.fixture['load'] as Map)['chunks'] as int;
    for (var i = 0; i < count; i++) {
      if (!mounted || !p.gate.sameStream(captured)) break;
      if (!p.gate.enqueue(Frame(captured, widget.load))) break;
      if (!burst) {
        final frame = p.gate.consume();
        if (frame != null) p.render?.call(frame.data);
        await Future<void>.delayed(Duration(milliseconds: (widget.fixture['load'] as Map)['intervalMs'] as int));
      }
    }
    if (!mounted) return;
    setState(() { loading = false; info = burst ? p.gate.lastResult : '完成 paced fixture；消费指解析提交，不是绘制完成'; });
  }

  void auxiliary(String bytes) {
    final p = active;
    setState(() { p.gate.send(p.gate.ticket, bytes, InputMode.direct); });
  }

  Widget terminal(ProbePane p) => Expanded(child: GestureDetector(
    onTap: () { if (p != active) select(panes.indexOf(p)); },
    child: Container(margin: const EdgeInsets.all(4), decoration: BoxDecoration(
      border: Border.all(color: p == active ? Colors.cyanAccent : Colors.grey, width: 2)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(padding: const EdgeInsets.all(6), child: Text('${p.gate.target} · ${p.gate.fresh ? "fixture full" : "旧画面 / 等待 full"}')),
        Expanded(child: TerminalPane(
          key: ValueKey('${p.gate.target}:${p.gate.generation}:${p.gate.epoch}:${p.gate.focus}'),
          pane: p, full: full, scrollback: (widget.fixture['terminal'] as Map)['scrollback'] as int, enabled: p == active && p.gate.canInput && p.gate.mode == InputMode.direct,
          onPaste: paste, onSent: () { if (mounted) setState(() {}); })),
      ]))));

  @override
  Widget build(BuildContext context) {
    final p = active, gate = active.gate;
    final wide = MediaQuery.sizeOf(context).width >= 960;
    final canSend = gate.canInput;
    return Scaffold(appBar: AppBar(title: const Text('Flutter · terminal_view 0.5.0')),
      body: SafeArea(child: Column(children: [
        Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: Text(info, style: const TextStyle(color: Colors.amberAccent))),
        Row(children: [for (var i = 0; i < panes.length; i++) Expanded(child: TextButton(
          onPressed: () => select(i), child: Text('${i == selected ? "● " : ""}${i == 0 ? "Tailscale 示例" : "EasyTier 示例"}'))),
          if (wide) IconButton(tooltip: '本地分屏；不调整远端 PTY', icon: const Icon(Icons.vertical_split), onPressed: () {
            setState(() { split = !split; for (final other in panes) { if (other != active) { if (split) { other.gate.visible = true; } else { other.gate.hide(); } } } });
          })]),
        Wrap(spacing: 8, children: [for (final mode in InputMode.values) ChoiceChip(
          label: Text(['观察', '逐键', '草稿'][mode.index]), selected: gate.mode == mode,
          onSelected: mode == InputMode.observe || canSend ? (_) => setMode(mode) : null),
          IconButton(tooltip: '收起键盘', onPressed: () { p.focusNode.unfocus(); SystemChannels.textInput.invokeMethod<void>('TextInput.hide'); }, icon: const Icon(Icons.keyboard_hide)),
          TextButton(onPressed: restore, child: const Text('获取新 full'))]),
        Expanded(child: Row(children: split && wide ? panes.map(terminal).toList() : [terminal(p)])),
        if (gate.mode == InputMode.draft) Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: Row(children: [
          Expanded(child: TextField(controller: p.draft, minLines: 1, maxLines: 3, maxLength: 4096,
            decoration: const InputDecoration(labelText: '本地草稿（不自动回车）'))),
          TextButton(onPressed: canSend ? () => preview(p.draft.text, draft: true) : null, child: const Text('预览发送'))])),
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
          for (final entry in {'Esc':'\u001b','Tab':'\t','↑':'\u001b[A','↓':'\u001b[B','←':'\u001b[D','→':'\u001b[C','Ctrl-C':'\u0003','Ctrl-D':'\u0004','Enter':'\r'}.entries)
            TextButton(onPressed: canSend && gate.mode == InputMode.direct ? () => auxiliary(entry.value) : null, child: Text(entry.key)),
          TextButton(onPressed: canSend && gate.mode != InputMode.observe ? paste : null, child: const Text('粘贴')),
          TextButton(onPressed: () => p.copy?.call(), child: const Text('复制选区')),
        ])),
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
          PopupMenuButton<int>(tooltip: '共享 ANSI / TUI fixture', onSelected: (i) {
            final data = (widget.fixture['frames'] as List)[i]['data'] as String;
            if (gate.enqueue(Frame(gate.ticket, data))) { final f = gate.consume(); if (f != null) p.render?.call(f.data); }
            setState(() {});
          }, itemBuilder: (_) => [for (var i = 1; i < (widget.fixture['frames'] as List).length; i++) PopupMenuItem(value: i, child: Text((widget.fixture['frames'] as List)[i]['id'] as String))], child: const Padding(padding: EdgeInsets.all(12), child: Text('ANSI / TUI'))),
          TextButton(onPressed: loading ? null : () => load(burst: false), child: const Text('1 MiB paced')),
          TextButton(onPressed: loading ? null : () => load(burst: true), child: const Text('慢消费者 / 溢出')),
          TextButton(onPressed: () => setState(() { gate.markUnknown(); p.focusNode.unfocus(); }), child: const Text('注入未知 / 断线')),
          TextButton(onPressed: gate.unknownResult && gate.fresh ? () => setState(gate.acknowledgeUnknown) : null, child: const Text('人工核实未知')),
        ])),
        Padding(padding: const EdgeInsets.all(6), child: SelectableText(
          '80×24 · 14px · queue ${gate.queuedBytes}/${gate.maxQueuedBytes} · peak ${gate.peakQueuedBytes}\n'
          'sink ${gate.inputCount} · rejected ${gate.rejectedInputs} · UTF8 ${gate.inputHex.isEmpty ? "—" : gate.inputHex.last}', maxLines: 3)),
      ])));
  }
}

/// A fresh widget/input connection is created for each mode/focus epoch.
/// Its captured ticket cannot send late composition into the next focus epoch.
class TerminalPane extends StatefulWidget {
  const TerminalPane({super.key, required this.pane, required this.full, required this.scrollback, required this.enabled, required this.onPaste, required this.onSent});
  final ProbePane pane;
  final String full;
  final int scrollback;
  final bool enabled;
  final VoidCallback onPaste, onSent;
  @override
  State<TerminalPane> createState() => _TerminalPaneState();
}

class _TerminalPaneState extends State<TerminalPane> {
  late final terminal = Terminal(maxLines: widget.scrollback, reflowEnabled: false);
  late final Ticket captured;
  late final void Function(String) output;
  @override
  void initState() {
    super.initState();
    captured = widget.pane.gate.ticket;
    widget.pane.selection.clearSelection();
    widget.pane.copy = () {
      final range = widget.pane.selection.selection;
      if (range != null) Clipboard.setData(ClipboardData(text: terminal.buffer.getText(range)));
    };
    terminal.resize(80, 24);
    terminal.write(widget.full);
    terminal.onOutput = (text) {
      widget.pane.gate.send(captured, text, InputMode.direct);
      widget.onSent();
    };
    output = (data) { if (mounted && widget.pane.gate.sameStream(captured)) terminal.write(data); };
    widget.pane.render = output;
  }
  @override
  void dispose() {
    if (widget.pane.render == output) { widget.pane.render = null; widget.pane.copy = null; }
    terminal.onOutput = null;
    terminal.dispose();
    super.dispose();
  }
  @override
  Widget build(BuildContext context) => TerminalView(terminal,
    controller: widget.pane.selection, focusNode: widget.pane.focusNode,
    autoResize: false, readOnly: !widget.enabled, simulateScroll: widget.enabled,
    keyboardType: TextInputType.text, textStyle: const TerminalStyle(fontFamily: 'ProbeNerd', fontSize: 14),
    shortcuts: const {},
    onKeyEvent: (node, event) {
      if (event is KeyDownEvent && (HardwareKeyboard.instance.isControlPressed || HardwareKeyboard.instance.isMetaPressed)) {
        if (event.logicalKey == LogicalKeyboardKey.keyV) { if (widget.enabled && widget.pane.gate.current(captured) && widget.pane.gate.canInput) widget.onPaste(); return KeyEventResult.handled; }
        if (event.logicalKey == LogicalKeyboardKey.keyC && (HardwareKeyboard.instance.isShiftPressed || HardwareKeyboard.instance.isMetaPressed)) {
          final range = widget.pane.selection.selection;
          if (range != null) Clipboard.setData(ClipboardData(text: terminal.buffer.getText(range)));
          return KeyEventResult.handled;
        }
      }
      return KeyEventResult.ignored;
    });
}
