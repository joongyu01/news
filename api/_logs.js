import {settings} from './_lib.js';

const stamp = value => Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString('ko-KR', {timeZone:'Asia/Seoul', hour12:false}) : '기록 없음';
const count = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('ko-KR') : '미기록';
const names = {collect:'아침 수집', dispatch:'동향 발송', alerts:'긴급 뉴스 점검'};
const states = {success:'✅ 성공', failure:'❌ 실패', cancelled:'취소', timed_out:'시간 초과',
  skipped:'건너뜀', in_progress:'⏳ 실행 중', queued:'대기 중', waiting:'대기 중', action_required:'조치 필요'};

async function read(table, query) {
  const s = settings();
  const response = await fetch(`${s.supabaseUrl}/rest/v1/${table}?${query}`, {
    headers:{apikey:s.supabaseKey, Authorization:`Bearer ${s.supabaseKey}`},
    signal:AbortSignal.timeout(6000),
  });
  if (!response.ok) throw Error('운영 기록 조회 실패');
  return response.json();
}

export function formatLogs(snapshot, draft, alert, selected='', now=Date.now()) {
  const lines = ['🗒 뉴스 운영 기록 (KST)'];
  if (!selected || selected === 'collect') {
    lines.push('', '최근 저장된 아침 초안');
    if (draft) {
      const articles = Array.isArray(draft.articles) ? draft.articles : [];
      const duplicates = articles.reduce((n,a)=>n+(Array.isArray(a.duplicates)?a.duplicates.length:0),0);
      lines.push(`대상 날짜: ${draft.date} · 생성: ${draft.generated_at || '미기록'} KST`,
        `저장 기사: ${count(articles.length+duplicates)}건 (대표 ${count(articles.length)} · 중복 ${count(duplicates)})`);
      const s = draft.collection_stats;
      if (s && Number.isSafeInteger(s.raw)) lines.push(`원시 수집 ${count(s.raw)} → 최근 기사 ${count(s.fresh)} → 분류 통과 ${count(s.classified)}건`);
      else lines.push('이전 초안의 원시 수집/필터 통과 건수는 상세 로그에서 확인하세요.');
      for (const sector of (draft.sectors || []).slice(0,10)) {
        lines.push(`  ${String(sector.title || sector.id).slice(0,50)}: 대표 ${articles.filter(a=>a.sector===sector.id).length}건`);
      }
    } else lines.push('조회 실패 또는 저장된 초안 없음');
  }
  if (!selected || selected === 'alerts') {
    lines.push('', '최근 긴급 검색 기록');
    if (alert?.last_checked_at) {
      lines.push(`점검 시작: ${stamp(alert.last_checked_at)}`,
        `수집 ${count(alert.last_collected)}건 · 발송 ${count(alert.last_sent)}건(수신방별)`);
      if (alert.last_completed_at) lines.push(`점검 종료: ${stamp(alert.last_completed_at)} · 후보 ${count(alert.last_candidates)} · 실패 ${count(alert.last_failures)}건`);
      if (now-Date.parse(alert.last_checked_at)>45*60*1000) lines.push('⚠️ 45분 이상 새 점검 기록이 없습니다. 아래 실행 결과를 확인하세요.');
    } else lines.push('조회 실패 또는 점검 기록 없음');
  }
  lines.push('', `GitHub 실행 기록 조회: ${stamp(snapshot?.checked_at)}`);
  if (!snapshot?.checked_at || now-Date.parse(snapshot.checked_at)>45*60*1000) lines.push('⚠️ 실행 기록 갱신이 늦거나 아직 없습니다. 링크에서 최신 상태를 확인하세요.');
  const repository = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(snapshot?.repository || '')
    ? snapshot.repository : 'joongyu01/news';
  for (const type of (selected ? [selected] : Object.keys(names))) {
    lines.push('', names[type]);
    const runs = (snapshot?.runs?.[type] || []).slice(0,selected?3:1);
    if (!runs.length) lines.push('실행 기록 조회 불가');
    for (const run of runs) {
      const state = run.status === 'completed' ? (states[run.conclusion] || '완료 · 결과 미상') : (states[run.status] || '상태 미상');
      lines.push(`${state} · ${run.event==='schedule'?'예약':run.event==='workflow_dispatch'?'수동':'기타'} 실행`,
        `시작 ${stamp(run.run_started_at)} · 갱신 ${stamp(run.updated_at)}`);
      if (Number.isSafeInteger(run.id) && run.id > 0) lines.push(`https://github.com/${repository}/actions/runs/${run.id}`);
    }
  }
  lines.push('', '수동 실행에는 시험 실행도 포함됩니다. 실행 성공과 실제 발송 여부는 상세 로그에서 확인하세요.',
    '예약: 수집 24시간 15분 간격 · AI 긴급 06:00~23:30 매시 00/30분 · 조간 05:17 예약 (08시 전 수신 목표, 지연 가능)',
    '/logs_collect 수집 · /logs_alerts 긴급 · /logs_dispatch 발송 (각 최근 3회)');
  return lines.join('\n');
}

export async function logsText(snapshot, selected='') {
  const [draft, alert] = await Promise.allSettled([
    !selected || selected==='collect'
      ? read('news_drafts','select=payload&order=date.desc&limit=1') : Promise.resolve([]),
    !selected || selected==='alerts'
      ? read('news_alert_state','id=eq.urgent&select=last_checked_at:payload->>last_checked_at,last_completed_at:payload->>last_completed_at,last_collected:payload->last_collected,last_sent:payload->last_sent,last_candidates:payload->last_candidates,last_failures:payload->last_failures') : Promise.resolve([]),
  ]);
  return formatLogs(snapshot, draft.status==='fulfilled'?draft.value[0]?.payload:null,
    alert.status==='fulfilled'?alert.value[0]:null, selected);
}
