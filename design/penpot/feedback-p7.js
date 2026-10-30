// Scoped, idempotent evidence feedback. No new boards or interactions.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f')throw new Error('Wrong file');
const board=penpotUtils.findShape(s=>s.type==='board'&&s.name.startsWith('P7-font · '),penpot.root);
if(!board)throw new Error('P7 missing');
const body=penpotUtils.findShape(s=>s.type==='text'&&(s.characters.startsWith('Nerd Font 候选')||s.characters.startsWith('macOS 实测：')),board);
body.characters='macOS 实测：terminal_view 0.5.0 的 ASCII\n组合重音未绘出；Tauri 同机目视可见。\n需对照原字节、复制与渲染，修复后重验。\n框架未定；手机 IME / 真实主题均未验证。';
body.resize(342,110);
const subtitle=penpotUtils.findShape(s=>s.type==='text'&&(s.characters==='画稿不能验证终端渲染'||s.characters==='实测反馈 · 需修复后重验'),board);
if(subtitle)subtitle.characters='实测反馈 · 需修复后重验';
board.setPluginData('herdr-pocket-evidence',JSON.stringify({date:'2026-10-30',source:'c8d70abf',finding:'macOS ASCII combining marks rendering defect; buffer/painter diagnosis pending',frameworkDecision:'open',themes:'unverified',mobileIME:'unverified'}));
return {board:board.id,scope:'P7 feedback only'};
