import test from 'node:test';
import assert from 'node:assert/strict';
import { initDirectSshUI } from '../src/direct-ssh-ui.js';

const target = { host: 'example.test', port: 22, username: 'alice' };
const key = { host: 'example.test', port: 22, publicKey: 'ssh-ed25519 AAAA', fingerprint: 'SHA256:test' };

const flush = () => new Promise((r) => setImmediate(r));

// 中 = e4 b8 ad ; 😀 = f0 9f 98 80 ; é = c3 a9
const SPLIT_CHUNKS = [
  { sessionId: 's1', seq: 2, kind: 'data', data: [0x61, 0xe4, 0xb8] },
  { sessionId: 's1', seq: 3, kind: 'data', data: [0xad, 0xf0, 0x9f, 0x98] },
  { sessionId: 's1', seq: 4, kind: 'data', data: [0x80, 0xc3, 0xa9, 0x21] },
];

// Import the production Unicode 15 terminal factory with Buffer hidden so the
// graphemes addon loads its browser build, like the other real-xterm tests.
async function importBrowserUnicodeTerminal() {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'Buffer');
  let module;
  try {
    Object.defineProperty(globalThis, 'Buffer', { configurable: true, writable: true, value: undefined });
    module = await import('../src/terminal-unicode.js');
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'Buffer', descriptor);
    else delete globalThis.Buffer;
  }
  return module;
}

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ''; this.dataset = {}; this.hidden = false; this.disabled = false; this.checked = false; this.style = {}; }
  get tagName() { return this.tag.toUpperCase(); }
  append(...items) { this.children.push(...items); }
  setAttribute() {}
  querySelector() { return null; }
  querySelectorAll() { return this.children; }
  addEventListener() {}
  focus() { globalThis.document.activeElement = this; }
}

// Real @xterm/xterm built by the production createUnicodeTerminal factory,
// driven through the production initDirectSshUI wiring. open() is stubbed
// (needs a full DOM); the UTF-8 decoder, WriteBuffer and cell buffer run for
// real, headless. write() is wrapped only to record the raw bytes handed over.
function uiHarness({ Terminal, createUnicodeTerminal }) {
  const nodes = Object.create(null);
  const ids = ['ssh-host', 'ssh-port', 'ssh-user', 'ssh-password', 'ssh-key', 'ssh-passphrase', 'ssh-auth-method', 'ssh-review', 'ssh-probe', 'ssh-form', 'ssh-connect', 'ssh-status', 'ssh-focus', 'ssh-setup', 'ssh-live', 'ssh-review-row', 'ssh-fingerprint', 'ssh-key-change', 'ssh-key-change-old', 'ssh-key-change-new', 'ssh-key-change-target', 'ssh-key-change-note', 'ssh-key-recheck', 'ssh-key-cancel', 'ssh-target', 'ssh-disconnect', 'ssh-cancel', 'ssh-terminal', 'ssh-page-heading', 'ssh-helper-keys'];
  for (const id of ids) nodes[id] = new Element('div');
  nodes['ssh-host'].value = target.host;
  nodes['ssh-port'].value = String(target.port);
  nodes['ssh-user'].value = target.username;
  nodes['ssh-password'].value = 'x';
  nodes['ssh-review'].checked = true;
  nodes['ssh-terminal'].parentElement = new Element('div');
  const oldDocument = globalThis.document;
  const oldRaf = globalThis.requestAnimationFrame;
  const oldCancelRaf = globalThis.cancelAnimationFrame;
  const oldObserver = globalThis.ResizeObserver;
  globalThis.document = { getElementById: (id) => nodes[id], addEventListener() {}, hidden: false };
  // Own the frame queue instead of leaving setImmediate callbacks alive after
  // the fake document is restored. Frames run explicitly at write/close fences.
  const animationFrames = new Map();
  let frameId = 0;
  globalThis.requestAnimationFrame = (fn) => { const id = ++frameId; animationFrames.set(id, fn); return id; };
  globalThis.cancelAnimationFrame = (id) => animationFrames.delete(id);
  const runAnimationFrames = () => {
    while (animationFrames.size) {
      const frames = [...animationFrames];
      for (const [id, fn] of frames) {
        if (!animationFrames.delete(id)) continue;
        fn(performance.now());
      }
    }
  };
  const observers = [];
  globalThis.ResizeObserver = class { constructor(callback) { observers.push({ callback, observed: [] }); } observe(node) { observers.at(-1).observed.push(node); } };
  const terminals = [], disposals = [], rawWrites = [];
  const terminalFactory = (opts) => {
    const t = createUnicodeTerminal(Terminal, { ...opts, cols: 80, rows: 24, scrollback: 0 });
    t.open = () => {};
    const realDispose = t.dispose.bind(t);
    t.dispose = () => { disposals.push(t); return realDispose(); };
    const realWrite = t.write.bind(t);
    t.write = (bytes, done) => { rawWrites.push([...bytes]); return realWrite(bytes, done); };
    terminals.push(t);
    return t;
  };
  let channel;
  // The fake server numbers sessions by connection count, independent of how
  // many terminal instances the UI created: a reused terminal must still get
  // the second session's events, or the defect would hide behind dropped data.
  let openCount = 0;
  const closedSessions = [], sent = [];
  const invoke = async (command, args) => {
    if (command === 'ssh_host_key_probe') return key;
    if (command === 'ssh_shell_open') return `s${++openCount}`;
    if (command === 'ssh_shell_close') closedSessions.push(args.sessionId);
    if (command === 'ssh_shell_write') sent.push(args.bytes);
    return {};
  };
  const ui = initDirectSshUI({ native: true, invoke, channelFactory: () => (channel = {}), terminalFactory });
  // Production flow: probe fills the fingerprint (controller.reviewed), the
  // user re-checks review (probe unchecks it), re-enters the password (the
  // form clears secrets after every attempt by design), then connects.
  const submit = async () => {
    await nodes['ssh-probe'].onclick();
    nodes['ssh-review'].checked = true;
    nodes['ssh-password'].value = 'x';
    await nodes['ssh-form'].onsubmit({ preventDefault() {} });
    await flush();
    await flush();
  };
  const emit = (sessionId, events) => { for (const e of events) channel.onmessage({ sessionId, ...e }); };
  const readLine = (t, row = 0) => {
    const line = t.buffer.active.getLine(row);
    let text = '';
    for (let i = 0; i < 20; i++) text += line.getCell(i).getChars();
    return text;
  };
  // Progress is driven by write completion callbacks, never fixed sleeps.
  const written = async (t) => { await new Promise((resolve) => t.write('', resolve)); runAnimationFrames(); };
  const dataWrites = () => rawWrites.filter((w) => w.length);
  const cleanup = async () => {
    try {
      ui.close();
      // close() deliberately returns void; this event-loop fence lets its
      // resolved native-close promise stop the real resizer before frames run.
      await flush();
      assert.equal(ui.isActive(), false, 'teardown closes the real controller');
      await Promise.all(terminals.filter((t) => !disposals.includes(t)).map(written));
      runAnimationFrames();
      for (const t of terminals) if (!disposals.includes(t)) t.dispose();
      assert.equal(animationFrames.size, 0, 'no frame callback outlives the fixture');
    } finally {
      globalThis.document = oldDocument;
      globalThis.requestAnimationFrame = oldRaf;
      globalThis.cancelAnimationFrame = oldCancelRaf;
      globalThis.ResizeObserver = oldObserver;
    }
  };
  return { nodes, terminals, disposals, observers, closedSessions, sent, dataWrites, submit, emit, readLine, written, cleanup, pendingFrames: () => animationFrames.size };
}

async function realXtermHarness() {
  const { default: pkg } = await import('@xterm/xterm');
  const { createUnicodeTerminal } = await importBrowserUnicodeTerminal();
  return uiHarness({ Terminal: pkg.Terminal, createUnicodeTerminal });
}

test('ordinary SSH arrows follow actual xterm DECCKM across enable and disable', async () => {
  const ui = await realXtermHarness();
  try {
    await ui.submit(); ui.emit('s1', [{seq:1,kind:'ready'}]);
    const clickUp = () => ui.nodes['ssh-helper-keys'].onclick({target:{closest:()=>({dataset:{sshKey:'up'}})}});
    clickUp(); await flush();
    ui.emit('s1', [{seq:2,kind:'data',data:[27,91,63,49,104]}]); await ui.written(ui.terminals[0]);
    clickUp(); await flush();
    ui.emit('s1', [{seq:3,kind:'data',data:[27,91,63,49,108]}]); await ui.written(ui.terminals[0]);
    clickUp(); await flush();
    assert.deepEqual(ui.sent, [[27,91,65],[27,79,65],[27,91,65]]);
  } finally { await ui.cleanup(); }
});

test('same connection: SSH chunks split mid-UTF-8 render CJK/emoji without replacement chars (real xterm)', async () => {
  const ui = await realXtermHarness();
  try {
    await ui.submit();
    ui.emit('s1', [{ seq: 1, kind: 'ready' }, ...SPLIT_CHUNKS]);
    await ui.written(ui.terminals[0]);
    const line = ui.readLine(ui.terminals[0]);
    assert.ok(line.startsWith('a中😀é!'), `line rendered: ${JSON.stringify(line)}`);
    assert.ok(!line.includes('\uFFFD'), 'no U+FFFD replacement char');
    // Raw-byte wiring: chunk boundaries preserved, no decode/re-encode/loss.
    assert.deepEqual(ui.dataWrites(), SPLIT_CHUNKS.map((c) => c.data));
  } finally { await ui.cleanup(); }
});

test('reconnection: fresh xterm isolates the previous session (real xterm)', async () => {
  const ui = await realXtermHarness();
  try {
    // Session 1 ends on a dangling half emoji (f0 9f); xterm's reset() does
    // not clear WriteBuffer interim bytes, so reusing the instance would
    // continue the old code point with the next session's first bytes.
    await ui.submit();
    ui.emit('s1', [
      { seq: 1, kind: 'ready' },
      { seq: 2, kind: 'data', data: [0x61, 0xf0, 0x9f] },
    ]);
    await ui.written(ui.terminals[0]);
    assert.equal(ui.readLine(ui.terminals[0]), 'a');
    ui.nodes['ssh-disconnect'].onclick();
    await flush();
    await ui.submit();
    // User-visible check first: the new session's opening bytes are the tail
    // of the old half code point plus "Z". On a fresh terminal they must
    // render as plain "Z" (orphan continuation bytes dropped) followed by the
    // session's own output — NOT the carried-over "😀Z中!". On the old
    // reuse-and-reset implementation this exact input renders "😀Z中!".
    ui.emit('s2', [
      { seq: 1, kind: 'ready' },
      { seq: 2, kind: 'data', data: [0x98, 0x80, 0x5a] },
      { seq: 3, kind: 'data', data: [...new TextEncoder().encode('中!')] },
    ]);
    await ui.written(ui.terminals.at(-1));
    const line2 = ui.readLine(ui.terminals.at(-1));
    assert.ok(!line2.includes('😀'), `old half code point must not continue into the new session: ${JSON.stringify(line2)}`);
    assert.ok(!line2.includes('\uFFFD'), 'no U+FFFD replacement char');
    assert.ok(line2.startsWith('Z中!'), `new session renders only its own output: ${JSON.stringify(line2)}`);
    // Structural checks after the user-visible one.
    assert.equal(ui.terminals.length, 2, 'reconnection creates a fresh terminal');
    assert.notEqual(ui.terminals[0], ui.terminals[1]);
    assert.ok(ui.disposals.includes(ui.terminals[0]), 'previous terminal is disposed on reconnection');
    // One resize watcher total: reconnections reuse it, never stack.
    assert.equal(ui.observers.length, 1, 'ResizeObserver created exactly once across reconnections');
  } finally { await ui.cleanup(); }
});

test('fixture teardown closes a ready SSH session and drains its queued animation frame', async () => {
  const oldDocument = globalThis.document;
  const oldRaf = globalThis.requestAnimationFrame;
  const oldCancelRaf = globalThis.cancelAnimationFrame;
  const ui = await realXtermHarness();
  try {
    await ui.submit();
    ui.emit('s1', [{ seq: 1, kind: 'ready' }]);
    assert.equal(ui.pendingFrames(), 1, 'ready queues the production resizer frame');
  } finally { await ui.cleanup(); }
  assert.deepEqual(ui.closedSessions, ['s1'], 'teardown closes the live native session');
  assert.equal(ui.pendingFrames(), 0);
  assert.deepEqual(ui.disposals, ui.terminals, 'all real terminals are disposed exactly once');
  assert.equal(globalThis.document, oldDocument);
  assert.equal(globalThis.requestAnimationFrame, oldRaf);
  assert.equal(globalThis.cancelAnimationFrame, oldCancelRaf);
});
