import { cp, mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const shared = new URL('../../shared/', import.meta.url);
for (const line of (await readFile(new URL('SHA256SUMS', shared), 'utf8')).trim().split('\n')) {
  const [expected, name] = line.split('  ');
  const actual = createHash('sha256').update(await readFile(new URL(name, shared))).digest('hex');
  if (actual !== expected) throw new Error(`Shared fixture hash mismatch: ${name}`);
}
await mkdir(new URL('../public/', import.meta.url), { recursive: true });
await cp(shared, new URL('../public/shared/', import.meta.url), {
  recursive: true,
  filter: source => !/(^|[\\/])__pycache__([\\/]|$)/.test(source) && !source.endsWith('.pyc'),
});
const notices = new URL('../public/rust-notices/', import.meta.url);
await mkdir(notices, { recursive: true });
for (const name of ['RUSSH-NOTICE.md', 'russh-0.65.0-source.json', 'russh-0.65.0-local-close.patch']) {
  await cp(new URL(`../../vendor/${name}`, import.meta.url), new URL(name, notices));
}
await cp(new URL('../../vendor/russh-0.65.0-LICENSE-APACHE', import.meta.url), new URL('russh-LICENSE', notices));
console.log('Shared fixture and font hashes verified.');
