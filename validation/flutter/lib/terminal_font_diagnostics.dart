import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';

import 'design_tokens.dart';
import 'theme_prompt_samples.dart';

const _fixtureAsset = 'assets/shared/terminal-font-diagnostics-v1.json';
const _themeAsset = 'assets/shared/theme-prompt-samples-v1.json';

class TerminalFontDiagnostics extends StatefulWidget {
  const TerminalFontDiagnostics({
    super.key,
    required this.tokens,
    required this.registeredFontFamily,
    required this.fontSize,
    required this.onClose,
    this.assetBundle,
  });

  final DesignTokens tokens;
  final String registeredFontFamily;
  final double fontSize;
  final VoidCallback onClose;
  final AssetBundle? assetBundle;

  @override
  State<TerminalFontDiagnostics> createState() =>
      _TerminalFontDiagnosticsState();
}

class _TerminalFontDiagnosticsState extends State<TerminalFontDiagnostics> {
  final FocusNode _focusNode = FocusNode(
    canRequestFocus: false,
    skipTraversal: true,
  );
  Terminal? _terminal;
  Map<String, dynamic>? _fixture;
  String? _error;
  String? _themeError;
  String _selected = 'columns';
  ThemePromptSamples? _themes;
  final _themeTerminals = <String,Terminal>{};

  @override
  void initState() {
    super.initState();
    _loadFixture();
    _loadThemeFixture();
  }

  Future<void> _loadFixture() async {
    Terminal? localTerminal;
    try {
      final decoded = jsonDecode(await (widget.assetBundle ?? rootBundle).loadString(_fixtureAsset));
      if (decoded is! Map<String, dynamic> ||
          decoded['schemaVersion'] != 1 ||
          decoded['id'] != 'terminal-font-diagnostics-v1' ||
          decoded['fontFamily'] is! String ||
          decoded['columns'] is! int ||
          decoded['rows'] is! int ||
          decoded['markerColumn'] is! int ||
          decoded['samples'] is! List ||
          decoded['write'] is! String) {
        throw const FormatException('invalid terminal font diagnostic fixture');
      }
      final columns = decoded['columns'] as int;
      final rows = decoded['rows'] as int;
      final markerColumn = decoded['markerColumn'] as int;
      final samples = decoded['samples'] as List;
      if (columns != 16 ||
          rows != 8 ||
          markerColumn != 15 ||
          samples.length != rows ||
          samples.any(
            (sample) =>
                sample is! Map<String, dynamic> ||
                sample['id'] is! String ||
                sample['label'] is! String ||
                sample['text'] is! String ||
                sample['cells'] is! int ||
                sample['cells'] < 0,
          )) {
        throw const FormatException(
          'invalid terminal font diagnostic dimensions or samples',
        );
      }
      // terminal_view initializes both buffers at 80×24 before its first
      // resize. They need room for those rows even on this 16×8 sample.
      localTerminal = Terminal(maxLines: 24, reflowEnabled: false)
        ..resize(columns, rows)
        ..write(decoded['write'] as String);
      if (!mounted) {
        localTerminal.dispose();
        return;
      }
      setState(() {
        _fixture = decoded;
        _terminal = localTerminal;
      });
    } catch (_) {
      localTerminal?.dispose();
      if (mounted) setState(() => _error = '字体诊断样例暂不可用 · 远端终端未受影响');
    }
  }

  Future<void> _loadThemeFixture() async {
    final created = <String,Terminal>{};
    try {
      final fixture = ThemePromptSamples.parse(await (widget.assetBundle ?? rootBundle).loadString(_themeAsset));
      for (final sample in fixture.samples) {
        final terminal = Terminal(maxLines:24,reflowEnabled:false);
        created[sample.id] = terminal;
        terminal..resize(40,3)..write(sample.ansi);
      }
      if (!mounted) { for (final terminal in created.values) { terminal.dispose(); } return; }
      setState(() { _themes = fixture; _themeTerminals.addAll(created); });
    } catch (_) {
      for (final terminal in created.values) { terminal.dispose(); }
      if (mounted) setState(() => _themeError = '主题样例暂不可用 · 字符列宽检查仍可使用');
    }
  }

  @override
  void dispose() {
    _terminal?.dispose();
    for (final terminal in _themeTerminals.values) { terminal.dispose(); }
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final fixture = _fixture;
    final samples = fixture?['samples'] as List<dynamic>? ?? const [];
    final columns = fixture?['columns'] as int?;
    final rows = fixture?['rows'] as int?;
    final markerColumn = fixture?['markerColumn'] as int?;
    final family = fixture?['fontFamily'] as String?;
    final previewHeight = rows == null
        ? 160.0
        : (rows * widget.fontSize * 1.45).clamp(160.0, 340.0).toDouble();

    return Container(
      key: const ValueKey('terminal-font-diagnostics'),
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: widget.tokens.color('card'),
        border: Border.all(color: widget.tokens.color('borderStrong')),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '字体与字符诊断',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              TextButton(
                key: const ValueKey('terminal-font-diagnostics-close'),
                onPressed: widget.onClose,
                child: const Text('关闭诊断'),
              ),
            ],
          ),
          Text(
            family == null
                ? '配置字体：读取共享诊断样例中'
                : '配置字体：$family · 当前字号 ${widget.fontSize.toStringAsFixed(0)} px',
            key: const ValueKey('terminal-font-diagnostics-font'),
            softWrap: true,
          ),
          const SizedBox(height: 8),
          Wrap(spacing:8,runSpacing:4,children:[
            for (final choice in const [('columns','字符列宽'),('powerlevel10k','Powerlevel10k'),('oh-my-posh','Oh My Posh')])
              ChoiceChip(key:ValueKey('terminal-font-sample-${choice.$1}'),label:Text(choice.$2),selected:_selected == choice.$1,
                onSelected:choice.$1 == 'columns' || _themeTerminals.containsKey(choice.$1)
                  ? (_) => setState(() => _selected = choice.$1) : null),
          ]),
          if (_themeError != null) Text(_themeError!,key:const ValueKey('terminal-theme-samples-error')),
          const SizedBox(height:8),
          if (_selected != 'columns') _themePreview()
          else if (_error != null)
            Text(
              _error!,
              key: const ValueKey('terminal-font-diagnostics-error'),
            )
          else if (fixture == null)
            const LinearProgressIndicator(
              key: ValueKey('terminal-font-diagnostics-loading'),
            )
          else ...[
            Semantics(
              container: true,
              label: '独立本地只读终端样例，$columns 列 $rows 行。按字符样例对照竖线边界与预期单元格数。',
              child: SizedBox(
                height: previewHeight,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: TerminalView(
                    _terminal!,
                    key: const ValueKey('terminal-font-diagnostics-view'),
                    theme: widget.tokens.terminalTheme,
                    focusNode: _focusNode,
                    autoResize: false,
                    readOnly: true,
                    hardwareKeyboardOnly: true,
                    keyboardType: TextInputType.none,
                    simulateScroll: false,
                    shortcuts: const {},
                    textStyle: TerminalStyle(
                      fontFamily: widget.registeredFontFamily,
                      fontSize: widget.fontSize,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '列宽依据：固定 $columns 列 × $rows 行；右侧竖线应落在第 $markerColumn 列。下方预期列数只计样例字符，不含行号、标记竖线和补齐空格。这里不调整远端 PTY。',
              key: const ValueKey('terminal-font-diagnostics-alignment'),
              softWrap: true,
            ),
            const SizedBox(height: 8),
            for (var index = 0; index < samples.length; index++)
              _sampleRow(samples[index] as Map<String, dynamic>, index),
            const SizedBox(height: 8),
            const Text(
              '此页显示配置字体与字符样例，不能识别系统实际选用的 fallback，也不能自动判定字体覆盖或字宽正确。请观察缺字方框、重音组合和竖线对齐。',
              key: ValueKey('terminal-font-diagnostics-fallback'),
            ),
            const SizedBox(height: 8),
            const Text(
              '若主题图标缺字或分隔符错位，可在远端主题改用无图标纯文本 prompt，关闭 Nerd Font 图标与 Powerline 分隔符并用文字标签；本页不会修改远端配置。',
              key: ValueKey('terminal-font-diagnostics-no-icons'),
            ),
          ],
        ],
      ),
    );
  }

  Widget _themePreview() {
    final sample = _themes!.samples.singleWhere((sample) => sample.id == _selected);
    final terminal = _themeTerminals[_selected]!;
    final actualColumn = terminal.buffer.cursorX, actualRow = terminal.buffer.cursorY;
    final matches = actualColumn == sample.cursorColumn && actualRow == sample.cursorRow;
    final measure = TextPainter(text:TextSpan(text:'M',style:TextStyle(fontFamily:widget.registeredFontFamily,fontSize:widget.fontSize)),
      textDirection:TextDirection.ltr)..layout();
    final width = (measure.width * 40 + 32).clamp(320.0,1600.0).toDouble();
    measure.dispose();
    return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text('${sample.label} · 本地只读示例 · 40 列 × 3 行',key:const ValueKey('terminal-theme-title')),
      Text('预期光标：第 ${sample.cursorColumn + 1} 列、第 ${sample.cursorRow + 1} 行（从 1 开始）；窄屏可左右滑动查看。',
        key:const ValueKey('terminal-theme-cursor')),
      Text('本地实际光标：第 ${actualColumn + 1} 列、第 ${actualRow + 1} 行（从 1 开始）',
        key:const ValueKey('terminal-theme-cursor-actual')),
      Text(matches ? '列与行位置一致 · 字形仍需人工核对' : '位置不一致 · 请检查字符宽度与字体回退',
        key:const ValueKey('terminal-theme-cursor-comparison')),
      const SizedBox(height:8),
      SizedBox(height:(widget.fontSize * 5).clamp(96.0,160.0).toDouble(),child:SingleChildScrollView(
        key:const ValueKey('terminal-theme-horizontal'),scrollDirection:Axis.horizontal,
        child:SizedBox(width:width,child:ClipRRect(borderRadius:BorderRadius.circular(8),child:TerminalView(
          terminal,key:ValueKey('terminal-theme-view-$_selected'),theme:widget.tokens.terminalTheme,
          focusNode:_focusNode,autoResize:false,readOnly:true,hardwareKeyboardOnly:true,keyboardType:TextInputType.none,
          simulateScroll:false,shortcuts:const {},textStyle:TerminalStyle(fontFamily:widget.registeredFontFamily,fontSize:widget.fontSize)))))),
      const SizedBox(height:8),
      const Text('本地只读绘制，不改变远端会话、PTY、草稿或输入；字形、颜色与光标位置需人工核对。'),
    ]);
  }

  Widget _sampleRow(Map<String, dynamic> sample, int index) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Wrap(
      spacing: 8,
      runSpacing: 2,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text(
          '${index + 1}. ${sample['label']}',
          key: ValueKey('terminal-font-diagnostic-sample-${sample['id']}'),
        ),
        Text('预期 ${sample['cells']} 列'),
      ],
    ),
  );
}
