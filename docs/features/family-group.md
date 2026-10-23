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
  - `POST /family-group/auth/password/reset/confirm-code` `{email, code, new_password}` → 204. 없는 이메일·익명 계정·틀린 코드·한도 초과·만료는 **모두 같은 400 `reset_code_invalid`**(계정 존재 여부가 새지 않음). 약한 새 비밀번호는 400 `weak_password`(코드가 맞았다면 횟수 1회 사용).
  - **무차별 대입 방어**: 코드(메일 1통)마다 `CODE_MAX_ATTEMPTS`(기본 5)번까지만 틀릴 수 있다. 시도 횟수는 비교 *전에* 조건부 UPDATE 한 문장으로 먼저 올리므로(`failed_attempts < 5` 조건) 동시에 여러 번 찍어도 전체가 한도를 넘지 못한다(PG16 동시 10요청 시험: 비교 5번, 나머지 즉시 거부). 한도를 넘으면 맞는 코드도 쓸 수 없고 메일을 다시 받아야 한다(새 메일 = 새 코드 = 새 횟수. 재발송은 60초 간격·시간당 5회, 재설정은 이메일별 시간당 3회로 제한). 코드는 행 id 를 섞은 SHA-256 해시로만 저장한다(6자리라 해시 자체는 약하므로 횟수 제한이 실제 방어선).
  - 이전(코드 이전) 메일의 행은 `code_hash` 가 NULL 이라 코드로는 못 쓰고 링크만 된다.
  - `POST /auth/signup` 의 `role_detail`(선택): 역할이 `other` 일 때만 저장(공백 정리, 40자 초과 400 `invalid_role_detail`), `UserOut.role_detail` 로 돌려준다. 그룹별 관계(PR 4-E 설계의 `group_members.family_relation*`)와는 별개인 가입 시 입력값이다.
  - 테스트: `family_group/tests/test_email_codes.py`(SQLite), `tests/test_email_pg_e2e.py`(PG16 코드 3건 추가). `conftest.py` 가 `MAIL_BACKEND`/`SMTP_*` 를 비워 개발자 `.env` 의 실제 메일 설정이 테스트로 새지 않는다.

- **PR 4-B(일부) — 이메일 인증·비밀번호 재설정** (스키마 변경 없음, 기존 `email_verifications`/`password_resets` 사용)
  - `POST /family-group/auth/email/verify/request` (Bearer) → 204. 인증 메일을 가입한 주소로 보낸다(재발송 겸용, 이전 링크는 즉시 무효). 간격 60초·시간당 5회 초과 429 `too_many_requests`+`Retry-After`, 이미 인증됨 409 `email_already_verified`, 이메일 없는 계정 400 `no_email`, 메일 설정 없음 503 `mail_not_configured`, 발송 실패 503 `mail_send_failed`.
  - `POST /family-group/auth/email/verify/confirm` `{token}` → 200 `{email_verified:true}`. 토큰이 자격이라 로그인 없이 호출(메일 링크를 다른 기기에서 열어도 됨). 400 `verification_invalid`/`verification_used`/`verification_expired`. 토큰은 발급 당시의 이메일에 묶여 있어 이메일이 바뀌었으면 인증되지 않는다.
  - `POST /family-group/auth/password/reset/request` `{email}` → **항상 204**(계정 유무와 무관, 발송은 응답 뒤 백그라운드). 이메일별 시간당 3회·IP별 시간당 20회 초과 429(없는 이메일도 똑같이 제한), 메일 설정 없음 503(계정과 무관). 익명 계정·없는 이메일에는 메일을 보내지 않는다. 새 요청은 이전 링크를 무효화한다.
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
  - **초대 코드**: 정식 회원이 만들거나 재발급하는 코드는 10자 난수·24시간·1회(`INVITE_TTL_SECONDS`, `INVITE_MAX_USES`). **기존 익명 계정이 만드는 그룹은 호환을 위해 예전 코드(8자·제한 없음)와 즉시 참여를 그대로 유지**한다(다른 기능의 기존 흐름·테스트가 한 코드로 여러 익명 계정을 가입시킨다). 폐기는 `revoked=true`(삭제하지 않음).
  - `POST /family-group/groups/invites/reissue`(→ `{invite_code, expires_at}`), `POST .../invites/revoke`(204): **owner/admin 만**. 기존 코드는 폐기되고 새 코드가 만들어진다. 구성원은 403 `not_manager`, 그룹 없음 400 `no_group`.
  - `POST /family-group/groups/join {code}`: **정식 회원, 그리고 새 정책 코드를 쓰는 모든 사람**은 멤버십이 아니라 승인 대기 요청이 만들어진다(`JoinRequestOut`, `status:"pending"`). 기존 익명 계정이 예전 방식 코드(만료·횟수 제한 없음)를 쓸 때만 기존처럼 바로 `GroupOut`(호환). 이미 구성원이면 409 `already_member`(익명 호환 경로는 기존처럼 조용히 통과). 같은 그룹에 이미 내 대기 요청이 있으면 그 요청을 그대로 돌려주고 사용 횟수를 다시 쓰지 않는다. 없는 코드·폐기·만료·소진은 모두 같은 400 `invalid_invite`. 응답 형태가 `GroupOut | JoinRequestOut` 으로 넓어졌다(하위 호환: 기존 익명 흐름의 응답은 그대로).
  - `GET /family-group/groups/me/join-requests`(owner/admin, 승인 대기 목록), `POST .../join-requests/{id}/approve`(→ `GroupOut`), `POST .../join-requests/{id}/reject`(204): 승인해야 비로소 `group_members` 행이 생기고(**항상 `member`**) 신청자의 `active_group_id` 가 그 그룹으로 바뀐다. 다른 그룹의 요청은 404(있는지조차 알려주지 않음), 같은 그룹의 일반 구성원은 403 `not_manager`, 이미 처리된 요청은 409 `join_request_already_decided`. 거절돼도 사용 횟수는 돌려주지 않는다.
  - `GET /family-group/groups/join-requests/mine`(내 최근 요청 또는 null), `POST .../join-requests/{id}/cancel`(신청자 본인만, 204): 승인 대기 화면이 쓴다. status: `pending | approved | rejected | cancelled`.
  - **권한 상승 방지**: 요청 본문에는 role 을 받는 곳이 없다(보내도 무시). 승인된 사람은 항상 member 이고, 관리자 판단은 DB 의 `group_members.role` 만 본다. `GroupOut` 은 `my_role` 과 구성원별 `group_role` 을 내려주고, **초대 코드(`invite_code`/`invite_expires_at`)는 owner/admin 에게만** 담긴다(일반 구성원·승인 대기자에게는 null).
  - **동시성**: 사용 횟수 증가(`UPDATE invites SET use_count = use_count + 1 WHERE … 만료 전·미폐기·횟수 남음`)와 요청 결정(`UPDATE join_requests … WHERE status='pending'`)은 조건부 UPDATE 한 문장이다. 동시 승인 8건 → 성공 1·409 7, 1회용 코드를 8명이 동시에 제출 → 요청 1건·사용 횟수 1(PG16 시험), 같은 사람의 동시 중복 제출 → 부분 유니크 인덱스(`uq_join_requests_pending_per_user`)로 요청 1건.
  - **시도 제한**: 틀린 코드 입력을 `invite_attempts` 에 남기고(코드 원문·해시는 저장하지 않고, 성공했을 때만 `invite_id`), 최근 15분 실패가 5회 이상이면 계정별·IP별로 429 `too_many_attempts` + `Retry-After`(슬라이딩 윈도우, `INVITE_MAX_FAILURES`/`INVITE_FAILURE_WINDOW_SECONDS`). 이메일 미인증 정식 회원은 이전과 같이 참여를 요청할 수 없다(403 `email_not_verified`, 메일이 설정된 환경에서만).
  - 코드: `join_router.py`/`join_service.py`/`join_repository.py`/`join_schemas.py`(기존 파일은 `group_out`·`create_group`·`join_group` 호출부만 수정). 테스트: `tests/test_join_approval.py`(SQLite 15건), `tests/test_join_pg_e2e.py`(PG16 3건).

## 남은 것

- **가족 초대·승인의 후속**: 승인 대기 요청의 자동 만료, 승인/거절 알림(푸시), 신청자에게 보여줄 거절 사유, 목록에 신청자가 가입 때 적은 관계(`role_detail`, 별도 PR 병합 후)·이메일 인증 여부 표시, 레거시(제한 없는) 초대 코드 일괄 폐기·자동 재발급은 공용 DB 배포 단계가 필요해 하지 않았다(익명 계정 호환 때문에 즉시 참여 경로도 남아 있다 — `ALLOW_LEGACY_TOKEN_AUTH=false` 전환 때 함께 닫는다).
- PR 4-B(나머지): 가입 요청 레이트리밋, 전체 기기 로그아웃, `allow_anonymous_signup` 플래그, 사용자 비활성 컬럼. **익명 가입(`POST /family-group/users`)과 레거시 토큰은 기본 허용 상태**라 모바일이 정식 가입/로그인으로 전환되는 시점에 `ALLOW_LEGACY_TOKEN_AUTH=false` 로 돌린다.
- 공용 DB: 회원가입은 스키마 변경이 없고 `b6931fc30c66` 이상이면 동작한다(공용 DB 는 `6304cb91e46a` 로 확인됨).
- PR 4-C: Google/Kakao 소셜 로그인 연동 API.
- PR 4-E: 가족 관계·표시 이름·구성원별 별명 지정 API, owner/admin 권한 관리 API.
- PR 4-F: 모바일 화면 — 로그인·회원가입·이메일 인증·비밀번호 재설정은 구현(docs/features/mobile-auth.md). 남은 것: 소셜 연동, 초대 승인, 가족 프로필.
