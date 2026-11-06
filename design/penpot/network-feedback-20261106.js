// One-shot increment to the existing v2 page. Refuses wrong file or duplicate boards.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const old=penpot.root.children.filter(s=>s.type==='board');
if(old.length!==26 || old.some(b=>/^S2[7-9]|^S30/.test(b.name)))throw Error('Unexpected boards');
const home=old.find(b=>b.name.startsWith('S01 '));if(!home)throw Error('Missing home');
const C={canvas:'#F8FAFC',card:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',warning:'#92400E',warnBg:'#FEF3C7',border:'#CBD5E1'};
const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,c){const s=penpot.createRectangle();s.resize(w,h);s.fills=[{fillColor:c,fillOpacity:1}];s.borderRadius=10;b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function txt(b,x,y,w,h,v,size=14,color=C.ink,weight=400){const s=penpot.createText(v);s.name=v.split('\n')[0].slice(0,50);s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.4';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function board(id,title,x){const b=penpot.createBoard();b.name=id+' · '+title;b.resize(390,844);b.x=x;b.y=5900;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'network-feedback-20261106',illustration:true}));txt(b,24,18,342,20,'HERDR POCKET  /  交互原型',12,C.muted,600);txt(b,24,55,342,46,title,24,C.ink,700);return b;}
function link(s,d){s.addInteraction('click',{type:'navigate-to',destination:d});}
function button(b,x,y,w,label,d,primary=false){const r=rect(b,x,y,w,44,primary?C.brand:C.card);r.name='action · '+label;const t=txt(b,x+8,y+10,w-16,24,label,14,primary?C.card:C.ink,600);t.align='center';link(r,d);link(t,d);}
function panel(b,y,h,title,body,bg=C.card,color=C.ink){rect(b,24,y,342,h,bg);txt(b,40,y+14,310,25,title,16,color,700);txt(b,40,y+45,310,h-52,body,14,C.sub);}
const list=board('S27','网络配置',0),edit=board('S28','编辑网络与影响',450),preview=board('S29','审查网络迁移',900),result=board('S30','导入后的网络',1350);
panel(list,113,113,'工作网络 · Tailscale','配置已保存 · 桥接不可用\n主机：工作站 01',C.card);
panel(list,238,105,'团队网络 · EasyTier','已停用 · 等待本机配置\n未绑定主机',C.card);
panel(list,355,105,'实验网络 · ZeroTier','配置已保存 · 桥接不可用\n连接不可用，不使用系统网络回退',C.card);
button(list,24,478,166,'编辑工作网络',edit,true);button(list,200,478,166,'审查加密迁移',preview);button(list,24,534,342,'返回主机看板',home);
txt(list,24,608,342,104,'本地配对请求仍可创建和审查。\n连接需等待网络组件与本机授权；保存配置不代表已入网。',13,C.sub);
panel(edit,113,150,'工作网络 · Tailscale','控制地址：使用默认\n设备名称：自动\n仅保存公开配置，不收集设备秘密。');
panel(edit,275,151,'修改前检查影响','工作站 01 引用此网络。保存或停用会停止该主机的连接，之后需重新核对。',C.warnBg,C.warning);
panel(edit,438,102,'保存结果未知','旧连接许可已撤销；先核对当前主机与网络状态。',C.soft,C.brand);
button(edit,24,560,342,'演示保存并返回',list,true);button(edit,24,616,342,'取消，返回网络',list);
panel(preview,113,141,'同名网络 · 新建副本','本机：工作网络 · Tailscale\n导入：工作网络 · Tailscale\n保留原配置；新网络默认停用。',C.warnBg,C.warning);
panel(preview,266,132,'本机授权与主机绑定','导入网络不含设备身份；需要单独认证。导入的主机按选择引用新网络。');
panel(preview,410,115,'终端字号偏好','☐ 应用文件中的字号：18\n默认不勾选，当前字号保持不变。');
button(preview,24,549,342,'演示确认导入',result,true);button(preview,24,605,342,'取消，返回网络',list);
panel(result,113,150,'网络资料已添加 · 示例','工作网络（新） · 已停用\n原同名网络保留；本机身份需单独配置。',C.soft,C.brand);
panel(result,275,132,'连接尚不可用','可继续本地配对审查；连接需网络组件与本机授权，不会自动连接。');
panel(result,419,103,'字号保持原值','未选择导入偏好，本机字号未覆盖。');
button(result,24,548,342,'返回网络配置',list,true);button(result,24,604,342,'返回迁移审查',preview);
for(const b of [list,edit,preview,result])txt(b,24,759,342,50,'交互原型 · 示例资料，不执行配置或连接',12,C.muted);
const hit=rect(home,195,770,97,44,C.canvas);hit.name='网络配置 · 入口';hit.opacity=0.01;link(hit,list);
return {boards:[list,edit,preview,result].map(b=>({id:b.id,name:b.name})),homeEntry:hit.id};
