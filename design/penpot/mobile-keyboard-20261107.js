// One-shot addition. Existing artwork and interactions are read-only.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f' || penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const old=penpot.root.children.filter(s=>s.type==='board');
if(old.length!==42 || old.some(s=>/^S4[34] /.test(s.name)) || !storage.keyboardBaseline || storage.keyboardBaseline.length!==1214)throw Error('Unexpected page state');
const direct=old.find(s=>s.name.startsWith('S03 ')),draft=old.find(s=>s.name.startsWith('S04 ')),observe=old.find(s=>s.name.startsWith('S02 '));
if(!direct || !draft || !observe)throw Error('Missing existing states');
const C={canvas:'#F8FAFC',card:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',line:'#CBD5E1',terminal:'#0F172A',terminalText:'#E2E8F0',warning:'#92400E',warnBg:'#FEF3C7'};
const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,color,radius=12){const r=penpot.createRectangle();r.resize(w,h);r.fills=[{fillColor:color,fillOpacity:1}];r.borderRadius=radius;b.appendChild(r);r.x=b.x+x;r.y=b.y+y;return r;}
function text(b,x,y,w,h,value,size=14,color=C.ink,weight=400){const t=penpot.createText(value);t.name=value.trim().split('\n')[0]||'示例';t.resize(w,h);font?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.35';t.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(t);t.x=b.x+x;t.y=b.y+y;return t;}
function board(id,title,x){const b=penpot.createBoard();b.name=id+' · '+title;b.resize(390,844);b.x=x;b.y=9900;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'mobile-keyboard-20261107',illustration:true}));text(b,24,18,342,20,'HERDR POCKET  /  手机终端',12,C.muted,600);text(b,24,48,342,35,title,22,C.ink,700);text(b,24,788,342,38,'交互原型 · 不控制系统键盘或连接',12,C.muted);return b;}
function link(s,d){s.addInteraction('click',{type:'navigate-to',destination:d});}
function button(b,x,y,w,label,d,primary=false){const r=rect(b,x,y,w,48,primary?C.brand:C.card);r.name='action · '+label;const t=text(b,x+8,y+13,w-16,22,label,14,primary?C.card:C.ink,600);t.align='center';link(r,d);link(t,d);return r;}
function terminal(b){const r=rect(b,24,118,342,174,C.terminal);r.name='terminal · local viewport';text(b,40,130,310,20,'workstation / agent-a · 80 × 24',12,'#94A3B8',600);text(b,40,162,310,100,'$ herdr status\n  agent-a  ·  ready\n  waiting for input…',13,C.terminalText,400);}
const locked=board('S43','键盘收起 · 输入已锁定',0);
const ready=board('S44','输入启用 · 键盘可再展开',450);
terminal(locked);terminal(ready);
rect(locked,24,94,342,18,C.soft,6);text(locked,31,94,328,19,'● 观察模式 · 不发送远端按键',12,C.brand,600);
rect(ready,24,94,342,18,C.soft,6);text(ready,31,94,328,19,'● 逐键输入已启用 · 当前目标不变',12,C.brand,600);
rect(locked,24,308,342,104,C.warnBg);text(locked,40,321,310,22,'已收起输入焦点',15,C.warning,700);text(locked,40,348,310,52,'输入许可已撤销。要再次输入，\n请重新选择逐键或草稿模式。',13,C.sub);
rect(ready,24,308,342,104,C.soft);text(ready,40,321,310,22,'系统键盘暂未显示 · 示例',15,C.brand,700);text(ready,40,348,310,52,'若系统返回后编辑器仍有焦点，\n可再次请求展开；显示由系统决定。',13,C.sub);
rect(locked,24,426,342,86,C.card);text(locked,40,438,310,20,'本地草稿 · 原目标',14,C.ink,700);text(locked,40,464,310,35,'请先检查测试结果。',14,C.sub);
rect(ready,24,426,342,86,C.card);text(ready,40,438,310,20,'本地草稿 · 原目标',14,C.ink,700);text(ready,40,464,310,35,'请先检查测试结果。',14,C.sub);
button(locked,24,528,342,'逐键输入 · 重新启用',ready,true);button(locked,24,588,342,'草稿模式 · 重新启用',draft);button(locked,24,648,342,'返回只读观察',observe);
button(ready,24,528,342,'展开键盘 · 同一编辑器',direct,true);button(ready,24,588,342,'收起键盘 · 撤销输入',locked);button(ready,24,648,342,'查看草稿模式',draft);
text(locked,24,718,342,54,'切换目标或进入后台后，旧输入不发送；窗口变化只影响本地视口。',13,C.sub);
text(ready,24,718,342,54,'本页展示可再请求展开，不代表设备键盘已显示；不会改变远端尺寸。',13,C.sub);
storage.mobileKeyboardBoards=[locked,ready];
return {boards:storage.mobileKeyboardBoards.map(b=>({id:b.id,name:b.name,x:b.x,y:b.y})),unchangedPolicy:'existing artwork and interactions were not modified'};
