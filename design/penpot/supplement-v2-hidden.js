if(penpot.currentPage.id!=='7a22df08-251d-8016-8008-de03541c11da'||penpotUtils.findShape(s=>s.name.startsWith('S16 ·'),penpot.root))throw Error('Wrong page or already applied');
const C={canvas:'#F8FAFC',card:'#FFFFFF',line:'#E2E8F0',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',success:'#047857',successBg:'#ECFDF5',warning:'#92400E',warningBg:'#FEF3C7',danger:'#BE123C',dangerBg:'#FFF1F2',term:'#0B0F17',termInk:'#E6EDF3'};
const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,color,r=10){const s=penpot.createRectangle();s.resize(w,h);s.fills=[{fillColor:color,fillOpacity:1}];s.borderRadius=r;b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function txt(b,x,y,w,h,value,size=14,color=C.ink,weight=400){const s=penpot.createText(value);s.name=value.split('\n')[0].replace(/[\/]+/g,'-').trim().slice(0,40)||'note';s.resize(w,h);if(font)font.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.45';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function board(id,title,x,y,w=390,h=844){const b=penpot.createBoard();b.name=id+' · '+title;b.resize(w,h);b.x=x;b.y=y;b.fills=[{fillColor:C.canvas,fillOpacity:1}];b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.setPluginData('herdr-pocket',JSON.stringify({screen:id,version:'v2-recovery',illustration:true}));txt(b,24,18,w-48,22,'HERDR POCKET  /  交互原型',12,C.muted,600);txt(b,24,62,w-48,64,title,24,C.ink,700);return b;}
function link(s,b){s.interactions?.forEach(i=>i.remove());s.addInteraction('click',{type:'navigate-to',destination:b});}
function button(b,y,label,dest,primary=true,x=24,w=342){const r=rect(b,x,y,w,48,primary?C.brand:C.card);r.name='action · '+label;const t=txt(b,x+12,y+13,w-24,24,label,14,primary?C.card:C.ink,600);t.align='center';if(dest){link(r,dest);link(t,dest);}return {r,t};}
function box(b,y,title,body,kind='neutral',h=150){const bg=kind==='danger'?C.dangerBg:kind==='warning'?C.warningBg:kind==='success'?C.successBg:C.card;const col=kind==='danger'?C.danger:kind==='warning'?C.warning:kind==='success'?C.success:C.ink;rect(b,24,y,b.width-48,h,bg);txt(b,40,y+16,b.width-80,28,title,16,col,600);txt(b,40,y+52,b.width-80,h-62,body,14,C.sub);}
const old={};for(const b of penpot.root.children.filter(s=>s.type==='board'))old[b.name.slice(0,3)]=b;

const b16=board('S16','B 标签 · 从暂停恢复观察',3480,1940);
box(b16,140,'新画面已取得 · 仅观察','B / Lab-Node-02 / test-session / agent-c\nEasyTier · 目标与连接代次已核验\n隐藏期间没有持续渲染，也没有发送输入。','success',174);
rect(b16,24,336,342,180,C.term);txt(b16,40,354,310,144,'B · 最新 full snapshot\n\n❯ agent-c: waiting\n\n当前仅观察；不继承 A 的输入模式。\n暂停期间完整历史不保证补齐。',14,C.termInk);
box(b16,538,'草稿与组合键分别处理','B 草稿按目标保留；A 的组合键和未提交 IME 已释放。取回全量画面不触发输入重放。','neutral',150);
button(b16,714,'返回工作台，选择输入目标',old.S11);txt(b16,24,780,342,40,'当前页没有输入动作；设备生命周期仍待实测。',12,C.muted);
for(const s of old.S11.children.filter(s=>s.interactions?.some(i=>i.action?.destination?.id===old.S09.id)))link(s,b16);
const next=txt(old.S07,870,18,306,44,'组件状态与可访问性 →',13,C.brand,600);link(next,old.S15);
for(const c of penpot.library.local.components.filter(c=>c.path==='v2')){const b=c.mainInstance();if(b.type==='board')b.showInViewMode=false;}
return {added:{id:b16.id,name:b16.name},componentNames:penpot.library.local.components.filter(c=>c.path==='v2').map(c=>c.name)};
