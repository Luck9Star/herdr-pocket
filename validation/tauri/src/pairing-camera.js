import { previewPairingResponse } from './pairing-view.js';

// Local consistency/expiry gates assist review; native pair_accept remains the
// final wire authority. Historical requests may bind a fresh revocation receipt.
export function pairingCameraRequest(raw,account,now=Math.floor(Date.now()/1000),{allowExpired=false}={}) {
  if(typeof raw!=='string' || new TextEncoder().encode(raw).length>2048)throw Error('invalid_request');
  const request=JSON.parse(raw);
  if(request?.version!==2 || request.type!=='pairing-public-key-request' ||
    !/^[0-9a-f]{32}$/.test(request.request_id) || request.account!==account ||
    !['host_key','public_key','device'].every(key=>typeof request[key]==='string' && request[key]) ||
    !Number.isSafeInteger(request.issued_at) || !Number.isSafeInteger(request.expires_at) ||
    request.issued_at<0 || request.issued_at>now || !allowExpired && now>=request.expires_at ||
    request.expires_at<=request.issued_at || request.expires_at-request.issued_at>600)throw Error('invalid_request');
  return request;
}
export function validatePairingCameraResponse(raw,request,fingerprint,now=Math.floor(Date.now()/1000),{state='awaiting-host',revocationOnly=false}={}) {
  previewPairingResponse(raw);
  const response=JSON.parse(raw);
  if(!request || state==='revoked' || response.version!==2 || response.type!=='pairing-binding-response' ||
    response.request_id!==request.request_id || response.account!==request.account ||
    response.host_key!==request.host_key || response.fingerprint!==fingerprint ||
    response.issued_at<0 || response.issued_at>now || now>=response.expires_at ||
    response.expires_at<=response.issued_at || response.expires_at-response.issued_at>600 ||
    response.status==='authorized' && (revocationOnly || state!=='awaiting-host' || now>=request.expires_at || response.expires_at>request.expires_at))throw Error('invalid_response_binding');
  return response;
}
export function pairingRequestSummary(request,fingerprint,state,now=Math.floor(Date.now()/1000)) {
  return `原请求 ID：${request.request_id} · SSH 账号：${request.account} · 主机指纹：${request.host_key} · 设备指纹：${fingerprint} · 设备名称：${request.device} · 原请求期限：${request.expires_at} Unix 秒（${new Date(request.expires_at*1000).toISOString()}） · ${now>=request.expires_at?'原请求已过期':state==='awaiting-host'?'仍待主机操作者确认':`当前状态 ${state}`}。`;
}
