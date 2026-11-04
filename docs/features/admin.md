# 구현 현황: 서비스 관리자 페이지

- 상태: 진행 중(1단계 완료, 2단계 중 AI 이용 현황 완료)
- 담당: 강민훈
- 요구사항: docs/requirements/admin.md

## 구현된 것

- `users.is_staff` 칸(리비전 `7f7a6cbbaea3`, expand, down_revision `f06220eb955a`). 기존 사용자는 모두 false.
- `app/shared/auth.py` 의 `staff_user`: `bearer_user`(JWT 정식 회원) 다음에 `is_staff` 를 확인한다. 아니면 404 `not_found`.
- `app/features/admin/`
  - `router.py`: `GET /admin/me`, `/admin/members`, `/admin/groups`, `/admin/features`, `/admin/ai-usage` (읽기 전용). `main.py` 에서 `schema_ready("family_group")` 로 등록한다.
  - `repository.py`: 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표에서 개수·시각만 읽는다.
  - `static/`: 관리자 화면. `main.py` 가 `/admin/ui` 로 내려준다. 로그인 → 메뉴 5개 모두 실제 데이터(회원·가족 그룹·기능·AI 이용·문의 및 신고). 문의·신고는 상태 바꾸기와 답변 저장을 한다(2026-11-04, `mock.js` 삭제). 테스터 관리·사용자 피드백 메뉴와 `/admin/testers` 는 뺐다(2026-11-03).
  - AI 이용 현황: 공용 `ai_usage_logs`(모든 AI 기능이 `ai_guard` 를 거치며 남김)의 행 수를 센다. 기능 이름은 `service.AI_FEATURE_NAMES`, 목록에 없는 기능은 key 를 그대로 보여 준다. 응답 형식 이름은 가족 채팅의 `AiUsageOut` 과 겹치지 않게 `AdminAiUsageOut`.
- 테스트 `app/features/admin/tests/test_admin_api.py`(12개): 비로그인 401, 일반 회원 404, 관리자 200, 가족 owner 404, 레거시 토큰 401, 목록 4개 권한, 회원·그룹·기능 집계, 회원 요약(활성·가족 없음·이메일 인증), 가족 요약(1명 가족·승인 대기·AI 켬), AI 요청 수 집계(캐시 적중 포함, 30일 밖 제외, nested·rejected 제외, 가족별·사용자별·한도 걸린 사람).

## 관리자 지정 방법

API 는 없다. 마이그레이션이 적용된 DB 에서 담당자가 직접 실행한다.

```sql
update users set is_staff = true where login_id = '<관리자 아이디>';
```

해제는 같은 문장에서 `false` 로 바꾼다.

## 보는 방법 (로컬)

1. `apps/api` 에서 서버를 켠다(`uvicorn app.main:app --reload`).
2. 로컬 DB 에서 내 계정을 관리자로 지정한다(위 SQL).
3. 브라우저로 `http://127.0.0.1:8000/admin/ui/` 를 열고 가비 앱 계정으로 로그인한다.

## 남은 것

- 2단계: 계정 정지, 로그인 실패 내역, 앱의 문의 보내기 화면(서버 `support` 기능은 완료)
- 바깥 문(IP 제한 등)과 관리자 접근 기록
