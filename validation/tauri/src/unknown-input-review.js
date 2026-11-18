import {displayDraft} from './input-codec.js';

// Memory-only display of an ambiguous send; never returns it to a send queue.
export function unknownInputRecord({label, target, bytes, text, scope, hostId}) {
  let content=text;
  if (content == null) {
    try { content=new TextDecoder('utf-8',{fatal:true}).decode(bytes); }
    catch { content=null; }
  }
  return {label, target:{...target}, scope, hostId, timestamp:Date.now(),
    content:content == null ? null : displayDraft(content)};
}

export function renderUnknownInputReview(container, record, target, previous=false) {
  container.replaceChildren();
  const shown=record?.target || target;
  container.hidden=!shown;
  if (!shown) return;
  const element=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
  container.append(element('strong',previous ? '原目标发送记录待核实' : '发送记录待核实 · 输入已锁定'));
  container.append(element('p',`原目标：${record?.label || '当前已核验连接'} · ${shown.paneId} · ${shown.terminalId}`));
  container.append(element('p',record ? `发送时间：${new Date(record.timestamp).toLocaleString()}` : '发送时间不可用；请核对原目标。'));
  container.append(element('p','本次记录只供核对，不会重试或恢复为可发送草稿。'));
  if (previous) container.append(element('p','目标或身份已变化；请查看原记录并重新选择目标。'));
  if (record?.content != null) container.append(element('pre',record.content));
  else container.append(element('p','原始内容未保存在本次页面内；请通过原目标独立核实。'));
}
