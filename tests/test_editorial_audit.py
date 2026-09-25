import copy
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts import alerts, analysis, editorial, market, morning, rolling, screening, weekly
from scripts.config import load_config
from scripts.dedupe import dedupe, same_story
from scripts.digest import Digest
from scripts.models import Article
from tests.test_alerts import NOW, article
from tests.test_parity import js_plain
from scripts.render import render_plain


class EditorialAuditTests(unittest.TestCase):
    def test_ai_event_identity_wins_over_title_similarity(self):
        a = article('석유관리원 진주·진해 무상 품질점검')
        b = article('가짜석유 피해 막는다…주민과 장병 연료 검사', 'https://n/2')
        a.event_key = b.event_key = '진주진해 연료점검 행사'
        self.assertEqual(len(dedupe([a, b])), 1)
        b.event_key = '추가 피해 확인 및 정부 조치'
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_fallback_cross_sector_statistics_and_new_casualties(self):
        a = article("명절 연휴 불법 석유 판매 업소 최근 5년간 59곳 적발")
        b = article("명절마다 불량 주유 적발…5년간 주유소 등 59곳 걸렸다", 'https://n/2')
        a.sector, b.sector = 'government', 'energy'
        self.assertEqual(len(dedupe([a, b])), 1)
        self.assertFalse(same_story('울산 정유공장 폭발 2명 부상', '울산 정유공장 폭발 12명 부상'))
        self.assertFalse(same_story('호르무즈 선박 피격', '호르무즈 선박 추가 피격'))

    def test_fallback_old_event_does_not_hide_new_day_incident(self):
        a = article('모스크바 정유공장 피격')
        b = article('우크라 공습으로 모스크바 정유공장 피격', 'https://n/2')
        b.published = (NOW + timedelta(days=3)).strftime('%Y-%m-%d %H:%M')
        self.assertEqual(len(dedupe([a,b])), 2)

    def test_urgent_explanations_statistics_and_old_event_veto(self):
        for title in [
            '호르무즈 봉쇄가 뒤바꾼 유럽 해상풍력 100GW 레이스: 금융 재편',
            '미 국무부 호르무즈 봉쇄에 중동 여행 재고 권고',
            '배는 사라졌는데 원유는 쏟아진다…호르무즈 봉쇄의 비밀',
            '명절 불법 석유 판매 최근 5년간 59곳 적발',
            '지난 17일 발생한 울산 정유공장 폭발 원인 소개',
        ]:
            with self.subTest(title=title):
                self.assertIsNone(alerts.urgent_reason(article(title), alerts.load_rules()))
        self.assertIsNotNone(alerts.urgent_reason(article('울산 정유공장 폭발 추가 사망 2명'), alerts.load_rules()))

    def test_previous_market_day_not_publication_time(self):
        now = NOW.replace(day=20)
        a = article('사우디 송유관 복구 추진 등에 9월18 국제유가 하락')
        self.assertTrue(editorial.stale_market(a, now))
        a.title = '9월19일 국제유가 하락'
        self.assertFalse(editorial.stale_market(a, now))
        self.assertFalse(editorial.stale_market(article('정부 9월18일 발표한 유류세 정책 오늘 확정'), now))

    def test_daily_fallback_drops_previous_selection(self):
        a = article()
        state = {}
        rolling.accumulate(state, [a], NOW, load_config())
        with patch.object(morning.alerts, 'load_rules', return_value={'ai_screening': False}), \
             patch.object(analysis, 'analyze', side_effect=RuntimeError()), \
             patch.object(morning, 'market_brief', return_value=[]):
            d = morning.build(load_config(), state, NOW, previous_articles=[a])
        self.assertEqual(d.articles, [])
        self.assertTrue(d.fallback_notice)

    def test_weekly_ai_groups_and_promotions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a = article('석유관리원 진주 무상 품질점검')
            b = article('석유관리원 장병 연료 품질 검사', 'https://n/2')
            a.event_key = b.event_key = '동일 행사'
            a.sector = b.sector = 'kpetro'
            promo = article('S-OIL 브랜드 마케팅 혁신 호평', 'https://n/3')
            promo.sector = 'energy'
            Digest(date=NOW.date().isoformat(), articles=[a,b,promo]).save(root / f'{NOW.date()}.json')
            with patch.object(weekly, 'DRAFT_DIR', root), patch.object(weekly, 'EXCLUSION_DIR', root), \
                 patch.object(weekly, 'now_kst', return_value=NOW):
                text, count = weekly.build(load_config())
            self.assertEqual(count, 1)
            self.assertIn('중복 제외 1건', text)
            self.assertNotIn('마케팅', text)

    def test_screening_context_uses_related_sent_event(self):
        a = article('모스크바 정유공장 피격')
        state = {'sent': [{'title': '모스크바 정유공장 피격', 'ai_event': '모스크바 공습'}]}
        rolling.accumulate(state, [a], NOW, load_config())
        captured = []
        def complete(payload, validator, state, persist):
            captured.append(payload['contents'][0]['parts'][0]['text'])
            return validator({'decisions': [dict(id=a.id, relevant=False, urgent=False,
                freshness='recap', event_key='모스크바 공습', reason='기존 사건 재보도')]}), {}, 1, 'test'
        with patch.object(analysis, 'complete', side_effect=complete):
            screening.run(state, NOW, Mock())
        self.assertIn('이미 긴급 발송', captured[0])
        self.assertEqual(screening.approved(state, [a], urgent=True), [])


class MarketTests(unittest.TestCase):
    def data(self):
        base = NOW.timestamp()
        return {'chart': {'result': [{'meta': {'symbol': 'CL=F', 'currency': 'USD',
            'instrumentType': 'FUTURE', 'exchangeTimezoneName': 'Asia/Seoul',
            'currentTradingPeriod': {'regular': {'start': base - 3600, 'end': base + 3600}}},
            'timestamp': [base - 2*86400, base - 86400, base],
            'indicators': {'quote': [{'close': [70, 77, 999]}]}}]}}

    def quote(self, data):
        response = Mock(); response.json.return_value = data
        with patch.object(market.requests, 'get', return_value=response), patch.object(market, 'now_kst', return_value=NOW):
            return market._oil_quote('WTI', 'CL=F')

    def test_unfinished_bar_excluded_and_change_uses_prior_close(self):
        q = self.quote(self.data())
        self.assertEqual(q.value, 77)
        self.assertEqual(q.change_pct, 10)
        self.assertEqual(q.as_of, '2026-09-18')
        self.assertIn('선물 일봉 종가', q.format())

    def test_stale_wrong_symbol_invalid_quote_rejected(self):
        for mutation in ('stale', 'symbol', 'nan'):
            data = self.data(); row = data['chart']['result'][0]
            if mutation == 'stale': row['timestamp'] = [s - 10*86400 for s in row['timestamp']]
            if mutation == 'symbol': row['meta']['symbol'] = 'OTHER'
            if mutation == 'nan': row['indicators']['quote'][0]['close'] = [None, float('nan'), None]
            self.assertIsNone(self.quote(data))

    def test_failure_does_not_remove_currency(self):
        q = market.Quote('원/달러', 1400, None, '원')
        with patch.object(market, '_oil_quote', return_value=None), patch.object(market, '_usd_krw', return_value=q):
            self.assertEqual(market.market_brief(), [q])

    def test_metadata_matches_browser_preview(self):
        d = Digest(date='2026-09-19', market=[self.quote(self.data()).__dict__])
        self.assertEqual(js_plain(d), render_plain(d, load_config()))
