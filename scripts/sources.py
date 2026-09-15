"""뉴스 수집 어댑터.

세 갈래로 모읍니다.
  1. 네이버 뉴스 검색 API  — 키가 있으면 주 소스. 기존 동향과 같은 n.news.naver.com 링크.
  2. 구글뉴스 RSS          — 키 없이 동작. 네이버 키가 없을 때의 대체재.
  3. 업계지 RSS            — 에너지신문·투데이에너지 등. 석유관리원 보도자료가 주로 여기 실립니다.

어느 하나가 죽어도 나머지로 그날 동향은 나가야 하므로, 소스별 실패는
로그만 남기고 삼킵니다.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import feedparser
import requests

from .config import env
from .models import Article

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
UA = "Mozilla/5.0 (compatible; kpetro-news-digest/1.0; +https://github.com/joongyu01/news)"
TIMEOUT = 20

# 네이버 API는 매체명을 주지 않아 도메인으로 역추적합니다.
# 없는 도메인은 호스트명을 그대로 씁니다.
DOMAIN_TO_OUTLET = {
    "yna.co.kr": "연합뉴스", "yonhapnews.co.kr": "연합뉴스",
    "chosun.com": "조선일보", "biz.chosun.com": "조선비즈",
    "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문",
    "mk.co.kr": "매일경제", "hankyung.com": "한국경제",
    "sedaily.com": "서울경제", "edaily.co.kr": "이데일리",
    "fnnews.com": "파이낸셜뉴스", "mt.co.kr": "머니투데이",
    "asiae.co.kr": "아시아경제", "heraldcorp.com": "헤럴드경제",
    "segye.com": "세계일보", "kmib.co.kr": "국민일보",
    "seoul.co.kr": "서울신문", "hankookilbo.com": "한국일보",
    "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "news1.kr": "뉴스1", "nocutnews.co.kr": "노컷뉴스",
    "ytn.co.kr": "YTN", "sbs.co.kr": "SBS", "imbc.com": "MBC",
    "kbs.co.kr": "KBS", "jtbc.co.kr": "JTBC", "mbn.co.kr": "MBN",
    "etnews.com": "전자신문", "dt.co.kr": "디지털타임스",
    "zdnet.co.kr": "지디넷코리아", "inews24.com": "아이뉴스24",
    "energy-news.co.kr": "에너지신문", "todayenergy.kr": "투데이에너지",
    "gasnews.com": "가스신문", "energydaily.co.kr": "에너지데일리",
    "e2news.com": "이투뉴스", "kunews.co.kr": "에너지경제",
    "ekn.kr": "에너지경제신문", "greened.kr": "녹색경제신문",
    "kukinews.com": "쿠키뉴스", "yeongnam.com": "영남일보",
    "slist.kr": "싱글리스트", "newspim.com": "뉴스핌",
    "ajunews.com": "아주경제", "biz.heraldcorp.com": "헤럴드경제",
}


def _clean(text: str) -> str:
    """검색 API가 넣는 <b> 강조 태그와 HTML 엔티티를 제거."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).replace("&quot;", '"').strip()


def _outlet_from_url(url: str) -> str:
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    host = host.removeprefix("www.")
    if host in DOMAIN_TO_OUTLET:
        return DOMAIN_TO_OUTLET[host]
    # news.naver.com 링크는 매체를 알 수 없으니 상위 도메인으로 한 번 더 시도
    parts = host.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in DOMAIN_TO_OUTLET:
            return DOMAIN_TO_OUTLET[cand]
    return host or "출처 미상"


def _to_kst(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def is_fresh(published: str, lookback_hours: int) -> bool:
    """수집 시점 기준 lookback_hours 안의 기사만 통과."""
    if not published:
        return True  # 날짜를 못 읽은 건 일단 살려두고 담당자가 판단
    try:
        dt = datetime.strptime(published, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except ValueError:
        return True
    return dt >= datetime.now(KST) - timedelta(hours=lookback_hours)


# --------------------------------------------------------------------------
# 1. 네이버 뉴스 검색 API
# --------------------------------------------------------------------------

def naver_available() -> bool:
    return bool(env("NAVER_CLIENT_ID") and env("NAVER_CLIENT_SECRET"))


def fetch_naver(query: str, display: int = 30) -> list[Article]:
    if not naver_available():
        return []
    url = (
        "https://openapi.naver.com/v1/search/news.json"
        f"?query={quote(query)}&display={display}&sort=date"
    )
    headers = {
        "X-Naver-Client-Id": env("NAVER_CLIENT_ID"),
        "X-Naver-Client-Secret": env("NAVER_CLIENT_SECRET"),
        "User-Agent": UA,
    }
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()

    out: list[Article] = []
    for item in resp.json().get("items", []):
        title = _clean(item.get("title", ""))
        if not title:
            continue
        original = item.get("originallink") or item.get("link") or ""
        try:
            published = _to_kst(parsedate_to_datetime(item["pubDate"]))
        except (KeyError, ValueError, TypeError):
            published = ""
        out.append(
            Article(
                title=title,
                # 본문 링크는 네이버판을 우선 (기존 동향과 동일한 형태)
                url=item.get("link") or original,
                source=_outlet_from_url(original),
                published=published,
                summary=_clean(item.get("description", ""))[:300],
                query=query,
            )
        )
    return out


# --------------------------------------------------------------------------
# 2. 구글뉴스 RSS (키 불필요 — 네이버 키가 없을 때의 대체 경로)
# --------------------------------------------------------------------------

def fetch_google_news(query: str) -> list[Article]:
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    )
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    out: list[Article] = []
    for entry in feed.entries:
        raw_title = _clean(entry.get("title", ""))
        if not raw_title:
            continue
        # 구글뉴스 제목은 "기사 제목 - 매체명" 형태
        outlet = ""
        source = entry.get("source")
        if isinstance(source, dict):
            outlet = _clean(source.get("title", ""))
        title = raw_title
        if outlet and raw_title.endswith(f" - {outlet}"):
            title = raw_title[: -len(f" - {outlet}")].strip()
        elif " - " in raw_title:
            title, _, outlet = raw_title.rpartition(" - ")
            title, outlet = title.strip(), outlet.strip()

        published = ""
        if entry.get("published_parsed"):
            published = _to_kst(
                datetime.fromtimestamp(
                    time.mktime(entry.published_parsed), tz=timezone.utc
                )
            )
        out.append(
            Article(
                title=title,
                url=entry.get("link", ""),
                source=outlet or "출처 미상",
                published=published,
                summary=_clean(entry.get("summary", ""))[:300],
                query=query,
            )
        )
    return out


# --------------------------------------------------------------------------
# 3. 업계지 RSS — 석유관리원 보도자료가 실리는 곳
# --------------------------------------------------------------------------

TRADE_FEEDS = [
    ("에너지신문", "https://www.energy-news.co.kr/rss/allArticle.xml"),
    ("투데이에너지", "https://www.todayenergy.kr/rss/allArticle.xml"),
    ("가스신문", "https://www.gasnews.com/rss/allArticle.xml"),
    ("에너지데일리", "https://www.energydaily.co.kr/rss/allArticle.xml"),
    ("이투뉴스", "https://www.e2news.com/rss/allArticle.xml"),
]


def fetch_trade_feeds() -> list[Article]:
    out: list[Article] = []
    for outlet, url in TRADE_FEEDS:
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as exc:                      # noqa: BLE001
            log.warning("업계지 RSS 실패 %s: %s", outlet, exc)
            continue

        for entry in feed.entries:
            title = _clean(entry.get("title", ""))
            if not title:
                continue
            published = ""
            if entry.get("published_parsed"):
                published = _to_kst(
                    datetime.fromtimestamp(
                        time.mktime(entry.published_parsed), tz=timezone.utc
                    )
                )
            out.append(
                Article(
                    title=title,
                    url=entry.get("link", ""),
                    source=outlet,
                    published=published,
                    summary=_clean(entry.get("summary", ""))[:300],
                    query=f"rss:{outlet}",
                )
            )
    return out
