"""섹터 분류와 리스크 키워드 판정."""

from __future__ import annotations

from .config import Config
from .models import Article


def _text(article: Article) -> str:
    return f"{article.title} {article.summary}"


def _query_sector(config: Config) -> dict[str, str]:
    """검색어 -> 섹터 id 역색인."""
    return {q: s.id for s in config.sectors for q in s.queries}


def sector_for(article: Article, config: Config, query_map: dict[str, str]) -> str | None:
    """기사가 속할 섹터. 어디에도 안 걸리면 None (= 버림).

    판정 순서가 중요합니다.
      1. must 키워드가 최우선. '국제유가' 검색에 걸렸더라도 석유관리원이
         언급됐다면 석유관리원 뉴스로 올립니다.
      2. 그 다음이 '어떤 검색어로 걸렸는가'. 검색어는 섹터별로 짜여 있으므로
         가장 신뢰할 만한 신호입니다.
      3. 마지막이 any 키워드. 업계지 RSS처럼 검색어가 없는 경로를 위한 장치.
    """
    text = _text(article)

    for sector in config.sectors:
        if any(kw in text for kw in sector.must):
            return sector.id

    mapped = query_map.get(article.query)
    if mapped:
        return mapped

    for sector in config.sectors:
        if any(kw in text for kw in sector.any):
            return sector.id

    return None


def risks_for(article: Article, config: Config) -> list[str]:
    """제목·요약에 걸린 리스크 키워드 목록."""
    text = _text(article)
    return [kw for kw in config.risk_keywords if kw in text]


def is_blocked(article: Article, config: Config) -> bool:
    """수집 단계에서 통째로 버릴 기사인지."""
    if any(bad in article.title for bad in config.block_titles):
        return True
    return any(src and src in article.source for src in config.block_sources)


def classify_all(articles: list[Article], config: Config) -> list[Article]:
    """분류 + 리스크 판정 + 차단 목록 적용. 섹터 없는 기사는 빠집니다."""
    query_map = _query_sector(config)
    kept: list[Article] = []
    for article in articles:
        if is_blocked(article, config):
            continue
        sector = sector_for(article, config, query_map)
        if sector is None:
            continue
        article.sector = sector
        article.risk = risks_for(article, config)
        kept.append(article)
    return kept
