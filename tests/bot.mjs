import assert from 'node:assert/strict';
import {command, DEFAULTS, webhookSecret} from '../api/_bot.js';
import handler from '../api/telegram.js';
const fresh=()=>({version:1,owner:'123',chats:{'123':structuredClone(DEFAULTS)},recent:[]});
let nextUpdate=100;
const msg=(text,id=nextUpdate++,chat=123,from=123)=>({update_id:id,message:{text,chat:{id:chat,type:chat<0?'supergroup':'private'},from:{id:from}}});
assert.equal(DEFAULTS.mode,'standard'); assert.equal(DEFAULTS.limit,0);
let state=fresh();
let result=command(msg('/subscribe@news_joongyubot',1,-987),state);
assert.ok(result.payload.chats['-987']);
state=result.payload;
result=command(msg('/urgent off',2,-987),state);
assert.equal(result.payload.chats['-987'].urgent,false);
assert.equal(result.payload.chats['123'].urgent,true);
state=result.payload;
assert.equal(command(msg('/urgent off',2,-987),state).payload,undefined); // replay is idempotent
assert.equal(command(msg('/urgent off',3,-987,999),state),null);
assert.equal(command(msg('/status@other_bot'),state),null);
assert.equal(command({...msg('/subscribe',3,-987),message:{...msg('/subscribe',3,-987).message,sender_chat:{id:-987}}},state),null);
assert.equal(command(msg('/limit 999'),state).payload,undefined);
assert.equal(command(msg('/limit 0'),state).payload.chats['123'].limit,0);
assert.equal(command(msg('/quiet 22-07'),state).payload.chats['123'].quiet,'22-07');
assert.equal(command(msg('/quiet 22-22'),state).payload,undefined);
assert.equal(command(msg('/quiet 25-07'),state).payload,undefined);
result=command(msg('/watch add (a+)+$',4),state);
assert.deepEqual(result.payload.chats['123'].watch,['(a+)+$']); // literal, never a regex
state=result.payload;
assert.equal(command(msg('/watch remove (a+)+$',5),state).payload.chats['123'].watch.length,0);
state.chats['123'].watch=Array.from({length:10},(_,i)=>`word${i}`);
assert.equal(command(msg('/watch add eleventh',6),state).payload,undefined);
for(let i=0;i<3;i++) state.chats[String(-100-i)]=structuredClone(DEFAULTS);
assert.equal(command(msg('/subscribe',7,-111),state).payload,undefined);
assert.equal(command(msg('/unsubscribe',8,-987),state).payload.chats['-987'],undefined);
assert.equal(command(msg('ordinary message'),state),null);

process.env.SUPABASE_URL='https://example.supabase.co';
process.env.SUPABASE_SERVICE_ROLE_KEY='test-only';
function res(){return {code:0,body:null,status(n){this.code=n;return this},setHeader(){return this},end(x){this.body=JSON.parse(x)}}}
let calls=0;
globalThis.fetch=async()=>{calls++;throw Error('must not call')};
let r=res(); await handler({method:'POST',headers:{},body:msg('/urgent off')},r);
assert.equal(r.code,403); assert.equal(calls,0);
const headers={'x-telegram-bot-api-secret-token':webhookSecret()};
r=res();await handler({method:'POST',headers,body:msg('ordinary message')},r);
assert.equal(r.code,200); assert.equal(calls,0);
const writes=[];
globalThis.fetch=async(url,args)=>{
  if(args.method==='GET') return {ok:true,json:async()=>[{payload:fresh(),revision:7}]};
  writes.push({url,...JSON.parse(args.body)});
  return {ok:true,json:async()=>[{id:'main'}]};
};
r=res();await handler({method:'POST',headers,body:msg('/limit 4')},r);
assert.equal(r.code,200);assert.equal(r.body.method,'sendMessage');assert.equal(r.body.chat_id,123);
assert.equal(writes[0].payload.chats['123'].limit,4);assert.match(writes[0].url,/revision=eq.7/);
globalThis.fetch=async()=>({ok:false,status:503});
r=res();await handler({method:'POST',headers,body:msg('/limit 4')},r);
assert.equal(r.code,503);
console.log('Bot command authorization, limits, isolation, replay and webhook checks passed');
