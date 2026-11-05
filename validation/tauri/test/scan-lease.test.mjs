import test from 'node:test';
import assert from 'node:assert/strict';
import { scanCurrent } from '../src/scan-lease.js';
test('late camera result cannot replace a new request or hidden view',()=>{
 const start={revision:2,request:'public-request'};
 const current={...start,showingRemote:true,hidden:false,pending:false};
 assert.equal(scanCurrent(start,current),true);
 for(const changed of [{revision:3},{request:'new-request'},{showingRemote:false},{hidden:true},{pending:true}]) assert.equal(scanCurrent(start,{...current,...changed}),false);
});
