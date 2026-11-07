// Add the font diagnostic state to the existing v2 terminal observation flow.
const file = 'b55064db-d93d-80f9-8008-ddd22e6d398f';
const page = '7a22df08-251d-8016-8008-de03541c11da';
if (penpot.currentFile?.id !== file || penpot.currentPage?.id !== page) throw Error('Wrong project page');
const boards = penpot.root.children.filter(s => s.type === 'board');
const observe = boards.find(s => s.id === '7a22df08-251d-8016-8008-de04a20d928d');
const entry = observe?.children.find(s => s.id === '7a22df08-251d-8016-8008-de04a2b07939');
const label = observe?.children.find(s => s.id === '7a22df08-251d-8016-8008-de04a2b20c14');
if (!entry || !label || entry.interactions.length || label.interactions.length ||
    label.characters !== '⚙️ 终端字体与诊断' || boards.some(s => s.name.startsWith('S45 '))) {
  throw Error('Review the existing diagnostic entry before editing');
}
const bottom = Math.max(...boards.map(s => s.y + s.height));
const board = penpot.createBoard();
board.name = 'S45 · 字体与字符诊断';
board.resize(390, 844);
board.x = 0;
board.y = Math.ceil(bottom + 80);
board.showInViewMode = true;
board.borderRadius = 20;
board.fills = [{fillColor:'#F8FAFC', fillOpacity:1}];
const face = penpot.fonts.findByName('Inter');
const mono = penpot.fonts.findByName('IBM Plex Mono') || face;
function box(name, x, y, w, h, color, radius=12) {
  const s = penpot.createRectangle();
  s.name = name; s.resize(w,h); s.borderRadius = radius;
  s.fills = [{fillColor:color,fillOpacity:1}];
  board.appendChild(s); s.x=board.x+x; s.y=board.y+y;
  return s;
}
function text(name, x, y, w, h, str, size, color, weight=400, font=face) {
  const s=penpot.createText(str);
  s.name=name; s.resize(w,h); font?.applyToText(s);
  s.fontSize=String(size); s.fontWeight=String(weight); s.lineHeight='1.35';
  s.fills=[{fillColor:color,fillOpacity:1}]; board.appendChild(s);
  s.x=board.x+x; s.y=board.y+y;
  return s;
}
function go(s, target) { s.addInteraction('click',{type:'navigate-to',destination:target}); }
text('页面标题',24,38,342,40,'字体与字符诊断',26,'#0F172A',600);
text('当前字体',24,90,342,25,'JetBrainsMono Nerd Font Mono',18,'#0F172A',600);
text('字号与范围',24,120,342,24,'14 px   ·   本地只读样例',14,'#475569');
box('终端示例',24,169,342,326,'#0F172A');
text('列标说明',42,183,304,22,'第 15 列',13,'#A5B4FC',600).align='right';
const rows=[
  ['ASCII','Hello'],['Powerline',''],['Nerd Font','󰟀'],['中文','中文'],
  ['组合重音','é Å'],['Emoji','😀🚀'],['Emoji 组合','👩‍💻❤️'],['ANSI','ANSI'],
];
rows.forEach(([name,sample],i)=>{
  const top=217+32*i;
  text('样例 · '+name,42,top,122,24,name,14,'#CBD5E1');
  text('字形 · '+name,170,top,125,24,sample,16,i===7?'#FB7185':'#F8FAFC',i===7?700:400,mono);
  text('右侧列标 '+(i+1),332,top,16,24,'|',16,'#A5B4FC',500,mono);
});
text('检查方法',24,524,342,29,'检查列对齐和重音',19,'#0F172A',600);
text('说明',24,561,342,62,'检查八行右侧的竖线是否同列，以及 é 的重音是否完整。中文和 emoji 可能使用系统字体。',15,'#475569');
text('缺字建议',24,637,342,60,'图标显示方框时，可在主机上自行选择无图标的提示符主题。',15,'#475569');
const back=box('关闭诊断',24,726,342,48,'#4F46E5');
const backText=text('关闭诊断标签',32,738,326,24,'返回终端观察',16,'#FFFFFF',600);
backText.align='center';go(back,observe);go(backText,observe);
text('验证范围',24,797,342,25,'原型示意 · 字形与列宽请在应用中核对',12,'#64748B');
entry.resize(170,44); label.y=observe.y+772;
go(entry,board);go(label,board);
// Static, editable glyph outlines from the repo's pinned JetBrainsMono Nerd Font Mono.
const diagrams = {
  "nerd": "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='25' viewBox='0 0 40 25'><path fill='#F8FAFC' d='M0.16 10.42 Q0.00 10.26 0.00 10.04 Q0.00 9.82 0.16 9.66 Q0.32 9.50 0.53 9.50 Q0.75 9.50 0.91 9.66 L4.11 12.87 Q4.27 13.03 4.27 13.24 Q4.27 13.46 4.11 13.62 L0.91 16.82 Q0.75 16.98 0.53 16.97 Q0.30 16.97 0.16 16.82 Q0.00 16.66 0.00 16.44 Q0.00 16.22 0.16 16.07 L2.98 13.24 Z M4.27 15.91 L9.06 15.91 Q9.28 15.91 9.44 16.07 Q9.60 16.23 9.58 16.44 Q9.58 16.66 9.44 16.82 Q9.28 16.98 9.06 16.97 L4.27 16.97 Q4.05 16.97 3.89 16.82 Q3.73 16.66 3.73 16.44 Q3.73 16.22 3.89 16.07 Q4.05 15.91 4.27 15.91 Z'/><path fill='#F8FAFC' d='M15.12 9.46 Q15.30 9.35 15.49 9.42 Q15.68 9.48 15.78 9.66 Q15.87 9.83 15.82 10.01 L13.90 16.73 Q13.84 16.92 13.66 17.02 Q13.49 17.11 13.31 17.06 Q13.12 17.00 13.01 16.82 Q12.91 16.65 12.98 16.47 L14.90 9.75 Q14.96 9.56 15.12 9.46 Z M16.69 11.22 L16.69 11.22 Q16.83 11.08 17.02 11.08 Q17.22 11.08 17.38 11.22 L19.06 12.90 Q19.20 13.05 19.18 13.24 Q19.18 13.43 19.06 13.58 L17.38 15.26 Q17.23 15.40 17.02 15.40 Q16.83 15.40 16.69 15.26 Q16.54 15.11 16.54 14.92 Q16.54 14.73 16.69 14.58 L18.03 13.24 L16.69 11.90 Q16.54 11.75 16.54 11.56 Q16.54 11.37 16.69 11.22 Z M11.76 11.08 Q11.95 11.08 12.10 11.22 Q12.24 11.37 12.24 11.56 Q12.24 11.75 12.10 11.90 L10.75 13.24 L12.10 14.58 Q12.24 14.73 12.24 14.92 Q12.24 15.11 12.10 15.26 Q11.95 15.40 11.76 15.40 Q11.57 15.40 11.42 15.26 L9.74 13.58 Q9.60 13.43 9.60 13.24 Q9.60 13.05 9.74 12.90 L11.42 11.22 Q11.57 11.08 11.76 11.08 Z'/><path fill='#F8FAFC' d='M21.12 8.44 Q20.70 8.44 20.43 8.72 Q20.16 9.00 20.16 9.38 L20.16 13.24 Q20.16 13.64 20.43 13.92 Q20.70 14.20 21.12 14.20 L26.88 14.20 Q27.26 14.20 27.55 13.92 Q27.84 13.64 27.84 13.24 L27.84 9.38 Q27.84 9.00 27.57 8.72 Q27.30 8.44 26.88 8.44 Z M21.12 9.38 L26.88 9.38 L26.88 13.24 L21.12 13.24 Z M20.16 14.68 Q19.78 14.68 19.49 14.96 Q19.20 15.24 19.20 15.64 L19.20 17.08 Q19.20 17.46 19.49 17.75 Q19.78 18.04 20.16 18.04 L27.84 18.04 Q28.22 18.04 28.51 17.75 Q28.80 17.46 28.80 17.08 L28.80 15.64 Q28.80 15.24 28.51 14.96 Q28.22 14.68 27.84 14.68 Z M22.08 15.64 L27.84 15.64 L27.84 17.08 L22.08 17.08 Z M22.56 16.01 L22.56 16.73 L24.48 16.73 L24.48 16.01 Z M25.44 16.01 L25.44 16.73 L27.36 16.73 L27.36 16.01 Z'/></svg>",
  "powerline": "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='25' viewBox='0 0 40 25'><path fill='#F8FAFC' d='M-0.58 2.58 L0.10 2.58 L9.58 13.24 L0.10 23.90 L-0.58 23.90 Z'/><path fill='#F8FAFC' d='M19.10 23.90 L9.62 13.24 L19.10 2.58 L19.78 2.58 L19.78 23.90 Z'/></svg>"
};
function includeGlyphIllustrations(board) {
  for (const [id,title,top] of [['powerline','Powerline',249],['nerd','Nerd Font',281]]) {
    const original=board.children.find(s=>s.name==='字形 · '+title);
    if (!original || board.children.some(s=>s.name==='图标轮廓 · '+title)) throw Error('Unexpected sample row');
    const symbols=penpot.createShapeFromSvg(diagrams[id]);
    if (!symbols) throw Error('Unable to render the sample');
    symbols.name='图标轮廓 · '+title; board.appendChild(symbols); symbols.x=board.x+170; symbols.y=board.y+top+2;
    original.hidden=true;
  }
}
includeGlyphIllustrations(board);
return {file,page,board:board.id,entry:entry.id,label:label.id,back:back.id,backText:backText.id,objects:board.children.length};
