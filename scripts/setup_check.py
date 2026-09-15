"""설정이 제대로 됐는지 한 번에 확인하는 진단 도구.

Secret 을 넣은 뒤 Actions 탭에서 '설정 확인' 을 한 번 돌리면, 어디까지 됐고
무엇이 비었는지 표로 나옵니다. 다음 날 아침을 기다렸다가 실패를 보는 대신
그 자리에서 알 수 있게 하는 것이 목적입니다.

텔레그램 chat_id 는 봇 토큰만 있으면 직접 찾아냅니다. getUpdates 응답을
사람이 읽고 숫자를 골라내는 단계를 없애기 위한 것입니다.

값 자체는 절대 출력하지 않습니다. 있는지 없는지와 몇 자리인지만 보여줍니다.
로그는 저장소가 공개면 누구나 볼 수 있습니다.
"""

from __future__ import annotations

import argparse
import smtplib
import sys
from dataclasses import dataclass

import requests

from .config import env

TIMEOUT = 20


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def mask(value: str) -> str:
    """값을 드러내지 않고 '들어 있다'는 것만 보여줍니다."""
    if not value:
        return "(비어 있음)"
    return f"({len(value)}자, {value[:2]}…{value[-2:]})" if len(value) > 6 else "(설정됨)"


# ---------------------------------------------------------------------------
# 텔레그램
# ---------------------------------------------------------------------------

def check_telegram(send_test: bool) -> list[Result]:
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        return [Result("텔레그램 봇 토큰", False, "비어 있음",
                       "@BotFather 에서 /newbot 으로 만든 토큰을 "
                       "TELEGRAM_BOT_TOKEN Secret 에 넣으세요")]

    results: list[Result] = []
    base = f"https://api.telegram.org/bot{token}"

    try:
        me = requests.get(f"{base}/getMe", timeout=TIMEOUT).json()
    except Exception as exc:                          # noqa: BLE001
        return [Result("텔레그램 봇 토큰", False, f"연결 실패: {exc}")]

    if not me.get("ok"):
        return [Result("텔레그램 봇 토큰", False,
                       f"거부됨: {me.get('description', '알 수 없음')}",
                       "토큰을 다시 복사해 Secret 에 넣으세요")]

    bot = me["result"]
    results.append(Result("텔레그램 봇 토큰", True, f"@{bot.get('username')} 확인됨"))

    # chat_id — 설정돼 있으면 그대로, 없으면 찾아서 알려줍니다.
    chat_id = env("TELEGRAM_CHAT_ID")
    if not chat_id:
        found = discover_chat_ids(base)
        if found:
            listed = ", ".join(f"{cid} ({name})" for cid, name in found)
            results.append(Result(
                "텔레그램 chat_id", False, f"비어 있음 — 찾은 값: {listed}",
                f"위 숫자를 TELEGRAM_CHAT_ID Secret 에 넣으세요. "
                f"여러 개면 동향을 받을 대화의 것을 고르세요."))
        else:
            results.append(Result(
                "텔레그램 chat_id", False, "비어 있고 자동 탐색도 실패",
                f"텔레그램에서 @{bot.get('username')} 에게 아무 메시지나 한 번 "
                f"보낸 뒤 이 검사를 다시 돌리세요"))
        return results

    results.append(Result("텔레그램 chat_id", True, f"설정됨 {mask(chat_id)}"))

    if send_test:
        try:
            resp = requests.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_id,
                      "text": "✅ 언론동향 설정 확인 — 텔레그램 연결이 정상입니다.",
                      "disable_web_page_preview": True},
                timeout=TIMEOUT)
            body = resp.json()
            if body.get("ok"):
                results.append(Result("텔레그램 시험 발송", True, "메시지가 갔습니다"))
            else:
                results.append(Result(
                    "텔레그램 시험 발송", False,
                    body.get("description", "알 수 없음"),
                    "chat_id 가 이 봇과의 대화가 맞는지 확인하세요"))
        except Exception as exc:                      # noqa: BLE001
            results.append(Result("텔레그램 시험 발송", False, str(exc)))

    return results


def discover_chat_ids(base: str) -> list[tuple[str, str]]:
    """봇이 최근 받은 메시지에서 chat_id 를 긁어옵니다.

    텔레그램은 최근 24시간치만 돌려주므로, 봇에게 메시지를 보낸 적이 없으면
    빈 목록이 나옵니다.
    """
    try:
        updates = requests.get(f"{base}/getUpdates", timeout=TIMEOUT).json()
    except Exception:                                 # noqa: BLE001
        return []
    if not updates.get("ok"):
        return []

    found: dict[str, str] = {}
    for item in updates.get("result", []):
        for key in ("message", "channel_post", "edited_message", "my_chat_member"):
            chat = (item.get(key) or {}).get("chat")
            if not chat:
                continue
            label = (chat.get("title") or chat.get("username")
                     or chat.get("first_name") or chat.get("type") or "이름 없음")
            found[str(chat["id"])] = label
    return sorted(found.items())


# ---------------------------------------------------------------------------
# 네이버 검색 API
# ---------------------------------------------------------------------------

def check_naver() -> list[Result]:
    cid, secret = env("NAVER_CLIENT_ID"), env("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        return [Result(
            "네이버 검색 API", False, "비어 있음 (선택 항목)",
            "없어도 구글뉴스로 동작하지만 국내 기사 품질이 떨어집니다. "
            "developers.naver.com 에서 무료로 받을 수 있습니다")]

    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json?query=석유관리원&display=5",
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret},
            timeout=TIMEOUT)
    except Exception as exc:                          # noqa: BLE001
        return [Result("네이버 검색 API", False, f"연결 실패: {exc}")]

    if resp.status_code == 401:
        return [Result("네이버 검색 API", False, "인증 거부 (401)",
                       "Client ID / Secret 을 다시 확인하세요")]
    if not resp.ok:
        return [Result("네이버 검색 API", False,
                       f"{resp.status_code}: {resp.text[:120]}")]

    total = resp.json().get("total", 0)
    return [Result("네이버 검색 API", True, f"정상 — '석유관리원' 검색결과 {total:,}건")]


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def check_gmail(send_test: bool) -> list[Result]:
    user, password = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
    recipients = [r.strip() for r in env("EMAIL_TO").split(",") if r.strip()]

    if not user or not password:
        return [Result("Gmail 계정", False, "비어 있음",
                       "2단계 인증을 켠 뒤 앱 비밀번호를 발급받아 "
                       "GMAIL_USER / GMAIL_APP_PASSWORD 에 넣으세요")]
    if not recipients:
        return [Result("받는 사람", False, "EMAIL_TO 가 비어 있음",
                       "받을 주소를 쉼표로 구분해 넣으세요")]

    results: list[Result] = []
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=TIMEOUT) as server:
            server.login(user, password)
            results.append(Result("Gmail 로그인", True, f"{user} 인증 성공"))

            if send_test:
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["Subject"] = "[언론동향] 설정 확인"
                msg["From"] = f"한국석유관리원 언론동향 <{user}>"
                msg["To"] = ", ".join(recipients)
                msg.set_content(
                    "언론동향 자동화 설정 확인 메일입니다.\n"
                    "이 메일이 보이면 이메일 발송 경로가 정상입니다.")
                server.send_message(msg)
                results.append(
                    Result("이메일 시험 발송", True, f"{len(recipients)}명에게 발송"))
    except smtplib.SMTPAuthenticationError:
        results.append(Result(
            "Gmail 로그인", False, "인증 거부",
            "일반 비밀번호가 아니라 16자리 앱 비밀번호여야 합니다. "
            "2단계 인증이 켜져 있는지도 확인하세요"))
    except Exception as exc:                          # noqa: BLE001
        results.append(Result("Gmail 로그인", False, str(exc)))

    results.append(Result("받는 사람", True, f"{len(recipients)}명 설정됨"))
    return results


# ---------------------------------------------------------------------------
# 검토 페이지 (Vercel)
# ---------------------------------------------------------------------------

def check_review_page() -> list[Result]:
    url = env("REVIEW_URL")
    if not url:
        return [Result(
            "검토 페이지", False, "REVIEW_URL 변수가 비어 있음",
            "Vercel 배포 후 나온 주소를 Settings > Variables 에 "
            "REVIEW_URL 이름으로 넣으세요")]

    try:
        resp = requests.get(url.rstrip("/"), timeout=TIMEOUT)
    except Exception as exc:                          # noqa: BLE001
        return [Result("검토 페이지", False, f"연결 실패: {exc}",
                       "Vercel 배포가 끝났는지 확인하세요")]

    if not resp.ok:
        return [Result("검토 페이지", False, f"HTTP {resp.status_code}")]

    results = [Result("검토 페이지", True, f"응답 정상 ({url})")]

    # PIN 이 설정돼 있는지는 일부러 틀린 PIN 을 보내 응답 코드로 판별합니다.
    # 401 이면 정상 동작 중, 500 이면 환경변수가 빠진 상태입니다.
    try:
        probe = requests.post(f"{url.rstrip('/')}/api/session",
                              json={"pin": "___설정확인용_잘못된_값___"},
                              timeout=TIMEOUT)
        if probe.status_code == 401:
            results.append(Result("검토 페이지 환경변수", True, "PIN 인증이 동작 중"))
        elif probe.status_code == 500:
            results.append(Result(
                "검토 페이지 환경변수", False, probe.json().get("error", "설정 누락"),
                "Vercel 대시보드 > Settings > Environment Variables 를 확인하고 "
                "저장 후 재배포하세요"))
        else:
            results.append(Result("검토 페이지 환경변수", False,
                                  f"예상치 못한 응답 {probe.status_code}"))
    except Exception as exc:                          # noqa: BLE001
        results.append(Result("검토 페이지 환경변수", False, str(exc)))

    return results


# ---------------------------------------------------------------------------

def display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글·한자는 두 칸을 씁니다."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def render(results: list[Result]) -> bool:
    width = max(display_width(r.name) for r in results) + 2
    print()
    print("=" * 72)
    print("  설정 확인 결과")
    print("=" * 72)
    for r in results:
        pad = " " * (width - display_width(r.name))
        print(f"  {'✅' if r.ok else '❌'}  {r.name}{pad}{r.detail}")
        if r.hint and not r.ok:
            print(f"      └─ {r.hint}")
    print("=" * 72)

    failed = [r for r in results if not r.ok]
    if not failed:
        print("  전부 정상입니다. 내일 아침 06:40 부터 자동으로 돕니다.")
    else:
        print(f"  {len(failed)}개 항목이 남았습니다. 위의 └─ 안내를 따라 주세요.")
    print()
    return not failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="설정 확인")
    parser.add_argument("--send-test", action="store_true",
                        help="텔레그램·이메일로 실제 시험 메시지를 보냄")
    args = parser.parse_args(argv)

    results: list[Result] = []
    results += check_telegram(args.send_test)
    results += check_naver()
    results += check_gmail(args.send_test)
    results += check_review_page()

    ok = render(results)
    # 선택 항목(네이버)만 빠진 경우까지 실패로 만들면 매번 빨간불이 뜹니다.
    required_failed = [
        r for r in results if not r.ok and not r.detail.startswith("비어 있음 (선택")
    ]
    return 0 if not required_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
