const ids=new Set(['powerlevel10k','oh-my-posh']);
const bytes=value=>new TextEncoder().encode(value).length;
const exactKeys=(value,keys)=>!!value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).length===keys.length && keys.every(key=>Object.hasOwn(value,key));
// Private-use glyphs are printable prompt content; format/control characters,
// including bidi controls and unpaired surrogates, are never accepted.
const printable=value=>/^[\p{L}\p{M}\p{N}\p{P}\p{S}\p{Zs}\p{Co}]*$/u.test(value);
function validAnsi(value) {
  const token=/\x1b\[[0-9;]*m|\r\n|[\p{L}\p{M}\p{N}\p{P}\p{S}\p{Zs}\p{Co}]+/uy;
  let offset=0,newlines=0;
  while(offset<value.length){
    token.lastIndex=offset;const part=token.exec(value);
    if(!part || part[0]==='\r\n' && ++newlines>2)return false;
    offset=token.lastIndex;
  }
  return true;
}
export function validThemePromptSamples(value) {
  if(!exactKeys(value,['schemaVersion','id','columns','rows','samples']) || value.schemaVersion!==1 || value.id!=='theme-prompt-samples-v1' || value.columns!==40 || value.rows!==3 || !Array.isArray(value.samples) || value.samples.length!==2)return false;
  try {if(bytes(JSON.stringify(value))>16384)return false;}catch{return false;}
  const seen=new Set();
  for(const sample of value.samples){
    if(!exactKeys(sample,['id','label','ansi','cursorColumn','cursorRow']) || !ids.has(sample.id) || seen.has(sample.id) || typeof sample.label!=='string' || !sample.label.trim() || bytes(sample.label)>160 || !printable(sample.label) || typeof sample.ansi!=='string' || !sample.ansi || bytes(sample.ansi)>4096 || !Number.isInteger(sample.cursorColumn) || sample.cursorColumn<0 || sample.cursorColumn>=40 || !Number.isInteger(sample.cursorRow) || sample.cursorRow<0 || sample.cursorRow>=3)return false;
    seen.add(sample.id);
    if(!validAnsi(sample.ansi))return false;
  }
  return true;
}

export async function loadThemePromptSamples() {
  const response=await fetch('/shared/theme-prompt-samples-v1.json');
  if(!response.ok)throw Error('theme_fixture_unavailable');
  const text=await response.text();
  if(bytes(text)>16384)throw Error('theme_fixture_too_large');
  const fixture=JSON.parse(text);
  if(!validThemePromptSamples(fixture))throw Error('theme_fixture_invalid');
  return fixture;
}
