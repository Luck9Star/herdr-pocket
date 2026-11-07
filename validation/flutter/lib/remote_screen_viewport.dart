import 'package:flutter/rendering.dart';
import 'package:terminal_view/terminal_view.dart';
import 'remote_screen_text.dart';

/// Read the pinned renderer's *actual* scroll position and cell dimensions,
/// intersecting its ancestors' paint clips and the app viewport. Only fully
/// visible cells are exported: an offscreen or half-clipped row/column is not
/// a license to read a whole 80x24 buffer page. No layout or terminal mutation.
RemoteScreenCells? visibleRemoteScreenCells(Terminal terminal,RenderTerminal render,Rect screenBounds) {
  if (!render.attached || !render.hasSize || render.size.isEmpty) return null;
  var visible = MatrixUtils.transformRect(render.getTransformTo(null),render.paintBounds).intersect(screenBounds);
  RenderObject child = render;
  while (child.parent != null) {
    final parent = child.parent!;
    var clip = parent.describeApproximatePaintClip(child);
    // The app rounds its terminal viewport. A rounded clip's bounding rect
    // alone includes hidden corner pixels, so use its conservative inner rect.
    if (clip != null && parent is RenderClipRRect) {
      if (parent.clipper != null) return null;
      final radius = parent.borderRadius.resolve(parent.textDirection);
      final corners = [radius.topLeft,radius.topRight,radius.bottomLeft,radius.bottomRight];
      final dx = corners.fold<double>(0,(value,radius) => radius.x > value ? radius.x : value);
      final dy = corners.fold<double>(0,(value,radius) => radius.y > value ? radius.y : value);
      clip = Rect.fromLTRB(clip.left + dx,clip.top + dy,clip.right - dx,clip.bottom - dy);
    }
    if (clip != null) visible = visible.intersect(MatrixUtils.transformRect(parent.getTransformTo(null),clip));
    child = parent;
  }
  if (visible.isEmpty) return null;
  final origin = render.getOffset(const CellOffset(0,0));
  final width = render.getOffset(const CellOffset(1,0)).dx - origin.dx,height = render.lineHeight;
  if (!width.isFinite || !height.isFinite || width <= 0 || height <= 0) return null;
  final start = render.globalToLocal(visible.topLeft),end = render.globalToLocal(visible.bottomRight);
  final firstRow = ((start.dy - origin.dy) / height - 0.000001).ceil().clamp(0,terminal.buffer.height).toInt();
  final endRow = ((end.dy - origin.dy) / height + 0.000001).floor().clamp(0,terminal.buffer.height).toInt();
  final firstColumn = ((start.dx - origin.dx) / width - 0.000001).ceil().clamp(0,terminal.viewWidth).toInt();
  final endColumn = ((end.dx - origin.dx) / width + 0.000001).floor().clamp(0,terminal.viewWidth).toInt();
  if (endRow <= firstRow || endColumn <= firstColumn || endRow - firstRow > 24 || endColumn - firstColumn > 80) return null;
  return RemoteScreenCells(firstRow,endRow,firstColumn,endColumn);
}
