import 'dart:ui' show FlutterView;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

/// Reports enabled state for either Material button style without throwing in diagnostics.
bool? iosDiagnosticButtonEnabled(Widget? widget) =>
    widget is ButtonStyleButton ? widget.onPressed != null : null;

/// A bounded projection of layout facts, never a widget dump or stack trace.
Map<String, Object?>? iosOverflowDiagnostic(
  FlutterErrorDetails details, {
  required String stage,
  required FlutterView view,
}) {
  final match = RegExp(
    r'^A RenderFlex overflowed by (\d+(?:\.\d+)?) pixels on the (left|right|top|bottom)\.$',
  ).firstMatch(details.exceptionAsString().trim());
  if (match == null) return null;
  final pixels = double.tryParse(match[1]!);
  if (pixels == null || !pixels.isFinite || pixels <= 0 || pixels > 100000)
    return null;
  final result = <String, Object?>{
    'direction': match[2],
    'pixels': pixels,
    'stage': stage,
    'owner': 'unknown',
    'file': 'unknown',
    'viewSize': [view.physicalSize.width, view.physicalSize.height],
    'viewInsets': [
      view.viewInsets.left,
      view.viewInsets.top,
      view.viewInsets.right,
      view.viewInsets.bottom,
    ],
    'devicePixelRatio': view.devicePixelRatio,
  };
  final nodes =
      details.informationCollector?.call().toList() ?? <DiagnosticsNode>[];
  for (final node in nodes) {
    final value = node.value;
    if (value is RenderFlex && value.hasSize) {
      result['flexSize'] = [value.size.width, value.size.height];
    }
    if (node is! DiagnosticsDebugCreator || value is! DebugCreator) continue;
    Element owner = value.element;
    if (!{
      'DirectSshPage',
      'HostCatalogPage',
      'ProbePage',
    }.contains(owner.widget.runtimeType.toString())) {
      owner.visitAncestorElements((ancestor) {
        if ({
          'DirectSshPage',
          'HostCatalogPage',
          'ProbePage',
        }.contains(ancestor.widget.runtimeType.toString())) {
          owner = ancestor;
          return false;
        }
        return true;
      });
    }
    final kind = owner.widget.runtimeType.toString();
    if ({'DirectSshPage', 'HostCatalogPage', 'ProbePage'}.contains(kind)) {
      result['owner'] = kind;
      result['routeCurrent'] = ModalRoute.of(owner)?.isCurrent;
    }
    // The inspector resolves the project construction location. Only these
    // file basenames and bounded coordinates may leave the test process.
    for (final diagnostic in debugTransformDebugCreator([node])) {
      final location = RegExp(
        r'/(direct_ssh_page|host_catalog_page|main)\.dart:(\d+):(\d+)',
      ).firstMatch(diagnostic.toStringDeep());
      if (location == null) continue;
      final line = int.parse(location[2]!), column = int.parse(location[3]!);
      if (line > 0 && line <= 10000 && column > 0 && column <= 10000) {
        result.addAll({
          'file': '${location[1]}.dart',
          'line': line,
          'column': column,
        });
      }
    }
  }
  return result;
}
