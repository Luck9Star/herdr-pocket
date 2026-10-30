/** HTML password inputs remove line breaks on paste. Reconstruct only the fixed PEM envelope. */
export function normalizePrivateKeyInput(value) {
  const begin='-----BEGIN OPENSSH PRIVATE KEY-----', end='-----END OPENSSH PRIVATE KEY-----';
  const text=value.trim();
  if(!text.startsWith(begin) || !text.endsWith(end)) return value;
  const body=text.slice(begin.length,-end.length).replace(/[\t\n\r ]/g,'');
  if(!body || !/^[A-Za-z0-9+/]+={0,2}$/.test(body)) return value;
  return `${begin}\n${body.match(/.{1,64}/g).join('\n')}\n${end}\n`;
}
