import test from 'node:test';
import assert from 'node:assert/strict';
import { auxiliaryKey, draftBytes, displayDraft } from '../src/input-codec.js';
test('auxiliary cursor keys follow terminal cursor mode',()=>{
  assert.equal(auxiliaryKey('up',false),'\x1b[A'); assert.equal(auxiliaryKey('up',true),'\x1bOA');
  assert.equal(auxiliaryKey('ctrl-c',true),'\x03'); assert.equal(auxiliaryKey('invalid',false),null);
});
test('draft uses bounded bracketed paste and rejects embedded closing marker',()=>{
  assert.deepEqual([...draftBytes('文',false)],[230,150,135]);
  assert.equal(new TextDecoder().decode(draftBytes('abc',true)),'\x1b[200~abc\x1b[201~');
  assert.equal(draftBytes('x\x1b[201~bad',true),null);
  assert.equal(draftBytes('x'.repeat(4090),true),null);
});

test('preview exposes hidden control and bidi formatting characters',()=>{
  assert.equal(displayDraft('a\x1b\u202eb\nc'), 'a\\u{1b}\\u{202e}b⏎\nc');
});
