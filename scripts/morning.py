"""05:17 예약: 누적 기사만 읽어 하루 한 번 분석하고 검토 초안을 저장한다."""
import argparse
import logging
from datetime import timedelta

from . import alerts, analysis, rolling, storage, preferences
from .collect import notify_reviewer
from .config import DRAFT_DIR, load_config
from .dedupe import dedupe
from .digest import Digest
from .editorial import prepare
from .market import market_brief
from .models import now_kst
from .render import render_plain

log = logging.getLogger(__name__)


def build(config, state, now, previous=None, persist=None, exclude_words=None):
    raw = rolling.daily_articles(state, now)
    raw = [a for a in raw if not any(w.casefold() in a.title.casefold() for w in (exclude_words or []))]
    if alerts.load_rules().get("ai_screening"):
        # 예약 선별 지연이 조간 전체를 막지 않도록 미판정 기사는 조간 AI가 직접 판단한다.
        # 기존 명시적 무관 판정만 제외한다. 기사 시각은 daily_articles의 24시간 제한 적용.
        decisions = {d['id']: d for d in state.get('screening', {}).get('checked', [])}
        pending = sum(a.id not in decisions for a in raw)
        raw = [a for a in raw if decisions.get(a.id, {}).get('relevant') is not False]
        if pending:
            log.info("미선별 누적 기사 %d건은 조간 AI가 직접 관련성 판단", pending)
    articles = dedupe(prepare(raw, config))
    fallback_notice = ""
    try:
        report = analysis.analyze(articles, previous, state, persist)
    except RuntimeError:
        # 기사 신선도·관련성·담당자 제외 검사는 그대로 유지한다.
        # 원문 예외에는 인증정보가 있을 수 있어 고정 문구만 공개한다.
        report = {}
        fallback_notice = "AI 분석 실패로 기본 스크랩을 보냅니다. 관련성·중복 제거 규칙을 적용했으며 AI 분석은 포함하지 않았습니다."
        log.warning(fallback_notice)
    if report:
        report["pool_started_at"] = state["pool"]["started_at"]
        report["pool_updated_at"] = state["pool"]["updated_at"]
    return Digest(date=now.strftime("%Y-%m-%d"), generated_at=now.strftime("%Y-%m-%d %H:%M"),
                  articles=articles, analysis=report, fallback_notice=fallback_notice,
                  market=[q.__dict__ for q in market_brief()],
                  sectors=[{"id": s.id, "title": s.title, "limit": s.limit} for s in config.sectors],
                  collection_stats={"raw": len(raw), "fresh": len(raw), "classified": len(raw),
                                    "representatives": len(articles), "duplicates": sum(len(a.duplicates) for a in articles)})


def main(argv=None):
    parser = argparse.ArgumentParser(description="누적 기사 AI 종합 분석")
    parser.add_argument("--dry-run", action="store_true", help="API 분석은 실행, 저장·알림 없음")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--refresh-analysis", action="store_true", help="dry-run에서 저장 초안을 재사용하지 않고 분석 검증")
    args = parser.parse_args(argv)
    if args.refresh_analysis and not args.dry_run:
        parser.error("--refresh-analysis requires --dry-run")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config, now = load_config(), now_kst()
    if not storage.enabled():
        raise RuntimeError("누적 기사 분석에는 기존 Supabase 연결이 필요합니다")
    date = now.strftime("%Y-%m-%d")
    existing = storage.read("news_drafts", date)
    if not args.refresh_analysis and existing and (existing.get("analysis", {}).get("version") == 1 or existing.get("fallback_notice")):
        # 워크플로 재실행은 API 재호출·담당자 검토 덮어쓰기를 하지 않는다.
        digest = Digest.from_dict(existing)
        if not args.dry_run:
            digest.save(DRAFT_DIR / f"{date}.json")
        print(render_plain(digest, config))
        return 0
    yesterday = (now-timedelta(days=1)).strftime("%Y-%m-%d")
    old = storage.read("news_drafts", yesterday)
    previous = (old or {}).get("analysis", {}).get("issues", [])
    prefs = preferences.load()
    words = prefs.get('global', prefs.get('chats', {}).get(prefs.get('owner'), {})).get('exclude', [])
    digest = build(config, alerts.read_state(), now, previous, alerts.save_state, words)
    if args.dry_run:
        print(render_plain(digest, config))
        return 0
    storage.save_draft(digest)
    digest.save(DRAFT_DIR / f"{date}.json")
    if not args.no_notify:
        notify_reviewer(digest, config)
    log.info("누적 기사 %d건 → 핵심 이슈 %d개, 기본 스크랩 %s", len(digest.articles),
             len(digest.analysis.get("issues", [])), bool(digest.fallback_notice))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # 인증 헤더나 API 응답 원문은 로그에 남기지 않는다.
        log.error("아침 AI 분석 실패 (%s). API 키·무료 한도·수집 상태를 확인하세요.", type(exc).__name__)
        raise SystemExit(1)
