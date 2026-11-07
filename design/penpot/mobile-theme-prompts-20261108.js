// Incremental v2 Penpot design change. Refuses another page, a repeated or
// partial increment, changed S45, occupied entry space or overlapping boards.
// The prompt strings and cursor expectations are from the shared v1 fixture;
// these are illustrative layouts, not a renderer or mobile-device result.
const file='b55064db-d93d-80f9-8008-ddd22e6d398f',page='7a22df08-251d-8016-8008-de03541c11da';
if(penpot.currentFile?.id!==file || penpot.currentPage?.id!==page) throw Error('wrong file/page');
const boards=penpot.root.children.filter(s=>s.type==='board');
const original=boards.find(s=>s.id==='ff7bd149-6597-80a5-8008-e8b74585bb97');
const observe=boards.find(s=>s.id==='7a22df08-251d-8016-8008-de04a20d928d');
const names=['主题样例 · Powerlevel10k','主题样例 · Oh My Posh'];
if(!original || original.name!=='S45 · 字体与字符诊断' || !observe ||
   Math.abs(original.width-390)>1 || Math.abs(original.height-844)>1 ||
   boards.some(b=>names.includes(b.name)) || original.children.some(s=>s.name.startsWith('主题样例入口'))) throw Error('existing/partial increment or S45 changed');
const advice=original.children.find(s=>s.id==='ff7bd149-6597-80a5-8008-e8b7461d98b7');
const back=original.children.find(s=>s.id==='ff7bd149-6597-80a5-8008-e8b746242898');
const backText=original.children.find(s=>s.id==='ff7bd149-6597-80a5-8008-e8b746294ae2');
if(!advice || advice.interactions.length!==0 || !back || !backText || back.interactions.length!==1 || backText.interactions.length!==1) throw Error('S45 baseline differs');
const expanded={x:original.x,y:original.y,w:390,h:908};
function intersects(a,b){return Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x) && Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y);}
if(boards.some(b=>b.id!==original.id && intersects(expanded,{x:b.x,y:b.y,w:b.width,h:b.height}))) throw Error('expanded S45 would overlap another board');
if(original.children.some(s=>s.y+s.height>original.y+844.01)) throw Error('S45 entry area not empty');
const face=penpot.fonts.findByName('Inter'),mono=penpot.fonts.findByName('IBM Plex Mono')||face;
function box(p,n,x,y,w,h,c,r=12){const s=penpot.createRectangle();s.name=n;s.resize(w,h);s.borderRadius=r;s.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(s);s.x=p.x+x;s.y=p.y+y;return s;}
function text(p,n,x,y,w,h,str,size,c,weight=400,font=face){const s=penpot.createText(str);s.name=n;s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.35';s.fills=[{fillColor:c,fillOpacity:1}];p.appendChild(s);s.x=p.x+x;s.y=p.y+y;return s;}
function go(s,target){s.addInteraction('click',{type:'navigate-to',destination:target});}
function button(p,n,x,y,w,label,target,primary=false){const bg=box(p,'action · '+n,x,y,w,48,primary?'#4F46E5':'#E0E7FF',10);const t=text(p,n,x+4,y+13,w-8,22,label,14,primary?'#FFFFFF':'#3730A3',600);t.align='center';if (target.id!==p.id) {go(bg,target);go(t,target);}}
const y=Math.ceil(Math.max(...boards.map(b=>b.y+b.height))+80);
function board(name,x){const b=penpot.createBoard();b.name=name;b.resize(390,844);b.x=x;b.y=y;b.showInViewMode=true;b.borderRadius=20;b.fills=[{fillColor:'#F8FAFC',fillOpacity:1}];return b;}
const p10k=board(names[0],0),omp=board(names[1],450);
// Editable static outlines are derived from the pinned repository font.
const glyphPaths = {"folder": "M1.2,-1.568 Q0.704,-1.568 0.352,-1.9040000000000001 Q0.0,-2.2560000000000002 0.0,-2.7520000000000002 L0.0,-8.752 Q0.0,-9.248 0.352,-9.616 Q0.704,-9.968 1.2,-9.968 L3.6,-9.968 Q4.176,-9.968 4.5440000000000005,-9.472 L4.912,-8.992 Q5.088,-8.752 5.392,-8.752 L8.4,-8.752 Q8.896,-8.752 9.248,-8.416 Q9.6,-8.064 9.584,-7.5680000000000005 L9.584,-2.7520000000000002 Q9.584,-2.2560000000000002 9.248,-1.9040000000000001 Q8.896,-1.552 8.4,-1.568 Z ", "arrow": "M-0.5760000000000001,-16.416 L0.096,-16.416 L9.584,-5.76 L0.096,4.896 L-0.5760000000000001,4.896 Z "};
function glyph(b,name,x,y,path,color){
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="12" height="20" viewBox="-1 0 12 20"><path fill="${color}" d="${path}" transform="translate(0 17)"/></svg>`;
 const shape=penpot.createShapeFromSvg(svg);if(!shape)throw Error('glyph outline unavailable');
 shape.name=name;b.appendChild(shape);shape.x=b.x+x;shape.y=b.y+y;
}
function promptArt(b,isP){
 const old=b.children.find(s=>s.name==='固定目录段');if(!old||old.hidden)throw Error('prompt shape mismatch');old.hidden=true;
 const blue='#005FAF',dark='#262626';
 if(!isP)glyph(b,'起始分隔符轮廓',40,371,glyphPaths.arrow,blue);
 const x=isP?40:50;
 box(b,'蓝色目录段',x,369,70,24,blue,0);
 glyph(b,'目录图标轮廓',x+5,371,glyphPaths.folder,'#FFFFFF');
 text(b,'中文目录',x+19,371,48,21,'中文',14,'#FFFFFF',600,mono);
 glyph(b,'目录分隔符轮廓',x+70,371,glyphPaths.arrow,blue);
 box(b,'提示符色块',x+82,369,35,24,dark,0);
 text(b,'提示符',x+88,371,20,21,'❯',14,'#5FD700',600,mono);
 glyph(b,'结束分隔符轮廓',x+117,371,glyphPaths.arrow,dark);
}
function draw(b,selected){
 const isP=selected==='p10k';
 text(b,'页面标题',24,32,342,38,'字体与字符诊断',24,'#0F172A',600);
 text(b,'当前字体',24,80,342,25,'JetBrainsMono Nerd Font Mono',16,'#0F172A',600);
 text(b,'字号与范围',24,110,342,24,'14 px · 本地只读样例',14,'#475569');
 button(b,'字符列宽',24,156,104,'字符列宽',original);
 button(b,'Powerlevel10k',137,156,112,'Powerlevel10k',p10k,isP);
 button(b,'Oh My Posh',258,156,108,'Oh My Posh',omp,!isP);
 text(b,'主题名称',24,230,342,50,isP?'Powerlevel10k 1.20.0 · 中文目录':'Oh My Posh 31.9.1 · 中文目录',17,'#0F172A',600);
 text(b,'尺寸',24,280,342,25,'40 列 × 3 行 · 本地只读',14,'#475569');
 box(b,'终端示意',24,320,342,130,'#0F172A');
 text(b,'样例说明',38,334,312,23,'主题固定目录段 · 示意',12,'#A5B4FC',600);
 // This line represents the exact visible segment, without invented Git state.
 text(b,'固定目录段',40,372,306,35,isP?'  中文  ❯  ':'  中文  ❯  ',16,'#F8FAFC',500,mono);
 promptArt(b,isP);
 text(b,'预期光标',24,478,342,26,isP?'预期光标：第 15 列、第 1 行':'预期光标：第 16 列、第 1 行',15,'#0F172A',600);
 text(b,'实际光标',24,514,342,50,'本地实际光标：以应用显示为准\n列与行位置需与预期逐项比较。',14,'#475569');
 text(b,'横向阅读',24,585,342,62,'手机窄屏可左右滑动查看完整 40 列。字形与颜色需在目标设备自行核对。',14,'#475569');
 text(b,'安全边界',24,665,342,54,'只在本机显示，不改变远端会话、PTY、草稿或输入。',14,'#475569');
 button(b,'返回字符诊断',24,744,342,'返回字符列宽诊断',original,true);
 text(b,'验证范围',24,812,342,22,'交互原型示意 · 不代表设备显示已验证',12,'#64748B');
}
draw(p10k,'p10k');draw(omp,'omp');
// Expand only the frame; all original child positions and links remain intact.
original.resize(390,908);
const entry=box(original,'主题样例入口',24,852,342,44,'#E0E7FF',10);
const label=text(original,'主题样例入口文字',30,863,330,22,'查看 Powerlevel10k 与 Oh My Posh',14,'#3730A3',600);
label.align='center';go(entry,p10k);go(label,p10k);
return {file,page,original:original.id,oldHeight:844,newHeight:908,powerlevel10k:p10k.id,ohMyPosh:omp.id,entry:entry.id,label:label.id};
