const fields = ['version','type','host','port','username','provider','session','socketPath','herdrPath','expectedHostKey'];
const encoder = new TextEncoder();
const invalid = () => { throw Error('invalid_connection_profile'); };
const scalarString = value => typeof value === 'string' && !/[\u0000-\u001f\u007f-\u009f]/u.test(value) && !/[\ud800-\udfff]/u.test(value);

// Only primitive fields exist in this wire format. Decode each JSON key before
// duplicate detection, so escaped spellings cannot bypass the unique-key rule.
function parseObject(raw) {
  let offset=0, closed=false; const result=Object.create(null), seen=new Set();
  const space=()=>{while(/[\x20\t\r\n]/.test(raw[offset] ?? '\0'))offset++;};
  function string() {
    const start=offset++;
    while(offset<raw.length) {
      if(raw[offset]==='\\'){offset+=2;continue;}
      if(raw[offset++]==='"')return JSON.parse(raw.slice(start,offset));
    }
    invalid();
  }
  space();if(raw[offset++]!=='{')invalid();space();
  if(raw[offset]==='}')invalid();
  while(offset<raw.length) {
    if(raw[offset]!=='"')invalid();const key=string();space();
    if(seen.has(key) || !fields.includes(key) || raw[offset++]!==':')invalid();
    seen.add(key);space();
    let value;
    if(raw[offset]==='"')value=string();
    else {const match=raw.slice(offset).match(/^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)/);if(!match)invalid();if(/[.eE]/.test(match[0]))invalid();offset+=match[0].length;value=JSON.parse(match[0]);}
    result[key]=value;space();const separator=raw[offset++];
    if(separator==='}'){closed=true;break;}
    if(separator!==',')invalid();space();
  }
  space();if(offset!==raw.length || seen.size!==fields.length || !closed)invalid();
  return result;
}
function ipv6(host) {
  if(!host.includes(':') || !/^[0-9a-fA-F:.]+$/.test(host))return false;
  let normalized=host;
  if(host.includes('.')) {
    const split=host.lastIndexOf(':'), tail=host.slice(split+1), parts=tail.split('.');
    if(parts.length!==4 || parts.some(x=>! /^(?:0|[1-9][0-9]{0,2})$/.test(x) || Number(x)>255))return false;
    normalized=host.slice(0,split)+':0:0';
  }
  if(normalized.includes('::')) {
    if(normalized.indexOf('::')!==normalized.lastIndexOf('::'))return false;
    const halves=normalized.split('::'), groups=halves.flatMap(x=>x?x.split(':'):[]);
    return groups.length<8 && groups.every(x=>/^[0-9a-fA-F]{1,4}$/.test(x));
  }
  const groups=normalized.split(':');return groups.length===8 && groups.every(x=>/^[0-9a-fA-F]{1,4}$/.test(x));
}
function validHost(host) {
  return typeof host==='string' && host.length>=1 && host.length<=253 &&
    (host.includes(':') ? ipv6(host) : host.split('.').every(label=>/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label)));
}
function path(value) {
  return scalarString(value) && encoder.encode(value).length<=1024 && value.startsWith('/') && value.slice(1).split('/').every(part=>part && part!=='.' && part!=='..');
}
export function publicKeyBlob(key) {
  if(typeof key!=='string' || !/^ssh-ed25519 [A-Za-z0-9+/]+={0,2}$/.test(key))invalid();
  const encoded=key.slice(12);let binary;
  try {binary=atob(encoded);}catch {invalid();}
  if(btoa(binary)!==encoded || binary.length!==51)invalid();
  const bytes=Uint8Array.from(binary,char=>char.charCodeAt(0));
  if(bytes[0]!==0 || bytes[1]!==0 || bytes[2]!==0 || bytes[3]!==11 ||
     String.fromCharCode(...bytes.slice(4,15))!=='ssh-ed25519' ||
     bytes[15]!==0 || bytes[16]!==0 || bytes[17]!==0 || bytes[18]!==32)invalid();
  return bytes;
}
export function parseConnectionProfile(raw) {
  if(typeof raw!=='string' || encoder.encode(raw).length>2048)invalid();
  const profile=parseObject(raw);
  if(profile.version!==1 || profile.type!=='herdr-connection-profile' || !validHost(profile.host) ||
    typeof profile.port!=='number' || !Number.isInteger(profile.port) || profile.port<1 || profile.port>65535 ||
    typeof profile.username!=='string' || !/^[a-z_][a-z0-9_-]{0,31}$/.test(profile.username) ||
    !['direct','tailscale','easytier','zerotier'].includes(profile.provider) ||
    typeof profile.session!=='string' || !/^[A-Za-z0-9_-]{1,64}$/.test(profile.session) || profile.session==='default' ||
    !path(profile.socketPath) || !path(profile.herdrPath))invalid();
  const suffix=`/herdr/sessions/${profile.session}/herdr.sock`;
  if(!profile.socketPath.endsWith(suffix) || profile.socketPath.length<=suffix.length)invalid();
  publicKeyBlob(profile.expectedHostKey);
  return Object.freeze({...profile});
}
export async function previewConnectionProfile(raw, subtle=globalThis.crypto.subtle) {
  const profile=parseConnectionProfile(raw), digest=await subtle.digest('SHA-256',publicKeyBlob(profile.expectedHostKey));
  const fingerprint='SHA256:'+btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/=+$/,'');
  const text=fields.map(field=>`${field}: ${profile[field]}`).join('\n')+`\n主机公钥指纹（本地计算）: ${fingerprint}`;
  return Object.freeze({profile,fingerprint,text});
}
