# 뉴스 Supabase 연결

프로젝트: `jgkgacuzpoxkjuxcrjxc` (joongyu01's Project, 서울)

`migrations/202609190001_news.sql`은 2026-09-19 프로젝트에 적용했습니다.
기존 테이블은 변경하지 않았습니다. 두 뉴스 테이블 모두 RLS를 사용하고
anon/authenticated 접근을 차단합니다. service_role 키는 서버에서만 사용하세요.

GitHub Actions Secrets와 검토 페이지의 Vercel 환경변수에 동일한 값을 설정합니다:

- `SUPABASE_URL`: `https://jgkgacuzpoxkjuxcrjxc.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY`: 프로젝트의 서버용 service_role 키

Vercel에는 기존 `REVIEW_PIN`, `SESSION_SECRET`도 필요합니다.
Supabase 설정 시 `GH_TOKEN`, `GH_REPO`는 검토 페이지에 필요하지 않습니다.
키가 둘 다 없으면 기존 GitHub 파일 방식으로 동작합니다. 한쪽만 있으면 실패합니다.

연결 순서:
1. GitHub Secrets 두 개를 등록합니다.
2. Actions의 **Supabase 초안 연결**을 실행해 기존 초안을 복사합니다.
   이 작업은 알림을 보내지 않고 기존 DB 초안과 검토 결과를 덮어쓰지 않습니다.
3. Vercel에 동일한 환경변수를 등록하고 재배포합니다.
4. 매일 수집 시 GitHub 파일과 DB에 초안을 저장합니다. 발송 시 DB 검토 결과를
   읽으며 DB가 응답하지 않으면 미검토 상태로 발송하지 않고 중단합니다.

메일/텔레그램 발송 자격 증명은 별도로 설정해야 합니다.

검증: `python -m unittest discover -s tests -v`, `node tests/storage.mjs`
