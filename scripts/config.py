"""설정 파일과 환경변수 로딩."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "news.yml"
DRAFT_DIR = ROOT / "data" / "drafts"
EXCLUSION_DIR = ROOT / "data" / "exclusions"
ARCHIVE_DIR = ROOT / "archive"


@dataclass
class Sector:
    id: str
    title: str
    must: list[str]
    any: list[str]
    queries: list[str]
    limit: int


class Config:
    def __init__(self, raw: dict[str, Any]):
        self._raw = raw
        limits = raw.get("limits", {})
        self.sectors = [
            Sector(
                id=s["id"],
                title=s["title"],
                must=s.get("must", []),
                any=s.get("any", []),
                queries=s.get("queries", []),
                limit=int(limits.get(s["id"], 5)),
            )
            for s in raw["sectors"]
        ]
        self.risk_keywords: list[str] = raw.get("risk_keywords", [])
        block = raw.get("blocklist", {}) or {}
        self.block_titles: list[str] = block.get("title_contains", []) or []
        self.block_sources: list[str] = block.get("sources", []) or []
        self.lookback_hours: int = int(raw.get("lookback_hours", 26))

    @property
    def sector_titles(self) -> dict[str, str]:
        return {s.id: s.title for s in self.sectors}

    def sector(self, sector_id: str) -> Sector | None:
        return next((s for s in self.sectors if s.id == sector_id), None)


def load_config(path: Path | None = None) -> Config:
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh))


def env(name: str, default: str = "") -> str:
    """환경변수. 값이 없으면 기본값. 앞뒤 공백은 항상 제거합니다."""
    return (os.environ.get(name) or default).strip()
