import {loadThemePromptSamples,validThemePromptSamples} from './theme-prompt-samples.js';
const fixtureUrl='/shared/terminal-font-diagnostics-v1.json';

function validFixture(value) {
  if(!value || value.schemaVersion!==1 || value.id!=='terminal-font-diagnostics-v1' || value.columns!==16 || value.rows!==8 || value.markerColumn!==15 || !Array.isArray(value.samples) || value.samples.length!==8 || typeof value.write!=='string' || value.write.length>4096)return false;
  if(!value.samples.every(s=>s && typeof s.id==='string' && /^[a-z]{1,24}$/.test(s.id) && typeof s.label==='string' && s.label.length>0 && s.label.length<=48 && typeof s.text==='string' && s.text.length<=80 && Number.isInteger(s.cells) && s.cells>=1 && s.cells<=12))return false;
  const plain=value.write.replace(/\x1b\[[0-9;]*m/g,'');
  return !/[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]/.test(plain) && plain.split('\r\n').length===8 && plain.split('\r\n').every((line,i)=>line.startsWith(`${i+1}|`) && line.endsWith('|'));
}

/** Local fixed-size renderer: no remote terminal, input handler, or PTY resize. */
export function createFontDiagnostics({current,terminalFactory,fontSize,theme,loadFixture=async()=>{
  const response=await fetch(fixtureUrl);if(!response.ok)throw Error('fixture_unavailable');return response.json();
},loadThemes=loadThemePromptSamples,returnFocus=null,onClose=()=>{}}) {
  const group=document.createElement('dialog');group.className='terminal-font-diagnostics';group.setAttribute('role','dialog');group.setAttribute('aria-modal','true');group.setAttribute('aria-label','字体与字符诊断');
  let closed=false, sample=null, revision=0;
  const valid=()=>!closed && current();
  const close=(restoreFocus=true)=>{
    if(closed)return;
    const restore=restoreFocus && valid() && !document.hidden && returnFocus?.isConnected && !returnFocus.disabled;
    closed=true;revision++;sample?.dispose();sample=null;
    if(group.open)group.close();group.remove();onClose();
    if(restore)returnFocus.focus();
    else if(returnFocus && document.activeElement===returnFocus)returnFocus.blur();
  };
  const heading=document.createElement('h2');heading.textContent='字体与字符诊断';group.append(heading);
  const context=document.createElement('p');context.textContent=`当前终端字体：JetBrainsMono Nerd Font Mono · ${fontSize}px。`;group.append(context);
  const guidance=document.createElement('p');guidance.textContent='本地只读示例。检查每行右侧 | 是否同列、图标是否缺字、组合重音是否叠在字母上。预期列数不含标记和补齐空格。异常时可考虑使用无图标主题，不会修改远端配置。';group.append(guidance);
  const choiceLabel=document.createElement('label');choiceLabel.textContent='诊断样例 ';
  const choice=document.createElement('select');choice.className='font-diagnostics-choice';choice.setAttribute('aria-label','诊断样例');
  for(const [value,label] of [['glyphs','字符列宽'],['powerlevel10k','Powerlevel10k'],['oh-my-posh','Oh My Posh']]){const option=document.createElement('option');option.value=value;option.textContent=label;choice.append(option);}
  choice.value='glyphs';choiceLabel.append(choice);group.append(choiceLabel);
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent='正在载入本地示例…';group.append(status);
  const scroller=document.createElement('div');scroller.className='font-diagnostics-scroll';scroller.setAttribute('aria-label','本地诊断终端，可横向滚动');scroller.setAttribute('tabindex','0');
  const host=document.createElement('div');host.className='font-diagnostics-terminal';host.setAttribute('aria-label','固定 16 列、8 行的只读终端示例');scroller.append(host);group.append(scroller);
  const legend=document.createElement('ol');legend.className='font-diagnostics-legend';group.append(legend);
  const closeButton=document.createElement('button');closeButton.type='button';closeButton.textContent='关闭诊断';closeButton.onclick=close;group.append(closeButton);
  group.addEventListener('cancel',event=>{event.preventDefault();close();});
  group.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
  // Establish the neutral trigger as the native dialog's restoration target.
  returnFocus?.focus();document.body.append(group);
  try {if(typeof group.showModal!=='function')throw Error('modal_unavailable');group.showModal();closeButton.focus();}
  catch(error){group.remove();throw error;}

  async function draw(kind) {
    const attempt=++revision;sample?.dispose();sample=null;host.replaceChildren();legend.replaceChildren();scroller.scrollLeft=0;
    const active=()=>valid() && attempt===revision;
    status.textContent='正在载入本地示例…';for(const key of ['sampleId','columns','rows','expectedCursorColumn','expectedCursorRow','actualCursorColumn','actualCursorRow','cursorMatch'])delete status.dataset[key];
    const glyphs=kind==='glyphs';legend.className=glyphs?'font-diagnostics-legend':'font-diagnostics-legend font-diagnostics-theme-legend';
    guidance.textContent=glyphs?'本地只读示例。检查每行右侧 | 是否同列、图标是否缺字、组合重音是否叠在字母上。预期列数不含标记和补齐空格。异常时可考虑使用无图标主题，不会修改远端配置。':'本地只读提示符样例。可在终端区域横向滚动，比较图标、颜色与光标位置；不会运行主题或修改远端设置。';
    let owned=null;
    try {
      const fixture=await (glyphs?loadFixture():loadThemes());if(!active())return;
      if(!(glyphs?validFixture(fixture):validThemePromptSamples(fixture)))throw Error('fixture_invalid');
      const item=glyphs?null:fixture.samples.find(s=>s.id===kind);
      if(!glyphs && !item)throw Error('sample_missing');
      const columns=glyphs?16:40,rows=glyphs?8:3;
      host.setAttribute('aria-label',`固定 ${columns} 列、${rows} 行的只读终端示例`);
      let faceLoaded=false;
      if(document.fonts?.load)try {faceLoaded=(await document.fonts.load(`${fontSize}px ProbeNerd`)).length>0;} catch {}
      if(!active())return;
      if(glyphs)for(const entry of fixture.samples){const li=document.createElement('li');li.textContent=`${entry.label} · 预期 ${entry.cells} 列`;legend.append(li);}
      else {const li=document.createElement('li');li.textContent=`${item.label} · 预期光标：第 ${item.cursorRow+1} 行、第 ${item.cursorColumn+1} 列`;legend.append(li);status.dataset.expectedCursorColumn=String(item.cursorColumn);status.dataset.expectedCursorRow=String(item.cursorRow);}
      owned=terminalFactory({cols:columns,rows,fontFamily:'ProbeNerd, monospace',fontSize,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme});sample=owned;
      owned.parser?.registerOscHandler(52,()=>true);owned.parser?.registerOscHandler(8,()=>true);
      owned.open(host);
      if(owned.textarea){owned.textarea.setAttribute('inputmode','none');owned.textarea.setAttribute('aria-hidden','true');owned.textarea.setAttribute('tabindex','-1');owned.textarea.readOnly=true;owned.textarea.disabled=true;}
      owned.write(glyphs?fixture.write:item.ansi,()=>{
        if(!active() || sample!==owned)return;
        status.dataset.sampleId=kind;
        if(Number.isSafeInteger(owned.cols) && owned.cols>0)status.dataset.columns=String(owned.cols);
        if(Number.isSafeInteger(owned.rows) && owned.rows>0)status.dataset.rows=String(owned.rows);
        const font=faceLoaded?'字体资源已载入；部分字符可能使用系统回退字体。':'字体加载未确认；部分字符可能使用系统回退字体。';
        if(glyphs)status.textContent=`示例已绘制，${font}请自行核对。`;
        else {
          const buffer=owned.buffer?.active,x=buffer?.cursorX,y=buffer?.cursorY;
          const measured=owned.cols===columns && owned.rows===rows && Number.isInteger(x) && x>=0 && x<columns && Number.isInteger(y) && y>=0 && y<rows;
          if(measured){status.dataset.actualCursorColumn=String(x);status.dataset.actualCursorRow=String(y);status.dataset.cursorMatch=String(x===item.cursorColumn && y===item.cursorRow);}
          status.textContent=measured?`实际光标：第 ${y+1} 行、第 ${x+1} 列；${x===item.cursorColumn && y===item.cursorRow?'与预期一致':'与预期不同，请核对列宽'}。${font}`:`示例已绘制；实际光标位置未能读取，请对照预期核查。${font}`;
        }
      });
    } catch {
      owned?.dispose();if(!active())return;if(sample===owned)sample=null;
      status.textContent='本地诊断样例不可用，请稍后重试；远端观察不受影响。';
    }
  }
  choice.onchange=()=>{if(valid() && ['glyphs','powerlevel10k','oh-my-posh'].includes(choice.value))void draw(choice.value);};
  void draw('glyphs');
  return {element:group,close,valid};
}
