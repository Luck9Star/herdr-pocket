// The preview ticket is single-use: changing source or leaving discards it.
export function buildImportChoices(entries, selections) {
  if (!Array.isArray(entries) || entries.length !== selections.size) throw Error('incomplete');
  const used = new Set();
  return entries.map(entry => {
    const action = selections.get(entry.index);
    if (!['add', 'keep', 'replace'].includes(action)) throw Error('incomplete');
    const replaceIds = action === 'replace' ? entry.conflicts.map(c => c.id) : [];
    if (action === 'replace' && !replaceIds.length) throw Error('invalid');
    for (const id of replaceIds) { if (used.has(id)) throw Error('overlap'); used.add(id); }
    return { index: entry.index, action, replaceIds };
  });
}
export function previewIsCurrent(requestEpoch, currentEpoch) { return requestEpoch === currentEpoch; }
export function validExportPassword(value) {
  const points = Array.from(value);
  return points.length >= 12 && points.every(c => { const n = c.codePointAt(0); return n < 0xd800 || n > 0xdfff; }) && new TextEncoder().encode(value).length <= 1024;
}
// Do not open a picker or initiate a download if encryption finished after leaving.
export async function exportIfCurrent(encrypt, isCurrent, save) {
  const bytes = await encrypt();
  if (!isCurrent()) return false;
  await save(bytes);
  return true;
}

export function initConfigTransfer({ native, invoke, getHosts, refreshHosts, onApplied }) {
  const panel = document.getElementById('config-transfer');
  const opener = document.getElementById('config-transfer-open');
  let ticket = null, plan = null, activeHostId = null, fileBytes = null, busy = false, pickerPending = false, epoch = 0, platform = null;
  const selections = new Map();
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  function clearSecrets() { panel.querySelectorAll('input[type=password]').forEach(n => { n.value = ''; }); }
  function discard() { const old = ticket; ticket = null; plan = null; activeHostId = null; selections.clear(); if (old) void invoke('config_discard', { ticket: old }).catch(() => {}); }
  function invalidate() { epoch++; discard(); fileBytes = null; clearSecrets(); panel.querySelector('.config-preview')?.remove(); }
  const describe = target => `${target.username}@${target.host}:${target.port} · 会话 ${target.session}`;
  function render() {
    panel.replaceChildren();
    const heading = el('h2', '加密配置迁移'); heading.id = 'config-transfer-title'; heading.tabIndex = -1; panel.append(heading);
    panel.append(el('p', '仅迁移所选主机的连接资料与网络类型。设备 SSH 私钥、组网身份和秘密、草稿及运行状态均不导出；目标设备需要单独授权和重新配对。'));
    const status = el('p', '', 'remote-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const message = text => { status.textContent = text; };
    const actions = el('div', null, 'config-actions');
    const close = el('button', '关闭'); close.type = 'button'; close.disabled = busy; close.onclick = () => { invalidate(); panel.hidden = true; opener.focus(); }; actions.append(close); panel.append(actions);
    if (!native) { panel.append(el('p', '浏览器预览不提供配置迁移；请使用原生测试应用。'), status); return; }
    if (!['android', 'ios', 'macos', 'webview'].includes(platform)) { panel.append(el('p', '无法确定文件选择方式；请关闭后重新打开。'), status); return; }
    const nativePicker = platform !== 'webview';
    const exportBox = el('fieldset'); exportBox.append(el('legend', '导出所选主机'));
    const selected = [];
    const hosts = getHosts().filter(h => !h.retired);
    if (!hosts.length) exportBox.append(el('p', '没有可导出的主机。'));
    for (const h of hosts) { const label = el('label', null, 'config-option'); const cb = el('input'); cb.type = 'checkbox'; cb.value = h.id; label.append(cb, document.createTextNode(` ${h.name}`)); exportBox.append(label); selected.push(cb); }
    const exportPass = password('导出口令（至少 12 个字符，最多 1024 UTF-8 字节）'); const confirmPass = password('再次输入口令'); exportBox.append(exportPass.label, confirmPass.label);
    const exp = el('button', '加密并保存'); exp.type = 'button'; exp.disabled = busy || !hosts.length;
    exp.onclick = async () => {
      if (busy) return;
      const ids = selected.filter(x => x.checked).map(x => x.value), pass = exportPass.input.value;
      if (!ids.length || ids.length > 16 || !validExportPassword(pass) || pass !== confirmPass.input.value) { clearSecrets(); message('请选择 1 至 16 台主机，输入一致的口令：至少 12 个 Unicode 字符，最多 1024 UTF-8 字节。'); return; }
      const current = epoch; busy = true; exp.disabled = true; close.disabled = true;
      try {
        await exportIfCurrent(async () => { try { return await invoke('config_export', { ids, password: pass }); } finally { clearSecrets(); } },
          () => previewIsCurrent(current, epoch) && !panel.hidden && !document.hidden,
          async bytes => {
            if (nativePicker) { pickerPending = true; try { const saved = await invoke('config_document_save', { bytes }); if (previewIsCurrent(current, epoch) && !panel.hidden) message(saved ? '已保存加密文件；目标设备仍需独立授权。' : '未保存文件。'); } finally { pickerPending = false; } }
            else { const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes)], { type: 'application/octet-stream' })); const a = el('a'); a.href = url; a.download = 'herdr-pocket.hpkt'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); message('已发起下载；请核查保存结果。'); }
          });
      } catch { message('导出或保存未确认，请核查文件；不会自动重试。'); }
      finally { clearSecrets(); busy = false; exp.disabled = false; close.disabled = false; if (!previewIsCurrent(current, epoch) && !panel.hidden) render(); }
    }; exportBox.append(exp); panel.append(exportBox);
    const importBox = el('fieldset'); importBox.append(el('legend', '导入配置'));
    let file;
    if (nativePicker) { const open = el('button', '选择加密文件'); open.type = 'button'; open.disabled = busy; open.onclick = async () => { if (busy) return; invalidate(); const current = epoch; busy = true; pickerPending = true; open.disabled = true; close.disabled = true; try { const bytes = await invoke('config_document_open'); if (!previewIsCurrent(current, epoch) || panel.hidden) return; fileBytes = bytes; message(bytes ? '文件已选择，请输入口令预览。' : '未选择文件。'); } catch { message('文件读取失败；不会自动重试。'); } finally { pickerPending = false; busy = false; open.disabled = false; close.disabled = false; if (!previewIsCurrent(current, epoch) && !panel.hidden) render(); } }; importBox.append(open); }
    else { const label = el('label', '选择加密文件'); file = el('input'); file.type = 'file'; file.accept = '.hpkt,application/octet-stream'; file.disabled = busy; file.onchange = () => { invalidate(); message(file.files.length ? '文件已选择，请输入口令预览。' : '未选择文件。'); }; label.append(file); importBox.append(label); }
    const pass = password('导入口令'); importBox.append(pass.label);
    const preview = el('button', '解密并预览'); preview.type = 'button'; preview.disabled = busy;
    preview.onclick = async () => {
      if (busy) return;
      const secret = pass.input.value; discard(); const current = ++epoch;
      if (!secret || (nativePicker ? !fileBytes : !file?.files?.length)) { clearSecrets(); message('请选择文件并输入口令。'); return; }
      busy = true; preview.disabled = true; close.disabled = true;
      try {
        if (!nativePicker && file.files[0].size > 131072) throw Error('file_too_large');
        const bytes = nativePicker ? fileBytes : Array.from(new Uint8Array(await file.files[0].arrayBuffer()));
        if (!previewIsCurrent(current, epoch)) return;
        const result = await invoke('config_preview', { bytes, password: secret }); clearSecrets();
        if (!previewIsCurrent(current, epoch)) { void invoke('config_discard', { ticket: result.ticket }).catch(() => {}); return; }
        ticket = result.ticket; plan = result.plan; activeHostId = result.activeHostId; fileBytes = null; busy = false; render(); panel.querySelector('.config-preview h3')?.focus();
      } catch { message('无法验证或解密文件，或文件不受支持；没有导入任何资料。'); }
      finally { clearSecrets(); busy = false; preview.disabled = false; close.disabled = false; if (!previewIsCurrent(current, epoch) && !panel.hidden) render(); }
    }; importBox.append(preview); panel.append(importBox);
    if (plan && ticket) {
      const previewBox = el('section', null, 'config-preview'); const previewTitle = el('h3', '逐条审查并选择'); previewTitle.tabIndex = -1; previewBox.append(previewTitle);
      previewBox.append(el('p', `当前活动主机 ID：${activeHostId || '无'}。替换会关闭受影响标签与连接；新目标须重新配对并主动连接。`));
      for (const entry of plan.entries) {
        const group = el('fieldset'); group.append(el('legend', entry.host.label));
        group.append(el('p', `${describe(entry.host.target)} · 网络 ${entry.host.provider}（需单独授权）`));
        if (entry.sameLabelIndices.length) group.append(el('p', `文件中另有同名条目：${entry.sameLabelIndices.map(i => i + 1).join('、')}。`));
        for (const c of entry.conflicts) group.append(el('p', `冲突：${c.name} · ${describe(c.target)}${c.id === activeHostId ? ' · 活动主机，替换将关闭标签' : ''}${c.paired ? ' · 已配对，替换后保留身份并停用，仍可删除或撤销' : ' · 替换后移除本机资料'}`));
        for (const [value, label] of [['add','新增'],['keep','保留现有 / 跳过此条'],['replace','替换全部列出的冲突']]) {
          if (value === 'replace' && !entry.conflicts.length) continue;
          const option = el('label', null, 'config-option'); const radio = el('input'); radio.type = 'radio'; radio.name = `config-choice-${entry.index}`; radio.value = value; radio.checked = selections.get(entry.index) === value; radio.onchange = () => { selections.set(entry.index, value); updateAffected(); }; option.append(radio, document.createTextNode(` ${label}`)); group.append(option);
        }
        previewBox.append(group);
      }
      const affected = el('p', '', 'config-affected'); previewBox.append(affected);
      function updateAffected() { const ids = plan.entries.filter(e => selections.get(e.index) === 'replace').flatMap(e => e.conflicts.map(c => c.id)); affected.textContent = ids.includes(activeHostId) ? '当前活动主机受影响：确认后将关闭其标签与连接。' : '当前选择不替换活动主机。'; }
      updateAffected();
      const apply = el('button', '确认应用所选操作', 'primary'); apply.type = 'button'; apply.disabled = busy;
      apply.onclick = async () => {
        if (busy) return;
        let choices; try { choices = buildImportChoices(plan.entries, selections); } catch { message('请逐条选择操作；同一冲突不能被多条同时替换。'); return; }
        const usedTicket = ticket; ticket = null; plan = null; selections.clear(); busy = true; apply.disabled = true; close.disabled = true;
        try { const result = await invoke('config_apply', { ticket: usedTicket, choices }); await onApplied(result); await refreshHosts(); busy = false; render(); panel.querySelector('[role=status]').textContent = `导入完成：新增 ${result.added.length}，保留停用身份 ${result.retired.length}，移除旧资料 ${result.removedIds.length}。新目标需重新配对。`; }
        catch { await refreshHosts(); busy = false; render(); panel.querySelector('[role=status]').textContent = '导入失败、预览已过期或保存结果未知；请核查主机列表后重新预览，不会自动重试。'; }
        finally { busy = false; clearSecrets(); }
      }; previewBox.append(apply); panel.append(previewBox);
    }
    panel.append(status);
  }
  function password(text) { const label = el('label', text); const input = el('input'); input.type = 'password'; input.autocomplete = 'new-password'; input.maxLength = 1024; label.append(input); return { label, input }; }
  opener.onclick = async () => { invalidate(); platform = null; panel.hidden = false; render(); if (native) { try { platform = await invoke('config_document_platform'); } catch { platform = null; } render(); } panel.querySelector('h2').focus?.(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) { if (pickerPending) { clearSecrets(); return; } invalidate(); if (!panel.hidden) render(); } });
  window.addEventListener('pagehide', invalidate);
  return () => { invalidate(); panel.hidden = true; };
}
