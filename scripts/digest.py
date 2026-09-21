"""하루치 동향 묶음 — 초안 저장과 최종 발송이 공유하는 자료구조."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .models import Article


@dataclass
class Digest:
    date: str                                  # "2026-09-16"
    generated_at: str = ""                     # "2026-09-16 06:40"
    articles: list[Article] = field(default_factory=list)
    market: list[dict[str, Any]] = field(default_factory=list)
    # 섹터 정의를 초안에 함께 적어둡니다. 검토 페이지(Node)가 config/news.yml 을
    # 따로 파싱하지 않아도 되고, 나중에 설정이 바뀌어도 과거 초안은 그대로 열립니다.
    sectors: list[dict[str, Any]] = field(default_factory=list)
    collection_stats: dict[str, int] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)

    def visible_issues(self, excluded=None):
        known = {a.id for a in self.articles}
        excluded = excluded or set()
        return [i for i in self.analysis.get("issues", [])
                if i.get("article_ids") and set(i["article_ids"]) <= known
                and not set(i["article_ids"]) & excluded]

    # ------------------------------------------------------------------
    def by_sector(
        self, config: Config, excluded: set[str] | None = None
    ) -> list[tuple[str, list[Article]]]:
        """[(섹터 제목, 기사들)] — 설정 파일의 섹터 순서를 그대로 따릅니다.

        제외된 기사는 빠지고, 섹터별 상한(limit)이 적용됩니다.
        기사가 하나도 없는 섹터는 아예 나타나지 않습니다.
        """
        excluded = excluded or set()
        selected = ({id for issue in self.visible_issues(excluded) for id in issue["article_ids"]}
                    if self.analysis else None)
        result: list[tuple[str, list[Article]]] = []
        for sector in config.sectors:
            picked = [
                a
                for a in self.articles
                if a.sector == sector.id and a.id not in excluded
                and (selected is None or a.id in selected)
            ]
            if selected is None:
                picked = picked[:sector.limit]
            if picked:
                result.append((sector.title, picked))
        return result

    def risk_articles(self, excluded: set[str] | None = None) -> list[Article]:
        excluded = excluded or set()
        selected = ({id for issue in self.visible_issues(excluded) for id in issue["article_ids"]}
                    if self.analysis else None)
        return [a for a in self.articles if a.risk and a.id not in excluded
                and (selected is None or a.id in selected)]

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "market": self.market,
            "sectors": self.sectors,
            "collection_stats": self.collection_stats,
            "analysis": self.analysis,
            "articles": [a.to_dict() for a in self.articles],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Digest":
        return cls(
            date=data["date"],
            generated_at=data.get("generated_at", ""),
            market=data.get("market", []),
            sectors=data.get("sectors", []),
            collection_stats=data.get("collection_stats", {}),
            analysis=data.get("analysis", {}),
            articles=[Article.from_dict(a) for a in data.get("articles", [])],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "Digest":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_exclusions(path: Path) -> set[str]:
    """검토 페이지가 저장해둔 제외 목록. 파일이 없으면 '아무것도 제외 안 함'."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("excluded", []))
