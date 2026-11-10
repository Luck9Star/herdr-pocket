// 桌面工作台侧栏（切片 1）：≥900px 的真实远端页在 #workbench-sidebar 显示主机与待处理摘要。
// 数据与主机看板同源（hostRecords + HostDashboardSummary 快照），不建第二份状态。
// 主机资料不可达时必须显示原因与重试入口，不允许渲染成空列表（docs/05-product-design.md:81）。
// 本切片只做展示与既有回调转发：不含键盘导航/分屏，也不触碰任何 PTY 或画布尺寸（docs/05:137）。
import {blockedTargetList} from './blocked-target-list.js';
import {hostSummaryText} from './host-dashboard-summary.js';

function pairingText(host) {
  if (host.pairingStatus === 'revoked') return '已撤销';
  if (host.pairingStatus === 'awaiting-host') return '待主机响应';
  if (host.pairingStatus === 'cancelled') return '配对已取消';
  return host.deviceFingerprint ? '已配对' : '未配对';
}

export function initDesktopWorkbench({hosts, activeHostId, provider, hostStatus, store, isBusy, onOpenHost, onOpenBlocked, onRetry}) {
  const $ = id => document.getElementById(id);
  const list = $('workbench-host-list'), errorMessage = $('workbench-host-error'), retry = $('workbench-host-retry'),
        pending = $('workbench-pending-list'), hostCount = $('workbench-host-count'), pendingCount = $('workbench-pending-count');
  let unavailable = null, deferred = false;
  retry.onclick = () => { if (!retry.hidden) onRetry(); };

  function renderUnavailable() {
    errorMessage.hidden = !unavailable;
    errorMessage.textContent = unavailable?.reason || '';
    retry.hidden = !(unavailable?.retry);
  }
  function renderHostCards(records) {
    list.replaceChildren();
    for (const host of records) {
      const card = document.createElement('button');
      card.type = 'button'; card.className = 'host-card'; card.dataset.hostId = host.id;
      const text = document.createElement('span');
      const name = document.createElement('strong'); name.textContent = host.name;
      const meta = document.createElement('small');
      meta.textContent = `${provider(host) || '系统连接'} · ${host.enabled ? pairingText(host) : '已停用'}`;
      text.append(name, meta); card.append(text);
      card.title = `${hostStatus(host.id)} · ${hostSummaryText(store.get(host))}`;
      card.setAttribute('aria-pressed', String(host.id === activeHostId()));
      card.disabled = isBusy() || !host.enabled;
      card.onclick = () => { if (!card.disabled) onOpenHost(host.id); };
      list.append(card);
    }
    // 可达但零主机：渲染空态占位而不是空白侧栏；「资料不可达」的错误文案仍归 setUnavailable 管。
    if (!records.length) {
      const empty = document.createElement('p');
      empty.className = 'saved-host-empty';
      empty.textContent = '还没有已存主机。';
      list.append(empty);
    }
    hostCount.textContent = String(records.length);
  }
  function renderPending(records) {
    pending.replaceChildren();
    if (unavailable) {
      const note = document.createElement('p'); note.className = 'workbench-pending-item';
      note.textContent = '主机资料不可用；待处理摘要暂停同步，重读成功后恢复。';
      pending.append(note); pendingCount.textContent = '0'; return;
    }
    let attention = 0;
    for (const host of records) {
      const summary = store.get(host); if (!summary) continue;
      if (summary.current && summary.phase === 'fresh' && summary.count > 0) attention++;
      const line = document.createElement('p'); line.className = 'workbench-pending-item';
      line.dataset.workbenchSummary = host.id;
      line.textContent = `${host.name} · 受阻 ${summary.count}${summary.unknown ? `（${summary.unknown} 状态未知）` : ''} · ${summary.current ? '当前快照' : '已陈旧'}`;
      pending.append(line);
      pending.append(blockedTargetList({store, host, disabled: isBusy(), onOpen: target => onOpenBlocked(host.id, target)}));
    }
    if (!pending.children.length) {
      const empty = document.createElement('p'); empty.className = 'workbench-pending-item';
      empty.textContent = '暂无任务快照；连接主机后显示权威待处理摘要。';
      pending.append(empty);
    }
    pendingCount.textContent = String(attention);
  }
  function render() {
    // 与 #host-list/#host-task-board 相同的纪律：正在被阅读或操作的按钮不被重绘打断，
    // 焦点离开后再补上最新清单。
    if (list.contains(document.activeElement) || pending.contains(document.activeElement)) { deferred = true; return; }
    deferred = false;
    renderUnavailable();
    const records = hosts();
    if (unavailable) { list.replaceChildren(); hostCount.textContent = '0'; }
    else renderHostCards(records);
    renderPending(records);
  }
  for (const panel of [list, pending]) panel.addEventListener('focusout', () => queueMicrotask(() => {
    if (deferred && !list.contains(document.activeElement) && !pending.contains(document.activeElement)) render();
  }));
  return {
    render,
    setUnavailable(reason, {retry: canRetry = true} = {}) { unavailable = {reason, retry: canRetry}; render(); },
    clearUnavailable() { unavailable = null; render(); },
  };
}
