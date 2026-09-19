"""수집 -> 분류 -> 중복묶기 -> 렌더링 전 구간 검증."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.classify import classify_all, is_blocked, risks_for, sector_for
from scripts.classify import _query_sector
from scripts.config import load_config
from scripts.dedupe import dedupe, similarity
from scripts.digest import Digest, load_exclusions
from scripts.models import Article, canonical_url
from scripts.render import render_markdown, render_plain, split_for_telegram
from tests.fixtures import sample_digest


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.qmap = _query_sector(self.config)

    def test_must_keyword_beats_query(self):
        """'국제유가'로 검색돼 들어왔어도 석유관리원이 언급되면 석유관리원 뉴스."""
        article = Article(
            title="석유관리원, 국제유가 급등에 품질검사 확대",
            url="https://x/1", source="에너지신문", query="국제유가",
        )
        self.assertEqual(sector_for(article, self.config, self.qmap), "kpetro")

    def test_query_decides_when_no_must(self):
        article = Article(title="정유사 실적 개선", url="https://x/2",
                          source="A", query="정유업계")
        self.assertEqual(sector_for(article, self.config, self.qmap), "energy")

    def test_rss_article_falls_back_to_keywords(self):
        """업계지 RSS는 검색어가 없으므로 any 키워드로 판정됩니다."""
        article = Article(title="한국가스공사 경영평가 결과 발표", url="https://x/3",
                          source="가스신문", query="rss:가스신문")
        self.assertEqual(sector_for(article, self.config, self.qmap), "public")

    def test_unrelated_article_is_dropped(self):
        article = Article(title="프로야구 한국시리즈 1차전", url="https://x/4",
                          source="스포츠", query="rss:가스신문")
        self.assertIsNone(sector_for(article, self.config, self.qmap))

    def test_requested_monitor_topics_survive_rss_classification(self):
        for title, sector in [("에너지시장감시단 조사 발표", "energy"),
                              ("에너지 시장 감시단 조사 발표", "energy"),
                              ("에너지·석유시장감시단 유통 실태 보고서", "energy"),
                              ("에너지자원공사 본사 입지 논의", "public"),
                              ("석유·가스공사 통합 법안 발의", "public")]:
            with self.subTest(title=title):
                item = Article(title=title, url="https://x/topic", source="A", query="rss:업계지")
                self.assertEqual(sector_for(item, self.config, self.qmap), sector)

    def test_blocklist(self):
        self.assertTrue(is_blocked(Article(title="[부고] 홍길동 모친상",
                                           url="https://x/5", source="A"), self.config))
        self.assertFalse(is_blocked(Article(title="정상 기사",
                                            url="https://x/6", source="A"), self.config))

    def test_risk_keywords(self):
        article = Article(title="가짜석유 판매 주유소 적발, 검찰 고발",
                          url="https://x/7", source="A")
        self.assertEqual(risks_for(article, self.config), ["가짜석유", "검찰", "고발"])

    def test_classify_all_assigns_and_filters(self):
        articles = [
            Article(title="석유관리원 품질검사 강화", url="https://x/8", source="A", query="석유관리원"),
            Article(title="[부고] 아무개 부친상", url="https://x/9", source="A", query="석유관리원"),
            Article(title="오늘의 날씨", url="https://x/10", source="A", query="rss:x"),
        ]
        kept = classify_all(articles, self.config)
        self.assertEqual([a.sector for a in kept], ["kpetro"])
        self.assertEqual(kept[0].risk, ["품질검사"])


class TestDedupe(unittest.TestCase):
    def test_similar_titles_merge(self):
        self.assertGreater(
            similarity("유가 다시 120달러 급등 막던 3대 안전판 흔들린다",
                       "[종합] 유가 다시 120달러… 급등 막던 3대 안전판 흔들린다"), 0.9)

    def test_different_titles_do_not_merge(self):
        self.assertLess(similarity("석유관리원 LPG 품질 관리 강화",
                                   "트럼프 이란전 중간선거 전후 끝날 것"), 0.2)

    def test_merge_keeps_first_and_unions_risk(self):
        articles = [
            Article(title="檢, 담합 의혹 OCI 대표 소환", url="https://a/1",
                    source="A", sector="energy", risk=["담합"]),
            Article(title="검찰, 담합 의혹 OCI 대표 소환", url="https://a/2",
                    source="B", sector="energy", risk=["담합", "검찰"]),
        ]
        merged = dedupe(articles)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "A")
        self.assertEqual(len(merged[0].duplicates), 1)
        self.assertEqual(merged[0].risk, ["담합", "검찰"])

    def test_different_sectors_never_merge(self):
        """제목이 같아도 섹터가 다르면 각 섹터에 하나씩 남아야 합니다."""
        articles = [
            Article(title="석유 수급 안정 대책", url="https://a/1", source="A", sector="kpetro"),
            Article(title="석유 수급 안정 대책", url="https://a/2", source="B", sector="energy"),
        ]
        self.assertEqual(len(dedupe(articles)), 2)

    def test_identical_url_dropped(self):
        articles = [
            Article(title="가", url="https://a/1?utm_source=x", source="A", sector="energy"),
            Article(title="나", url="https://a/1", source="B", sector="energy"),
        ]
        self.assertEqual(len(dedupe(articles)), 1)

    def test_canonical_url_strips_tracking_only(self):
        self.assertEqual(canonical_url("https://n.news.naver.com/a?sid=101&utm_source=x"),
                         "https://n.news.naver.com/a?sid=101")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.digest = sample_digest()

    def test_plain_matches_house_style(self):
        text = render_plain(self.digest, self.config)
        self.assertTrue(text.startswith("한국석유관리원 26년 9월 16일 일일언론동향"))
        self.assertIn("[석유관리원 뉴스]", text)
        self.assertIn("1. ⚠️ 석유관리원, 전국 지자체와 LPG 품질·정량 관리 강화 / 에너지신문", text)
        self.assertIn("https://www.energy-news.co.kr/a/1", text)

    def test_duplicate_count_shown(self):
        self.assertIn("(외 2건)", render_plain(self.digest, self.config))

    def test_exclusion_removes_and_renumbers(self):
        excluded = {self.digest.articles[2].id}     # 에너지 섹터 1번 기사
        text = render_plain(self.digest, self.config, excluded)
        self.assertNotIn("OCI 대표 소환", text)
        self.assertIn("1. 유가 100달러 시대 다시 왔다 / 중앙일보", text)

    def test_risk_summary_reflects_exclusions(self):
        risky_ids = {a.id for a in self.digest.articles if a.risk}
        self.assertNotIn("⚠️ 주의", render_plain(self.digest, self.config, risky_ids))

    def test_sector_limit_applied(self):
        digest = sample_digest()
        digest.articles += [
            Article(title=f"추가 에너지 기사 {i}", url=f"https://z/{i}",
                    source="A", sector="energy") for i in range(10)
        ]
        text = render_plain(digest, self.config)
        energy_block = text.split("[에너지 뉴스]")[1]
        numbered = [l for l in energy_block.splitlines() if l and l[0].isdigit()]
        self.assertEqual(len(numbered), self.config.sector("energy").limit)

    def test_empty_sector_is_omitted(self):
        digest = sample_digest()
        digest.articles = [a for a in digest.articles if a.sector != "public"]
        self.assertNotIn("[공공기관 뉴스]", render_plain(digest, self.config))

    def test_markdown_includes_duplicate_links(self):
        md = render_markdown(self.digest, self.config)
        self.assertIn("# 한국석유관리원 일일언론동향 (2026년 9월 16일)", md)
        self.assertIn("(동일 사안) 연합뉴스:", md)

    def test_telegram_chunks_respect_limit(self):
        digest = sample_digest()
        digest.articles += [
            Article(title=f"긴 제목 기사 {i} " + "가" * 60, url=f"https://z/{i}",
                    source="매체", sector="energy") for i in range(40)
        ]
        chunks = split_for_telegram(render_plain(digest, self.config), limit=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 500)

    def test_single_chunk_when_short(self):
        self.assertEqual(len(split_for_telegram(render_plain(self.digest, self.config))), 1)


class TestDigestIO(unittest.TestCase):
    def test_round_trip(self):
        original = sample_digest()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            original.save(path)
            loaded = Digest.load(path)
        self.assertEqual(loaded.date, original.date)
        self.assertEqual([a.id for a in loaded.articles],
                         [a.id for a in original.articles])
        self.assertEqual(loaded.sectors, original.sectors)
        self.assertEqual(loaded.articles[2].duplicates, original.articles[2].duplicates)

    def test_article_id_is_stable_across_tracking_params(self):
        a = Article(title="t", url="https://x/a?sid=1", source="s")
        b = Article(title="t", url="https://x/a?sid=1&utm_medium=rss", source="s")
        self.assertEqual(a.id, b.id)

    def test_missing_exclusions_file(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(load_exclusions(Path(tmp) / "none.json"), set())

    def test_corrupt_exclusions_file_is_ignored(self):
        """제외 파일이 깨졌다고 발송이 멈추면 안 됩니다."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{ not json", encoding="utf-8")
            self.assertEqual(load_exclusions(path), set())

    def test_exclusions_parsed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.json"
            path.write_text(json.dumps({"excluded": ["a", "b"]}), encoding="utf-8")
            self.assertEqual(load_exclusions(path), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
