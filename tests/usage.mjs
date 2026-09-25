import assert from 'node:assert/strict';
import {usageText} from '../api/_usage.js';
import {formatLogs} from '../api/_logs.js';
import {command, DEFAULTS, webhookSecret} from '../api/_bot.js';
import handler from '../api/telegram.js';
import {formatAiUsage,formatAiStatus} from '../api/_ai_usage.js';

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
for (const c of ['/usage','usage','Usage','/usage@news_joongyubot','/useage','useage','/useage@news_joongyubot']) {
  assert.match(command(msg(c),stored).text,/GitHub 뉴스 봇 사용량/);
  assert.equal(command(msg(c),stored).payload,undefined);
}
assert.equal(command(msg('/logs 수집'),stored).logs,'collect');
assert.equal(command(msg('logs'),stored).logs,'');
assert.equal(command(msg('/logs unknown'),stored).logs,undefined);
for (const c of ['/usage','/useage','/logs','usage','logs']) {
  assert.match(command(msg(c,999,-1),stored).text,/개인 대화/);
  assert.ok(command(msg(c,999),stored));
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
assert.equal(response.code,200);assert.equal(calls.length,2);
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

const ai={ai:{date:'2026-09-19',requests:3,usage:{totalTokenCount:1936}},
  groq_ai:{date:'2026-09-19',requests:10,usage:{total_tokens:20000},recent:[
    {at:now/1000-3600,tokens:25000},{at:now/1000-86401,tokens:90000}]}};
text=formatAiUsage(ai,now);
assert.match(text,/남은 요청: 37회/); assert.match(text,/남은 요청: 30회/);
assert.match(text,/남은 토큰 예산: 175,000/); assert.match(text,/167,200토큰 · 29회/);
assert.match(text,/1,936/); assert.match(text,/남은 토큰: 미확인/);
assert.match(formatAiUsage(ai,now+86400000),/남은 토큰 예산: 200,000/);
assert.match(formatAiUsage(ai,now+86400000),/남은 요청: 40회/);
assert.match(formatAiUsage(null,now),/사용 기록 없음/);
assert.match(formatAiUsage({groq_ai:{date:'2026-09-19',requests:45}},now),/남은 요청: 0회/);
assert.match(formatAiUsage({groq_ai:{...ai.groq_ai,recent:[{at:now/1000,tokens:-1}]}},now),/기록 부족/);
assert.ok((text+'\n\n'+usageText(snapshot,now)).length<4096);
response=res(); await handler({method:'POST',headers,body:msg('/useage')},response);
assert.match(response.body.text,/AI 사용량 조회 실패/); assert.equal(response.code,200);
assert.equal(command(msg('/api_status'),stored).aiStatus,true);
assert.equal(command(msg('/api_usage'),stored).aiUsage,true);
assert.match(command(msg('/api_help'),stored).text,/AI API 명령/);
for(const c of ['/useage','/api_usage','/api_status','/api_help']) {
  for(const [from,chat] of [[123,-1],[999,999],[999,123]]) {
    const denied=command(msg(c,from,chat),stored);
    assert.equal(denied.aiUsage,undefined); assert.equal(denied.aiStatus,undefined);
    assert.match(denied.text,/소유자/);
  }
}
text=formatAiStatus({ai:{last_status:'ok',last_model:'gemini-test',last_success_at:new Date(now).toISOString()},
  groq_ai:{last_status:'requesting',last_attempt_at:new Date(now-11*60000).toISOString()}},now);
assert.match(text,/마지막 호출 성공/); assert.match(text,/작업 중단/); assert.match(text,/gemini-test/);
assert.doesNotMatch(formatAiStatus({ai:{last_model:'secret\nunsafe'}},now),/secret/);
response=res(); await handler({method:'POST',headers,body:msg('/api_status')},response);
assert.match(response.body.text,/AI 상태 조회 실패/); assert.equal(response.code,200);
globalThis.fetch=async(url)=>({ok:true,json:async()=>url.includes('news_bot_settings')
  ? [{payload:stored,revision:1}] : [{payload:ai}]});
response=res(); await handler({method:'POST',headers,body:msg('/api_status')},response);
assert.match(response.body.text,/AI API 상태/);
response=res(); await handler({method:'POST',headers,body:msg('/useage')},response);
assert.match(response.body.text,/Gemini/); assert.match(response.body.text,/Groq/);
