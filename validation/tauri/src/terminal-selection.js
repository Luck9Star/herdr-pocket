// Only fully visible cells are exported. Rectangles are intersected with every
// CSS clipping ancestor and the visual viewport; hit tests reject occlusion.
export function visibleCellBounds(terminal) {
  const root=terminal.element, screen=root?.querySelector('.xterm-screen');
  if(!root || !screen || !document.elementsFromPoint || !document.querySelectorAll || !globalThis.getComputedStyle)throw Error('layout_unavailable');
  const rect=screen.getBoundingClientRect(), rows=terminal.rows, cols=terminal.cols;
  if(!Number.isInteger(rows) || rows<1 || !Number.isInteger(cols) || cols<1 || rows>24 || cols>80 || !Number.isFinite(rect.width) || !Number.isFinite(rect.height) || rect.width<=0 || rect.height<=0)throw Error('layout_unavailable');
  const viewport=globalThis.visualViewport;
  const clip={left:viewport?.offsetLeft ?? 0,top:viewport?.offsetTop ?? 0,right:(viewport?.offsetLeft ?? 0)+(viewport?.width ?? document.documentElement.clientWidth),bottom:(viewport?.offsetTop ?? 0)+(viewport?.height ?? document.documentElement.clientHeight)};
  if(!Object.values(clip).every(Number.isFinite))throw Error('layout_unavailable');
  for(let node=screen.parentElement;node;node=node.parentElement){
    const style=getComputedStyle(node), box=node.getBoundingClientRect();
    if(style.display==='none' || style.visibility!=='visible')throw Error('layout_unavailable');
    const bounds={left:box.left+node.clientLeft,top:box.top+node.clientTop,right:box.left+node.clientLeft+node.clientWidth,bottom:box.top+node.clientTop+node.clientHeight};
    if(!Object.values(bounds).every(Number.isFinite))throw Error('layout_unavailable');
    if(/^(auto|scroll|hidden|clip)$/.test(style.overflowX)){clip.left=Math.max(clip.left,bounds.left);clip.right=Math.min(clip.right,bounds.right);}
    if(/^(auto|scroll|hidden|clip)$/.test(style.overflowY)){clip.top=Math.max(clip.top,bounds.top);clip.bottom=Math.min(clip.bottom,bounds.bottom);}
  }
  const width=rect.width/cols,height=rect.height/rows;
  if(!Number.isFinite(width) || !Number.isFinite(height) || width<=0 || height<=0)throw Error('layout_unavailable');
  const startCol=Math.max(0,Math.ceil((clip.left-rect.left)/width)),endCol=Math.min(cols,Math.floor((clip.right-rect.left)/width));
  const startRow=Math.max(0,Math.ceil((clip.top-rect.top)/height)),endRow=Math.min(rows,Math.floor((clip.bottom-rect.top)/height));
  // Conservatively exclude any non-terminal box crossing a cell, even when
  // the box might be behind it. This avoids leaking a sliver under a title.
  const occluders=[];
  for(const node of document.querySelectorAll('*')) {
    if(node===root || root.contains(node) || node.contains(root))continue;
    const style=getComputedStyle(node);
    if(style.display==='none' || style.visibility==='hidden')continue;
    for(const box of node.getClientRects()) {
      if(box.right>rect.left && box.left<rect.right && box.bottom>rect.top && box.top<rect.bottom)occluders.push(box);
    }
  }
  return {startCol,endCol,startRow,endRow,visible(y,x){
    const left=rect.left+x*width,top=rect.top+y*height,epsilon=Math.min(.5,width/4,height/4);
    if(occluders.some(box=>box.left<left+width && box.right>left && box.top<top+height && box.bottom>top))return false;
    return [[left+epsilon,top+epsilon],[left+width-epsilon,top+epsilon],[left+epsilon,top+height-epsilon],[left+width-epsilon,top+height-epsilon],[left+width/2,top+height/2]].every(([px,py])=>{
      const hit=document.elementsFromPoint(px,py)[0];return !!hit && root.contains(hit);
    });
  }};
}

export function visibleTerminalText(terminal, bounds=visibleCellBounds(terminal)) {
  const buffer=terminal.buffer.active, rows=terminal.rows, cols=terminal.cols;
  if(!Number.isInteger(rows) || rows<1 || !Number.isInteger(cols) || cols<1 || rows>24 || cols>80)throw Error('invalid_viewport');
  const {startRow,endRow,startCol,endCol}=bounds;
  if(![startRow,endRow,startCol,endCol].every(Number.isInteger) || startRow<0 || endRow>rows || startCol<0 || endCol>cols || startRow>=endRow || startCol>=endCol)throw Error('empty_viewport');
  const encoder=new TextEncoder();
  let text='', bytes=0, hadCell=false, previousFull=false;
  for(let y=startRow;y<endRow;y++) {
    const line=buffer.getLine(buffer.viewportY+y);
    if(!line)throw Error('missing_line');
    const visibility=[];
    for(let x=startCol;x<endCol;x++)visibility.push(bounds.visible(y,x));
    let row='', rowBytes=0, pendingSpaces=0;
    for(let x=startCol;x<endCol;x++) {
      const cell=line.getCell(x);
      if(!cell)throw Error('missing_cell');
      const width=cell.getWidth();
      if(width===0)continue;
      if(width!==1 && width!==2)throw Error('invalid_cell');
      const visible=x+width<=endCol && visibility.slice(x-startCol,x-startCol+width).every(Boolean);
      const chars=visible ? cell.getChars() : '';
      if(visible)hadCell=true;
      if (!chars) {
        pendingSpaces += Math.min(width, endCol - x);
      } else {
        // Unwritten padding only enters the snapshot between written cells.
        const remainingBytes = 65536 - bytes - rowBytes - pendingSpaces;
        if (chars.length > remainingBytes) throw Error('snapshot_too_large');
        const charBytes = encoder.encode(chars).length;
        if (charBytes > remainingBytes) throw Error('snapshot_too_large');
        row += ' '.repeat(pendingSpaces) + chars;
        rowBytes += pendingSpaces + charBytes;
        pendingSpaces = 0;
      }
      x+=width-1;
    }
    const full=startCol===0 && endCol===cols && visibility.every(Boolean);
    const newline=y>startRow && !(line.isWrapped && full && previousFull);
    if(bytes+rowBytes+(newline?1:0)>65536)throw Error('snapshot_too_large');
    if(newline){text+='\n';bytes++;}
    text+=row;bytes+=rowBytes;previousFull=full;
  }
  if(!hadCell)throw Error('empty_viewport');return text;
}

export function createTerminalSelection({current,terminal,label}) {
  const group=document.createElement('section');group.className='terminal-selection';group.setAttribute('aria-label','选择终端文本');
  let closed=false;
  const close=()=>{closed=true;field.value='';group.remove();};
  const valid=()=>!closed && current();
  const heading=document.createElement('h3');heading.textContent='选择终端文本';group.append(heading);
  const info=document.createElement('p');info.textContent=`${label} · 冻结的实际可见终端单元（最多 64 KiB）。长按选择文字并使用系统复制菜单，或选择后点击复制选区。`;group.append(info);
  const field=document.createElement('textarea');field.readOnly=true;field.value=visibleTerminalText(terminal);field.setAttribute('aria-label','可见终端文本，只读');field.setAttribute('spellcheck','false');group.append(field);
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');group.append(status);
  const actions=document.createElement('div');actions.className='remote-actions';
  const button=(text,handler)=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=handler;actions.append(b);};
  button('复制选区',async()=>{
    if(!valid()){close();return;}
    const start=field.selectionStart,end=field.selectionEnd;
    if(!Number.isInteger(start) || !Number.isInteger(end) || start===end){status.textContent='请先在只读画面中选择文字；不会复制全部。';return;}
    const selected=field.value.slice(start,end);
    try {
      if(!globalThis.navigator?.clipboard?.writeText)throw Error('clipboard_unavailable');
      await globalThis.navigator.clipboard.writeText(selected);
      if(valid())status.textContent='已复制选区。';
    } catch {if(valid())status.textContent='复制失败；请长按选区使用系统复制菜单。';}
  });
  button('关闭',close);group.append(actions);
  document.body.append(group);field.focus();
  return {close,valid,element:group};
}
