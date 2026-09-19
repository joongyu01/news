const kst = value => new Date(value).toLocaleString('ko-KR', {timeZone:'Asia/Seoul', hour12:false});
const integer = value => Number.isSafeInteger(value) && value >= 0;
const amount = value => value.toLocaleString('ko-KR');

export function usageText(snapshot, now=Date.now()) {
  if (!snapshot || !Number.isFinite(Date.parse(snapshot.checked_at))) {
    return 'GitHub 사용량을 아직 조회하지 못했습니다. 다음 뉴스 점검 후 /usage로 확인해주세요.\n계정 청구 확인: https://github.com/settings/billing/usage';
  }
  const lines = ['📊 GitHub 뉴스 봇 사용량', `조회 기준: ${kst(snapshot.checked_at)} KST`];
  const age = now - Date.parse(snapshot.checked_at);
  if (age > 45*60*1000 || age < -60000) lines.push('⚠️ 최신 수치가 아닙니다. 예약 실행 지연 또는 조회 실패 가능성이 있습니다.');
  lines.push('', '실행 시간 (GitHub Actions)');
  if (snapshot.visibility === 'public' && snapshot.standard_runners === true) {
    lines.push('공개 저장소 · 표준 Ubuntu 실행기', '실행 시간 무료 · 월 무료 실행분 차감 없음', '남은 실행분: 이 저장소에는 차감 한도 적용 안 됨');
  } else {
    lines.push('무료 실행분 잔여량: 조회 불가 (계정 청구 조회 권한 필요)');
  }
  lines.push('', 'API 호출 한도 (뉴스 저장소의 GITHUB_TOKEN)');
  const r = snapshot.rate;
  if (r && integer(r.limit) && integer(r.remaining) && r.remaining <= r.limit && integer(r.reset)
      && Number.isFinite(new Date(r.reset*1000).getTime())) {
    lines.push(`조회 당시 잔여: ${amount(r.remaining)} / ${amount(r.limit)}회`,
      `사용: ${amount(r.limit-r.remaining)}회 · 초기화: ${kst(r.reset*1000)} KST`);
    if (r.reset*1000 <= now) lines.push('⚠️ 위 초기화 시각이 지나 현재 잔여량은 다음 점검 후 확인할 수 있습니다.');
  } else lines.push('잔여 호출 수: 조회 실패 (0회라는 뜻이 아닙니다)');
  lines.push('API 호출 횟수이며 AI 토큰·유료 크레딧 잔액과는 별개입니다.');
  lines.push('', 'Actions 캐시');
  if (integer(snapshot.cache_bytes)) {
    const gb = snapshot.cache_bytes / 2**30;
    lines.push(`현재 ${gb.toFixed(3)} GiB / 무료 기준 10 GiB`,
      `무료 기준까지 여유: ${Math.max(0,10-gb).toFixed(3)} GiB`);
  } else lines.push('현재 용량: 조회 실패');
  lines.push('', '계정 전체 청구액·유료 잔액: 미조회',
    '캐시·아티팩트 등 저장 비용은 실행 시간과 별도입니다.',
    'https://github.com/settings/billing/usage',
    '기존 15분 예약 실행 때 갱신합니다. 예약 지연 가능.');
  return lines.join('\n');
}
