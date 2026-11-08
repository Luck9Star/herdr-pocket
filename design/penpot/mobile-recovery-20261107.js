// One-shot increment, not a synchronization command. Preserve all existing shapes.
if (penpot.currentFile?.id !== 'b55064db-d93d-80f9-8008-ddd22e6d398f' || penpot.currentPage?.id !== '7a22df08-251d-8016-8008-de03541c11da') throw Error('Wrong file/page');
const old = penpot.root.children.filter(s => s.type === 'board');
if (old.length !== 30 || old.some(s => /^S3[1-8] /.test(s.name))) throw Error('Unexpected existing boards; inspect before retry');
if (!storage.recoveryBefore || storage.recoveryBefore.length !== 1008) throw Error('Missing original-object snapshot');
const home = old.find(s => s.name.startsWith('S01 ')), network = old.find(s => s.name.startsWith('S27 ')), draft = old.find(s => s.name.startsWith('S04 '));
if (!home || !network || !draft) throw Error('Missing original destinations');
const C = {canvas:'#F8FAFC',card:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',warning:'#92400E',warnBg:'#FEF3C7',line:'#CBD5E1'};
const font = penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,color) { const r=penpot.createRectangle();r.resize(w,h);r.fills=[{fillColor:color,fillOpacity:1}];r.borderRadius=12;b.appendChild(r);r.x=b.x+x;r.y=b.y+y;return r; }
function text(b,x,y,w,h,value,size=14,color=C.ink,weight=400) { const t=penpot.createText(value);t.name=value.split('\n')[0];t.resize(w,h);font?.applyToText(t);t.fontSize=String(size);t.fontWeight=String(weight);t.lineHeight='1.4';t.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(t);t.x=b.x+x;t.y=b.y+y;return t; }
function board(id,title,x,y) { const b=penpot.createBoard();b.name=id+' · '+title;b.resize(390,844);b.x=x;b.y=y;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'mobile-recovery-20261107',illustration:true,accessibility:'44px targets, status text plus color, explicit confirmation; not screen-reader/device proof'}));text(b,24,18,342,20,'HERDR POCKET  /  手机恢复',12,C.muted,600);text(b,24,55,342,44,title,24,C.ink,700);text(b,24,778,342,42,'交互原型 · 示例状态，不执行连接或设备操作',12,C.muted);return b; }
function link(s,d) { s.addInteraction('click',{type:'navigate-to',destination:d}); }
function button(b,x,y,w,label,d,primary=false) { const r=rect(b,x,y,w,44,primary?C.brand:C.card);r.name='action · '+label;const t=text(b,x+8,y+10,w-16,24,label,14,primary?C.card:C.ink,600);t.align='center';link(r,d);link(t,d);return r; }
function panel(b,y,h,title,body,bg=C.card,titleColor=C.ink) { const r=rect(b,24,y,342,h,bg);r.name='card · '+title;text(b,40,y+14,310,27,title,16,titleColor,700);text(b,40,y+48,310,h-55,body,14,C.sub); }
const stale=board('S31','连接中断 · 保留旧看板',0,6900);
const retained=board('S32','找回原目标的草稿',450,6900);
const paste=board('S33','粘贴前，保留已有草稿',900,6900);
const pending=board('S34','共享设备 · 原操作待完成',1350,6900);
const confirm=board('S35','确认处理原设备记录',0,7900);
const unknown=board('S36','处理结果尚未确认',450,7900);
const cleared=board('S37','原操作已结束 · 示例',900,7900);
const copied=board('S38','原草稿已复制 · 示例',1350,7900);
panel(stale,113,126,'旧状态 · 当前不可选择','Workstation-01 / design-session\n上次已核验看板：16:40:12\n连接尝试不刷新此时间。',C.warnBg,C.warning);
panel(stale,251,113,'上次待处理 1 · agent-a','状态来自上次主机快照，可能已经变化。\n重新核验前不开放目标选择。');
panel(stale,376,105,'上次运行中 · agent-b','保留原分组，不以空列表表示没有任务。\n终端画面时间与看板同步时间分开。');
button(stale,24,505,342,'查看保留的未发送草稿',retained,true);
button(stale,24,561,342,'演示：核验后返回可选看板',home);
button(stale,24,617,342,'返回网络配置',network);
text(stale,24,695,342,58,'重连由用户发起。旧画面不开放输入，也不会自动补发之前的内容。',13,C.sub);
panel(retained,113,125,'只读 · 不授予发送权限','Workstation-01 / design-session\nagent-a · terminal t-7\n来源：此原目标的未发送编辑内容。',C.soft,C.brand);
panel(retained,250,154,'原草稿','请先检查测试结果。\n不要修改主分支。');
panel(retained,416,112,'目标消失也可复制','不会转交同名 agent 或其他终端。\n已发送但结果未知的正文单独核查。',C.warnBg,C.warning);
button(retained,24,552,342,'演示复制原草稿',copied,true);button(retained,24,608,342,'返回旧看板',stale);
text(retained,24,690,342,60,'仅在本页内存保留。关闭标签前请自行保存；清除草稿仍需另行明确确认。',13,C.sub);
panel(paste,113,110,'当前原目标','Workstation-01 / design-session\nagent-a · terminal t-7');
panel(paste,235,112,'已有草稿 · 保持不变','请先检查测试结果。');
panel(paste,359,112,'待粘贴内容 · 尚未发送','\n不要修改主分支。',C.soft,C.brand);
button(paste,24,495,342,'追加到本地草稿 · 演示',retained,true);
button(paste,24,551,166,'取消 · 保留原稿',draft);button(paste,200,551,166,'返回终端草稿',draft);
text(paste,24,625,342,105,'实际界面另提供“替换草稿”。追加、替换都只修改本地草稿；目标、焦点或草稿变化后，旧粘贴审查失效。\n发送仍需独立预览和确认。',13,C.sub);
panel(pending,113,133,'原设备记录 · 已开始删除','记录编号：…a7c9（示例）\n阶段：记录已移除，清理尚未确认。\n不是“可以新建身份”的空状态。',C.warnBg,C.warning);
panel(pending,258,143,'完整影响范围','实验网络 · 启用\n旧实验网络 · 已停用\nBackup-03 · 归档主机（仍计入范围）');
panel(pending,413,100,'恢复只针对原操作','无原删除记录时拒绝恢复，不能改为删除当前新身份。');
button(pending,24,537,342,'第 1 步 · 审查原设备操作',confirm,true);button(pending,24,593,342,'返回网络配置',network);
text(pending,24,676,342,74,'仅演示已读取待定记录的情况。当前测试包未接入这批设备恢复能力；未绑定组件时显示不可用。',13,C.sub);
panel(confirm,113,120,'第 2 步 · 再次核对','记录编号：…a7c9（示例）\n阶段：记录已移除，清理尚未确认。');
panel(confirm,245,143,'影响全部共享网络与主机','实验网络、旧实验网络（停用）\nBackup-03（归档）\n不会复制、替换或导出设备身份。');
panel(confirm,400,112,'仅继续原待完成操作','记录、阶段或影响范围变化后重新审查。相关连接仍占用身份时拒绝处理。',C.warnBg,C.warning);
button(confirm,24,536,342,'确认继续原操作 · 演示未知结果',unknown,true);button(confirm,24,592,342,'取消 · 返回重新读取',pending);
text(confirm,24,676,342,72,'创建恢复与放弃使用同一审查模型：恢复只接纳已安装记录，放弃只清理未安装记录，不自动改做另一操作。',13,C.sub);
panel(unknown,113,145,'未确认 · 不自动重试','请求可能已经完成，也可能仍在处理。\n关闭、切后台或重建页面都不是取消证明。\n保持原记录引用，仅重新读取。',C.warnBg,C.warning);
panel(unknown,270,138,'先核对实际读回状态','仍有待定记录 → 重新审查原阶段。\n设备与待定记录全为空 → 才确认原移除结束。\n有新身份 → 不能按旧确认继续删除。');
button(unknown,24,432,342,'演示读回：仍待定，重新审查',pending,true);
button(unknown,24,488,342,'演示读回：原记录已清理',cleared);
button(unknown,24,544,342,'关闭并返回网络配置',network);
text(unknown,24,637,342,104,'这两个出口仅演示不同读回结果，不是“重试”或“强制成功”按钮。实际应用由重新读取的状态决定可用操作。',13,C.sub);
panel(cleared,113,140,'已核对：原移除结束','设备记录：无\n待定创建：无\n待定删除：无',C.soft,C.brand);
panel(cleared,265,125,'没有自动新建或连接','公开网络配置仍保留。创建新的本机身份需要独立明确操作，再核对授权与连通。');
button(cleared,24,414,342,'返回网络配置',network,true);button(cleared,24,470,342,'返回恢复示例',pending);
text(cleared,24,558,342,91,'示例不代表 ZeroTier 节点、SSH 或 herdr 已连接，也不是当前 APK 的运行证据。',13,C.sub);
panel(copied,113,122,'仅复制了原草稿 · 示例','原内容仍保留在本页。\n没有连接、发送或改变目标。',C.soft,C.brand);
panel(copied,247,154,'Workstation-01 / design-session','agent-a · terminal t-7\n\n请先检查测试结果。\n不要修改主分支。');
button(copied,24,425,342,'返回原草稿',retained,true);button(copied,24,481,342,'返回旧看板',stale);button(copied,24,537,342,'查看粘贴审查示例',paste);
text(copied,24,635,342,98,'实际系统复制失败时保留原稿并提示手动复制。该原型按钮不操作系统剪贴板。',13,C.sub);
button(home,24,708,342,'连接中断后的恢复示例',stale);
const entry=rect(network,24,355,342,105,C.canvas);entry.opacity=0.01;entry.name='shared-device-entry · ZeroTier card';link(entry,pending);
const arrow=text(network,335,363,18,28,'›',24,C.brand,600);link(arrow,pending);
storage.recoveryBoards=[stale,retained,paste,pending,confirm,unknown,cleared,copied];
return {added:storage.recoveryBoards.map(b=>({id:b.id,name:b.name})),entry:entry.id,oldShapeCount:storage.recoveryBefore.length};
