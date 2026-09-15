"""테스트가 공유하는 표본 초안."""

from scripts.digest import Digest
from scripts.models import Article


def sample_digest() -> Digest:
    articles = [
        Article(
            title="석유관리원, 전국 지자체와 LPG 품질·정량 관리 강화",
            url="https://www.energy-news.co.kr/a/1", source="에너지신문",
            published="2026-09-16 08:10", sector="kpetro", risk=["품질검사"],
        ),
        Article(
            title="석유관리원, 수급업체 안전 보건망 구축 확대",
            url="https://www.todayenergy.kr/a/2", source="투데이에너지",
            published="2026-09-16 07:50", sector="kpetro",
        ),
        Article(
            title='檢, "석유화학제품 담합 의혹" OCI 대표 소환',
            url="https://n.news.naver.com/a/3", source="파이낸셜뉴스",
            published="2026-09-16 07:30", sector="energy",
            risk=["담합", "검찰"],
            duplicates=[
                {"title": "x", "source": "연합뉴스", "url": "https://n.news.naver.com/a/33"},
                {"title": "y", "source": "매일경제", "url": "https://n.news.naver.com/a/34"},
            ],
        ),
        Article(
            title="유가 100달러 시대 다시 왔다",
            url="https://n.news.naver.com/a/4", source="중앙일보",
            published="2026-09-16 07:00", sector="energy",
        ),
        Article(
            title="합산 부채 62조 '에너지 공룡' 출범 준비",
            url="https://n.news.naver.com/a/5", source="쿠키뉴스",
            published="2026-09-16 06:40", sector="public",
        ),
        Article(
            title="산업부, 석유사업법 시행령 개정안 입법예고",
            url="https://n.news.naver.com/a/6", source="연합뉴스",
            published="2026-09-16 06:20", sector="government",
        ),
    ]
    return Digest(
        date="2026-09-16",
        generated_at="2026-09-16 06:40",
        articles=articles,
        market=[
            {"label": "브렌트", "value": 78.2, "change_pct": 1.23, "unit": "$"},
            {"label": "WTI", "value": 74.1, "change_pct": -0.95, "unit": "$"},
            {"label": "원/달러", "value": 1380.5, "change_pct": None, "unit": "원"},
        ],
        sectors=[
            {"id": "kpetro", "title": "석유관리원 뉴스", "limit": 6},
            {"id": "public", "title": "공공기관 뉴스", "limit": 4},
            {"id": "government", "title": "정부·정책 뉴스", "limit": 4},
            {"id": "energy", "title": "에너지 뉴스", "limit": 6},
        ],
    )
