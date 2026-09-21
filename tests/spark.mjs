import assert from 'node:assert/strict';
import handler,{relayKey} from '../api/spark.js';
process.env.SESSION_SECRET='test-session';
let calls=0;
globalThis.fetch=async()=>{calls++;throw Error('Retired POST must never access DB');};
function res(){return {code:0,body:null,status(n){this.code=n;return this},setHeader(){return this},end(x){this.body=JSON.parse(x)}}}
let r=res();await handler({method:'POST',headers:{},body:{text:'report'}},r);
assert.equal(r.code,403);
r=res();await handler({method:'GET',headers:{},query:{setup:'1'}},r);
assert.equal(r.code,401);
r=res();await handler({method:'POST',headers:{authorization:'Bearer '+relayKey()},body:{text:'report'}},r);
assert.equal(r.code,410);
assert.equal(calls,0);
console.log('Retired Spark submission rejects reports without touching the queue');
