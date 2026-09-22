"""Read a validated Spark morning report without calling an LLM API."""
import argparse
import logging
import os
from . import alerts, analysis, archive, preferences, rolling, storage
from .config import DRAFT_DIR, load_config
from .digest import Digest
from .models import now_kst


def build(state, report, now, config, words=()):
    if report.get('date') != now.strftime('%Y-%m-%d'):
        raise ValueError('Spark report date mismatch')
    articles = rolling.daily_articles(state, now)
    checked = {d['id']: d for d in state.get('screening', {}).get('checked', [])}
    articles = [a for a in articles if checked.get(a.id, {}).get('relevant') is not False
                and not any(w.casefold() in a.title.casefold() for w in words)]
    issues = analysis.validate({'issues': report['issues']}, {a.id for a in articles})
    ids = {i for issue in issues for i in issue['article_ids']}
    selected = [a for a in articles if a.id in ids]
    foreign = {a.id for a in selected if a.language == 'en'}
    if sum(bool(foreign.intersection(i['article_ids'])) for i in issues) > 2:
        raise ValueError('Too many foreign issues')
    return Digest(date=report['date'], generated_at=now.strftime('%Y-%m-%d %H:%M'),
                  articles=selected,
                  sectors=[{'id': s.id, 'title': s.title, 'limit': s.limit} for s in config.sectors],
                  analysis={'version': 1, 'model': 'gemini-spark', 'issues': issues,
                            'input_count': len(articles), 'usage': {}, 'attempts': [],
                            'pool_updated_at': report['pool_updated_at']})


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    now = now_kst()
    date = now.strftime('%Y-%m-%d')
    ready = False
    if archive.archive_path(date).exists():
        print('이미 발송된 날짜 — 생략')
    elif existing := storage.read('news_drafts', date):
        if existing.get('analysis', {}).get('model') != 'gemini-spark':
            raise ValueError('Existing draft belongs to another producer')
        digest = Digest.from_dict(existing)
        ready = True
    else:
        prefs = preferences.load()
        report = prefs.get('spark_morning', {})
        if report.get('date') == date:
            digest = build(alerts.read_state(), report, now, load_config(), prefs.get('global', {}).get('exclude', []))
            ready = True
        elif now.hour >= 10:
            raise RuntimeError('Spark 조간 결과 미접수 — Gemini 예약 실행·승인 상태 확인 필요')
        else:
            print('Spark 조간 결과 대기 중 — 발송 없음')
    if ready:
        print(f'Spark 조간 검증 성공: 이슈 {len(digest.analysis["issues"])}개')
        if not args.dry_run:
            storage.save_draft(digest)
            digest.save(DRAFT_DIR / f'{date}.json')
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as f:
            f.write(f'ready={str(ready).lower()}\n')
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.error('Spark 조간 준비 실패 (%s). 예약 실행·승인·접수 상태를 확인하세요.', type(exc).__name__)
        raise SystemExit(1)
