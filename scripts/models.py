"""수집한 기사를 표현하는 자료구조."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

KST_FMT = "%Y-%m-%d %H:%M"

_TRACKING_PARAMS = re.compile(
    r"(?:^|&)(?:utm_[^=]+|fbclid|gclid|igshid|ref|refsrc|from)=[^&]*"
)


def canonical_url(url: str) -> str:
    """추적 파라미터를 걷어낸 URL. 같은 기사를 다른 링크로 두 번 싣지 않기 위함."""
    url = url.strip()
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        part
        for part in query.split("&")
        if part and not _TRACKING_PARAMS.match("&" + part)
    ]
    return f"{base}?{'&'.join(kept)}" if kept else base


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: str = ""          # KST "YYYY-MM-DD HH:MM"
    summary: str = ""
    sector: str = ""
    risk: list[str] = field(default_factory=list)
    # 같은 사안을 다룬 다른 매체 기사들 (중복 묶기 결과)
    duplicates: list[dict[str, str]] = field(default_factory=list)
    query: str = ""              # 어떤 검색어로 걸렸는지 (디버깅용)
    language: str = "ko"          # 해외 영문 기사는 아침 분석에만 사용
    event_key: str = ""          # API 모델의 사건 판정; 규칙으로 생성하지 않음

    @property
    def id(self) -> str:
        """URL 기준 안정적인 식별자. 검토 페이지의 체크 상태를 이 값으로 추적합니다."""
        return hashlib.sha1(canonical_url(self.url).encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Article":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
