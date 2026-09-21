"""텔레그램·이메일 발송."""

from __future__ import annotations

import logging
import smtplib
import time
from email.message import EmailMessage

import requests

from .config import env

log = logging.getLogger(__name__)

TIMEOUT = 25


# ---------------------------------------------------------------------------
# 텔레그램
# ---------------------------------------------------------------------------

def send_telegram(chunks: list[str], chat_id: str | None = None, *, parse_mode=None) -> int:
    """평문 또는 서버에서 escape한 HTML. 링크 미리보기는 끈다."""
    if parse_mode not in (None, "HTML"):
        raise ValueError("Unsupported Telegram format")
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("텔레그램 설정 없음 — 건너뜁니다")
        return 0

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0
    for idx, chunk in enumerate(chunks):
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
                **({"parse_mode": parse_mode} if parse_mode else {}),
            },
            timeout=TIMEOUT,
        )
        if not resp.ok:
            # 어느 조각에서 깨졌는지 알아야 다음 날 고칠 수 있습니다.
            raise RuntimeError(
                f"텔레그램 발송 실패 ({idx + 1}/{len(chunks)}): "
                f"{resp.status_code} {resp.text[:300]}"
            )
        sent += 1
        if idx < len(chunks) - 1:
            time.sleep(0.4)          # 연속 발송 rate limit 회피
    return sent


def send_digest(chunks: list[str], *, parse_mode=None) -> int:
    """Final digests go only to explicitly subscribed chats; reviews stay private."""
    from . import preferences
    if not env("TELEGRAM_BOT_TOKEN"):
        return 0
    settings = preferences.load()
    count = 0
    for chat_id, options in settings["chats"].items():
        if not options.get("daily", True):
            continue
        try:
            count += send_telegram(chunks, chat_id=chat_id, parse_mode=parse_mode)
        except Exception as exc:
            log.error("Telegram 구독방 발송 실패 (%s)", type(exc).__name__)
    return count


# ---------------------------------------------------------------------------
# 이메일 (Gmail SMTP)
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str, plain_body: str) -> int:
    """받는 사람은 EMAIL_TO 에 쉼표로 구분해 넣습니다."""
    user, password = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
    recipients = [r.strip() for r in env("EMAIL_TO").split(",") if r.strip()]
    if not user or not password or not recipients:
        log.warning("이메일 설정 없음 — 건너뜁니다")
        return 0

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"한국석유관리원 언론동향 <{user}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(plain_body)                       # 텍스트 메일 클라이언트용
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=TIMEOUT) as server:
        server.login(user, password)
        server.send_message(msg)
    return len(recipients)
