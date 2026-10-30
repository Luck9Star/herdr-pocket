import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { ViewGate } from '../src/gate.js';
import { viewState } from '../src/view-state.js';
import { readTheme } from '../src/theme.js';
const ready = () => { const g = new ViewGate('a'); g.focus(true); const t=g.reconnect(); g.consumed(g.receive('full','screen',t)); return g; };
test('unknown recovery keeps all sending controls locked after full until explicit acknowledgement', () => {
  const g=ready(); g.setMode('direct'); g.unknownSend();
  assert.equal(viewState(g).showRecovery,true); assert.equal(viewState(g).canAcknowledge,false);
  const t=g.reconnect(); g.consumed(g.receive('full','new screen',t));
  const locked=viewState(g); assert.equal(locked.canChooseMode,false); assert.equal(locked.canType,false); assert.equal(locked.canPaste,false); assert.equal(locked.canSendDraft,false); assert.equal(locked.canAcknowledge,true);
  assert.equal(g.acknowledgeUnknown(g.token()),true);
  assert.equal(viewState(g).canChooseMode,true); assert.equal(viewState(g).canType,false);
  g.setMode('direct'); assert.equal(viewState(g).canType,true);
});
test('inactive split pane and hidden targets cannot expose active sending controls', () => {
  const g=ready(); g.setMode('draft'); assert.equal(viewState(g).canSendDraft,true);
  g.focus(false); assert.equal(viewState(g).canSendDraft,false); assert.equal(viewState(g).canPaste,false); assert.equal(viewState(g).canChooseMode,false);
  g.focus(true); g.hide(); assert.equal(viewState(g).canSendDraft,false); assert.equal(viewState(g).showRecovery,true);
});
test('shared palette rejects a missing ANSI value or changed fixed terminal dimensions', async () => {
  const tokens=JSON.parse(await readFile(new URL('../../shared/design-tokens-v2.json',import.meta.url),'utf8'));
  const theme=readTheme(tokens); assert.equal(Object.keys(theme.terminal).length,21);
  const broken=structuredClone(tokens); delete broken.terminal.ansi.red; assert.throws(()=>readTheme(broken),/Invalid/);
  const resized=structuredClone(tokens); resized.terminal.columns=79; assert.throws(()=>readTheme(resized),/Unsupported/);
});
