"""업무 관련성 필터. 검색에 걸렸다는 이유만으로 발송 후보에 넣지 않는다."""
import re

# 제목을 주 신호로 사용한다. 요약의 회사 소개나 검색어는 관련성 근거가 아니다.
FUEL = r"석유|원유|정유|주유소|휘발유|경유|등유|유류|나프타|납사|LPG|LNG|천연가스|비축유|유가|OPEC|호르무즈|바이오디젤|항공유|SAF|연료.*품질"
AGENCY = r"(?:한국)?석유관리원"
WATCHDOG = r"(?:에너지\s*(?:[·ㆍ・‧-]\s*)?(?:석유\s*)?|석유\s*)시장\s*감시단"
INTEGRATION = r"통합|합병|통폐합|기능\s*(?:이관|조정|재편)|본사|에너지\s*자원\s*공사"
PUBLIC_POLICY = r"경영평가|공공기관.*(?:혁신|개편|예산|인건비|임금|채용.*제도|지정|통폐합)|공기업.*(?:개편|경영|인건비)"
PROMO = r"창간축사|축사|봉사|환경정화|나눔|기부|표창|수상|최우수기관|브랜드|마케팅|사회공헌|업무협약|직무\s*탐색|신입사원|채용공고"
OPINION = r"\[(?:칼럼|기고|사설|기자수첩|창간|초대석)[^\]]*\]"
MARKETS = r"금값|금\s*시세|코스피|코스닥|주가|증시|테마주|목표주가|주식|비트코인|스토어\s*플래너|폐주유소.*편의점"
ACTION = r"적발|수사|구속|기소|고발|압수수색|과징금|담합|품질부적합|정량미달|불법유통|사망|폭발|화재|누출|공급\s*(?:중단|차질)|비리"


def urgent_exclusion(article):
    """Deterministic veto even when the model incorrectly approves a headline."""
    t = article.title
    if re.search(OPINION + "|" + MARKETS + r"|해상풍력|여행\s*(?:재고|자제|경보)|금융\s*(?:구조|재편)|방정식|의 비밀", t):
        return "해설·투자·여행 정보는 긴급 대상 아님"
    if re.search(r"최근\s*\d+년|\d+년간|되짚|돌아본|재조명", t):
        return "과거 누적 통계·회고"
    # A recap must not become urgent merely because it was posted today.
    if re.search(r"지난\s*(?:\d+월\s*)?\d+일|지난해|작년", t + " " + article.summary) and not re.search(r"오늘|방금|추가.*(?:사망|피해)|새로.*(?:확정|중단)|정부.*(?:명령|결정)", t):
        return "과거 사건 소개, 현재의 중요 변화 근거 없음"
    return ""


def stale_market(article, now):
    from datetime import date
    if not re.search(r"유가|시황", article.title):
        return False
    match = re.search(r"(\d{1,2})월\s*(\d{1,2})일?", article.title)
    if not match:
        return False
    try:
        day = date(now.year, *map(int, match.groups()))
        if (day - now.date()).days > 180:
            day = day.replace(year=now.year - 1)
        return (now.date() - day).days >= 2
    except ValueError:
        return False


def relevance(article):
    """(score, sector, reason); score=0 is excluded from daily analysis."""
    t = article.title
    if article.language == "en":
        fuel = r"\b(?:oil|petroleum|fuel|diesel|gasoline|LNG|OPEC|Hormuz|refinery|refineries)\b|natural gas"
        event = r"\b(?:supply|output|production|cuts?|exports?|imports?|sanctions?|disruption|halt|attack|closure|standards?|regulation|mandate|reserves?|release)\b"
        noise = r"\b(?:stocks?|shares?|dividend|investors?|forecast|outlook|opinion|awards?|sponsored)\b"
        if not re.search(fuel, t, re.I) or not re.search(event, t, re.I) or re.search(noise, t, re.I):
            return 0, None, "해외 핵심 수급·연료 제도 외 제외"
        return 70, "energy", "해외 핵심 수급·연료 제도"
    if re.search(OPINION, t) or re.search(MARKETS, t, re.I):
        return 0, None, "칼럼·투자·소비정보"
    if re.search(PROMO, t) and not re.search(ACTION, t):
        return 0, None, "행사·홍보·수상"
    if re.search(AGENCY, t):
        return 100, "kpetro", "석유관리원 직접 보도"
    if re.search(WATCHDOG, t):
        return 95, "energy", "에너지시장감시단"
    if re.search(r"석유\s*(?:공사|公)|가스\s*(?:공사|公)|에너지\s*자원\s*공사", t) and re.search(INTEGRATION, t):
        return 95, "public", "석유·가스 공공기관 개편"
    if re.search(PUBLIC_POLICY, t):
        return 75, "public", "공공기관 공통 경영·제도"
    if not re.search(FUEL, t, re.I):
        return 0, None, "석유·연료 업무와 직접 관련 없음"
    if re.search(r"법|시행령|규제|정부|유류세|최고가격제|품질\s*기준|정책", t):
        return 85, "government", "석유·연료 제도"
    return (90 if re.search(ACTION, t) else 60), "energy", "석유·연료 시장"


def prepare(articles, config, now=None):
    from .classify import is_blocked, risks_for
    kept = []
    for a in articles:
        score, sector, _ = relevance(a)
        if not score or is_blocked(a, config) or (now and stale_market(a, now)):
            continue
        a.sector = sector
        # 예방 활동에 '가짜석유'가 들어갔다는 이유로 경보를 붙이지 않는다.
        a.risk = risks_for(a, config) if re.search(ACTION, a.title) else []
        kept.append(a)
    return sorted(kept, key=lambda a: (relevance(a)[0], a.published), reverse=True)
