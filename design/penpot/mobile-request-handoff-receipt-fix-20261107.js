if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da') throw Error('Wrong project');
const b=penpot.root.children.find(s=>s.name.startsWith('S53 ·'));
const t=b?.children.find(s=>s.name==='撤销详情'&&s.type==='text');if(!t)throw Error('Missing receipt detail');
t.fontSize='12';t.characters='编号 0123456789abcdef\n       0123456789abcdef\n账号 demo · revoked · 16:40–16:50\n主机 SHA256:bbXpuKG6zhzdmnxq256Tlqz\n       FBzRl2f6OOg722cYNbU8\n设备 SHA256:aaaaaaaaaaaaaaaaaaaaaaa\n       aaaaaaaaaaaaaaaaaaaa';
return {id:t.id,board:b.id,text:t.characters};
