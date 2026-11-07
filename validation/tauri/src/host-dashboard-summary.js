// A host gets one latest authoritative session snapshot; tabs are never summed.
export function hostSummaryIdentity(host) {
  if (!host || !host.id || !host.target || !host.enabled || host.retired || !host.deviceFingerprint) return null;
  if (host.networkProfileId && host.networkRevision == null) return null;
  return JSON.stringify({id:host.id,target:host.target,deviceFingerprint:host.deviceFingerprint,networkProfileId:host.networkProfileId ?? null,networkRevision:host.networkRevision ?? null});
}
export class HostDashboardSummary {
  #records = new Map();
  #owners = new Map();

  reconcile(hosts) {
    const identities = new Map(hosts.map(host => [host.id, hostSummaryIdentity(host)]));
    for (const entries of [this.#records, this.#owners]) {
      for (const [id, entry] of entries) {
        if (identities.get(id) !== entry.identity) entries.delete(id);
      }
    }
  }

  suspendAll() {
    this.#owners.clear();
    let changed = false;
    for (const id of this.#records.keys()) {
      if (this.invalidateHost(id)) changed = true;
    }
    return changed;
  }

  begin(host, source) {
    const identity = hostSummaryIdentity(host);
    if (!identity || !source) return false;
    this.#owners.set(host.id, {identity, source});
    return this.invalidateHost(host.id);
  }

  publish(host, source, board) {
    const identity = hostSummaryIdentity(host);
    const owner = this.#owners.get(host?.id);
    if (!identity || !source || owner?.identity !== identity || owner.source !== source) return false;
    if (!Array.isArray(board?.panes) || !Number.isFinite(board.capturedAt) ||
        !['fresh', 'unavailable'].includes(board.phase)) return false;

    this.#records.set(host.id, {
      identity, source, session: host.target.session, current: true,
      count: board.panes.filter(pane => pane.agentStatus === 'blocked').length,
      unknown: board.panes.filter(pane => !['blocked', 'idle', 'working', 'done'].includes(pane.agentStatus)).length,
      capturedAt: board.capturedAt, phase: board.phase,
    });
    return true;
  }

  invalidateSource(hostId, source) {
    return this.#records.get(hostId)?.source === source && this.invalidateHost(hostId);
  }

  invalidateHost(hostId) {
    const record = this.#records.get(hostId);
    if (!record?.current) return false;
    record.current = false;
    return true;
  }

  get(host) {
    const record = this.#records.get(host.id);
    return record && record.identity === hostSummaryIdentity(host) ? record : null;
  }

  order(hosts) {
    const blocked = [];
    const others = [];
    for (const host of hosts) {
      const summary = this.get(host);
      const priority = summary?.current && summary.phase === 'fresh' && summary.count > 0;
      (priority ? blocked : others).push(host);
    }
    return [...blocked, ...others];
  }
}
export function hostSummaryText(summary) {
  if(!summary)return '任务状态未知 · 尚无本次运行的权威会话快照';
  const time=new Date(summary.capturedAt).toLocaleString();
  const blocked=summary.unknown ? `受阻至少 ${summary.count}（${summary.unknown} 个状态未知）` : `受阻 ${summary.count}`;
  return `${summary.current ? (summary.phase==='unavailable'?'本次快照（持续更新不可用）':'当前快照') : '上次快照（状态已陈旧）'} · 会话 ${summary.session} · ${blocked} · 同步 ${time}`;
}
