"""동향을 세 가지 형태로 출력.

  render_plain    카카오톡에 그대로 붙여넣는 평문. 기존 동향 서식 그대로.
  render_markdown archive/ 에 쌓을 마크다운.
  render_email    이메일 본문 HTML.

담당자의 실제 동선은 '텔레그램에서 복사 → 카카오톡에 붙여넣기'입니다.
그래서 평문이 원본이고 나머지가 파생물입니다.
"""

from __future__ import annotations

import html

from .config import Config
from .digest import Digest
from .market import Quote, brief_line
from .models import Article

TELEGRAM_LIMIT = 3900       # 실제 상한 4096. 헤더·꼬리표 여유분을 남겨둠


def _quotes(digest: Digest) -> list[Quote]:
    return [Quote(**q) for q in digest.market]


def _title_line(date: str) -> str:
    """'한국석유관리원 26년 9월 16일 일일언론동향' — 기존 동향과 같은 표기."""
    year, month, day = date.split("-")
    return f"한국석유관리원 {year[2:]}년 {int(month)}월 {int(day)}일 일일언론동향"


def _risk_summary(articles: list[Article]) -> str:
    if not articles:
        return ""
    keywords: list[str] = []
    for a in articles:
        for kw in a.risk:
            if kw not in keywords:
                keywords.append(kw)
    return f"⚠️ 주의 {len(articles)}건 — {', '.join(keywords[:6])}"


def _dupe_suffix(article: Article) -> str:
    return f" (외 {len(article.duplicates)}건)" if article.duplicates else ""


# ---------------------------------------------------------------------------
# 1. 평문 — 카카오톡용
# ---------------------------------------------------------------------------

def render_plain(digest: Digest, config: Config, excluded: set[str] | None = None) -> str:
    lines = [_title_line(digest.date), ""]

    quotes = _quotes(digest)
    if quotes:
        lines += [brief_line(quotes), ""]

    risky = digest.risk_articles(excluded)
    if risky:
        lines += [_risk_summary(risky), ""]

    for sector_title, articles in digest.by_sector(config, excluded):
        lines.append(f"[{sector_title}]")
        for idx, article in enumerate(articles, 1):
            mark = "⚠️ " if article.risk else ""
            lines.append(
                f"{idx}. {mark}{article.title}{_dupe_suffix(article)} / {article.source}"
            )
            lines.append(article.url)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def split_for_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """텔레그램 글자수 제한에 맞춰 자릅니다. 섹터 경계를 우선 지킵니다."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # 한 섹터가 통째로 한도를 넘으면 줄 단위로 쪼갭니다.
        if len(block) <= limit:
            current = block
            continue
        current = ""
        for line in block.split("\n"):
            nxt = f"{current}\n{line}" if current else line
            if len(nxt) > limit:
                chunks.append(current)
                current = line
            else:
                current = nxt
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# 2. 마크다운 — archive/ 보관용
# ---------------------------------------------------------------------------

def render_markdown(digest: Digest, config: Config, excluded: set[str] | None = None) -> str:
    year, month, day = digest.date.split("-")
    lines = [f"# 한국석유관리원 일일언론동향 ({year}년 {int(month)}월 {int(day)}일)", ""]

    quotes = _quotes(digest)
    if quotes:
        lines += [f"> {brief_line(quotes)}", ""]

    risky = digest.risk_articles(excluded)
    if risky:
        lines += [f"> {_risk_summary(risky)}", ""]

    for sector_title, articles in digest.by_sector(config, excluded):
        lines += [f"## {sector_title}", ""]
        for idx, article in enumerate(articles, 1):
            mark = "⚠️ " if article.risk else ""
            lines.append(
                f"{idx}. {mark}{article.title}{_dupe_suffix(article)} / {article.source}"
            )
            lines.append(f"   - {article.url}")
            for dup in article.duplicates:
                lines.append(f"   - (동일 사안) {dup['source']}: {dup['url']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 3. HTML — 이메일 본문
# ---------------------------------------------------------------------------

_EMAIL_CSS = """
body{font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
     color:#1a1a1a;line-height:1.6;max-width:680px;margin:0 auto;padding:20px}
h1{font-size:19px;border-bottom:2px solid #1a5490;padding-bottom:10px;margin-bottom:6px}
h2{font-size:15px;color:#1a5490;margin:26px 0 10px;padding-left:9px;
   border-left:4px solid #1a5490}
ol{padding-left:22px;margin:0}
li{margin-bottom:11px}
a{color:#1a5490;text-decoration:none}
.meta{color:#666;font-size:12px}
.market{background:#f4f7fa;border-radius:6px;padding:10px 13px;font-size:13px;margin:12px 0}
.risk{background:#fff4f4;border-left:4px solid #d93025;border-radius:0 6px 6px 0;
      padding:10px 13px;font-size:13px;margin:12px 0;color:#a5271d;font-weight:600}
.src{color:#666;font-size:12.5px}
.dup{color:#888;font-size:12px}
.copy{background:#f8f9fa;border:1px solid #e0e0e0;border-radius:6px;padding:14px;
      white-space:pre-wrap;font-size:12.5px;font-family:ui-monospace,Menlo,monospace;
      margin-top:14px}
.foot{color:#999;font-size:11.5px;margin-top:30px;border-top:1px solid #eee;padding-top:12px}
"""


def render_email(digest: Digest, config: Config, excluded: set[str] | None = None) -> str:
    esc = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<style>{_EMAIL_CSS}</style></head><body>",
        f"<h1>{esc(_title_line(digest.date))}</h1>",
        f"<div class='meta'>수집 {esc(digest.generated_at)}</div>",
    ]

    quotes = _quotes(digest)
    if quotes:
        parts.append(f"<div class='market'>{esc(brief_line(quotes))}</div>")

    risky = digest.risk_articles(excluded)
    if risky:
        parts.append(f"<div class='risk'>{esc(_risk_summary(risky))}</div>")

    for sector_title, articles in digest.by_sector(config, excluded):
        parts.append(f"<h2>{esc(sector_title)}</h2><ol>")
        for article in articles:
            mark = "⚠️ " if article.risk else ""
            parts.append(
                f"<li><a href='{esc(article.url)}'>{mark}{esc(article.title)}</a>"
                f" <span class='src'>/ {esc(article.source)}</span>"
            )
            if article.duplicates:
                outlets = ", ".join(
                    esc(d["source"]) for d in article.duplicates[:4]
                )
                parts.append(
                    f"<br><span class='dup'>동일 사안 {len(article.duplicates)}건 — {outlets}</span>"
                )
            parts.append("</li>")
        parts.append("</ol>")

    plain = render_plain(digest, config, excluded)
    parts += [
        "<h2>카카오톡 붙여넣기용</h2>",
        f"<div class='copy'>{esc(plain)}</div>",
        "<div class='foot'>이 메일은 매일 아침 자동 발송됩니다. "
        "기사 제외는 검토 페이지에서 하실 수 있습니다.</div>",
        "</body></html>",
    ]
    return "".join(parts)
