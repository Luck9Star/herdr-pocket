import test from 'node:test';
import assert from 'node:assert/strict';
import {pairingCameraRequest,validatePairingCameraResponse} from '../src/pairing-camera.js';
const request={version:2,type:'pairing-public-key-request',request_id:'a'.repeat(32),account:'demo',host_key:'SHA256:host',public_key:'public-key-from-native',device:'Phone',issued_at:100,expires_at:700};
const response={version:2,type:'pairing-binding-response',request_id:request.request_id,account:request.account,host_key:request.host_key,fingerprint:'SHA256:device',issued_at:101,expires_at:600,status:'authorized',authorization_added:true};
test('request must still be the locally-created current account and within its native public window',()=>{
 assert.deepEqual(pairingCameraRequest(JSON.stringify(request),'demo',101),request);
 for(const now of [99,700,701])assert.throws(()=>pairingCameraRequest(JSON.stringify(request),'demo',now));
 assert.throws(()=>pairingCameraRequest(JSON.stringify(request),'other',101));
 for(const change of [{version:1},{type:'herdr-connection-profile'},{expires_at:701},{issued_at:true},{expires_at:true}])assert.throws(()=>pairingCameraRequest(JSON.stringify({...request,...change}),'demo',101));
});
test('camera bytes must match the request and device before an unauthenticated review can be restored',()=>{
 validatePairingCameraResponse(JSON.stringify(response),request,'SHA256:device',102);
 for(const change of [{request_id:'b'.repeat(32)},{host_key:'foreign'},{account:'other'},{fingerprint:'foreign'},{version:1},{type:'herdr-connection-profile'},{issued_at:103},{expires_at:102},{expires_at:701}])assert.throws(()=>validatePairingCameraResponse(JSON.stringify({...response,...change}),request,'SHA256:device',102));
});
