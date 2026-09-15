"""동향 맨 위에 붙는 유가·환율 한 줄 브리핑.

키가 필요 없는 무료 소스만 씁니다.
  · WTI / 브렌트 : stooq.com 일봉 CSV
  · 원/달러      : frankfurter.app (유럽중앙은행 고시)

시세는 부가 정보입니다. 어느 하나라도 실패하면 그 항목만 빠지고
동향 본문은 정상 발송됩니다. 절대 예외를 위로 던지지 않습니다.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import timedelta

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

    def format(self) -> str:
        if self.change_pct is None:
            return f"{self.label} {self.value:,.2f}{self.unit}"
        arrow = "▲" if self.change_pct > 0 else ("▼" if self.change_pct < 0 else "-")
        return (
            f"{self.label} {self.value:,.2f}{self.unit} "
            f"{arrow}{abs(self.change_pct):.1f}%"
        )


def _stooq_last_two(symbol: str) -> tuple[float, float] | None:
    """stooq 일봉에서 (최근 종가, 직전 종가)."""
    today = now_kst().date()
    start = today - timedelta(days=14)
    url = (
        "https://stooq.com/q/d/l/"
        f"?s={symbol}&d1={start:%Y%m%d}&d2={today:%Y%m%d}&i=d"
    )
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    closes = [float(r["Close"]) for r in rows if r.get("Close") not in (None, "", "N/D")]
    if len(closes) < 2:
        return None
    return closes[-1], closes[-2]


def _quote_from_stooq(label: str, symbol: str, unit: str) -> Quote | None:
    try:
        pair = _stooq_last_two(symbol)
    except Exception as exc:                          # noqa: BLE001
        log.warning("시세 조회 실패 %s: %s", label, exc)
        return None
    if pair is None:
        log.warning("시세 데이터 부족 %s", label)
        return None
    last, prev = pair
    change = ((last - prev) / prev * 100) if prev else None
    return Quote(label, last, change, unit)


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
    return Quote("원/달러", last, change, "원")


def market_brief() -> list[Quote]:
    """브리핑에 실을 시세 목록. 실패한 항목은 빠집니다."""
    candidates = [
        _quote_from_stooq("두바이유 대체(브렌트)", "cb.f", "$"),
        _quote_from_stooq("WTI", "cl.f", "$"),
        _usd_krw(),
    ]
    return [q for q in candidates if q is not None]


def brief_line(quotes: list[Quote]) -> str:
    """'브렌트 78.20$ ▲1.2% | WTI 74.10$ ▲1.0% | 원/달러 1,380.50원 ▼0.3%'"""
    return "  |  ".join(q.format() for q in quotes)
