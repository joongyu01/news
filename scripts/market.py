"""동향 맨 위에 붙는 유가·환율 한 줄 브리핑.

키가 필요 없는 무료 소스만 씁니다.
  · WTI / 브렌트 : Yahoo Finance 선물 일봉 Close (공식 정산가 아님)
  · 원/달러      : frankfurter.app (유럽중앙은행 고시)

시세는 부가 정보입니다. 어느 하나라도 실패하면 그 항목만 빠지고
동향 본문은 정상 발송됩니다. 절대 예외를 위로 던지지 않습니다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .models import now_kst

log = logging.getLogger(__name__)

TIMEOUT = 15
UA = "Mozilla/5.0 (compatible; kpetro-news-digest/1.0)"


@dataclass
class Quote:
    label: str
    value: float
    change_pct: float | None
    unit: str = ""
    as_of: str = ""
    basis: str = ""
    source: str = ""

    def format(self) -> str:
        note = " · ".join(x for x in (self.as_of, self.basis, self.source) if x)
        suffix = f" ({note})" if note else ""
        if self.change_pct is None:
            return f"{self.label} {self.value:,.2f}{self.unit}" + suffix
        arrow = "▲" if self.change_pct > 0 else ("▼" if self.change_pct < 0 else "-")
        return (
            f"{self.label} {self.value:,.2f}{self.unit} "
            f"{arrow}{abs(self.change_pct):.1f}%" + suffix
        )


def _oil_quote(label: str, symbol: str) -> Quote | None:
    """Use completed daily bars only, never an in-progress session's Close."""
    try:
        resp = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                            params={"range": "1mo", "interval": "1d"},
                            headers={"User-Agent": UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()["chart"]["result"][0]
        meta = data["meta"]
        if meta["symbol"] != symbol or meta["currency"] != "USD" or meta["instrumentType"] != "FUTURE":
            return None
        now = now_kst()
        period = meta["currentTradingPeriod"]["regular"]
        tz = ZoneInfo(meta["exchangeTimezoneName"])
        rows = sorted((stamp, float(close)) for stamp, close in zip(
            data["timestamp"], data["indicators"]["quote"][0]["close"])
            if close is not None and math.isfinite(float(close)) and stamp <= now.timestamp()
            and (stamp < period["start"] or now.timestamp() >= period["end"]))
        if len(rows) < 2:
            return None
        stamp, last = rows[-1]
        day = datetime.fromtimestamp(stamp, tz).date()
        if not 0 <= (now.astimezone(tz).date() - day).days <= 7:
            return None
        prev = rows[-2][1]
        change = (last - prev) / abs(prev) * 100 if prev else None
        return Quote(label, last, change, "달러/배럴", day.isoformat(), "선물 일봉 종가", "Yahoo Finance")
    except Exception as exc:                          # noqa: BLE001
        log.warning("시세 조회 실패 %s (%s)", label, type(exc).__name__)
        return None


def _usd_krw() -> Quote | None:
    try:
        today = now_kst().date()
        url = (
            "https://api.frankfurter.app/"
            f"{today - timedelta(days=10):%Y-%m-%d}..{today:%Y-%m-%d}"
            "?from=USD&to=KRW"
        )
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        rates = resp.json().get("rates", {})
        series = [rates[d]["KRW"] for d in sorted(rates) if "KRW" in rates[d]]
    except Exception as exc:                          # noqa: BLE001
        log.warning("환율 조회 실패: %s", exc)
        return None
    if not series:
        return None
    last = series[-1]
    prev = series[-2] if len(series) > 1 else None
    change = ((last - prev) / prev * 100) if prev else None
    return Quote("원/달러", last, change, "원", sorted(rates)[-1], "기준환율", "Frankfurter")


def market_brief() -> list[Quote]:
    """브리핑에 실을 시세 목록. 실패한 항목은 빠집니다."""
    candidates = [
        _usd_krw(),
        _oil_quote("WTI", "CL=F"),
        _oil_quote("브렌트", "BZ=F"),
    ]
    return [q for q in candidates if q is not None]


def brief_line(quotes: list[Quote]) -> str:
    """'브렌트 78.20$ ▲1.2% | WTI 74.10$ ▲1.0% | 원/달러 1,380.50원 ▼0.3%'"""
    return "  |  ".join(q.format() for q in quotes)
