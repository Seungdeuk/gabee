# 구현 현황: family-group (통합 인증·가족 구성원)

- 상태: 진행 중 (PR 4-A 스키마 완료, 4-B 중 회원가입 API 구현, 로그인·모바일은 아직)
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

## 남은 것

- PR 4-B(나머지): 로그인(Access/Refresh 발급, `current_user` Bearer 지원, 레거시 토큰 플래그 `allow_legacy_token_auth`·`allow_anonymous_signup`), 로그아웃·refresh, 이메일 인증·비밀번호 재설정, 가입 요청 레이트리밋. **지금은 익명 가입(`POST /family-group/users`)이 기본 허용 상태**라 레거시 경로가 열려 있다 — 모바일이 정식 가입/로그인으로 전환되는 시점에 플래그 기본값을 false 로 돌린다.
- 공용 DB: 회원가입은 스키마 변경이 없고 `b6931fc30c66` 이상이면 동작한다(공용 DB 는 `6304cb91e46a` 로 확인됨).
- PR 4-C: Google/Kakao 소셜 로그인 연동 API.
- PR 4-D: 초대코드 보안 강화(관리자 승인, 레이트리밋, 만료/1회 정책) + 레거시 무제한 코드 폐기·자동 재발급.
- PR 4-E: 가족 관계·표시 이름·구성원별 별명 지정 API, owner/admin 권한 관리 API.
- PR 4-F: 위 기능들의 모바일 화면(로그인, 소셜 연동, 초대 승인, 가족 프로필).
