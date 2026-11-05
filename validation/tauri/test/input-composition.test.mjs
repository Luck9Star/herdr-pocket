import test from 'node:test';
import assert from 'node:assert/strict';
import { InputComposition } from '../src/input-composition.js';
test('late IME completion is rejected after focus or generation changes', () => {
  const gate=new InputComposition(); const old={generation:1,epoch:2,revision:3};
  gate.begin(old); gate.end();
  assert.equal(gate.accepts({...old,revision:4}),false);
  gate.begin(old); gate.end();
  assert.equal(gate.accepts({...old,generation:2}),false);
  gate.begin(old); gate.end(); assert.equal(gate.accepts(old),true);
});
