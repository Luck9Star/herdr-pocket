import test from 'node:test';
import assert from 'node:assert/strict';
import { buildImportChoices, previewIsCurrent, validExportPassword, exportIfCurrent } from '../src/config-transfer-ui.js';
const entries = [{ index: 0, conflicts: [{ id: 'a' }, { id: 'b' }] }, { index: 1, conflicts: [] }];
test('requires an explicit choice per entry and replaces every conflict', () => {
  assert.throws(() => buildImportChoices(entries, new Map([[0, 'replace']])));
  assert.deepEqual(buildImportChoices(entries, new Map([[0, 'replace'], [1, 'add']])), [
    { index: 0, action: 'replace', replaceIds: ['a', 'b'] }, { index: 1, action: 'add', replaceIds: [] }
  ]);
  assert.throws(() => buildImportChoices(entries, new Map([[0, 'keep'], [1, 'replace']])));
});
test('rejects replacing the same local record twice', () => {
  assert.throws(() => buildImportChoices([{ index: 0, conflicts: [{ id: 'a' }] }, { index: 1, conflicts: [{ id: 'a' }] }], new Map([[0, 'replace'], [1, 'replace']])));
});
test('a late picker or preview result cannot survive source change or leaving', () => {
  assert.equal(previewIsCurrent(4, 4), true);
  assert.equal(previewIsCurrent(4, 5), false);
});
test('export password counts Unicode scalars and UTF-8 bytes without trimming', () => {
  assert.equal(validExportPassword('😀'.repeat(12)), true);
  assert.equal(validExportPassword(' '.repeat(12)), true);
  assert.equal(validExportPassword('😀'.repeat(11)), false);
  assert.equal(validExportPassword('a'.repeat(1024)), true);
  assert.equal(validExportPassword('a'.repeat(1025)), false);
  assert.equal(validExportPassword('😀'.repeat(257)), false);
  assert.equal(validExportPassword('a'.repeat(12) + '\ud800'), false);
});
test('late export cannot open picker or start download after navigation', async () => {
  for (const departure of ['epoch', 'panel', 'background']) {
    let resolve; const encryption = new Promise(r => { resolve = r; });
    let epoch = 7, panelVisible = true, foreground = true, saves = 0;
    const pending = exportIfCurrent(() => encryption, () => epoch === 7 && panelVisible && foreground, () => { saves++; });
    if (departure === 'epoch') epoch++;
    if (departure === 'panel') panelVisible = false;
    if (departure === 'background') foreground = false;
    resolve([1, 2, 3]);
    assert.equal(await pending, false);
    assert.equal(saves, 0);
  }
  let saved;
  assert.equal(await exportIfCurrent(async () => [1, 2], () => true, bytes => { saved = bytes; }), true);
  assert.deepEqual(saved, [1, 2]);
});
