// One-shot addition: preserve unrelated v2 objects and original page selection.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da') throw Error('Wrong project');
const boards=penpot.root.children.filter(s=>s.type==='board');
if(boards.some(s=>/^S(52|53|54) ·/.test(s.name))) throw Error('Duplicate; inspect first');
const pair=boards.find(b=>b.name.startsWith('S05 ')),helper=boards.find(b=>b.name.startsWith('S13 ')),reviewed=boards.find(b=>b.name.startsWith('S51 ')),home=boards.find(b=>b.name.startsWith('S01 '));
if(!pair||!helper||!reviewed||!home) throw Error('Missing established destinations');
const C={bg:'#F8FAFC',white:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',warning:'#92400E',warnBg:'#FEF3C7'};
const font=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||font;
function box(b,n,x,y,w,h,c){const r=penpot.createRectangle();r.name=n;r.resize(w,h);r.borderRadius=12;r.fills=[{fillColor:c,fillOpacity:1}];b.appendChild(r);r.x=b.x+x;r.y=b.y+y;return r;}
function text(b,n,x,y,w,h,v,size=14,color=C.ink,weight=400,face=font){const t=penpot.createText(v);t.name=n;t.resize(w,h);face?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.3';t.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(t);t.x=b.x+x;t.y=b.y+y;return t;}
function link(s,d){s.addInteraction('click',{type:'navigate-to',destination:d});}
function action(b,name,y,label,d,primary=false){const r=box(b,'action · '+name,24,y,342,46,primary?C.brand:C.soft);const t=text(b,name,32,y+12,326,24,label,15,primary?C.white:'#3730A3',600);t.align='center';link(r,d);link(t,d);}
const y=Math.ceil(Math.max(...boards.map(b=>b.y+b.height))+80);
function board(name,x,title,sub){const b=penpot.createBoard();b.name=name;b.resize(390,844);b.x=x;b.y=y;b.fills=[{fillColor:C.bg,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;text(b,'产品标识',24,18,342,20,'HERDR POCKET  /  设备配对',12,C.muted,600);text(b,'标题',24,52,342,38,title,24,C.ink,700);text(b,'副标题',24,96,342,40,sub,14,C.sub);text(b,'原型边界',24,805,342,24,'交互原型 · 虚构示例，不执行复制或授权',12,C.muted);return b;}
const handoff=board('S52 · 公开请求交接',0,'交给主机独立审查','本机身份已创建 · 等待主机确认');
const receipt=board('S53 · 原请求结束 · 审查撤销回执',450,'原请求已取消或过期','授权结果未知 · 仅可审查新鲜撤销回执');
const done=board('S54 · 已审查撤销 · 本机身份保留',900,'撤销回执已审查','此原请求不能再授权或连接');
box(handoff,'请求摘要',24,145,342,245,C.white);text(handoff,'摘要标题',40,158,310,24,'原请求 · 有效 10 分钟',16,C.ink,700);
text(handoff,'原请求详情',40,190,310,179,'编号 0123456789abcdef\n       0123456789abcdef\n账号 demo  ·  到期 16:50:00\n主机 SHA256:bbXpuKG6zhzdmnxq256Tlqz\n       FBzRl2f6OOg722cYNbU8\n设备 SHA256:aaaaaaaaaaaaaaaaaaaaaaa\n       aaaaaaaaaaaaaaaaaaaa',12,C.sub,500,mono);
box(handoff,'交接说明',24,403,342,114,C.soft);text(handoff,'交接标题',40,416,310,22,'只交付当前有效的公开请求',15,'#3730A3',700);text(handoff,'交接正文',40,447,310,58,'主机须通过可信渠道独立核对编号、账号与两端指纹，再明确确认授权。',14,C.sub);
action(handoff,'模拟复制',534,'演示：复制公开请求并查看主机确认',helper,true);action(handoff,'审查授权响应',591,'演示：主机已确认 · 审查响应',pair);action(handoff,'结束请求',648,'演示：请求过期或取消后',receipt);
text(handoff,'交接安全',24,718,342,58,'复制失败可手动选择公开请求；过期后不可再交付授权请求。',13,C.sub);
box(receipt,'失效状态',24,146,342,104,C.warnBg);text(receipt,'失效标题',40,159,310,23,'等待已结束 · 原身份仍在',16,C.warning,700);text(receipt,'失效说明',40,190,310,49,'取消不代表主机未授权；迟到授权不能启用连接。',14,C.sub);
box(receipt,'撤销摘要',24,263,342,182,C.white);text(receipt,'撤销标题',40,276,310,24,'待审查 · 撤销回执',16,C.ink,700);text(receipt,'撤销详情',40,308,310,118,'编号 0123456789abcdef\n       0123456789abcdef\n账号 demo  ·  状态 revoked\n核对主机及设备完整指纹与有效期\n来源须通过可信渠道独立确认',13,C.sub);
box(receipt,'审查确认',24,458,342,62,C.soft);text(receipt,'审查确认说明',40,473,310,34,'☐ 已核对来源、原编号与两端指纹',14,'#3730A3',600);
action(receipt,'确认撤销',540,'演示：独立核验并接受撤销',done,true);action(receipt,'回到主机步骤',597,'查看主机确认与撤销步骤',helper);action(receipt,'返回看板',654,'返回主机看板',home);
text(receipt,'撤销安全',24,722,342,60,'错配或过期的回执不能接受；身份和原公钥保留，不自动重试。',13,C.sub);
box(done,'撤销结果',24,150,342,135,C.soft);text(done,'撤销结果标题',40,164,310,24,'已审查匹配的撤销回执',16,'#3730A3',700);text(done,'撤销结果说明',40,196,310,73,'原请求已撤销；本机身份、关联公钥及句柄仍保留，供独立核验。',14,C.sub);
box(done,'连接边界',24,299,342,132,C.warnBg);text(done,'连接边界标题',40,313,310,24,'不会自动连接或删除身份',16,C.warning,700);text(done,'连接边界正文',40,345,310,74,'撤销限制后续认证，不保证断开已建立的 SSH；主机状态仍应独立核验。',14,C.sub);
action(done,'返回主机看板',454,'返回主机看板',home,true);action(done,'查看撤销步骤',511,'查看主机撤销步骤',helper);
text(done,'结果边界',24,588,342,86,'需要新的配对时应另行明确创建。此示例不提供从撤销结果直接连接的出口。',13,C.sub);
// Change only the two existing S51 creation action targets; preserve their appearance.
const old=reviewed.children.filter(s=>['action · 创建设备身份','创建设备身份'].includes(s.name));if(old.length!==2)throw Error('Unexpected S51 action');
for(const s of old){for(const i of [...s.interactions])s.removeInteraction(i);link(s,handoff);}
return {file:penpot.currentFile.id,page:penpot.currentPage.id,added:[handoff,receipt,done].map(b=>({id:b.id,name:b.name})),entry:old.map(s=>s.id)};
