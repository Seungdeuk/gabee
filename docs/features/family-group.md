# 구현 현황: family-group (통합 인증·가족 구성원)

- 상태: 진행 중 (PR 4-A 스키마, 4-B 회원가입·로그인·JWT 세션·이메일 인증·비밀번호 재설정 구현, 소셜·모바일은 아직)
- 담당: Seungdeuk (PR 4-A)
- 요구사항: docs/requirements/family-group.md

## 구현된 것

- **PR 4-A — DB 스키마 확장** (Alembic 리비전 `b6931fc30c66`, `355a1a748ec5` 위)
  - `users`에 `login_id`/`email`/`email_verified_at`/`password_hash` 추가(전부 nullable, 익명 계정은 NULL 유지).
  - `group_members`에 `role`(owner/admin/member, 그룹당 owner 최대 1명을 부분 유니크 인덱스로 강제)/`family_relation`/`family_relation_detail`/`display_name` 추가. 기존 행은 `groups.owner_id` 기준으로 `role` 백필.
  - `invites`에 서로게이트 `id`(UNIQUE, 기존 행도 백필)/`expires_at`/`max_uses`/`use_count` 추가. PK는 여전히 `code`, 기존 코드는 폐기하지 않음(폐기는 PR 4-D에서).
  - 신규 테이블 7개: `social_accounts`, `refresh_tokens`, `password_resets`, `email_verifications`, `member_nicknames`(그룹 멤버십을 참조하는 복합 FK), `join_requests`(pending 중복 방지 부분 유니크), `invite_attempts`.
  - `repository.add_group()`의 owner-role 버그 수정(그룹 생성자가 `member`로 저장되던 것을 `owner`로 수정) — 회귀 테스트 `test_create_group_assigns_invite_id_and_owner_role` 추가.
  - 기존 API 동작은 전혀 바뀌지 않음(회원가입/로그인/초대 참여 로직은 그대로).

- **PR 4-B(일부) — 회원가입 API** (스키마 변경 없음, 리비전 `b6931fc30c66` 컬럼 사용)
  - `POST /family-group/auth/signup` `{login_id, password, email, name, role?}` → 201 `{user}`. **토큰은 발급하지 않는다**(로그인 API 에서 발급).
  - `GET /family-group/auth/login-id-available?login_id=` → `{login_id, available}` (가입 화면 중복 확인).
  - 규칙(`family_group/credentials.py`): 아이디 4~32자, 영문 소문자로 시작, 소문자·숫자·밑줄, 대소문자 무시(소문자 저장), 예약어(admin 등) 금지 / 이메일 형식 검사 후 소문자 저장, 최대 255자 / 비밀번호 8~128자, 문자와 숫자 포함, 아이디·이메일 아이디 포함 금지, 입력 그대로 보존 / 이름 1~40자.
  - 비밀번호는 **Argon2id**(`app/shared/passwords.py`, argon2-cffi 기본 파라미터 64MiB·3회·병렬 4)로 해시해 `users.password_hash` 에만 저장한다. 원문·해시는 응답·로그에 나오지 않는다.
  - 에러(공통 형식 `{code,message}`): 400 `invalid_login_id`/`invalid_email`/`invalid_name`/`weak_password`, 409 `login_id_taken`/`email_taken`, 크기·타입 오류는 FastAPI 기본 422. 동시 가입은 DB unique 제약이 최종 방어하고 500 대신 409 로 돌려준다.
  - `UserOut` 에 `login_id`, `email`, `email_verified` 추가(익명 계정은 null/false — 하위 호환).
  - **레거시 인증 우회 차단**: 정식 회원(`login_id`/`password_hash` 가 있는 계정)은 `X-Gyeot-Token` 으로 인증할 수 없다(`shared/auth.py`, 401 `token_invalid`). `users.token`(NOT NULL·unique) 에는 아무에게도 알려주지 않는 `nologin:` 무작위 값을 넣는다.
  - 테스트: `family_group/tests/test_signup_account.py`(SQLite 38건), `tests/test_signup_pg_e2e.py`(PG16 + 최신 head, 동시 가입 포함, `GABEE_PG16_E2E=1`).

- **PR 4-B(일부) — 로그인·JWT 세션** (스키마 변경 없음, 기존 `refresh_tokens` 사용)
  - `POST /family-group/auth/login` `{login_id, password, device_label?}` → 200 `{access_token, refresh_token, token_type:"bearer", expires_in, refresh_expires_in, user}`. 없는 아이디·틀린 비밀번호·비밀번호 없는 계정은 모두 401 `invalid_credentials`(같은 메시지, 없는 계정도 해시 검증 비용을 들임).
  - `POST /family-group/auth/refresh` `{refresh_token}` → 200 `{access_token, refresh_token, ...}`. 회전: 쓴 토큰은 즉시 폐기, 폐기+발급은 한 트랜잭션, 조건부 UPDATE 로 동시 요청 중 하나만 성공. 모르는/만료 401 `refresh_invalid`, 폐기된 토큰 재사용 401 `refresh_reused`(폐기 10초 이후의 재사용은 탈취로 보고 그 사용자의 모든 세션을 폐기).
  - `POST /family-group/auth/logout` `{refresh_token}` → 204. 이 세션만 폐기, 반복·모르는 토큰도 204(멱등). 전체 기기 로그아웃은 후속.
  - `GET /family-group/auth/me` → `UserOut`. Bearer 전용(레거시 토큰 불가).
  - Access Token: JWT HS256 고정, 필수 클레임 iss/aud/sub/iat/exp/jti/token_use(`access`), 기본 15분. 권한(role, 그룹)은 클레임이 아니라 요청마다 DB 로 확인. 만료 401 `token_expired`, 그 외 401 `token_invalid`. Refresh Token: JWT 가 아닌 무작위 48바이트, DB 에는 SHA-256 해시만, 기본 30일. 설정: `JWT_SECRET`(32자 이상, 비면 프로세스 임시 키), `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS` (`.env.example`).
  - 인증 의존성 `current_user`: `Authorization` 헤더가 있으면 Bearer 만 보고 실패해도 `X-Gyeot-Token` 으로 넘어가지 않는다. 헤더가 없을 때만 레거시 토큰(익명 계정 전용, `ALLOW_LEGACY_TOKEN_AUTH` 기본 true)을 본다. 정식 회원은 레거시 토큰 불가.
  - 로그인 실패 제한: 아이디별 5회 / IP별 50회 (15분), 초과 429 `too_many_attempts` + `Retry-After`. 프로세스 메모리 기반(재시작 시 초기화, 워커별) — 기존에 쓸 수 있는 테이블(`invite_attempts` 는 초대 전용)이 없어 인프라 추가 없이 구현. 공유 한도가 필요하면 DB 테이블로 교체(후속).
  - 테스트: `family_group/tests/test_login_jwt.py`(SQLite 27건), `tests/test_login_pg_e2e.py`(PG16 5건, 동시 갱신 8요청 → 성공 1건).

- **이메일 인증·비밀번호 재설정 — 6자리 코드 추가** (Alembic `52fe05184992`, 컬럼 추가만: `email_verifications`/`password_resets` 의 `code_hash`·`failed_attempts`, `users.role_detail`)
  - 인증·재설정 메일에 **6자리 숫자 코드**와 **링크**가 함께 들어간다. 링크(긴 토큰)는 기존 그대로 열면 자동 인증/재설정 화면이고, 코드는 앱 화면에서 입력한다(6칸 입력, 남은 시간 03:00→00:00, 다시 받기). 기존 `confirm` 엔드포인트는 그대로라 하위 호환이 유지된다.
  - `POST /family-group/auth/email/verify/confirm-code` (Bearer) `{code}` → 200 `{email_verified:true}`. 로그인한 본인의 가장 최근 유효한 인증 메일만 대상. 400 `verification_code_invalid`(틀림)/`verification_code_locked`(한도 초과)/`verification_expired`(유효한 메일 없음·만료)/`verification_used`. 이미 인증된 계정은 200(멱등). 형식이 6자리 숫자가 아니면 422(횟수에 포함하지 않음).
  - `POST /family-group/auth/password/reset/confirm-code` `{login_id, code, new_password}` → 204 (이전에는 `email`, 아이디 방식으로 변경됨). 없는 아이디·익명 계정·틀린 코드·한도 초과·만료는 **모두 같은 400 `reset_code_invalid`**(계정 존재 여부가 새지 않음). 약한 새 비밀번호는 400 `weak_password`(코드가 맞았다면 횟수 1회 사용).
  - **무차별 대입 방어**: 코드(메일 1통)마다 `CODE_MAX_ATTEMPTS`(기본 5)번까지만 틀릴 수 있다. 시도 횟수는 비교 *전에* 조건부 UPDATE 한 문장으로 먼저 올리므로(`failed_attempts < 5` 조건) 동시에 여러 번 찍어도 전체가 한도를 넘지 못한다(PG16 동시 10요청 시험: 비교 5번, 나머지 즉시 거부). 한도를 넘으면 맞는 코드도 쓸 수 없고 메일을 다시 받아야 한다(새 메일 = 새 코드 = 새 횟수. 재발송은 60초 간격·시간당 5회, 재설정은 이메일별 시간당 3회로 제한). 코드는 행 id 를 섞은 SHA-256 해시로만 저장한다(6자리라 해시 자체는 약하므로 횟수 제한이 실제 방어선).
  - 이전(코드 이전) 메일의 행은 `code_hash` 가 NULL 이라 코드로는 못 쓰고 링크만 된다.
  - **메일 본문 변경(링크 제거 + 마스코트)**: 인증·재설정 메일에서 **링크를 없애고 6자리 코드만** 담는다(위 38·55번 줄의 링크 설명은 이 변경 전 내용). 메일은 글자 본문 + HTML 본문을 함께 보내고, HTML 에는 마스코트(`app/shared/assets/gabee-mascot.png`, 앱 아이콘을 200px 로 줄인 약 40KB)가 `cid:gabee-mascot` 로 **메일에 내장**된다(외부 이미지 서버·"이미지 표시" 누르기 불필요). 파일이 없으면 이미지만 빠지고 메일은 나간다. 템플릿은 `app/shared/mail_templates.py`. 토큰 확인 엔드포인트(`confirm`)는 그대로 있지만 메일로는 토큰이 전달되지 않는다(링크를 다시 넣을 때를 위해 남김, `EMAIL_LINK_BASE` 는 예약 설정).
  - **아이디 찾기 · 비밀번호 찾기(아이디+이메일)**: `POST /family-group/auth/login-id/recover` `{email}` → **항상 204**. 그 이메일로 가입한 정식 계정이 있으면 **가입한 메일로만** 아이디를 보낸다(응답에는 절대 싣지 않음, 토큰·코드 없음, 링크 없음, 마스코트 HTML). 인증하지 않은 이메일이어도 보낸다(이메일은 가입 때 선택, 그 주소는 계정에 등록된 것). 없는 이메일·익명 계정에는 보내지 않고 응답은 같다. 요청 제한은 재설정과 같은 설정(`RESET_MAX_PER_EMAIL_PER_HOUR`·`RESET_MAX_PER_IP_PER_HOUR`)을 쓰되 **카운트는 재설정과 따로**(`recover-*` 키)이며, 없는 이메일도 똑같이 제한된다. 메일 설정이 없으면 503 `mail_not_configured`(계정과 무관). 발송 실패는 `mail_delivery_failed kind=login_id_recover` 로그(수신자·아이디 제외). 이메일을 등록하지 않은 계정은 앱 화면에서 '가족 관리자에게 문의' 안내만 한다(서버는 계정 존재를 알리지 않음).
  - 비밀번호 찾기 요청은 이제 `{login_id, email}` 이며 옛 `{email}` 만 보내는 방식은 삭제했다(출시 전이라 하위 호환 없음). 6자리 코드 확인은 `login_id` 로 한다.
  - 테스트: `family_group/tests/test_account_recovery.py`(14건: 아이디·이메일 둘 다 일치할 때만 발송, 응답 동일, 대소문자·공백, 익명 계정, 옛 email 방식 거부 422, 아이디 찾기 발송·응답 동일·미인증 이메일·제한·카운트 분리·503·발송 실패 로그), 기존 재설정 시험은 새 계약으로 수정.
  - 테스트: 메일에 링크·토큰이 없고 HTML 에 코드가 있음, SMTP 메시지에 text/html + 내장 PNG, 이미지 파일이 없어도 발송(`test_email_flows.py`·`test_email_codes.py`). 토큰 엔드포인트 시험은 발급 시점의 토큰을 가로채 쓴다.
  - `POST /auth/signup` 의 `role_detail`(선택): 역할이 `other` 일 때만 저장(공백 정리, 40자 초과 400 `invalid_role_detail`), `UserOut.role_detail` 로 돌려준다. 그룹별 관계(PR 4-E 설계의 `group_members.family_relation*`)와는 별개인 가입 시 입력값이다.
  - 테스트: `family_group/tests/test_email_codes.py`(SQLite), `tests/test_email_pg_e2e.py`(PG16 코드 3건 추가). `conftest.py` 가 `MAIL_BACKEND`/`SMTP_*` 를 비워 개발자 `.env` 의 실제 메일 설정이 테스트로 새지 않는다.

- **PR 4-B(일부) — 이메일 인증·비밀번호 재설정** (스키마 변경 없음, 기존 `email_verifications`/`password_resets` 사용)
  - `POST /family-group/auth/email/verify/request` (Bearer) → 204. 인증 메일을 가입한 주소로 보낸다(재발송 겸용, 이전 링크는 즉시 무효). 간격 60초·시간당 5회 초과 429 `too_many_requests`+`Retry-After`, 이미 인증됨 409 `email_already_verified`, 이메일 없는 계정 400 `no_email`, 메일 설정 없음 503 `mail_not_configured`, 발송 실패 503 `mail_send_failed`.
  - `POST /family-group/auth/email/verify/confirm` `{token}` → 200 `{email_verified:true}`. 토큰이 자격이라 로그인 없이 호출(메일 링크를 다른 기기에서 열어도 됨). 400 `verification_invalid`/`verification_used`/`verification_expired`. 토큰은 발급 당시의 이메일에 묶여 있어 이메일이 바뀌었으면 인증되지 않는다.
  - `POST /family-group/auth/password/reset/request` `{login_id, email}` → **아이디와 이메일이 같은 계정과 둘 다 일치하면 204**(발송은 응답 뒤 백그라운드), **일치하지 않으면 400 `reset_mismatch`("아이디와 이메일이 일치하지 않아요")**. 없는 아이디·익명 계정·이메일 없는 계정·이메일 불일치는 **응답 본문이 모두 같아서** 아이디가 있는지 이메일이 틀렸는지는 알 수 없다(짝이 맞는지만 알려 준다. 사용자 요청으로 이전의 '항상 204'에서 바꿈). 아이디는 공백 제거·소문자로 비교하고 형식 오류도 같은 불일치로 본다. 이메일별 시간당 3회·IP별 시간당 20회 초과 429 — **불일치도 횟수에 세어서** 짝을 계속 바꿔 대입하는 것을 막는다(제한이 먼저, 일치 판단은 그 뒤). 메일 설정 없음 503(계정과 무관). 새 요청은 이전 링크를 무효화한다. **남는 위험**: 제한 안에서 (아이디, 이메일) 짝이 맞는지 시험해 볼 수 있다(예: 알고 있는 아이디에 이메일을 추측해 대입하면 이메일 하나당 한 번씩 확인). 아이디 찾기(`login-id/recover`)는 여전히 항상 204 라 이메일이 가입됐는지는 이 경로로 알 수 없다.
  - `POST /family-group/auth/password/reset/confirm` `{token, new_password}` → 204. 새 비밀번호는 가입과 같은 규칙(약하면 400 `weak_password`, 이때 토큰은 소비되지 않음)으로 Argon2id 해시, **모든 기기의 Refresh Token 폐기**, 같은 사용자의 다른 재설정 링크 무효, 로그인 잠금 해제. 400 `reset_token_invalid`/`reset_token_used`/`reset_token_expired`.
  - **재설정 후 Access Token**: Refresh Token 폐기에 더해, Access Token 에 비밀번호 버전(`pv`, 비밀번호 해시에서 파생한 16자리 값)을 넣고 요청마다 현재 값과 비교하므로 **비밀번호가 바뀌면 이전에 발급된 Access Token 이 만료(15분)를 기다리지 않고 즉시 401 `token_invalid`** 가 된다(DB 변경 없음). 다른 사용자의 토큰은 영향 없음. 이 변경 이전에 발급된(`pv` 없는) 토큰은 거부되어 한 번 다시 로그인해야 한다. 로그아웃은 해당 Refresh Token 만 폐기하므로 Access Token 은 만료까지 유효하다(아래 한계 참고).
  - **백그라운드 발송 실패**: 재설정 메일은 응답 뒤에 보내 계정 존재 여부가 응답·시간으로 새지 않게 한다. 발송이 실패하면 요청자에게는 알리지 않지만 서버 로그에 `ERROR mail_delivery_failed kind=password_reset reason=<오류 종류>` 로 남는다(수신자·본문·토큰·SMTP 응답 제외, 예기치 못한 예외 포함). 운영에서는 이 로그 키로 알림을 건다. 인증 메일은 요청자가 로그인한 본인이라 동기 발송하고 실패를 503 으로 알린다.
  - 토큰: `secrets.token_urlsafe(48)` 원문은 메일에만, DB 에는 SHA-256 해시만. 일회용(조건부 UPDATE 한 문장으로 소비 → 동시 요청 중 하나만 성공). 유효 기간: 인증 **3분**(`EMAIL_VERIFY_TTL_SECONDS`, 기본 180), 재설정 30분(`PASSWORD_RESET_TTL_SECONDS`).
  - **미인증 계정 정책(2026-10 변경: 기본은 막지 않음)**: 이메일은 **가입 때 선택**이고(`POST /auth/signup` 의 `email` 생략·빈 문자열·공백 모두 "이메일 없음", 적었다면 형식·중복 검사는 그대로), **이메일이 없거나 인증하지 않아도 가족 그룹을 만들고 참여할 수 있다**(`REQUIRE_EMAIL_VERIFICATION` 기본 false). `true` 로 켜면 아래 제한이 다시 적용되고, 이메일이 없는 계정은 켜도 막지 않는다. 이메일이 없는 계정은 인증 메일(400 `no_email`)과 비밀번호 재설정 메일을 쓸 수 없다(비밀번호를 잊으면 복구 수단이 없다 — 후속: 가입 뒤 이메일 등록). 아래는 정책을 켰을 때의 동작이다. 로그인·내 정보 조회·인증 메일 재요청·비밀번호 변경(재설정)은 허용, **가족 그룹 생성·참여(`POST /groups`, `/groups/join`)는 403 `email_not_verified`**. 익명 계정(모바일 현재 방식)은 영향 없음. **메일 발송이 설정되지 않은 환경(SMTP 없음, 인증 메일을 보낼 수 없음)에서는 이 정책을 적용하지 않는다** — 가입 후 막다른 길을 막기 위함이며, `MAIL_BACKEND` 를 설정하는 순간부터 자동으로 적용된다. `REQUIRE_EMAIL_VERIFICATION=false` 로 메일이 있어도 끌 수 있다(기본 true).
  - **메일 발송**: 표준 라이브러리 smtplib(새 의존성·인프라 없음). `MAIL_BACKEND=smtp`+`SMTP_*`(실제), `console`(개발 전용, 로컬 SQLite/DEBUG=true 에서만, 메일 내용을 로그에 출력), 기본 꺼짐(503, 성공으로 처리하지 않음). 발송 실패 로그에는 수신자·본문·서버 응답 내용을 남기지 않는다. 링크는 `EMAIL_LINK_BASE`(기본 `gabee://`) + `verify-email`/`reset-password` + `?token=` — 모바일 딥링크 연동 시 확정.
  - **이메일 선점(pre-hijacking) 검토**: 공격자가 피해자 이메일로 미리 미인증 계정을 만들어도 ① 미인증이라 가족 그룹에 들어갈 수 없고 ② 피해자가 그 이메일로 비밀번호 재설정을 하면 공격자의 비밀번호·세션이 모두 사라지며(재설정 링크는 메일함 주인에게만 가고 성공하면 이메일 인증 처리됨) 피해자가 계정을 갖는다. 공격자는 메일함이 없어 인증 토큰을 얻을 수 없다. 인증 메일은 계정에 등록된 주소로만 가며 요청 본문으로 주소를 받지 않는다. 남는 한계: 가입 시 `email_taken`(409)이 계정 존재를 알려주고, 선점당한 사용자는 가입이 막힌 채 재설정으로 되찾아야 한다.
  - 테스트: `family_group/tests/test_email_flows.py`(SQLite 28건, 메일은 가짜 발송기로 가로챔), `tests/test_email_pg_e2e.py`(PG16 4건, 동시 소비 8요청 → 성공 1건).

### 로그인·JWT 운영 참고와 알려진 한계

- **JWT_SECRET**: 32자 이상 무작위 값을 서버 `.env` 에만 둔다(코드·Git 금지). 비어 있을 때 로컬 SQLite 나 `DEBUG=true` 에서만 프로세스 임시 키를 쓴다(재시작하면 로그인이 풀림). **PostgreSQL(공용·운영)에서 DEBUG 없이 비어 있거나 32자 미만이면 로그인·갱신·Bearer 인증이 503 `auth_not_configured`** 이고, 서버 시작·`/health`·레거시 토큰 인증(모바일 현재 방식)·가입 등 나머지 API 는 그대로 동작한다. 공용 DB 에 붙여 개발하는 팀원은 `.env` 에 `JWT_SECRET`(개발용 아무 32자 이상 값) 또는 `DEBUG=true` 를 둔다.
- **로그아웃해도 Access Token 은 만료(기본 15분)까지 유효**하다. Access Token 은 서버에 상태를 두지 않는 JWT 라 폐기 목록이 없다. 로그아웃은 Refresh Token 만 폐기하므로 더 이상 갱신은 되지 않는다. 즉시 차단이 필요하면 만료 시간(`ACCESS_TOKEN_TTL_SECONDS`)을 줄이거나, 후속으로 `users` 에 토큰 버전/비활성 컬럼을 두고 요청마다 확인한다(마이그레이션 필요). 계정이 삭제되면 남은 Access Token 도 거부된다.
- **로그인 횟수 제한의 한계**: 프로세스 메모리 기반이라 ① 서버 재시작 시 초기화 ② 워커·서버가 여러 개면 프로세스별로 집계(한도가 사실상 늘어남) ③ 아이디별 제한은 공격자가 남의 아이디를 일부러 틀려 일시적으로 잠글 수 있음(15분, `Retry-After`) ④ IP 제한은 `request.client.host` 기준이라, **리버스 프록시(Caddy) 뒤에서 uvicorn 을 `--proxy-headers --forwarded-allow-ips=<프록시 IP>` 없이 실행하면 모든 사용자가 프록시 IP 하나로 집계**된다 — 그 경우 `LOGIN_MAX_FAILURES_PER_IP=0` 으로 IP 제한을 끈다. 오래된 기록은 주기적으로 청소하므로 없는 아이디를 무작위로 시도해도 메모리가 계속 늘지 않는다. 공유·영구 한도가 필요하면 DB 테이블(마이그레이션)로 교체한다.
- Refresh Token 재사용은 폐기 10초 이후면 탈취로 보고 그 사용자의 모든 세션을 폐기한다(10초 이내는 동시 갱신 경쟁으로 보고 해당 요청만 거부).
- 이메일 중복 응답(409 `email_taken`)은 계정 존재 여부를 알려준다(가입 레이트리밋과 함께 후속).
- 메일 요청 횟수 제한(인증 재발송·재설정)도 로그인 제한과 같이 프로세스 메모리 기반이다(재시작 시 초기화, 워커별). `created_at` 컬럼이 없어 DB 로 셀 수 없고 마이그레이션 없이 구현했다. 로그인 직후 해시 파라미터 갱신(`needs_rehash`)도 비밀번호 버전을 바꾸므로 다른 기기의 Access Token 이 한 번 거부될 수 있다(Refresh 로 다시 받으면 된다).

- **가족 초대·가입 승인** (로드맵 PR 4-B, 스키마 변경 없음 — 4-A 의 `invites`/`join_requests`/`invite_attempts`/`group_members.role` 사용)
  - **초대 코드**: 정식 회원이 만들거나 재발급하는 코드는 10자 난수·24시간·1회(`INVITE_TTL_SECONDS`, `INVITE_MAX_USES`). **기존 익명 계정이 만드는 그룹은 호환을 위해 예전 코드(8자·만료/횟수 제한 없음)를 그대로 발급**한다. 단 이 코드로도 **참여는 승인 대기를 거친다**(2026-10 보안 수정: 익명 계정의 즉시 참여 경로 `join_immediately` 제거). 폐기는 `revoked=true`(삭제하지 않음).
  - `POST /family-group/groups/invites/reissue`(→ `{invite_code, expires_at}`), `POST .../invites/revoke`(204): **owner/admin 만**. 기존 코드는 폐기되고 새 코드가 만들어진다. 구성원은 403 `not_manager`, 그룹 없음 400 `no_group`.
  - `POST /family-group/groups/join {code}`: **모든 계정(정식·익명, 새 코드·레거시 코드)** 은 멤버십이 아니라 승인 대기 요청이 만들어진다(`JoinRequestOut`, `status:"pending"`). 응답은 항상 `JoinRequestOut` 이다(예전 익명 계정의 `GroupOut` 즉시 응답은 사라졌다 — 하위 호환 변경, 모바일은 이미 `requestJoin` 으로 pending 을 처리한다). 이미 구성원이면 익명 계정도 409 `already_member`. 같은 그룹에 이미 내 대기 요청이 있으면 그 요청을 그대로 돌려주고 사용 횟수를 다시 쓰지 않는다. 없는 코드·폐기·만료·소진은 모두 같은 400 `invalid_invite`. 응답 형태는 `JoinRequestOut` 하나다.
  - `GET /family-group/groups/me/join-requests`(owner/admin, 승인 대기 목록), `POST .../join-requests/{id}/approve`(→ `GroupOut`), `POST .../join-requests/{id}/reject`(204): 승인해야 비로소 `group_members` 행이 생기고(**항상 `member`**) 신청자의 `active_group_id` 가 그 그룹으로 바뀐다. 다른 그룹의 요청은 404(있는지조차 알려주지 않음), 같은 그룹의 일반 구성원은 403 `not_manager`, 이미 처리된 요청은 409 `join_request_already_decided`. 거절돼도 사용 횟수는 돌려주지 않는다.
  - `GET /family-group/groups/join-requests/mine`(내 최근 요청 또는 null), `POST .../join-requests/{id}/cancel`(신청자 본인만, 204): 승인 대기 화면이 쓴다. status: `pending | approved | rejected | cancelled`.
  - **권한 상승 방지**: 요청 본문에는 role 을 받는 곳이 없다(보내도 무시). 승인된 사람은 항상 member 이고, 관리자 판단은 DB 의 `group_members.role` 만 본다. `GroupOut` 은 `my_role` 과 구성원별 `group_role` 을 내려주고, **초대 코드(`invite_code`/`invite_expires_at`)는 owner/admin 에게만** 담긴다(일반 구성원·승인 대기자에게는 null).
  - **동시성**: 사용 횟수 증가(`UPDATE invites SET use_count = use_count + 1 WHERE … 만료 전·미폐기·횟수 남음`)와 요청 결정(`UPDATE join_requests … WHERE status='pending'`)은 조건부 UPDATE 한 문장이다. 동시 승인 8건 → 성공 1·409 7, 1회용 코드를 8명이 동시에 제출 → 요청 1건·사용 횟수 1(PG16 시험), 같은 사람의 동시 중복 제출 → 부분 유니크 인덱스(`uq_join_requests_pending_per_user`)로 요청 1건.
  - **시도 제한**: 틀린 코드 입력을 `invite_attempts` 에 남기고(코드 원문·해시는 저장하지 않고, 성공했을 때만 `invite_id`), 최근 15분 실패가 5회 이상이면 계정별·IP별로 429 `too_many_attempts` + `Retry-After`(슬라이딩 윈도우, `INVITE_MAX_FAILURES`/`INVITE_FAILURE_WINDOW_SECONDS`). 이메일 미인증 정식 회원은 이전과 같이 참여를 요청할 수 없다(403 `email_not_verified`, 메일이 설정된 환경에서만).
  - 코드: `join_router.py`/`join_service.py`/`join_repository.py`/`join_schemas.py`(기존 파일은 `group_out`·`create_group`·`join_group` 호출부만 수정). 테스트: `tests/test_join_approval.py`(SQLite 15건), `tests/test_join_pg_e2e.py`(PG16 3건).

- **Google·Kakao 로그인·계정 연동** (로드맵 PR 4-D, 스키마 변경 없음 — 4-A 의 `social_accounts` 사용)
  - `POST /family-group/auth/social/{google|kakao} {provider_token, role?, device_label?}` → `LoginOut`(로그인·신규 가입) 또는 `{candidate_account: true, masked_email}`. provider_token 은 Google=ID 토큰, Kakao=액세스 토큰. 이미 연동된 (provider, uid) 면 그 계정으로 로그인, 아니면 **같은 이메일의 기존 계정이 있을 때 자동으로 합치지 않고** 마스킹한 이메일(`j***@example.com`)만 돌려준다(기존 방식으로 로그인한 뒤 연동). 없으면 소셜 전용 계정(비밀번호·아이디 없음)을 새로 만든다. 제공자가 검증한 이메일만 저장하고 그 계정은 이메일 인증이 끝난 것으로 본다(이메일이 없어도 가입된다).
  - `POST .../auth/social/{provider}/link {provider_token, password?}`(Bearer, 204): 내 계정에 연결. **비밀번호가 있는 계정은 비밀번호를 다시 확인**(없으면 400 `password_required`, 틀리면 401 `invalid_credentials` 이고 로그인 실패 제한에 센다). 다른 계정에 이미 연결된 소셜 계정은 409 `social_already_linked`, 같은 종류를 또 연결하면 409 `social_provider_already_linked`, 같은 계정 재연결은 204(멱등).
  - `GET .../auth/social`(내 연동 목록), `DELETE .../auth/social/{provider}`(204): **마지막 로그인 수단 보호** — 연동 수 + (비밀번호가 있으면 1)이 1 이하면 403 `last_login_method`. 사용자 행을 `SELECT … FOR UPDATE` 로 잠가 동시 해제를 한 줄로 세운다(PG16: 동시 해제 2건 → `[204, 403]`). 연동되지 않은 제공자는 404.
  - **제공자 검증**(`social_providers.py`): Google 은 Google 의 `tokeninfo` 로 ID 토큰 서명을 확인하고 서버가 aud(`GOOGLE_CLIENT_IDS` 중 하나)·iss·만료를 다시 본다. 로컬 JWKS 서명 검증은 `cryptography` 패키지(의존성 승인)가 필요해 그때 같은 `Identity` 를 돌려주도록 바꾼다. Kakao 는 `access_token_info`(우리 앱의 `KAKAO_APP_ID` 인지 확인) → `v2/user/me`. 설정이 비어 있으면 503 `social_not_configured`, 토큰 오류 401 `social_token_invalid`(IP별 실패 제한), 제공자 서버 오류 503 `social_unavailable`. 토큰은 로그·오류에 남기지 않는다. **MVP 의 Firebase 로그인 토큰(iss `securetoken.google.com`)은 받지 않는다** — 일반 Google OAuth 클라이언트의 ID 토큰만 받는다.
  - 소셜 계정은 정식 회원이다: 이메일 인증 정책 대상이 아니고(검증된 이메일), 그룹 생성은 새 정책 초대 코드, 참여는 승인 흐름을 따른다(익명 계정 호환 경로를 쓰지 않는다).
  - 설정(`.env`): `GOOGLE_CLIENT_IDS`(쉼표로 여러 개), `KAKAO_APP_ID`, `SOCIAL_HTTP_TIMEOUT_SECONDS`. 앱 키는 서버 `.env` 에만 둔다.
  - 코드: `social_router/service/repository/providers/schemas.py`. 테스트: `tests/test_social_login.py`(SQLite 19건, 제공자 응답 해석은 네트워크 없이), `tests/test_social_pg_e2e.py`(PG16 3건).

- **가족 관계·표시 이름·별명·관리자 지정** (로드맵 PR 4-C, 스키마 변경 없음 — 4-A 의 `group_members.family_relation/family_relation_detail/display_name/role`, `member_nicknames` 사용)
  - `PUT /family-group/groups/me/profile {display_name?, family_relation?, family_relation_detail?}` → `GroupOut`: **내 멤버십만** 바꾼다(다른 사람 것을 바꾸는 경로가 없다). 보낸 항목만 바뀌고 null/빈 문자열은 지운다. 관계는 `mom|dad|son|daughter|grandma|grandpa|other`(그 외 422). `other` 일 때만 직접 적은 관계(40자)를 둘 수 있고(아니면 400 `relation_detail_needs_other`), 다른 관계로 바꾸면 직접 입력은 지워진다. 표시 이름은 40자(400 `invalid_display_name`), 그룹을 안 정했으면 400 `no_group`. 관계·이름은 **그룹 멤버십별**이라 한 사용자가 그룹마다 다르게 둘 수 있다.
  - `PUT /family-group/groups/members/{user_id}/role {role: "admin"|"member"}` → `GroupOut`: **소유자(owner)만** 관리자 지정·해제(관리자·구성원은 403 `not_owner`). 소유자는 대상이 될 수 없고(400 `cannot_change_owner`), `owner` 로 올리는 값은 422 로 받지 않는다(소유권 이전은 이번 범위 밖). 다른 그룹 사람·없는 사람은 404. 변경은 `role != 'owner'` 조건부 UPDATE 한 문장이라 동시 요청에도 그룹당 owner 1명이 유지된다(PG16 시험).
  - `GET /family-group/groups/me/nicknames`, `PUT /family-group/groups/me/nicknames/{target_user_id} {nickname?, memo?}` → `{target_user_id, nickname, memo}`: **내가 쓴 별명·메모만** 조회·수정(쿼리가 `owner_user_id = 나` 로 고정돼 다른 사람 것은 나오지 않는다), 다른 구성원에게는 영향이 없다. 둘 다 비우면 지운다. 자기 자신 400 `cannot_nickname_self`, 다른 그룹 사람 404, 별명 40자 400 `invalid_nickname`. DB 의 복합 FK 가 그룹 구성원만 쓰고 대상이 되도록 한 번 더 막는다(서비스를 거치지 않아도 PG16 에서 거부됨).
  - `GroupOut` 에 `my_id`(응답을 받는 사람의 id)가 추가되고 `MemberOut` 에 `display_name`/`family_relation`/`family_relation_detail` 이 추가됐다(전부 선택 필드, 하위 호환). 기존 익명 계정도 같은 API 를 쓸 수 있다.
  - 코드: `profile_router/service/repository/schemas.py`(기존 파일은 `group_out`·`MemberOut`·라우터 포함 한 줄만 수정). 테스트: `tests/test_family_profile.py`(SQLite 13건), `tests/test_profile_pg_e2e.py`(PG16 3건).

- **프로필 사진 업로드** (로드맵 PR B, 서버·DB — 모바일 화면은 별도 PR)
  - 스키마: `users.profile_photo_path`(String 255)·`profile_photo_updated_at`(DateTime tz), 둘 다 nullable 인 expand 변경(리비전 `a7d3e1c94b52`, ADD COLUMN 만). 기존 사용자는 NULL.
  - `POST /family-group/me/photo`(multipart `file`, 로그인 필요) → `{photo_url, photo_updated_at}`. JPEG/PNG/WebP 만, 2MB 초과 413 `photo_too_large`, 이미지가 아니거나 깨진/위장 파일·다른 형식(GIF 등)·긴 변 8000px 초과 400 `invalid_image`, 사용자당 분당 5회 초과 429 `too_many_uploads`(+`Retry-After`). 서버가 EXIF 회전을 반영한 뒤 **EXIF·GPS 등 메타데이터를 모두 버리고**, 가운데 정사각형 크롭 → 최대 512x512 JPEG(quality 85)로 다시 만들어 `DATA_DIR/profile_photos/<user_id>_<버전>.jpg` 에 임시 파일 → `os.replace` 로 저장한다. 파일 이름은 사용자 id·시각으로만 만들고 사용자 입력(업로드 파일명 등)은 경로에 쓰지 않는다.
  - `DELETE /family-group/me/photo`(204, 사진이 없어도 204): 파일 삭제 + 칼럼 NULL.
  - `GET /family-group/users/{user_id}/photo`(로그인 필요): **요청자와 대상이 같은 가족 그룹 구성원(본인 포함)일 때만** 이미지(`image/jpeg`)를 준다. 다른 가족·가족 없음·없는 사용자·사진 없음은 모두 같은 404 라 존재 여부를 알 수 없다. `Cache-Control: private, max-age=3600`, `ETag`(바꾼 시각 밀리초, `If-None-Match` 일치 시 304), `X-Content-Type-Options: nosniff`.
  - `UserOut`(`GET /me` 등)과 `MemberOut`(구성원 목록)에 **추가 필드** `photo_url`(없으면 null, 있으면 상대 경로 `/family-group/users/{id}/photo?v=<바꾼 시각 밀리초>`)이 생겼다(하위 호환). 앱은 서버 주소 뒤에 붙이고 인증 헤더를 함께 보내 요청한다(이미지 요청이라 `?v=` 가 바뀌면 캐시가 새로 받는다).
  - 방어(검토 반영): 디코딩 전에 긴 변 8000px·총 1600만 화소 초과를 400 `invalid_image` 로 거절하고, JPEG 는 `draft` 축소 디코딩·그 외는 `thumbnail`(1024px)로 먼저 줄인 뒤 회전·변환·크롭한다. 동시 처리 업로드는 2건(`BoundedSemaphore`), 초과는 대기 없이 503 `photo_busy`. 업로드 경로(`POST /family-group/me/photo`)만 순수 ASGI 미들웨어(`photo_limit.py`)가 multipart 파싱 전에 Content-Length 2.1MB 초과(chunked 는 읽은 바이트 수)를 413 `photo_too_large` 로 거절한다. 사용자 행을 `FOR UPDATE` 로 잠가(+프로세스 락) 업로드·삭제를 직렬화하고, 파일은 `<user_id>_<버전>.jpg` 로 새로 쓴 뒤 DB 커밋이 성공한 후에만 이전 파일을 지운다(커밋 실패 시 새 파일 삭제).
  - 배포 권고: Caddy 에도 업로드 경로에 `request_body { max_size 2.2MB }` 를 두면 앱에 닿기 전에 큰 본문을 막을 수 있다(`deploy/` 는 이 PR 에서 수정하지 않음).
  - 사진 내용·경로는 로그에 남기지 않고 외부 서비스(LLM 포함)로 보내지 않는다. 저장 위치는 `DATA_DIR`(기본 `./data`)이라 운영 배포에서는 이 폴더가 컨테이너 볼륨에 있어야 사진이 유지된다.
  - 코드: `photo_router/service/repository/schemas.py`. 테스트: `tests/test_profile_photo.py`(SQLite 16건, `tmp_path` 를 `DATA_DIR` 로 지정).

## 남은 것
- **레거시 초대 코드의 재신청 남용**: 익명 계정이 만든 그룹의 코드(8자, 만료·횟수 제한 없음)는 거절/취소 뒤에도 같은 사용자가 무제한 재신청해 관리자 대기 목록을 채울 수 있다(승인 우회는 아님). 코드를 재발급하면 새 정책 코드로 바뀐다. 작은 완화안(미구현): 같은 사용자가 같은 그룹에서 거절된 직후 N분 동안 재신청 제한.

- **가족 나가기** (스키마 변경 없음 — `profile_router/service/repository`)
  - `POST /family-group/groups/me/leave`(본문 없음) → **204**. 그룹은 `current_group_id` 로만 정한다(그룹 없음 400 `no_group`, 구성원 아님 403 `not_member`, 미인증 401). **소유자는 혼자여도 나갈 수 없다**: 400 `cannot_leave_owner`(소유권 이전은 범위 밖). 관리자·구성원은 나갈 수 있다.
  - 한 트랜잭션: ① 이 그룹에서 내가 쓴(`owner_user_id`) 별명과 나에게 붙은(`target_user_id`) 별명 삭제(복합 FK 에 ondelete 가 없어 멤버십보다 먼저) ② `role != 'owner'` 조건부 DELETE 한 문장으로 멤버십 삭제(0행이면 다시 조회해 owner 면 `cannot_leave_owner`, 이미 없으면 403 `not_member`) ③ `users.active_group_id` 가 이 그룹이면 NULL. 두 번째 호출·동시 호출은 400/403 이고 500 이 아니다.
  - **의도적으로 남기는 것**(제품 결정): 지난 채팅 메시지·일정·가계·1:1 대화방 등 그 사람이 만든 데이터는 지우지 않는다. 토큰도 폐기하지 않고 멤버십 확인으로 막는다. 나간 뒤에는 초대 코드로 다시 가입 요청을 보낼 수 있다. 이름 변경·구성원 강제 퇴출 API 는 만들지 않기로 했다.
  - 시험: `family_group/tests/test_leave.py`.
- **가족 초대·승인의 후속**: 승인 대기 요청의 자동 만료, 승인/거절 알림(푸시), 신청자에게 보여줄 거절 사유, 목록에 신청자가 가입 때 적은 관계(`role_detail`, 별도 PR 병합 후)·이메일 인증 여부 표시, 레거시(제한 없는) 초대 코드 일괄 폐기·자동 재발급은 공용 DB 배포 단계가 필요해 하지 않았다(익명 계정의 즉시 참여 경로는 닫았다 — 코드가 새도 관리자 승인이 필요하다. 코드 자체의 영구 유효성은 남아 있어 관리자가 재발급하면 새 정책 코드로 바뀐다).
- PR 4-B(나머지): 가입 요청 레이트리밋, 전체 기기 로그아웃, `allow_anonymous_signup` 플래그, 사용자 비활성 컬럼. **익명 가입(`POST /family-group/users`)과 레거시 토큰은 기본 허용 상태**라 모바일이 정식 가입/로그인으로 전환되는 시점에 `ALLOW_LEGACY_TOKEN_AUTH=false` 로 돌린다.
- 공용 DB: 회원가입은 스키마 변경이 없고 `b6931fc30c66` 이상이면 동작한다(공용 DB 는 `6304cb91e46a` 로 확인됨).
- PR 4-C: Google/Kakao 소셜 로그인 연동 API.
- PR 4-E: 가족 관계·표시 이름·구성원별 별명 지정 API, owner/admin 권한 관리 API.
- 홈(AI 채팅) 인사말 아래 "가족 만들기"(`/family-create`)·"초대 코드로 참여"(`/family-join`) 버튼 둘(2026-11): 가족 그룹도 승인 대기 요청도 없을 때만 보인다(`JoinFamilyPrompt`, 판단은 `joinPrompt.js`). AI 화면은 `emptyAction` 자리만 두고 홈 라우트(`(tabs)/chat.js`)에서 조립한다. 앱만 바뀌고 서버는 그대로.
- PR 4-F: 모바일 화면 — 로그인·회원가입·이메일 인증·비밀번호 재설정은 구현(docs/features/mobile-auth.md). 남은 것: 소셜 연동, 초대 승인, 가족 프로필.
