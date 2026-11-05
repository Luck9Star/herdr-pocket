import test from 'node:test';
import assert from 'node:assert/strict';
import { previewPairingResponse } from '../src/pairing-view.js';
test('preview presents fields for independent review without treating them as trusted', () => {
  const text=previewPairingResponse(JSON.stringify({account:'runner',host_key:'SHA256:host',fingerprint:'SHA256:device',status:'authorized',request_id:'123',issued_at:100,expires_at:700,authorization_added:true}));
  for(const value of ['runner','SHA256:host','SHA256:device','授权','100','700','未经认证']) assert.ok(text.includes(value));
});
test('preview rejects malformed values and oversized UTF-8 input', () => {
  assert.throws(()=>previewPairingResponse('{}'));
  assert.throws(()=>previewPairingResponse('中'.repeat(800)));
  assert.throws(()=>previewPairingResponse('{'));
});
