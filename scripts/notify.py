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

def send_telegram(chunks: list[str]) -> int:
    """평문 그대로 보냅니다. 마크다운 파싱을 켜지 않는 이유가 두 가지 있습니다.

      · 기사 제목에 * _ [ ] 가 들어가면 파싱 오류로 발송 자체가 실패합니다.
      · 담당자가 복사해서 카카오톡에 붙여넣으므로 서식 기호가 없어야 깔끔합니다.

    링크 미리보기는 끕니다. 기사가 10건 넘으면 화면이 감당이 안 됩니다.
    """
    token, chat_id = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
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
