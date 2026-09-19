import assert from 'node:assert/strict';
import {usageText} from '../api/_usage.js';
import {formatLogs} from '../api/_logs.js';
import {command, DEFAULTS, webhookSecret} from '../api/_bot.js';
import handler from '../api/telegram.js';

const now=Date.parse('2026-09-19T12:00:00Z');
const snapshot={repository:'joongyu01/news', checked_at:'2026-09-19T11:55:00Z',visibility:'public',standard_runners:true,
  cache_bytes:2**30,rate:{limit:1000,remaining:994,reset:now/1000+300},runs:{collect:[
    {id:12,status:'completed',conclusion:'failure',event:'workflow_dispatch',run_started_at:'2026-09-19T11:50:00Z',updated_at:'2026-09-19T11:51:00Z'}]}};
assert.match(usageText(snapshot,now),/994 \/ 1,000회/);
assert.match(usageText(snapshot,now),/차감 없음/);
assert.match(usageText(snapshot,now),/9.000 GiB/);
assert.doesNotMatch(usageText({...snapshot,visibility:'private'},now),/차감 없음/);
assert.match(usageText({...snapshot,rate:null},now),/조회 실패/);
assert.match(usageText({...snapshot,cache_bytes:null},now),/현재 용량: 조회 실패/);
assert.match(usageText(snapshot,now+3600000),/최신 수치가 아닙니다/);
assert.match(usageText(snapshot,now+3600000),/초기화 시각이 지나/);
assert.match(usageText(null,now),/아직 조회하지 못/);
const draft={date:'2026-09-19',generated_at:'2026-09-19 06:48',articles:[{sector:'energy',duplicates:[{},{}]}],
  sectors:[{id:'energy',title:'에너지'}],collection_stats:{raw:100,fresh:50,classified:3}};
const alert={last_checked_at:'2026-09-19T11:50:00Z',last_collected:12,last_sent:0,last_candidates:0,last_failures:0,last_completed_at:'2026-09-19T11:51:00Z'};
let text=formatLogs(snapshot,draft,alert,'',now);
assert.match(text,/저장 기사: 3건 \(대표 1 · 중복 2\)/);
assert.match(text,/원시 수집 100 → 최근 기사 50 → 분류 통과 3건/);
assert.match(text,/수집 12건 · 발송 0건/);
assert.match(text,/❌ 실패/);
assert.match(text,/https:\/\/github.com\/joongyu01\/news\/actions\/runs\/12/);
assert.doesNotMatch(formatLogs(snapshot,draft,alert,'dispatch',now),/저장 기사:/);
assert.match(formatLogs(null,null,null,'',now),/기록 조회 불가/);
assert.ok(text.length<4096);

const stored={version:1,owner:'123',chats:{'123':structuredClone(DEFAULTS)},recent:[],github_usage:snapshot};
let id=10;
const msg=(text,from=123,chat=123)=>({update_id:id++,message:{text,from:{id:from},chat:{id:chat,type:chat<0?'group':'private'}}});
for (const c of ['/usage','usage','Usage','/usage@news_joongyubot']) {
  assert.match(command(msg(c),stored).text,/GitHub 뉴스 봇 사용량/);
  assert.equal(command(msg(c),stored).payload,undefined);
}
assert.equal(command(msg('/logs 수집'),stored).logs,'collect');
assert.equal(command(msg('logs'),stored).logs,'');
assert.equal(command(msg('/logs unknown'),stored).logs,undefined);
for (const c of ['/usage','/logs','usage','logs']) {
  assert.equal(command(msg(c,999,-1),stored),null);
  assert.match(command(msg(c,999),stored).text,/소유자 전용/);
  assert.match(command(msg(c,123,-1),stored).text,/개인 대화/);
}
assert.equal(command(msg('/logs@other_bot'),stored),null);
assert.equal(command({...msg('/logs'),message:{...msg('/logs').message,forward_origin:{type:'user'}}},stored),null);
const unsubscribed={...stored,chats:{}};
assert.match(command(msg('/usage'),unsubscribed).text,/GitHub 뉴스 봇 사용량/);

process.env.SUPABASE_URL='https://example.supabase.co';process.env.SUPABASE_SERVICE_ROLE_KEY='test-only';
const headers={'x-telegram-bot-api-secret-token':webhookSecret()};
const res=()=>({code:0,body:null,status(n){this.code=n;return this},setHeader(){return this},end(x){this.body=JSON.parse(x)}});
const calls=[];
globalThis.fetch=async(url,opts)=>{
  calls.push(url);assert.ok(!opts.method || opts.method==='GET');
  if (url.includes('news_bot_settings')) return {ok:true,json:async()=>[{payload:stored,revision:1}]};
  if (url.includes('news_drafts')) return {ok:true,json:async()=>[{payload:draft}]};
  return {ok:true,json:async()=>[alert]};
};
let response=res();await handler({method:'POST',headers,body:msg('usage')},response);
assert.equal(response.code,200);assert.equal(calls.length,1);
assert.match(response.body.text,/API 호출 한도/);
response=res();await handler({method:'POST',headers,body:msg('/logs')},response);
assert.equal(response.code,200);assert.match(response.body.text,/저장 기사: 3건/);
const before=calls.length;
response=res();await handler({method:'POST',headers,body:msg('/logs',123,-1)},response);
assert.equal(calls.length,before+1); // no operational reads for group requests
globalThis.fetch=async(url)=>url.includes('news_bot_settings')
  ? {ok:true,json:async()=>[{payload:stored,revision:1}]} : {ok:false,status:503};
response=res();await handler({method:'POST',headers,body:msg('/logs')},response);
assert.equal(response.code,200);assert.match(response.body.text,/조회 실패/);
console.log('Usage/log commands: authorization, stale/error reporting, counts, read-only webhook passed');
