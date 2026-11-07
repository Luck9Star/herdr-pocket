import 'package:flutter_test/flutter_test.dart';
import 'package:terminal_view/core.dart';
import 'package:herdr_flutter_probe/remote_frame_geometry.dart';
import 'package:herdr_flutter_probe/remote_terminal_screen.dart';
import 'package:herdr_flutter_probe/remote_screen_text.dart';

void main() {
  test('remote grid limits bound each axis and total allocation', () {
    for (final size in [(2,1),(119,40),(512,128),(128,512)]) {
      expect(validRemoteFrameGeometry(size.$1,size.$2),isTrue);
    }
    for (final size in [(0,24),(1,24),(-1,24),(513,1),(2,513),(512,129)]) {
      expect(validRemoteFrameGeometry(size.$1,size.$2),isFalse);
      expect(() => createRemoteTerminalScreen(size.$1,size.$2),throwsArgumentError);
    }
    expect(validRemoteFrameGeometry(80.0,24),isFalse);
    expect(validRemoteFrameGeometry(80,null),isFalse);
  });

  for (final size in [(2,1),(16,8),(80,24),(119,40),(160,50),(512,128),(128,512)]) {
    test('local ${size.$1}x${size.$2} grid preserves last cell and bounds both buffers', () {
      final cols = size.$1,rows = size.$2;
      final terminal = createRemoteTerminalScreen(cols,rows);
      addTearDown(terminal.dispose);
      final output = <String>[],resizes = <String>[];
      terminal.onOutput = output.add;
      terminal.onResize = (width,height,pixelWidth,pixelHeight) => resizes.add('$width×$height');
      expect(terminal.viewWidth,cols); expect(terminal.viewHeight,rows);
      expect(terminal.mainBuffer.lines.maxLength,rows); expect(terminal.altBuffer.lines.maxLength,rows);
      terminal.write('\x1b[$rows;${cols}HZ');
      expect(terminal.buffer.getText(BufferRangeLine(CellOffset(cols-1,rows-1),CellOffset(cols,rows-1))),'Z');
      expect(terminal.buffer.cursorX,cols-1); expect(terminal.buffer.cursorY,rows-1);
      if (cols > 80) {
        expect(captureRemoteScreenText(terminal,RemoteScreenCells(rows-1,rows,cols-1,cols)),'Z');
      }
      // Both normal and alternate buffers stay screen-only after scrolling.
      terminal.write('\r\n' * (rows + 2));
      expect(terminal.mainBuffer.height,rows); expect(terminal.mainBuffer.scrollBack,0);
      terminal.write('\x1b[?1049hALT');
      terminal.write('\r\n' * (rows + 2));
      expect(terminal.altBuffer.height,rows); expect(terminal.altBuffer.scrollBack,0);
      expect(terminal.viewWidth,cols); expect(terminal.viewHeight,rows);
      expect(output,isEmpty); expect(resizes,isEmpty);
    });
  }
}
