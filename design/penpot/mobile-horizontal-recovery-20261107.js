// Add an explanatory branch without replacing existing prototype transitions.
const file = 'b55064db-d93d-80f9-8008-ddd22e6d398f';
const page = '7a22df08-251d-8016-8008-de03541c11da';
if (penpot.currentFile?.id !== file || penpot.currentPage?.id !== page) throw Error('Wrong project page');
const boards = penpot.root.children.filter(s => s.type === 'board');
const observe = boards.find(s => s.id === '7a22df08-251d-8016-8008-de04a20d928d');
const pause = boards.find(s => s.id === '61ebadac-98b5-8013-8008-e6e791a288bd');
if (!observe || !pause || boards.some(s => /^S4[67] · 横向阅读/.test(s.name)) ||
    observe.children.some(s => s.name === '横向位置说明入口') ||
    pause.children.some(s => s.name === '横向恢复说明入口')) throw Error('Review existing boards before editing');
const face = penpot.fonts.findByName('Inter');
const mono = penpot.fonts.findByName('IBM Plex Mono') || face;
function box(parent,name,x,y,w,h,color,radius=12) {
  const s=penpot.createRectangle(); s.name=name; s.resize(w,h); s.borderRadius=radius;
  s.fills=[{fillColor:color,fillOpacity:1}]; parent.appendChild(s); s.x=parent.x+x; s.y=parent.y+y; return s;
}
function text(parent,name,x,y,w,h,value,size,color,weight=400,font=face) {
  const s=penpot.createText(value); s.name=name; s.resize(w,h); font?.applyToText(s);
  s.fontSize=String(size); s.fontWeight=String(weight); s.lineHeight='1.35';
  s.fills=[{fillColor:color,fillOpacity:1}]; parent.appendChild(s); s.x=parent.x+x; s.y=parent.y+y; return s;
}
function go(s,target) { s.addInteraction('click',{type:'navigate-to',destination:target}); }
function action(parent,name,x,y,w,label,target,primary=false) {
  const bg=box(parent,'action · '+name,x,y,w,48,primary?'#4F46E5':'#E0E7FF');
  const t=text(parent,name,x+8,y+12,w-16,24,label,15,primary?'#FFFFFF':'#3730A3',600); t.align='center';
  go(bg,target); go(t,target); return [bg,t];
}
const bottom=Math.max(...boards.map(s=>s.y+s.height));
function board(name,x) {
  const b=penpot.createBoard(); b.name=name; b.resize(390,844); b.x=x; b.y=Math.ceil(bottom+80);
  b.showInViewMode=true; b.borderRadius=20; b.fills=[{fillColor:'#F8FAFC',fillOpacity:1}]; return b;
}
const same=board('S46 · 横向阅读 · 原目标已恢复',0);
const other=board('S47 · 横向阅读 · 切换目标',450);
function populate(b,changed) {
  text(b,'产品标识',24,20,342,22,'HERDR POCKET / 手机终端',12,'#64748B',600);
  text(b,'标题',24,58,342,40,changed?'切换目标，从左侧开始':'原目标，恢复阅读位置',24,'#0F172A',600);
  text(b,'状态说明',24,108,342,49,changed?'首次打开另一个 terminal 的独立本地视口。':'核对原主机、session 与 terminal；取得新 full 后恢复本地列。',15,'#475569');
  box(b,'状态卡',24,173,342,86,changed?'#EEF2FF':'#DCFCE7');
  text(b,'状态标题',40,188,310,24,changed?'新目标 · 独立位置':'原目标 · 新画面已取得',16,changed?'#3730A3':'#166534',600);
  text(b,'目标身份',40,220,310,24,changed?'workstation / design / term-b':'workstation / design / term-a',13,'#334155',500,mono);
  box(b,'终端示意',24,280,342,214,'#0F172A');
  text(b,'终端标题',40,294,310,22,'80 × 24 · 本地横向视口',13,'#CBD5E1',500,mono);
  text(b,'屏幕示意',40,332,306,83,changed?'col 01 → 02 → 03 → …\n$ herdr status\n等待新的输出':'… → col 11 → 12 → 13\n  task: running\n  tests: complete',15,'#F8FAFC',400,mono);
  box(b,'横向轨道',40,452,310,10,'#334155',5);
  box(b,'横向位置',changed?40:125,452,115,10,'#A5B4FC',5);
  text(b,'列说明',24,510,342,48,changed?'首次打开从左侧起；已访问的目标保留各自位置。':'示例：回到之前的列；窗口或字号变化时位置会调整到可见范围。',14,'#475569');
  text(b,'安全边界',24,572,342,50,'只改变本地视口；不重放输入，也不调整远端 PTY 尺寸。',14,'#475569');
  action(b,'切换示例',24,642,342,changed?'查看原目标恢复':'查看切换目标示例',changed?same:other,true);
  action(b,'返回观察',24,704,342,'返回终端观察',observe);
  text(b,'原型边界',24,786,342,36,'交互示意 · 不连接主机或发送输入',12,'#64748B');
}
populate(same,false); populate(other,true);
const pbg=box(pause,'横向恢复说明入口',24,681,342,44,'#EEF2FF');
const pt=text(pause,'横向恢复说明',32,691,326,24,'查看横向阅读位置如何恢复',15,'#3730A3',600); pt.align='center'; go(pbg,same); go(pt,same);
const obg=box(observe,'横向位置说明入口',32,636,326,44,'#312E81');
const ot=text(observe,'横向位置说明',40,648,310,24,'↔ 查看横向阅读恢复示例',14,'#E0E7FF',600); ot.align='center'; go(obg,same); go(ot,same);
return {same:same.id,other:other.id,observe:observe.id,pause:pause.id,entries:[pbg.id,pt.id,obg.id,ot.id],sameCount:same.children.length,otherCount:other.children.length};
