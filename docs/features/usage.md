# 구현 현황: 체류시간 (usage)

- 상태: 진행 중 (서버·관리자 화면·앱 코드 완료, 실제 기기 확인 전)
- 담당: kang
- 요구사항: `docs/requirements/usage-time.md`

## 구현된 것

- 앱 `apps/mobile/src/features/usage/`
  - `meter.js`: 측정기. 타이머 없이 "앞에 온 시각"과 "뒤로 간 시각·탭을 옮긴 시각"의 차이로 탭별 ms 를 모은다. 30분 안에 돌아오면 실행 횟수를 세지 않는다. 로그아웃하면 모은 값을 버린다.
  - `tabs.js`: `tabFromPath()`(경로 첫 칸 → `chat`·`family-chat`·`schedule`·`care`·`my`·`other`), `localDay()`.
  - `UsageTracker.js`: 화면 없는 컴포넌트. `AppState` 의 active/background 와 `usePathname()` 만 듣고 측정기에 알린다. 값은 측정기 객체에만 있어 화면을 다시 그리지 않고, 저장소에도 쓰지 않는다. 백그라운드로 갈 때 한 번 `POST /usage/report`, 실패하면 버린다.
  - `src/app/_layout.js` 에 `PushBootstrap`·`AcquisitionBootstrap` 옆으로 등록.
- 서버 `app/features/usage/`: 모델 `UsageDaily`(테이블 `usage_daily`, 기본키 `(user_id, day, tab)`, 날짜 인덱스), Alembic `3ba836194fcf`(down `eab90289ee51`, 표·인덱스 추가만).
  - `POST /usage/report` → 204. 탭은 정해진 6개, 초는 0~86400(한 번에 4시간 상한), 실행 0~20, 날짜는 한국 시간 오늘 기준 7일 전~내일(아니면 422 `usage_day_out_of_range`). 탭 줄과 `app` 줄(합계·실행)에 더하고 하루 86400초를 넘지 않게 자른다.
  - `main.py` 에 `schema_ready("usage")`, `shared/db.py` 의 `import_all_models()`, 보안 매트릭스 "가족 없이 되는 주소", `/health/db` 기능 목록 시험.
- 관리자 이용 분석 › 재방문·사용 시간 탭 "사용 시간 (최근 30일)": `service_admin/analytics.py` 의 `usage()`(기록이 있는 사람·날 기준 평균, 탭별 시간도 같은 기준의 1명당 하루 평균), `repository.usage_rows()`, `app.js` 의 `usageCard()`. 표가 없는 DB 에서는 읽지 않고 "준비 중".
- 시험: `app/features/usage/tests/test_usage_api.py`(16개), `service_admin/tests/test_admin_api.py` 의 `test_analytics_usage_time`·`test_analytics_without_usage_table`·`test_usage_calculation`. 앱 측정기는 PC 에서 시나리오로 직접 실행해 확인.

## 남은 것

- 실제 기기 확인(개발 빌드 또는 내부 테스트), 화면 다시 그리기가 늘지 않는지 React DevTools 로 확인.
- 요구사항 "미정": 개인정보처리방침 문구, 보관 기간(90일 제안)과 지우는 작업, 30분 기준값.
