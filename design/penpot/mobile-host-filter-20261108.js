// Run once with the official Penpot MCP execute_code tool. Never change another
// file/page; repeated execution refuses to duplicate this small prototype flow.
const file='b55064db-d93d-80f9-8008-ddd22e6d398f',page='7a22df08-251d-8016-8008-de03541c11da';
if(penpot.currentFile?.id!==file || penpot.currentPage?.id!==page)throw Error('wrong file/page');
const boards=penpot.root.children.filter(s=>s.type==='board');
if(boards.some(s=>s.name.startsWith('主机检索 · ')))throw Error('host filter increment already exists; inspect before retry');
const home=penpotUtils.findShapeById('7a22df08-251d-8016-8008-de045ec11db9');
const identity=penpotUtils.findShapeById('feb2a821-b263-8097-8008-de215d7cb45c');
if(!home || !identity || home.flex || home.grid || identity.flex || identity.grid)throw Error('unexpected existing boards');
const oldRows=['7a22df08-251d-8016-8008-de045ef5da63','7a22df08-251d-8016-8008-de045ef8ee05',
 '7a22df08-251d-8016-8008-de045efe8a3e','7a22df08-251d-8016-8008-de045f017734',
 '7a22df08-251d-8016-8008-de045f068ba0','7a22df08-251d-8016-8008-de045f093f48',
 '7a22df08-251d-8016-8008-de045f0e7897','7a22df08-251d-8016-8008-de045f114d68'].map(id=>penpotUtils.findShapeById(id));
if(oldRows.some(s=>!s || s.interactions.length || s.parent.id!==home.id || s.hidden))throw Error('homepage filter row changed');
const before=oldRows.map(s=>({id:s.id,hidden:s.hidden,name:s.name}));
const face=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||face;
const y=Math.ceil(Math.max(...boards.map(b=>b.y+b.height))+80);
function box(b,name,x,yy,w,h,color,r=12){const s=penpot.createRectangle();s.name=name;s.resize(w,h);s.borderRadius=r;s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+yy;return s;}
function text(b,name,x,yy,w,h,value,size=14,color='#475569',weight=400,font=face){const s=penpot.createText(value);s.name=name;s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.35';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+yy;return s;}
function go(s,b){if(s.parent?.id!==b.id)s.addInteraction('click',{type:'navigate-to',destination:b});}
function button(b,name,yy,label,destination,primary=false){const r=box(b,'action · '+name,24,yy,342,48,primary?'#4F46E5':'#E0E7FF');const t=text(b,name,32,yy+12,326,24,label,14,primary?'#FFFFFF':'#3730A3',600);t.align='center';go(r,destination);go(t,destination);return r;}
function board(name,x){const b=penpot.createBoard();b.name='主机检索 · '+name;b.resize(390,844);b.x=x;b.y=y;b.clipContent=true;b.showInViewMode=true;b.borderRadius=20;b.fills=[{fillColor:'#F8FAFC',fillOpacity:1}];return b;}
const menu=board('搜索与任务状态',0),current=board('当前待处理',450),history=board('历史 B 待核查',900),observe=board('原 B 只读首帧',1800);
const review=identity.clone();review.name='主机检索 · 原 B 身份与连接审查';review.x=1350;review.y=y;review.showInViewMode=true;
function header(b,title,subtitle){text(b,'产品标识',24,20,342,20,'HERDR POCKET / 手机看板',12,'#64748B',600);text(b,'标题',24,52,342,34,title,23,'#0F172A',700);text(b,'说明',24,94,342,44,subtitle,13);}
function search(b,mode,count){
 box(b,'搜索框',24,150,342,48,'#FFFFFF');text(b,'搜索标签',38,158,314,17,'查找主机或会话',12,'#64748B');text(b,'查询示例',38,176,270,22,'work',15,'#0F172A',500);
 const selector=box(b,'任务状态选择器',24,210,342,48,'#EEF2FF');text(b,'任务状态值',38,223,310,22,mode+'  ▾',14,'#3730A3',600);go(selector,menu);
 text(b,'条数',24,270,342,22,`显示 ${count} / 3 台主机 · 名称相同也保留独立身份`,12,'#64748B');
}
header(menu,'查找主机或会话','只筛选本机公开资料，不连接 SSH 或启动网络。');search(menu,'全部任务状态',2);
box(menu,'任务状态菜单',24,304,342,174,'#FFFFFF');
for(const [yy,label,target] of [[310,'全部任务状态',menu],[364,'当前待处理（1）',current],[418,'上次受阻，待核查（1）',history]]){
 const r=box(menu,'option · '+label,32,yy,326,48,'#FFFFFF',8);text(menu,'选项 · '+label,44,yy+13,302,22,label,14,'#0F172A',500);go(r,target);
}
text(menu,'搜索范围',24,500,342,94,'名称、命名会话、地址、当前绑定 provider\n连续子串；忽略大小写与首尾空白。\nN / M 为全目录主机数，不随关键词变化。',14);
button(menu,'保留原新增入口',614,'新增主机与设备配对（原入口）',penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de087525a40f'));
button(menu,'清除全部筛选',674,'清除全部筛选，返回首页',home);
text(menu,'设计边界',24,776,342,42,'可点击示意 · 输入法与搜索行为以应用为准',12,'#64748B');

header(current,'当前待处理','仅 fresh 且仍可精确定位的受阻目标。');search(current,'当前待处理（1）',1);
box(current,'当前主机卡',24,310,342,184,'#FFFFFF');text(current,'当前主机标题',40,326,310,26,'工作站 · Build-01',18,'#0F172A',600);
text(current,'当前公开资料',40,364,310,46,'会话 work · Tailscale · 100.64.0.1',13);
text(current,'当前确认边界',40,417,310,54,'主机报告：当前受阻 1 个\n未报告的阶段不视为在线或已通过。',14,'#3730A3');
button(current,'查看历史筛选',526,'上次受阻，待核查（1）',history);
button(current,'选择状态',586,'更改任务状态',menu);
button(current,'返回首页',646,'返回首页',home);
text(current,'当前设计边界',24,770,342,46,'设计示例，不证明主机在线；不沿用输入许可。',12,'#64748B');

header(history,'上次受阻，待核查','回到首页后，暂停标签留下历史报告；状态待核查。');search(history,'上次受阻，待核查（1）',1);
box(history,'历史主机卡',24,306,342,310,'#FFFFFF');text(history,'历史主机名称',40,320,310,26,'构建机 · Build-02',18,'#0F172A',600);
text(history,'历史公开资料',40,356,310,42,'会话 work · Tailscale · 100.64.0.2',13);
text(history,'历史时效',40,400,310,44,'上次主机报告 · 受阻 2 个\n当前状态未知，不当作现在在线。',13,'#92400E',500);
text(history,'同名 A 身份',40,454,310,42,'同名任务 · 上次受阻\nw2:p1 · term_aaaa',13,'#475569',400,mono);
text(history,'同名 B 身份',40,510,310,42,'同名任务 · 上次受阻\nw3:p1 · term_bbbb',13,'#0F172A',600,mono);
const bHit=box(history,'action · 重新核查原 B',40,564,310,44,'#4F46E5',10);const bLabel=text(history,'重新核查原 B',46,574,298,24,'重新核查 B 原目标',14,'#FFFFFF',600);bLabel.align='center';go(bHit,review);go(bLabel,review);
button(history,'历史更改状态',642,'更改任务状态',menu);button(history,'历史清除全部',702,'清除全部筛选',home);
text(history,'历史设计边界',24,772,342,44,'搜索与状态相交；清文字保留状态，全部清除才重置。',12,'#64748B');

// Reuse the established independent-conditions review, changing only this clone.
const texts=penpotUtils.findShapes(s=>s.type==='text',review);
const byOld=(value)=>texts.find(s=>s.characters===value);
byOld('已授权 · 尚未验证连接').characters='重新核查原 B · 只读观察';
byOld('先确认三项独立条件').characters='再次审查同一目标';
byOld('1 · 组网授权和目标地址可达\n2 · 实际 SSH host key 与预期一致\n3 · SSH 认证成功及 herdr 能力可用').characters='主机 Build-02 · 会话 work\n原目标 w3:p1 · term_bbbb\n原设备身份与当前 Tailscale 绑定\n主机指纹按原保存值核对';
byOld('不会自动授权或自动输入').characters='新标签 · 输入许可不沿用';
byOld('扫码只提供本次请求绑定的资料。主机 helper 已经明确确认过公钥；手机仍需主动发起连接验证。').characters='重新连接后，快照须仍是原 pane 与 terminal，且首帧前仍明确受阻；完成、替换或消失时停止。原草稿保留在旧标签。';
byOld('这是可点击原型分支，不代表实际连通成功。').characters='交互原型 · 不创建身份、不连接主机或发送输入。';
for(const s of penpotUtils.findShapes(s=>s.interactions.length>0,review))for(const i of [...s.interactions])s.removeInteraction(i);
for(const [old,label,target] of [['演示：三项验证通过 → 看板','演示：审查通过 → 原 B 只读',observe],['演示：指纹变化 → 阻止连接','取消，保留历史看板',history],['网络未就绪，保留资料待处理','对照既有身份审查说明',identity]]){
 const t=byOld(old);const bg=review.children.find(s=>s.name==='action · '+old);if(!t || !bg)throw Error('review clone mapping changed');t.characters=label;go(t,target);go(bg,target);
}

header(observe,'原 B · 只读首帧','已重新核查原目标；新标签只读，原草稿不搬入。');
box(observe,'原 B 目标卡',24,150,342,102,'#EEF2FF');text(observe,'原 B 精确身份',40,165,310,78,'Build-02 · work\nw3:p1 · term_bbbb\n原目标 full 已绘制（示例）',14,'#3730A3',600,mono);
box(observe,'原 B 只读终端',24,272,342,238,'#0F172A');text(observe,'原 B 首帧示意',40,294,310,160,'POCKET-BLOCKED-B\nSynthetic waiting process\n\n> 原 B 输出；不是同名 A\n> 观察模式 · 输入已关闭',14,'#F8FAFC',400,mono);
text(observe,'原 B 安全边界',24,532,342,96,'取得首帧前完成或被替换会停止。\n首帧后完成可继续观察新输出。\n不发按键，不调整共享 PTY，不自动恢复输入。',14);
button(observe,'返回历史看板',656,'返回历史看板，保留原目标记录',history);
button(observe,'返回原首页',716,'返回首页',home);
text(observe,'原 B 设计边界',24,786,342,32,'设计原型 · 不代表 SSH 或设备测试通过',12,'#64748B');

// Replace only the old noninteractive status chips, preserving all old host
// cards and navigation. Their hidden states are returned for an exact audit.
for(const s of oldRows)s.hidden=true;
const entry=box(home,'主机检索 · 首页入口',24,94,342,44,'#EEF2FF',10);
const entryText=text(home,'主机检索 · 首页入口文字',38,105,314,24,'查找主机或会话  ·  筛选  ⌕',14,'#3730A3',600);go(entry,menu);go(entryText,menu);
return {file,page,entry:entry.id,entryBoard:home.id,oldRows:before,boards:[menu,current,history,review,observe].map(b=>({id:b.id,name:b.name,x:b.x,y:b.y})),identityReference:identity.id};
