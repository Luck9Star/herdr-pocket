// Local allocation policy for received observer grids, not a remote PTY size.
const maxRemoteFrameCols = 512;
const maxRemoteFrameRows = 512;
const maxRemoteFrameCells = 65536;
const remoteObservationCanvases = [(cols:80,rows:24),(cols:120,rows:40),(cols:160,rows:50)];

bool validRemoteFrameGeometry(Object? cols,Object? rows) =>
  cols is int && rows is int && cols >= 2 && rows > 0 &&
  cols <= maxRemoteFrameCols && rows <= maxRemoteFrameRows && cols * rows <= maxRemoteFrameCells;
