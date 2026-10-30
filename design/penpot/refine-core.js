if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f')throw new Error('Wrong file');
const hp=storage.hp;
for(const s of hp.screenData){const b=hp.boards[s.id];
 if(s.kind==='desktop'){
  const links=hp.links.filter(l=>l.from===s.id&&l.label!=='原型导航');const gap=12,width=(b.width-48-(links.length-1)*gap)/links.length;
  links.forEach((l,i)=>{l.shape.x=b.x+24+i*(width+gap);l.shape.y=b.y+b.height-120;l.shape.resize(width,48);const t=penpotUtils.findShapes(x=>x.type==='text',l.shape)[0];t.x=l.shape.x+16;t.y=l.shape.y+12;t.resize(width-32,32);});
  const text=penpotUtils.findShapes(t=>t.type==='text'&&t.characters.startsWith('› herdr observe'),b);
  if(text.length>1)text[1].characters=text[1].characters.replace('agent-a','agent-b');
 }
 if(s.kind==='helper'){
  const text=penpotUtils.findShapes(t=>t.type==='text'&&t.y>b.y+160&&t.y<b.y+220,b)[0];if(text)text.characters=s.body.join('\n');
 }
}
return {fixed:'desktop action overlap and helper wrapping'};
