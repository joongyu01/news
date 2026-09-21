import {settings} from './_lib.js';
import {globalOptions} from './_bot.js';

const esc = value => String(value || '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function formatAudit(state, stored, {page=1, excluded=false}={}, now=Date.now()) {
  const options = globalOptions(stored);
  const checked = new Map((state?.screening?.checked || []).map(d=>[d.id,d]));
  const rows = (state?.pool?.articles || []).map(a=> {
    const d = checked.get(a.id);
    const word = options.exclude.find(w=>a.title.toLowerCase().includes(w.toLowerCase()));
    let reason, omitted=true;
    if (word) reason=`전체 제외 키워드: ${word}`;
    else if (now-Date.parse(a.published.replace(' ','T')+':00+09:00')>86400000) reason='최근 24시간 분석 범위 밖';
    else if (!d) {reason='AI 판정 대기 (미실행·실패 여부는 /logs 확인)'; omitted=false;}
    else if (!d.relevant) reason=`AI 관련성 제외: ${d.reason}`;
    else if (!d.urgent) reason=`조간 후보 · 긴급 제외: ${d.reason}`;
    else {reason=`긴급 후보: ${d.reason} (최종 규칙·중복·발송 설정을 추가 적용)`; omitted=false;}
    return {...a, reason, omitted};
  });
  const all = [...rows, ...(state?.pool?.rejected || []).map(a=>({...a,omitted:true}))]
    .filter(a=>!excluded || a.omitted).sort((a,b)=>String(b.published || '').localeCompare(String(a.published || '')));
  const pages = Math.max(1,Math.ceil(all.length/5));
  if (page>pages) return `총 ${pages}페이지입니다. /${excluded?'excluded':'articles'}_${pages}`;
  const lines = [`<b>${excluded?'제외·긴급 제외 사유':'수집 기사와 판정'}</b> (${page}/${pages}, ${all.length}건)`,
    '최근 48시간 보관 자료 · 조간 후보는 최종 선정/발송을 의미하지 않습니다.'];
  for (const a of all.slice((page-1)*5,page*5)) {
    const title=esc(a.title.slice(0,180));
    const url=/^https?:\/\//i.test(a.url || '') ? a.url : '';
    lines.push('', url ? `<a href="${esc(url)}">${title}</a>` : title,
      esc(`${a.published || ''} · ${a.source || ''}`.slice(0,100)), esc(a.reason.slice(0,220)));
  }
  if (!all.length) lines.push('기록이 없습니다. 규칙 필터 제외 기록은 기능 적용 이후부터 쌓입니다.');
  if (page<pages) lines.push('', `다음: /${excluded?'excluded':'articles'}_${page+1}`);
  lines.push('', '검색 원시 결과 전체가 아닌 제한된 보관 기록입니다.');
  return lines.join('\n');
}

export async function auditText(stored, selection) {
  const s=settings();
  const r=await fetch(`${s.supabaseUrl}/rest/v1/news_alert_state?id=eq.urgent&select=payload`,{
    headers:{apikey:s.supabaseKey,Authorization:`Bearer ${s.supabaseKey}`},signal:AbortSignal.timeout(6000)});
  if (!r.ok) return '기사 판정 조회에 실패했습니다. 잠시 후 다시 요청해주세요.';
  const data=await r.json();
  return formatAudit(data[0]?.payload,stored,selection);
}
