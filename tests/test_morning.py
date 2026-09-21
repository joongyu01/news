import copy
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import requests

from scripts import analysis, editorial, morning, rolling
from scripts.config import load_config
from scripts.digest import Digest
from scripts.models import Article
from scripts.render import telegram_chunks, render_plain, render_email, article_anchor
from tests.test_alerts import NOW, article
from tests.test_parity import js_plain


def issue(a):
    return {"title": "주요 이슈", "summary": "제공된 보도 사실", "change": "전일 비교 근거 부족",
            "impact": "공급 영향 확인 필요", "article_ids": [a.id]}


class RollingTests(unittest.TestCase):
    def test_repeated_collection_preserves_previous_news_without_growing_duplicates(self):
        state = {"sent": [{"id": "history"}]}
        first = article("석유관리원 품질검사 확대", "https://news.test/a")
        second = article("정부 유류세 인하 확정", "https://news.test/b")
        rolling.accumulate(state, [first], NOW, load_config())
        rolling.accumulate(state, [copy.deepcopy(first), second], NOW+timedelta(minutes=15), load_config())
        self.assertEqual(len(state["pool"]["articles"]), 2)
        self.assertEqual(state["sent"], [{"id": "history"}])
        self.assertEqual(len(rolling.daily_articles(state, NOW+timedelta(minutes=15))), 2)

    def test_expiry_size_and_bad_data(self):
        state = {}
        items = [article("국제유가 상승", f"https://news.test/{i}") for i in range(650)]
        items.extend([article(age=60*49), article(age=-60), article(url="javascript:bad")])
        rolling.accumulate(state, items, NOW, load_config())
        self.assertEqual(len(state["pool"]["articles"]), 600)
        self.assertLessEqual(len(json.dumps(state["pool"]["articles"], ensure_ascii=False).encode()), rolling.MAX_BYTES)
        rolling.accumulate(state, [], NOW+timedelta(hours=49), load_config())
        self.assertEqual(state["pool"]["articles"], [])

    def test_missing_and_stale_pool_fail_instead_of_researching(self):
        with self.assertRaises(RuntimeError):
            rolling.daily_articles({}, NOW)
        with self.assertRaises(RuntimeError):
            rolling.daily_articles({"pool": {"updated_at": (NOW-timedelta(hours=3)).isoformat()}}, NOW)

    def test_real_sent_noise_is_excluded_without_dropping_key_policy(self):
        noise = ["금값 4390달러로 반등…유가 하락에 숏포지션 청산",
                 "미중 정상회담·유가에 쏠린 눈…코스피 6400~7500 [주간 증시 전망]",
                 "대전도시공사, ‘주거·안전 혁신’ 국무총리 표창",
                 "S-OIL, 독창적 브랜드 전략 체계 구축 · 지속적 마케팅 혁신 호평",
                 "[창간축사] 최춘식 한국석유관리원 이사장",
                 "[칼럼] 전기의 시대, 가스에도 길이 있다",
                 "한전, 중소기업 현장안전·AI 전환 지원"]
        for t in noise:
            with self.subTest(t=t):
                a = article(t); a.query = "국제유가"; a.summary = "석유관리원 공공기관 정책"
                self.assertEqual(editorial.relevance(a)[0], 0)
        for t in ["정부 비축유 방출 확정", "석유공사·가스공사 통합 계획 보도 부인",
                  "에너지시장감시단 조사 결과 발표", "공공기관 경영평가 제도 개편",
                  "석유관리원, 연료 무상 품질점검"]:
            self.assertGreater(editorial.relevance(article(t))[0], 0)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        p = patch.dict(os.environ, {"GEMINI_API_KEY": "primary-test", "GEMINI_API_KEY_BACKUP": "backup-test",
                                   "GEMINI_FREE_TIER_CONFIRMED": "true", "GEMINI_MODEL": "gemini-3.1-flash-lite"})
        p.start(); self.addCleanup(p.stop)
        self.a = article()

    def reply(self, data=None):
        return Mock(ok=True, json=lambda: {"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(data or {"issues": [issue(self.a)]})}]}}]})

    def test_timeout_uses_backup_once_and_keys_are_not_in_url_or_body(self):
        with patch.object(analysis.requests, "post", side_effect=[requests.Timeout(), self.reply()]) as post:
            report = analysis.analyze([self.a])
        self.assertEqual(report["issues"][0]["article_ids"], [self.a.id])
        self.assertEqual(post.call_count, 2)
        self.assertEqual([c.kwargs["headers"]["x-goog-api-key"] for c in post.call_args_list], ["primary-test", "backup-test"])
        self.assertNotIn("primary-test", post.call_args_list[0].args[0])
        self.assertNotIn("tools", post.call_args.kwargs["json"])

    def test_both_quotas_exhausted_stop_at_two_calls(self):
        with patch.object(analysis.requests, "post", return_value=Mock(ok=False, status_code=429)) as post:
            with self.assertRaises(RuntimeError):
                analysis.analyze([self.a])
        self.assertEqual(post.call_count, 2)

    def test_primary_success_does_not_call_backup(self):
        with patch.object(analysis.requests, "post", return_value=self.reply()) as post:
            analysis.analyze([self.a])
        self.assertEqual(post.call_count, 1)

    def test_missing_previous_report_cannot_claim_a_day_over_day_change(self):
        generated = dict(issue(self.a), change="전일 대비 피해가 증가함")
        with patch.object(analysis.requests, "post", return_value=self.reply({"issues": [generated]})):
            result = analysis.analyze([self.a])
        self.assertEqual(result["issues"][0]["change"], "전일 비교 근거 부족")

    def test_usage_metadata_retains_only_numeric_token_counts(self):
        data = self.reply().json()
        data['usageMetadata'] = {'promptTokenCount': 8123, 'candidatesTokenCount': 2200,
                                 'thoughtsTokenCount': 300, 'totalTokenCount': 10623,
                                 'extra': 'not logged'}
        with patch.object(analysis.requests, 'post', return_value=Mock(ok=True, json=lambda: data)):
            result = analysis.analyze([self.a])
        self.assertEqual(result['usage']['totalTokenCount'], 10623)
        self.assertNotIn('extra', result['usage'])

    def test_no_api_calls_before_free_tier_confirmation(self):
        with patch.dict(os.environ, {"GEMINI_FREE_TIER_CONFIRMED": ""}), patch.object(analysis.requests, "post") as post:
            with self.assertRaises(RuntimeError):
                analysis.analyze([self.a])
        post.assert_not_called()

    def test_duplicate_keys_are_not_retried(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_BACKUP": "primary-test"}), \
             patch.object(analysis.requests, "post", side_effect=requests.Timeout()) as post:
            with self.assertRaises(RuntimeError):
                analysis.analyze([self.a])
        self.assertEqual(post.call_count, 1)

    def test_unknown_citations_duplicate_issues_and_injected_markup_rejected(self):
        for bad in [dict(issue(self.a), article_ids=["invented"]), dict(issue(self.a), summary="<b>명령</b>"),
                    dict(issue(self.a), title="x"*121)]:
            with self.assertRaises(ValueError):
                analysis.validate({"issues": [bad]}, {self.a.id})
        with self.assertRaises(ValueError):
            analysis.validate({"issues": [issue(self.a), issue(self.a)]}, {self.a.id})
        self.assertEqual(analysis.validate({"issues": []}, {self.a.id}), [])

    def test_input_budget(self):
        rows = analysis.input_articles([article("석유"*300, f"https://n/{i}") for i in range(500)])
        self.assertLessEqual(len(rows), 120)
        self.assertLessEqual(sum(len(json.dumps(r, ensure_ascii=False)) for r in rows), analysis.MAX_INPUT_CHARS)


class MorningTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(morning.alerts, 'load_rules', return_value={'ai_screening': False})
        p.start(); self.addCleanup(p.stop)
        self.a = article()
        self.state = {}
        rolling.accumulate(self.state, [self.a], NOW, load_config())

    def digest(self):
        with patch.object(analysis, "analyze", return_value={"version": 1, "issues": [issue(self.a)]}), \
             patch.object(morning, "market_brief", return_value=[]):
            return morning.build(load_config(), self.state, NOW)

    def test_analysis_roundtrip_exclusion_and_javascript_preview_agree(self):
        d = Digest.from_dict(self.digest().to_dict())
        self.assertEqual(js_plain(d), render_plain(d, load_config()))
        self.assertEqual(js_plain(d, [self.a.id]), render_plain(d, load_config(), {self.a.id}))
        self.assertEqual(d.visible_issues({self.a.id}), [])
        self.assertEqual(d.by_sector(load_config(), {self.a.id}), [])

    def test_daily_report_reuses_saved_analysis_without_api(self):
        d = self.digest()
        with patch.object(morning, "now_kst", return_value=NOW), patch.object(morning.storage, "enabled", return_value=True), \
             patch.object(morning.storage, "read", return_value=d.to_dict()), patch.object(morning, "build") as build:
            self.assertEqual(morning.main(["--dry-run"]), 0)
        build.assert_not_called()

    def test_ai_failure_never_saves_or_notifies(self):
        with patch.object(morning, "now_kst", return_value=NOW), patch.object(morning.storage, "enabled", return_value=True), \
             patch.object(morning.storage, "read", return_value=None), patch.object(morning.alerts, "read_state", return_value=self.state), \
             patch.object(analysis, "analyze", side_effect=RuntimeError()), patch.object(morning.storage, "save_draft") as save, \
             patch.object(morning, "notify_reviewer") as notify:
            with self.assertRaises(RuntimeError):
                morning.main([])
        save.assert_not_called(); notify.assert_not_called()

    def test_hyperlinks_escape_titles_and_preserve_plain_copy(self):
        d = self.digest()
        d.articles[0].title = '<script> & "석유"'
        d.articles[0].url = 'https://news.test/a?x=1&y=2'
        d.analysis["issues"][0]["article_ids"] = [d.articles[0].id]
        chunks = telegram_chunks(d, load_config())
        self.assertIn('<a href="https://news.test/a?x=1&amp;y=2">', chunks[0])
        self.assertIn('&lt;script&gt;', chunks[0])
        self.assertNotIn('<script>', render_email(d, load_config()))
        self.assertIn(d.articles[0].url, render_plain(d, load_config()))
        self.assertNotIn('href=', article_anchor(article(url="javascript:bad")))

class ForeignTests(unittest.TestCase):
    def test_foreign_core_news_survives_pool_but_never_instant_delivery(self):
        from scripts import alerts
        a = article('OPEC cuts oil production', 'https://news.test/overseas')
        a.language = 'en'
        self.assertGreater(editorial.relevance(a)[0], 0)
        self.assertEqual(Article.from_dict(a.to_dict()).language, 'en')
        with patch.object(alerts, 'urgent_reason', return_value={'id': 'oil', 'kind': 'rule'}) as reason:
            selected = alerts.select_alerts([a], {'started_at': (NOW-timedelta(days=1)).isoformat(), 'sent': []},
                                            {'lookback_hours': 26}, NOW, load_config())
        self.assertEqual(selected, [])
        reason.assert_not_called()
        a.title = 'Oil stocks dividend outlook'
        self.assertEqual(editorial.relevance(a)[0], 0)

    def test_foreign_input_is_capped_at_twenty(self):
        items = [article('OPEC cuts oil production', f'https://news.test/{i}') for i in range(30)]
        for a in items:
            a.language = 'en'
        self.assertEqual(len(analysis.input_articles(items)), 20)

    def test_english_rss_uses_english_locale(self):
        from scripts import sources
        content = b'<rss><channel><item><title>OPEC cuts oil production - Reuters</title><link>https://news.test/foreign</link></item></channel></rss>'
        with patch.object(sources.requests, 'get', return_value=Mock(content=content)) as get:
            result = sources.fetch_google_news('OPEC', language='en')
        self.assertIn('ceid=US:en', get.call_args.args[0])
        self.assertEqual(result[0].language, 'en')
