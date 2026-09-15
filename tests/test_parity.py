"""검토 페이지 미리보기(JS)와 실제 발송본(Python)이 같은 글자를 내는지 확인.

담당자는 미리보기를 보고 '이대로 나가겠구나' 판단합니다. 둘이 어긋나면
엉뚱한 내용이 전 직원에게 갑니다. 그래서 형식이 아니라 전체 문자열을
그대로 비교합니다.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from scripts.config import load_config
from scripts.models import Article
from scripts.render import render_plain
from tests.fixtures import sample_digest

HARNESS = Path(__file__).parent / "parity.mjs"


def js_plain(digest, excluded=()):
    payload = json.dumps(
        {"digest": digest.to_dict(), "excluded": list(excluded)}, ensure_ascii=False
    )
    result = subprocess.run(
        ["node", str(HARNESS)], input=payload, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(f"parity.mjs 실행 실패:\n{result.stderr}")
    return result.stdout


@unittest.skipIf(shutil.which("node") is None, "node 없음")
class TestPreviewParity(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def assert_same(self, digest, excluded=()):
        self.assertEqual(js_plain(digest, excluded),
                         render_plain(digest, self.config, set(excluded)))

    def test_plain_case(self):
        self.assert_same(sample_digest())

    def test_with_exclusions(self):
        digest = sample_digest()
        self.assert_same(digest, [digest.articles[2].id, digest.articles[4].id])

    def test_all_risk_articles_excluded(self):
        digest = sample_digest()
        self.assert_same(digest, [a.id for a in digest.articles if a.risk])

    def test_sector_limit_overflow(self):
        digest = sample_digest()
        digest.articles += [
            Article(title=f"추가 기사 {i}", url=f"https://z/{i}", source="매체",
                    published="2026-09-16 05:00", sector="energy")
            for i in range(9)
        ]
        self.assert_same(digest)
        # 상한을 넘긴 상태에서 앞 기사를 빼면 뒤 기사가 올라옵니다.
        # 이 승격 규칙이 양쪽에서 같아야 합니다.
        self.assert_same(digest, [digest.articles[2].id])

    def test_no_market_data(self):
        digest = sample_digest()
        digest.market = []
        self.assert_same(digest)

    def test_everything_excluded(self):
        digest = sample_digest()
        self.assert_same(digest, [a.id for a in digest.articles])

    def test_quotes_and_special_characters(self):
        digest = sample_digest()
        digest.articles[0].title = '「단독」 석유관리원 "품질검사" 40%↑ … 논란 & 파장'
        self.assert_same(digest)


if __name__ == "__main__":
    unittest.main()
