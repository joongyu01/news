"""archive/ 디렉터리 관리 — 발송한 동향을 날짜별로 쌓고 목차를 다시 씁니다."""

from __future__ import annotations

import re
from pathlib import Path

from .config import ARCHIVE_DIR

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:-(\d+))?\.md$")


def archive_path(date: str) -> Path:
    """2026-09-16 -> archive/2026-09/2026-09-16.md"""
    return ARCHIVE_DIR / date[:7] / f"{date}.md"


def write(date: str, markdown: str) -> Path:
    path = archive_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def entries() -> list[tuple[str, Path]]:
    """(정렬키, 파일경로) 최신순. 목차 생성과 주간 롤업이 함께 씁니다."""
    found: list[tuple[str, Path]] = []
    for path in ARCHIVE_DIR.glob("*/*.md"):
        match = DATE_RE.match(path.name)
        if match:
            found.append((path.stem, path))
    return sorted(found, key=lambda item: item[0], reverse=True)


def rebuild_index() -> Path:
    """archive/README.md 목차를 현재 파일 목록에 맞춰 다시 생성."""
    lines = [
        "# 일일언론동향 아카이브",
        "",
        "매일 08:00에 발송된 동향이 여기 쌓입니다. 이 목차는 자동 생성되므로",
        "직접 고치지 마세요 — 다음 발송 때 덮어써집니다.",
        "",
    ]
    current_month = ""
    for stem, path in entries():
        month = stem[:7]
        if month != current_month:
            year, mon = month.split("-")
            lines += ["", f"## {year}년 {int(mon)}월", ""]
            current_month = month
        rel = path.relative_to(ARCHIVE_DIR).as_posix()
        label = stem if len(stem) == 10 else f"{stem[:10]} ({stem[11:]})"
        lines.append(f"- [{label}]({rel})")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    index = ARCHIVE_DIR / "README.md"
    index.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return index
