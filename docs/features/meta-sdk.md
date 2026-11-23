# 메타 광고 측정 SDK (앱)

## 목적
인스타그램·페이스북 광고를 보고 앱을 설치한 사람이 실행·가입했는지 메타 광고 관리자에서 보고, 메타가 가입할 만한 사람에게 광고를 보여 주게 한다.
가입 경로(utm) 집계는 이 SDK 와 별개로 플레이 설치 리퍼러로 한다(`acquisition.md`).

## 구현 현황 (2026-11-23)
- 패키지: `react-native-fbsdk-next`(13.4.x, `npx expo install` 로 추가)
- 설정: `apps/mobile/app.config.js` 가 `app.json` 에 메타 설정을 덧붙인다.
  - 앱 ID `1523729119817097`(메타 개발자 앱 "Gabee", 공개 값)
  - 클라이언트 토큰은 코드에 없다. **EAS 환경변수 `META_CLIENT_TOKEN`**(expo.dev › 프로젝트 › Environment variables, Sensitive)을 빌드할 때 읽는다. 없으면 `extra.metaEnabled=false` 로 빌드되어 메타가 꺼진다.
  - 자동 시작 끔(`isAutoInitEnabled: false`), 켠 뒤 설치·실행 자동 기록(`autoLogAppEventsEnabled: true`), 안드로이드 광고 ID 수집 켬, 아이폰 추적 허용 팝업(ATT)은 아직 없음
- 코드: `src/shared/meta/`
  - `metaGate.js` `canUseMeta()`: 안드로이드·아이폰이고, Expo Go 가 아니고(`executionEnvironment !== "storeClient"`), 토큰이 있을 때만 true (시험 `tests/metagate.test.js`)
  - `metaEvents.js` `startMeta()`: 앱 시작(`src/app/_layout.js`) 때 한 번 SDK 를 켠다. SDK 는 이 안에서만 `require` 해서 Expo Go 에서는 불러오지도 않는다
  - `logMetaSignup()`: 아이디 회원가입 성공 직후(`SignupScreen.js`) "가입 완료"(`fb_mobile_complete_registration`, 방법 `id`)를 보낸다
- 보내는 것: 설치·실행·가입 이벤트, 기기 광고 ID(사용자가 끄지 않은 경우), 기기 종류·OS. 이름·아이디·이메일·가족·대화·일정·가계·사진·AI 내용은 보내지 않는다(개인정보처리방침 v0.3 4항).

## 시험 방법
- Expo Go: 메타가 꺼진 채로 앱이 평소처럼 열린다(팀 개발은 그대로).
- 메타까지 확인: `apps/mobile` 에서 `npx eas-cli@latest build --profile development --platform android` → 설치 → 실행·가입 → 메타 개발자 사이트 › 이벤트 관리자에서 이벤트 확인.

## 남은 일
- 메타 앱 설정에 안드로이드 키 해시 등록
- 소셜(구글·카카오) 가입은 서버가 새 가입인지 알려 주지 않아 "가입 완료"를 보내지 않는다
- 아이폰 ATT(`expo-tracking-transparency` 추가 필요, 별도 제안)
- 플레이 콘솔 데이터 보안 설문, 팀 GitHub Pages 개인정보처리방침 같은 문구로 수정
