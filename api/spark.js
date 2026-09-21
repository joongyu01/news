import crypto from 'node:crypto';
import {json, verifySession} from './_lib.js';

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
      return json(res,410,{error:'웹 예약 접수는 종료되었습니다.'});
    }
    if(!['GET','POST'].includes(req.method)) return json(res,405,{error:'허용되지 않은 요청입니다.'});
    if(!authorized(req)) return json(res,403,{error:'연결 키를 확인하세요.'});
    return json(res,410,{error:'웹 예약 보고는 종료되었습니다. 아침 Gemini API 종합 분석으로 통합했습니다.'});
  } catch {return json(res,503,{error:'연결을 확인한 뒤 다시 시도하세요.'});}
}
