// Official Penpot MCP execute_code source. Same v2 file/page only; refuses reruns.
// Static synthetic design examples, not device state or native/network evidence.
const file='b55064db-d93d-80f9-8008-ddd22e6d398f',page='7a22df08-251d-8016-8008-de03541c11da';
if(penpot.currentFile?.id!==file || penpot.currentPage?.id!==page)throw Error('wrong file/page');
const prefix='设备影响 · ';
const boards=penpot.root.children.filter(s=>s.type==='board');
if(boards.some(b=>b.name.startsWith(prefix)))throw Error('device impact increment already exists; inspect before retry');
const original=penpotUtils.findShapeById('2a5fd934-a163-8057-8008-e823088d7aeb');
const confirmation=penpotUtils.findShapeById('2a5fd934-a163-8057-8008-e823089e01ed');
if(!original || !confirmation || original.flex || original.grid)throw Error('original device review changed');
const ids={
 brand:'2a5fd934-a163-8057-8008-e82308900666',title:'2a5fd934-a163-8057-8008-e82308953b13',
 footer:'2a5fd934-a163-8057-8008-e8230899e968',warning:'2a5fd934-a163-8057-8008-e824e8eb523d',
 warningTitle:'2a5fd934-a163-8057-8008-e824e8ee5f39',body:'2a5fd934-a163-8057-8008-e824e8f3a140',
 card:'2a5fd934-a163-8057-8008-e824e8f8ea16',cardTitle:'2a5fd934-a163-8057-8008-e824e8fc2740',
 cardBody:'2a5fd934-a163-8057-8008-e824e9011349',
 primary:'2a5fd934-a163-8057-8008-e824e9122945',primaryText:'2a5fd934-a163-8057-8008-e824e9152498',
 secondary:'2a5fd934-a163-8057-8008-e824e91bf32f',secondaryText:'2a5fd934-a163-8057-8008-e824e91ece2b',
 note:'2a5fd934-a163-8057-8008-e824e925327a'
};
const refs=Object.fromEntries(Object.entries(ids).map(([key,id])=>[key,penpotUtils.findShapeById(id)]));
if(Object.values(refs).some(s=>!s || s.parent?.id!==original.id))throw Error('original components changed');
if(refs.cardTitle.characters!=='完整影响范围' || [refs.card,refs.cardTitle,refs.cardBody].some(s=>s.interactions.length))throw Error('impact entry already changed');
const snapshot=b=>({id:b.id,name:b.name,children:b.children.map(s=>({id:s.id,name:s.name,text:s.characters,x:s.x,y:s.y,width:s.width,height:s.height,hidden:s.hidden,to:s.interactions.map(i=>({trigger:i.trigger,type:i.action.type,destination:i.action.destination?.id}))}))});
const before={original:snapshot(original),confirmation:snapshot(confirmation)};
const y=Math.ceil(Math.max(...boards.map(b=>b.y+b.height))+80);
function board(name,x){const b=penpot.createBoard();b.name=prefix+name;b.resize(390,844);b.x=x;b.y=y;b.clipContent=true;b.showInViewMode=true;b.borderRadius=original.borderRadius;b.fills=original.fills;return b;}
function copy(b,key,name,x,yy,w,h,value){const s=refs[key].clone();for(const i of [...s.interactions])s.removeInteraction(i);s.name=name;b.appendChild(s);s.resize(w,h);s.x=b.x+x;s.y=b.y+yy;if(value!==undefined)s.characters=value;return s;}
function go(s,b){s.addInteraction('click',{type:'navigate-to',destination:b});}
function button(b,name,yy,label,target,primary=false){const r=copy(b,primary?'primary':'secondary','action · '+name,24,yy,342,44);const t=copy(b,primary?'primaryText':'secondaryText',name,32,yy+10,326,24,label);go(r,target);go(t,target);return r;}
function heading(b){copy(b,'brand','产品标识',24,18,342,20,'HERDR POCKET / 共享设备');copy(b,'title','标题',24,55,342,44,'共享设备审查');copy(b,'footer','原型边界',24,778,342,42,'交互原型 · 合成资料，不执行设备或网络操作');}
function disabled(b,yy){const r=copy(b,'secondary','设备写操作 · 不可用',24,yy,342,44);r.fills=[{fillColor:'#E2E8F0',fillOpacity:1}];const t=copy(b,'secondaryText','设备写操作不可用',32,yy+10,326,24,'创建 / 恢复 / 放弃 / 移除均不可用');t.fills=[{fillColor:'#475569',fillOpacity:1}];}
const known=board('能力不可用 · 范围已核对',0),unknown=board('目录受阻 · 范围未知',450);
heading(known);heading(unknown);
copy(known,'warning','能力不可用提示',24,113,342,130);
copy(known,'warningTitle','能力状态',40,127,310,27,'ZeroTier 身份能力不可用');
copy(known,'body','能力说明',40,161,310,75,'设备状态未知，不表示没有身份。\n当前不能创建、恢复或移除设备；\n仍可核对本机保存的影响范围。');
copy(known,'card','完整影响范围卡',24,257,342,218);
copy(known,'cardTitle','已核对范围标题',40,271,310,27,'已核对：2 个网络 · 3 台主机');
copy(known,'cardBody','完整影响范围',40,307,310,155,'实验网络 · 启用\n旧实验网络 · 已停用\nWorkstation-01 · 启用主机\nBackup-03 · 停用 / 归档主机\nLegacy-04 · 旧类型 ZeroTier 主机\n停用与旧类型仍计入本次范围。');
disabled(known,491);
copy(known,'note','本地范围边界',24,549,342,44,'列表来自已读回的本机目录，\n不表示网络在线或主机已连接。');
button(known,'刷新状态与影响范围',613,'刷新状态与影响范围',unknown,true);
button(known,'返回原设备审查',669,'返回原设备审查',original);
copy(known,'note','刷新示例说明',24,727,342,37,'刷新分支演示读取受阻；不重发任何设备写入。');

copy(unknown,'warning','范围未知提示',24,113,342,155);
copy(unknown,'warningTitle','范围未知标题',40,127,310,27,'影响范围未知');
copy(unknown,'body','读取受阻说明',40,161,310,100,'目录或主机资料读取失败，\n或目录正在写入，暂不能核对。\n网络：未知 · 主机：未知\n未知不计为 0。');
copy(unknown,'card','等待读回卡',24,282,342,162);
copy(unknown,'cardTitle','等待读回标题',40,296,310,27,'读回完整范围后再审查');
copy(unknown,'cardBody','等待读回说明',40,332,310,105,'旧列表不能代替当前影响范围。\n不会继续设备写入，也不自动\n重试原操作。读取成功后，\n重新展示完整网络与主机列表。');
disabled(unknown,464);
button(unknown,'重新读取',536,'重新读取',known,true);
button(unknown,'未知范围返回',592,'返回原设备审查',original);
copy(unknown,'note','读回能力边界',24,666,342,82,'读回范围后，ZeroTier 身份能力仍可能不可用。\n以当前能力和当前目录为准；\n不把未知状态当作空记录。');

// S34 has no free 44 px row. Reuse its entire existing 143 px impact card;
// only this title and three click bindings change. All original buttons remain.
refs.cardTitle.characters='完整影响范围 · 查看状态 ›';
refs.cardTitle.fills=[{fillColor:'#3730A3',fillOpacity:1}];
for(const s of [refs.card,refs.cardTitle,refs.cardBody])go(s,known);
return {file,page,before,entry:{board:original.id,shapes:[refs.card.id,refs.cardTitle.id,refs.cardBody.id],height:refs.card.height},boards:[known,unknown].map(b=>({id:b.id,name:b.name,x:b.x,y:b.y})),confirmationUnchanged:JSON.stringify(snapshot(confirmation))===JSON.stringify(before.confirmation)};
