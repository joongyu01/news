import assert from 'node:assert/strict';
import handler,{relayKey} from '../api/spark.js';
process.env.SESSION_SECRET='test-session';
process.env.SUPABASE_URL='https://example.supabase.co';
process.env.SUPABASE_SERVICE_ROLE_KEY='test-only';
function res(){return {code:0,body:null,status(n){this.code=n;return this},setHeader(){return this},end(x){this.body=JSON.parse(x)}}}
let stored={payload:{owner:'123',chats:{'123':{urgent:true}},recent:[]},revision:1},calls=0,conflict=false;
globalThis.fetch=async(url,args)=>{
 calls++;
 if(args.method==='GET')return {ok:true,json:async()=>[structuredClone(stored)]};
 if(conflict){conflict=false;stored.payload.chats['123'].urgent=false;stored.revision++;return {ok:true,json:async()=>[]};}
 const expected=Number(new URL(url).searchParams.get('revision').slice(3));
 assert.equal(expected,stored.revision);
 stored={...JSON.parse(args.body)};return {ok:true,json:async()=>[{id:'main'}]};
};
let r=res();await handler({method:'POST',headers:{},body:{text:'valid report text'}},r);
assert.equal(r.code,403);assert.equal(calls,0);
r=res();await handler({method:'GET',headers:{},query:{setup:'1'}},r);assert.equal(r.code,401);
const headers={authorization:'Bearer '+relayKey()};
const req=text=>({method:'POST',headers,body:{text}});
conflict=true;r=res();await handler(req('First public news report'),r);
assert.equal(r.code,200);assert.equal(stored.payload.spark_queue.length,1);assert.equal(stored.payload.chats['123'].urgent,false);
const id=r.body.id;
r=res();await handler(req('First public news report'),r);assert.equal(r.body.duplicate,true);assert.equal(stored.payload.spark_queue.length,1);
r=res();await handler(req('x'.repeat(3001)),r);assert.equal(r.code,400);
stored.payload.spark_queue=[];stored.payload.spark_recent=[{id,sent_at:new Date().toISOString()}];
r=res();await handler(req('First public news report'),r);assert.equal(r.body.status,'delivered');
stored.payload.spark_queue=Array.from({length:3},(_,i)=>({id:String(i)}));
r=res();await handler(req('Another public news report'),r);assert.equal(r.code,429);
r=res();await handler({method:'GET',headers},r);assert.equal(r.body.pending,3);assert.equal(r.body.key,undefined);assert.equal(r.body.owner,undefined);
console.log('Spark relay authentication, bounds, replay and concurrent settings checks passed');
