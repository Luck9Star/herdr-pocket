import test from 'node:test';
import assert from 'node:assert/strict';
import {createDirectSsh} from '../src/direct-ssh.js';
const target = {host:'example.test',port:22,username:'alice'};
const key = {host:'example.test',port:22,publicKey:'ssh-ed25519 AAAA',fingerprint:'SHA256:test'};
function harness({closeReply} = {}) {
  const calls=[], statuses=[], data=[]; let channel, resolveOpen;
  const invoke = async (command,args) => { calls.push({command,args}); if (command==='ssh_host_key_probe') return key; if (command==='ssh_shell_open') return new Promise(resolve => { resolveOpen=resolve; }); if (command==='ssh_shell_close') { if (closeReply==='REJECT') throw Error('local shutdown failed'); return closeReply; } };
  const ssh=createDirectSsh({invoke,channelFactory:()=>channel={},onStatus:(...v)=>statuses.push(v),onData:bytes=>data.push([...bytes])});
  return {ssh,calls,statuses,data,get channel(){return channel;},resolveOpen:id=>resolveOpen(id)};
}
async function opening(h) { await h.ssh.probe(target); const pending=h.ssh.open(target,{password:'secret'},true); await new Promise(resolve=>setImmediate(resolve)); return {pending}; }
test('ready metadata is a captured public identity and excludes credentials',async()=>{
  const h=harness(), selected={...target};
  await h.ssh.probe(selected);
  selected.username='changed';
  const pending=h.ssh.open(selected,{privateKeyPem:'private-secret',privateKeyPassphrase:'passphrase-secret',host:'evil',username:'evil',expectedHostKey:'evil'},true);
  await new Promise(resolve=>setImmediate(resolve));
  h.resolveOpen('s1');await pending;
  h.channel.onmessage({sessionId:'s1',seq:1,kind:'ready'});
  assert.deepEqual(h.statuses.at(-1)[3],{target:{...target,username:'changed'}});
  assert.equal(Object.isFrozen(h.statuses.at(-1)[3].target),true);
  assert.doesNotMatch(JSON.stringify(h.statuses),/private-secret|passphrase-secret/);
  assert.equal(h.calls.find(c=>c.command==='ssh_shell_open').args.config.username,'changed');
  assert.equal(h.calls.find(c=>c.command==='ssh_shell_open').args.config.host,'example.test');
  assert.equal(h.calls.find(c=>c.command==='ssh_shell_open').args.config.expectedHostKey,key.publicKey);
});
test('ready pins the key captured for that connection even after another probe',async()=>{
  let channel, nextKey=key;
  const ssh=createDirectSsh({invoke:async cmd=>cmd==='ssh_host_key_probe'?nextKey:'s1',channelFactory:()=>channel={},onStatus:()=>{},onData:()=>{}});
  await ssh.probe(target);await ssh.open(target,{password:'x'},true);
  nextKey={...key, fingerprint:'SHA256:new',publicKey:'ssh-ed25519 NEW'};
  await ssh.probe(target);
  channel.onmessage({sessionId:'s1',seq:1,kind:'ready'});
  assert.equal(ssh.pinnedFingerprint(),'SHA256:test');
});
test('early events bind to returned identity, input waits for ready and preserves ANSI bytes',async()=>{
  const h=harness(); const {pending}=await opening(h);
  h.channel.onmessage({sessionId:'other',seq:1,kind:'ready'}); h.channel.onmessage({sessionId:'s1',seq:1,kind:'ready'}); h.channel.onmessage({sessionId:'s1',seq:2,kind:'data',data:[27,91,51,49,109]});
  h.resolveOpen('s1'); await pending; assert.equal(h.ssh.isReady(),true); assert.deepEqual(h.data,[[27,91,51,49,109]]);
  h.ssh.write(new Uint8Array([65])); await new Promise(resolve=>setImmediate(resolve)); assert.deepEqual(h.calls.at(-1),{command:'ssh_shell_write',args:{sessionId:'s1',bytes:[65]}});
});
test('cancel before open resolves closes the late session and discards events',async()=>{
  const h=harness(); const {pending}=await opening(h); await h.ssh.close(); h.channel.onmessage({sessionId:'s1',seq:1,kind:'ready'});h.resolveOpen('s1');await pending;
  assert.equal(h.ssh.isReady(),false);assert.ok(h.calls.some(c=>c.command==='ssh_shell_close' && c.args.sessionId==='s1'));
});

test('explicit close accepts only a unit or void acknowledgement and names local failure', async () => {
  for (const [name, closeReply, closed, reason] of [
    ['Rust unit', null, true, undefined],
    ['JavaScript void', undefined, true, undefined],
    ['false', false, false, 'close_unconfirmed'],
    ['uncontracted boolean', true, false, 'close_unconfirmed'],
    ['uncontracted object', {closed: true}, false, 'close_unconfirmed'],
    ['uncontracted string', 'ok', false, 'close_unconfirmed'],
    ['native reject', 'REJECT', false, 'close_failed'],
  ]) {
    const h = harness({closeReply});
    const {pending} = await opening(h);
    h.resolveOpen('s1');
    await pending;
    h.channel.onmessage({sessionId:'s1', seq:1, kind:'ready'});
    await h.ssh.close({explicit:true});
    const last = h.statuses.at(-1);
    assert.equal(last[0], closed ? '本机已断开；凭据已清空，重连时请重新填写。' : '本机连接关闭失败；会话可能仍在。可返回首页。', name);
    assert.deepEqual(last.slice(1), [
      false, reason, {closed, explicit:true, remoteReported:false},
    ], name);
    h.channel.onmessage({sessionId:'s1', seq:2, kind:'ready'});
    h.ssh.write(new Uint8Array([65]));
    assert.equal(h.ssh.isReady(), false, name);
    assert.equal(h.calls.filter(call => call.command === 'ssh_shell_close').length, 1, name);
    assert.equal(h.calls.filter(call => call.command === 'ssh_shell_write').length, 0, name);
  }
});
test('an explicit remote exit report only comes from a valid exitStatus or signal', async () => {
  for (const [event, reported, message] of [
    [{kind:'exit'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitStatus:null}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitStatus:0}, true, '本机已断开；远端已报告结束，凭据已清空。'],
    [{kind:'exit', exitStatus:2}, true, '本机已断开；远端已报告结束，凭据已清空。'],
    [{kind:'exit', exitStatus:'0'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitStatus:-1}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitStatus:4294967296}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitStatus:4294967295}, true, '本机已断开；远端已报告结束，凭据已清空。'],
    [{kind:'exit', exitSignal:'TERM'}, true, '本机已断开；远端已报告结束，凭据已清空。'],
    [{kind:'exit', exitSignal:'sigterm'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitSignal:'TERMIT'} , false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitSignal:'other'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitSignal:'NOT_A_SIGNAL'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit', exitSignal:'  '}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
    [{kind:'exit'}, false, '本机已断开；凭据已清空，重连时请重新填写。'],
  ]) {
    const h = harness({closeReply:null});
    const {pending} = await opening(h);
    h.resolveOpen('s1');
    await pending;
    h.channel.onmessage({sessionId:'s1', seq:1, kind:'ready'});
    h.channel.onmessage({sessionId:'s1', seq:2, ...event});
    assert.equal(h.ssh.remoteReported(), reported);
    await h.ssh.close({explicit:true});
    const last = h.statuses.at(-1);
    assert.equal(last[0], message);
    assert.equal(last[3].remoteReported, reported);
  }
});
test('edits invalidate pin and authentication must be exactly one method',async()=>{
  const h=harness();await h.ssh.probe(target);h.ssh.invalidateReview();await assert.rejects(h.ssh.open(target,{password:'x'},true),/review_required/);
  await h.ssh.probe(target);await assert.rejects(h.ssh.open(target,{password:'x',privateKeyPem:'y'},true),/credential_required/);await assert.rejects(h.ssh.open({...target,host:'other'}, {password:'x'}, true),/review_required/);
});
test('late probe is invalidated by edit',async()=>{
  let resolve;const ssh=createDirectSsh({invoke:()=>new Promise(r=>resolve=r),channelFactory:()=>({}),onStatus:()=>{},onData:()=>{}});
  const probe=ssh.probe(target);ssh.invalidateReview();resolve(key);assert.equal(await probe,null);
});
test('write errors stop later chunks without replay or disclosure',async()=>{
  const calls=[];let channel;const ssh=createDirectSsh({invoke:async(cmd,args)=>{calls.push({cmd,args});if(cmd==='ssh_host_key_probe')return key;if(cmd==='ssh_shell_open')return 's';if(cmd==='ssh_shell_write')throw Error('secret from backend');},channelFactory:()=>channel={},onStatus:(s)=>assert.ok(!s.includes('secret')),onData:()=>{}});
  await ssh.probe(target);await ssh.open(target,{password:'secret'},true);channel.onmessage({sessionId:'s',seq:1,kind:'ready'});ssh.write(new Uint8Array(5000));await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.filter(c=>c.cmd==='ssh_shell_write').length,1);assert.equal(ssh.isReady(),false);
});

test('data acknowledgement occurs once on consumption and late callbacks never ack a new session',async()=>{
  let callback;const calls=[];let channel;
  const ssh=createDirectSsh({invoke:async(cmd,args)=>{calls.push({cmd,args});if(cmd==='ssh_host_key_probe')return key;if(cmd==='ssh_shell_open')return 's';},channelFactory:()=>channel={},onStatus:()=>{},onData:(_bytes,done)=>{callback=done;}});
  await ssh.probe(target);await ssh.open(target,{password:'x'},true);channel.onmessage({sessionId:'s',seq:1,kind:'data',data:[65]});
  assert.equal(calls.filter(c=>c.cmd==='ssh_shell_ack').length,0);callback();callback();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls.filter(c=>c.cmd==='ssh_shell_ack').map(c=>c.args),[{sessionId:'s',seq:1}]);
  channel.onmessage({sessionId:'s',seq:2,kind:'data',data:[66]});await ssh.close();callback();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.filter(c=>c.cmd==='ssh_shell_ack').length,1);
});

test('known authentication and host-key failures are distinguished without exposing error text',async()=>{
  for (const [error,expected] of [['host_key_mismatch',/公钥.*不一致/],['authentication_failed',/认证失败/],['rsa_sha2_required',/RSA SHA-2 用户认证.*RSA 私钥无法登录/],['secret from backend',/连接失败/]]) {
    const h=harness();const {pending}=await opening(h);h.resolveOpen('s1');await pending;
    h.channel.onmessage({sessionId:'s1',seq:1,kind:'error',error});
    assert.match(h.statuses.at(-1)[0],expected);assert.ok(!h.statuses.at(-1)[0].includes('secret from backend'));
    if(error==='host_key_mismatch') await assert.rejects(h.ssh.open(target,{password:'x'},true),/review_required/);
  }
});

test('a late resize failure cannot invalidate a newly connected session',async()=>{
  let channel, rejectResize, nextId=0;const statuses=[];
  const ssh=createDirectSsh({invoke:async cmd=>{
    if(cmd==='ssh_host_key_probe')return key;
    if(cmd==='ssh_shell_open')return `s${++nextId}`;
    if(cmd==='ssh_shell_resize')return new Promise((_resolve,reject)=>{rejectResize=reject;});
  },channelFactory:()=>channel={},onStatus:(...args)=>statuses.push(args),onData:()=>{}});
  await ssh.probe(target);await ssh.open(target,{password:'x'},true);channel.onmessage({sessionId:'s1',seq:1,kind:'ready'});
  const pending=ssh.resize(80,12);await ssh.close();await ssh.open(target,{password:'x'},true);channel.onmessage({sessionId:'s2',seq:1,kind:'ready'});
  rejectResize(Error('late'));assert.equal(await pending,false);assert.equal(ssh.isReady(),true);
  assert.doesNotMatch(statuses.at(-1)[0],/尺寸更新失败/);
});

test('the pin survives failed and unconfirmed re-probes; only a reviewed session replaces it',async()=>{
  let probed=key, probeError=null, channel, nextId=0; const statuses=[];
  const invoke=async cmd=>{
    if(cmd==='ssh_host_key_probe'){ if(probeError) throw probeError; return probed; }
    if(cmd==='ssh_shell_open') return `s${++nextId}`;
    return {};
  };
  const ssh=createDirectSsh({invoke,channelFactory:()=>channel={},onStatus:(...a)=>statuses.push(a),onData:()=>{}});
  // The reviewed connection to A establishes the trust in effect.
  await ssh.probe(target);
  await ssh.open(target,{password:'x'},true);
  channel.onmessage({sessionId:'s1',seq:1,kind:'ready'});
  assert.equal(ssh.pinnedFingerprint(),'SHA256:test');
  // The peer presents a changed key: the refusal blocks the target with A pinned.
  channel.onmessage({sessionId:'s1',seq:2,kind:'host_key_change',presentedFingerprint:'SHA256:changed'});
  assert.equal(ssh.isBlocked(),true);
  assert.equal(ssh.pinnedFingerprint(),'SHA256:test');
  // A failed re-probe keeps the old pin and the block.
  probeError=Error('unreachable');
  await assert.rejects(ssh.probe(target),/unreachable/);
  assert.equal(ssh.isBlocked(),true);
  assert.equal(ssh.pinnedFingerprint(),'SHA256:test');
  // Seeing the re-probed key is not approving it: the pin survives the window
  // between a successful probe and the user's own reviewed connection.
  probeError=null; probed={...key,fingerprint:'SHA256:changed',publicKey:'ssh-ed25519 changed'};
  assert.equal((await ssh.probe(target)).fingerprint,'SHA256:changed');
  assert.equal(ssh.isBlocked(),false);
  assert.equal(ssh.pinnedFingerprint(),'SHA256:test');
  // A reviewed connection that actually succeeds is the only replacement.
  await ssh.open(target,{password:'x'},true);
  channel.onmessage({sessionId:'s2',seq:1,kind:'ready'});
  assert.equal(ssh.pinnedFingerprint(),'SHA256:changed');
  // Leaving the target clears the pin and the block entirely.
  ssh.resetTargetBlock();
  assert.equal(ssh.pinnedFingerprint(),null);
  assert.equal(ssh.isBlocked(),false);
});
