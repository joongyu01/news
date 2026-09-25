import {settings} from './_lib.js';

const valid = n => Number.isSafeInteger(n) && n >= 0;
const number = n => valid(n) ? n.toLocaleString('ko-KR') : '미확인';
const dayKst = now => new Date(now + 9*3600000).toISOString().slice(0,10);
const stamp = n => new Date(n).toLocaleString('ko-KR', {timeZone:'Asia/Seoul',hour12:false});

export function formatAiUsage(state, now=Date.now()) {
  const day = dayKst(now);
  const lines = ['🤖 AI API 사용량 · 봇 기록 기준', `조회: ${stamp(now)} KST`,
    '제공업체의 실시간 잔여량이 아닌 이 봇의 사용·보호 한도입니다.'];
  for (const [name, ledger, tokenField] of [
    ['Groq',state?.groq_ai,'total_tokens'], ['Gemini',state?.ai,'totalTokenCount']]) {
    lines.push('', `[${name}]`);
    if (!ledger || !/^\d{4}-\d{2}-\d{2}$/.test(ledger.date || '') || ledger.date > day) {
      lines.push('사용 기록 없음 · 잔여량 미확인'); continue;
    }
    const today = ledger.date === day;
    const requests = today ? ledger.requests : 0;
    lines.push(`오늘 요청: ${number(requests)} / 봇 상한 40회`,
      `남은 요청: ${valid(requests) ? number(Math.max(0,40-requests)) : '미확인'}회 (실패·재시도 포함)`);
    const tokens = today ? ledger.usage?.[tokenField] : 0;
    lines.push(`오늘 응답에서 확인된 토큰: ${number(tokens)}`);
    if (name === 'Groq') {
      const recent = ledger.recent;
      if (Array.isArray(recent) && recent.every(r=>Number.isFinite(r.at) && r.at <= now/1000+60 && valid(r.tokens))) {
        const rows = recent.filter(r=>r.at > now/1000-86400);
        const used = rows.reduce((n,r)=>n+r.tokens,0);
        lines.push(`최근 24시간 사용·예약: ${number(used)} / 봇 예산 200,000토큰`,
          `남은 토큰 예산: ${number(Math.max(0,200000-used))}`,
          `긴급 선별용 여유: ${number(Math.max(0,200000-7800-used))}토큰 · ${valid(requests) ? number(Math.max(0,39-requests)) : '미확인'}회`,
          '조간용 7,800토큰·1회 확보. 실패·미응답 예약분도 포함.');
        if (rows.length) lines.push(`다음 예약분 만료: ${stamp((Math.min(...rows.map(r=>r.at))+86400)*1000)} KST`);
      } else lines.push('최근 24시간 토큰 잔여: 미확인 (기록 부족)');
    } else {
      lines.push('두 키·백업 모델 합산. 키별·모델별 실제 잔여 한도는 미조회.',
        '남은 토큰: 미확인 (Gemini 토큰 상한을 임의 계산하지 않음)');
    }
    lines.push(`마지막 사용 기록일: ${ledger.date} KST`);
  }
  lines.push('', '요청 횟수는 KST 자정 초기화, Groq 토큰 예산은 각 기록의 24시간 경과 시 복원.',
    '다른 앱에서 쓴 양·응답에 없는 토큰은 알 수 없습니다. 실제 API 제한은 더 일찍 걸릴 수 있습니다.',
    '조회 자체는 AI를 호출하지 않습니다.');
  return lines.join('\n');
}

export function formatAiStatus(state, now=Date.now()) {
  const lines=['🤖 AI API 상태 · 최근 호출 기록', `조회: ${stamp(now)} KST`,
    '실시간 접속 시험이 아닙니다. 과거 성공이 현재 가용성을 보장하지 않습니다.'];
  const time = value => Number.isFinite(Date.parse(value)) ? stamp(Date.parse(value))+' KST' : '기록 없음';
  for (const [name,ledger] of [['Groq',state?.groq_ai],['Gemini',state?.ai]]) {
    let status = ({ok:'✅ 마지막 호출 성공',failed:'❌ 마지막 호출 실패',requesting:'⏳ 요청 중 또는 결과 미기록'})[ledger?.last_status] || '상태 기록 없음 (기능 적용 후 갱신)';
    if (ledger?.last_status==='requesting' && now-Date.parse(ledger.last_attempt_at)>10*60000)
      status='⚠️ 요청 후 결과 미기록 · 작업 중단/저장 실패 가능';
    const model = typeof ledger?.last_model === 'string' && /^[a-zA-Z0-9./_-]{1,100}$/.test(ledger.last_model) ? ledger.last_model : '미기록';
    lines.push('',`[${name}] ${status}`,`최근 모델: ${model}`,`최근 요청: ${time(ledger?.last_attempt_at)}`,
      `마지막 성공: ${time(ledger?.last_success_at)}`,`마지막 실패: ${time(ledger?.last_failure_at)}`);
  }
  lines.push('',`기사 수집 갱신: ${time(state?.pool?.updated_at)}`,
    `AI 선별 갱신: ${time(state?.screening?.updated_at)}`,
    '한도 도달·키 미설정 등 호출 전 중단은 /logs_alerts 및 /logs_collect에서 확인하세요.',
    '/api_usage 남은 봇 예산 · /api_help 명령 안내');
  return lines.join('\n');
}

export async function aiUsageText(mode='usage') {
  try {
    const s = settings();
    if (!s.supabaseUrl || !s.supabaseKey) throw new Error('Missing configuration');
    const response = await fetch(`${s.supabaseUrl}/rest/v1/news_alert_state?id=eq.urgent&select=payload`, {
      headers:{apikey:s.supabaseKey,Authorization:`Bearer ${s.supabaseKey}`},signal:AbortSignal.timeout(6000)});
    if (!response.ok) throw new Error('Usage read failed');
    const rows = await response.json();
    return mode==='status' ? formatAiStatus(rows[0]?.payload) : formatAiUsage(rows[0]?.payload);
  } catch {
    return `AI ${mode==='status'?'상태':'사용량'} 조회 실패. 잠시 후 /api_${mode}로 다시 확인해주세요. 잔여량이 0이라는 뜻은 아닙니다.`;
  }
}
