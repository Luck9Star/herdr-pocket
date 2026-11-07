import { previewPairingResponse } from './pairing-view.js';

// These are local consistency/expiry gates for camera review, never proof of
// source authentication. Native pair_accept remains the final wire authority.
export function pairingCameraRequest(raw,account,now=Math.floor(Date.now()/1000)) {
  if(typeof raw!=='string' || new TextEncoder().encode(raw).length>2048)throw Error('invalid_request');
  const request=JSON.parse(raw);
  if(request?.version!==2 || request.type!=='pairing-public-key-request' ||
    !/^[0-9a-f]{32}$/.test(request.request_id) || request.account!==account ||
    !['host_key','public_key','device'].every(key=>typeof request[key]==='string' && request[key]) ||
    !Number.isSafeInteger(request.issued_at) || !Number.isSafeInteger(request.expires_at) ||
    request.issued_at<0 || request.issued_at>now || now>=request.expires_at ||
    request.expires_at-request.issued_at>600)throw Error('invalid_request');
  return request;
}
export function validatePairingCameraResponse(raw,request,fingerprint,now=Math.floor(Date.now()/1000)) {
  previewPairingResponse(raw);
  const response=JSON.parse(raw);
  if(response.version!==2 || response.type!=='pairing-binding-response' ||
    response.request_id!==request.request_id || response.account!==request.account ||
    response.host_key!==request.host_key || response.fingerprint!==fingerprint ||
    response.issued_at<0 || response.issued_at>now || now>=response.expires_at ||
    response.expires_at-response.issued_at>600 ||
    response.status==='authorized' && response.expires_at>request.expires_at)throw Error('invalid_response_binding');
}
