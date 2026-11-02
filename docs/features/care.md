# 구현 현황: 돌봄 (care)

> **2026-11-02 팀 회의 결과: 하단 탭 "돌봄"을 "지갑"으로 바꾸고, 데일리 체크(현황판·항목·기록·추천·식단 기록)와 돌봄 에이전트를 지웠다.** 지갑 탭에는 정산·지출·용돈만 둔다. 요구사항은 `docs/requirements/wallet.md`.

- 상태: 데일리 체크는 삭제됨. **위치 공유만 코드로 남아 있고 보류(꺼짐)** 이다.
- 앱 라우트 이름(`care`)은 그대로이고 탭 이름만 "지갑"이다. 화면은 `features/care/screens/CareScreen.js`(정산·지출·용돈, 월말 정산 알림).

## 지운 것 (2026-11-02)
- **서버**: 데일리 체크(`/care/daily`, `/care/items`, `/care/items/{id}/entry`), 추천(`/care/recommendations`), 식단 추천·기록(`/care/meals`, `/care/meal-log`), 돌봄 기록(`/care/records`, `/care/summary/today`), 돌봄 에이전트(`/care/agent/chat`, `/care/agent/confirm`, `care/agent.py`)와 관련 서비스·저장소·스키마·설정·테스트. 메인 에이전트의 `ask_care`는 먼저 목록에서 뺐다.
- **앱**: 현황판·데일리 체크·항목 추가·누락 배너·길게 눌러 삭제·돌봄 임시 화면, 시간 선택기(`TimePicker`), 서버 호출 함수(`getDaily` 등).
- **평가·스크립트**: 평가 사례 중 돌봄 6개와 돌봄·구독을 메인에 시키는 사례 6개(64개 → 52개), 평가용 돌봄 시드, 개발용 스크립트의 돌봄 호출.
- **지우지 않은 것(DB)**: 테이블 `care_items`, `care_entries`, `care_records`, `care_meal_logs`와 모델(`care/models.py`)은 그대로 둔다. 테이블을 지우는 것은 데이터가 사라지는 변경이라 DB 담당자 승인과 별도 PR이 필요하다(`destructive-approved` 표기).

## 남아 있는 것: 위치 공유 (보류)
위치 공유는 법적 요건(사업 신고 등) 때문에 이번 범위에서 제외했고 코드는 지우지 않았다.
- **서버 스위치**: `CARE_API_ENABLED`(기본 꺼짐)가 꺼져 있으면 `/care/*`가 403 `care_disabled`이다. 위치 동의 철회·조회(`/care/location/consent`)는 저장된 내 위치를 지우는 길이라 열어 둔다. `CARE_LOCATION_ENABLED`(기본 꺼짐)가 꺼져 있으면 위치 저장·조회·동의 켜기가 403 `location_disabled`이다. 둘 다 켜야 위치를 쓸 수 있다.
- **API**: `GET·PUT /care/location/consent`, `POST /care/locations`(최대 50개), `GET /care/locations/latest`.
  - 동의: 정본은 `users.location_consent_at`(없으면 미동의). 가입 API가 `location_consent`를 받고, 이후 `GET·PUT /care/location/consent`로 바꾼다. 동의·철회 이력은 `location_consent_events`(좌표 없음)에 남는다.
  - `POST /care/locations`: 동의하지 않았으면 403 `consent_required`. 보관 기간(7일)을 넘었거나 5분 넘게 미래인 점은 버리고, 쓸 때 보관 기간이 지난 위치를 함께 지운다.
  - `GET /care/locations/latest`: 가족 구성원의 최신 위치. 동의하지 않은 사람은 좌표 없이 `sharing=false`.
  - 동의를 철회하면 저장된 내 위치를 바로 지운다. 좌표는 로그에 남기지 않고 외부 서비스로 보내지 않는다.
  - 정책 값은 `care/config.py`(`LOCATION_RETENTION_DAYS` 등). 꺼 두면 새 위치가 오지 않아 이미 저장된 위치는 자동으로 지워지지 않는다.
- **앱**: `LOCATION_ENABLED=false`(`features/care/location/enabled.js`). 위치 구역은 지갑 탭에 없다. 백그라운드 위치 작업(`location/`)은 서버로 보내지 않고, 지갑 탭을 열면 이전에 켜 둔 백그라운드 위치 공유를 멈춘다. 컴포넌트 `LocationTab`, `LocationDisabled`와 `expo-location` 설정은 그대로 있다.

## 개발 빌드(EAS) — 백그라운드 위치용
Expo Go 는 백그라운드 위치를 지원하지 않아 실기기 확인에는 개발 빌드가 필요하다. 설정은 준비됐고, **빌드는 한 번도 돌리지 않았다**(EAS 로그인·Apple 계정 필요).
- 준비된 것: `apps/mobile/eas.json`(profiles `development`·`development-simulator`·`preview`·`production`), `expo-dev-client`, `app.json`의 `ios.bundleIdentifier`·`android.package` = `com.kangminhun.gabee`(**임시 값 — 첫 스토어 배포 전에 팀이 확정**).
- 빌드: `npm i -g eas-cli && eas login` 후 `eas build --platform android --profile development`. 설치한 뒤 `npx expo start --dev-client` 로 연결한다.
- 서버 주소는 `eas.json`에 넣지 않았다(`EXPO_PUBLIC_API_URL` 은 배포 주소가 정해지면 프로필별 `env` 로 추가; 비밀값 금지).

## 남은 것
- 위치를 다시 켤 때: 서버 `CARE_API_ENABLED`와 `CARE_LOCATION_ENABLED`, 앱 `LOCATION_ENABLED`를 함께 바꾸고 `release/1.2`의 앱 위치 권한 차단(`app.json`)도 되돌린다.
- **백그라운드 위치 수집은 검증하지 못했다.** 전용 개발 빌드(EAS)와 실기기가 필요하다.
- 출시 전 검토: 개인위치정보 수집·이용의 법적 요건(별도 동의, 만 14세 미만 보호자 동의, 사업자 신고 등)은 확인하지 못했다.
- 사용자가 여러 가족 그룹에 속하면 위치가 모든 그룹 구성원에게 보인다(동의는 사용자 단위).
- 돌봄 DB 테이블 삭제는 별도 PR(DB 담당자 승인).
