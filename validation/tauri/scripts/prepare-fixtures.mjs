import { cp, mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const shared = new URL('../../shared/', import.meta.url);
for (const line of (await readFile(new URL('SHA256SUMS', shared), 'utf8')).trim().split('\n')) {
  const [expected, name] = line.split('  ');
  const actual = createHash('sha256').update(await readFile(new URL(name, shared))).digest('hex');
  if (actual !== expected) throw new Error(`Shared fixture hash mismatch: ${name}`);
}
await mkdir(new URL('../public/', import.meta.url), { recursive: true });
await cp(shared, new URL('../public/shared/', import.meta.url), { recursive: true });
console.log('Shared fixture and font hashes verified.');
