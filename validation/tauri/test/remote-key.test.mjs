import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizePrivateKeyInput } from '../src/remote-key.js';
import { RemoteViewGate } from '../src/remote-state.js';
test('password input newline stripping preserves a fixed OpenSSH PEM envelope',()=>{
  // Synthetic payload, not a key or credential.
  const body='YQ'.repeat(40),begin='-----BEGIN OPENSSH PRIVATE KEY-----',end='-----END OPENSSH PRIVATE KEY-----';
  const expected=`${begin}\n${body.slice(0,64)}\n${body.slice(64)}\n${end}\n`;
  assert.equal(normalizePrivateKeyInput(begin+body+end),expected);
  assert.equal(normalizePrivateKeyInput(`${begin}\r\n${body}\r\n${end}\r\n`),expected);
});
test('normalization never accepts extra PEM material or changes malformed data',()=>{
  for(const value of ['synthetic-invalid-key','-----BEGIN RSA PRIVATE KEY-----YWJj-----END RSA PRIVATE KEY-----','-----BEGIN OPENSSH PRIVATE KEY-----YW;Jj-----END OPENSSH PRIVATE KEY-----'])assert.equal(normalizePrivateKeyInput(value),value);
});
test('synthetic malformed password input never throws or prevents attempt cleanup',()=>{
  const gate=new RemoteViewGate();gate.reviewed=true;const generation=gate.begin();
  try { assert.equal(normalizePrivateKeyInput('synthetic-invalid-key'),'synthetic-invalid-key'); }
  finally { gate.finish(generation);gate.reviewed=false; }
  assert.equal(gate.pending,false);assert.equal(gate.begin(),null);
  gate.reviewed=true;assert.ok(gate.begin()>generation);
});
