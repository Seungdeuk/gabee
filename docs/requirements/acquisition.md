# 기능: 유입 경로 (acquisition)

> 상태: 초안 (2026-11-18). 서버·관리자 화면은 이 문서대로 만들고, 앱 쪽(꼬리표 읽기)은 `expo-application` 추가를 팀이 확인한 뒤 진행한다.

## 목적
가입자가 어느 홍보 채널(유튜브·인스타그램·뉴스 등)을 보고 가비를 설치했는지 관리자 페이지에서 본다.
사용자에게 "어디서 알게 되셨나요?"를 묻지 않고, 플레이 스토어 설치 꼬리표(install referrer)로 자동으로 안다.

## 흐름
1. 홍보 채널마다 꼬리표가 다른 플레이 스토어 링크를 쓴다.
   예: `https://play.google.com/store/apps/details?id=com.kangminhun.gabee&referrer=utm_source%3Dyoutube%26utm_medium%3Dvideo%26utm_campaign%3Dlaunch`
2. 앱(안드로이드)이 처음 실행될 때 설치 꼬리표를 읽는다(`expo-application` 의 `getInstallReferrerAsync()`, 앱 PR 에서 문서로 다시 확인).
3. 로그인된 뒤 `utm_source`·`utm_medium`·`utm_campaign` 세 값만 서버에 한 번 보낸다. 꼬리표 원문(광고 클릭 번호 `gclid` 등)은 보내지 않는다.
4. 서버가 한 사람당 한 줄로 저장한다(처음 값만 남긴다).
5. 관리자 페이지 이용 분석 › 유입·가입 탭에서 경로별 가입 수·비율·가족 연결 비율을 본다.

- 꼬리표 없이 스토어에서 검색해 설치하면 플레이 스토어가 `utm_source=google-play&utm_medium=organic` 을 준다 → "직접 검색".
- 아이폰·웹·APK 직접 설치·이 기능 이전 가입자는 기록이 없다 → "알 수 없음".

## 화면 (관리자, 이용 분석 › 유입·가입 탭)
- "유입 경로" 구역: 경로 / 가입 / 비율 / 가족 연결 표.
- 한글 이름: youtube 유튜브, instagram 인스타그램, facebook 페이스북, blog 블로그, cafe 카페, news 뉴스 기사, qr QR(오프라인), kakao 카톡 공유, google-play 직접 검색, unknown 알 수 없음. 그 밖의 값은 받은 값 그대로(`esc()`) 보인다.
- 유튜브·인스타그램·블로그·카페·뉴스 기사·QR·카톡 공유·직접 검색 8개 채널(페이스북은 기록이 있을 때만)과 "알 수 없음"은 가입이 0명이어도 늘 한 줄씩 보인다(2026-11-19, 링크를 뿌린 채널이 효과가 없는지도 보이게). 0명 채널의 가족 연결은 "-".
- 가입이 많은 순, 같으면 위 채널 순서, 목록 밖 값은 그 뒤. "알 수 없음"은 맨 아래.
- 사람 이름·id 는 보이지 않는다. 숫자만 쓴다.
- 표가 아직 없는 DB 에서는 이 구역만 "준비 중"이고 나머지 분석은 그대로 보인다.

## API
- `POST /acquisition/install-source` (로그인 필요, 가족 없어도 됨) → 204
  - 본문: `{source, medium?, campaign?}`. 각 값은 먼저 다듬은 뒤 `^[a-z0-9_-]{1,40}$`(영어 소문자·숫자·`_`·`-`, 40자)로 검사한다. 다듬은 뒤 빈 값이면 422.
  - 다듬기(서버 `schemas.normalize_tag`, 앱 `referrer.js` 의 `normalizeTag` 가 같다): 앞뒤 공백 제거·소문자 → 메타 광고 주소·별칭은 채널 이름으로(`apps.facebook.com`·`m.facebook.com`·`l.facebook.com`·`lm.facebook.com`·`facebook.com`·`fb` → `facebook`, `instagram.com`·`l.instagram.com`·`ig` → `instagram`) → 그 밖에는 허용되지 않는 글자(점 등)를 `-` 로 바꾸고 겹친 `-` 는 하나로, 앞뒤 `-` 는 빼고 40자까지(예: `News.Daum.net` → `news-daum-net`). 메타 광고가 점이 든 값을 보내 422 로 버려지던 문제 때문이다. 서버에서 다듬으므로 이미 배포된 앱도 고쳐진다.
  - 이미 저장된 사람이면 아무것도 바꾸지 않고 204.
  - 가입한 지 30일이 지난 사람이면 저장하지 않고 204(오래된 회원이 앱을 다시 설치했을 때 "그 경로로 가입"으로 잘못 세지 않게).
  - 로그인 안 함 401, 표가 없는 DB 503(`schema_ready("acquisition")`).
- `GET /admin/service/analytics` 응답에 `acquisition: [{source, signups, share, family_rate}]` 와 `acquisition_ready: bool` 추가.
  - `signups`: 그 경로로 가입한 사람 수, `share`: 전체 가입자 대비 %, `family_rate`: 그중 가족에 들어간 사람 %.
  - 저장 기록이 없는 가입자는 `unknown` 한 줄로 센다.

## 데이터
- 새 표 `install_sources` (한 사람 = 한 줄)

| 칸 | 형식 | 뜻 |
|---|---|---|
| `user_id` | 문자 32, 기본키, `users.id` | 누구의 경로인지 |
| `source` | 문자 40 | 어디서 왔나 |
| `medium` | 문자 40, null 가능 | 어떤 형태인가 |
| `campaign` | 문자 40, null 가능 | 어떤 홍보인가 |
| `created_at` | 시각 | 저장한 시각 |

- `user_id` 기본키라 같은 사람의 줄이 두 번 생기지 않는다(처음 값 유지).
- 표 추가만 하는 Alembic 리비전(위험 변경 아님). 기존 `users` 표는 바꾸지 않는다.
- 로그에는 값을 남기지 않는다.

## 완료 조건
- 서버 시험: 비로그인 401, 잘못된 글자 422, 첫 저장 204 + 한 줄, 다른 값으로 다시 보내도 처음 값 유지, `source` 만 보내도 저장, 가입 30일 지난 사람은 저장 안 함, 가족 없어도 저장.
- 관리자 시험: 경로별 가입 수·비율·가족 연결 비율, 기록 없는 사람은 unknown, 표가 없으면 `acquisition_ready=false` 이고 분석은 200.
- 보안 시험 표(`test_security_matrix.py`)에 새 주소를 "가족 없이도 되는 주소"로 올린다.
- 문서: `docs/contracts/openapi.json`, `docs/contracts/db.md`, `docs/features/acquisition.md`.

## 미정
1. 개인정보 처리방침(`/privacy`)에 "설치 경로(홍보 채널 이름)를 저장한다"는 문구를 넣을지, 문구는 무엇으로 할지 — 팀 확인.
2. 앱 PR: `expo-application` 추가(의존성 추가라 팀 확인), 앱 작업 담당.
3. 아이폰 유입 경로: 앱스토어 커넥트 캠페인 링크 통계로만 본다(관리자 페이지 연결 없음). 바꿀지.
4. 30일 기준값.
