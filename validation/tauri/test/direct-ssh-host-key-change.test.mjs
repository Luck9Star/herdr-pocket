import test from "node:test";
import assert from "node:assert/strict";
import { initDirectSshUI } from "../src/direct-ssh-ui.js";

const flush = () => new Promise((resolve) => setImmediate(resolve));
// Local-only fake host keys; no real host is contacted.
const REVIEWED = { fingerprint: "SHA256:reviewedLocalOnly", publicKey: "ssh-ed25519 reviewed-local-only" };
const CHANGED = { fingerprint: "SHA256:changedLocalOnly", publicKey: "ssh-ed25519 changed-local-only" };

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
  dispatchEvent(event) {
    this.listeners[event.type]?.(event);
    return true;
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
    "home-ssh",
    "host-home",
  ];
  const nodes = Object.fromEntries(ids.map((id) => [id, new Element()]));
  nodes["ssh-host"].value = "127.0.0.1";
  nodes["ssh-port"].value = "2222";
  nodes["ssh-user"].value = "tester";
  nodes["ssh-terminal"].parentElement = new Element();
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
  let channel;
  let probed = REVIEWED;
  let presented = "SHA256:presentedLocalOnly";
  let accept = false;
  let session = 0;
  const calls = [];
  const invoke = async (cmd, args) => {
    calls.push({ cmd, args });
    if (cmd === "ssh_host_key_probe") return { host: args.host, port: Number(args.port), ...probed };
    if (cmd === "ssh_shell_open") {
      const id = `s${++session}`;
      // The refused handshake reports the key it presented, then the refusal follows.
      setImmediate(() => {
        if (accept) {
          channel.onmessage({ sessionId: id, seq: 1, kind: "ready" });
          return;
        }
        if (presented) {
          channel.onmessage({ sessionId: id, seq: 1, kind: "host_key_change", presentedFingerprint: presented });
        }
        channel.onmessage({ sessionId: id, seq: presented ? 2 : 1, kind: "error", error: "host_key_mismatch" });
      });
      return id;
    }
    if (cmd === "ssh_shell_close") return {};
    return {};
  };
  const terminalFactory = () => ({
    textarea: new Element(),
    modes: { applicationCursorKeysMode: false },
    open() {},
    onData() {},
    dispose() {},
    focus() {},
    resize() {},
  });
  initDirectSshUI({ native: true, invoke, channelFactory: () => (channel = {}), terminalFactory });
  async function probe() {
    await nodes["ssh-probe"].onclick();
  }
  async function connect() {
    nodes["ssh-review"].checked = true;
    nodes["ssh-password"].value = "temporary-local-secret";
    await nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
  }
  function openCalls() {
    return calls.filter((call) => call.cmd === "ssh_shell_open");
  }
  return {
    nodes,
    calls,
    document,
    probe,
    connect,
    openCalls,
    setProbed: (key) => {
      probed = key;
    },
    setPresented: (value) => {
      presented = value;
    },
    setAccept: (value) => {
      accept = value;
    },
    restore: () => {
      globalThis.document = original.document;
      globalThis.requestAnimationFrame = original.requestAnimationFrame;
      globalThis.cancelAnimationFrame = original.cancelAnimationFrame;
      globalThis.ResizeObserver = original.ResizeObserver;
    },
  };
}

test("a changed host key refuses the connection, blocks input and returns to the review step", async () => {
  const h = setup();
  try {
    await h.probe();
    assert.ok(h.nodes["ssh-fingerprint"].textContent.includes(REVIEWED.fingerprint));
    assert.ok(h.nodes["ssh-fingerprint"].textContent.includes("127.0.0.1:2222"));
    await h.connect();
    assert.match(h.nodes["ssh-status"].textContent, /主机公钥与已核对的指纹不一致/);
    assert.match(h.nodes["ssh-status"].textContent, /连接已拒绝/);
    // The reviewed fingerprint stays visible, the confirmation is revoked and no session exists.
    assert.ok(h.nodes["ssh-fingerprint"].textContent.includes(REVIEWED.fingerprint));
    assert.equal(h.nodes["ssh-review"].checked, false);
    assert.equal(h.nodes["ssh-live"].hidden, true);
    assert.equal(h.nodes["ssh-focus"].disabled, true);
    assert.equal(h.nodes["ssh-password"].value, "");
    assert.equal(h.nodes["ssh-key"].value, "");
    assert.equal(h.nodes["ssh-passphrase"].value, "");
    // The blocked view replaces the setup form, so the password and connect stay off screen.
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.equal(h.nodes["ssh-setup"].hidden, true);
    assert.ok(h.nodes["ssh-key-change-old"].textContent.includes(REVIEWED.fingerprint));
    assert.ok(h.nodes["ssh-key-change-new"].textContent.includes("SHA256:presentedLocalOnly"));
    assert.ok(h.nodes["ssh-key-change-target"].textContent.includes("tester@127.0.0.1:2222"));
    assert.equal(typeof h.nodes["ssh-key-recheck"].onclick, "function");
    assert.equal(typeof h.nodes["ssh-key-cancel"].onclick, "function");
    // The refusal offers the review and cancel exits, and no way past the change.
    assert.equal(h.nodes["ssh-probe"].disabled, false);
    assert.equal(typeof h.nodes["ssh-cancel"].onclick, "function");
    const controls = ["ssh-probe", "ssh-cancel"];
    assert.ok(controls.every((id) => h.nodes[id]));
    const texts = Object.values(h.nodes).map((node) => node.textContent || "");
    assert.equal(texts.some((text) => /忽略|继续使用新指纹|强制接受/.test(text)), false);
  } finally {
    h.restore();
  }
});

test("a refused connection cannot be retried until the fingerprint is verified again", async () => {
  const h = setup();
  try {
    await h.probe();
    await h.connect();
    assert.equal(h.openCalls().length, 1);
    h.nodes["ssh-password"].value = "temporary-local-secret";
    h.nodes["ssh-review"].checked = false;
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
    assert.equal(h.openCalls().length, 1);
    assert.match(h.nodes["ssh-status"].textContent, /主机指纹变化尚未重新核对/);
    assert.equal(h.nodes["ssh-password"].disabled, true);
    assert.equal(h.nodes["ssh-review"].disabled, true);
  } finally {
    h.restore();
  }
});

test("without a presented key the review says a fresh probe is pending", async () => {
  const h = setup();
  try {
    h.setPresented(null);
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.ok(h.nodes["ssh-key-change-new"].textContent.includes("待重新探测"));
    assert.equal(h.nodes["ssh-key-change-new"].textContent.includes(REVIEWED.fingerprint), false);
    assert.equal(h.nodes["ssh-setup"].hidden, true);
    assert.match(h.nodes["ssh-status"].textContent, /连接已拒绝/);
    assert.equal(h.nodes["ssh-review"].checked, false);
    // Cancelling keeps the old trust: the blocked view closes, secrets stay cleared and
    // the changed key is not accepted. A connection needs a fresh probe plus confirmation.
    await h.nodes["ssh-key-cancel"].onclick();
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.equal(h.nodes["ssh-setup"].hidden, false);
    assert.equal(h.nodes["ssh-password"].value, "");
    assert.equal(h.nodes["ssh-review"].checked, false);
    h.nodes["ssh-password"].value = "temporary-local-secret";
    h.nodes["ssh-review"].checked = true;
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
    assert.equal(h.openCalls().length, 1);
    assert.match(h.nodes["ssh-status"].textContent, /主机指纹变化尚未重新核对/);
    assert.equal(h.nodes["ssh-review"].disabled, true);
  } finally {
    h.restore();
  }
});

test("cancelling the review returns to the same target form and keeps every entry locked", async () => {
  const h = setup();
  try {
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    await h.nodes["ssh-key-cancel"].onclick();
    // Back on the setup form for the same target, not on the review page.
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.equal(h.nodes["ssh-setup"].hidden, false);
    assert.equal(h.nodes["ssh-page-heading"].hidden, false);
    assert.equal(h.nodes["ssh-status"].hidden, false);
    // The old trust stays on display and nothing was accepted.
    assert.ok(h.nodes["ssh-fingerprint"].textContent.includes(REVIEWED.fingerprint));
    assert.equal(h.nodes["ssh-password"].value, "");
    assert.equal(h.nodes["ssh-key"].value, "");
    assert.equal(h.nodes["ssh-passphrase"].value, "");
    // Review, authentication and connect stay disabled until the next re-probe.
    assert.equal(h.nodes["ssh-review"].disabled, true);
    assert.equal(h.nodes["ssh-password"].disabled, true);
    assert.equal(h.nodes["ssh-key"].disabled, true);
    assert.equal(h.nodes["ssh-passphrase"].disabled, true);
    assert.equal(h.nodes["ssh-auth-method"].disabled, true);
    assert.equal(h.nodes["ssh-form"].children.every((button) => button.disabled), true);
    // A retry without a re-probe is refused before any session is opened.
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-password"].value = "temporary-local-secret";
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
    assert.equal(h.openCalls().length, 1);
    assert.match(h.nodes["ssh-status"].textContent, /主机指纹变化尚未重新核对/);
    // The next re-probe of the same target releases the entries again.
    await h.probe();
    assert.equal(h.nodes["ssh-review"].disabled, false);
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-review"].dispatchEvent({ type: "change" });
    assert.equal(h.nodes["ssh-password"].disabled, false);
    assert.equal(h.nodes["ssh-auth-method"].disabled, false);
  } finally {
    h.restore();
  }
});

test("the blocked review is the first heading and hides the generic heading and status", async () => {
  const h = setup();
  try {
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.equal(h.nodes["ssh-page-heading"].hidden, true);
    assert.equal(h.nodes["ssh-status"].hidden, true);
    assert.equal(h.nodes["ssh-setup"].hidden, true);
  } finally {
    h.restore();
  }
});

test("a reviewed connection shows the terminal and keeps the setup form out of sight", async () => {
  const h = setup();
  try {
    h.setAccept(true);
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-live"].hidden, false);
    assert.equal(h.nodes["ssh-setup"].hidden, true);
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.match(h.nodes["ssh-status"].textContent, /已连接/);
  } finally {
    h.restore();
  }
});

test("re-probing after a refusal shows the changed key and allows a reviewed connection again", async () => {
  const h = setup();
  try {
    await h.probe();
    await h.connect();
    assert.match(h.nodes["ssh-status"].textContent, /主机公钥与已核对的指纹不一致/);
    h.setProbed(CHANGED);
    await h.nodes["ssh-key-recheck"].onclick();
    await flush();
    assert.ok(h.nodes["ssh-fingerprint"].textContent.includes(CHANGED.fingerprint));
    assert.equal(h.nodes["ssh-review"].checked, false);
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.equal(h.nodes["ssh-setup"].hidden, false);
    h.setProbed(REVIEWED);
    await h.connect();
    assert.equal(h.openCalls().length, 2);
    assert.ok(h.openCalls()[1].args.config.expectedHostKey);
  } finally {
    h.restore();
  }
});
