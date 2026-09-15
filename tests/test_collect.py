"""수집 진입점 통합 검증.

실제 네트워크를 타지 않고, 소스 어댑터만 가짜로 바꿔 끼워
gather -> 신선도 -> 분류 -> 중복묶기 -> 초안 까지 한 번에 확인합니다.
"""

import unittest
from unittest.mock import patch

from scripts import collect
from scripts.config import load_config
from scripts.models import Article, now_kst


def _fresh_time(hours_ago: int = 1) -> str:
    from datetime import timedelta
    return (now_kst() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M")


FAKE_RESULTS = {
    "한국석유관리원": [
        Article(title="석유관리원, 품질검사 확대 시행", url="https://a/kp1",
                source="에너지신문", published=_fresh_time(), query="한국석유관리원"),
        # 같은 사안을 다른 매체가 쓴 것 — 묶여야 합니다
        Article(title="한국석유관리원, 품질검사 확대 시행한다", url="https://a/kp2",
                source="투데이에너지", published=_fresh_time(2), query="한국석유관리원"),
    ],
    "국제유가": [
        Article(title="국제유가 배럴당 90달러 돌파", url="https://a/e1",
                source="연합뉴스", published=_fresh_time(), query="국제유가"),
        # 오래된 기사 — 신선도에서 걸러져야 합니다
        Article(title="지난달 유가 동향 정리", url="https://a/e2",
                source="연합뉴스", published="2026-01-01 09:00", query="국제유가"),
        # 차단 목록 — 수집 단계에서 빠져야 합니다
        Article(title="[부고] 아무개 위원 모친상", url="https://a/e3",
                source="연합뉴스", published=_fresh_time(), query="국제유가"),
    ],
    "공공기관 경영평가": [
        Article(title="한국가스공사 경영평가 C등급", url="https://a/p1",
                source="뉴시스", published=_fresh_time(), query="공공기관 경영평가"),
    ],
}


def fake_naver(query, display=30):
    # 리스트를 그대로 돌려주면 테스트끼리 같은 객체를 공유하게 됩니다.
    return [Article(**{**a.__dict__}) for a in FAKE_RESULTS.get(query, [])]


def fake_trade_feeds():
    return [
        Article(title="가짜석유 판매 주유소 무더기 적발", url="https://a/t1",
                source="가스신문", published=_fresh_time(), query="rss:가스신문"),
        # 어느 섹터에도 안 걸리는 기사 — 버려져야 합니다
        Article(title="프로야구 한국시리즈 개막", url="https://a/t2",
                source="가스신문", published=_fresh_time(), query="rss:가스신문"),
    ]


class TestCollectPipeline(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def build(self):
        with patch.object(collect, "naver_available", return_value=True), \
             patch.object(collect, "fetch_naver", side_effect=fake_naver), \
             patch.object(collect, "fetch_trade_feeds", side_effect=fake_trade_feeds), \
             patch.object(collect, "market_brief", return_value=[]):
            return collect.build(self.config)

    def test_pipeline_produces_expected_articles(self):
        digest = self.build()
        titles = [a.title for a in digest.articles]

        self.assertIn("석유관리원, 품질검사 확대 시행", titles)
        self.assertIn("국제유가 배럴당 90달러 돌파", titles)
        self.assertIn("한국가스공사 경영평가 C등급", titles)
        self.assertIn("가짜석유 판매 주유소 무더기 적발", titles)

        self.assertNotIn("지난달 유가 동향 정리", titles)      # 오래됨
        self.assertNotIn("[부고] 아무개 위원 모친상", titles)   # 차단 목록
        self.assertNotIn("프로야구 한국시리즈 개막", titles)    # 섹터 없음

    def test_duplicate_merged_into_representative(self):
        digest = self.build()
        rep = next(a for a in digest.articles if a.title.startswith("석유관리원, 품질검사"))
        self.assertEqual(len(rep.duplicates), 1)
        self.assertEqual(rep.duplicates[0]["source"], "투데이에너지")

    def test_risk_articles_sorted_first(self):
        digest = self.build()
        self.assertTrue(digest.articles[0].risk,
                        "리스크 기사가 맨 앞에 와야 담당자가 먼저 봅니다")

    def test_sector_assignment(self):
        digest = self.build()
        by_title = {a.title: a.sector for a in digest.articles}
        self.assertEqual(by_title["석유관리원, 품질검사 확대 시행"], "kpetro")
        self.assertEqual(by_title["한국가스공사 경영평가 C등급"], "public")
        self.assertEqual(by_title["가짜석유 판매 주유소 무더기 적발"], "energy")

    def test_sector_metadata_embedded(self):
        """검토 페이지가 config/news.yml 을 읽지 않아도 되도록 초안에 넣어둡니다."""
        digest = self.build()
        self.assertEqual([s["id"] for s in digest.sectors],
                         [s.id for s in self.config.sectors])
        self.assertTrue(all("title" in s and "limit" in s for s in digest.sectors))

    def test_source_failure_does_not_break_run(self):
        """검색어 하나가 터져도 나머지로 그날 동향은 나가야 합니다."""
        def flaky(query, display=30):
            if query == "국제유가":
                raise RuntimeError("API 한도 초과")
            return fake_naver(query)

        with patch.object(collect, "naver_available", return_value=True), \
             patch.object(collect, "fetch_naver", side_effect=flaky), \
             patch.object(collect, "fetch_trade_feeds", side_effect=fake_trade_feeds), \
             patch.object(collect, "market_brief", return_value=[]):
            digest = collect.build(self.config)

        self.assertTrue(digest.articles)
        self.assertNotIn("국제유가 배럴당 90달러 돌파", [a.title for a in digest.articles])

    def test_rendered_output_is_wellformed(self):
        from scripts.render import render_plain
        text = render_plain(self.build(), self.config)
        self.assertIn("일일언론동향", text)
        self.assertIn("[석유관리원 뉴스]", text)
        self.assertIn("⚠️ 주의", text)


if __name__ == "__main__":
    unittest.main()
