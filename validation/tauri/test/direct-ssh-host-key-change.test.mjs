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
    this.position = "static";
    this.rect = { top: 0, bottom: 0, height: 0 };
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
  contains(element) {
    return this.children.includes(element);
  }
  getBoundingClientRect() {
    return this.rect;
  }
  setAttribute() {}
  closest() {
    return this;
  }
  blur() {}
}

function setup({ innerHeight = 956, ios = false, headingTop = 161.906, headerBottom = 130 } = {}) {
  const ids = [
    "ssh-host",
    "ssh-port",
    "ssh-user",
    "ssh-password",
    "ssh-password-fields",
    "ssh-key",
    "ssh-key-fields",
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
    "host-open-remote",
    "show-remote",
    "nav-terminal",
    "nav-network",
    "nav-settings",
    "ssh-hide-keyboard",
    "ssh-helper-keys",
  ];
  const nodes = Object.fromEntries(ids.map((id) => [id, new Element()]));
  nodes["ssh-host"].value = "127.0.0.1";
  nodes["ssh-port"].value = "2222";
  nodes["ssh-user"].value = "tester";
  nodes["ssh-terminal"].parentElement = new Element();
  const original = {
    document: globalThis.document,
    window: globalThis.window,
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
  const navGroups = { ".app-header": new Element(), ".route-tabs": new Element() };
  document.querySelector = (selector) => navGroups[selector] || null;
  // Real-WK geometry from the R17 screenshots: the sticky header band ends at
  // y=130; the heading sits at y=161.906 once the page is scrolled to the top.
  navGroups[".app-header"].rect = { top: 0, bottom: headerBottom, height: headerBottom };
  const heading = nodes["ssh-page-heading"];
  heading.rect = { top: headingTop, bottom: headingTop + 28, height: 28 };
  document.documentElement = {
    classList: { contains: (name) => ios && name === "ios-edge-to-edge" },
  };
  const scrolls = [];
  const tops = [];
  const frames = [];
  const view = {
    innerHeight,
    getComputedStyle: (element) => ({ position: element.position }),
    scrollBy: (x, y) => scrolls.push([x, y]),
    scrollTo: (x, y) => tops.push([x, y]),
  };
  globalThis.document = document;
  globalThis.window = view;
  globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
  globalThis.cancelAnimationFrame = () => {};
  globalThis.ResizeObserver = undefined;
  let channel;
  let probed = REVIEWED;
  let presented = "SHA256:presentedLocalOnly";
  let accept = false;
  let probeError = null;
  let session = 0;
  const calls = [];
  const invoke = async (cmd, args) => {
    calls.push({ cmd, args });
    if (cmd === "ssh_host_key_probe") {
      if (probeError) throw probeError;
      return { host: args.host, port: Number(args.port), ...probed };
    }
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
  const runFrames = () => { for (const fn of frames.splice(0)) fn(); };
  return {
    nodes,
    calls,
    document,
    scrolls,
    tops,
    frames,
    runFrames,
    view,
    navGroups,
    heading,
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
    setProbeError: (error) => {
      probeError = error;
    },
    restore: () => {
      globalThis.document = original.document;
      globalThis.window = original.window;
      globalThis.requestAnimationFrame = original.requestAnimationFrame;
      globalThis.cancelAnimationFrame = original.cancelAnimationFrame;
      globalThis.ResizeObserver = original.ResizeObserver;
    },
  };
}

test("confirming the fingerprint reveals the obscured password without focusing or connecting", async () => {
  const h = setup();
  try {
    const password = h.nodes["ssh-password"];
    const review = h.nodes["ssh-review"];
    password.rect = { top: 890, bottom: 936, height: 46 };
    Object.assign(h.navGroups[".route-tabs"], {
      position: "fixed", rect: { top: 891, bottom: 956, height: 65 },
    });
    await h.probe();
    h.document.activeElement = review;
    assert.equal(password.disabled, true);
    assert.deepEqual(h.scrolls, []);

    review.checked = true;
    review.dispatchEvent({ type: "change" });
    assert.equal(password.disabled, false);
    assert.equal(h.scrolls.length, 1);
    assert.ok(password.rect.bottom - h.scrolls[0][1] < h.navGroups[".route-tabs"].rect.top);
    assert.equal(h.document.activeElement, review);
    assert.equal(password.value, "");
    assert.equal(h.openCalls().length, 0);

    review.checked = false;
    review.dispatchEvent({ type: "change" });
    assert.equal(password.disabled, true);
    assert.equal(h.scrolls.length, 1);
  } finally {
    h.restore();
  }
});

test("a visible desktop password stays put and key selection uses the visual viewport", async () => {
  const h = setup();
  try {
    h.nodes["ssh-password"].rect = { top: 560, bottom: 606, height: 46 };
    h.navGroups[".route-tabs"].rect = { top: 60, bottom: 124, height: 64 };
    await h.probe();
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-review"].dispatchEvent({ type: "change" });
    assert.deepEqual(h.scrolls, []);

    const key = h.nodes["ssh-key"];
    key.rect = { top: 610, bottom: 710, height: 100 };
    h.view.visualViewport = { offsetTop: 70, height: 550 };
    h.nodes["ssh-auth-method"].value = "key";
    h.nodes["ssh-auth-method"].dispatchEvent({ type: "change" });
    assert.equal(h.nodes["ssh-password-fields"].hidden, true);
    assert.equal(h.nodes["ssh-key-fields"].hidden, false);
    assert.equal(h.scrolls.length, 1);
    assert.ok(key.rect.bottom - h.scrolls[0][1] < 620);
    assert.equal(h.document.activeElement, null);
    assert.equal(h.openCalls().length, 0);
  } finally {
    h.restore();
  }
});

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

test("key refusal releases focus on a credential before hiding the form", async () => {
  const h = setup();
  try {
    const form = h.nodes["ssh-setup"];
    const field = h.nodes["ssh-password"];
    form.children.push(field);
    h.document.activeElement = field;
    let blurs = 0;
    field.blur = () => {
      assert.equal(form.hidden, false);
      blurs++;
      h.document.activeElement = null;
    };
    await h.probe();
    await h.connect();
    assert.equal(blurs, 1);
    assert.equal(h.document.activeElement, null);
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.equal(form.hidden, true);
    assert.equal(field.value, "");
    assert.equal(field.disabled, true);
    assert.equal(h.openCalls().length, 1);
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
    h.nodes["ssh-password"].rect = { top: 980, bottom: 1026, height: 46 };
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
    assert.deepEqual(h.scrolls, []);
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
    assert.deepEqual(h.scrolls, []);
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-review"].dispatchEvent({ type: "change" });
    assert.equal(h.nodes["ssh-password"].disabled, false);
    assert.equal(h.nodes["ssh-auth-method"].disabled, false);
    assert.equal(h.scrolls.length, 1);
    assert.equal(h.openCalls().length, 1);
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

test("the open change review removes every navigation exit and both exits restore it", async () => {
  const h = setup();
  try {
    // An unrelated reason keeps a nav button disabled; the review must not
    // overwrite that state, it removes the groups instead.
    h.nodes["host-open-remote"].disabled = true;
    h.nodes["nav-network"].disabled = true;
    await h.probe();
    await h.connect();
    // While the review is open the header and the route tabs are gone entirely:
    // only the two review actions remain reachable by mouse or keyboard.
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.equal(h.navGroups[".app-header"].hidden, true);
    assert.equal(h.navGroups[".route-tabs"].hidden, true);
    // Cancelling is the first exit and restores the navigation groups as they were.
    await h.nodes["ssh-key-cancel"].onclick();
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
    assert.equal(h.nodes["host-open-remote"].disabled, true);
    assert.equal(h.nodes["nav-network"].disabled, true);
    // Back on the setup form a retry is refused before any session.
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-password"].value = "temporary-local-secret";
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
    assert.equal(h.openCalls().length, 1);
    assert.match(h.nodes["ssh-status"].textContent, /主机指纹变化尚未重新核对/);
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
    // A successful re-probe releases the target; the next refusal removes the
    // groups again, and the explicit re-probe is the other exit that restores them.
    await h.probe();
    h.setProbed(CHANGED);
    await h.connect();
    assert.equal(h.openCalls().length, 2);
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.equal(h.navGroups[".app-header"].hidden, true);
    assert.equal(h.navGroups[".route-tabs"].hidden, true);
    h.setProbed(CHANGED);
    await h.nodes["ssh-key-recheck"].onclick();
    await flush();
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
  } finally {
    h.restore();
  }
});

test("navigation stays available on ordinary pages without a refusal", async () => {
  const h = setup();
  try {
    h.setAccept(true);
    await h.probe();
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
    await h.connect();
    assert.equal(h.nodes["ssh-live"].hidden, false);
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
    await h.nodes["ssh-disconnect"].onclick();
    await flush();
    assert.equal(h.nodes["ssh-live"].hidden, true);
    assert.equal(h.navGroups[".app-header"].hidden, false);
    assert.equal(h.navGroups[".route-tabs"].hidden, false);
  } finally {
    h.restore();
  }
});

test("a failed re-probe of the same target keeps the pin that was in effect", async () => {
  const h = setup();
  try {
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.ok(h.nodes["ssh-key-change-old"].textContent.includes(REVIEWED.fingerprint));
    // The re-probe itself fails (peer unreachable); the old trust must survive it.
    h.setProbeError(new Error("probe_unreachable"));
    await h.nodes["ssh-key-recheck"].onclick();
    await flush();
    assert.match(h.nodes["ssh-fingerprint"].textContent, /探测失败/);
    assert.equal(h.nodes["ssh-key-change"].hidden, true);
    // The target stays blocked on the old pin: a retry is refused before any
    // session and the setup form keeps the navigation groups visible.
    h.nodes["ssh-review"].checked = true;
    h.nodes["ssh-password"].value = "temporary-local-secret";
    await h.nodes["ssh-form"].onsubmit({ preventDefault() {} });
    await flush();
    assert.equal(h.openCalls().length, 1);
    assert.match(h.nodes["ssh-status"].textContent, /主机指纹变化尚未重新核对/);
    // The next successful re-probe of the same key releases the entries, and a
    // reviewed connection that runs into the changed key again still presents
    // the original reviewed fingerprint as the old trust.
    h.setProbeError(null);
    h.setProbed(REVIEWED);
    await h.probe();
    await h.connect();
    assert.equal(h.openCalls().length, 2);
    assert.equal(h.nodes["ssh-key-change"].hidden, false);
    assert.ok(h.nodes["ssh-key-change-old"].textContent.includes(REVIEWED.fingerprint));
    assert.ok(h.nodes["ssh-key-change-new"].textContent.includes("SHA256:presentedLocalOnly"));
    assert.equal(h.navGroups[".app-header"].hidden, true);
    assert.equal(h.navGroups[".route-tabs"].hidden, true);
  } finally {
    h.restore();
  }
});

// R18: the retained form scroll parks the generic H2 under the sticky header
// when the live terminal appears (or after the keyboard collapses). Real-WK
// measurements: H2 y=108.906 vs header band bottom y=130 on 440x956; after a
// scroll-to-top the H2 sits at y=161.906 on all three phone sizes.
const HEADING_SIZES = [
  { name: "375x667", innerHeight: 667, headingTop: -50.094 },
  { name: "390x844", innerHeight: 844, headingTop: 46.906 },
  { name: "440x956", innerHeight: 956, headingTop: 108.906 },
];

test("a natural entry into the live terminal realigns the heading below the sticky header on all three phone sizes", async () => {
  for (const size of HEADING_SIZES) {
    const h = setup({ innerHeight: size.innerHeight, ios: true, headingTop: size.headingTop });
    try {
      h.setAccept(true);
      await h.probe();
      await h.connect();
      h.runFrames();
      assert.deepEqual(h.tops, [[0, 0]], `${size.name}: exactly one scroll-to-top on entry`);
      assert.equal(h.nodes["ssh-live"].hidden, false, `${size.name}: terminal is live`);
      assert.equal(h.nodes["ssh-page-heading"].hidden, false);
    } finally {
      h.restore();
    }
  }
});

test("collapsing the keyboard realigns the heading below the sticky header", async () => {
  const h = setup({ ios: true });
  try {
    h.setAccept(true);
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-live"].hidden, false);
    h.runFrames();
    assert.deepEqual(h.tops, [], "no alignment needed when the heading is already clear");
    // The keyboard collapse leaves the old form scroll in place on iOS.
    h.nodes["ssh-page-heading"].rect = { top: 46.906, bottom: 74.906, height: 28 };
    h.nodes["ssh-hide-keyboard"].onclick();
    h.runFrames();
    assert.deepEqual(h.tops, [[0, 0]], "exactly one scroll-to-top on keyboard collapse");
  } finally {
    h.restore();
  }
});

test("an already-clear heading and later manual scrolling are never corrected", async () => {
  const h = setup({ ios: true, headingTop: 161.906 });
  try {
    h.setAccept(true);
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-live"].hidden, false);
    h.runFrames();
    assert.deepEqual(h.tops, []);
    // The user scrolls manually afterwards; the heading goes back under the
    // header band exactly like a normal document scroll.
    h.nodes["ssh-page-heading"].rect = { top: 97.906, bottom: 125.906, height: 28 };
    h.runFrames();
    await flush();
    h.runFrames();
    assert.deepEqual(h.tops, [], "no product-triggered scroll after manual scrolling");
  } finally {
    h.restore();
  }
});

test("a deferred alignment never scrolls a hidden parent view, a switched page or a refused key change", async () => {
  for (const hide of ["home-ssh", "host-home", "geometry"]) {
    const h = setup({ ios: true, headingTop: 108.906 });
    try {
      h.setAccept(true);
      await h.probe();
      await h.connect();
      assert.equal(h.nodes["ssh-live"].hidden, false, `${hide}: terminal is live before the switch`);
      if (hide === "geometry") h.nodes["ssh-page-heading"].rect = { top: 0, bottom: 0, height: 0 };
      else h.nodes[hide].hidden = true;
      h.runFrames();
      assert.deepEqual(h.tops, [], `${hide}: no scroll after the parent view changed`);
    } finally {
      h.restore();
    }
  }
  const refused = setup({ ios: true, headingTop: 108.906 });
  try {
    await refused.probe();
    await refused.connect();
    refused.runFrames();
    assert.deepEqual(refused.tops, [], "a refused key change never scrolls");
    assert.equal(refused.nodes["ssh-page-heading"].hidden, true);
    assert.equal(refused.nodes["ssh-key-change"].hidden, false);
    assert.equal(refused.nodes["ssh-review"].checked, false);
  } finally {
    refused.restore();
  }
});

test("non-iOS roots keep the old behavior: no entry alignment at all", async () => {
  const h = setup({ headingTop: 46.906 });
  try {
    h.setAccept(true);
    await h.probe();
    await h.connect();
    assert.equal(h.nodes["ssh-live"].hidden, false);
    h.runFrames();
    assert.deepEqual(h.tops, []);
    h.nodes["ssh-hide-keyboard"].onclick();
    h.runFrames();
    assert.deepEqual(h.tops, []);
  } finally {
    h.restore();
  }
});
