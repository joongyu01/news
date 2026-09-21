"""15분 수집의 제한된 기사 풀. 기존 urgent 행의 단일 writer가 갱신한다."""
import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .models import Article
from .sources import KST
from .editorial import prepare, relevance
from .classify import is_blocked

MAX_ARTICLES = 600
MAX_BYTES = 900_000
RETENTION_HOURS = 48


def published(article):
    try:
        return datetime.strptime(article.published, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def accumulate(state, incoming, now, config):
    previous = state.get("pool", {})
    rejected = {a['id']: a for a in previous.get('rejected', [])
                if a.get('observed_at', '') >= (now-timedelta(hours=48)).isoformat()}
    for a in incoming:
        score, _, reason = relevance(a)
        if not score or is_blocked(a, config):
            rejected[a.id] = {'id': a.id, 'title': a.title[:180], 'source': a.source[:60],
                              'published': a.published, 'observed_at': now.isoformat(),
                              'reason': '수집 규칙 제외: ' + (reason if not score else '기본 차단 키워드')}
    items = [Article.from_dict(a) for a in previous.get("articles", [])]
    by_id = {}
    for a in prepare([*items, *incoming], config):
        when = published(a)
        if not when or not now-timedelta(hours=RETENTION_HOURS) <= when <= now+timedelta(minutes=5):
            continue
        url = urlsplit(a.url)
        if url.scheme not in ("https", "http") or not url.netloc or len(a.url) > 2500:
            continue
        if a.id in by_id:
            continue
        a.title, a.summary, a.source = a.title[:500], a.summary[:500], a.source[:100]
        a.duplicates = []  # 반복 수집 때 중복 목록이 불어나지 않도록 아침에 한 번 묶는다.
        by_id[a.id] = a.to_dict()
    articles = list(by_id.values())[:MAX_ARTICLES]
    while len(json.dumps(articles, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        articles.pop()
    state["pool"] = {"articles": articles, "updated_at": now.isoformat(),
                     "rejected": sorted(rejected.values(), key=lambda a:a['observed_at'], reverse=True)[:150],
                     "started_at": previous.get("started_at", now.isoformat())}


def daily_articles(state, now, hours=24):
    pool = (state or {}).get("pool")
    if not pool:
        raise RuntimeError("누적 기사 풀이 없습니다. 15분 통합 수집을 먼저 실행하세요.")
    updated = datetime.fromisoformat(pool["updated_at"])
    if not timedelta(minutes=-5) <= now-updated <= timedelta(hours=2):
        raise RuntimeError("통합 수집이 2시간 이상 갱신되지 않아 분석을 중단합니다.")
    items = [Article.from_dict(a) for a in pool["articles"]]
    return [a for a in items if (when := published(a)) and
            now-timedelta(hours=hours) <= when <= now+timedelta(minutes=5)]
