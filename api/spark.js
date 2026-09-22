import crypto from 'node:crypto';
import {json, verifySession, settings, todayKST, readFile} from './_lib.js';
import {db, globalOptions} from './_bot.js';

export function candidates(state, stored, now=Date.now()) {
  const age=now-Date.parse(state?.pool?.updated_at);
  if(!Number.isFinite(age) || age < -300000 || age > 86400000) throw Error('Stale collection');
  const decisions=new Map((state.screening?.checked || []).map(d=>[d.id,d]));
  const words=globalOptions(stored).exclude;
  let size=0, foreign=0;
  return (state.pool.articles || []).filter(a=> {
    const age=now-Date.parse(String(a.published).replace(' ','T')+':00+09:00');
    return age>=-300000 && age<=86400000 && /^https?:\/\//.test(a.url) &&
      decisions.get(a.id)?.relevant!==false && !words.some(w=>a.title.toLowerCase().includes(w.toLowerCase()));
  }).sort((a,b)=>b.published.localeCompare(a.published)).filter(a=> {
    if(a.language==='en' && foreign>=20) return false;
    size+=JSON.stringify(a).length;
    if(size>60000) return false;
    foreign+=a.language==='en'; return true;
  }).slice(0,120);
}
export function validateReport(body, articles, date=todayKST()) {
  if(body?.date!==date || !Array.isArray(body.issues) || body.issues.length>5 ||
     Object.keys(body).some(k=>!['date','issues','test'].includes(k))) throw Error('Invalid report');
  const known=new Map(articles.map(a=>[a.id,a])), seen=new Set();
  let foreign=0;
  const fields={title:120,summary:350,change:250,impact:250};
  for(const issue of body.issues) {
    if(!issue || Object.keys(issue).sort().join()!==[...Object.keys(fields),'article_ids'].sort().join()) throw Error('Invalid fields');
    for(const [k,n] of Object.entries(fields)) if(typeof issue[k]!=='string' || !issue[k].trim() ||
       issue[k].length>n || /https?:\/\/|<[^>]+>|[\x00-\x1f]/.test(issue[k])) throw Error('Invalid text');
    const ids=issue.article_ids;
    if(!Array.isArray(ids) || ids.length<1 || ids.length>3) throw Error('Invalid evidence');
    for(const id of ids) {if(!known.has(id)||seen.has(id)) throw Error('Invalid evidence'); seen.add(id);}
    foreign+=ids.some(id=>known.get(id).language==='en');
  }
  if(foreign>2 || (body.test!==undefined && typeof body.test!=='boolean')) throw Error('Invalid report');
  return body.issues;
}
async function state() {
  const s=settings();
  const r=await fetch(`${s.supabaseUrl}/rest/v1/news_alert_state?id=eq.urgent&select=payload`,{
    headers:{apikey:s.supabaseKey,Authorization:`Bearer ${s.supabaseKey}`},signal:AbortSignal.timeout(8000)});
  if(!r.ok) throw Error('Collection read failed');
  return (await r.json())[0]?.payload;
}

export function relayKey() {
  if (!process.env.SESSION_SECRET) throw Error('Not configured');
  return crypto.createHmac('sha256',process.env.SESSION_SECRET).update('news-spark-submit-v1').digest('hex');
}
function authorized(req) {
  const given=String(req.headers.authorization || '').replace(/^Bearer /,'');
  return crypto.timingSafeEqual(crypto.createHash('sha256').update(given).digest(),
    crypto.createHash('sha256').update(relayKey()).digest());
}
export default async function handler(req,res) {
  try {
    if(req.method==='GET' && req.query?.setup==='1') {
      if(!verifySession(req)) return json(res,401,{error:'검토 페이지 로그인이 필요합니다.'});
      return json(res,200,{key:relayKey()});
    }
    if(!['GET','POST'].includes(req.method)) return json(res,405,{error:'허용되지 않은 요청입니다.'});
    if(!authorized(req)) return json(res,403,{error:'연결 키를 확인하세요.'});
    res.setHeader('Cache-Control','no-store');
    const collected=await state();
    for(let attempt=0;attempt<3;attempt++) {
      const rows=await db('GET','id=eq.main&select=payload,revision');
      if(!rows.length) throw Error('Settings missing');
      const {payload,revision}=rows[0];
      const articles=candidates(collected,payload), date=todayKST();
      if(req.method==='GET') {
        const yesterday=new Date(Date.now()-86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Seoul'});
        const previous=await readFile(`data/drafts/${yesterday}.json`);
        return json(res,200,{date,pool_updated_at:collected.pool.updated_at,
          articles:articles.map(({id,title,summary,source,published,language})=>({id,title,summary,source,published,language})),
          previous:previous?.json?.analysis?.issues || [],accepted:payload.spark_morning?.date===date});
      }
      if(Buffer.byteLength(JSON.stringify(req.body || {}))>16000) return json(res,413,{error:'보고가 너무 큽니다.'});
      let issues;
      try {issues=validateReport(req.body,articles,date);} catch {return json(res,400,{error:'날짜·근거 ID·JSON 형식을 확인하세요.'});}
      if(req.body.test) return json(res,200,{ok:true,message:'검증 성공 · 저장·발송 없음'});
      if(payload.spark_morning?.date===date) return json(res,200,{ok:true,message:'오늘 보고는 이미 접수됨 · 중복 저장 없음'});
      payload.spark_morning={date,issues,received_at:new Date().toISOString(),pool_updated_at:collected.pool.updated_at};
      if(Buffer.byteLength(JSON.stringify(payload))>65536) return json(res,413,{error:'설정 저장 한도를 초과했습니다.'});
      const saved=await db('PATCH',`id=eq.main&revision=eq.${revision}`,{payload,revision:revision+1,updated_at:new Date().toISOString()});
      if(saved.length) return json(res,200,{ok:true,message:'조간 접수 완료 · 아직 발송 전입니다. 서버가 검증 후 전달합니다.'});
    }
    throw Error('Concurrent update');
  } catch {return json(res,503,{error:'연결을 확인한 뒤 다시 시도하세요.'});}
}
