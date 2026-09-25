"""동향을 세 가지 형태로 출력.

  render_plain    카카오톡에 그대로 붙여넣는 평문. 기존 동향 서식 그대로.
  render_markdown archive/ 에 쌓을 마크다운.
  render_email    이메일 본문 HTML.

담당자의 실제 동선은 '텔레그램에서 복사 → 카카오톡에 붙여넣기'입니다.
그래서 평문이 원본이고 나머지가 파생물입니다.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

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
    if digest.analysis:
        return render_analysis(digest, excluded)
    lines = [_title_line(digest.date), ""]
    if digest.fallback_notice:
        lines += [digest.fallback_notice, ""]

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


def render_analysis(digest, excluded=None):
    if digest.analysis.get("mode") == "dual":
        from .config import load_config
        return "\n\n".join(dual_blocks(digest, load_config(), excluded)) + "\n"
    lines = [_title_line(digest.date), "", "[AI 종합 분석]", ""]
    issues = digest.visible_issues(excluded)
    articles = {a.id: a for a in digest.articles}
    for n, issue in enumerate(issues, 1):
        lines.extend([f"{n}. {issue['title']}", f"핵심: {issue['summary']}",
                      f"새로운 점: {issue['change']}", f"업무 관련성: {issue['impact']}"])
        for id in issue["article_ids"]:
            a = articles[id]
            lines.extend([f"근거: {a.title} / {a.source}", a.url])
        lines.append("")
    if not issues:
        lines.extend(["오늘 발송할 주요 새 이슈가 없습니다.", ""])
    lines.append("수집된 제목·매체 요약을 바탕으로 작성한 AI 분석입니다. 중요 사실은 원문 확인이 필요합니다.")
    return "\n".join(lines).rstrip() + "\n"


def article_anchor(article):
    label = html.escape(f"{article.title} / {article.source}")
    url = urlsplit(article.url)
    if url.scheme not in ("http", "https") or not url.netloc:
        return label
    return f'<a href="{html.escape(article.url, quote=True)}">{label}</a>'


def dual_blocks(digest, config, excluded=None, *, markup=False):
    esc = html.escape if markup else str
    groups = digest.by_sector(config, excluded)
    ordered = [a for _, items in groups for a in items]
    indexes = {a.id: n for n, a in enumerate(ordered, 1)}
    blocks = [esc(_title_line(digest.date)),
              f"동일 자료 {digest.analysis.get('input_count', 0)}건 · Gemini / Groq 독립 분석"]
    for title, items in groups:
        blocks.append(esc('[' + title + ']'))
        for a in items:
            label = article_anchor(a) if markup else f'{a.title} / {a.source}\n{a.url}'
            blocks.append(f'{indexes[a.id]}. {label}')
    selected = []
    for report in digest.analysis.get('reports', []):
        label = 'Gemini' if report['provider'] == 'gemini' else 'Groq'
        blocks.append(f'[{label} 분석]')
        if report['status'] != 'ok':
            blocks.append('분석 실패 · 다른 모델 결과와 기본 기사 목록을 유지합니다.')
            selected.append(None)
            continue
        blocks.append(esc('실제 모델: ' + report.get('model', '')))
        issues = [i for i in report.get('issues', []) if i.get('article_ids') and
                  all(id in indexes for id in i['article_ids'])]
        selected.append({id for i in issues for id in i['article_ids']})
        for n, i in enumerate(issues, 1):
            refs = ', '.join(str(indexes[id]) for id in i['article_ids'])
            blocks.append(esc(f"{n}. {i['title']}\n핵심: {i['summary']}\n새로운 점: {i['change']}\n업무 관련성: {i['impact']}\n근거 기사: {refs}"))
        if not issues:
            blocks.append('주요 새 이슈 없음 (담당자 제외 반영).')
    blocks.append('[선택 비교]')
    if len(selected) == 2 and all(x is not None for x in selected):
        a, b = selected
        for label, ids in [('공통 선택', a & b), ('Gemini만 선택', a - b), ('Groq만 선택', b - a)]:
            refs = ', '.join(str(indexes[id]) for id in indexes if id in ids) or '없음'
            blocks.append(f'{label} 기사: {refs}')
        blocks.append('근거 기사 선택의 비교이며, 결론의 일치·불일치 판정은 아닙니다.')
    else:
        blocks.append('일부 모델 실패로 양쪽 비교가 불가능합니다.')
    blocks.append('수집된 제목·매체 요약 기반 AI 분석입니다. 각 모델의 해석은 원문 확인이 필요합니다.')
    return blocks


def telegram_chunks(digest, config, excluded=None):
    """HTML 태그·링크를 자르지 않고 이슈/기사 경계에서 분할한다."""
    esc = html.escape
    blocks = [f"<b>{esc(_title_line(digest.date))}</b>"]
    if digest.fallback_notice:
        blocks.append(esc(digest.fallback_notice))
    if digest.analysis.get("mode") == "dual":
        blocks = dual_blocks(digest, config, excluded, markup=True)
    elif digest.analysis:
        blocks.append("<b>AI 종합 분석</b>")
        articles = {a.id: a for a in digest.articles}
        issues = digest.visible_issues(excluded)
        for n, issue in enumerate(issues, 1):
            blocks.append("\n".join([f"<b>{n}. {esc(issue['title'])}</b>",
                f"핵심: {esc(issue['summary'])}", f"새로운 점: {esc(issue['change'])}",
                f"업무 관련성: {esc(issue['impact'])}",
                *(f"↗ {article_anchor(articles[id])}" for id in issue["article_ids"])]))
        if not issues:
            blocks.append("오늘 발송할 주요 새 이슈가 없습니다.")
        blocks.append("수집된 제목·매체 요약을 바탕으로 작성한 AI 분석입니다. 중요 사실은 원문 확인이 필요합니다.")
    else:
        if digest.market:
            blocks.append(esc(brief_line(_quotes(digest))))
        risky = digest.risk_articles(excluded)
        if risky:
            blocks.append(esc(_risk_summary(risky)))
        for title, articles in digest.by_sector(config, excluded):
            blocks.append(f"<b>{esc(title)}</b>")
            blocks.extend(article_anchor(a) for a in articles)
    chunks, current = [], ""
    def length(text):
        return len(html.unescape(re.sub(r"<[^>]*>", "", text)).encode("utf-16-le")) // 2
    for block in blocks:
        if length(block) > TELEGRAM_LIMIT:
            raise ValueError("Telegram 이슈 길이 초과")
        candidate = current + "\n\n" + block if current else block
        if length(candidate) > TELEGRAM_LIMIT:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


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
    if digest.analysis:
        return render_analysis(digest, excluded)
    year, month, day = digest.date.split("-")
    lines = [f"# 한국석유관리원 일일언론동향 ({year}년 {int(month)}월 {int(day)}일)", ""]
    if digest.fallback_notice:
        lines += [digest.fallback_notice, ""]

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
    if digest.analysis:
        return ("<!doctype html><html><meta charset='utf-8'><body><div style='white-space:pre-wrap'>"
                + "\n\n".join(telegram_chunks(digest, config, excluded)) + "</div></body></html>")
    esc = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<style>{_EMAIL_CSS}</style></head><body>",
        f"<h1>{esc(_title_line(digest.date))}</h1>",
        f"<div class='meta'>수집 {esc(digest.generated_at)}</div>",
    ]
    if digest.fallback_notice:
        parts.append(f"<p>{esc(digest.fallback_notice)}</p>")

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
