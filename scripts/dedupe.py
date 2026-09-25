"""같은 사안을 다룬 여러 매체 기사를 하나로 묶습니다.

기존 동향을 보면 한 섹터에 5건 안팎이 적정한데, 검색으로 모으면 같은 사안이
매체별로 10건씩 잡힙니다. 대표 1건만 남기고 나머지는 '외 N건'으로 접습니다.
"""

from __future__ import annotations

import re

from .models import Article, canonical_url

# 제목에서 의미를 거의 담지 않는 기호·수식어
_NOISE = re.compile(r"""[\[\]（）()<>《》「」『』"'“”‘’…·\-—~!?,.:;|/]+""")
_STOP = ("종합", "속보", "단독", "1보", "2보", "3보", "영상", "포토", "사진")

SIMILARITY_THRESHOLD = 0.52


def event_signature(title: str) -> str:
    """Conservative anchors for recurring stories with very different headlines.

    A shared topic alone is never an event. Require an actor/location and action;
    callers additionally bound the publication interval.
    """
    if all(re.search(p, title) for p in (r"이란", r"호르무즈", r"봉쇄", r"조건|약속", r"이행", r"유지|지속|계속")):
        return "이란:호르무즈:조건이행전봉쇄유지"
    if all(re.search(p, title) for p in (r"호르무즈", r"화물선|벌크선|선박", r"피격|공격|강타", r"인도.*선원.*사망")):
        return "호르무즈:인도선원:선박피격사망"
    if all(re.search(p, title) for p in (r"모스크바", r"정유공장", r"피격")):
        return "모스크바:정유공장:피격"
    if all(re.search(p, title) for p in (r"에너지자원공사", r"울산", r"경주", r"반발|반박|선 긋기")):
        return "경주:울산에너지자원공사유치발표:반박"
    if all(re.search(p, title) for p in (r"석유관리원", r"진주", r"진해", r"무상", r"점검")):
        return "석유관리원:진주진해:무상점검"
    stats = re.search(r"(\d+)년간.*?(\d+)\s*곳", title)
    if stats and re.search(r"명절", title) and re.search(r"불법.*석유|불량.*주유|주유소", title):
        return "명절:석유적발:" + ":".join(stats.groups())
    return ""


def same_story(a: str, b: str, threshold=SIMILARITY_THRESHOLD) -> bool:
    # Preserve different casualty counts, dates, quantities, and explicit new actions.
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    changes = r"추가|새로|재개|해제|확대|확정|명령|결정"
    if set(re.findall(changes, a)) != set(re.findall(changes, b)):
        return False
    key = event_signature(a)
    return bool(key and key == event_signature(b)) or similarity(a, b) >= threshold


def same_article_event(a: Article, b: Article) -> bool:
    from datetime import datetime
    try:
        if abs((datetime.fromisoformat(a.published) - datetime.fromisoformat(b.published)).total_seconds()) > 36 * 3600:
            return False
    except ValueError:
        pass
    if a.event_key and b.event_key:
        return a.event_key == b.event_key
    return same_story(a.title, b.title)


def _normalize(title: str) -> str:
    text = _NOISE.sub(" ", title)
    for word in _STOP:
        text = text.replace(word, " ")
    return re.sub(r"\s+", "", text)


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def similarity(a: str, b: str) -> float:
    """제목 두 개의 글자 바이그램 자카드 유사도 (0.0 ~ 1.0)."""
    x, y = _bigrams(_normalize(a)), _bigrams(_normalize(b))
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def dedupe(articles: list[Article]) -> list[Article]:
    """URL 완전중복 제거 후, 제목이 비슷한 것들을 대표 1건으로 묶습니다.

    입력 순서가 우선순위입니다. 앞에 있는 기사가 대표로 남습니다.
    """
    seen_urls: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        key = canonical_url(article.url)
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique.append(article)

    representatives: list[Article] = []
    for article in unique:
        match = next(
            (
                rep
                for rep in representatives
                if same_article_event(rep, article)
            ),
            None,
        )
        if match is None:
            representatives.append(article)
            continue
        match.duplicates.append(
            {"title": article.title, "source": article.source, "url": article.url}
        )
        # 대표 기사에 없던 리스크 키워드는 끌어올립니다. 묶였다고 놓치면 안 되므로.
        for kw in article.risk:
            if kw not in match.risk:
                match.risk.append(kw)
    return representatives
