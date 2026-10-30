// Exact one-text correction from independent ADR-0007 review; no layout or token changes.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const s=penpotUtils.findShapeById('feb2a821-b263-8097-8008-de21b81f9e41');
const before='[示意输出 / 不可执行]\n账户 ubuntu · 设备 phone-demo\n追加一条手机专属 SSH 公钥？\n主机操作者：确认\n生成一次性响应码后退出';
const after=before.replace('生成一次性响应码后退出','生成本次请求绑定的响应码后退出');
if(!s||s.type!=='text'||s.parent?.id!=='feb2a821-b263-8097-8008-de215d8656a9'||s.characters!==before)throw Error('Unexpected S13 source text; refusing edit');
s.characters=after;
return {fileId:penpot.currentFile.id,pageId:penpot.currentPage.id,shapeId:s.id,before,after:s.characters,changedOnly:'characters'};
