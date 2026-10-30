// One-time historical supplement. Refuse duplicate boards on a populated file.
if(penpotUtils.findShapes(s=>s.type==='board'&&s.name.startsWith('P1-loading · '),penpot.root).length)throw new Error('Supplement already applied');
if(penpot.currentFile.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f')throw new Error('Wrong file');storage.hp={boards:{},links:[],components:{},tokens:{},screenData:[]};const hp=storage.hp;hp.colors={"surface": "#F6F7F8", "panel": "#FFFFFF", "ink": "#15252B", "muted": "#4D626B", "line": "#D5DEE2", "accent": "#176859", "accentSoft": "#E6F3EF", "warning": "#714A0A", "warningSoft": "#FFF3D7", "danger": "#A52F35", "dangerSoft": "#FCECEE", "terminal": "#142329", "terminalInk": "#D8E5E7", "focus": "#007D70"};for(const b of penpot.root.children.filter(s=>s.type==='board'))hp.boards[b.name.split(' · ')[0]]=b;for(const key of ['action/primary','action/secondary','action/disabled','mode/observe','mode/direct','mode/draft','tab/focused','tab/paused'])hp.components[key]=penpot.library.local.components.find(c=>c.name===key.split('/')[1]);hp.font=penpot.fonts.findByName('Noto Sans SC');hp.mono=penpot.fonts.findByName('Roboto Mono');hp.rect=function(parent,x,y,w,h,color='panel',radius=8){
 const r=penpot.createRectangle();r.name='surface/'+color;r.resize(w,h);r.borderRadius=radius;r.fills=[{fillColor:hp.colors[color]||color,fillOpacity:1}];if(parent)parent.appendChild(r);r.x=(parent?.x||0)+x;r.y=(parent?.y||0)+y;if(hp.tokens[color])r.applyToken(hp.tokens[color],['fill']);return r;
};
hp.text=function(parent,x,y,w,h,str,size=14,color='ink',mono=false){
 const t=penpot.createText(str);t.name=str.split('\n')[0].slice(0,50);t.resize(w,h);t.growType='fixed';(mono?hp.mono:hp.font)?.applyToText(t);t.fontSize=String(size);t.lineHeight='1.45';t.fills=[{fillColor:hp.colors[color]||color,fillOpacity:1}];if(parent)parent.appendChild(t);t.x=(parent?.x||0)+x;t.y=(parent?.y||0)+y;if(hp.tokens[color])t.applyToken(hp.tokens[color],['fill']);return t;
};
hp.instance=function(parent,key,x,y,label,w){
 const i=hp.components[key].instance();parent.appendChild(i);i.x=parent.x+x;i.y=parent.y+y;i.name=key+(label?'/'+label:'');if(w)i.resize(w,i.height);
 const text=penpotUtils.findShapes(s=>s.type==='text',i)[0];if(text&&label){text.characters=label;text.resize((w||i.width)-32,32);text.x=i.x+16;text.y=i.y+12;}return i;
};
hp.button=function(b,label,to,x,y,w,primary=true){const i=hp.instance(b,primary?'action/primary':'action/secondary',x,y,label,w);hp.links.push({shape:i,from:b.name.split(' · ')[0],label,to});return i;};
hp.terminal=function(b,x,y,w,h,target,mode){
 hp.rect(b,x,y,w,h,'terminal');
 hp.text(b,x+16,y+14,w-32,22,target,12,'terminalInk');
 hp.text(b,x+16,y+48,w-32,h-60,'› herdr observe — 交互示意\n\n  agent-a  ·  waiting for input\n\n  文件与状态已更新。\n  请检查当前目标再继续。\n\n  中文  é  🙂    \n\n  ▍',13,'terminalInk',true);
};
hp.board=function(screen,index){
 const w=screen.width||390,h=screen.height||844;
 const b=penpot.createBoard();b.name=screen.id+' · '+screen.title;b.resize(w,h);b.x=(index%7)*1500;b.y=Math.floor(index/7)*1100;b.fills=[{fillColor:hp.colors.surface,fillOpacity:1}];b.borderRadius=16;b.clipContent=true;b.showInViewMode=true;
 hp.boards[screen.id]=b;hp.screenData.push(screen);b.setPluginData('herdr-pocket',JSON.stringify({screen:screen.id,family:screen.family,stage:'interaction-prototype',validation:'not-device-evidence'}));
 const desktop=screen.kind==='desktop';const helper=screen.kind==='helper';
 hp.text(b,24,20,w-48,20,helper?'HOST HELPER · 仅示意':desktop?'HERDR-POCKET / REMOTE WORKSPACE':'16:40                         HERDR-POCKET',11,'muted');
 hp.text(b,24,57,w-48,42,screen.title,24,'ink');hp.text(b,24,106,w-48,44,screen.subtitle,13,'muted');
 let bodyY=162;
 if(desktop){
   const side=w>1000?212:0;if(side){hp.rect(b,24,162,188,535,'panel');hp.text(b,40,180,156,260,'主机\n\n● 工作站\n  Tailscale\n\n● 实验机\n  EasyTier\n\n◷ 备用机\n  ZeroTier',14,'ink');}
   const start=24+side,avail=w-start-24,pane=side?(avail-16)/2:avail;
   hp.instance(b,'tab/focused',start,162,'A · 工作站',160);if(side)hp.instance(b,'tab/paused',start+176,162,'B · 实验机',160);
   hp.terminal(b,start,224,pane,360,'A / design-session / agent-a','观察');
   if(side)hp.terminal(b,start+pane+16,224,pane,360,'B / build-session / agent-b','观察');
   const fx=screen.focus==='B'&&side?start+pane+16:start;const ring=hp.rect(b,fx,224,pane,360,'#FFFFFF',8);ring.fills=[];ring.strokes=[{strokeColor:hp.colors.focus,strokeWidth:3,strokeStyle:'solid',strokeAlignment:'inner'}];
   hp.text(b,start,602,avail,92,screen.body.join('\n'),14,'muted');
 }else if(screen.kind==='terminal'||screen.kind==='draft'){
   const isDraft=screen.kind==='draft';hp.instance(b,screen.mode==='逐键输入'?'mode/direct':isDraft?'mode/draft':'mode/observe',24,158,screen.mode||'观察',w-48);
   const th=screen.keyboard?200:260;hp.terminal(b,24,216,w-48,th,screen.subtitle,screen.mode);
   let y=screen.keyboard?430:490;
   if(isDraft){hp.rect(b,24,430,w-48,92,'panel');hp.text(b,36,442,w-72,74,'本地草稿\n请先运行回归测试，再汇报失败项。',14,'ink');y=535;}
   else {hp.text(b,24,y,w-48,62,screen.body.join('\n'),12,'muted');y+=65;}
   if(screen.keyboard){
     for(const [j,k] of ['Esc','Tab','Ctrl','Alt','↑','↓'].entries()){hp.rect(b,24+j*((w-48)/6),y,(w-60)/6,40,k==='Ctrl'&&screen.id==='P3-combo'?'accent':'panel',6);hp.text(b,26+j*((w-48)/6),y+10,(w-60)/6-4,24,k,12,k==='Ctrl'&&screen.id==='P3-combo'?'panel':'ink');}
     hp.rect(b,24,y+46,w-48,54,'line',6);hp.text(b,36,y+57,w-72,32,'系统键盘占位 · IME 组合先留本地',12,'muted');
   }
 }else if(screen.kind==='scan'){
   hp.rect(b,56,164,w-112,220,'panel',16);hp.text(b,72,210,w-144,100,'┌                 ┐\n   响应码取景框\n└                 ┘',19,'muted',true);hp.text(b,24,406,w-48,130,screen.body.join('\n\n'),14,'ink');
 }else if(helper){
   hp.rect(b,24,160,w-48,250,'terminal',8);hp.text(b,44,180,w-88,215,screen.body.join('\n\n'),14,'terminalInk',true);
 }else{
   const tone=['danger','warning'].includes(screen.kind)?screen.kind+'Soft':null;
   if(tone)hp.rect(b,24,160,w-48,Math.min(400,screen.body.length*74+20),tone,8);
   for(let i=0;i<screen.body.length;i++){
     const y=bodyY+i*74;if(!tone)hp.rect(b,24,y,w-48,66,'panel',8);
     hp.text(b,36,y+12,w-72,54,screen.body[i],14,screen.kind==='danger'?'danger':screen.kind==='warning'?'warning':'ink');
   }
 }
 const actionY=h-64-screen.actions.length*56;
 screen.actions.forEach((a,i)=>hp.button(b,a.label,a.to,24,actionY+i*56,w-48,i===0));
 hp.text(b,24,h-43,w-48,28,'交互原型 · 虚构数据 · 运行能力未验证',10,'muted');
 if(screen.extraLinks){screen.extraLinks.forEach((a,i)=>hp.button(b,a[0],a[1],24,458+i*50,w-48,false));}
 return b;
};
const newScreens=[{"id": "P1-loading", "title": "正在获取当前状态", "subtitle": "主机已连接 · 会话尚未同步", "body": ["网络在线不代表看板已刷新。", "正在校验 herdr 能力并获取当前 session 快照。", "旧状态保留时间戳；没有快照时显示状态待确认。"], "actions": [{"label": "模拟快照到达", "to": "P1-dashboard"}, {"label": "模拟失联", "to": "P1-stale"}], "family": "P1", "kind": "warning"}, {"id": "P6-commit-failed", "title": "配置提交失败", "subtitle": "配置完整回滚 · 连接保持关闭", "body": ["没有部分写入新增或替换条目。", "相关连接已停止，提交失败不自动恢复或重连。", "保留原配置后仍需用户主动核验连接。"], "actions": [{"label": "回到导入审查", "to": "P6-import"}, {"label": "查看原主机配置", "to": "P2-manual"}], "family": "P6", "kind": "danger"}];newScreens.forEach((s,i)=>hp.board(s,54+i));
for(const id of ['P1-loading','P6-commit-failed']){const b=hp.boards[id];const f=penpotUtils.findShapes(s=>s.type==='text'&&s.characters.startsWith('交互原型'),b)[0];f.characters='原型导航 ↗ · 虚构数据 · 能力未验证';hp.links.push({shape:f,from:id,label:'原型导航',to:'START'});}
const success=hp.boards['P2-success'];const toDash=penpotUtils.findShapes(s=>s.interactions.length>0&&s.name.includes('进入主机会话看板'),success)[0];toDash.interactions.forEach(i=>toDash.removeInteraction(i));toDash.addInteraction('click',{type:'navigate-to',destination:hp.boards['P1-loading']});
hp.button(hp.boards['P6-conflict'],'演示提交失败','P6-commit-failed',24,536,342,false);
for(const l of hp.links)l.shape.addInteraction('click',{type:'navigate-to',destination:hp.boards[l.to]});
return {added:newScreens.map(s=>s.id)};
