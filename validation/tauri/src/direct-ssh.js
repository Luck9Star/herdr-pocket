/** Direct SSH lifecycle. Never replay writes or retain credentials between attempts. */
export function createDirectSsh({invoke, channelFactory, onStatus, onData}) {
  let generation = 0;
  let sessionId = null;
  let ready = false;
  let connecting = false;
  let sequence = 0;
  let reviewed = null;
  // What the refused handshake actually presented, and the pin that was in effect.
  let presentedFingerprint = null;
  let pinnedFingerprint = null;
  // A refused handshake blocks the target until the same target is probed and
  // confirmed again; the pin in effect survives the refusal.
  let blocked = false;
  let probeGeneration = 0;
  let writes = Promise.resolve();

  const sameTarget = (target, key) => key && target.host === key.host && Number(target.port) === key.port;
  function invalidateReview() { probeGeneration++; reviewed = null; }
  async function probe(target) {
    const current = ++probeGeneration;
    reviewed = null;
    const key = await invoke('ssh_host_key_probe', {host: target.host, port: Number(target.port)});
    if (current !== probeGeneration || !sameTarget(target, key) || !key.publicKey || !key.fingerprint) return null;
    // Seeing the freshly probed key is not approving it: the pin that was in
    // effect survives a failed probe and survives a successful one until a
    // reviewed connection actually succeeds. Only a different target clears it.
    reviewed = key;
    blocked = false;
    presentedFingerprint = null;
    return key;
  }
  async function close({explicit = false} = {}) {
    const current = ++generation;
    ready = false;
    connecting = false;
    const id = sessionId;
    sessionId = null;
    let closed = false;
    if (id) {
      // Tauri serializes Rust unit as null; JavaScript callers can return void.
      try {
        const response = await invoke('ssh_shell_close', {sessionId: id});
        closed = response === null || response === undefined;
      } catch {}
    }
    if (current !== generation) return;
    if ((id || explicit) && !closed) {
      onStatus('已结束本地会话；无法确认远端连接已关闭。', false, 'close_unconfirmed', {closed, explicit});
    } else {
      onStatus(closed ? '已断开；重新连接需要再次输入凭据。' : '尚未连接。', false, undefined, {closed, explicit});
    }
  }
  async function open(target, credentials, confirmed) {
    if (!confirmed || !sameTarget(target, reviewed)) throw Error('review_required');
    if (!!credentials.password === !!credentials.privateKeyPem) throw Error('credential_required');
    const connectionTarget = Object.freeze({host: target.host, port: Number(target.port), username: target.username});
    const closing = close();
    const guard = generation;
    await closing;
    if (guard !== generation || !confirmed || !sameTarget(connectionTarget, reviewed)) return false;
    const current = ++generation;
    const key = {publicKey: reviewed.publicKey, fingerprint: reviewed.fingerprint};
    const early = [];
    let assigned = null;
    sequence = 0;
    const channel = channelFactory();
    function deliver(event) {
      if (current !== generation || !assigned || event?.sessionId !== assigned || !Number.isSafeInteger(event.seq) || event.seq <= sequence) return;
      sequence = event.seq;
      if (event.kind === 'ready') {
        connecting = false; ready = true;
        // A reviewed connection that actually succeeds is the only thing that
        // replaces the trust in effect; seeing a probed key never is.
        pinnedFingerprint = key.fingerprint || pinnedFingerprint;
        onStatus('已连接，可以输入。', true, undefined, {target: connectionTarget});
      }
      else if (event.kind === 'data' && Array.isArray(event.data)) {
        const seq = event.seq;
        let acknowledged = false;
        onData(new Uint8Array(event.data), () => {
          if (acknowledged || current !== generation || assigned !== sessionId) return;
          acknowledged = true;
          void invoke('ssh_shell_ack', {sessionId:assigned, seq}).catch(() => {
            if (current === generation) { ready = false; onStatus('终端数据确认失败；请断开后重新连接。', false); }
          });
        });
      }
      else if (event.kind === 'host_key_change') {
        // Only the fingerprint the refused handshake presented is kept.
        presentedFingerprint = event.presentedFingerprint || null;
        pinnedFingerprint = (reviewed && reviewed.fingerprint) || pinnedFingerprint;
        blocked = true;
      }
      else if (event.kind === 'exit' || event.kind === 'error') {
        connecting = false; ready = false;
        const messages = {host_key_mismatch:'主机公钥与已核对的指纹不一致，连接已拒绝。请重新探测并核对。', authentication_failed:'认证失败，请检查用户名和认证方式后重试。', rsa_sha2_required:'服务器未提供 RSA SHA-2 用户认证，当前 RSA 私钥无法登录。'};
        if (event.error === 'host_key_mismatch') {
          pinnedFingerprint = pinnedFingerprint || (reviewed && reviewed.fingerprint) || null;
          invalidateReview();
          blocked = true;
        }
        onStatus(event.kind === 'exit' ? '远端会话已结束。' : messages[event.error] || '连接失败或已中断，请核查连接资料。', false, event.error || event.kind,
          event.error === 'host_key_mismatch' ? {presentedFingerprint, pinnedFingerprint, blocked: true} : undefined);
      }
    }
    channel.onmessage = event => { if (!assigned) early.push(event); else deliver(event); };
    const authentication = credentials.password
      ? {password: credentials.password}
      : {privateKeyPem: credentials.privateKeyPem, ...(credentials.privateKeyPassphrase ? {privateKeyPassphrase: credentials.privateKeyPassphrase} : {})};
    const config = {...connectionTarget,
      expectedHostKey: key.publicKey, reviewConfirmed: true, cols: 80, rows: 24, ...authentication};
    connecting = true;
    onStatus('正在连接…', false, 'connecting');
    let id;
    try { id = await invoke('ssh_shell_open', {config, onEvent: channel}); }
    catch { if (current === generation) { connecting = false; onStatus('连接未能启动，请核查连接资料。', false, 'error'); } return false; }
    if (current !== generation) { try { await invoke('ssh_shell_close', {sessionId: id}); } catch {} return false; }
    assigned = id; sessionId = id;
    for (const event of early) deliver(event);
    return true;
  }
  function write(bytes, stillCurrent = () => true) {
    const id = sessionId, current = generation;
    if (!ready || !id || !bytes.length) return;
    // Serialize chunks; a failed/unknown write stops the queue and is never retried.
    for (let offset = 0; offset < bytes.length; offset += 4096) {
      const chunk = Array.from(bytes.slice(offset, offset + 4096));
      writes = writes.then(async () => {
        if (current !== generation || !ready || sessionId !== id || !stillCurrent()) return;
        try { await invoke('ssh_shell_write', {sessionId: id, bytes: chunk}); }
        catch { ready = false; onStatus('输入结果未知；已停止发送，请核查远端状态。', false); }
      });
    }
  }
  async function resize(cols, rows) {
    const id = sessionId, current = generation;
    if (!ready || !id) return false;
    try { await invoke('ssh_shell_resize', {sessionId:id, cols, rows}); return current === generation && id === sessionId && ready; }
    catch { if (current === generation && id === sessionId) { ready = false; onStatus('终端尺寸更新失败；请检查连接。', false); } return false; }
  }
  return {probe, invalidateReview, open, close, write, resize, isReady: () => ready, isActive: () => ready || connecting,
    isBlocked: () => blocked, pinnedFingerprint: () => pinnedFingerprint,
    resetTargetBlock: () => { blocked = false; presentedFingerprint = null; pinnedFingerprint = null; }};
}
