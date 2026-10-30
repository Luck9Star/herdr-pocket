// One-shot, guarded incremental edit. Never rerun against an already extended page.
// Existing S01-S07 and all V1 boards stay in place; only listed semantics/contrast change.
if (penpot.currentFile?.id !== 'b55064db-d93d-80f9-8008-ddd22e6d398f' || penpot.currentPage?.id !== '7a22df08-251d-8016-8008-de03541c11da') throw Error('Wrong file/page');
if (penpotUtils.findShape(s => s.name.startsWith('S08 ·'), penpot.root)) throw Error('V2 recovery extension already exists');
const C={canvas:'#F8FAFC',card:'#FFFFFF',line:'#E2E8F0',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',success:'#047857',successBg:'#ECFDF5',warning:'#92400E',warningBg:'#FEF3C7',danger:'#BE123C',dangerBg:'#FFF1F2',term:'#0B0F17',termInk:'#E6EDF3'};
const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,color,r=10){const s=penpot.createRectangle();s.resize(w,h);s.fills=[{fillColor:color,fillOpacity:1}];s.borderRadius=r;b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function txt(b,x,y,w,h,value,size=14,color=C.ink,weight=400){const s=penpot.createText(value);s.name=value.split('\n')[0].replace(/[\/]+/g,'-').trim().slice(0,40)||'note';s.resize(w,h);if(font)font.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.45';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function board(id,title,x,y,w=390,h=844){const b=penpot.createBoard();b.name=id+' · '+title;b.resize(w,h);b.x=x;b.y=y;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'v2-recovery',illustration:true}));txt(b,24,18,w-48,22,'HERDR POCKET  /  交互原型',12,C.muted,600);txt(b,24,62,w-48,64,title,24,C.ink,700);return b;}
function link(s,b){s.interactions?.forEach(i=>i.remove());s.addInteraction('click',{type:'navigate-to',destination:b});}
function button(b,y,label,dest,primary=true,x=24,w=342){const r=rect(b,x,y,w,48,primary?C.brand:C.card);r.name='action · '+label;const t=txt(b,x+12,y+13,w-24,24,label,14,primary?C.card:C.ink,600);t.align='center';if(dest){link(r,dest);link(t,dest);}return {r,t};}
function box(b,y,title,body,kind='neutral',h=150){const bg=kind==='danger'?C.dangerBg:kind==='warning'?C.warningBg:kind==='success'?C.successBg:C.card;const col=kind==='danger'?C.danger:kind==='warning'?C.warning:kind==='success'?C.success:C.ink;rect(b,24,y,b.width-48,h,bg);txt(b,40,y+16,b.width-80,28,title,16,col,600);txt(b,40,y+52,b.width-80,h-62,body,14,C.sub);}
const old={};for(const b of penpot.root.children.filter(s=>s.type==='board'))old[b.name.slice(0,3)]=b;
const b08=board('S08','发送结果待核实',0,1940);const b09=board('S09','画面已恢复 · 输入仍锁定',450,1940);const b10=board('S10','主机指纹发生变化',900,1940);const b11=board('S11','窄窗口 · 单输入焦点',1350,1940,720,900);const b12=board('S12','已授权 · 尚未验证连接',2130,1940);const b13=board('S13','主机辅助确认与撤销',2580,1940);const b14=board('S14','审查即将发送的内容',3030,1940);
box(b08,140,'输入已停止','发送时连接中断。服务端是否收到未知；恢复画面也不会补发这次输入。','warning',150);
box(b08,310,'原目标与发送记录','workstation-01 / design-session\nagent-a · epoch 7 · 16:40:12\n原始内容保留为只读记录，不回填草稿。','neutral',170);
rect(b08,24,502,342,108,C.term);txt(b08,40,518,310,80,'上次画面 · 16:40:10\n❯ 等待最新 full snapshot…\n输入锁定 / 无重试按钮',14,C.termInk);
button(b08,638,'恢复可信连接并获取当前画面',b09);button(b08,700,'返回看板',old.S01,false);txt(b08,24,774,342,40,'此处模拟未知结果；不执行 SSH 或发送命令。',12,C.muted);
box(b09,140,'已取得新全量画面','主机身份、session 绑定与当前目标已核对。连接恢复不等于旧输入执行成功。','success',160);
rect(b09,24,322,342,166,C.term);txt(b09,40,340,310,140,'workstation-01 / design-session\nagent-a · 新连接 epoch 8\n\n❯ 最新画面（原型示意）\n历史未知发送仍保留记录',14,C.termInk);
box(b09,510,'请先核实结果','检查原目标的输出与实际状态。只有明确点击下方按钮，才重新进入输入模式。','neutral',126);
button(b09,658,'已核实目标与结果，继续输入',old.S03);button(b09,720,'保持观察',old.S02,false);
box(b10,140,'已阻止连接与输入','实际 SSH host key 与已保存身份不同。不会自动接受新指纹，也不会继续认证或补发输入。','danger',160);
box(b10,320,'通过独立可信渠道核验','旧：SHA256:example-old…（示意）\n新：SHA256:example-new…（示意）\n目标：workstation-01 / ubuntu\n联系主机操作者确认变更原因。','neutral',190);
button(b10,542,'返回配对资料审查',old.S05);button(b10,604,'取消连接，保留旧信任',old.S01,false);txt(b10,24,684,342,72,'本页没有“忽略变化继续”出口。\n示例指纹不能用于真实主机身份核验。',13,C.muted);
box(b12,140,'先确认三项独立条件','1 · 组网授权和目标地址可达\n2 · 实际 SSH host key 与预期一致\n3 · SSH 认证成功及 herdr 能力可用','neutral',190);
box(b12,350,'不会自动授权或自动输入','扫码只提供本次请求绑定的资料。主机 helper 已经明确确认过公钥；手机仍需主动发起连接验证。','warning',170);
button(b12,548,'演示：三项验证通过 → 看板',old.S01);button(b12,610,'演示：指纹变化 → 阻止连接',b10,false);button(b12,672,'网络未就绪，保留资料待处理',old.S05,false);txt(b12,24,748,342,50,'这是可点击原型分支，不代表实际连通成功。',12,C.muted);
box(b13,140,'一次性 helper · 主机端确认','手机先生成独立公钥请求，经可信方式交给主机操作者。主机核对账号、请求与公钥指纹后，明确批准本次追加。','neutral',190);
rect(b13,24,350,342,150,C.term);txt(b13,40,368,310,120,'[示意输出 / 不可执行]\n账户 ubuntu · 设备 phone-demo\n追加一条手机专属 SSH 公钥？\n主机操作者：确认\n生成一次性响应码后退出',13,C.termInk);
button(b13,526,'演示：主机已确认 → 手机扫码',old.S05);box(b13,594,'撤销须在主机端执行','拒绝或取消手机连接不会删除授权。主机 helper 仅移除本次新增记录，不承诺断开已有 SSH 会话。','warning',150);button(b13,764,'返回看板',old.S01,false);
box(b14,140,'目标固定 · 原始换行保留','workstation-01 / design-session / agent-a\n这次发送不自动添加末尾回车。\n多行内容自带的换行仍可能触发命令。','warning',170);
rect(b14,24,332,342,152,C.term);txt(b14,40,350,310,120,'# 示例草稿（原型）\npython3 -m unittest discover\ngit status --short\n\n末尾无额外 Enter / CR',13,C.termInk);
button(b14,514,'演示：仅发送一次 → 返回观察',old.S02);button(b14,576,'演示：发送中断 → 结果待核实',b08,false);button(b14,638,'返回继续编辑',old.S04,false);txt(b14,24,714,342,70,'目标或连接代次变化时预览失效，需重新审查。成功文案只表示服务端已接收，不表示命令完成。',13,C.muted);
// Narrow desktop uses a local viewport; no shared PTY resize.
rect(b11,24,140,672,52,C.card);txt(b11,40,156,440,24,'A · Tailscale    B · EasyTier（观察已暂停）',14,C.sub,600);
rect(b11,24,212,672,430,C.term);txt(b11,44,236,624,32,'A / workstation / design-session / agent-a',16,C.termInk,600);txt(b11,44,284,624,300,'唯一输入焦点：A\n\n❯ 终端内容（示意）\n\n窄窗口只收纳本地面板。\n远端 PTY 保持既有尺寸，横向内容可滚动。\n\nB 标签保留状态与草稿，隐藏期间暂停渲染。',16,C.termInk);
button(b11,668,'切回宽屏分屏',old.S06,true,24,326);button(b11,668,'演示：隐藏标签恢复核验',b09,false,370,326);txt(b11,24,744,672,112,'Tab 焦点顺序：标签 → 模式 → 终端 → 辅助键 → 诊断。\n标签/分屏切换释放组合键并取消未提交 IME，草稿按目标保留。\n所有交互目标至少 44×44；输入焦点同时有边框与文字标记。',14,C.sub);
// Fix only exact known misleading labels and routes, not the accepted layout/palette.
const edits={
'e6d238f0-ac08-8028-8008-de099e93dfd2':'Flutter + terminal_view（五端 A/B 候选）',
'e6d238f0-ac08-8028-8008-de099e9b88bc':'• 使用受控绘制补丁候选；不启动本地 PTY',
'e6d238f0-ac08-8028-8008-de099ea24c22':'• IME 本地组合提交后发送一次；真机仍待验',
'e6d238f0-ac08-8028-8008-de099ea8210a':'Tauri + xterm.js + Rust（五端 A/B 候选）',
'e6d238f0-ac08-8028-8008-de099eaca815':'• Rust 管理远端 SSH/herdr 流和目标生命周期',
'e6d238f0-ac08-8028-8008-de099eb31169':'• 输入按活动目标隔离，快捷键不得绕过输入锁',
'e6d238f0-ac08-8028-8008-de0875b59307':'保存资料并开始连接验证',
'e6d238f0-ac08-8028-8008-de0875bed5b1':'取消与撤销指引',
'e6d238f0-ac08-8028-8008-de0875ba4152':'查看主机确认步骤',
'e6d238f0-ac08-8028-8008-de0875874f2f':'待连接核验',
'e6d238f0-ac08-8028-8008-de08759f7cff':'未验证',
'e6d238f0-ac08-8028-8008-de0875aa18b0':'ubuntu（主机端已确认）',
'e6d238f0-ac08-8028-8008-de07ec445eda':'不添加末尾回车；原有换行仍可能执行',
'e6d238f0-ac08-8028-8008-de07ec4d399a':'发送后转为记录，不自动回填待发草稿',
'e6d238f0-ac08-8028-8008-de07ec215ef2':'UTF-8 · 5 行',
'7a22df08-251d-8016-8008-de045f5bc5ee':'运行中',
'7a22df08-251d-8016-8008-de045f114d68':'网络',
'7a22df08-251d-8016-8008-de045fb630d9':'默认观察 · 输入显式发送 · 布局不改变远端尺寸'};
for(const [id,value] of Object.entries(edits)){const s=penpotUtils.findShapeById(id);if(!s||s.type!=='text')throw Error('Missing expected text '+id);s.characters=value;}
link(penpotUtils.findShapeById('7a22df08-251d-8016-8008-de045ef0143f'),b13);
link(penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de0875b59307'),b12);
link(penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de0875bed5b1'),b13);
link(penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de0875ba4152'),b13);
link(penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de07ec593600'),b14);
link(penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de07ec095892'),old.S02);
const fault=txt(old.S03,24,394,342,44,'演示：发送时断线 → 核实结果',13,C.warning,600);link(fault,b08);
const narrow=txt(old.S06,1110,18,300,44,'窄窗口与隐藏标签恢复 →',13,C.brand,600);link(narrow,b11);
// Readable text aliases preserve original status indicator/brand swatches.
const set=penpot.library.local.tokens.sets.find(s=>s.name==='herdr-pocket/tokens-v2');
for(const [name,value] of Object.entries({mutedReadable:'#64748B',successReadable:'#047857',warningReadable:'#92400E',dangerReadable:'#BE123C',infoReadable:'#0369A1'})){if(!set.tokens.some(t=>t.name==='v2.color.text.'+name))set.addToken({type:'color',name:'v2.color.text.'+name,value});}
const replacements={'#94a3b8':'#64748B','#10b981':'#047857','#f59e0b':'#92400E','#f43f5e':'#BE123C'};let contrastChanges=0;
for(const b of Object.values(old)){for(const t of b.children.filter(s=>s.type==='text')){const c=t.fills?.[0]?.fillColor?.toLowerCase();if(!replacements[c])continue;const previous=b.children.slice(0,b.children.findIndex(s=>s.id===t.id));const cx=t.x+t.width/2,cy=t.y+t.height/2;const bg=previous.filter(s=>s.type==='rectangle'&&s.fills?.[0]?.fillColor&&cx>=s.x&&cx<s.x+s.width&&cy>=s.y&&cy<s.y+s.height).pop();const bc=bg?.fills?.[0]?.fillColor?.toLowerCase()||'#f8fafc';if(['#0b0f17','#111827','#1f2937','#1e293b','#4f46e5'].includes(bc))continue;t.fills=[{fillColor:replacements[c],fillOpacity:1}];contrastChanges++;}}
// Exact 44+ touch areas for existing routed labels, keeping visible labels unchanged.
let expandedTargets=0;for(const b of Object.values(old)){for(const t of b.children.filter(s=>s.type==='text'&&s.interactions?.length)){const dest=t.interactions[0]?.action?.destination;if(!dest)continue;const same=b.children.filter(s=>s.type==='rectangle'&&s.y<=t.y&&s.y+s.height>=t.y+t.height&&s.x<=t.x&&s.x+s.width>=t.x+t.width).pop();if(same&&same.height>=30){link(same,dest);expandedTargets++;}}}
const spec=board('S15','组件状态与可访问性',0,2900,1200,900);
txt(spec,24,132,1152,68,'既有靛蓝操作色与绿色状态色保留。文字使用深色语义变体；状态同时显示文字。\n这是工程交付约束；终端读屏、手机输入法与触控仍需设备验收。',16,C.sub);
const samples=[['Primary · 操作',C.brand,C.card],['Success · 在线',C.successBg,C.success],['Unknown · 输入锁定',C.warningBg,C.warning],['Host key changed · 停止',C.dangerBg,C.danger]];
for(let i=0;i<samples.length;i++){const [name,bg,fg]=samples[i];const p=penpot.createBoard();p.name='v2-'+name;p.resize(260,64);spec.appendChild(p);p.x=spec.x+24+i*288;p.y=spec.y+240;p.fills=[{fillColor:bg,fillOpacity:1}];p.borderRadius=10;txt(p,14,20,232,24,name,14,fg,600);const c=penpot.library.local.createComponent([p]);c.name='v2 / '+name;}
txt(spec,24,344,1152,210,'正常文字对比度目标 ≥ 4.5:1；指示色不能独自传达状态。\n触控命中区 ≥ 44×44；键盘焦点可见，标签与终端仅一个输入目标。\n窄窗口收纳侧栏与分屏；保持远端 PTY 尺寸，不自动发送 resize。\n恢复取得 full snapshot 后仍需人工核实未知发送，不能出现重试或补发按钮。\n扫码配对先有请求和主机确认，再审查响应；保存资料不能当作连接成功。',18,C.ink);
txt(spec,24,600,1152,160,'验证壳读取同一 design-tokens-v2.json；Terminal ANSI 16 色为共同测试基线。\nPenpot 终端字体仅示意，实际继续固定现有 Nerd Font / fixture / 80×24。\n两种 UI 框架都覆盖五端验证，不按手机与桌面提前拆成两个技术栈。',16,C.sub);
button(spec,790,'返回手机看板',old.S01,true,24,342);
return {added:[b08,b09,b10,b11,b12,b13,b14,spec].map(b=>({id:b.id,name:b.name})),contrastChanges,expandedTargets};
