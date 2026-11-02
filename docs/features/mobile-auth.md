# 구현 현황: 모바일 회원가입·로그인 (family-group 모바일)

- 상태: 구현 완료(실제 기기 확인 전). 백엔드 PR #27(가입)·#28(로그인/JWT)·#29(이메일 인증·재설정)가 모두 main 에 병합돼 있고, 이 브랜치는 최신 main 을 반영했다.
- 요구사항: docs/requirements/family-group.md (PR 4-F 중 로그인·가입·이메일 인증·재설정 부분. 소셜 로그인, 초대 승인 화면은 제외)

## 화면 (모두 `apps/mobile/src/app/*.js` 라우트 → `features/auth/screens`)

| 경로 | 화면 |
|---|---|
| `/login` | 아이디·비밀번호 로그인. 실패 시 같은 문구, 실패한 비밀번호는 지움 |
| `/signup` | 회원가입(아이디 중복 확인, 이름, 역할 — **기타를 고르면 관계 입력칸**이 생긴다(선택, 예: 이모), 이메일, 비밀번호 확인). 가입 → 자동 로그인 → 인증 메일 발송 → `/verify-email` |
| `/verify-email` | 메일의 **6자리 인증번호**를 6칸에 입력(숫자 키패드·자동 입력 지원), 남은 시간 03:00→00:00, 인증번호 다시 받기(60초 간격), 인증 완료 안내. 메일 링크로 열면 자동 인증 |
| `/forgot-password` | **아이디 + 이메일**로 재설정 코드 메일 요청(둘이 같은 계정과 맞을 때만 서버가 메일을 보내고 "재설정 코드를 메일로 보냈어요"를 보인다. 맞지 않으면 서버가 400 `reset_mismatch` 를 주고 화면에 "아이디와 이메일이 일치하지 않아요. 가입할 때 적은 아이디와 이메일을 다시 확인해 주세요"를 보인다 — 아이디가 없는지 이메일이 틀렸는지는 구분하지 않는 한 문구다). 성공하면 `/reset-password` 로 **아이디**를 넘긴다 |
| `/find-id` | 아이디 찾기: 가입한 이메일을 입력하면 아이디를 메일로 보낸다(`POST /auth/login-id/recover`, 계정 유무와 무관하게 같은 안내). 이메일을 등록하지 않았다면 가족 관리자에게 문의 안내. 로그인 화면의 "아이디 찾기" 링크로 들어온다 |
| `/reset-password` | 새 비밀번호 설정(링크로 열면 토큰 자동, 아니면 **아이디** + 메일의 6자리 재설정 코드 입력(메일에는 링크 없이 코드만 있다)). 성공하면 로그인 화면으로 |
| 기타 탭 | `AccountCard`: 로그인 여부, 이메일 인증 상태/인증하기, 로그아웃 |
| 시작 화면 | 저장된 세션이 있으면 건너뛰고 홈, 로그인·회원가입 링크 추가. "시작하기"(익명)는 그대로 |

## 인증 상태 구조

- `shared/api/client.js`: 토큰 보관·헤더 선택·자동 갱신의 한 곳. 화면은 `apiFetch` 만 쓴다.
  - 로그인 세션이 있으면 **`Authorization: Bearer` 만** 보낸다. 없으면 기존 `X-Gyeot-Token`(익명/개발용 `EXPO_PUBLIC_DEV_TOKEN`). 한 요청에 둘을 섞지 않는다. 가입·로그인·메일 링크 확인은 `auth: false`.
  - Access Token 만료(`token_expired`/`token_invalid`) → Refresh Token 으로 갱신하고 **실패한 요청을 한 번만** 재시도. 갱신은 단일 비행(single-flight): 동시 요청이 몇 개든 서버 호출 1회(Refresh Token 은 한 번 쓰면 폐기되므로 중복 갱신은 세션을 끊는다). 다른 요청이 이미 갱신했으면 새 토큰으로 바로 재시도.
  - 갱신이 `refresh_invalid`/`refresh_reused` 면 안전하게 로그아웃(세션 삭제 + 앱에 알림). 네트워크/서버 일시 오류는 세션을 지우지 않는다.
  - 403 `email_not_verified` → 앱이 `/verify-email` 안내 화면으로 이동(3초 안 중복 이동 방지).
- `shared/auth/AuthProvider.js`: `useAuth()` = `{status, user, signIn, signOut, refreshUser, restore}`. status 는 `loading | authenticated | anonymous | unreachable`. 앱을 켜면 저장된 Refresh Token 으로 복원(`/auth/me`).
- 저장: **Refresh Token 만** `expo-secure-store`(iOS Keychain / Android Keystore)에 저장. Access Token 은 메모리에만. 웹은 보안 저장소가 없어 메모리만(새로고침하면 로그아웃).
- 로그아웃: 서버 `POST /auth/logout`(이 세션만 폐기, 실패해도 계속) → 로컬 토큰 삭제.

## Google·카카오 로그인 (PR 4-D)

- 로그인 화면에 설정된 제공자의 버튼만 보인다(`EXPO_PUBLIC_GOOGLE_*_CLIENT_ID`, `EXPO_PUBLIC_KAKAO_REST_API_KEY` — `apps/mobile/.env.example`). 비어 있으면 버튼이 없어서 기존 로그인은 그대로다. 시스템 브라우저 OAuth(PKCE, `expo-auth-session`)로 Google ID 토큰·카카오 코드→액세스 토큰을 받아 서버에 넘긴다(앱 시크릿은 앱에 넣지 않는다).
- 같은 이메일의 기존 계정이 있으면 합치지 않고 안내만 보여 준다("기타 탭의 소셜 계정 연동에서 연결"). 기타 탭 계정 카드 → `/social-accounts`: 연결·해제(비밀번호가 있는 계정은 비밀번호 확인, 마지막 로그인 수단은 서버가 거부).
- `AuthProvider.signInWithSession(loginResponse)`: 소셜 로그인 응답으로 세션을 시작한다(아이디 로그인과 같은 저장·복원 경로).
- **실제 Google·카카오 앱 등록과 기기 동작은 확인하지 못했다**(앱 키 필요, 카카오는 아직 앱 등록 전). 자동 시험은 호출 경로·설정·후보 응답 처리까지.

## 이메일은 선택 (가족 참여에 인증이 필요 없다)

- 회원가입의 이메일 칸은 **선택**이다(`이메일 (선택)`): 비워도 가입되고, 적었다면 형식을 검사해 보낸다. 이메일이 없으면 가입 직후 인증 화면 없이 바로 홈으로 간다. 이메일을 적었다면 인증 메일을 보내고 인증 화면으로 가지만 "나중에 할게요"로 건너뛸 수 있다.
- 로그인 뒤에도 미인증이라는 이유로 인증 화면으로 보내지 않는다(기타 탭 계정 카드의 "이메일 인증하기"로 언제든 할 수 있다). 이메일이 없거나 인증하지 않아도 가족 그룹을 만들고 초대 코드로 참여할 수 있다(서버 `REQUIRE_EMAIL_VERIFICATION` 기본 false).
- 이메일이 없으면 비밀번호 찾기를 쓸 수 없다 — 비밀번호 찾기·아이디 찾기 화면에 "가족 관리자에게 문의" 안내가 있다.

## 기존 익명 계정과의 호환 (`ALLOW_LEGACY_TOKEN_AUTH` 는 건드리지 않음)

- 로그인하지 않으면 기존과 똑같이 동작한다(개발용 토큰/익명 가입의 `X-Gyeot-Token`). `family-group/api.js`의 익명 `signup`/`setToken` 은 그대로다.
- 정식 회원은 레거시 토큰으로 인증되지 않고(서버가 거부), 앱도 세션이 있으면 레거시 헤더를 보내지 않는다.
- 이메일 미인증 정식 회원의 가족 그룹 생성·참여 제한은 서버가 메일 설정이 있을 때만 적용한다(없으면 막지 않음).

## 딥링크 / 이메일 링크

- `app.json` 의 `scheme` 을 `familysecretary` → **`gabee`** 로 변경(백엔드 `EMAIL_LINK_BASE=gabee://` 기본값과 일치, 코드에서 옛 스킴 참조 없음).
- `gabee://verify-email?token=…` → `/verify-email`, `gabee://reset-password?token=…` → `/reset-password` (Expo Router 파일 경로가 곧 딥링크).
- 토큰 보호: 화면이 열리자마자 토큰을 상태로 옮기고 `router.setParams({ token: undefined })` 로 라우트 파라미터(React Navigation 상태)의 값을 덮어쓰고, 웹에서는 `scrubTokenFromBrowserUrl()` 로 주소창·기록의 `?token=` 도 새 기록 항목 없이 지운다. 네이티브에서 OS 가 앱을 연 원본 URL 은 앱이 지울 수 없다(앱은 저장·출력하지 않는다). 앱 코드에 `console.*` 로그가 없고 분석 도구도 없다. 토큰을 에러 메시지에 넣지 않는다. 링크가 안 열리는 환경을 위해 메일에는 같은 토큰이 코드로도 적혀 있고 화면에서 붙여 넣을 수 있다(링크 전체를 붙여 넣어도 토큰만 추출).

## 개발용 메일 (SMTP 없이 흐름 검증)

백엔드 `apps/api/.env` 에 `MAIL_BACKEND=console` (SQLite 또는 `DEBUG=true` 에서만 동작) → 인증/재설정 메일 내용이 **서버 로그**에 출력된다. 그 링크(`gabee://verify-email?token=…`)를 폰 브라우저/`npx uri-scheme open`/Expo Go 의 URL 열기로 열거나, 로그의 토큰을 화면의 코드 입력란에 붙여 넣는다. 서버에 `MAIL_BACKEND` 가 없으면 인증 요청은 503 `mail_not_configured` 이고 앱은 "메일을 보낼 수 없어요" 로 안내한다(가입·로그인은 정상).

## 테스트

- `npm test` (`apps/mobile`, Node 내장 test runner, 추가 의존성 없음):
  - 단위(`tests/unit.test.js`): 입력 검증(서버 규칙과 동일), 토큰 추출, 오류 문구, 토큰 보관소.
  - 클라이언트(`tests/client.test.js`, 가짜 서버): 헤더 혼용 방지, 자동 갱신 + 1회 재시도, 동시 8요청 갱신 1회, 재사용/만료 시 로그아웃, 네트워크 오류 시 세션 유지, 403 `email_not_verified` 알림, 앱 재시작 복원.
  - 실서버(`tests/e2e.test.js`, 평소엔 건너뜀): 임시 SQLite·`MAIL_BACKEND=console`·`ACCESS_TOKEN_TTL_SECONDS=2` 로 띄운 FastAPI 에 가입→로그인→이메일 인증→자동 갱신→로그아웃→재설정→익명 계정 호환→레거시 우회 거부, 그리고 6자리 인증번호(가입 시 관계 저장→인증번호 인증→틀린 번호→재설정 코드). 실행: `GABEE_E2E_API_URL=http://127.0.0.1:8765 GABEE_E2E_MAIL_LOG=<서버 로그 파일> npm test` (Windows 에서는 서버를 `PYTHONUTF8=1` 로 띄워야 로그의 한글 줄(6자리 코드)을 읽을 수 있다) (서버는 공용·개인 DB 가 아닌 임시 DB 로).
- `npm run lint` — CI(mobile)가 실행하는 것은 lint 이며 `npm test` 는 로컬 검증용이다(CI 워크플로우는 수정하지 않았다).
- 화면(React Native 렌더링)과 SecureStore, 딥링크 수신은 자동화하지 않았다 — 실제 기기 확인 항목은 PR 설명 참고.
