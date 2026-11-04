# 구현 현황: 서비스 관리자 페이지

- 상태: 진행 중 (메뉴 5개 완료, 경로·권한 문서 정리 남음)
- 담당: kang
- 요구사항: docs/requirements/admin.md

## 구현된 것

- 권한: 모든 `/admin/*` API 는 `require_operator("service_admin")`(`app/shared/auth.py`)를 거친다. Bearer(JWT) 정식 회원이면서 환경변수 `SERVICE_ADMIN_USER_IDS` 허용 목록에 있어야 한다. 없으면 403 `operator_required`, 로그인 안 함·레거시 토큰은 401. 별도 DB 칸(`users.is_staff`)은 만들지 않았다.
- `app/features/admin/`
  - `router.py`: `GET /admin/me`, `/admin/members`, `/admin/groups`, `/admin/features`, `/admin/ai-usage` (읽기 전용), `GET /admin/support`, `PATCH /admin/support/{ticket_id}`(문의·신고 상태·답변). `main.py` 에서 `schema_ready("family_group")` 로 등록하고, 문의·신고 두 경로는 `schema_ready("support")` 도 거친다.
  - `repository.py`: 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표에서 개수·시각만 읽는다.
  - `static/`: 관리자 화면. `main.py` 가 `/admin/ui` 로 내려준다. 로그인 → 메뉴 5개(회원·가족 그룹·기능·AI 이용·문의 및 신고) 모두 실제 데이터. 허용 목록에 없으면 "관리자 계정이 아니에요".
  - 기능 관리: 일정·소통·정산의 최근 7일 사용 수. 돌봄은 release/1.2 에서 기능과 표가 지워져 뺐다.
  - 문의 및 신고: 상태별 건수와 최근순 목록. 줄마다 "답변하기"(답변이 있으면 "답변 고치기") 버튼을 누르거나 제목을 누르면 사용자가 쓴 내용과 답변 칸이 펼쳐지고, "처리 시작"·"처리 완료" 버튼으로 상태를 바꾼다. 답변은 하나만 두고 다시 쓰면 덮어쓴다.
  - AI 이용 현황: 공용 `ai_usage_logs` 의 행 수를 센다(사용자가 한 번 쓰면 1, 캐시·오류 포함). `nested`·`rejected` 표식 줄은 요청 수에서 빼고, 기능별 사용량에서는 "직접 / AI 비서가 부름"으로 나눠 보여 준다. 기능 이름은 `service.AI_FEATURE_NAMES`.
- 테스트 `app/features/admin/tests/test_admin_api.py`(15개): 비로그인 401, 목록에 없는 회원 403, 목록에 있는 회원 200, 가족 owner 403, 운영 관리자 목록만 있으면 403, 레거시 토큰 401, 목록 5개 권한, 회원·그룹·기능 집계, 회원 요약, 가족 요약, AI 요청 수 집계, 문의·신고 목록·상태·답변, 문의·신고 바꾸기 규칙(422·404·보낸 본인도 403). 허용 목록에는 시험 계정 id 만 넣는다.

## 관리자 지정 방법

운영 담당자가 서버 환경변수 `SERVICE_ADMIN_USER_IDS` 에 관리자 사용자 id 를 쉼표로 넣는다. 실제 id 는 코드·Git·문서·테스트에 쓰지 않고 개인 채널로 전달한다.

## 보는 방법 (로컬)

1. 내 로컬 `.env` 에 `SERVICE_ADMIN_USER_IDS=<내 사용자 id>` 를 넣고 `apps/api` 에서 서버를 켠다(`uvicorn app.main:app --reload`).
2. 브라우저로 `http://127.0.0.1:8000/admin/ui/` 를 열고 가비 앱 계정으로 로그인한다.

## 남은 것

- 경로 접두어(`/admin/service/*`로 옮길지)와 `docs/contracts/permissions.md` 서비스 관리자 절: `docs/requirements/service-admin.md` 미정 항목.
- 계정 정지, 로그인 실패 내역, 바깥 문(IP 제한 등).
