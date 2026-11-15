import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

function luminance(hex) {
  const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255)
    .map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
  return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];
}
function contrast(a,b) {
  const [light,dark]=[luminance(a),luminance(b)].sort((x,y)=>y-x);
  return (light+0.05)/(dark+0.05);
}
function topLevelCss(css) {
  return css.replace(/@media[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}/g,'');
}

test('cross-width inactive tab rules keep desktop and narrow-window normal and hover surfaces readable',async()=>{
  const tokens=JSON.parse(await readFile(new URL('../../shared/design-tokens-v2.json',import.meta.url),'utf8'));
  const colors=tokens.colors;
  assert.ok(contrast(colors.termText,colors.termSurface)>=4.5);
  assert.ok(contrast(colors.termText,colors.termKeyBg)>=4.5);
  const css=await readFile(new URL('../src/style.css',import.meta.url),'utf8');
  const topLevel=topLevelCss(css);
  assert.match(topLevel,/#tab-workspace #view-tabs button\[aria-pressed=false\]\s*\{\s*color:var\(--hp-termText\);\s*\}/);
  assert.match(topLevel,/#tab-workspace #view-tabs button\[aria-pressed=false\]:hover:not\(:disabled\)\s*\{\s*color:var\(--hp-termText\);\s*background:var\(--hp-termKeyBg\);\s*\}/);
  assert.match(topLevel,/#tab-workspace #view-tabs button:focus-visible\s*\{\s*outline-color:var\(--hp-brandBorder\);\s*\}/);
});
