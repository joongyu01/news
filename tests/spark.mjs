import assert from 'node:assert/strict';
import handler,{relayKey,candidates,validateReport} from '../api/spark.js';
process.env.SESSION_SECRET='test-session';
const now=Date.now(), date=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul'}).format(new Date());
const published=new Date(now+9*3600000).toISOString().slice(0,16).replace('T',' ');
const a={id:'a',title:'석유관리원 품질 검사',url:'https://news.test/a',published,language:'ko'};
const state={pool:{updated_at:new Date(now-3*3600000).toISOString(),articles:[a]}};
assert.equal(candidates(state,{global:{exclude:[]}},now).length,1);
assert.equal(candidates(state,{global:{exclude:['품질']}},now).length,0);
assert.throws(()=>candidates({...state,pool:{...state.pool,updated_at:'bad'}},{},now));
const body={date,issues:[{title:'품질 검사',summary:'검사 보도',change:'전일 비교 근거 부족',impact:'품질 관리 관련',article_ids:['a']}]};
assert.equal(validateReport(body,[a]).length,1);
assert.throws(()=>validateReport({...body,date:'2000-01-01'},[a]));
assert.throws(()=>validateReport(body,[]));
assert.throws(()=>validateReport({...body,issues:[...body.issues,...body.issues]},[a]));
let writes=0;
let payload={owner:'1',chats:{'1':{}},global:{exclude:[]}};
globalThis.fetch=async(url,opts={})=>({ok:true,json:async()=> {
 if(String(url).includes('news_alert_state')) return [{payload:state}];
 if(String(url).includes('news_bot_settings')) {
   if(opts.method==='PATCH'){writes++;payload=JSON.parse(opts.body).payload;return [{payload}];}
   return [{payload,revision:1}];
 }
 return [];
}});
function res(){return {code:0,body:null,status(n){this.code=n;return this},setHeader(){return this},end(x){this.body=JSON.parse(x)}}}
process.env.SUPABASE_URL='https://example.test';process.env.SUPABASE_SERVICE_ROLE_KEY='fake';
const headers={authorization:'Bearer '+relayKey()};
let r=res();await handler({method:'POST',headers:{},body},r);assert.equal(r.code,403);
r=res();await handler({method:'POST',headers,body:{...body,test:true}},r);assert.equal(r.code,200);assert.equal(writes,0);
r=res();await handler({method:'POST',headers,body},r);assert.equal(r.code,200);assert.equal(writes,1);
r=res();await handler({method:'POST',headers,body},r);assert.equal(r.code,200);assert.equal(writes,1);
r=res();await handler({method:'POST',headers,body:{date,issues:body.issues.map(i=>({...i,article_ids:['fake']}))}},r);assert.equal(r.code,400);
console.log('Spark authorization, freshness, evidence, dry-run and duplicate guards passed');
