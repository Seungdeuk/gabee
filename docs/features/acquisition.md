# 구현 현황: 유입 경로 (acquisition)

- 상태: 진행 중 (서버 저장·관리자 화면 완료, 앱 꼬리표 읽기 남음)
- 담당: kang
- 요구사항: `docs/requirements/acquisition.md`

## 구현된 것

- `app/features/acquisition/models.py`: 모델 `InstallSource`(테이블 `install_sources`, 기본키 `user_id`). Alembic 리비전 `eab90289ee51`(새 표 1개, expand 만). `app/shared/db.py` 의 `import_all_models()` 에 등록.
- `POST /acquisition/install-source`(router → service → repository) → 204.
  - 본문 `{source, medium?, campaign?}`, 각 값 `^[a-z0-9_-]{1,40}$`. 아니면 422.
  - 처음 값만 남긴다(이미 있으면 그대로 204). 가입 30일이 지난 회원은 저장하지 않는다(`service.NEW_MEMBER_WINDOW`).
  - `main.py` 에 `schema_ready("acquisition")` 와 함께 등록. 보안 매트릭스에는 "가족 없이 써도 되는 경로".
- 관리자 "데이터 분석" 탭(`GET /admin/service/analytics`): `acquisition`(경로별 가입·비율·가족 연결 비율, 기록 없는 가입자는 `unknown` 으로 맨 끝)과 `acquisition_ready`. 표가 없는 DB 에서는 표를 읽지 않고 빈 목록 + "준비 중".
  - 계산: `service_admin/analytics.py` 의 `acquisition()`, 조회: `service_admin/repository.py` 의 `install_sources()`.
  - 화면: `service_admin/static/app.js` 의 `acquisitionCard()`. 한글 이름표 `SOURCE_LABEL`, 목록에 없는 값은 `esc()` 로 그대로.
- 테스트: `app/features/acquisition/tests/test_acquisition_api.py`(16개), `service_admin/tests/test_admin_api.py` 의 `test_analytics_acquisition_by_source`, `test_analytics_without_acquisition_table`, `test_acquisition_order_and_rates`.

## 남은 것

- 앱(안드로이드): 첫 실행 때 설치 꼬리표를 읽고(`expo-application` 의 `getInstallReferrerAsync()`), 로그인 뒤 utm 세 값만 한 번 보낸다. `expo-application` 추가는 팀 확인 후.
- 요구사항 "미정": 개인정보 처리방침 문구, 아이폰 유입 경로, 30일 기준값.
