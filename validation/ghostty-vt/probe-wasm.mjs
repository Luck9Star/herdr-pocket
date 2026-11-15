// Node >=22, official 1.0.1 C ABI. No npm dependencies or transport forwarding.
import {createHash} from 'node:crypto';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';

const expected = 'e226900d2126faab515668e5400b69fc78ba3d99aaf9525b325f79707b29bf01';
const url = 'https://release.files.ghostty.org/libghostty-vt/1.0.1/ghostty-vt-1.0.1-small.wasm';
const requireReset = process.argv.includes('--require-reset');
const args = process.argv.slice(2).filter(arg => arg !== '--require-reset');
if (args.length > 2 || args.some(arg => arg.startsWith('--'))) throw Error('usage: node probe-wasm.mjs [WASM_PATH] [OUTPUT_JSON] [--require-reset]');
const wasmPath = resolve(args[0] ?? join(tmpdir(), 'herdr-ghostty-vt-1.0.1', 'ghostty-vt-1.0.1-small.wasm'));
const output = resolve(args[1] ?? join(dirname(wasmPath), 'wasm-result.json'));
let bytes;
let downloaded = false;
try { bytes = await readFile(wasmPath); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  const response = await fetch(url, {headers: {'User-Agent': 'herdr-pocket-prototype-validation'}});
  if (!response.ok) throw Error(`official WASM download HTTP ${response.status}`);
  bytes = Buffer.from(await response.arrayBuffer());
  downloaded = true;
}
const hash = createHash('sha256').update(bytes).digest('hex');
if (hash !== expected) throw Error('official WASM SHA256 mismatch');
if (downloaded) {
  await mkdir(dirname(wasmPath), {recursive: true});
  await writeFile(wasmPath, bytes);
}
const module = await WebAssembly.compile(bytes);
if (WebAssembly.Module.imports(module).length) throw Error('expected self-contained official WASM without host imports');
const e = (await WebAssembly.instantiate(module)).exports;
const encoder = new TextEncoder(), decoder = new TextDecoder();
const view = () => new DataView(e.memory.buffer);
const memory = () => new Uint8Array(e.memory.buffer);
const api = result => { if (result !== 0) throw Error(`C API returned ${result}`); };
const alloc = size => { const p = e.ghostty_wasm_alloc(size); if (!p) throw Error('WASM allocation failed'); return p; };
const free = (p, size) => e.ghostty_wasm_free(p, size);
function opaque(create) {
  const slot = e.ghostty_wasm_alloc_opaque();
  if (!slot) throw Error('WASM opaque slot allocation failed');
  try { api(create(slot)); return view().getUint32(slot, true); }
  finally { e.ghostty_wasm_free_opaque(slot); }
}
const terminal = (cols = 80, rows = 24) => opaque(slot => e.ghostty_terminal_new(0, slot, cols, rows));
function write(t, value) {
  const b = typeof value === 'string' ? encoder.encode(value) : value;
  if (!b.length) return;
  const p = alloc(b.length);
  try { memory().set(b, p); e.ghostty_terminal_vt_write(t, p, b.length); }
  finally { free(p, b.length); }
}
function text(t, unwrap = false) {
  const f = opaque(slot => e.ghostty_formatter_terminal_new(0, slot, t));
  const flag = alloc(1), out = alloc(8192), count = alloc(4);
  try {
    memory()[flag] = Number(unwrap);
    api(e.ghostty_formatter_set(f, 2, flag)); // GHOSTTY_FORMATTER_OPT_UNWRAP
    api(e.ghostty_formatter_format_buf(f, out, 8192, count));
    return decoder.decode(memory().slice(out, out + view().getUint32(count, true)));
  } finally { free(flag, 1); free(out, 8192); free(count, 4); e.ghostty_formatter_free(f); }
}
function u16(t, key) {
  const p = alloc(2);
  try { api(e.ghostty_terminal_get(t, key, p)); return view().getUint16(p, true); }
  finally { free(p, 2); }
}
function withTerminal(fn, cols = 80, rows = 24) {
  const t = terminal(cols, rows);
  try { return fn(t); } finally { e.ghostty_terminal_free(t); }
}
const checks = [];
const observations = [];
const check = (name, passed, actual) => checks.push({name, passed: !!passed, ...(actual === undefined ? {} : {actual})});
const observe = (name, supported, actual) => observations.push({name, supported: !!supported, actual});
const sample = 'a中😀é!', sampleBytes = encoder.encode(sample);
let allBoundaries = true, allWidths = true;
for (let split = 0; split <= sampleBytes.length; split++) withTerminal(t => {
  write(t, sampleBytes.slice(0, split)); write(t, sampleBytes.slice(split));
  allBoundaries &&= text(t) === sample;
  allWidths &&= u16(t, 3) === 7; // GHOSTTY_TERMINAL_DATA_CURSOR_X
});
check('utf8_every_two_chunk_boundary', allBoundaries);
check('cjk_emoji_cell_width_cursor_7', allWidths);
withTerminal(t => {
  for (const b of sampleBytes) write(t, Uint8Array.of(b));
  const actual = text(t); check('utf8_one_byte_chunks', actual === sample, actual);
});
withTerminal(t => {
  write(t, 'MAIN\x1b[?1049h\x1b[HALT');
  check('alternate_screen_enter', text(t) === 'ALT', text(t));
  write(t, '\x1b[?1049l');
  check('alternate_screen_restore', text(t) === 'MAIN', text(t));
});
withTerminal(t => {
  write(t, 'abcdefg'); api(e.ghostty_terminal_resize(t, 4, 4, 8, 16));
  const actual = text(t, true);
  check('local_resize_reflow_preserves_text', u16(t, 1) === 4 && u16(t, 2) === 4 && actual === 'abcdefg', actual);
}, 6, 3);
const half = Uint8Array.of(0xf0, 0x9f), tail = Uint8Array.of(0x98, 0x80, 0x5a);
withTerminal(t => {
  write(t, half); write(t, tail);
  check('same_session_partial_utf8_continues', text(t) === '😀Z', text(t));
});
withTerminal(t => {
  write(t, half); e.ghostty_terminal_reset(t); write(t, tail);
  const actual = text(t); observe('reset_isolates_partial_utf8', !actual.includes('😀') && actual.includes('Z'), actual);
});
withTerminal(t => {
  write(t, '\x1b[31'); e.ghostty_terminal_reset(t); write(t, 'mZ');
  observe('reset_isolates_partial_csi', text(t) === 'mZ', text(t));
});
withTerminal(t => write(t, half));
withTerminal(t => {
  write(t, tail);
  // The two U+FFFD characters are valid handling of this new stream's two
  // orphan continuation bytes, not leakage from the retired session.
  check('new_instance_isolates_partial_utf8', text(t) === '\uFFFD\uFFFDZ', text(t));
});
withTerminal(t => write(t, '\x1b[31'));
withTerminal(t => { write(t, 'mZ'); check('new_instance_isolates_partial_csi', text(t) === 'mZ', text(t)); });
const versionPtr = e.ghostty_version();
const versionEnd = memory().indexOf(0, versionPtr);
const libraryVersion = decoder.decode(memory().slice(versionPtr, versionEnd));
if (libraryVersion !== '1.0.1') throw Error('runtime library version mismatch');
const failureCount = checks.filter(c => !c.passed).length;
const rejected = observations.filter(item => !item.supported).map(item => item.name);
const accepted = failureCount === 0 && !(requireReset && rejected.length);
const report = {
  libraryVersion, transportWrites: 0, checks, observations, checkCount: checks.length,
  observationCount: observations.length, failureCount,
  source: {url, sha256: hash, tag: 'vt-1.0.1', tagObject: 'e9dc690b08bde7e2ec9c7aff8a18a85c9cade46d',
    releaseCommit: '108cacb17ed8990840cd14abfce43d8ed8503ca1'},
  execution: {kind: 'local-Node-WASM-C-ABI', node: process.version, os: process.platform, architecture: process.arch,
    probeSourceSha256: createHash('sha256').update(await readFile(new URL(import.meta.url))).digest('hex')},
  scope: {wasmHostImports: 0, remoteTransportOpened: false, rendererOrDeviceValidated: false,
    callbacksOrKeyEncodingValidatedHere: false},
  acceptancePolicy: {sessionIsolation: 'free old terminal and create a new instance', requireResetIsolation: requireReset,
    rejectedResetHypotheses: rejected},
};
await mkdir(dirname(output), {recursive: true});
await writeFile(output, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({output, libraryVersion, checks: checks.length,
  failed: checks.filter(c => !c.passed).map(c => c.name), rejectedResetHypotheses: rejected, accepted}));
process.exitCode = accepted ? 0 : 1;
