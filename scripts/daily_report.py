"""Bounded operational summary, delivered only to the configured private owner."""
import argparse
import re
from datetime import datetime, timedelta, timezone

import requests

from . import alerts, preferences, storage
from .config import env
from .models import now_kst
from .notify import send_telegram
from .sources import KST
from .spark_relay import update

WORKFLOWS = {'alerts.yml': '수집', 'screening.yml': '긴급 선별',
             'collect.yml': '조간', 'dispatch.yml': '수동 발송', 'weekly.yml': '주간'}


def workflow_counts(now):
    repo, token = env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not token:
        raise RuntimeError('GitHub configuration missing')
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    counts = {name: {'success': 0, 'failed': 0, 'other': 0} for name in WORKFLOWS.values()}
    seen = set()
    for page in range(1, 11):
        response = requests.get(f'https://api.github.com/repos/{repo}/actions/runs',
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'},
            params={'per_page': 100, 'page': page, 'branch': 'main',
                    'created': f'{start.astimezone(timezone.utc).isoformat()}..{now.astimezone(timezone.utc).isoformat()}'}, timeout=15)
        response.raise_for_status()
        runs = response.json()['workflow_runs']
        for run in runs:
            name = WORKFLOWS.get(run.get('path', '').split('/')[-1])
            if not name or run['id'] in seen:
                continue
            seen.add(run['id'])
            result = run.get('conclusion')
            key = 'success' if result == 'success' else 'failed' if result in ('failure', 'timed_out', 'action_required') else 'other'
            counts[name][key] += 1
        if len(runs) < 100:
            return counts
    raise RuntimeError('Daily run count exceeds bounded query')


def chat_info(prefs):
    result = {}
    for chat in prefs['chats']:
        try:
            response = requests.post(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/getChat",
                                     json={'chat_id': chat}, timeout=10)
            body = response.json()
            if not response.ok or not body.get('ok'):
                continue
            info = body['result']
            name = info.get('title') or ' '.join(filter(None, [info.get('first_name'), info.get('last_name')]))
            result[chat] = {'name': re.sub(r'[\x00-\x1f]', ' ', name)[:100] or '이름 미확인'}
        except (requests.RequestException, ValueError, KeyError):
            continue
    return result


def format_report(now, state, prefs, counts, draft):
    day = now.date().isoformat()
    lines = [f'📊 뉴스 봇 일일 운영 요약 · {day}', f'집계: 오늘 00:00~{now:%H:%M} KST', '']
    if counts is None:
        lines.append('작업 성공·실패: GitHub 조회 실패 (0회가 아닙니다)')
    else:
        failed = sum(v['failed'] for v in counts.values())
        lines.append(f'작업 실패 {failed}회 (실행별 최종 상태 기준)')
        for name, v in counts.items():
            lines.append(f"· {name}: 성공 {v['success']} / 실패 {v['failed']} / 취소·진행 등 {v['other']}")
        lines.append('백업 모델로 복구된 API 오류·재실행 전 실패는 위 실패 횟수에 포함되지 않습니다.')
    lines.append('')
    if state is None:
        lines.append('기사·긴급 기록: 조회 실패 또는 기록 없음')
    else:
        stats = state.get('daily_counts', {}).get(day)
        if stats:
            lines.append(f"수집 처리 {stats['collected']}건 · {stats['collection_runs']}회 (반복 기사 포함)")
            lines.append(f"수집 집계 시작: {stats['started_at'][11:16]} · 기능 적용 이후 기록")
        else:
            lines.append('수집 처리 합계: 집계 기록 없음 (기능 적용 이후부터 누적)')
        articles = state.get('pool', {}).get('articles', [])
        today = {a['id'] for a in articles if a.get('published', '').startswith(day)}
        checked = {d['id']: d for d in state.get('screening', {}).get('checked', [])}
        lines.append(f'보관 중인 오늘 발행 기사: {len(today)}건 (중복 제거·보관 한도 적용)')
        lines.append(f"이 중 AI 판정 {sum(i in checked for i in today)}건 · 긴급 판정 {sum(bool(checked.get(i, {}).get('urgent')) for i in today)}건")
        sent = [x for x in state.get('sent', []) if datetime.fromisoformat(x['sent_at']).astimezone(KST).date() == now.date()]
        lines.append(f"보관된 오늘 긴급 발송: 기사 {len({x['id'] for x in sent})}건 / 수신방별 합계 {len(sent)}건")
        lines.append('최근 수집: ' + str(state.get('pool', {}).get('updated_at', '없음'))[:25])
    if draft is None:
        lines.append('조간 초안: 없음 또는 조회 실패')
    else:
        lines.append('조간 초안: ' + ('AI 실패 → 기본 스크랩' if draft.get('fallback_notice') else '생성됨'))
    lines += ['', f"구독 {len(prefs['chats'])}개 방 · /subscribers로 조회",
              '20:00 예약 요약입니다. 실행 지연 시 실제 집계 시각까지 포함합니다.',
              '이 운영 요약은 소유자 개인톡에만 전달됩니다. /daily_report로 다시 조회']
    return '\n'.join(lines)


def run(*, dry_run=False):
    now = now_kst()
    prefs = preferences.load()
    owner = str(prefs['owner'])
    if not owner.isdigit() or int(owner) <= 0 or owner != env('TELEGRAM_CHAT_ID'):
        raise RuntimeError('Private owner mismatch')
    day = now.date().isoformat()
    if not dry_run and prefs.get('daily_report', {}).get('sent_date') == day:
        print('오늘 운영 요약은 이미 발송했습니다')
        return
    try:
        counts = workflow_counts(now)
    except Exception:
        counts = None
    try:
        state = alerts.read_state()
    except Exception:
        state = None
    try:
        rows = storage.request('GET', 'news_drafts', params={'date': f'eq.{day}', 'select': 'payload'}).json()
        draft = rows[0]['payload'] if rows else None
    except Exception:
        draft = None
    text = format_report(now, state, prefs, counts, draft)
    if dry_run:
        print(text)
        return
    names = chat_info(prefs)
    # One shared Actions concurrency group serializes reporting and news jobs.
    # Save only after confirmed delivery; a lost Telegram response cannot be made exactly-once.
    if send_telegram([text], chat_id=owner) != 1:
        raise RuntimeError('Daily report delivery failed')
    def save(p):
        p['daily_report'] = {'sent_date': day, 'generated_at': now.isoformat(), 'text': text}
        old = p.get('chat_info', {})
        p['chat_info'] = {c: names.get(c, old.get(c, {'name': '이름 미확인'})) for c in p['chats']}
    update(save)
    print('운영 요약 1건 소유자 개인톡 발송·저장 완료')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    try:
        run(dry_run=parser.parse_args().dry_run)
    except Exception as exc:
        print(f'운영 요약 실패 ({type(exc).__name__})')
        raise SystemExit(1)
