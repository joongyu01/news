import unittest
from datetime import datetime
from unittest.mock import patch, Mock

from scripts import daily_report
from scripts.sources import KST


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 25, 20, tzinfo=KST)
        self.prefs = {'owner': '123', 'chats': {'123': {}, '-987': {}}}

    def test_failure_unknown_and_distinct_deliveries(self):
        state = {'pool': {'articles': [{'id': 'a', 'published': '2026-09-25 12:00'}]},
                 'sent': [{'id': 'a', 'sent_at': '2026-09-25T12:00:00+09:00', 'chat': c} for c in ['123', '-987']]}
        text = daily_report.format_report(self.now, state, self.prefs, None, {'fallback_notice': 'failed'})
        self.assertIn('조회 실패 (0회가 아닙니다)', text)
        self.assertIn('기사 1건 / 수신방별 합계 2건', text)
        self.assertIn('AI 실패 → 기본 스크랩', text)
        self.assertIn('집계 기록 없음', text)

    def test_pagination_and_kst_day(self):
        rows = [{'id': i, 'path': '.github/workflows/alerts.yml', 'conclusion': 'success'} for i in range(100)]
        responses = [Mock(ok=True, json=lambda: {'workflow_runs': rows}),
                     Mock(ok=True, json=lambda: {'workflow_runs': [{'id': 100, 'path': '.github/workflows/screening.yml', 'conclusion': 'failure'}]})]
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'test', 'GITHUB_REPOSITORY': 'joongyu01/news'}), patch('scripts.daily_report.requests.get', side_effect=responses) as get:
            counts = daily_report.workflow_counts(self.now)
        self.assertEqual(counts['수집']['success'], 100)
        self.assertEqual(counts['긴급 선별']['failed'], 1)
        self.assertTrue(get.call_args_list[0].kwargs['params']['created'].startswith('2026-09-24T15:00:00+00:00'))

    def test_owner_only_and_repeat_guard(self):
        with patch('scripts.daily_report.preferences.load', return_value={**self.prefs, 'owner': '-987'}), patch('scripts.daily_report.send_telegram') as send:
            with self.assertRaises(RuntimeError):
                daily_report.run()
            send.assert_not_called()
        prefs = {**self.prefs, 'daily_report': {'sent_date': '2026-09-25'}}
        with patch('scripts.daily_report.now_kst', return_value=self.now), patch('scripts.daily_report.preferences.load', return_value=prefs), patch.dict('os.environ', {'TELEGRAM_CHAT_ID': '123'}), patch('scripts.daily_report.send_telegram') as send:
            daily_report.run()
            send.assert_not_called()

    def test_delivery_never_fans_out(self):
        with patch('scripts.daily_report.now_kst', return_value=self.now), patch('scripts.daily_report.preferences.load', return_value=self.prefs), patch.dict('os.environ', {'TELEGRAM_CHAT_ID': '123'}), patch('scripts.daily_report.workflow_counts', return_value={}), patch('scripts.daily_report.alerts.read_state', return_value=None), patch('scripts.daily_report.storage.request', side_effect=RuntimeError), patch('scripts.daily_report.chat_info', return_value={}), patch('scripts.daily_report.update') as update, patch('scripts.daily_report.send_telegram', return_value=1) as send:
            daily_report.run()
            self.assertEqual(send.call_args.kwargs, {'chat_id': '123'})
            self.assertEqual(len(send.call_args.args[0]), 1)
            update.assert_called_once()

