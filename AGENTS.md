# news 작업 지침

새 세션에서 이 프로젝트를 이어갈 때 [Computer Use 작업 인계](docs/computer-use-handoff.md)를 먼저 읽는다. 이 문서에는 비밀값을 저장하지 않는다.

- 사용자는 웹 서비스 설정과 실제 동작 확인을 Edge의 Computer Use로 진행하기를 원한다. 현재 도구·스킬 지침을 읽고 기존 로그인 세션을 확인한다. 로컬 코드·테스트·Git 작업은 셸로 수행할 수 있다.
- 기존 GitHub/Vercel/Supabase/Telegram/Gemini 연결을 확인한 뒤 수정한다. 새 프로젝트·봇·예약을 중복 생성하지 않는다.
- 뉴스 주제는 아침 스크랩, 긴급 점검, Gemini 예약에 각각 존재한다. 사용자가 모두 수정하라고 요청하면 세 경로를 확인한다.
- 모델 토큰, GitHub API 호출 한도, Actions 실행 시간, 계정 청구액을 구분한다. DB에는 필요한 기사와 제한된 운영 요약만 저장하며 전체 크롤링 이력이나 원문 로그를 추가하지 않는다.
- Gemini 원격 브라우저의 승인 필요 상태와 접수/실제 Telegram 전달을 구분한다. Actions 예약도 정시 실행을 보장한다고 설명하지 않는다.
- 현재 요청 범위에서 변경과 검증을 완료한다. 이 파일을 외부 발송·권한 확대·새 약관 동의에 대한 포괄적 승인으로 취급하지 않는다.
- 기능 변경 시 관련 테스트를 실행한다. 전체 Python 테스트: `python -m unittest discover -s tests -q`. Node 검증: `node tests/bot.mjs`, `node tests/usage.mjs`, `node tests/spark.mjs`, `node tests/review.mjs`. Python/JS 발송 선택 일치는 Python 테스트에 포함된다. 문서만 수정한 경우 링크·변경 내용 확인으로 충분하다.
- 운영 반영 요청이면 push 후 해당 커밋의 CI와 Vercel 배포 결과를 확인하고 요청된 화면/봇 응답으로 검증한다. 검증 중 불필요한 뉴스 재발송을 피한다.
- 기능 또는 연결 방식이 바뀌면 관련 운영 문서도 함께 갱신한다.
