import crypto from 'node:crypto';
import {json, verifySession} from './_lib.js';
import {db} from './_bot.js';

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
    if(req.method==='GET') {
      const rows=await db('GET','id=eq.main&select=payload');
      const p=rows[0]?.payload;
      if(!p) return json(res,503,{error:'봇 설정이 준비되지 않았습니다.'});
      return json(res,200,{pending:(p.spark_queue||[]).length,recent:(p.spark_recent||[]).slice(-5)});
    }
    const text=typeof req.body?.text==='string' ? req.body.text.trim() : '';
    if(text.length<10 || text.length>3000) return json(res,400,{error:'보고 내용은 10~3000자로 입력하세요.'});
    const id=crypto.createHash('sha256').update(text).digest('hex').slice(0,24);
    for(let attempt=0;attempt<4;attempt++) {
      const rows=await db('GET','id=eq.main&select=payload,revision');
      if(!rows.length) return json(res,503,{error:'봇 설정이 준비되지 않았습니다.'});
      const {payload:p,revision}=rows[0];
      const recent=(p.spark_recent||[]).filter(x=>Date.parse(x.sent_at)>Date.now()-7*86400000).slice(-100);
      const queue=p.spark_queue||[];
      const previous=recent.find(x=>x.id===id);
      if(previous || queue.some(x=>x.id===id)) return json(res,200,{ok:true,id,status:previous?'delivered':'queued',duplicate:true});
      if(queue.length>=3) return json(res,429,{error:'전달 대기 3건이 있어 잠시 후 다시 시도하세요.'});
      p.spark_queue=[...queue,{id,text,created_at:new Date().toISOString()}];
      p.spark_recent=recent;
      if(Buffer.byteLength(JSON.stringify(p))>60000) return json(res,413,{error:'저장 공간 보호 한도입니다. 내용을 줄여주세요.'});
      const saved=await db('PATCH',`id=eq.main&revision=eq.${revision}`,{payload:p,revision:revision+1,updated_at:new Date().toISOString()});
      if(saved.length) return json(res,200,{ok:true,id,status:'queued',message:'접수 완료. 기존 뉴스 봇의 다음 실행에서 소유자 개인 텔레그램으로 전달됩니다.'});
    }
    return json(res,503,{error:'설정이 변경 중입니다. 다시 시도하세요.'});
  } catch {return json(res,503,{error:'연결을 확인한 뒤 다시 시도하세요.'});}
}
