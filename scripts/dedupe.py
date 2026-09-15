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
                if rep.sector == article.sector
                and similarity(rep.title, article.title) >= SIMILARITY_THRESHOLD
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
