if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong project');
const boards=penpot.root.children.filter(s=>s.type==='board'),prev=boards.find(b=>b.name.startsWith('S53 ·')),done=boards.find(b=>b.name.startsWith('S54 ·'));
if(!prev||!done||boards.some(b=>b.name.startsWith('S55 ·')))throw Error('Unexpected state');
const C={bg:'#F8FAFC',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',white:'#FFFFFF'};const font=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||font;
const b=penpot.createBoard();b.name='S55 · 已核验撤销回执 · 待接受';b.resize(390,844);b.x=1350;b.y=prev.y;b.fills=[{fillColor:C.bg,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;
function box(n,x,y,w,h,c){const r=penpot.createRectangle();r.name=n;r.resize(w,h);r.borderRadius=12;r.fills=[{fillColor:c,fillOpacity:1}];b.appendChild(r);r.x=b.x+x;r.y=b.y+y;return r;}
function text(n,x,y,w,h,v,size=14,color=C.ink,weight=400,face=font){const t=penpot.createText(v);t.name=n;t.resize(w,h);face?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.3';t.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(t);t.x=b.x+x;t.y=b.y+y;return t;}
function link(s,d){s.addInteraction('click',{type:'navigate-to',destination:d});}
function action(n,y,label,d,primary=false){const r=box('action · '+n,24,y,342,46,primary?C.brand:C.soft),t=text(n,32,y+12,326,24,label,15,primary?C.white:'#3730A3',600);t.align='center';link(r,d);link(t,d);}
text('产品标识',24,18,342,20,'HERDR POCKET  /  设备配对',12,C.muted,600);text('标题',24,52,342,38,'已核验撤销回执',24,C.ink,700);text('副标题',24,96,342,40,'尚未接受 · 原身份继续保留',14,C.sub);
box('核验摘要',24,146,342,190,C.white);text('摘要标题',40,160,310,24,'撤销回执 · 与原请求匹配',16,C.ink,700);text('摘要正文',40,194,310,123,'编号 0123456789abcdef\n       0123456789abcdef\n账号 demo · revoked · 16:40–16:50\n主机与设备完整指纹均已独立比对',13,C.sub,400,mono);
box('已核验',24,349,342,112,C.soft);text('已核验标题',40,363,310,24,'☑ 已核对来源、原编号与两端指纹',14,'#3730A3',700);text('已核验说明',40,394,310,52,'来源或内容变化、回执到期后需要重新核验。',14,C.sub);
action('接受撤销',483,'明确接受撤销回执 · 演示',done,true);action('返回待核验',540,'返回待核验回执',prev);
text('安全边界',24,618,342,90,'只记录本次撤销结果；不会自动连接、删除本机密钥或保证断开已有 SSH。',13,C.sub);text('原型边界',24,805,342,24,'交互原型 · 虚构示例，不执行授权操作',12,C.muted);
for(const name of ['action · 确认撤销','确认撤销']){const s=prev.children.find(x=>x.name===name);if(!s)throw Error('Missing original action');for(const i of [...s.interactions])s.removeInteraction(i);link(s,b);if(s.type==='text')s.characters='演示：确认已独立核验';}
for(const name of ['审查确认','审查确认说明']){const s=prev.children.find(x=>x.name===name);if(!s)throw Error('Missing review checkbox');link(s,b);}
return {id:b.id,name:b.name};
