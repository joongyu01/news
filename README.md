# 한국석유관리원 뉴스 수집·AI 종합 분석

수집과 분석을 분리합니다. 24시간 15분마다 기사를 저장하고, 06:00~23:30의 매시 00분·30분에 새 기사만 AI로 선별합니다. 오전 08:00에는 누적 자료를 종합 분석한 뒤 조간을 바로 보냅니다.

```text
15분 수집 (24시간, AI 없음) → 관련성 필터 → URL 중복 제거·48시간 누적
                              ├ 06:00~23:30 매시 00/30분 → 새 기사 AI 선별 → 긴급 기사 한 메시지
                              └ 매일 08:00 → 하루치 AI 종합 분석 → 조간 자동 발송
```

GitHub Actions 예약은 지연될 수 있습니다. 아침 분석은 뉴스를 다시 검색하지 않습니다.

## 보고 기준

- 석유관리원 업무, 석유 품질·정량·유통·수급·가격 정책, 에너지시장감시단, 석유공사·가스공사 통합, 공공기관 공통 제도를 우선합니다.
- 행사·봉사·수상·축사·기업 홍보·증시·금값·직접 관련 없는 전력 소식은 제외합니다.
- 같은 사건의 여러 매체 보도는 AI가 하나의 이슈로 정리합니다. 최대 5개이며 개수를 채우지 않습니다.
- 핵심 해외 수급·연료 규제 뉴스는 아침 분석에만 최대 2개 포함합니다. 해외 입력 후보는 최대 20건이며, 국내 보도와 같은 사건이면 합칩니다. 해외 검색 실패는 국내 수집을 중단시키지 않습니다.
- 사실 요약, 전일 대비 새로운 점, 업무 관련성, 근거 기사 제목 링크를 제공합니다.
- 제목과 RSS/API 제공 요약을 분석합니다. 기사 전문을 읽거나 사실 검증을 완료한 결과는 아닙니다.
- 일반 관심 주제와 사용자 watch 검색 결과는 업무 관련성 범위에서 아침 분석 후보가 됩니다. 긴급 알림은 AI 긴급 판정과 실제 긴급 규칙을 모두 통과해야 합니다. 과거 사건 재서술·해설과 시점 불명확 기사는 긴급 제외, 중요한 새 사실이 없는 같은 사건은 재알림하지 않습니다. 한 번에 최대 3건을 한 메시지로 묶고 후보가 없으면 보내지 않습니다.

## 무료 AI API와 예비 키

GitHub Actions **Secrets**:

| 이름 | 용도 |
| --- | --- |
| `GEMINI_API_KEY` | 기본 Gemini API 키 |
| `GEMINI_API_KEY_BACKUP` | 두 번째 프로젝트 키. A→B→A 순서로 교대 |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | 기존 뉴스 DB |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 기존 봇과 소유자 |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `EMAIL_TO` | 선택: 이메일 발송 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 선택: 없으면 Google News RSS |

**Variables**: `REVIEW_URL`은 기존 검토 주소입니다. `GEMINI_FREE_TIER_CONFIRMED=true`는 등록한 기본·예비 키의 프로젝트가 모두 무료 등급이고 결제 계정 미연결임을 확인한 뒤 설정합니다. 확인 전에는 API를 호출하지 않습니다.

Gemini Pro 웹 구독과 API 결제는 별개입니다. 계정이 달라도 예비 키를 사용할 수 있으나 **프로젝트가 같으면 한도를 공유**합니다. Google AI Studio의 각 프로젝트 지출 화면에서 무료 등급·결제 미설정을 확인하세요. 결제를 연결하거나 유료 등급으로 바꾸지 않습니다. 코드의 확인 변수는 결제 상태를 실시간 검증하는 장치가 아니므로, 키를 교체하거나 프로젝트의 결제를 변경하면 다시 확인해야 합니다.

기본 모델은 `gemini-3.8-flash`입니다. 선별·조간 모두 요청마다 두 키를 교대로 사용하고, 실패하면 다른 키로 한 번 재시도합니다. 순번과 하루 요청 수를 DB에 먼저 기록하며 재시도를 포함해 하루 최대 40회입니다.  정상 분석이 저장된 날짜를 재실행하면 저장본을 재사용합니다. 두 요청 모두 실패하면 분석을 중단하고 GitHub Actions가 실패를 표시합니다. 임의의 유료 모델이나 공급자로 전환하지 않습니다. 무료 제공량과 서비스 가용성은 보장되지 않습니다. [공식 요금](https://ai.google.dev/gemini-api/docs/pricing), [프로젝트별 한도](https://ai.google.dev/gemini-api/docs/rate-limits).

무료 API에는 공개 뉴스 제목·매체 요약과 이전 분석만 전송합니다. 비밀키·개인 대화·기관 내부자료는 전송하지 않습니다. 무료 등급 콘텐츠는 Google 제품 개선에 사용될 수 있습니다.

15분 수집은 하루 96회이며 AI를 호출하지 않습니다. AI 선별 예약은 하루 36회, 조간은 1회입니다. 새 기사가 없거나 이미 선별한 기사는 호출을 생략합니다. 한 번에 최대 40개 새 기사를 판정하며 남은 후보는 다음 선별에서 처리합니다. 00:00~05:59에는 AI 선별과 긴급 알림을 하지 않습니다. 출력은 최대 6,000토큰, thinkingLevel은 low입니다. 문자 제한은 정확한 토큰 제한이 아닙니다. 성공 응답의 입력·출력·추론·전체 토큰 수를 `analysis.usage`에 저장하고 키나 응답 원문은 로그에 남기지 않습니다. 재시도 시 실패 요청에서 이미 사용한 토큰은 성공 응답 사용량에 포함되지 않습니다.

## 검토와 발송

### Telegram 개인톡 공통 설정

어느 계정에서든 봇과의 개인톡에서 `/settings`로 전체 설정을 확인하고 변경할 수 있습니다. 개인톡을 구독하지 않아도 되며 설정 응답은 요청한 대화에만 보냅니다. 설정은 모든 구독방에 공통 적용되고 `/subscribe`·`/unsubscribe`만 현재 대화의 구독을 바꿉니다. 기존 방별 설정은 소유자 방의 값을 초기 공통값으로 사용합니다.

- `/urgent_on`, `/urgent_off`, `/daily_on`, `/daily_off`
- `/mode_strict`, `/mode_standard`, `/limit_5`, `/quiet_22_07`, `/quiet_off`
- `/watch_add_석유_품질`, `/watch_remove_석유_품질`, `/watch_list`
- `/exclude_add_홍보`, `/exclude_remove_홍보`, `/exclude_list`
- `/articles`, `/articles_2`: 보관된 수집 기사와 판정, 한 페이지 5건
- `/excluded`, `/excluded_2`: 규칙 제외·AI 관련성 제외·긴급 제외 이유
- `/logs_collect`, `/logs_alerts`, `/logs_dispatch`: 운영 기록

키워드 내부 언더바는 공백으로 해석합니다. 기존 띄어쓰기 명령도 호환합니다. 기사 상세는 개인톡 전용이며 AI 판정 대기를 제외 확정으로 표시하지 않습니다. 조간 후보와 긴급 후보는 실제 발송을 의미하지 않습니다. 규칙 필터 제외는 적용 후부터 48시간·최대 150건의 제목과 사유만 기록하며, 기존 기사 풀과 AI 판정을 함께 조회합니다. 모든 검색 결과의 영구 이력은 아닙니다. 변경 후 `봇 명령 연결` 작업으로 Telegram 메뉴를 갱신합니다.

[검토 페이지](https://news-lake-delta.vercel.app/)에서 기존 PIN으로 로그인합니다. 저장된 기사 검색·날짜 조회·중복 묶음 열람·전체 복사를 계속 지원합니다.

AI가 근거로 사용한 기사를 제외하면 **그 기사를 인용한 이슈 전체가 빠집니다.** 미선정 기사로 자동 대체하거나 분석을 자동 재생성하지 않습니다. 텔레그램과 이메일은 기사 제목 하이퍼링크, 카카오톡 복사본은 제목과 전체 URL입니다. 이전 날짜의 기존 기사 목록 형식도 계속 열 수 있습니다.

기존 Gemini Spark 웹 보고 접수·자동 전달은 종료했습니다. 기존 웹 예약이 있다면 일시중지하세요. 주간 집계는 기존 금요일 08:30 예약을 유지합니다.

## 저장·운영

기존 Supabase `news_alert_state`의 `urgent` 행에 `pool`을 추가합니다. 스키마 변경이나 새 DB는 필요하지 않습니다. 관련 기사 메타데이터만 **48시간·최대 600건·기사 JSON 900KB**로 제한합니다. 매 15분 Git 커밋은 만들지 않습니다. 긴급 발송 이력은 기존 7일·500건 한도를 유지합니다. 수집·AI 선별·조간 작업은 같은 Actions concurrency 그룹에서 직렬 실행해 기사 풀·키 순번을 함께 보존합니다.

아침에는 최근 24시간 기사 중 AI가 관련 있다고 판정한 자료만 사용합니다. 선별 결과가 3시간 넘게 갱신되지 않았으면 중단합니다. 풀이 없거나 2시간 이상 갱신되지 않았으면 실패로 중단합니다. 중요도순 최대 120건·기사 입력 JSON 합계 60,000자로 AI 입력량을 제한하며, 실제 입력 건수는 초안의 `analysis.input_count`에 남습니다. 초기 가동일은 아직 하루치가 쌓이지 않았을 수 있으며 수집 시작·마지막 갱신 시각도 분석 메타데이터에 저장합니다.

초안은 기존 `news_drafts`와 `data/drafts/`, 담당자 제외는 `news_exclusions`, 실제 발송본은 `archive/`를 사용합니다. API 분석이 실패하면 AI 분석을 가장한 기사 목록을 대신 보내지 않습니다. 조간은 분석 단계가 성공해야 발송 단계가 실행됩니다. 기존 별도 08:00 발송 예약은 제거했고 수동 발송만 남겼습니다.

## 코드 위치

| 변경 대상 | 파일 |
| --- | --- |
| 통합 검색어 | `config/news.yml`, `config/alerts.yml` |
| 즉시 알림 판정 | `scripts/alerts.py`, `config/alerts.yml` |
| 업무 관련성 | `scripts/editorial.py` |
| 누적·만료·크기 제한 | `scripts/rolling.py` |
| AI 지시·응답 검증·키 교대 | `scripts/analysis.py`, `scripts/screening.py` |
| 아침 실행 | `scripts/morning.py`, `.github/workflows/collect.yml` |
| 메시지와 링크 | `scripts/render.py`, `scripts/notify.py` |
| 검토 UI | `public/index.html`, `api/draft.js` |

## 검증

Actions의 `AI API 진단`은 수동 실행 전용입니다. 짧은 JSON 응답을 한 번 요청하고 실패 시 다른 키로 한 번만 재시도합니다. 뉴스 저장·발송 없이 API 사용량만 같은 하루 상한에 기록하며, 실패하면 작업도 실패합니다. 기사 선별의 `no_send`와 조간의 `dry_run`으로 실제 기사 분석을 발송 없이 확인할 수 있습니다.

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -q
node tests/bot.mjs
node tests/usage.mjs
node tests/spark.mjs
node tests/review.mjs
node tests/storage.mjs
```

`python -m scripts.alerts --dry-run`은 수집·판정만 하고 DB 쓰기나 발송을 하지 않습니다. `python -m scripts.morning --dry-run`은 누적 기사 분석용 API를 호출하지만 초안 저장·알림은 하지 않습니다. API 교대 순번·횟수는 기록합니다. 정상 저장된 당일 분석이 있으면 API 없이 재사용합니다. `python -m scripts.dispatch --dry-run`은 발송문만 출력합니다. 운영 뉴스의 불필요한 재발송을 피하세요.

프로젝트 연결·브라우저 작업 지침: [AGENTS.md](AGENTS.md), [작업 인계](docs/computer-use-handoff.md), [Supabase](supabase/README.md).

AI 선별·조간 실패 시 소유자 Telegram에 실행 로그 링크를 보냅니다. 같은 단계는 6시간에 한 번만 알리며, DB 자체가 내려가 중복 기록을 읽을 수 없으면 알림을 우선합니다. API 키나 오류 원문은 보내지 않습니다.
