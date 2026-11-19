import 'package:terminal_view/core.dart';
import 'remote_frame_geometry.dart';

typedef RegisterHostTransport = void Function() Function(Future<void> Function(),{
  RetainedHostScreen? Function()? takeScreen,
});

class RetainedHostScreen {
  const RetainedHostScreen(this.terminal,this.session,this.paneId,this.terminalId,this.frameAt,this.fontSize);
  final Terminal terminal;
  final String session,paneId;
  final String? terminalId;
  final DateTime frameAt;
  final double fontSize;
}

/// Creates a local screen matching a validated observer grid. No SSH resize.
Terminal createRemoteTerminalScreen(int cols,int rows) {
  if (!validRemoteFrameGeometry(cols,rows)) throw ArgumentError('Invalid remote frame geometry');
  // 0.5.0 initializes both buffers at 24 rows before resize. A capacity below
  // 24 would make its initial shrink pop more rows than were allocated.
  final terminal = Terminal(maxLines:rows < 24 ? 24 : rows,reflowEnabled:false)..resize(cols,rows);
  terminal.mainBuffer.lines.maxLength = rows;
  terminal.altBuffer.lines.maxLength = rows;
  return terminal;
}
