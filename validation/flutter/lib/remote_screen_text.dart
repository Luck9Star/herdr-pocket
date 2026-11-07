import 'package:terminal_view/core.dart';

const remoteScreenTextByteLimit = 65536;

class RemoteScreenCells {
  const RemoteScreenCells(this.firstRow,this.endRow,this.firstColumn,this.endColumn);
  final int firstRow,endRow,firstColumn,endColumn;
}

/// Already-rendered visible cells only; never re-decode ANSI or other tabs.
///
/// Matches pinned terminal_view 0.5.0 Buffer.getText / BufferLine.getText:
/// full-width wrapped continuation rows concatenate, hard line breaks remain, wide-glyph
/// continuation cells are skipped, interior blank cells become spaces, trailing
/// unwritten cells are omitted, and written spaces + getCombined suffixes are
/// retained without normalization. The bounded visible range comes from the
/// live renderer. Horizontally clipped rows keep a separator to avoid joining
/// across omitted cells. Reject excess atomically rather than truncate a grapheme.
String? captureRemoteScreenText(Terminal terminal,RemoteScreenCells cells) {
  final buffer = terminal.buffer;
  final firstRow = cells.firstRow,endRow = cells.endRow,firstColumn = cells.firstColumn,endColumn = cells.endColumn;
  if (firstRow < 0 || endRow > buffer.height || endRow <= firstRow || endRow - firstRow > 24 ||
      firstColumn < 0 || endColumn > terminal.viewWidth || endColumn <= firstColumn || endColumn - firstColumn > 80) return null;
  final text = StringBuffer();
  var bytes = 0;
  bool append(String value) {
    // Count UTF-8 without allocating an encoding of an oversized zero-width
    // suffix that might have arrived over many bounded delta frames.
    if (value.length > remoteScreenTextByteLimit - bytes) return false;
    for (final scalar in value.runes) {
      bytes += scalar <= 0x7f ? 1 : scalar <= 0x7ff ? 2 : scalar <= 0xffff ? 3 : 4;
      if (bytes > remoteScreenTextByteLimit) return false;
    }
    text.write(value); return true;
  }
  for (var row = firstRow; row < endRow; row++) {
    final line = buffer.lines[row];
    if (row != firstRow && (!line.isWrapped || firstColumn != 0 || endColumn != terminal.viewWidth) && !append('\n')) return null;
    if (line.length < endColumn) return null;
    var blanks = 0;
    for (var column = firstColumn; column < endColumn; column++) {
      final scalar = line.getCodePoint(column),width = line.getWidth(column);
      if (scalar == 0) {
        if (column == 0 || line.getWidth(column - 1) != 2) blanks++;
        continue;
      }
      if (column + width > endColumn) continue;
      if (blanks > 0 && !append(' ' * blanks)) return null;
      blanks = 0;
      if (!append(String.fromCharCode(scalar))) return null;
      final combined = line.getCombined(column);
      if (combined != null && !append(combined)) return null;
    }
  }
  return text.toString();
}
