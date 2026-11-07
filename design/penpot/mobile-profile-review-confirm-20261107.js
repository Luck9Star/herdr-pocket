// Make the independent review an explicit prototype step; do not modify other boards.
if (penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f' || penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da') throw Error('Wrong file/page');
const all=penpot.root.children.filter(s=>s.type==='board'),prev=all.find(s=>s.name.startsWith('S49 ·')),pair=all.find(s=>s.name.startsWith('S05 '));
if (!prev || !pair || all.some(s=>s.name.startsWith('S51 ·'))) throw Error('Unexpected prior state');
const b=penpot.createBoard();b.name='S51 · 已独立核验 · 继续配对';b.resize(390,844);b.x=1350;b.y=prev.y;b.fills=[{fillColor:'#F8FAFC',fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;
const face=penpot.fonts.findByName('Inter');
function box(p,n,x,y,w,h,c){const r=penpot.createRectangle();r.name=n;r.resize(w,h);r.borderRadius=12;r.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(r);r.x=p.x+x;r.y=p.y+y;return r;}
function text(p,n,x,y,w,h,v,size,c,weight=400){const t=penpot.createText(v);t.name=n;t.resize(w,h);face?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.3';t.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(t);t.x=p.x+x;t.y=p.y+y;return t;}
function link(s,d){s.addInteraction('click',{type:'navigate-to',destination:d});}
function action(y,n,label,d,primary){const r=box(b,'action · '+n,24,y,342,46,primary?'#4F46E5':'#EEF2FF');const t=text(b,n,32,y+12,326,24,label,15,primary?'#FFFFFF':'#3730A3',600);t.align='center';link(r,d);link(t,d);}
text(b,'产品标识',24,18,342,20,'HERDR POCKET  /  首次配对',12,'#64748B',600);text(b,'标题',24,52,342,38,'已独立核验 · 示例',24,'#0F172A',700);text(b,'副标题',24,96,342,38,'请再次核对目标，再明确创建本机身份。',14,'#475569');
box(b,'目标卡',24,146,342,155,'#FFFFFF');text(b,'目标标题',40,160,310,24,'已审查目标',16,'#0F172A',700);text(b,'目标详情',40,194,310,95,'demo @ buildbox.example.invalid:22\n网络 direct  ·  会话 work\n/home/demo/.config/…/work/herdr.sock\n/opt/herdr/bin/herdr',13,'#475569');
box(b,'核验卡',24,314,342,124,'#EEF2FF');text(b,'核验标题',40,328,310,24,'☑ 已独立核验账号、公钥与会话',15,'#3730A3',700);text(b,'核验详情',40,361,310,57,'核验只针对当前内容。编辑目标、切页或更换资料后需要重新核验。',14,'#475569');
action(462,'创建设备身份','演示：明确创建设备身份',pair,true);action(519,'返回未核验','返回未核验表单',prev,false);
text(b,'安全边界',24,602,342,112,'此原型只演示下一步。实际设备身份由本机安全存储创建；主机授权和 SSH 连接仍需独立完成。',13,'#475569');text(b,'原型边界',24,804,342,25,'交互原型 · 示例数据，不会实际配对或连接',12,'#64748B');
const bg=prev.children.find(s=>s.name==='action · 示例确认后配对'),label=prev.children.find(s=>s.name==='示例确认后配对'),check=prev.children.find(s=>s.name==='未勾选'),checkText=prev.children.find(s=>s.name==='审查未确认');
if(!bg || !label || !check || !checkText) throw Error('Unexpected review shapes');
for(const s of [bg,label]) { for(const i of [...s.interactions]) s.removeInteraction(i); link(s,b); }
label.characters='演示：确认已独立核验';for(const s of [check,checkText]) link(s,b);
return {added:{id:b.id,name:b.name},review:prev.id};
