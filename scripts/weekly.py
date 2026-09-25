"""금요일 08:30 실행 — 그 주에 나간 동향을 한 장으로 요약해 보냅니다."""

from __future__ import annotations

import argparse
import html
import logging
import sys
from collections import Counter
from datetime import timedelta

from . import archive
from .config import DRAFT_DIR, EXCLUSION_DIR, load_config
from .digest import Digest, load_exclusions
from .models import now_kst
from .notify import send_email, send_digest as send_telegram
from .render import split_for_telegram
from .dedupe import dedupe
from .editorial import prepare

log = logging.getLogger(__name__)


def build(config, days: int = 7) -> tuple[str, int]:
    """(평문 요약, 포함된 날짜 수)."""
    today = now_kst().date()
    start = today - timedelta(days=days - 1)

    sector_counts: Counter[str] = Counter()
    risk_counter: Counter[str] = Counter()
    risk_articles: list[tuple[str, str, str, str]] = []   # 날짜, 제목, 매체, url
    days_used = 0
    candidates = []
    dates = {}

    for offset in range(days):
        date = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        path = DRAFT_DIR / f"{date}.json"
        if not path.exists():
            continue
        days_used += 1
        digest = Digest.load(path)
        excluded = load_exclusions(EXCLUSION_DIR / f"{date}.json")
        for title, items in digest.by_sector(config, excluded):
            for article in items:
                candidates.append(article)
                dates.setdefault(article.id, date)

    # One representative per event across dates, sources, and sections; counts and
    # highlights use the same filtered set rather than every archived risk keyword.
    titles = {s.id: s.title for s in config.sectors}
    for article in dedupe(prepare(candidates, config)):
        sector_counts[titles[article.sector]] += 1
        if article.risk:
            risk_counter.update(article.risk)
            risk_articles.append((dates[article.id], article.title, article.source, article.url))

    lines = [
        f"한국석유관리원 주간 언론동향 ({start:%m월 %d일} ~ {today:%m월 %d일})",
        "",
    ]
    if not days_used:
        lines.append("이번 주 발송된 동향이 없습니다.")
        return "\n".join(lines) + "\n", 0

    total = sum(sector_counts.values())
    lines += [f"[집계] {days_used}일간 중복 제외 {total}건", ""]
    for title, count in sector_counts.most_common():
        lines.append(f"· {title} {count}건")

    if risk_counter:
        top = ", ".join(f"{kw} {n}회" for kw, n in risk_counter.most_common(6))
        lines += ["", f"[주의 키워드] {top}", ""]
        # 같은 기사가 여러 날 잡힐 수 있어 URL 기준으로 한 번씩만
        seen: set[str] = set()
        for date, title, source, url in risk_articles:
            if url in seen:
                continue
            seen.add(url)
            lines.append(f"· ({date[5:]}) {title} / {source}")
            lines.append(f"  {url}")

    return "\n".join(lines).rstrip() + "\n", days_used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="주간 언론동향 롤업")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    config = load_config()
    text, days_used = build(config)

    if args.dry_run:
        print("\n" + text)
        return 0
    if not days_used:
        log.info("이번 주 데이터가 없어 건너뜁니다")
        return 0

    send_telegram(split_for_telegram(text))
    try:
        body = (
            '<pre style="font-family:inherit;white-space:pre-wrap;font-size:14px">'
            f"{html.escape(text)}</pre>"
        )
        send_email(f"[주간 언론동향] {now_kst():%Y-%m-%d}", body, text)
    except Exception as exc:                          # noqa: BLE001
        log.error("주간 이메일 발송 실패: %s", exc)

    archive.rebuild_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
