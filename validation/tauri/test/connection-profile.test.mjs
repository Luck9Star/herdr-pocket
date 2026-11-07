import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parseConnectionProfile,previewConnectionProfile } from '../src/connection-profile.js';
const corpus=JSON.parse(await readFile(new URL('../../shared/connection-profile-v1.json',import.meta.url),'utf8'));
for(const item of corpus.valid)test(`connection profile valid: ${item.name}`,async()=>{
  const preview=await previewConnectionProfile(item.raw);assert.equal(preview.fingerprint,item.fingerprint);
  assert.deepEqual({...parseConnectionProfile(item.raw)},JSON.parse(item.raw));
  for(const [key,value]of Object.entries(preview.profile))assert.ok(preview.text.includes(`${key}: ${value}`),key);
});
for(const item of corpus.invalid)test(`connection profile rejects: ${item.name}`,()=>assert.throws(()=>parseConnectionProfile(item.raw)));
test('accepts surrounding JSON whitespace; preserves astral path UTF-8',()=>{
  const base=JSON.parse(corpus.valid[0].raw);base.herdrPath='/工具/😀/herdr';
  assert.equal(parseConnectionProfile(' \n'+JSON.stringify(base)+'\r\t ').herdrPath,base.herdrPath);
});
