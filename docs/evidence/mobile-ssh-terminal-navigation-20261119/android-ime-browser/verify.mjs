import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const read = (name) => readFileSync(new URL(name, import.meta.url));
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const index = JSON.parse(read('index.json'));
const expectedOpen = [
  [320, 640, 'unchanged', 640, 238, 402],
  [390, 844, 'unchanged', 844, 291, 553],
  [393, 851, 'unchanged', 851, 300, 551],
  [393, 851, 'visual', 551, 300, 551],
  [393, 851, 'native', 551, 0, 551],
];

for (const phase of ['before', 'after']) {
  const evidence = index.phaseEvidence[phase];
  const recorded = read(evidence.path);
  assert.equal(sha256(recorded), evidence.originalSha256);
  const data = JSON.parse(recorded);
  assert.equal(data.phase, phase);
  assert.equal(data.real, true);
  assert.equal(data.rows.length, evidence.dataRows);
  const baseline = phase === 'before';
  const cases = baseline ? expectedOpen.slice(0, 3) : expectedOpen;
  const opened = data.rows.filter((row) => row.phase === 'opened');
  assert.equal(opened.length, cases.length);
  for (const [i, [width, height, mode, visual, inset, effective]] of cases.entries()) {
    const row = opened[i];
    const { controls } = row;
    assert.deepEqual(row.size, [width, height]);
    assert.equal(row.mode, mode);
    assert.equal(row.visual, visual);
    assert.equal(row.ime.visible, true);
    assert.equal(row.ime.overlap, inset);
    assert.equal(row.viewportHeight, baseline ? '' : effective + 'px');
    assert.equal(row.viewportInset, baseline ? '' : inset + 'px');
    assert.equal(controls.routes.visible, baseline);
    assert.equal(controls.show.hit, baseline);
    assert.equal(controls.hide.hit, !baseline);
    if (!baseline) {
      for (const name of ['title', 'target', 'hide', 'disconnect']) {
        const { rect: [, y, , h], hit } = controls[name];
        assert(hit && y + h <= effective, name);
      }
    }
  }
  const sessions = data.rows.filter((row) => row.peer);
  assert.equal(sessions.length, cases.length);
  for (const { peer } of sessions) {
    assert.deepEqual(peer, { connection: 2, auth: 1, pty: 1, shell: 1, inputBytes: 0, closed: true });
  }
  const recovered = data.rows.filter((row) => ['hidden', 'system-back'].includes(row.phase));
  assert.equal(recovered.length, baseline ? 0 : cases.length * 2);
  for (const row of recovered) {
    assert.equal(row.ime.visible, false);
    assert.equal(row.viewportInset, '');
    assert.equal(row.controls.routes.visible, true);
  }
}

for (const image of index.screens) {
  const png = read(image.path);
  assert.equal(sha256(png), image.archiveSha256);
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], image.imagePixels);
}
console.log('IME evidence verified (8 cases and 8 archived PNGs)');
