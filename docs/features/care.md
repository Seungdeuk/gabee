# 기능: 돌봄 (삭제됨)

> 2026-11-03: 돌봄 기능을 전부 지웠다. 하단 탭 "돌봄"은 "지갑"으로 바뀌었고(정산·지출·용돈), 지갑 탭 화면은 `apps/mobile/src/features/care/screens/CareScreen.js`에 있다(라우트 이름 `care`는 그대로).

## 지운 것
- 서버: `apps/api/app/features/care/` 전체. `/care/*` API(데일리 체크, 항목·기록, 추천, 식단, 돌봄 기록, 돌봄 에이전트, 위치 공유·동의)와 `CARE_API_ENABLED`·`CARE_LOCATION_ENABLED` 설정.
- 앱: 현황판, 데일리 체크, 항목 추가, 누락 배너, 돌봄 임시 화면, 시간 선택기, 위치 가져오기(`features/care/location/`).
- DB: `care_items`, `care_entries`, `care_records`, `care_meal_logs`, `care_locations` — Alembic 리비전 `5d1c0a7b9e42`(DB 담당자 승인이 필요한 별도 PR).

## 남긴 것
- `users.location_consent_at`, `location_consent_events`, 가입 요청의 `location_consent` 필드(가입 쪽 코드라 이번에 건드리지 않았다). 위치 기능이 없으므로 쓰이지 않는다. 정리할지는 미정이다.
- 알림 분류 `care`, 제안 토큰의 탭 이름 `care`(저장된 값과의 호환을 위해 그대로 둔다).

지갑 탭의 현황은 `docs/requirements/wallet.md`와 `docs/features/billing.md`를 본다.
