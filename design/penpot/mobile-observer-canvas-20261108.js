// One-time incremental design change; refuses a different page or duplicate boards.
const file='b55064db-d93d-80f9-8008-ddd22e6d398f',page='7a22df08-251d-8016-8008-de03541c11da';
if(penpot.currentFile?.id!==file||penpot.currentPage?.id!==page)throw Error('wrong page');
const old=penpot.root.children.filter(s=>s.type==='board');
if(old.some(s=>/^S5[6-9] · 观察画布|^S60 · 观察画布/.test(s.name)))throw Error('existing increment needs review');
const origin=old.find(s=>s.id==='ff7bd149-6597-80a5-8008-e8c46842cb06');
const entryBoard=old.find(s=>s.id==='61ebadac-98b5-8013-8008-e6e7917e7a2b');
if(!origin||!entryBoard||old.some(b=>b.children.some(s=>s.name==='观察画布说明入口'||s.name==='观察画布说明')))throw Error('entry already exists or missing board');
const target={x:entryBoard.x+24,y:entryBoard.y+680,w:342,h:48};
const intersects=s=>Math.min(target.x+target.w,s.x+s.width)>Math.max(target.x,s.x) && Math.min(target.y+target.h,s.y+s.height)>Math.max(target.y,s.y);
if(entryBoard.children.some(intersects))throw Error('entry area occupied');
const face=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||face;
function rect(p,n,x,y,w,h,c,r=12){const s=penpot.createRectangle();s.name=n;s.resize(w,h);s.borderRadius=r;s.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(s);s.x=p.x+x;s.y=p.y+y;return s;}
function text(p,n,x,y,w,h,v,size,c,weight=400,font=face){const s=penpot.createText(v);s.name=n;s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.35';s.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(s);s.x=p.x+x;s.y=p.y+y;return s;}
function go(s,t){s.addInteraction('click',{type:'navigate-to',destination:t});}
function button(p,n,x,y,w,label,target,primary=false){const bg=rect(p,'action · '+n,x,y,w,48,primary?'#4F46E5':'#E0E7FF');const t=text(p,n,x+6,y+12,w-12,25,label,15,primary?'#FFFFFF':'#3730A3',600);t.align='center';go(bg,target);go(t,target);}
const y=Math.ceil(Math.max(...old.map(s=>s.y+s.height))+80);
function board(n,x){const b=penpot.createBoard();b.name=n;b.resize(390,844);b.x=x;b.y=y;b.showInViewMode=true;b.borderRadius=20;b.fills=[{fillColor:'#F8FAFC',fillOpacity:1}];return b;}
const choices=[board('S56 · 观察画布 · 80 × 24',0),board('S57 · 观察画布 · 120 × 40',450),board('S58 · 观察画布 · 160 × 50',900)];
const top=board('S59 · 观察画布 · 左上阅读',1350),bottom=board('S60 · 观察画布 · 右下阅读',1800);
const labels=['80 × 24','120 × 40','160 × 50'];
choices.forEach((b,selected)=>{
 text(b,'标识',24,20,342,22,'HERDR POCKET / 手机终端',12,'#64748B',600);
 text(b,'标题',24,58,342,35,'选择观察画布',24,'#0F172A',600);
 text(b,'目标',24,102,342,46,'workstation / work / term-a\n连接前选择，仅作用于本次观察',14,'#475569',400,mono);
 text(b,'尺寸标题',24,170,342,24,'画布尺寸',16,'#0F172A',600);
 labels.forEach((label,i)=>{const bg=rect(b,'画布选项 '+label,24,210+i*68,342,56,i===selected?'#E0E7FF':'#FFFFFF');const t=text(b,'选择 '+label,42,225+i*68,300,25,(i===selected?'●  ':'○  ')+label+(i===0?'  ·  默认':''),16,i===selected?'#3730A3':'#334155',600,mono);if(i!==selected){go(bg,choices[i]);go(t,choices[i]);}});
 text(b,'边界说明',24,440,342,68,'这是只读观察画布，不代表远端 PTY 的原始尺寸。选择不会立即连接，也不会调整共享 PTY。',14,'#475569');
 text(b,'保持说明',24,525,342,63,'连接后保持本次选择；要更改需停止并主动重新连接。窗口与键盘变化只影响本地视口。',14,'#475569');
 button(b,'开始观察',24,626,342,'查看 120 × 40 阅读示例',top,true);button(b,'返回横向恢复',24,692,342,'返回阅读位置说明',origin);
 text(b,'注记',24,780,342,32,'原型示意 · 不连接主机或发送输入',12,'#64748B');
});
function reader(b,right){
 text(b,'标识',24,20,342,22,'HERDR POCKET / 手机终端',12,'#64748B',600);
 text(b,'标题',24,58,342,35,right?'右下区域 · 本地阅读':'左上区域 · 本地阅读',24,'#0F172A',600);
 text(b,'目标与画布',24,106,342,48,'workstation / work / term-a\n观察画布 120 × 40 · 只读',14,'#475569',400,mono);
 rect(b,'终端背景',24,176,342,250,'#0F172A');text(b,'视口位置',42,190,306,24,right?'列 81–120 / 行 24–40':'列 1–40 / 行 1–17',13,'#A5B4FC',600,mono);
 text(b,'示意内容',42,235,306,105,right?'… terminal output    →\n… pane status: ready\n… right / bottom':'$ herdr session observe\n  pane status: ready\n  more columns →',15,'#F8FAFC',400,mono);
 rect(b,'水平轨道',42,394,280,8,'#334155',4);rect(b,'水平位置',right?214:42,394,108,8,'#A5B4FC',4);rect(b,'垂直轨道',346,198,8,190,'#334155',4);rect(b,'垂直位置',346,right?304:198,8,84,'#A5B4FC',4);
 text(b,'阅读说明',24,451,342,75,'上下左右滑动查看同一画布；本地位置按目标保存。窗口、键盘和字体变化不会调整共享 PTY。',14,'#475569');
 button(b,'切换视口示例',24,572,342,right?'返回左上区域':'查看右下区域',right?top:bottom,true);button(b,'返回选择',24,638,342,'返回画布选择',choices[1]);button(b,'返回阅读位置说明',24,704,342,'返回阅读位置说明',origin);
 text(b,'注记',24,786,342,30,'演示视口变化 · 不触发远端 resize',12,'#64748B');
}
reader(top,false);reader(bottom,true);
const entry=rect(entryBoard,'观察画布说明入口',24,680,342,48,'#EEF2FF',8);const et=text(entryBoard,'观察画布说明',30,694,330,20,'查看观察画布与上下左右阅读',13,'#3730A3',600);et.align='center';go(entry,choices[0]);go(et,choices[0]);
return {choices:choices.map(b=>b.id),top:top.id,bottom:bottom.id,entry:[entry.id,et.id],origin:origin.id,entryBoard:entryBoard.id};
