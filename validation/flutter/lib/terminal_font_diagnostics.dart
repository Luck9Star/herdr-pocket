import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';

import 'design_tokens.dart';

const _fixtureAsset = 'assets/shared/terminal-font-diagnostics-v1.json';

class TerminalFontDiagnostics extends StatefulWidget {
  const TerminalFontDiagnostics({
    super.key,
    required this.tokens,
    required this.registeredFontFamily,
    required this.fontSize,
    required this.onClose,
  });

  final DesignTokens tokens;
  final String registeredFontFamily;
  final double fontSize;
  final VoidCallback onClose;

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

  @override
  void initState() {
    super.initState();
    _loadFixture();
  }

  Future<void> _loadFixture() async {
    Terminal? localTerminal;
    try {
      final decoded = jsonDecode(await rootBundle.loadString(_fixtureAsset));
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
      if (columns < 1 ||
          rows < 1 ||
          markerColumn < 1 ||
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
      localTerminal = Terminal(maxLines: rows, reflowEnabled: false)
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

  @override
  void dispose() {
    _terminal?.dispose();
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
          if (_error != null)
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
