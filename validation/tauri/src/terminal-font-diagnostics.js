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
},returnFocus=null,onClose=()=>{}}) {
  const group=document.createElement('dialog');group.className='terminal-font-diagnostics';group.setAttribute('role','dialog');group.setAttribute('aria-modal','true');group.setAttribute('aria-label','字体与字符诊断');
  let closed=false, sample=null;
  const valid=()=>!closed && current();
  const close=(restoreFocus=true)=>{
    if(closed)return;
    const restore=restoreFocus && valid() && !document.hidden && returnFocus?.isConnected && !returnFocus.disabled;
    closed=true;sample?.dispose();sample=null;
    if(group.open)group.close();group.remove();onClose();
    if(restore)returnFocus.focus();
    else if(returnFocus && document.activeElement===returnFocus)returnFocus.blur();
  };
  const heading=document.createElement('h2');heading.textContent='字体与字符诊断';group.append(heading);
  const context=document.createElement('p');context.textContent=`当前终端字体：JetBrainsMono Nerd Font Mono · ${fontSize}px。`;group.append(context);
  const guidance=document.createElement('p');guidance.textContent='本地只读示例。检查每行右侧 | 是否同列、图标是否缺字、组合重音是否叠在字母上。预期列数不含标记和补齐空格。异常时可考虑使用无图标主题，不会修改远端配置。';group.append(guidance);
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent='正在载入本地示例…';group.append(status);
  const scroller=document.createElement('div');scroller.className='font-diagnostics-scroll';scroller.setAttribute('aria-label','本地诊断终端，可横向滚动');
  const host=document.createElement('div');host.className='font-diagnostics-terminal';host.setAttribute('aria-label','固定 16 列、8 行的只读终端示例');scroller.append(host);group.append(scroller);
  const legend=document.createElement('ol');legend.className='font-diagnostics-legend';group.append(legend);
  const closeButton=document.createElement('button');closeButton.type='button';closeButton.textContent='关闭诊断';closeButton.onclick=close;group.append(closeButton);
  group.addEventListener('cancel',event=>{event.preventDefault();close();});
  group.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
  // Establish the neutral trigger as the native dialog's restoration target.
  returnFocus?.focus();document.body.append(group);
  try {if(typeof group.showModal!=='function')throw Error('modal_unavailable');group.showModal();closeButton.focus();}
  catch(error){group.remove();throw error;}

  void (async()=>{
    try {
      const fixture=await loadFixture();if(!valid())return;
      if(!validFixture(fixture))throw Error('fixture_invalid');
      let faceLoaded=false;
      if(document.fonts?.load)try {faceLoaded=(await document.fonts.load(`${fontSize}px ProbeNerd`)).length>0;} catch {}
      if(!valid())return;
      for(const item of fixture.samples){const li=document.createElement('li');li.textContent=`${item.label} · 预期 ${item.cells} 列`;legend.append(li);}
      sample=terminalFactory({cols:16,rows:8,fontFamily:'ProbeNerd, monospace',fontSize,scrollback:0,disableStdin:true,cursorBlink:false,convertEol:false,theme});
      sample.parser?.registerOscHandler(52,()=>true);sample.parser?.registerOscHandler(8,()=>true);
      sample.open(host);
      if(sample.textarea){sample.textarea.setAttribute('inputmode','none');sample.textarea.setAttribute('aria-hidden','true');sample.textarea.setAttribute('tabindex','-1');sample.textarea.readOnly=true;sample.textarea.disabled=true;}
      sample.write(fixture.write,()=>{if(valid())status.textContent=faceLoaded?'示例已绘制，字体资源已载入；请自行核对，部分字符可能使用系统回退字体。':'示例已绘制，但字体加载未确认；请自行核对，部分字符可能使用系统回退字体。';});
    } catch {sample?.dispose();sample=null;if(valid())status.textContent='本地诊断样例不可用，请稍后重试；远端观察不受影响。';}
  })();
  return {element:group,close,valid};
}
