import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';
import 'probe_gate.dart';
import 'design_tokens.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final fixture = jsonDecode(await rootBundle.loadString('assets/shared/fixture.json')) as Map<String, dynamic>;
  final load = await rootBundle.loadString('assets/shared/load-chunk.txt');
  final tokens = await DesignTokens.load();
  runApp(MaterialApp(debugShowCheckedModeBanner: false, theme: tokens.theme,
      home: ProbePage(fixture: fixture, load: load, tokens: tokens)));
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
  const ProbePage({super.key, required this.fixture, required this.load, required this.tokens});
  final Map<String, dynamic> fixture;
  final String load;
  final DesignTokens tokens;
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
      if (!(split && wideLayout) && i != selected) panes[selected].gate.hide();
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

  DesignTokens get tokens => widget.tokens;

  Widget statusPanel(ProbeGate gate) {
    final blocked = gate.unknownResult || !gate.fresh || !gate.connected;
    final message = gate.unknownResult
        ? '发送结果待核实 · 输入已锁定，旧输入不会重放'
        : !gate.fresh || !gate.connected
            ? '旧画面仅供参考 · 取得新画面后再显式输入'
            : gate.mode == InputMode.direct
                ? '逐键输入 · 按键只进入当前目标的本地记录器'
                : gate.mode == InputMode.draft
                    ? '本地草稿 · 预览确认后发送，不附加回车'
                    : '观察模式 · 终端只读，任务不受本地视图影响';
    return Semantics(liveRegion: blocked, child: Container(
      width: double.infinity, margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: tokens.color(blocked ? 'warningSoft' : 'brandSoft'),
        borderRadius: BorderRadius.circular(8)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(message, style: TextStyle(fontSize: 12,
          color: tokens.color(blocked ? 'warningText' : 'brandHover'))),
        if (gate.unknownResult && gate.fresh) TextButton(
          key: const ValueKey('acknowledge-unknown'),
          onPressed: () => setState(gate.acknowledgeUnknown),
          child: const Text('人工核实未知')),
      ])));
  }

  Widget terminal(ProbePane p) => Expanded(child: GestureDetector(
    onTap: () { if (p != active) select(panes.indexOf(p)); },
    child: Container(margin: const EdgeInsets.symmetric(horizontal: 6), clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: tokens.color('termBg'), borderRadius: BorderRadius.circular(12),
        border: Border.all(color: tokens.color(p == active ? 'brand' : 'termBorder'), width: 2)),
      child: LayoutBuilder(builder: (context, constraints) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (constraints.maxHeight > 96) Container(color: tokens.color('termSurface'), padding: const EdgeInsets.all(10),
          child: Text('${p == active ? "输入焦点 · " : "非活动 · "}${p.gate.target}\n'
            '${p.gate.fresh ? "示例画面" : "旧画面 / 等待 full"} · 80×24',
            style: TextStyle(color: tokens.color('termText'), fontSize: 11))),
        Expanded(child: TerminalPane(
          key: ValueKey('${p.gate.target}:${p.gate.generation}:${p.gate.epoch}:${p.gate.focus}'),
          pane: p, full: full, theme: tokens.terminalTheme,
          scrollback: (widget.fixture['terminal'] as Map)['scrollback'] as int,
          enabled: p == active && p.gate.canInput && p.gate.mode == InputMode.direct,
          onPaste: paste, onSent: () { if (mounted) setState(() {}); })),
      ])))));

  Widget hosts() => Container(width: 228, margin: const EdgeInsets.only(right: 6),
    decoration: BoxDecoration(color: tokens.color('card'),
      border: Border(right: BorderSide(color: tokens.color('border')))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Padding(padding: EdgeInsets.all(20), child: Text('主机与会话',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
      for (var i = 0; i < panes.length; i++) Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
        child: Material(color: tokens.color(i == selected ? 'brandSoft' : 'cardSubtle'),
          borderRadius: BorderRadius.circular(10), child: ListTile(
            key: ValueKey('host-$i'), selected: i == selected,
            leading: Icon(Icons.dns_outlined, color: tokens.color('brand')),
            title: Text(i == 0 ? 'demo-ts' : 'demo-et'),
            subtitle: Text('${i == 0 ? "Tailscale" : "EasyTier"} · 本地示例\n${i == 0 ? "session-a" : "session-b"}'),
            onTap: () => select(i)))),
      const Spacer(),
      Padding(padding: const EdgeInsets.all(16), child: Text(
        '网络名称为测试目标标识。\n此壳没有建立真实网络或 SSH 连接。',
        style: TextStyle(fontSize: 12, color: tokens.color('textSecondary')))),
    ]));

  Future<void> diagnostics() async {
    final p = active, gate = p.gate;
    await showModalBottomSheet<void>(context: context, isScrollControlled: true,
      builder: (context) => SafeArea(child: SingleChildScrollView(
        padding: const EdgeInsets.all(20), child: Column(mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('本地验证工具', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          SelectableText('$info\n目标 ${gate.target}\n'
            'queue ${gate.queuedBytes}/${gate.maxQueuedBytes} · peak ${gate.peakQueuedBytes}\n'
            'sink ${gate.inputCount} · rejected ${gate.rejectedInputs}\n'
            'UTF8 ${gate.inputHex.isEmpty ? "—" : gate.inputHex.last}'),
          const SizedBox(height: 12),
          Wrap(spacing: 8, children: [
            for (var i = 1; i < (widget.fixture['frames'] as List).length; i++) TextButton(
              onPressed: () {
                final data = (widget.fixture['frames'] as List)[i]['data'] as String;
                if (gate.enqueue(Frame(gate.ticket, data))) {
                  final f = gate.consume(); if (f != null) p.render?.call(f.data);
                }
                Navigator.pop(context); setState(() {});
              }, child: Text((widget.fixture['frames'] as List)[i]['id'] as String)),
            TextButton(onPressed: loading ? null : () { Navigator.pop(context); load(burst: false); }, child: const Text('1 MiB paced')),
            TextButton(onPressed: loading ? null : () { Navigator.pop(context); load(burst: true); }, child: const Text('慢消费者 / 溢出')),
            TextButton(key: const ValueKey('inject-unknown'), onPressed: () {
              Navigator.pop(context); setState(() { gate.markUnknown(); p.focusNode.unfocus(); });
            }, child: const Text('注入未知 / 断线')),
          ]),
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('关闭')),
        ]))));
  }

  @override
  Widget build(BuildContext context) {
    final p = active, gate = active.gate;
    final wide = MediaQuery.sizeOf(context).width >= 960;
    final canSend = gate.canInput;
    return Scaffold(appBar: AppBar(title: const Text('herdr pocket'),
      actions: [Padding(padding: const EdgeInsets.only(right: 16), child: Center(
        child: Text('Flutter · 本地验证', style: TextStyle(color: tokens.color('textSecondary'), fontSize: 12))))]),
      body: SafeArea(child: Row(children: [
        if (wide) hosts(),
        Expanded(child: Column(children: [
          if (MediaQuery.viewInsetsOf(context).bottom == 0) Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(children: [Icon(Icons.science_outlined, size: 16, color: tokens.color('brand')),
              const SizedBox(width: 6), Expanded(child: Text('离线 fixture · 配对 / SSH / 三网络尚未接入',
                style: TextStyle(color: tokens.color('textSecondary'), fontSize: 11)))])),
          Row(children: [for (var i = 0; i < panes.length; i++) Expanded(child: TextButton(
            key: ValueKey('tab-$i'), onPressed: () => select(i),
            style: TextButton.styleFrom(backgroundColor: i == selected ? tokens.color('brandSoft') : null),
            child: Text('${i == selected ? "● " : ""}${i == 0 ? "Tailscale · A" : "EasyTier · B"}'))),
            if (wide) IconButton(key: const ValueKey('split-toggle'),
              tooltip: '本地分屏；不调整远端 PTY', icon: const Icon(Icons.vertical_split), onPressed: () {
                setState(() { split = !split; for (final other in panes) { if (other != active) { if (split) { other.gate.visible = true; } else { other.gate.hide(); } } } });
              })]),
          Padding(padding: const EdgeInsets.symmetric(horizontal: 6), child: SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
            for (final mode in InputMode.values) Padding(padding: const EdgeInsets.only(right: 4), child: ChoiceChip(
              key: ValueKey('mode-${mode.name}'),
              label: Text(['观察', '逐键', '草稿'][mode.index]), selected: gate.mode == mode,
              onSelected: mode == InputMode.observe || canSend ? (_) => setMode(mode) : null)),
            IconButton(tooltip: '收起键盘', onPressed: () { p.focusNode.unfocus(); SystemChannels.textInput.invokeMethod<void>('TextInput.hide'); }, icon: const Icon(Icons.keyboard_hide)),
            IconButton(key: const ValueKey('restore-full'), tooltip: '获取新 full', onPressed: restore, icon: const Icon(Icons.refresh)),
          ]))),
          statusPanel(gate),
          Expanded(child: Row(children: split && wide ? panes.map(terminal).toList() : [terminal(p)])),
          if (gate.mode == InputMode.draft) Padding(padding: const EdgeInsets.fromLTRB(12, 8, 12, 0), child: Row(children: [
            Expanded(child: TextField(controller: p.draft, minLines: 1, maxLines: 2, maxLength: 4096,
              decoration: const InputDecoration(labelText: '本地草稿（不自动回车）'))),
            Column(mainAxisSize: MainAxisSize.min, children: [
              TextButton(onPressed: canSend ? paste : null, child: const Text('粘贴')),
              TextButton(onPressed: canSend ? () => preview(p.draft.text, draft: true) : null, child: const Text('预览发送')),
            ])])),
          if (gate.mode != InputMode.draft) SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
            for (final entry in {'Esc':'\u001b','Tab':'\t','↑':'\u001b[A','↓':'\u001b[B','←':'\u001b[D','→':'\u001b[C','Ctrl-C':'\u0003','Ctrl-D':'\u0004','Enter':'\r'}.entries)
              TextButton(onPressed: canSend && gate.mode == InputMode.direct ? () => auxiliary(entry.value) : null, child: Text(entry.key)),
            TextButton(onPressed: canSend && gate.mode != InputMode.observe ? paste : null, child: const Text('粘贴')),
            TextButton(onPressed: () => p.copy?.call(), child: const Text('复制选区')),
          ])),
          Container(decoration: BoxDecoration(border: Border(top: BorderSide(color: tokens.color('border')))),
            child: Row(children: [Expanded(child: Padding(padding: const EdgeInsets.only(left: 12),
              child: Text('80×24 · 本地接收 ${gate.inputCount}', key: const ValueKey('input-count'),
                style: TextStyle(fontSize: 11, color: tokens.color('textSecondary'))))),
              TextButton(key: const ValueKey('diagnostics'), onPressed: diagnostics, child: const Text('验证工具'))])),
        ])),
      ])));
  }

}

/// A fresh widget/input connection is created for each mode/focus epoch.
/// Its captured ticket cannot send late composition into the next focus epoch.
class TerminalPane extends StatefulWidget {
  const TerminalPane({super.key, required this.pane, required this.full, required this.scrollback, required this.enabled, required this.onPaste, required this.onSent, this.theme = TerminalThemes.defaultTheme});
  final ProbePane pane;
  final String full;
  final int scrollback;
  final bool enabled;
  final TerminalTheme theme;
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
    controller: widget.pane.selection, focusNode: widget.pane.focusNode, theme: widget.theme,
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
