# 구현 현황: 서비스 관리자 페이지

- 상태: 진행 중 (메뉴 7개 완료, 권한 문서 정리 남음)
- 담당: kang
- 요구사항: docs/requirements/admin.md

## 구현된 것

- 경로: API 는 `/admin/service/*`, 화면은 `/admin/service/ui`, 폴더는 `app/features/service_admin/`(2026-11-05, 운영 관리자 `/admin/ops/*`·`app/features/ops_admin/` 와 짝을 맞춤).
- 권한: 모든 `/admin/service/*` API 는 `require_operator("admin")`(`app/shared/auth.py`)를 거친다. Bearer(JWT) 정식 회원이면서 환경변수 `ADMIN_USER_IDS`(통합관리자) 허용 목록에 있어야 한다. 운영 관리(`/admin/ops/*`)도 같은 목록이다(2026-11-06 결정: 권한은 통합관리자 하나). 없으면 403 `operator_required`, 로그인 안 함·레거시 토큰은 401. 별도 DB 칸(`users.is_staff`)은 만들지 않았다.
- `app/features/service_admin/`
  - `router.py`: `GET /admin/service/me`, `/admin/service/members`, `/admin/service/groups`, `/admin/service/features`, `/admin/service/ai-usage` (읽기 전용), `GET /admin/service/support`, `PATCH /admin/service/support/{ticket_id}`(문의·신고 상태·답변). `main.py` 에서 `schema_ready("family_group")` 로 등록하고, 문의·신고 두 경로는 `schema_ready("support")` 도 거친다.
  - `repository.py`: 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표에서 개수·시각만 읽는다.
  - `static/`: 관리자 화면. `main.py` 가 `/admin/service/ui` 로 내려준다. 화면 틀과 색은 운영 관리자 웹(`apps/ops-admin`)과 같다(왼쪽 남색 메뉴·위 고정 머리줄·흰 패널, 시스템 글꼴, 다크 모드, 900px 이하 햄버거 메뉴, 2026-11-05). 로그인 → 메뉴 7개(회원·가족 그룹·기능·AI 이용·문의 및 신고·공지사항·데이터 분석) 모두 실제 데이터. 허용 목록에 없으면 "관리자 계정이 아니에요".
  - 기능 관리: 일정·소통·정산의 최근 7일 사용 수. 돌봄은 release/1.2 에서 기능과 표가 지워져 뺐다.
  - 문의 및 신고: 상태별 건수와 최근순 목록. 줄마다 "답변하기"(답변이 있으면 "답변 수정") 버튼이나 제목을 누르면 사용자가 쓴 내용과 답변 칸이 펼쳐진다. 답변을 저장하면 상태가 자동으로 "답변 완료"가 되고(답변 없이는 완료 불가), 상태 버튼은 "처리 시작"(접수 → 처리 중)뿐이다. 그리고 "처리 시작"·"처리 완료" 버튼으로 상태를 바꾼다. 답변은 다시 저장하면 고쳐진다. 새 문의는 F5 없이 보인다: 15초마다·창으로 돌아올 때·탭에 들어올 때·"새로고침" 버튼을 누를 때 문의 목록만 다시 받고, 탭에는 처리하지 않은 새 문의 건수가 붙는다(답변 칸에 쓰던 글이 있으면 화면을 다시 그리지 않아 글이 지워지지 않는다).
  - 데이터 분석: `analytics.py` 가 재방문 코호트·가입 퍼널·가족 인원별 활동·기능 사용 지도·AI 품질/비용·요일×시간 활동·고객 응대를 계산하고 `GET /admin/service/analytics` 로 준다. 시험 `test_analytics_shape_and_counts`, `test_analytics_is_admin_only`. 유입 경로 구역(경로별 가입·비율·가족 연결, 2026-11-18)은 `install_sources` 표를 읽는다 — `docs/features/acquisition.md`. 체류시간 구역(1명당 하루 평균 분·실행 횟수, 탭 비율, 30일 막대, 2026-11-19)은 `usage_daily` 표를 읽는다 — `docs/features/usage.md`.
  - 공지사항: 평소에는 목록과 "글쓰기" 버튼만 보이고, 글쓰기나 고치기를 누르면 쓰기 칸(종류·제목·내용)이 열린다. 올리고, 목록에서 고치기·지우기. `GET/POST /admin/service/notices`, `PUT/DELETE /admin/service/notices/{notice_id}`. 자세한 것은 `docs/features/notices.md`.
  - AI 이용 현황: 공용 `ai_usage_logs` 의 행 수를 센다(사용자가 한 번 쓰면 1, 캐시·오류 포함). `nested`·`rejected` 표식 줄은 요청 수에서 빼고, 기능별 사용량에서는 "직접 / AI 비서가 부름"으로 나눠 보여 준다. 기능 이름은 `service.AI_FEATURE_NAMES`.
- 테스트 `app/features/service_admin/tests/test_admin_api.py`(15개): 비로그인 401, 목록에 없는 회원 403, 목록에 있는 회원 200, 가족 owner 403, 운영 관리자 목록만 있으면 403, 레거시 토큰 401, 목록 5개 권한, 회원·그룹·기능 집계, 회원 요약, 가족 요약, AI 요청 수 집계, 문의·신고 목록·상태·답변, 문의·신고 바꾸기 규칙(422·404·보낸 본인도 403). 허용 목록에는 시험 계정 id 만 넣는다.

## 관리자 지정 방법

운영 담당자가 서버 환경변수 `ADMIN_USER_IDS` 에 통합관리자 사용자 id 를 쉼표로 넣는다(서비스·운영 관리가 함께 열린다). 실제 id 는 코드·Git·문서·테스트에 쓰지 않고 개인 채널로 전달한다.

## 보는 방법 (로컬)

1. 내 로컬 `.env` 에 `ADMIN_USER_IDS=<내 사용자 id>` 를 넣고 `apps/api` 에서 서버를 켠다(`uvicorn app.main:app --reload`).
2. 브라우저로 `http://127.0.0.1:8000/admin/service/ui/` 를 열고 가비 앱 계정으로 로그인한다.

## 운영 탭 (운영 관리자 화면 합치기 1단계, 2026-11-06)

- 왼쪽 메뉴 맨 아래 **운영 › 서버 상태**. 운영 관리자 대시보드(`apps/ops-admin`, release/1.2 `1f4eac0`)를 이 화면 안에서 연다.
- **로그인은 한 번**: 서비스 관리자 로그인 토큰(같은 탭의 sessionStorage)을 운영 화면이 그대로 쓴다. 다시 로그인하지 않는다.
- **권한**: 통합관리자 하나라서 로그인한 관리자에게는 '운영' 묶음이 늘 보인다. 통합관리자가 아니면 로그인 단계에서 막힌다("관리자 계정이 아니에요"). 최종 판단은 언제나 서버(`require_operator("admin")`)가 한다.
- 파일: `static/ops/` 는 `apps/ops-admin` 의 `index.html`·`css/style.css`·`js/api.js`·`js/auth.js`·`js/config.js`·`js/app.js` 복사본이다. API 서버 이미지(`apps/api/Dockerfile`)에는 `apps/api` 만 들어가서, 운영 웹 폴더를 그대로 쓸 수 없다.
  - 원본과 다른 점: `index.html`(샘플 모드 파일 대신 `js/embed.js`, CSP `connect-src 'self'` 만), `js/app.js` 네 군데(바깥 토큰으로 바로 대시보드, 안쪽 로그아웃 버튼 숨김, 로그인 만료를 바깥 화면에 알림), 새 파일 `js/embed.js`.
  - 운영 원본(`apps/ops-admin`)을 고치면 이 복사본도 맞춰야 한다. 원본을 계속 둘지, 이 복사본 하나로 합칠지는 운영 담당과 정한다(미정).

## 남은 것

- `docs/contracts/permissions.md` 서비스 관리자 절: `docs/requirements/service-admin.md` 미정 항목.
- 계정 정지, 로그인 실패 내역, 바깥 문(IP 제한 등).
