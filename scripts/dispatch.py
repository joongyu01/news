"""08:00 실행 — 검토 결과를 반영한 최종본을 발송하고 아카이브에 남깁니다."""

from __future__ import annotations

import argparse
import logging
import sys

from . import archive, storage
from .config import DRAFT_DIR, EXCLUSION_DIR, load_config
from .digest import Digest, load_exclusions
from .models import now_kst
from .notify import send_email, send_digest as send_telegram
from .render import render_email, render_markdown, render_plain, split_for_telegram

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="일일언론동향 발송")
    parser.add_argument("--date", help="발송할 날짜 (기본: 오늘, KST)")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 발송 없이 최종본만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    date = args.date or now_kst().strftime("%Y-%m-%d")

    draft_path = DRAFT_DIR / f"{date}.json"
    try:
        use_supabase = storage.enabled()
        remote_draft = storage.read("news_drafts", date) if use_supabase else None
        remote_exclusions = storage.read("news_exclusions", date) if use_supabase else None
    except Exception as exc:
        log.error("Supabase 조회 실패 — 검토 결과 없이 발송하지 않습니다: %s", exc)
        return 1
    if (use_supabase and remote_draft is None) or (not use_supabase and not draft_path.exists()):
        # 수집이 실패했으면 빈 동향을 보내지 않고 조용히 멈춥니다.
        log.error("초안이 없습니다: %s — 06:40 수집 작업 로그를 확인하세요", draft_path)
        return 1

    config = load_config()
    digest = Digest.from_dict(remote_draft) if use_supabase else Digest.load(draft_path)
    excluded = (set((remote_exclusions or {}).get("excluded", [])) if use_supabase
                else load_exclusions(EXCLUSION_DIR / f"{date}.json"))

    total = len(digest.articles)
    shown = sum(len(items) for _, items in digest.by_sector(config, excluded))
    log.info("초안 %d건 · 담당자 제외 %d건 · 발송 %d건", total, len(excluded), shown)

    if shown == 0:
        log.error("발송할 기사가 없습니다 — 중단합니다")
        return 1

    plain = render_plain(digest, config, excluded)
    html_body = render_email(digest, config, excluded)
    markdown = render_markdown(digest, config, excluded)
    subject = f"[언론동향] {date}"

    if args.dry_run:
        print("\n" + plain)
        return 0

    chunks = split_for_telegram(plain)
    sent = send_telegram(chunks)
    log.info("텔레그램 %d개 메시지 발송", sent)

    count = 0
    try:
        count = send_email(subject, html_body, plain)
        log.info("이메일 %d명 발송", count)
    except Exception as exc:                          # noqa: BLE001
        # 텔레그램이 이미 나갔으면 담당자는 동향을 받은 상태입니다.
        # 이메일 실패로 전체를 실패시키면 아카이브가 안 남으므로 경고만 남깁니다.
        log.error("이메일 발송 실패: %s", exc)

    if not sent and not count:
        # 설정이 비어 있으면 send_* 는 예외 대신 0을 돌려줍니다. 그대로 두면
        # 아무에게도 안 간 동향이 아카이브에 남고 Actions 는 초록불이 뜹니다.
        # 조용히 잘못되는 쪽이 더 나쁘므로 여기서 실패로 끊습니다.
        log.error(
            "텔레그램·이메일 어느 쪽으로도 발송되지 않았습니다 — "
            "아카이브를 남기지 않고 중단합니다. Secret 설정을 확인하세요."
        )
        return 1

    path = archive.write(date, markdown)
    archive.rebuild_index()
    log.info("아카이브 저장: %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
