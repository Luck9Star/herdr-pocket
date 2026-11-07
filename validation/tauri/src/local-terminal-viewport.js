/** Local presentation only: no PTY resize, input lease, persistence, or transport calls. */
export function terminalViewportIdentity(connection, target) {
  if(!connection || !target)return null;
  const c=connection.target || connection;
  return JSON.stringify([c.host,c.port,c.username,c.expectedHostKey,c.socketPath,c.herdrPath,c.session,
    connection.deviceFingerprint ?? null,connection.networkProfileId ?? null,connection.networkRevision ?? null,
    target.paneId,target.terminalId]);
}

export class LocalTerminalViewport {
  positions=new Map();
  viewport=null;
  terminal=null;
  key=null;
  ready=false;
  observer=null;
  onScroll=null;
  measuredWidth=null;
  applied=null;
  cellWidth() {
    const screen=this.terminal?.element?.querySelector?.('.xterm-screen');
    const width=screen?.getBoundingClientRect?.().width || this.terminal?.element?.getBoundingClientRect?.().width;
    const columns=this.terminal?.cols;
    return Number.isFinite(width) && width>0 && Number.isFinite(columns) && columns>0 ? width/columns : null;
  }
  capture() {
    const v=this.viewport;
    // Hidden/detached geometry must never overwrite the last visible position.
    if(!this.ready || !this.key || !v || !(v.clientWidth>0))return;
    const width=this.cellWidth();if(!width)return;
    // Font/layout changes retain columns rather than reinterpret old pixels.
    if(this.measuredWidth!==null && width!==this.measuredWidth && this.positions.has(this.key)){this.restore();return;}
    this.measuredWidth=width;
    // Programmatic clamping can emit scroll later; retain the user's column anchor.
    if(this.applied?.viewport===v && v.scrollLeft===this.applied.left && v.scrollTop===this.applied.top)return;
    this.applied=null;
    this.positions.delete(this.key);
    this.positions.set(this.key,{column:Math.max(0,v.scrollLeft || 0)/width,top:Math.max(0,v.scrollTop || 0)});
    while(this.positions.size>8)this.positions.delete(this.positions.keys().next().value);
  }
  mount(viewport,terminal,key,ready=false) {
    this.capture();this.observer?.disconnect();this.viewport?.removeEventListener?.('scroll',this.onScroll);
    this.viewport=viewport;this.terminal=terminal;this.key=key;this.ready=ready;this.measuredWidth=null;this.applied=null;
    this.onScroll=()=>{if(this.viewport===viewport)this.capture();};
    viewport?.addEventListener?.('scroll',this.onScroll,{passive:true});
    if(typeof ResizeObserver==='function' && viewport) {
      this.observer=new ResizeObserver(()=>this.restore());this.observer.observe(viewport);
      const screen=terminal?.element?.querySelector?.('.xterm-screen');if(screen)this.observer.observe(screen);
    }
    this.restore();
  }
  restore() {
    const v=this.viewport,p=this.positions.get(this.key) || {column:0,top:0};
    if(!this.ready || !this.key || !v || !(v.clientWidth>0))return;
    const width=this.cellWidth();if(!width)return;
    this.measuredWidth=width;
    v.scrollLeft=Math.max(0,Math.min(p.column*width,Math.max(0,v.scrollWidth-v.clientWidth)));
    v.scrollTop=Math.max(0,Math.min(p.top,Math.max(0,v.scrollHeight-v.clientHeight)));
    this.applied={viewport:v,left:v.scrollLeft,top:v.scrollTop};
  }
  fullRendered() {this.ready=true;this.restore();}
  detach() {this.capture();this.observer?.disconnect();this.viewport?.removeEventListener?.('scroll',this.onScroll);this.observer=null;this.viewport=null;this.terminal=null;this.key=null;this.ready=false;}
}
