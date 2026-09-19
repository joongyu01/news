"""15분마다 긴급 보고 후보를 확인. AI 호출·Git 커밋 없이 Telegram으로 알림."""
from __future__ import annotations

import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import yaml

from . import storage
from .classify import is_blocked
from .config import ROOT, env, load_config
from .dedupe import similarity
from .models import Article, now_kst
from .notify import send_telegram
from .sources import KST, fetch_google_news, fetch_naver, naver_available

log = logging.getLogger(__name__)


def load_rules():
    with open(ROOT / "config" / "alerts.yml", encoding="utf-8") as fh:
        rules = yaml.safe_load(fh)
    if not 1 <= rules["max_per_run"] <= 10 or not rules["queries"]:
        raise ValueError("Invalid urgent alert limits")
    # 설정 오류는 수집/발송 전에 드러나야 합니다.
    re.compile(rules["exclude_title"])
    for rule in rules["rules"]:
        re.compile(rule["scope"])
        re.compile(rule["trigger"])
    return rules


def urgent_reason(article, rules):
    title = article.title
    if re.search(rules["exclude_title"], title, re.I):
        return None
    for rule in rules["rules"]:
        if re.search(rule["scope"], title, re.I) and re.search(rule["trigger"], title, re.I):
            return rule
    return None


def published_at(article):
    try:
        return datetime.strptime(article.published, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def gather(rules):
    use_naver = naver_available()

    def fetch(query):
        if use_naver:
            try:
                return fetch_naver(query), True
            except Exception:
                log.warning("네이버 검색 실패 — Google RSS 대체")
        try:
            return fetch_google_news(f"{query} when:{rules['lookback_hours']}h"), True
        except Exception as exc:
            # 예외 문자열에 인증 정보가 포함될 수 있어 타입만 기록합니다.
            log.warning("긴급 검색 실패: %s (%s)", query, type(exc).__name__)
            return [], False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, rules["queries"]))
    if not any(ok for _, ok in results):
        raise RuntimeError("모든 긴급 뉴스 검색 실패")
    log.info("검색 성공 %d/%d", sum(ok for _, ok in results), len(results))
    return [a for articles, _ in results for a in articles]


def read_state():
    if not storage.enabled():
        raise RuntimeError("긴급 알림은 Supabase 설정이 필요합니다")
    rows = storage.request("GET", "news_alert_state", params={
        "id": "eq.urgent", "select": "payload",
    }).json()
    if not rows:
        return None
    state = rows[0]["payload"]
    if state.get("version") != 1 or not isinstance(state.get("sent"), list):
        raise RuntimeError("긴급 알림 기록 형식 오류")
    datetime.fromisoformat(state["started_at"])
    return state


def save_state(state):
    storage.request("POST", "news_alert_state", params={"on_conflict": "id"}, json={
        "id": "urgent", "payload": state, "updated_at": now_kst().isoformat(),
    })


def trim_history(state, rules, now):
    state["sent"] = [old for old in state["sent"]
                     if datetime.fromisoformat(old["sent_at"]) >= now - timedelta(days=rules["history_days"])][-rules["max_history"]:]


def already_sent(article, reason, history, threshold):
    numbers = re.findall(r"\d+", article.title)
    return any(
        article.id == old["id"] or (
            reason["id"] == old["rule"]
            and numbers == re.findall(r"\d+", old["title"])
            and similarity(article.title, old["title"]) >= threshold
        ) for old in history
    )


def select_alerts(articles, state, rules, now, config):
    cutoff = max(now - timedelta(hours=rules["lookback_hours"]),
                 datetime.fromisoformat(state["started_at"]))
    selected = []
    known = list(state["sent"])
    for article in sorted(articles, key=lambda a: a.published, reverse=True):
        published = published_at(article)
        if not published or not cutoff <= published <= now + timedelta(minutes=5):
            continue
        if urlsplit(article.url).scheme not in ("http", "https") or not urlsplit(article.url).netloc:
            continue
        if is_blocked(article, config):
            continue
        reason = urgent_reason(article, rules)
        if not reason or already_sent(article, reason, known, rules["similarity_threshold"]):
            continue
        selected.append((article, reason))
        known.append({"id": article.id, "title": article.title, "rule": reason["id"]})
        if len(selected) >= rules["max_per_run"]:
            break
    return selected


def message(article, reason):
    # Telegram 한 메시지 한도보다 짧게 유지하고 원문 링크를 함께 보냅니다.
    return (f"🚨 긴급 보고 후보 | {reason['label']}\n\n"
            f"{article.title[:500]}\n\n"
            f"매체: {article.source[:100]}\n보도 시각: {article.published} KST\n"
            f"확인할 점: {reason['action']}\n\n{article.url[:2500]}\n\n"
            "제목 기준 자동 선별입니다. 보고 전 원문과 공식 발표를 확인해주세요.")


def run(rules, *, dry_run=False, send_test=False):
    if not rules["enabled"]:
        log.info("긴급 알림 비활성화")
        return 0
    if not dry_run and (not env("TELEGRAM_BOT_TOKEN") or not env("TELEGRAM_CHAT_ID")):
        raise RuntimeError("Telegram 토큰과 수신 대화가 필요합니다")
    now = now_kst()
    # DB 접근 실패 시 기록 없이 발송하지 않습니다.
    state = read_state()
    if state is None:
        state = {"version": 1,
                 "started_at": (now - timedelta(minutes=rules["initial_lookback_minutes"])).isoformat(),
                 "sent": []}
    trim_history(state, rules, now)
    articles = gather(rules)
    candidates = select_alerts(articles, state, rules, now, load_config())
    log.info("수집 %d건 · 신규 긴급 보고 후보 %d건", len(articles), len(candidates))
    if dry_run:
        for article, reason in candidates:
            log.info("[시험] %s: %s", reason["label"], article.title)
        return len(candidates)
    # 첫 발송 전 저장 권한까지 검증. 발송별 저장으로 부분 실패도 재처리 가능.
    save_state(state)
    for article, reason in candidates:
        if send_telegram([message(article, reason)]) != 1:
            raise RuntimeError("긴급 Telegram 발송 실패")
        state["sent"].append({"id": article.id, "title": article.title[:500],
                              "rule": reason["id"], "sent_at": now.isoformat()})
        trim_history(state, rules, now)
        save_state(state)
    state["last_checked_at"] = now.isoformat()
    state["last_collected"] = len(articles)
    state["last_sent"] = len(candidates)
    save_state(state)
    if send_test:
        if send_telegram(["✅ 긴급 뉴스 알림 가동 확인\n24시간, 15분 간격으로 확인합니다.\n"
                          "석유관리원 중대 보도 · 석유/가스 사고 · 공급 차질 · 긴급 정책\n"
                          "해당 소식이 없으면 알림을 보내지 않습니다.\n"
                          "AI 호출 없이 선별하며, 검색 반영·예약 실행 지연이 있을 수 있습니다."]) != 1:
            raise RuntimeError("가동 확인 메시지 실패")
    log.info("긴급 알림 %d건 발송 완료", len(candidates))
    return len(candidates)


def main(argv=None):
    parser = argparse.ArgumentParser(description="긴급 보고 후보 알림")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        run(load_rules(), dry_run=args.dry_run, send_test=args.send_test)
    except Exception as exc:
        log.error("긴급 알림 중단 (%s). 설정·소스·DB 연결을 확인하세요.", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
