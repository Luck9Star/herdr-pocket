if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f')throw new Error('Wrong file');
const hp=storage.hp;
const index=penpot.createBoard();index.name='START · 原型导航与验证边界';index.resize(1280,900);index.x=-1500;index.y=-1100;index.fills=[{fillColor:hp.colors.surface,fillOpacity:1}];index.showInViewMode=true;hp.boards.START=index;
hp.text(index,40,36,1200,54,'herdr-pocket / 核心交互原型',32,'ink');
hp.text(index,40,110,1200,62,'先走通关键流程，再用真实终端结果收敛视觉。\n所有主机、指纹、状态和终端内容均为虚构示例。',18,'muted');
const journeys=[['J1 · 手机与主机 helper 配对','P1-empty','公钥请求 → 主机确认 → 扫码核验 → 主动连接'],['J2 · 完整终端与手机输入','P3-observe','观察 / 逐键 / 草稿、键盘、组合键和粘贴'],['J3 · 跨网络标签与恢复','P4-tabs','隐藏恢复、发送未知、指纹变化和目标失效'],['P1 · 主机会话看板','P1-dashboard','当前状态与上次状态分开；失联不为空列表'],['P5 · 三网络配置','P5-networks','节点与主机连接分开；停用前预览影响'],['P6 · 加密配置迁移','P6-export','排除秘密、导入审查、冲突与完整失败'],['P7 · 字体诊断示意','P7-font','Nerd Font、CJK、emoji 须用验证壳实测'],['D1 / D2 · 桌面工作台','D1-workspace','分屏、焦点隔离、窄窗口，不隐式 resize'],['异常 · 输入结果未知','P4-unknown','停止发送、不重试、恢复后核实原目标']];
journeys.forEach(([title,to,desc],i)=>{const x=40+(i%3)*406,y=220+Math.floor(i/3)*180;hp.rect(index,x,y,382,152,'panel');hp.text(index,x+20,y+20,340,34,title,18,'ink');hp.text(index,x+20,y+62,340,58,desc,14,'muted');const hit=hp.rect(index,x,y,382,152,'#FFFFFF');hit.fills=[{fillColor:'#FFFFFF',fillOpacity:0.001}];hit.name='打开/'+title;hp.links.push({shape:hit,from:'START',label:title,to});});
hp.text(index,40,792,1200,64,'验证边界：这是低 / 中保真交互稿，不证明真实扫码、SSH、IME、字体列宽、网络并发或性能通过。\n每页底部可返回此导航；Penpot 原型中的成功 / 失败按钮只是场景演示入口。',14,'muted');
for(const [id,b] of Object.entries(hp.boards)){
 if(id==='START')continue;
 const footer=penpotUtils.findShapes(s=>s.type==='text'&&s.characters==='交互原型 · 虚构数据 · 运行能力未验证',b)[0];
 footer.characters='原型导航 ↗ · 虚构数据 · 能力未验证';hp.links.push({shape:footer,from:id,label:'原型导航',to:'START'});
}
for(const l of hp.links){if(!hp.boards[l.to])throw new Error('Missing board '+l.to);l.shape.addInteraction('click',{type:'navigate-to',destination:hp.boards[l.to]});}
// Penpot 2.19.0 createFlow rejects Board proxies with this 2.15.4 MCP API.
// The first interactions create default flows; safely retarget these existing flows.
const flowTargets=[['J1 · 手机配对','P1-empty'],['J2 · 终端与输入','P3-observe'],['J3 · 多标签与恢复','P4-tabs'],['P5 · 三网络配置','P5-networks'],['P6 · 配置导入导出','P6-export'],['00 · 原型导航','START']];
if(penpot.currentPage.flows.length!==flowTargets.length)throw new Error('Unexpected flow count; inspect before assigning');
penpot.currentPage.flows.forEach((f,i)=>{f.name=flowTargets[i][0];f.startingBoard=hp.boards[flowTargets[i][1]];});
// Keep a visible component reference board; do not disguise static examples as device proof.
const comp=penpot.createBoard();comp.name='LIBRARY · 状态与无障碍规格';comp.resize(1280,1050);comp.x=-1500;comp.y=0;comp.fills=[{fillColor:hp.colors.surface,fillOpacity:1}];comp.showInViewMode=false;
hp.text(comp,32,24,1216,45,'小型组件库 / 状态与无障碍',28,'ink');
hp.text(comp,32,82,1216,100,'触控目标 ≥ 44 × 44；正文默认 14 / 16，可放大。状态同时使用文字、图标与颜色。\n焦点边框 2 px；手机顺序：标题与目标 → 状态 → 主操作 → 辅助操作 → 导航。\n终端与应用快捷键分开；切焦点或失联取消组合态；隐藏恢复必须等待新 full。',16,'muted');
Object.entries(hp.components).forEach(([key,c],i)=>{const shape=c.mainInstance();comp.appendChild(shape);shape.x=comp.x+32+(i%3)*410;shape.y=comp.y+220+Math.floor(i/3)*125;hp.text(comp,32+(i%3)*410,190+Math.floor(i/3)*125,380,25,key,12,'muted');});
penpot.viewport.zoomIntoView([index]);
return {file:penpot.currentFile.id,page:penpot.currentPage.id,boards:Object.fromEntries(Object.entries(hp.boards).map(([k,b])=>[k,b.id])),screenCount:Object.keys(hp.boards).length,interactions:hp.links.length,components:penpot.library.local.components.length,tokens:penpot.library.local.tokens.sets.reduce((n,s)=>n+s.tokens.length,0),flows:penpot.currentPage.flows.map(f=>({id:f.id,name:f.name})),penpotVersion:penpot.version};
