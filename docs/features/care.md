# 구현 현황: 돌봄 (care)

- 상태: 진행 중 (서버·앱 화면 연결과 브라우저 클릭 검증 완료, 실기기 미검증)
- 요구사항: `docs/requirements/care.md` 없음. 2026-10-21 요청 메시지의 명세를 기준으로 구현했다.
- 브랜치: `billing-care`

## 구현된 것
### 서버 (`apps/api/app/features/care`)
- 데일리 체크 `GET /care/daily`: 샘플 7개(아침 식사, 영양제, 컨디션, 점심 식사, 물 ml, 산책 분, 저녁 식사)를 처음 열 때 만든다. 항목 추가(`POST /care/items`)·삭제(소프트 삭제). 기록 방식은 예/아니오, 수치(목표 있음), 컨디션(좋음/보통/나쁨). 기록은 `PUT /care/items/{id}/entry`(같은 날 덮어씀).
- 누락 확인: 서버가 계산한다. 완료되지 않았고 현재 시각이 예정 시각 + 60분을 **넘으면** 누락(정각 +60분은 아직 아님). 지난 날의 미완료는 모두 누락.
  - 완료 기준: 예/아니오는 '예', 목표 있는 수치는 목표 이상, 목표 없는 수치·컨디션은 기록 있음.
  - `at=HH:MM`을 주면 그 시각을 '지금'으로 본다(화면 테스트용).
- 추천 `GET /care/recommendations`: 물, 산책, 컨디션, 영양제 규칙. 모델을 쓰지 않는다.
- 식단 추천 `GET /care/meals`, `GET /care/meals/{meal}?index=`: 기록이 없는 끼니만, "다른 메뉴"는 `next_index`로 순환. 메뉴는 `care/config.py`.
- 위치 `GET /care/location`: 실제 GPS 없이 예시 위치만 돌려주고 `is_example: true`와 안내 문구를 포함한다.
- 기존 `/care/records`(종류별 하루 기록)는 그대로 두었다.
- 테스트: `tests/test_care.py`, `tests/test_care_daily.py`. DB: Alembic 리비전 `9e28d84c1686`.

### 앱 (`apps/mobile/src/features/care`)
- `CareScreen`: 데일리 체크·추천·식단·위치 4구역(`components/*Tab.js`), 서버 호출은 `api.js`.
- 누락은 "미기록 · 누락" 크림색 배지로 보이고, 건강 이상이 아니라는 안내 문구를 함께 둔다.
- 서버 주소(`EXPO_PUBLIC_API_URL`)가 없으면 기존 임시 데이터 화면(`CarePreview`)을 그대로 보여 준다.

## 확인 방법
- 서버 확인용 화면: `apps/api/scripts/dev_console.py` → `/console`.
- 앱: `EXPO_PUBLIC_API_URL=http://<서버> EXPO_PUBLIC_DEV_TOKEN=<토큰> npx expo start --web`.
- 2026-10-22 Edge 브라우저(Expo 웹)에서 체크 기록·항목 추가/삭제·추천·식단 순환·위치 클릭 흐름 검증(서버 응답까지 대조).
  이 검증으로 "다른 메뉴"를 누를 때 첫 메뉴로 잠깐 되돌아가는 깜빡임 결함을 찾아 고쳤다.

## 정한 것 (확인 필요)
- **추천 규칙 문구는 프로토타입에서 찾지 못해 임시로 썼다.** 맞출 문구가 있으면 `care/config.py`의 `RECOMMENDATIONS`만 바꾸면 된다.
- 샘플 항목의 예정 시각(08:00, 09:00, 10:00, 12:00, 물 18:00, 산책 17:00, 저녁 19:00)과 목표(물 1500ml, 산책 30분)도 임시 값이다.
- 식단 추천에서 '기록되지 않은 끼니'는 기록이 아예 없는 끼니다('아니오'도 기록으로 본다).

## 남은 것
- 로그인·가족 그룹 화면 연결(현재는 개발용 토큰), 실기기(Expo Go) 확인.
- 실제 GPS 위치, 병원 일정·가족 요청·AI 안부.
