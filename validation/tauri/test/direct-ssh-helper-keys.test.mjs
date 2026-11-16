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
  const ids = [
    "ssh-host",
    "ssh-port",
    "ssh-user",
    "ssh-password",
    "ssh-key",
    "ssh-passphrase",
    "ssh-auth-method",
    "ssh-review",
    "ssh-probe",
    "ssh-form",
    "ssh-status",
    "ssh-focus",
    "ssh-setup",
    "ssh-live",
    "ssh-fingerprint",
      "ssh-key-change",
      "ssh-key-change-old",
      "ssh-key-change-new",
      "ssh-key-change-target",
      "ssh-key-change-note",
      "ssh-key-recheck",
      "ssh-key-cancel",
    "ssh-target",
    "ssh-disconnect",
    "ssh-cancel",
    "ssh-terminal",
    "ssh-page-heading",
    "ssh-helper-keys",
    "home-ssh",
    "host-home",
  ];
  const nodes = Object.fromEntries(ids.map((id) => [id, new Element()]));
  nodes["ssh-host"].value = "example.test";
  nodes["ssh-port"].value = "22";
  nodes["ssh-user"].value = "user";
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
        host: "example.test",
        port: 22,
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
    click,
    block(p) {
      block = p;
    },
    restore() {
      Object.assign(globalThis, original);
    },
  };
}

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
