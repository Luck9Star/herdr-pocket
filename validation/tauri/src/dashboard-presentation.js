/** Presentation only: retain each reviewed snapshot binding and source order. */
export function dashboardPresentation(panes) {
  const blocked = [], remaining = [];
  for (const pane of panes) (pane.agentStatus === 'blocked' ? blocked : remaining).push(pane);
  const attentionCount = blocked.length;
  const instruction = panes.length ? '请选择本次会话中的 pane。' : '当前会话没有可观察的 pane；请停止连接。';
  return {
    panes: [...blocked, ...remaining],
    attentionCount,
    summary: attentionCount ? `待处理优先 · ${attentionCount} 个受阻窗格（主机报告）。${instruction}` : instruction,
  };
}

export function paneStatusText(pane) {
  let status;
  switch (pane.agentStatus) {
    case 'idle': status = '空闲'; break;
    case 'working': status = '工作中'; break;
    case 'blocked': status = '受阻'; break;
    case 'done': status = '已完成'; break;
    default: status = '状态未知';
  }
  return `${pane.agent || '窗格状态'} · ${status}`;
}
