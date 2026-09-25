"""15분 수집과 주간 30분 AI 선별·묶음 알림을 별도 작업으로 실행."""
from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import yaml

from . import storage, preferences, rolling, screening
from .classify import is_blocked
from .config import ROOT, env, load_config
from .dedupe import similarity
from .models import Article, now_kst
from .notify import send_telegram
from .render import article_anchor
from .sources import KST, fetch_google_news, fetch_naver, fetch_trade_feeds, naver_available

log = logging.getLogger(__name__)


def load_rules():
    with open(ROOT / "config" / "alerts.yml", encoding="utf-8") as fh:
        rules = yaml.safe_load(fh)
    if not 1 <= rules["max_per_run"] <= 10 or not rules["queries"]:
        raise ValueError("Invalid urgent alert limits")
    # 설정 오류는 수집/발송 전에 드러나야 합니다.
    re.compile(rules["exclude_title"])
    re.compile(rules.get("topic_exclude_title", r"(?!)"))
    for rule in [*rules["rules"], *rules.get("topics", [])]:
        re.compile(rule["scope"])
        re.compile(rule["trigger"])
    return rules


def urgent_reason(article, rules, options=None):
    title = article.title
    if options and any(word.casefold() in title.casefold() for word in options.get("exclude", [])):
        return None
    if not re.search(rules.get("topic_exclude_title", r"(?!)"), title, re.I):
        for topic in rules.get("topics", []):
            if re.search(topic["scope"], title, re.I) and re.search(topic["trigger"], title, re.I):
                return topic
    if re.search(rules["exclude_title"], title, re.I):
        return None
    if rules.get("topics_delivery") != "daily" and options and any(word.casefold() in title.casefold() for word in options.get("watch", [])):
        return {"id": "watch", "label": "관심 키워드", "action": "설정한 관심 키워드가 포함된 소식입니다"}
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
    articles = [a for articles, _ in results for a in articles]
    if rules.get("include_trade"):
        articles.extend(fetch_trade_feeds())
    for query in rules.get("foreign_queries", []):
        try:
            articles.extend(fetch_google_news(f"{query} when:26h", language="en"))
        except Exception:
            log.warning("해외 뉴스 검색 실패 — 국내 수집은 유지")
    return articles


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


def topic_key(article, reason):
    """Optional strict mode groups the same facility/region/type for 24 hours."""
    title = article.title
    regions = re.findall(r"호르무즈|사우디|이란|미국|러시아|울산|여수|대산|인천|부산|대구|광주|대전|포항|구미|군산|익산|영천", title)
    facilities = re.findall(r"석유관리원|정유공장|저유소|송유관|유조선|가스충전소|주유소|LPG|비축유|최고가격제|가짜석유", title, re.I)
    events = re.findall(r"화재|폭발|누출|유출|피격|봉쇄|중단|방출|적발|구속|기소", title)
    if not regions or not facilities or not events:
        return ""
    return '|'.join([reason['id'], ','.join(sorted(set(regions))),
                     ','.join(sorted(set(facilities))), ','.join(sorted(set(events)))])


def select_alerts(articles, state, rules, now, config, options=None):
    cutoff = max(now - timedelta(hours=rules["lookback_hours"]),
                 datetime.fromisoformat(state["started_at"]))
    selected = []
    known = list(state["sent"])
    for article in sorted(articles, key=lambda a: a.published, reverse=True):
        if article.language != "ko":
            continue  # 해외 뉴스는 아침 분석 전용
        published = published_at(article)
        if not published or not cutoff <= published <= now + timedelta(minutes=5):
            continue
        if urlsplit(article.url).scheme not in ("http", "https") or not urlsplit(article.url).netloc:
            continue
        if is_blocked(article, config):
            continue
        decision = next((d for d in state.get("screening", {}).get("checked", []) if d["id"] == article.id), None)
        if rules.get("ai_screening"):
            if not decision:
                continue
            if not decision["urgent"]:
                continue
            if any(old.get("ai_event") == decision["event_key"] and
                   datetime.fromisoformat(old["sent_at"]) >= now-timedelta(hours=24) for old in known):
                continue
        reason = urgent_reason(article, rules, options)
        if reason and reason.get("kind") == "topic" and rules.get("topics_delivery") == "daily":
            # 관심 주제라도 실제 사고·확정 정책 규칙에 해당하면 즉시 알린다.
            reason = urgent_reason(article, {**rules, "topics": []}, options)
        if not reason or already_sent(article, reason, known, rules["similarity_threshold"]):
            continue
        if options and options.get("mode") == "strict":
            if reason.get("kind") != "topic" and re.search(r"표창|수상|인터뷰|분석|파장|기대|검토|시행.*(?:후|영향)|방출.*(?:안|않)", article.title):
                continue
            topic = topic_key(article, reason)
            if topic and any(old.get("topic") == topic and
                             datetime.fromisoformat(old["sent_at"]) >= now-timedelta(hours=24) for old in known):
                continue
        selected.append((article, reason))
        known.append({"id": article.id, "title": article.title, "rule": reason["id"],
                      "topic": topic_key(article, reason), "sent_at": now.isoformat(),
                      "ai_event": decision["event_key"] if decision else ""})
        if len(selected) >= rules["max_per_run"]:
            break
    return selected


def message(article, reason):
    # Telegram 한 메시지 한도보다 짧게 유지하고 원문 링크를 함께 보냅니다.
    heading = "📰 관심 주제 업데이트" if reason.get("kind") == "topic" else "🚨 긴급 보고 후보"
    return (f"{heading} | {reason['label']}\n\n"
            f"{article.title[:500]}\n\n"
            f"매체: {article.source[:100]}\n보도 시각: {article.published} KST\n"
            f"확인할 점: {reason['action']}\n\n{article.url[:2500]}\n\n"
            "제목 기준 자동 선별입니다. 보고 전 원문과 공식 발표를 확인해주세요.")


def html_message(article, reason):
    return (f"🚨 <b>{html.escape(reason['label'])}</b>\n\n{article_anchor(article)}\n\n"
            f"보도 시각: {html.escape(article.published)} KST\n"
            f"확인할 점: {html.escape(reason['action'])}\n\n"
            "제목 기준 자동 선별입니다. 보고 전 원문과 공식 발표를 확인해주세요.")


def bundled_message(items, now):
    parts = [f"🚨 <b>긴급 뉴스 {len(items)}건</b> · {now.strftime('%m/%d %H:%M')} KST"]
    for n, (article, reason) in enumerate(items, 1):
        linked = Article.from_dict(article.to_dict())
        linked.title, linked.source = linked.title[:240], linked.source[:60]
        parts.append(f"<b>{n}. {html.escape(reason['label'][:60])}</b>\n{article_anchor(linked)}\n"
                     f"확인할 점: {html.escape(reason['action'][:120])}")
    parts.append("제목·매체 요약을 기준으로 선별했습니다. 중요한 사실은 원문을 확인해 주세요.")
    return "\n\n".join(parts)


def run(rules, *, dry_run=False, send_test=False, collect_only=False, screen_only=False, no_send=False):
    if not rules["enabled"]:
        log.info("긴급 알림 비활성화")
        return 0
    if not dry_run and not collect_only and (not env("TELEGRAM_BOT_TOKEN") or not env("TELEGRAM_CHAT_ID")):
        raise RuntimeError("Telegram 토큰과 수신 대화가 필요합니다")
    now = now_kst()
    start_minute = 317 if collect_only else 360
    if now.hour * 60 + now.minute < start_minute:
        log.info("휴식 시간 — 수집·AI·알림 생략")
        return 0
    # DB 접근 실패 시 기록 없이 발송하지 않습니다.
    state = read_state()
    if state is None:
        state = {"version": 1,
                 "started_at": (now - timedelta(minutes=rules["initial_lookback_minutes"])).isoformat(),
                 "sent": []}
    trim_history(state, rules, now)
    prefs = preferences.load()
    config = load_config()
    queries = list(dict.fromkeys([*rules["queries"],
                                *(q for sector in config.sectors for q in sector.queries)]))
    words = sorted({word for opts in prefs["chats"].values() for word in opts.get("watch", [])})
    if words:
        # One extra query regardless of number of rooms; quote metacharacters.
        queries.append(' OR '.join('"'+re.sub(r'["\\\r\n]', ' ', word)+'"' for word in words))
    if screen_only:
        articles = rolling.daily_articles(state, now)
    else:
        articles = gather({**rules, "queries": queries, "include_trade": True,
                           "foreign_queries": config._raw.get("foreign_queries", []),
                           "lookback_hours": max(26, rules["lookback_hours"])})
        rolling.accumulate(state, articles, now, config)
    # 알림을 꺼두었거나 전송이 실패해도 아침 분석용 수집은 유지한다.
    if not dry_run:
        save_state(state)
    if collect_only:
        log.info("기사 수집·저장 완료: %d건. AI 호출·발송 없음", len(articles))
        return 0
    if not dry_run:
        if rules.get("ai_screening"):
            screening.run(state, now, save_state, force=no_send)
            articles = screening.approved(state, rolling.daily_articles(state, now), urgent=True)
    deliveries = []
    for chat, options in prefs["chats"].items():
        if not options.get("urgent", True) or preferences.quiet_now(options, now):
            continue
        history = [old for old in state["sent"] if old.get("chat", prefs["owner"]) == chat]
        today_count = sum(datetime.fromisoformat(old["sent_at"]).astimezone(KST).date() == now.date() for old in history)
        if chat == prefs['owner']:
            today_count += sum(datetime.fromisoformat(old['sent_at']).astimezone(KST).date() == now.date()
                               for old in prefs.get('spark_recent', []))
        daily_limit = options.get("limit", 0)
        per_run = min(3, rules["max_per_run"])
        remaining = min(per_run, max(0, daily_limit-today_count)) if daily_limit else per_run
        if not remaining:
            continue
        candidates = select_alerts(articles, {**state, "sent": history},
                                   {**rules, "max_per_run": remaining}, now, config, options)
        deliveries.extend((chat, a, reason) for a, reason in candidates)
    log.info("수집 %d건 · 신규 긴급 보고 후보 %d건(수신방별)", len(articles), len(deliveries))
    if no_send:
        log.info("검증 모드 — AI 판정은 저장, 실제 알림·발송 이력은 생략")
        return len(deliveries)
    if dry_run:
        for chat, article, reason in deliveries:
            log.info("[시험] %s: %s", reason["label"], article.title)
        return len(deliveries)
    # 첫 발송 전 저장 권한까지 검증. 발송별 저장으로 부분 실패도 재처리 가능.
    save_state(state)
    failures = 0
    grouped = {}
    for chat, article, reason in deliveries:
        grouped.setdefault(chat, []).append((article, reason))
    for chat, items in grouped.items():
        try:
            if send_telegram([bundled_message(items, now)], chat_id=chat, parse_mode="HTML") != 1:
                raise RuntimeError("긴급 Telegram 발송 실패")
        except Exception:
            failures += len(items)
            continue
        for article, reason in items:
            state["sent"].append({"id": article.id, "title": article.title[:500], "chat": chat,
                                  "topic": topic_key(article, reason),
                                  "ai_event": next((d["event_key"] for d in state.get("screening", {}).get("checked", [])
                                                    if d["id"] == article.id), ""),
                                  "rule": reason["id"], "sent_at": now.isoformat()})
        trim_history(state, rules, now)
        save_state(state)
    state["last_checked_at"] = now.isoformat()
    state["last_collected"] = len(articles)
    state["last_sent"] = len(deliveries)-failures
    state["last_candidates"] = len(deliveries)
    state["last_failures"] = failures
    state["last_completed_at"] = now_kst().isoformat()
    save_state(state)
    if failures:
        raise RuntimeError("일부 구독방의 긴급 발송 실패")
    if send_test:
        if send_telegram(["✅ 긴급 뉴스 알림 가동 확인\n05:17~23:59 수집, 주간 30분 AI 선별입니다.\n"
                          "석유관리원 중대 보도 · 석유/가스 사고 · 공급 차질 · 긴급 정책\n"
                          "해당 소식이 없으면 알림을 보내지 않습니다.\n"
                          "06:00~23:30에 30분마다 새 기사를 AI로 선별하며, 예약 실행 지연이 있을 수 있습니다."]) != 1:
            raise RuntimeError("가동 확인 메시지 실패")
    log.info("긴급 알림 %d건 발송 완료", len(deliveries))
    return len(deliveries)


def main(argv=None):
    parser = argparse.ArgumentParser(description="긴급 보고 후보 알림")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--collect-only", action="store_true")
    mode.add_argument("--screen-only", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        run(load_rules(), dry_run=args.dry_run, send_test=args.send_test,
            collect_only=args.collect_only, screen_only=args.screen_only, no_send=args.no_send)
    except Exception as exc:
        log.error("긴급 알림 중단 (%s). 설정·소스·DB 연결을 확인하세요.", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
