import copy
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from scripts import alerts
from scripts.config import load_config
from scripts.models import Article
from scripts.sources import KST

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=KST)


def article(title="울산 정유공장 폭발, 근로자 2명 부상", url="https://news.test/1", age=5):
    return Article(title=title, url=url, source="시험매체",
                   published=(NOW - timedelta(minutes=age)).strftime("%Y-%m-%d %H:%M"))


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.rules = alerts.load_rules()
        self.state = {"version": 1, "started_at": (NOW-timedelta(hours=6)).isoformat(), "sent": []}
        pref = patch.object(alerts.preferences, "load", return_value={"owner":"test", "chats":{"test":alerts.preferences.defaults()}})
        pref.start()
        self.addCleanup(pref.stop)

    def select(self, articles):
        return alerts.select_alerts(articles, self.state, self.rules, NOW, load_config())

    def test_relevant_emergencies(self):
        for title in ["석유관리원 간부 비리 혐의로 압수수색", "울산 정유공장 폭발",
                      "호르무즈 해협 봉쇄, 원유 공급 중단", "정부 비축유 방출 결정",
                      "가짜석유 전국 유통 조직 적발"]:
            with self.subTest(title=title):
                self.assertIsNotNone(alerts.urgent_reason(article(title), self.rules))

    def test_routine_or_unrelated_not_urgent(self):
        for title in ["석유관리원, 가짜석유 예방 무상점검", "정유공장 폭발 대비훈련",
                      "[속보] 야구팀 감독 사퇴", "국제유가 급등 전망", "주유소 폭발 우려",
                      "석유관리원 품질검사 확대", "비축유 방출 가능성", "정유공장 화재 예방 캠페인",
                      "원유 공급 중단 없다", "호르무즈 봉쇄 해제", "정유공장 폭발은 사실무근"]:
            with self.subTest(title=title):
                self.assertIsNone(alerts.urgent_reason(article(title), self.rules))

    def test_missing_stale_future_and_bad_url_rejected(self):
        missing = article(); missing.published = ""
        malformed = article(); malformed.published = "nonsense"
        self.assertEqual(self.select([missing, malformed, article(age=361), article(age=-20),
                                      article(url="javascript:bad")]), [])

    def test_requested_topics_include_reports_and_policy_reversals(self):
        for title, topic in [
            ("에너지시장감시단, 가격 조사 결과 발표", "energy_watchdog"),
            ("에너지·석유시장감시단, 유통 마진 분석 발표", "energy_watchdog"),
            ("에너지 시장 감시단, 공급 차질 우려 제기", "energy_watchdog"),
            ("석유 시장 감시단, 신규 조사 보고서 공개", "energy_watchdog"),
            ("석유공사·가스공사 통합 법안 발의", "oil_gas_integration"),
            ("석유·가스公 합병 추진", "oil_gas_integration"),
            ("가스공사, 석유공사 통합 계획 보도 부인", "oil_gas_integration"),
            ("석유공사 노조, 통합에 우려…재검토 촉구", "oil_gas_integration"),
            ("에너지자원공사 본사 입지 논의", "oil_gas_integration"),
            ("석유공사 기능 이관 검토", "oil_gas_integration"),
        ]:
            with self.subTest(title=title):
                selected = alerts.select_alerts([article(title)], self.state, self.rules,
                                                NOW, load_config(), {"mode": "strict"})
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0][1]["id"], topic)
                self.assertTrue(alerts.message(*selected[0]).startswith("📰 관심 주제 업데이트"))

    def test_requested_topics_do_not_broaden_to_unrelated_company_news(self):
        for title in ["한국가스공사 신입사원 채용", "석유공사 통합안전관리 시스템 도입",
                      "가스공사 통합 관제 플랫폼 구축", "환경성적표지 시장감시단 출범",
                      "[칼럼] 석유공사·가스공사 통합 전망", "에너지자원공사 관련 테마주 주가 상승"]:
            with self.subTest(title=title):
                self.assertIsNone(alerts.urgent_reason(article(title), self.rules))
        self.assertIsNone(alerts.urgent_reason(article("에너지시장감시단 조사 발표"),
                                               self.rules, {"exclude": ["감시단"]}))

    def test_same_url_and_syndicated_title_deduplicated(self):
        a = article()
        self.assertEqual(len(self.select([a, a, article("[속보] " + a.title, "https://other.test/2")])), 1)
        self.state["sent"] = [{"id": a.id, "title": a.title, "rule": "accident", "sent_at": NOW.isoformat()}]
        self.assertEqual(self.select([article(url="https://other.test/3")]), [])
        # 피해 규모가 달라진 후속 보도는 허용합니다.
        self.assertEqual(len(self.select([article(a.title.replace("2명", "12명"), "https://other.test/4")])), 1)

    def test_bootstrap_recent_only_and_batch_cap(self):
        self.state["started_at"] = (NOW-timedelta(minutes=15)).isoformat()
        self.assertEqual(self.select([article(age=16)]), [])
        candidates = [article(f"{i}번 정유공장 폭발, {i}명 부상", f"https://news.test/{i}") for i in range(10)]
        self.assertEqual(len(self.select(candidates)), 3)

    def test_history_is_bounded_by_age_and_count(self):
        self.state["sent"] = [{"sent_at": (NOW-timedelta(days=8)).isoformat()}] + [
            {"id": str(i), "sent_at": NOW.isoformat()} for i in range(510)]
        alerts.trim_history(self.state, self.rules, NOW)
        self.assertEqual(len(self.state["sent"]), 500)
        self.assertEqual(self.state["sent"][0]["id"], "10")

    def simulate(self, **kwargs):
        return alerts.run(self.rules, **kwargs)

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"})
    def test_delivery_recorded_then_repeat_silent(self):
        db = [copy.deepcopy(self.state)]
        with patch.object(alerts, "now_kst", return_value=NOW), \
             patch.object(alerts, "read_state", side_effect=lambda: copy.deepcopy(db[0])), \
             patch.object(alerts, "save_state", side_effect=lambda s: db.__setitem__(0, copy.deepcopy(s))), \
             patch.object(alerts, "gather", return_value=[article()]), \
             patch.object(alerts, "send_telegram", return_value=1) as send:
            self.assertEqual(self.simulate(), 1)
            self.assertEqual(self.simulate(), 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(set(db[0]["sent"][0]), {"id", "title", "rule", "sent_at", "chat", "topic"})

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"})
    def test_db_read_or_initial_write_failure_never_sends(self):
        for read_error in (True, False):
            with patch.object(alerts, "now_kst", return_value=NOW), \
                 patch.object(alerts, "read_state", side_effect=RuntimeError() if read_error else None,
                              return_value=self.state), \
                 patch.object(alerts, "gather", return_value=[article()]), \
                 patch.object(alerts, "save_state", side_effect=RuntimeError()), \
                 patch.object(alerts, "send_telegram") as send:
                with self.assertRaises(RuntimeError):
                    self.simulate()
                send.assert_not_called()

    def test_dry_run_never_writes_or_sends(self):
        with patch.object(alerts, "now_kst", return_value=NOW), \
             patch.object(alerts, "read_state", return_value=self.state), \
             patch.object(alerts, "gather", return_value=[article()]), \
             patch.object(alerts, "save_state") as save, patch.object(alerts, "send_telegram") as send:
            self.assertEqual(self.simulate(dry_run=True, send_test=True), 1)
        save.assert_not_called(); send.assert_not_called()

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"})
    def test_failed_send_not_marked_sent(self):
        snapshots = []
        with patch.object(alerts, "now_kst", return_value=NOW), \
             patch.object(alerts, "read_state", return_value=copy.deepcopy(self.state)), \
             patch.object(alerts, "gather", return_value=[article()]), \
             patch.object(alerts, "save_state", side_effect=lambda s: snapshots.append(copy.deepcopy(s))), \
             patch.object(alerts, "send_telegram", return_value=0):
            with self.assertRaises(RuntimeError):
                self.simulate()
        self.assertEqual(snapshots[-1]["sent"], [])

    def test_source_fallback_and_total_outage(self):
        with patch.object(alerts, "naver_available", return_value=True), \
             patch.object(alerts, "fetch_naver", side_effect=RuntimeError()), \
             patch.object(alerts, "fetch_google_news", return_value=[article()]):
            self.assertTrue(alerts.gather(self.rules))
        with patch.object(alerts, "naver_available", return_value=False), \
             patch.object(alerts, "fetch_google_news", side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):
                alerts.gather(self.rules)
