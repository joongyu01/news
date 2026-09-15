"""06:40 실행 — 뉴스를 모아 검토용 초안을 만듭니다.

결과물은 data/drafts/YYYY-MM-DD.json 한 파일입니다. 08:00 발송 작업과
검토 페이지가 모두 이 파일을 봅니다.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .classify import classify_all
from .config import DRAFT_DIR, env, load_config
from .dedupe import dedupe
from .digest import Digest
from .market import market_brief
from .models import Article, now_kst
from .notify import send_telegram
from .sources import (
    is_fresh,
    fetch_google_news,
    fetch_naver,
    fetch_trade_feeds,
    naver_available,
)

log = logging.getLogger(__name__)


def gather(config) -> list[Article]:
    """설정된 모든 검색어와 업계지 RSS를 훑습니다.

    소스 하나가 죽어도 그날 동향은 나가야 하므로 실패는 경고만 남기고 넘어갑니다.
    """
    use_naver = naver_available()
    log.info("주 수집원: %s", "네이버 검색 API" if use_naver else "구글뉴스 RSS")

    collected: list[Article] = []
    for sector in config.sectors:
        for query in sector.queries:
            try:
                found = fetch_naver(query) if use_naver else fetch_google_news(query)
            except Exception as exc:                  # noqa: BLE001
                log.warning("검색 실패 [%s] %s: %s", sector.id, query, exc)
                continue
            log.info("  %-24s %2d건", query, len(found))
            collected.extend(found)

    trade = fetch_trade_feeds()
    log.info("  업계지 RSS             %2d건", len(trade))
    collected.extend(trade)
    return collected


def build(config) -> Digest:
    raw = gather(config)
    fresh = [a for a in raw if is_fresh(a.published, config.lookback_hours)]
    log.info("수집 %d건 → 최근 %d시간 %d건", len(raw), config.lookback_hours, len(fresh))

    classified = classify_all(fresh, config)
    log.info("섹터 분류 통과 %d건", len(classified))

    # 리스크 기사를 위로, 그 안에서는 최신순.
    # 파이썬 정렬은 안정적이므로 뒤 기준부터 차례로 걸면 됩니다.
    # 이 순서가 중복 묶기에서 '어느 기사를 대표로 남길지'도 결정합니다.
    classified.sort(key=lambda a: a.published, reverse=True)
    classified.sort(key=lambda a: bool(a.risk), reverse=True)

    merged = dedupe(classified)
    log.info("중복 묶기 후 %d건", len(merged))

    now = now_kst()
    digest = Digest(
        date=now.strftime("%Y-%m-%d"),
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        articles=merged,
        market=[q.__dict__ for q in market_brief()],
        sectors=[
            {"id": s.id, "title": s.title, "limit": s.limit} for s in config.sectors
        ],
    )
    for sector in config.sectors:
        count = sum(1 for a in merged if a.sector == sector.id)
        log.info("  [%s] %d건 (상한 %d)", sector.title, count, sector.limit)
    return digest


def notify_reviewer(digest: Digest, config) -> None:
    """담당자에게만 '검토해 주세요' 알림. 전 직원 발송은 08:00 작업이 합니다."""
    review_url = env("REVIEW_URL")
    if not review_url:
        return
    shown = sum(len(items) for _, items in digest.by_sector(config))
    risky = len(digest.risk_articles())
    lines = [
        f"📋 {digest.date} 동향 초안이 준비됐습니다.",
        f"기사 {shown}건" + (f" · ⚠️ 주의 {risky}건" if risky else ""),
        "",
        "빼실 기사를 눌러 제외하신 뒤 두시면,",
        "08:00에 최종본이 발송됩니다.",
        "",
        review_url,
    ]
    try:
        send_telegram(["\n".join(lines)])
    except Exception as exc:                          # noqa: BLE001
        log.warning("검토 알림 발송 실패: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="일일언론동향 초안 수집")
    parser.add_argument("--dry-run", action="store_true",
                        help="파일로 저장하지 않고 화면에만 출력")
    parser.add_argument("--no-notify", action="store_true",
                        help="검토 알림 텔레그램을 보내지 않음")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    config = load_config()
    digest = build(config)

    if args.dry_run:
        from .render import render_plain

        print("\n" + render_plain(digest, config))
        return 0

    path = DRAFT_DIR / f"{digest.date}.json"
    digest.save(path)
    log.info("초안 저장: %s", path.relative_to(path.parents[2]))

    if not args.no_notify:
        notify_reviewer(digest, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
