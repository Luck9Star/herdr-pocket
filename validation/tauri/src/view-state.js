/** Presentation policy only. ViewGate remains the authority for accepting bytes. */
export function viewState(gate) {
  const usable = gate.ready && gate.visible && gate.focused && !gate.unknown;
  let tone = 'neutral';
  let title = '观察模式 · 不发送输入';
  let detail = '可以选择和复制终端文字；进入输入模式后才会记录按键。';
  if (gate.unknown) {
    tone = 'warning';
    title = '发送结果待核实 · 输入已锁定';
    detail = gate.ready
      ? '新全量画面已到达。请核实原目标结果并明确确认，再选择输入模式；不会自动补发。'
      : '先恢复可信连接与新全量画面，再核实原目标结果；不会排队、补发或回填已发送内容。';
  } else if (!gate.ready || !gate.visible) {
    tone = 'warning';
    title = '画面尚未就绪 · 输入已锁定';
    detail = gate.reason;
  } else if (gate.mode === 'direct') {
    tone = 'brand';
    title = '逐键输入 · 按键立即发送到明确目标';
    detail = '本验证壳仅本地捕获字节；IME 提交前留在本地，粘贴先核对。';
  } else if (gate.mode === 'draft') {
    tone = 'brand';
    title = '草稿模式 · 编辑内容暂不发送';
    detail = '预览并确认后只尝试一次，不自动追加回车；每个目标保留独立草稿。';
  }
  return {
    tone, title, detail,
    canChooseMode: usable,
    canType: usable && gate.mode === 'direct',
    canPaste: usable && gate.mode !== 'observe',
    canSendDraft: usable && gate.mode === 'draft',
    canAcknowledge: gate.ready && gate.visible && gate.focused && gate.unknown,
    showRecovery: gate.unknown || !gate.ready || !gate.visible,
  };
}
