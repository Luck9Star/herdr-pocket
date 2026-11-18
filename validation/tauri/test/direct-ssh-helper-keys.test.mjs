import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";
import { initDirectSshUI } from "../src/direct-ssh-ui.js";

const flush = () => new Promise((resolve) => setImmediate(resolve));
class Element {
  constructor() {
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.dataset = {};
    this.listeners = {};
    this.children = [];
  }
  addEventListener(type, fn) {
    this.listeners[type] = fn;
  }
  querySelectorAll() {
    return this.children;
  }
  setAttribute() {}
  closest() {
    return this;
  }
}
function setup() {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
  const nodes = Object.fromEntries(ids.map((id) => [id, new Element()]));
  nodes["ssh-host"].value = "example.test";
  nodes["ssh-port"].value = "22";
  nodes["ssh-user"].value = "user";
  nodes["ssh-hide-keyboard"].disabled = true;
  nodes["ssh-terminal"].parentElement = new Element();
  const buttons = ["esc", "tab", "up", "down", "left", "right", "ctrl-c"].map(
    (key) => {
      const b = new Element();
      b.dataset.sshKey = key;
      return b;
    },
  );
  nodes["ssh-helper-keys"].children = buttons;
  const original = {
    document: globalThis.document,
    requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame,
    ResizeObserver: globalThis.ResizeObserver,
  };
  const document = {
    hidden: false,
    activeElement: null,
    getElementById: (id) => nodes[id],
    addEventListener(type, fn) {
      this[type] = fn;
    },
  };
  globalThis.document = document;
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.ResizeObserver = undefined;
  let channel,
    count = 0,
    block = null;
  const calls = [],
    terminals = [];
  const invoke = async (cmd, args) => {
    calls.push({ cmd, args });
    if (cmd === "ssh_host_key_probe")
      return {
        host: args.host,
        port: args.port,
        publicKey: "ssh-ed25519 key",
        fingerprint: "SHA256:test",
      };
    if (cmd === "ssh_shell_open") return `s${++count}`;
    if (cmd === "ssh_shell_write" && block) await block;
    return {};
  };
  const terminalFactory = () => {
    const t = {
      textarea: new Element(),
      modes: { applicationCursorKeysMode: false },
      open() {},
      onData(fn) {
        this.output = fn;
      },
      dispose() {},
      focus() {
        document.activeElement = this.textarea;
      },
      resize() {},
    };
    terminals.push(t);
    return t;
  };
  const ui = initDirectSshUI({
    native: true,
    invoke,
    channelFactory: () => (channel = {}),
    terminalFactory,
  });
  async function connect() {
    await nodes["ssh-probe"].onclick();
    nodes["ssh-review"].checked = true;
    nodes["ssh-password"].value = "temporary";
    await nodes["ssh-form"].onsubmit({ preventDefault() {} });
    channel.onmessage({ sessionId: `s${count}`, seq: 1, kind: "ready" });
    await flush();
  }
  function click(key) {
    const button = buttons.find((b) => b.dataset.sshKey === key);
    nodes["ssh-helper-keys"].onclick({ target: button });
  }
  return {
    nodes,
    buttons,
    document,
    calls,
    terminals,
    ui,
    connect,
    get channel() { return channel; },
    click,
    block(p) {
      block = p;
    },
    restore() {
      Object.assign(globalThis, original);
    },
  };
}

test("ready shows the connected identity even if form values change without events", async () => {
  const h = setup();
  try {
    await h.nodes["ssh-probe"].onclick();
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-password"].value = "secret-password";
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    const oldChannel = h.channel;
    h.nodes["ssh-host"].value = "changed.test";
    h.nodes["ssh-user"].value = "changed";
    oldChannel.onmessage({ sessionId: "s1", seq: 1, kind: "ready" });
    assert.equal(h.nodes["ssh-target"].textContent, "user@example.test:22 · SSH 已连接");
    h.nodes["ssh-disconnect"].onclick();
    await flush();
    assert.equal(h.nodes["ssh-target"].textContent, "");
    h.nodes["ssh-host"].value = "example.test";
    h.nodes["ssh-user"].value = "next";
    await h.connect();
    oldChannel.onmessage({ sessionId: "s1", seq: 2, kind: "ready" });
    assert.equal(h.nodes["ssh-target"].textContent, "next@example.test:22 · SSH 已连接");
  } finally { h.restore(); }
});

test("IPv6 and a long username remain fully represented in the connected label", async () => {
  const h = setup();
  try {
    h.nodes["ssh-host"].value = "2001:db8::1234";
    h.nodes["ssh-user"].value = "a".repeat(120);
    await h.connect();
    assert.equal(h.nodes["ssh-target"].textContent, `${"a".repeat(120)}@[2001:db8::1234]:22 · SSH 已连接`);
  } finally { h.restore(); }
});

test("hide keyboard blurs only the current connected terminal without invoking SSH", async () => {
  const h = setup();
  try {
    const button = h.nodes["ssh-hide-keyboard"];
    assert.equal(button.disabled, true);
    button.onclick();
    assert.deepEqual(h.calls, []);

    await h.connect();
    const previous = h.terminals[0].textarea;
    const blurred = [];
    previous.blur = () => blurred.push(previous);
    h.nodes["ssh-disconnect"].onclick();
    await flush();
    assert.equal(button.disabled, true);
    const disconnectedCalls = h.calls.slice();
    button.onclick();
    await flush();
    assert.deepEqual(blurred, []);
    assert.deepEqual(h.calls, disconnectedCalls);

    await h.connect();
    assert.equal(button.disabled, false);
    const current = h.terminals[1].textarea;
    current.blur = () => {
      blurred.push(current);
      h.document.activeElement = null;
    };
    h.nodes["ssh-focus"].onclick();
    assert.equal(h.document.activeElement, current);
    const connectedCalls = h.calls.slice();
    button.onclick();
    await flush();
    assert.deepEqual(blurred, [current]);
    assert.equal(h.document.activeElement, null);
    assert.equal(h.ui.isReady(), true);
    assert.deepEqual(h.calls, connectedCalls);
  } finally { h.restore(); }
});

test("ordinary SSH helper keys send ordered bytes and preserve terminal focus", async () => {
  const h = setup();
  try {
    await h.connect();
    assert.ok(h.buttons.every((b) => !b.disabled));
    h.terminals[0].focus();
    let prevented = false;
    h.nodes["ssh-helper-keys"].onpointerdown({
      preventDefault() {
        prevented = true;
      },
    });
    assert.equal(prevented, true);
    assert.equal(h.document.activeElement, h.terminals[0].textarea);
    h.terminals[0].output("x");
    for (const key of ["esc", "tab", "up", "down", "left", "right", "ctrl-c"])
      h.click(key);
    await flush();
    assert.deepEqual(
      h.calls
        .filter((c) => c.cmd === "ssh_shell_write")
        .map((c) => c.args.bytes),
      [
        [120],
        [27],
        [9],
        [27, 91, 65],
        [27, 91, 66],
        [27, 91, 68],
        [27, 91, 67],
        [3],
      ],
    );
    h.terminals[0].modes.applicationCursorKeysMode = true;
    h.click("up");
    h.click("left");
    await flush();
    assert.deepEqual(
      h.calls
        .filter((c) => c.cmd === "ssh_shell_write")
        .slice(-2)
        .map((c) => c.args.bytes),
      [
        [27, 79, 65],
        [27, 79, 68],
      ],
    );
  } finally {
    h.restore();
  }
});

test("queued and old controls cannot write after hide, target change, disconnect or reconnect", async () => {
  const h = setup();
  try {
    await h.connect();
    let release;
    h.block(new Promise((resolve) => (release = resolve)));
    h.click("esc");
    await flush();
    h.click("tab");
    const oldClick = h.nodes["ssh-helper-keys"].onclick,
      oldOutput = h.terminals[0].output;
    h.ui.hide();
    h.nodes["home-ssh"].hidden = true;
    h.nodes["home-ssh"].hidden = false;
    release();
    await flush();
    await flush();
    assert.deepEqual(
      h.calls
        .filter((c) => c.cmd === "ssh_shell_write")
        .map((c) => c.args.bytes),
      [[27]],
    );
    h.block(null);
    h.ui.show();
    oldClick({ target: h.buttons[0] });
    oldOutput("old");
    h.click("down");
    await flush();
    assert.deepEqual(
      h.calls
        .filter((c) => c.cmd === "ssh_shell_write")
        .map((c) => c.args.bytes),
      [[27], [27, 91, 66]],
    );
    h.nodes["ssh-user"].listeners.input();
    await flush();
    assert.ok(h.buttons.every((b) => b.disabled));
    oldClick({ target: h.buttons[0] });
    oldOutput("old");
    await flush();
    assert.equal(h.calls.filter((c) => c.cmd === "ssh_shell_write").length, 2);
    await h.connect();
    oldClick({ target: h.buttons[0] });
    oldOutput("old");
    h.click("ctrl-c");
    await flush();
    assert.deepEqual(
      h.calls
        .filter((c) => c.cmd === "ssh_shell_write")
        .map((c) => [c.args.sessionId, c.args.bytes]),
      [
        ["s1", [27]],
        ["s1", [27, 91, 66]],
        ["s2", [3]],
      ],
    );
    h.document.hidden = true;
    h.document.visibilitychange();
    h.click("esc");
    await flush();
    assert.equal(h.calls.filter((c) => c.cmd === "ssh_shell_write").length, 3);
  } finally {
    h.restore();
  }
});
