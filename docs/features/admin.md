# 구현 현황: 서비스 관리자 페이지

- 상태: 진행 중(1단계 완료, 2단계 남음)
- 담당: 강민훈
- 요구사항: docs/requirements/admin.md

## 구현된 것

- `users.is_staff` 칸(리비전 `7f7a6cbbaea3`, expand, down_revision `f06220eb955a`). 기존 사용자는 모두 false.
- `app/shared/auth.py` 의 `staff_user`: `bearer_user`(JWT 정식 회원) 다음에 `is_staff` 를 확인한다. 아니면 404 `not_found`.
- `app/features/admin/`
  - `router.py`: `GET /admin/me`, `/admin/members`, `/admin/groups`, `/admin/features`, `/admin/testers` (읽기 전용). `main.py` 에서 `schema_ready("family_group")` 로 등록한다.
  - `repository.py`: 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표에서 개수·시각만 읽는다.
  - `static/`: 관리자 화면. `main.py` 가 `/admin/ui` 로 내려준다. 로그인 → 실제 데이터 4개 메뉴, AI 이용·피드백·문의는 `mock.js` 예시.
- 테스트 `app/features/admin/tests/test_admin_api.py`(7개): 비로그인 401, 일반 회원 404, 관리자 200, 가족 owner 404, 레거시 토큰 401, 목록 4개 권한, 회원·그룹·기능 집계.

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

- 2단계: 계정 정지, AI 호출 기록, 피드백, 문의·신고, 테스트 진행 표와 앱 화면
- 바깥 문(IP 제한 등)과 관리자 접근 기록
