// One-shot incremental Penpot MCP edit; do not rerun on an existing S17.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const old={};for(const b of penpot.root.children.filter(s=>s.type==='board'))old[b.name.slice(0,3)]=b;
if(old.S17||old.S18||old.S19||old.S20||!old.S14||!old.S16)throw Error('Unexpected page state');
const sourceIds=['feb2a821-b263-8097-8008-de21b8539fcb','feb2a821-b263-8097-8008-de21b85608f9'];
const sources=sourceIds.map(id=>penpotUtils.findShapeById(id));
if(sources.some(s=>!s||s.parent?.id!==old.S14.id||s.interactions.length!==1||s.interactions[0].action?.destination?.id!==old.S02.id))throw Error('Unexpected S14 success route');
const C={canvas:'#F8FAFC',card:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',success:'#047857',successBg:'#ECFDF5',warn:'#92400E',warnBg:'#FEF3C7',term:'#0B0F17',termInk:'#E6EDF3'};
const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,c){let s=penpot.createRectangle();s.resize(w,h);s.fills=[{fillColor:c,fillOpacity:1}];s.borderRadius=10;b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function txt(b,x,y,w,h,v,size=14,color=C.ink,weight=400){let s=penpot.createText(v);s.name=v.split('\n')[0].slice(0,50);s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.45';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function board(id,title,x){let b=penpot.createBoard();b.name=id+' · '+title;b.resize(390,844);b.x=x;b.y=3900;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'v2-mobile-20261106',illustration:true}));txt(b,24,18,342,22,'HERDR POCKET  /  交互原型',12,C.muted,600);txt(b,24,62,342,64,title,24,C.ink,700);return b;}
function box(b,y,h,title,body,bg=C.card,color=C.ink){rect(b,24,y,342,h,bg);txt(b,40,y+16,310,28,title,16,color,600);txt(b,40,y+50,310,h-58,body,14,C.sub);}
function button(b,y,label,dest,primary=true){let r=rect(b,24,y,342,48,primary?C.brand:C.card);r.name='action · '+label;let t=txt(b,36,y+13,318,24,label,14,primary?C.card:C.ink,600);t.align='center';for(let s of [r,t])s.addInteraction('click',{type:'navigate-to',destination:dest});}
const s17=board('S17','主机已受理',0),s18=board('S18','隐藏后恢复原目标',450),s19=board('S19','审查导入冲突',900),s20=board('S20','辅助键状态',1350);
box(s17,140,175,'已受理 · 不是命令完成','请求 ID：req-demo-02\npane：pane-demo / terminal：term-demo\n受理：9 bytes · 16:40:12\n请查看终端反馈确认实际结果。',C.successBg,C.success);
box(s17,338,170,'发送记录','Pocket测\n已提交内容移出待发送区；明确拒绝可保留草稿。结果未知时锁定，不自动补发。');
button(s17,548,'返回观察终端',old.S02);button(s17,610,'查看隐藏恢复示意',s18,false);txt(s17,24,760,342,50,'回执与终端均为虚构示意。',12,C.muted);
box(s18,140,170,'观察暂停 · 输入已关闭','workstation-01 / pane-demo / term-demo\n最后画面：16:40:10\n隐藏不停止远端任务；草稿按目标保留。',C.warnBg,C.warn);
box(s18,330,180,'返回后取得新 full','重新核对同一稳定目标，取得当前画面前保持只读；暂停期间的历史不保证补齐。\n不重放任何输入。');
button(s18,548,'演示：新画面已取得',old.S16);button(s18,610,'查看配置冲突审查',s19,false);txt(s18,24,760,342,50,'目标退出或身份变化时重新选择，旧许可不沿用。',12,C.muted);
box(s19,140,180,'审查前不会写入','导入文件：加密主机资料（示意）\n新增 1 · 保留 1 · 替换 1\n替换影响：1 个已保存连接\n缺少认证的主机需要独立配对。',C.warnBg,C.warn);
box(s19,340,170,'逐项选择并确认','新增：Lab-Node-02\n保留：workstation-01\n替换：测试主机（需主动核验）\n不导入秘密，不自动连接或覆盖信任。');
button(s19,536,'演示：确认审查',old.S01);button(s19,598,'取消，不写入',old.S01,false);button(s19,660,'查看辅助键状态',s20,false);txt(s19,24,744,342,68,'错误口令、篡改或不兼容不部分导入；替换后停止相关重试。',12,C.muted);
box(s20,140,170,'Ctrl / Alt · 单次保持','默认  Ctrl   Alt\n保持  Ctrl ✓  → 选择一个基础键\n发送后释放；再次点击可取消。',C.soft,C.brand);
box(s20,330,170,'不可输入时禁用','隐藏、离焦或停止会撤销输入许可。\n辅助键状态与 IME 组合文字分开处理；软键盘和布局变化不改变远端 PTY。');
button(s20,538,'返回逐键输入示意',old.S03);button(s20,600,'查看未知结果',old.S08,false);txt(s20,24,746,342,64,'文字与形状共同区分状态；真实触控、IME 和读屏待验。',12,C.muted);
for(const s of sources){s.interactions.forEach(i=>i.remove());s.addInteraction('click',{type:'navigate-to',destination:s17});}sources[1].characters='演示：仅发送一次 → 查看受理回执';
return {added:[s17,s18,s19,s20].map(b=>({id:b.id,name:b.name})),rerouted:sourceIds};
