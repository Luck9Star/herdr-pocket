import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dashboardPresentation, paneStatusText } from '../src/dashboard-presentation.js';

const snapshot = JSON.parse(readFileSync(new URL('../../shared/dashboard-snapshot.json', import.meta.url), 'utf8'));
// Exercise presentation-shaped rows based on the shared snapshot. Native
// metadata sanitization and protocol validation have their own transport tests.
const panes = snapshot.result.snapshot.panes.map(row => ({
  paneId: row.pane_id, terminalId: row.terminal_id, label: row.label,
  agent: row.display_agent, agentStatus: row.agent_status,
}));

test('shared snapshot working and future states retain order and future stays unknown', () => {
  const view = dashboardPresentation(panes);
  assert.deepEqual(view.panes, panes);
  assert.equal(view.attentionCount, 0);
  assert.equal(view.summary, '请选择本次会话中的 pane。');
  assert.equal(paneStatusText(panes[0]), 'Codex · 工作中');
  assert.equal(paneStatusText(panes[1]), '窗格状态 · 状态未知');
});

test('only exact blocked moves first without mutating snapshot rows or identities', () => {
  const blocked = Object.freeze({...panes[1], agentStatus: 'blocked'});
  const working = Object.freeze({...panes[0]});
  const source = Object.freeze([working, blocked]);
  const before = JSON.stringify(source);
  const view = dashboardPresentation(source);
  assert.deepEqual(view.panes, [blocked, working]);
  assert.strictEqual(view.panes[0], blocked);
  assert.strictEqual(view.panes[1], working);
  assert.equal(JSON.stringify(source), before);
  assert.equal(view.attentionCount, 1);
  assert.equal(view.summary, '待处理优先 · 1 个受阻窗格（主机报告）。请选择本次会话中的 pane。');
});

test('multiple blocked rows and remaining rows each retain their source order', () => {
  const rows = ['working', 'blocked', 'done', 'blocked', 'unknown', 'blocked'].map((agentStatus, index) =>
    Object.freeze({paneId: `w1:p${index + 1}`, terminalId: `term_${index + 1}`, agentStatus}));
  const view = dashboardPresentation(Object.freeze(rows));
  const order = [1, 3, 5, 0, 2, 4];
  order.forEach((sourceIndex, index) => assert.strictEqual(view.panes[index], rows[sourceIndex]));
  assert.equal(view.attentionCount, 3);
  assert.match(view.summary, /3 个受阻窗格（主机报告）/);
});

test('labels, agent names, future states and differently cased statuses cannot imply blocked', () => {
  const rows = [undefined, 'unknown', 'future-value', 'Blocked', 'BLOCKED', 'constructor', 'toString', '__proto__']
    .map((agentStatus, index) => ({paneId: `w1:p${index + 1}`, terminalId: `term_${index + 1}`,
      label: 'blocked approval needs attention', agent: 'blocked reviewer', agentStatus}));
  const view = dashboardPresentation(rows);
  rows.forEach((row, index) => {
    assert.strictEqual(view.panes[index], row);
    assert.equal(paneStatusText(row), 'blocked reviewer · 状态未知');
  });
  assert.equal(view.attentionCount, 0);
  assert.doesNotMatch(view.summary, /待处理|受阻|0 个/);
});

test('missing agent reports pane state without inventing an Agent identity', () => {
  for (const agent of [undefined, null, '']) {
    assert.equal(paneStatusText({agent, agentStatus: 'blocked'}), '窗格状态 · 受阻');
    assert.equal(paneStatusText({agent, agentStatus: 'working'}), '窗格状态 · 工作中');
    assert.equal(paneStatusText({agent}), '窗格状态 · 状态未知');
  }
});

test('legacy panes without status preserve bindings and order without a pending count', () => {
  const legacy = panes.map(({paneId, terminalId}) => Object.freeze({paneId, terminalId}));
  const view = dashboardPresentation(Object.freeze(legacy));
  legacy.forEach((row, index) => {
    assert.strictEqual(view.panes[index], row);
    assert.equal(paneStatusText(row), '窗格状态 · 状态未知');
  });
  assert.equal(view.attentionCount, 0);
  assert.equal(view.summary, '请选择本次会话中的 pane。');
});

test('empty snapshot remains empty and asks to stop without a pending count', () => {
  const view = dashboardPresentation(Object.freeze([]));
  assert.deepEqual(view.panes, []);
  assert.equal(view.attentionCount, 0);
  assert.equal(view.summary, '当前会话没有可观察的 pane；请停止连接。');
});
