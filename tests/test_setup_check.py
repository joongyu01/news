"""설정 확인 도구 검증.

네트워크를 타는 부분은 응답만 가짜로 끼워 넣고, 판정 로직과 chat_id 추출만
확인합니다. 진단 도구가 오히려 틀린 안내를 하면 설정이 더 꼬입니다.
"""

import unittest
from unittest.mock import patch

from scripts import setup_check
from scripts.setup_check import Result, discover_chat_ids, display_width, mask


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class TestHelpers(unittest.TestCase):
    def test_mask_never_reveals_full_value(self):
        token = "8123456789:AAHxyz-secret-part"
        masked = mask(token)
        self.assertNotIn("secret", masked)
        self.assertIn(str(len(token)), masked)

    def test_mask_empty(self):
        self.assertEqual(mask(""), "(비어 있음)")

    def test_mask_short_value_is_not_partially_shown(self):
        self.assertEqual(mask("1234"), "(설정됨)")

    def test_display_width_counts_hangul_as_two(self):
        self.assertEqual(display_width("검토"), 4)
        self.assertEqual(display_width("ab"), 2)
        self.assertEqual(display_width("검토 페이지"), 11)


class TestChatIdDiscovery(unittest.TestCase):
    """봇 토큰만으로 chat_id 를 찾아내는 부분. 담당자가 JSON 을 읽지 않아도 되게."""

    def discover(self, payload):
        with patch.object(setup_check.requests, "get",
                          return_value=FakeResponse(payload)):
            return discover_chat_ids("https://api.telegram.org/botX")

    def test_extracts_from_message(self):
        found = self.discover({"ok": True, "result": [
            {"message": {"chat": {"id": 12345, "first_name": "홍길동", "type": "private"}}}
        ]})
        self.assertEqual(found, [("12345", "홍길동")])

    def test_deduplicates_repeated_chats(self):
        found = self.discover({"ok": True, "result": [
            {"message": {"chat": {"id": 7, "title": "동향방", "type": "group"}}},
            {"message": {"chat": {"id": 7, "title": "동향방", "type": "group"}}},
        ]})
        self.assertEqual(len(found), 1)

    def test_handles_channel_posts_and_group_adds(self):
        found = self.discover({"ok": True, "result": [
            {"channel_post": {"chat": {"id": -100123, "title": "공지채널"}}},
            {"my_chat_member": {"chat": {"id": -456, "title": "팀방"}}},
        ]})
        self.assertEqual(dict(found), {"-100123": "공지채널", "-456": "팀방"})

    def test_empty_when_bot_never_messaged(self):
        self.assertEqual(self.discover({"ok": True, "result": []}), [])

    def test_empty_on_api_error(self):
        self.assertEqual(self.discover({"ok": False, "description": "Unauthorized"}), [])

    def test_network_failure_does_not_raise(self):
        with patch.object(setup_check.requests, "get",
                          side_effect=RuntimeError("연결 끊김")):
            self.assertEqual(discover_chat_ids("https://api.telegram.org/botX"), [])


class TestTelegramCheck(unittest.TestCase):
    def test_missing_token_reports_actionable_hint(self):
        with patch.object(setup_check, "env", return_value=""):
            results = setup_check.check_telegram(send_test=False)
        self.assertFalse(results[0].ok)
        self.assertIn("BotFather", results[0].hint)

    def test_bad_token_is_reported_as_rejected(self):
        def fake_env(name, default=""):
            return "틀린토큰" if name == "TELEGRAM_BOT_TOKEN" else ""

        payload = {"ok": False, "description": "Unauthorized"}
        with patch.object(setup_check, "env", side_effect=fake_env), \
             patch.object(setup_check.requests, "get",
                          return_value=FakeResponse(payload)):
            results = setup_check.check_telegram(send_test=False)
        self.assertFalse(results[0].ok)
        self.assertIn("Unauthorized", results[0].detail)

    def test_valid_token_without_chat_id_suggests_discovered_value(self):
        def fake_env(name, default=""):
            return "좋은토큰" if name == "TELEGRAM_BOT_TOKEN" else ""

        def fake_get(url, **kwargs):
            if url.endswith("/getMe"):
                return FakeResponse({"ok": True, "result": {"username": "kpetro_bot"}})
            return FakeResponse({"ok": True, "result": [
                {"message": {"chat": {"id": 999, "first_name": "담당자"}}}
            ]})

        with patch.object(setup_check, "env", side_effect=fake_env), \
             patch.object(setup_check.requests, "get", side_effect=fake_get):
            results = setup_check.check_telegram(send_test=False)

        self.assertTrue(results[0].ok)
        self.assertIn("kpetro_bot", results[0].detail)
        self.assertFalse(results[1].ok)
        self.assertIn("999", results[1].detail)


class TestExitCode(unittest.TestCase):
    def test_optional_naver_alone_does_not_fail_the_run(self):
        """선택 항목만 비어 있으면 초록불이어야 매번 빨간불에 둔감해지지 않습니다."""
        results = [
            Result("텔레그램 봇 토큰", True, "정상"),
            Result("네이버 검색 API", False, "비어 있음 (선택 항목)"),
        ]
        with patch.object(setup_check, "check_telegram", return_value=[results[0]]), \
             patch.object(setup_check, "check_naver", return_value=[results[1]]), \
             patch.object(setup_check, "check_gmail", return_value=[]), \
             patch.object(setup_check, "check_review_page", return_value=[]):
            self.assertEqual(setup_check.main([]), 0)

    def test_required_failure_returns_nonzero(self):
        with patch.object(setup_check, "check_telegram",
                          return_value=[Result("텔레그램 봇 토큰", False, "비어 있음")]), \
             patch.object(setup_check, "check_naver", return_value=[]), \
             patch.object(setup_check, "check_gmail", return_value=[]), \
             patch.object(setup_check, "check_review_page", return_value=[]):
            self.assertEqual(setup_check.main([]), 1)


if __name__ == "__main__":
    unittest.main()
