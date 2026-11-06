// One-shape adjustment; other boards and interactions remain untouched.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const b=penpot.root.children.find(s=>s.id==='b9d502c0-514c-80a9-8008-e7033db44885');
const t=penpotUtils.findShapeById('b9d502c0-514c-80a9-8008-e7033db7329c');
if(!b||t?.parent?.id!==b.id||t.characters!=='HERDR POCKET  /  交互原型'||Math.abs(t.y-b.y-18)>0.1)throw Error('Unexpected object');
const before={x:t.x-b.x,y:t.y-b.y,width:t.width,height:t.height};
t.y=b.y+24;t.resize(342,24);
return {id:t.id,before,after:{x:t.x-b.x,y:t.y-b.y,width:t.width,height:t.height}};
