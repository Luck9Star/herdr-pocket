// One-time increment to the user's v2 file. Inspect existing edits before running.
const fileId = 'b55064db-d93d-80f9-8008-ddd22e6d398f';
const pageId = '7a22df08-251d-8016-8008-de03541c11da';
if (penpot.currentFile?.id !== fileId || penpot.currentPage?.id !== pageId) throw Error('Wrong file or page');
const boards = penpot.root.children.filter(s => s.type === 'board');
const partialId = 'ff7bd149-6597-80a5-8008-e88156484822';
const partial = boards.find(b => b.id === partialId);
const orphan = penpotUtils.findShapeById('ff7bd149-6597-80a5-8008-e8815667a86e');
if (partial && (partial.name !== 'S39 · 选择终端文本' || partial.children.length ||
    orphan?.parent?.id !== penpot.root.id || orphan.characters !== 'workstation   /   agent-a')) throw Error('Partial state changed');
if (boards.filter(b => b.id !== partialId).some(b => /^S(39|40|41|42) /.test(b.name) || (b.y < 9744 && b.y + b.height > 8900 && b.x < 1740 && b.x + b.width > 0))) throw Error('Occupied board range');
const source = id => penpotUtils.findShapeById(id);
const observe = source('7a22df08-251d-8016-8008-de04a20d928d');
const paste = source('2a5fd934-a163-8057-8008-e823087a9fc9');
const selectBase = source('7a22df08-251d-8016-8008-de04a2ab99c1');
const selectLabel = source('7a22df08-251d-8016-8008-de04a2ad0f1a');
const pasteNote = source('2a5fd934-a163-8057-8008-e824e8e5ae49');
if (selectBase?.parent?.id !== observe?.id || selectBase.interactions.length || selectLabel?.parent?.id !== observe.id ||
    selectLabel.characters !== '📋 复制画面文本' || selectLabel.interactions.length ||
    pasteNote?.parent?.id !== paste?.id || !pasteNote.characters.startsWith('实际界面另提供')) throw Error('Existing entry changed');
const palette = {canvas:'#F8FAFC', white:'#FFFFFF', ink:'#0F172A', muted:'#475569', brand:'#4F46E5', tint:'#EEF2FF', highlight:'#C7D2FE', night:'#1E293B', warning:'#92400E', amber:'#FEF3C7'};
const font = penpot.fonts.findByName('Inter');
function box(parent,name,x,y,w,h,fill,radius=12) {
  const shape=penpot.createRectangle(); shape.name=name; shape.resize(w,h);shape.borderRadius=radius;
  shape.fills=[{fillColor:fill,fillOpacity:1}];parent.appendChild(shape);shape.x=parent.x+x;shape.y=parent.y+y;return shape;
}
function label(parent,name,x,y,w,h,value,size=15,color=palette.ink,weight=400) {
  const shape=(parent===partial && name==='连接目标') ? orphan : penpot.createText(value);parent.appendChild(shape);shape.name=name;shape.resize(w,h);font?.applyToText(shape);
  shape.fontSize=String(size);shape.fontWeight=String(weight);shape.lineHeight='1.4';shape.fills=[{fillColor:color,fillOpacity:1}];
  shape.x=parent.x+x;shape.y=parent.y+y;return shape;
}
function board(index,title,x) {
  const b=index===39 && partial ? partial : penpot.createBoard();b.name='S'+index+' · '+title;b.resize(390,844);b.x=x;b.y=8900;b.borderRadius=20;b.clipContent=true;b.showInViewMode=true;b.fills=[{fillColor:palette.canvas,fillOpacity:1}];
  b.setPluginData('herdr-pocket',JSON.stringify({screen:'S'+index,illustration:true,accessibility:'44px 操作目标，状态同时以文字表达，切换身份或标签后清除选择界面'}));
  label(b,'连接目标',24,36,342,26,'workstation   /   agent-a',14,palette.muted,500);
  label(b,'标题',24,82,342,52,title,26,palette.ink,700);return b;
}
function navigate(shape,dest) {shape.addInteraction('click',{type:'navigate-to',destination:dest});}
function button(b,x,y,w,value,dest,primary=false) {
  const bg=box(b,value,x,y,w,48,primary?palette.brand:palette.white);
  const txt=label(b,value,x+7,y+12,w-14,24,value,15,primary?palette.white:palette.ink,600);
  txt.align='center';navigate(bg,dest);navigate(txt,dest);
}
const select=board(39,'选择终端文本',0), copied=board(40,'已复制选区',450);
const limit=board(41,'追加超出上限',900), replaced=board(42,'草稿已替换',1350);
function selectionCard(b) {
  box(b,'冻结的终端文本',24,174,342,232,palette.night);
  label(b,'输出首行',42,203,296,26,'$ herdr status',16,'#CBD5E1');
  label(b,'未选文字',42,248,296,26,'agent-a   ready',16,'#F8FAFC');
  box(b,'示例选区',39,287,186,33,palette.highlight,5);
  label(b,'选中文字',43,290,192,29,'输出校验  ✓',17,palette.ink,600);
  label(b,'未选末行',42,346,296,25,'2 checks passed',16,'#F8FAFC');
}
selectionCard(select);selectionCard(copied);
label(select,'操作说明',24,438,342,92,'长按画面文字并调整选区。此处保留打开时的文本，复制只包含选中的部分。',16,palette.muted);
button(select,24,555,342,'复制选区',copied,true);button(select,24,618,342,'关闭并返回观察',observe);
label(copied,'复制反馈',24,438,342,68,'已复制“输出校验  ✓”。',17,palette.ink,600);
button(copied,24,555,342,'继续选择文本',select,true);button(copied,24,618,342,'返回观察',observe);
label(copied,'示例边界',24,708,342,52,'此原型演示复制反馈。',13,palette.muted);
box(limit,'字节上限',24,161,342,137,palette.amber);
label(limit,'超限合计',40,184,310,32,'4097 / 4096 字节',21,palette.warning,700);
label(limit,'超限说明',40,231,310,50,'原稿 4094 字节，加上“中”占 3 字节。',15,palette.warning);
box(limit,'待粘贴文本',24,320,342,118,palette.white);
label(limit,'待粘贴标签',40,341,310,24,'待粘贴',14,palette.muted);label(limit,'待粘贴值',40,380,310,30,'中',20);
box(limit,'追加禁用',24,472,342,48,'#E2E8F0');const disabled=label(limit,'追加禁用说明',30,484,330,24,'追加不可用 · 超出 1 字节',15,palette.muted,600);disabled.align='center';
button(limit,24,535,342,'替换本地草稿',replaced,true);button(limit,24,598,342,'取消并返回粘贴示例',paste);
label(limit,'保留说明',24,694,342,68,'取消会保留原稿。替换后仍需单独预览并确认发送。',14,palette.muted);
box(replaced,'草稿正文',24,174,342,196,palette.white);
label(replaced,'草稿标签',40,197,310,28,'本地草稿  ·  3 字节',15,palette.muted,600);label(replaced,'当前草稿',40,254,310,65,'中',27);
label(replaced,'状态',24,410,342,72,'目标仍为 agent-a，尚未发送。',17,palette.muted);
button(replaced,24,555,342,'返回超限示例',limit,true);button(replaced,24,618,342,'返回终端观察',observe);
selectBase.resize(170,44);selectLabel.characters='选择终端文本';selectLabel.name='选择终端文本';selectLabel.y=observe.y+772;
navigate(selectBase,select);navigate(selectLabel,select);
pasteNote.characters='追加、替换和取消都只影响当前草稿。目标变化后，请重新核对要粘贴的内容。';
pasteNote.resize(342,66);button(paste,24,702,342,'查看追加超限示例',limit);
return {fileId,pageId,boards:[select,copied,limit,replaced].map(b=>({id:b.id,name:b.name})),sources:[selectBase.id,selectLabel.id,paste.id]};
