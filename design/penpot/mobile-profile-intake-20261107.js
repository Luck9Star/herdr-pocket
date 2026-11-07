// One-shot addition to the existing v2 page. Refuse duplicates; preserve old objects.
const file='b55064db-d93d-80f9-8008-ddd22e6d398f', page='7a22df08-251d-8016-8008-de03541c11da';
if (penpot.currentFile?.id!==file || penpot.currentPage?.id!==page) throw Error('Wrong file/page');
const boards=penpot.root.children.filter(s=>s.type==='board');
if (boards.some(s=>/^S(48|49|50) ·/.test(s.name))) throw Error('Already added; inspect existing state');
const pair=boards.find(s=>s.name.startsWith('S05 ')), network=boards.find(s=>s.name.startsWith('S27 '));
if (!pair || !network || pair.children.some(s=>s.name==='公开资料入口')) throw Error('Missing source or duplicate entry');
const C={canvas:'#F8FAFC',white:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',warn:'#92400E',warnBg:'#FEF3C7'};
const face=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||face;
function box(b,name,x,y,w,h,color) { const r=penpot.createRectangle();r.name=name;r.resize(w,h);r.borderRadius=12;r.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(r);r.x=b.x+x;r.y=b.y+y;return r; }
function text(b,name,x,y,w,h,value,size=14,color=C.ink,weight=400,font=face) {const t=penpot.createText(value);t.name=name;t.resize(w,h);font?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.3';t.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(t);t.x=b.x+x;t.y=b.y+y;return t;}
function link(s,d) {s.addInteraction('click',{type:'navigate-to',destination:d});}
function action(b,name,y,label,target,primary=false) {const r=box(b,'action · '+name,24,y,342,46,primary?C.brand:C.soft);const t=text(b,name,32,y+12,326,24,label,15,primary?C.white:'#3730A3',600);t.align='center';link(r,target);link(t,target);}
const bottom=Math.ceil(Math.max(...boards.map(b=>b.y+b.height))+80);
function board(name,x,title,subtitle) {const b=penpot.createBoard();b.name=name;b.resize(390,844);b.x=x;b.y=bottom;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;text(b,'产品标识',24,18,342,20,'HERDR POCKET  /  首次配对',12,C.muted,600);text(b,'标题',24,52,342,38,title,24,C.ink,700);text(b,'副标题',24,96,342,38,subtitle,14,C.sub);text(b,'原型边界',24,804,342,25,'交互原型 · 示例数据，不会实际配对或连接',12,C.muted);return b;}
const preview=board('S48 · 公开资料预览 · 本地指纹',0,'预览公开连接资料','扫码或粘贴后，仅显示待审查内容。');
const filled=board('S49 · 已填入 · 独立核验',450,'资料已填入表单','尚未信任，设备身份尚未创建。');
const overlay=board('S50 · 覆盖网络待绑定',900,'先绑定本机网络','公开资料已保存 · 尚未选择本机网络');
box(preview,'目标卡',24,144,342,150,C.white);
text(preview,'目标标题',40,158,310,23,'目标与会话',16,C.ink,700);
text(preview,'目标详情',40,190,310,90,'buildbox.example.invalid:22\n账号 demo  ·  网络 direct\n会话 work\nsocket /home/demo/.config/…/work/herdr.sock',13,C.sub);
box(preview,'路径卡',24,306,342,66,C.white);text(preview,'执行路径',40,319,310,40,'herdr  /opt/herdr/bin/herdr',13,C.sub);
box(preview,'指纹卡',24,384,342,123,C.soft);text(preview,'指纹标题',40,397,310,23,'主机公钥指纹 · 本机计算',15,'#3730A3',700);
text(preview,'完整指纹',40,427,310,49,'SHA256:bbXpuKG6zhzdmnxq256TlqzFBzRl\n2f6OOg722cYNbU8',13,C.ink,500,mono);
text(preview,'信任边界',40,480,310,19,'请通过可信渠道独立核对。',13,C.sub);
action(preview,'填入未审查表单',528,'明确填入未审查表单',filled,true);action(preview,'返回配对',585,'取消 · 返回配对',pair);action(preview,'查看网络待绑定',642,'查看 overlay 待绑定示例',overlay);
text(preview,'保留边界',24,711,342,66,'填入不会创建身份、授权或连接。编辑或切页后，旧扫描结果不能覆盖新内容。',13,C.sub);
box(filled,'待核验卡',24,146,342,175,C.white);text(filled,'待核验标题',40,160,310,24,'待核验目标',16,C.ink,700);text(filled,'待核验详情',40,193,310,108,'demo @ buildbox.example.invalid:22\n网络 direct  ·  会话 work\n/home/demo/.config/…/work/herdr.sock\n/opt/herdr/bin/herdr',13,C.sub);
box(filled,'核验提示',24,333,342,122,C.warnBg);text(filled,'核验标题',40,347,310,24,'独立核验主机指纹',16,C.warn,700);text(filled,'核验文字',40,379,310,60,'通过可信渠道比对完整 SHA256 指纹和目标；资料本身不证明身份。',14,C.sub);
box(filled,'未勾选',24,468,342,62,C.white);text(filled,'审查未确认',40,484,310,33,'☐ 我已独立核验账号、公钥与会话',14,C.ink,600);
action(filled,'示例确认后配对',550,'演示：核验后继续配对',pair,true);action(filled,'返回资料预览',607,'返回资料预览',preview);
text(filled,'创建边界',24,684,342,88,'实际流程需先勾选独立核验，再明确创建设备身份；主机授权与 SSH 连接仍是后续独立步骤。',13,C.sub);
box(overlay,'网络提示卡',24,148,342,126,C.warnBg);text(overlay,'待绑定标题',40,162,310,25,'Tailscale · 尚未绑定',16,C.warn,700);text(overlay,'待绑定说明',40,195,310,66,'此资料声明覆盖网络，但未选择本机网络。不会按名称自动绑定，也不会回退系统直连。',14,C.sub);
box(overlay,'离线配对卡',24,287,342,114,C.white);text(overlay,'离线标题',40,301,310,24,'离线配对可继续',16,C.ink,700);text(overlay,'离线说明',40,333,310,55,'可核验目标、创建设备身份并审查授权；这些操作不代表网络已连通。',14,C.sub);
box(overlay,'连接前置卡',24,414,342,100,C.soft);text(overlay,'连接前置',40,428,310,24,'连接前先选择匹配网络',16,'#3730A3',700);text(overlay,'连接前置说明',40,459,310,43,'在网络管理中创建或启用相同 provider，回主机明确绑定。',13,C.sub);
action(overlay,'去网络配置',534,'去网络配置',network,true);action(overlay,'继续离线配对',591,'继续离线配对',pair);action(overlay,'返回资料预览',648,'返回公开资料预览',preview);
text(overlay,'网络边界',24,720,342,58,'首次绑定后，后续更换或解除仍需明确操作；本页不自动发起连接。',13,C.sub);
// New entry only; does not replace any existing S05 interactions.
const entry=box(pair,'公开资料入口',20,784,350,40,C.soft);const label=text(pair,'公开资料入口文字',28,793,334,22,'扫码／粘贴公开资料 · 查看示例',14,'#3730A3',600);label.align='center';link(entry,preview);link(label,preview);
return {file,page,added:[preview,filled,overlay].map(b=>({id:b.id,name:b.name})),entry:entry.id};
