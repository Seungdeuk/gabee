# 기능: family-group (통합 인증 · 가족 구성원)

> PR 4-0 — 설계 전용 문서. 이번 단계에서는 코드·마이그레이션을 실행하지 않았다. "미정" 항목은 Claude가 임의로 정하지 않고 팀 결정을 기다린다(`docs/requirements/_template.md` 규칙 그대로).
> **2026-10-22 업데이트 1**: 익명 가입/레거시 토큰의 전환 정책, 초대코드 보안(길이·만료·레이트리밋·관리자 승인), 소셜 로그인 구현 방식 4가지를 팀이 확정했다. 이 문서에 반영하고 기존 "미정" 중 해당 항목을 "결정됨"으로 옮겼다 — 아래 각 절과 맨 뒤 "결정됨" 목록 참고. 이번에도 코드·마이그레이션 실행, Commit/Push/PR은 하지 않았다.
> **2026-10-22 업데이트 2**: 설계 리뷰 보완 7건 반영 — 초대코드 원문 참조를 `invite_id` 구조로 변경, 기존 무제한 초대코드의 안전한 폐기 정책 추가, 전환기 플래그 기본값을 `false`(명시적 활성화 전까지 비활성)로 변경, 이메일 미인증 허용 범위·온보딩 흐름 명시, 레이트리밋·환불·중복요청·재가입 정책 확정, owner 전용 관리자 지정/해제·마지막 로그인 수단 보호 규칙 추가, PR 4-D를 초대·승인(4-D)과 가족 프로필(4-E)로 분리(모바일 UI는 4-F로 밀림). FK·Unique·인덱스·동시 요청 처리 방안도 함께 명시했다. 이번에도 DB 변경·Alembic 실행·Commit/Push/PR은 하지 않았다. (별도로, 이전에 승인된 Noto Sans KR 모바일 코드 변경은 미커밋 상태로 그대로 보존했다 — 이 설계 문서와는 무관한 변경이다.)

## 목적

지금은 이름·역할만 입력하면 가입되는 익명에 가까운 토큰 하나로 전체 인증을 처리한다. 이 기능은 (1) 아이디·비밀번호·이메일 기반 일반 회원가입/로그인, (2) Google·Kakao 소셜 로그인과 계정 연동, (3) 가족 그룹 내 역할(owner/admin/member)과 가족 관계(엄마/아빠/…)·표시 이름·개인별 별명을 추가해, "로그인한 사람이 자기 가족만 본다"는 PR 3의 권한 체계 위에 실제 신원 확인을 올린다.

## 1. 현재 구현 vs 미구현 비교표

| 요구사항 | 현재 상태 | 비고 |
|---|---|---|
| 아이디/비밀번호/이메일 가입 | **미구현** | 지금은 `name`, `role`만 받는 익명 가입(`family_group/service.signup`) |
| 이메일 인증 | 미구현 | — |
| 아이디/이메일 중복 검사 | 미구현 | `users`에 `login_id`/`email` 컬럼 자체가 없음 |
| 비밀번호 해시 저장 | 미구현 | `users.token`만 있고 비밀번호 개념이 없음 |
| 로그인/로그아웃 | 부분 구현 | "로그인"은 사실 가입과 동일한 토큰 발급. 로그아웃 엔드포인트 없음(모바일에서 토큰을 지우면 끝) |
| Access/Refresh 토큰, 세션 관리 | **미구현** | 지금은 만료 없는 고정 토큰 1개뿐(`secrets.token_urlsafe(24)`), 모바일은 메모리에만 보관(재시작 시 소실, `shared/api/client.js`) |
| 비밀번호 재설정 | 미구현(비밀번호 자체가 없음) | — |
| Google/Kakao 소셜 로그인 | **미구현** | 원본 프로젝트는 Firebase를 썼음(`docs/legacy/original-reference.md`) |
| 계정 연동(동일 사용자에 여러 로그인 수단) | 미구현 | — |
| 이메일 후보 자동 병합 금지 | N/A(설계 원칙, 구현 대상 아님) | 설계에 반영 |
| 가족 생성/초대코드 발급/참여 | **구현됨** | `family_group/service.create_group`, `join_group` |
| 초대코드 만료 | 미구현 | `invites`에 `expires_at` 없음 |
| 초대코드 재발급/폐기 | 부분 구현 | `revoked` 컬럼은 있으나 재발급·폐기 엔드포인트 없음 |
| 초대코드 사용 횟수 관리 | 미구현 | `invites`에 사용 횟수 컬럼 없음(코드 하나가 무제한 재사용 가능) |
| 초대코드 추측 방지(레이트리밋) | **미구현** | 결정됨: FastAPI 필수 구현(IP·계정별 실패 횟수 제한), Cloudflare는 보조 — 6번 참고 |
| 초대 승인(관리자 승인 후 멤버십 등록) | **미구현, 신규 요구사항** | 지금은 코드만 맞으면 즉시 `GroupMember` 생성. 결정됨: 승인 전 접근 전면 차단 — 6번 참고 |
| 기존 무만료·무제한 초대코드의 폐기 | **신규 요구사항** | 새 24시간·1회 정책이 생기면 과거 코드가 상대적으로 "영구 무제한"이 되어 위험 — 결정됨: PR 4-D 배포 시 폐기+신규 코드 자동 발급을 동시 수행(4-A는 손대지 않음) — 6번 참고 |
| 동일 그룹 중복 참여 방지 | **구현됨**(DB 레벨) | `group_members` 복합 PK로 중복 삽입 자체가 불가능, `repository.join()`은 이미 멤버면 조용히 통과(에러 아님) |
| PR 3 가족 멤버십 권한 재사용 | 설계 전제 | 새 엔드포인트도 전부 `current_group_id`/`ensure_group_member`를 그대로 쓴다 |
| 가족 관계(엄마/아빠/…) | 미구현 | `users.role`은 parent/child/other 뿐이고 "관계"가 아니라 가입 시 1회 선택값 |
| 관계·시스템 권한 분리 | 미구현 | 지금은 `groups.owner_id` 하나로만 "관리자"가 구분되고, 그 외엔 전부 동급 member |
| 그룹 내 표시 이름 | 미구현 | `users.name` 하나만 있고 그룹별로 다르게 쓸 수 없음 |
| 개인별 별명(내가 남에게 붙이는) | **미구현** | 관련 테이블 없음 |
| 개인 메모(작성자만 조회) | **미구현** | 관련 테이블 없음 |

## 2. 요구사항별 소유 도메인과 담당 파일

모두 **family_group** 기능 소유(README 브랜치 표의 `ai_assistant-knowledge` 등과 달리, 로그인·가족은 CLAUDE.md가 "모든 기능이 의존한다"고 못박은 영역이라 별도 담당자 배정이 필요 — 팀 결정 항목 10-c 참고).

| 영역 | 파일(예정) |
|---|---|
| 인증(토큰/세션/비밀번호) | `apps/api/app/shared/auth.py`(신원 확인 핵심), `apps/api/app/features/family_group/{router,service,repository,models,schemas}.py` |
| 소셜 로그인 | `apps/api/app/features/family_group/social.py`(신설, provider별 콜백 처리), `app/shared/config.py`(provider client id/secret) |
| 가족 관계·표시이름·별명·관리자 지정(4-E) | `apps/api/app/features/family_group/{models,service,schemas}.py` 확장 |
| 권한 | `apps/api/app/shared/auth.py`(PR 3에서 만든 `ensure_group_member`, `current_group_id` 그대로 재사용 — 변경 없음, 단 Bearer 토큰 분기 추가는 함) |
| 전환기 기능 플래그 | `apps/api/app/shared/config.py`(신규 `allow_anonymous_signup`, `allow_legacy_token_auth` — 결정됨, 10번 참고) |
| 초대코드 보안·승인(4-D) | `apps/api/app/features/family_group/{router,service,repository,models,schemas}.py`(코드 길이·만료·1회성·승인 플로우), 신규 레이트리밋 로직 |
| 모바일 로그인/온보딩 UI(4-F) | `apps/mobile/src/features/family-group/`(신설 `screens/`), `apps/mobile/src/features/start/screens/StartScreen.js`(로그인 분기 추가) |
| 모바일 토큰 저장 | `apps/mobile/src/shared/api/client.js`(지금은 메모리만 — 영속 저장소 필요) |
| 문서 | `docs/contracts/permissions.md`(역할 분리 반영), `docs/contracts/db.md`, `docs/contracts/openapi.json`(자동 생성, 서버 변경 후 갱신) |

## 3. ERD 및 변경안 (기존 DB를 최대한 활용)

### 바꾸지 않는 것

`users.id`, `groups.id`, `group_members`(그룹+사용자 복합 PK), `invites.code`(기존 PK) — **PK와 기존 행은 그대로 둔다.** 전부 "컬럼 추가"로 해결되고, 기존 Alembic 리비전(`355a1a748ec5`)을 수정하지 않고 새 리비전을 쌓는다(CLAUDE.md 규칙 그대로). `invites.code`의 PK 지위도 바꾸지 않는다 — 대신 `invites.id`라는 **새 서로게이트 식별자**를 추가 컬럼으로 얹는다(아래 참고, 보완 1번). `users.token`(구 토큰) 컬럼도 지금 단계에서는 삭제하지 않는다 — 결정됨: 전환이 끝난 뒤 **별도의 후속 Alembic 마이그레이션**(이 문서의 4-A~4-F 범위 밖)에서 제거한다.

### 컬럼 추가안

```
users
  + login_id       varchar(32)  unique, nullable  (일반 가입자만 값이 있음)
  + email          varchar(255) unique, nullable
  + email_verified_at  timestamptz, nullable
  + password_hash  varchar(255) nullable           (소셜 전용 계정은 null)
  (기존 token 컬럼은 과도기 동안 유지 — 10번 호환성 참고)

groups
  (변경 없음 — owner_id 는 "최초 생성자" 기록용으로 유지, 실제 권한 판단은 group_members.role 로 옮김)

group_members
  + role              varchar(16)  default 'member'   (owner | admin | member)
  + family_relation   varchar(16)  nullable            (mom|dad|son|daughter|grandma|grandpa|other)
  + family_relation_detail varchar(40) nullable        (관계=other 일 때 직접 입력)
  + display_name      varchar(40)  nullable            (없으면 users.name 사용)

invites
  + id            varchar(32)  UNIQUE, not null (신규, 서로게이트 식별자 — 보완 1번, PK는 여전히 code)
  + expires_at   timestamptz nullable   (결정됨: 신규 발급 기본값 24시간 뒤. 컬럼 자체는 nullable로 둬서 과거 행은 무만료로 해석)
  + max_uses     integer     nullable   (결정됨: 신규 발급 기본값 1. null = 무제한, 과거 행은 무제한으로 해석)
  + use_count    integer     default 0
```

코드 생성 로직도 함께 바뀐다(스키마 변경 아님, `family_group/service.py`의 `_CODE_CHARS` 생성 길이만): 결정됨 — 암호학적으로 안전한 난수(기존 `secrets.choice` 유지) **10~12자**로 늘린다(지금은 8자).

**보완 1 — `invites.id` 신설 이유**: 애초 설계에서 `join_requests.invite_code`에 코드 원문을 그대로 복사해 두려 했는데, 이는 "초대코드 원문을 로그에 남기지 않는다"는 원칙과 같은 맥락에서 DB에도 비밀값을 불필요하게 중복 저장하는 셈이라 바람직하지 않다. `invites`에 다른 테이블의 평범한 PK들과 같은 형태(varchar(32) 생성 id)로 `id`를 추가하고, `join_requests`/`invite_attempts`는 이 `id`를 참조하도록 바꿨다(아래 "새 테이블" 참고). `code` 자체의 PK 지위는 바꾸지 않으므로(코드 제출 시 조회는 여전히 `code`로 한다) 기존 조회 경로·인덱스에 영향이 없다.

### 새 테이블

```
social_accounts                              refresh_tokens
  id            varchar(32) PK                  id            varchar(32) PK
  user_id       FK -> users.id                  user_id       FK -> users.id
  provider      varchar(16)   'google'|'kakao'   token_hash    varchar(128)
  provider_uid  varchar(128)                     issued_at     timestamptz
  email_at_link varchar(255) nullable            expires_at    timestamptz
  linked_at     timestamptz                      revoked_at    timestamptz nullable
  UNIQUE(provider, provider_uid)                 device_label  varchar(60) nullable

password_resets                               email_verifications
  id          varchar(32) PK                     id          varchar(32) PK
  user_id     FK -> users.id                     user_id     FK -> users.id
  token_hash  varchar(128)                       email       varchar(255)
  expires_at  timestamptz                        token_hash  varchar(128)
  used_at     timestamptz nullable                expires_at  timestamptz
                                                   verified_at timestamptz nullable

member_nicknames
  group_id     FK -> groups.id  \ 복합 PK
  owner_user_id FK -> users.id  / (내가 쓴 것만 — 소유자별로 1행)
  target_user_id FK -> users.id --- PK
  nickname     varchar(40) nullable
  memo         text nullable        (작성자 본인만 조회 — 서비스 계층에서 owner_user_id == 요청자일 때만 반환)
  updated_at   timestamptz

join_requests                                 invite_attempts
  id          varchar(32) PK                    id          varchar(32) PK
  group_id    FK -> groups.id                    ip          varchar(64)            (IP, 필요하면 후속으로 해시화)
  user_id     FK -> users.id                      user_id     FK -> users.id nullable (인증된 상태로 시도했다면)
  invite_id   FK -> invites.id                     invite_id   FK -> invites.id nullable (매칭된 코드가 있을 때만)
  status      varchar(16) default 'pending'       success     boolean
               (pending|approved|rejected)         created_at  timestamptz
  requested_at timestamptz
  decided_at   timestamptz nullable
  decided_by   FK -> users.id nullable

  UNIQUE(group_id, user_id) WHERE status='pending'   -- 부분 유니크 인덱스, 동시요청 방지(보완 설명 아래)
  INDEX(invite_id)
                                                     INDEX(ip, created_at)
                                                     INDEX(user_id, created_at)
```

`join_requests`가 신설된 이유(6번에서 자세히): **결정됨** — 초대코드 검증만으로는 멤버십을 바로 주지 않고, 가족 관리자(owner/admin) 승인을 거쳐야 한다. 승인 전에는 `group_members` 행 자체를 만들지 않으므로, PR 3의 `ensure_group_member`(코드 변경 없음)가 자동으로 접근을 막아준다. `invite_attempts`는 IP·계정별 실패 횟수 제한(레이트리밋)에 쓴다 — **원문/해시 코드 값을 아예 저장하지 않고** `invite_id`(매칭 성공 시만 채움, 실패 시 null)만 남긴다 — 보완 1번과 같은 이유로 코드 원문이 DB 어디에도 복제되지 않는다.

### 보완 2 — Unique·인덱스·동시 요청 처리

요구사항의 "변경에 따른 FK·Unique·인덱스·동시 요청 처리 방안"에 대한 구체 설계:

- **`invites.use_count` 증가는 조건부 원자적 UPDATE로 한다.** `SELECT`로 먼저 확인하고 나중에 `UPDATE`하면(check-then-act) 두 요청이 동시에 들어왔을 때 1회용 코드 하나로 두 명이 들어올 수 있다. 대신 `UPDATE invites SET use_count = use_count + 1 WHERE code = :code AND NOT revoked AND (expires_at IS NULL OR expires_at > now()) AND (max_uses IS NULL OR use_count < max_uses) RETURNING id` 형태의 **단일 조건부 UPDATE**를 쓴다 — 0행이면 그 사이 누가 먼저 썼거나 만료/폐기된 것이므로 `invalid_invite`로 처리한다.
- **중복 pending 요청은 부분 유니크 인덱스(`UNIQUE(group_id, user_id) WHERE status='pending'`)로 DB 레벨에서 막는다.** 애플리케이션에서 "이미 pending 있나 먼저 조회" 후 insert하면 역시 동시 요청에 취약하다 — 대신 바로 insert를 시도하고, 유니크 제약 위반(`IntegrityError`)이 나면 기존 pending 행을 다시 조회해 그걸 반환한다(6번 "중복 pending 재사용" 정책의 구현 방법).
- **`social_accounts`의 `UNIQUE(provider, provider_uid)`**(기존 설계)도 같은 이유로 유지 — 두 사용자가 동시에 같은 소셜 계정으로 가입을 시도해도 하나만 성공하고 나머지는 제약 위반으로 막힌다.
- **새 FK 컬럼(`invites.id`를 참조하는 `join_requests.invite_id`, `invite_attempts.invite_id` 등)에는 전부 인덱스를 둔다** — Postgres는 FK 컬럼에 자동으로 인덱스를 만들어주지 않으므로 명시적으로 추가해야 조회·JOIN 성능이 나온다.
- **마지막 로그인 수단 삭제 — 결정됨, 강화(2026-10-22)**: DB 제약(`CHECK`)으로 강제하기 애매한 다중 테이블 조건(`social_accounts` 행 수 + `users.password_hash` 존재 여부)이라 애플리케이션 레벨에서 확인하되, **사용자 단위 잠금으로 동시 요청을 직렬화**한다 — 연동 해제 트랜잭션 시작 시 `SELECT * FROM users WHERE id = :user_id FOR UPDATE`로 그 사용자의 행을 잠그고(동일 사용자의 동시 요청은 이 시점에 하나씩 순서대로 처리됨), 잠근 상태에서 "연동된 `social_accounts` 수 + (`password_hash` 있으면 1)"을 세어 1 이하면 거부한다. 비밀번호가 없는 소셜 전용 계정이 마지막 하나 남은 소셜 연동을 끊으려는 경우도 같은 체크로 자동 거부된다(비밀번호 수단이 0이므로 `social_accounts` 수가 바로 전체 로그인 수단 수). 두 요청이 동시에 와도 `FOR UPDATE`가 직렬화하므로 "둘 다 통과해서 0개가 되는" 레이스는 발생하지 않는다 — advisory lock 같은 별도 메커니즘 없이 행 잠금만으로 충분하다고 판단.

### ERD 요약 (텍스트)

```
users 1───* group_members *───1 groups
users 1───* social_accounts
users 1───* refresh_tokens
users 1───* password_resets / email_verifications
groups 1───* invites
groups 1,users 1(owner) ─ member_nicknames ─ 1 users(target)   # 그룹 내에서만 의미있는 3자 관계
groups 1───* join_requests *───1 users
invites 1───* join_requests   (invite_id FK, 원문 코드 비저장)
invites 1───* invite_attempts (invite_id FK nullable, 원문 코드 비저장)
```

`group_members`가 이미 복합 PK(그룹+사용자)라서 **한 사용자가 여러 그룹에 속하는 것을 스키마가 이미 허용**하고 있다 — "그룹 전환" 기능은 `users.active_group_id`를 바꾸는 것만으로 동작하고 테이블 변경이 필요 없다(PR 3가 이미 `group_members` 기준으로 실제 멤버십을 검증하므로 안전).

## 4. SQLAlchemy 모델 · Alembic Revision 추가 계획

전부 **추가적 변경**(컬럼 추가 nullable, 새 테이블)이라 기존 행에 영향이 없다. 계획(실행하지 않음):

1. `355a1a748ec5`(현재 head) → 새 리비전: `users`에 `login_id/email/email_verified_at/password_hash` 추가, 유니크 인덱스 2개.
2. → 새 리비전: `group_members`에 `role/family_relation/family_relation_detail/display_name` 추가, 기존 행 백필(`groups.owner_id`와 같은 `user_id`를 가진 행은 `role='owner'`, 나머지는 `'member'`) — **데이터가 있는 컬럼 추가라 백필 로직이 필요한 유일한 단계**, PR 4-A에서 가장 신경 써야 할 부분.
3. → 새 리비전: `invites`에 `id`(서로게이트, 유니크)/`expires_at`/`max_uses`/`use_count` 추가. 기존 행에 `id`만 채워 넣는다(생성 id 백필). **결정됨(변경, 2026-10-22)**: 이 리비전에서는 **기존 초대코드를 폐기하지 않는다** — `expires_at`/`max_uses`는 기존 행에서 전부 null로 남고, 서비스 코드는 지금과 똑같이 "무만료·무제한"으로 해석한다. PR 4-A는 순수 스키마 확장(+역할 백필)만 하고, 초대코드의 실제 동작(승인 요구, 레이트리밋, 만료)은 전혀 바뀌지 않는다 — 레거시 코드 폐기는 **PR 4-D로 이동**(아래 "보완" 및 6번 참고).
4. → 새 리비전: `social_accounts`, `refresh_tokens`, `password_resets`, `email_verifications`, `member_nicknames`, `join_requests`(`invite_id` FK), `invite_attempts`(`invite_id` FK nullable) 신규 테이블 생성 + 보완 2의 인덱스·부분 유니크 제약.

리비전을 기능별로 쪼갤지 한 PR(4-A)에 한 번에 담을지는 미정(9번 참고). `users.token` 컬럼 삭제는 **이 계획에 포함하지 않는다**(전환 완료 후 별도 후속 마이그레이션 — 결정됨).

**4-A 구현 완료(2026-10-22, 리비전 `b6931fc30c66`)**: 위 계획대로 `apps/api/app/features/family_group/models.py`에 4개 기존 테이블 컬럼 추가 + 7개 신규 테이블을 구현했다. 구현 중 발견·반영한 사항:

- **버그 발견 — 그룹 생성자가 member로 저장될 뻔함**: `repository.add_group()`이 `GroupMember(group_id=.., user_id=owner.id)`를 만들 때 `role`을 넘기지 않아서, `role`의 ORM 기본값(`default="member"`)이 그대로 적용되면 **그룹을 만든 사람(owner)이 `role='member'`로 저장되는 버그**가 생겼을 것이다. `add_group()`에 `role="owner"`를 명시하는 1줄로 고쳤다(새 API 추가 아님, 기존 동작을 의도대로 맞추는 호환성 수정). `test_family_group.py`에 `test_create_group_assigns_invite_id_and_owner_role` 회귀 테스트를 추가해 "그룹 생성자의 `group_members.role`이 `'owner'`인지"를 확인한다.
- **`invites.id` ORM 기본값**: `Invite.id`에 `default=_uid`(기존 `service.py`의 `_uid()`와 동일한 `uuid.uuid4().hex[:12]`)를 지정해, `repository.add_group()`이 `id`를 넘기지 않는 기존 호출부 그대로도 INSERT가 성공한다. 신규 테이블 7개의 PK `id`도 전부 같은 `default=_uid`로 통일했다(혼용 없음).
- **`group_members.role`/`invites.id` 백필 순서**: 자동 생성된 Alembic 리비전을 그대로 쓰지 않고 직접 재작성했다 — `invites.id`를 참조하는 `join_requests`/`invite_attempts`는 `invites.id`가 백필·검증·`NOT NULL`+`UNIQUE` 제약까지 전부 끝난 뒤에 만들도록 순서를 바꿨고(자동 생성은 이 순서를 몰라 FK 생성이 실패했을 것), `group_members.role`도 nullable 추가 → 백필(전부 `'member'` 후 `groups.owner_id`와 일치하는 행만 `'owner'`) → `NOT NULL` 순서로 직접 작성했다. 마이그레이션 시작 시 모든 `groups.owner_id`가 실제 `group_members` 행을 갖는지 사전 검증하고, 하나라도 없으면 임의로 복구하지 않고 해당 그룹 id 목록과 함께 예외를 던져 마이그레이션을 중단한다.
- **검증**: 빈 테스트 DB(스키마 일치·idempotent), 대표 데이터(그룹 2·사용자 3)를 PR 4-A 이전 스키마 모양으로 넣고 업그레이드한 뒤 role 백필·`invites.id` 고유성·기존 9개 테이블 행 수 보존을 확인, 제약 위반 5건(owner 중복/pending 중복/소셜계정 중복/비멤버 별명 대상 거부·실제 멤버 허용)을 Postgres에서 직접 확인, owner-멤버십 없는 그룹이 있는 경우 마이그레이션이 트랜잭션 전체를 롤백하며 중단되는지도 확인했다 — 전부 격리된 테스트 DB에서만 수행, 실제 `gabee` DB는 변경하지 않았다(해당 시점 기준 `users`/`groups`/`group_members`/`invites` 전부 0행이라 owner-멤버십 무결성 문제 자체가 없었다).

**보완 — 레거시 초대코드 폐기 시점(결정됨, 변경, 2026-10-22)**: 폐기는 **4-A가 아니라 4-D에서** 한다. 4-D 배포(새 승인·보안 로직이 이미 코드에 있는 시점)의 **같은 트랜잭션/같은 배포 단계**에서, 그 시점까지 "무만료·무제한"으로 남아있는 모든 활성 코드를 ① `revoked=true` 처리하고 **즉시 같은 단계에서** 그룹마다 새 정책(24시간·1회)의 대체 코드를 자동 발급한다 — 폐기와 재발급을 분리하지 않고 한 번에 묶어서, "활성 코드가 하나도 없는 공백 시간"이 생기지 않게 한다(요구사항의 "서비스 중단 없이"). 새 코드는 기존 `GroupOut`/`group_out()`이 이미 "그 그룹의 비폐기 초대"를 조회해 보여주는 구조라, owner/admin이 다음에 가족 그룹 화면을 열면 자동으로 새 코드가 보인다 — 별도 알림 설계가 필요 없다.
**레거시 코드가 신규 보안 정책을 우회하지 않는 이유**: 4-D의 `POST /groups/join`은 **어떤 초대코드로 들어오든**(레거시든 신규든) 반드시 `join_requests`에 pending 행을 만들고 owner/admin 승인을 거치게 돼 있다(승인 절차는 코드 자체의 `expires_at`/`max_uses`와 무관하게 전부 적용). 레거시 코드가 실제로 우회할 수 있는 것은 "무만료·무제한"이라는 코드 고유 제약뿐이고, 그마저도 4-D 배포 순간 위 자동 교체로 즉시 없어진다 — 그 사이(4-A~4-C 기간)에는 애초에 승인 플로우 자체가 아직 배포 안 됐으므로 "신규 보안 정책 우회"라는 개념 자체가 성립하지 않는다(우회할 신규 정책이 아직 없음).

## 5. 로그인·계정 연동 시퀀스

**일반 로그인**
```
클라이언트 → POST /family-group/auth/login {login_id, password}
서버: login_id 조회 → password_hash 검증 → Access(짧은 TTL) + Refresh(긴 TTL, DB에 해시 저장) 발급
클라이언트: Refresh 는 보안 저장소에, Access 는 메모리에 보관
이후 요청: Authorization: Bearer <access> (기존 X-Gyeot-Token 과 과도기 동안 공존 — 10번 참고)
Access 만료 시: POST /family-group/auth/refresh {refresh_token} → 새 Access(+선택적으로 새 Refresh, 회전)
```

**소셜 로그인(최초) — 결정됨: 제공자별 구현 방식**

- **Google**: 검증된 네이티브 SDK 또는 **시스템 브라우저 기반 OAuth/OIDC + PKCE**(`expo-auth-session` 계열). 결과로 ID 토큰(JWT)을 받는다 — 서버는 Google의 공개키로 서명을 검증해 `provider_uid`(`sub` 클레임)·이메일을 뽑는다.
- **Kakao**: Expo와 호환되는 **RN 네이티브 SDK를 우선 검토**하고, 안 되면 시스템 브라우저 기반 OAuth. 결과로 받은 액세스 토큰을 서버가 Kakao 사용자 정보 API로 다시 검증해 `provider_uid`를 뽑는다(Google처럼 자체 서명 검증이 안 되므로 반드시 Kakao API 호출 필요).
- **임베디드 WebView 인증은 쓰지 않는다**(어느 제공자든). 네이티브 SDK/시스템 브라우저만 허용.
- 비밀키(Google/Kakao 앱 시크릿)는 **서버에서만** 관리한다(`app/shared/config.py`), 모바일 번들에 넣지 않는다.
- 네이티브 SDK를 쓰는 순간 플레인 Expo Go로는 테스트할 수 없다 — **Expo Development Build**(`expo-dev-client`) 준비가 전제(10번 참고).

```
모바일 → (Google: 시스템 브라우저 OAuth+PKCE 또는 네이티브 SDK / Kakao: 네이티브 SDK 우선, 아니면 시스템 브라우저 OAuth)
      → provider 토큰(ID 토큰 또는 액세스 토큰) 획득 — 임베디드 WebView 사용 안 함
→ POST /family-group/auth/social/{provider} {provider_token}
서버: provider_token 검증(Google=JWT 서명 검증, Kakao=Kakao API 호출) → provider_uid 추출
  → social_accounts 에 (provider, provider_uid) 있음? 있으면 그 user 로 즉시 로그인(Access/Refresh 발급)
  → 없으면: provider 가 준 이메일로 users.email 조회
      → 기존 계정 있음 → "이 이메일로 가입된 계정이 있어요. 로그인 후 연동할까요?" 를 의미하는 후보 응답(자동 로그인/자동 병합 하지 않음)
      → 기존 계정 없음 → 바로 신규 가입(소셜 전용 계정, password_hash=null) 후 로그인
```

**명시적 계정 연동(이미 로그인된 상태에서)**
```
클라이언트(기존 계정으로 이미 로그인) → POST /family-group/auth/social/{provider}/link {provider_token}
서버: 현재 인증된 user 에 social_accounts 행 추가(재인증 확인 후 — 예: 최근 로그인 or 비밀번호 재확인)
```

이메일이 같다는 이유만으로 서버가 자동으로 계정을 합치는 경로는 **설계에 포함하지 않는다**(요구사항 그대로 금지).

### 이메일 인증 상태별 허용 범위와 온보딩 흐름 — 결정됨(보완 4)

일반 회원가입(아이디/비밀번호/이메일) 계정에만 해당한다. 소셜 로그인 계정은 provider가 이미 이메일을 검증했다고 보고 가입 즉시 `email_verified_at`을 채워 아래 제약 대상이 아니다. 개발 전용 익명 가입(`POST /family-group/users`) 계정은 애초에 이메일이 없어 "미인증"이 아니라 "해당 없음"이다.

**이메일 미인증 상태에서 허용**: 로그인, 로그아웃, 내 정보 조회/수정(`GET /family-group/me`), 비밀번호 변경, 인증 메일 재전송 요청.
**이메일 미인증 상태에서 차단**: 가족 그룹 생성(`POST /family-group/groups`), 초대코드로 참여 신청(`POST /family-group/groups/join`) — 가족 데이터와 관련된 모든 행동. 구현은 `current_user()`/`current_group_id()`를 바꾸지 않고, `create_group`/`join_group` 서비스 진입부에 `if not user.email_verified_at: raise ApiError(403, "email_not_verified", ...)` 가드만 추가한다(다른 인증 방식 계정은 이 필드가 이미 채워져 있어 자연히 통과).

**온보딩 흐름**:
```
일반 가입(login_id/password/email/name) → 인증 메일 발송
  → (미인증) 로그인은 되지만 "새 가족 만들기 / 초대코드로 참여"는 비활성화 + 안내 문구
  → POST .../email/verify/confirm {token} 으로 인증 완료 → email_verified_at 채워짐
  → "새 가족 만들기 / 초대코드로 참여" 선택 화면 활성화
       새 가족 만들기 → POST /groups (기존과 동일, 즉시 owner)
       초대코드 참여  → POST /groups/join (아래 승인 대기 흐름으로 들어감)

소셜 로그인 가입 → 이메일 인증 단계 없이 바로 "새 가족 만들기 / 초대코드로 참여" 화면
```

**초대코드 참여 — 결정됨: 관리자 승인 필수**
```
클라이언트 → POST /family-group/groups/join {code}
서버: 사용자가 이미 이 그룹의 멤버다 → already_member 에러(결정됨 — 조용히 통과하지 않는다. 6번 참고)
  → invite_attempts 로 요청자(IP·user_id)의 최근 15분 실패 횟수 확인 → 5회 이상이면 즉시 거부(레이트리밋, 6번)
  → 이 그룹에 이미 내 pending 요청이 있다 → 새로 만들지 않고 그 요청을 그대로 응답(6번 "중복 pending 재사용")
  → invites.use_count 를 조건부 원자적 UPDATE 로 증가 시도(보완 2) → 0행이면 invite_attempts 에 실패 기록 후 invalid_invite
  → 성공 시: invite_attempts 에 성공 기록(invite_id 포함), join_requests 에 invite_id 로 status='pending' 행 생성
    — 이 시점엔 group_members 행을 만들지 않는다
  → 응답: {status: "pending", group_name, requested_at} (기존 GroupOut 과 다른 형태 — 하위 호환 깨짐, PR 설명에 명시 필요)

가족 관리자(owner/admin, PR 4-D 의 group_members.role 사용) → GET /family-group/groups/me/join-requests
  → POST /family-group/groups/join-requests/{id}/approve  → 이때 비로소 group_members 행 생성 + active_group_id 설정
  → 또는 .../reject → join_requests.status='rejected' (결정됨 — invites.use_count 는 환불하지 않는다. 6번)

승인 전 상태에서 family_chat/schedule/billing/care/ai_assistant 호출 시: group_members 행이 없으므로
그 그룹을 active_group_id 로 가리킬 방법 자체가 없다 — active_group_id 를 안 바꿨다면 no_group(다른 그룹이
전혀 없는 경우) 또는 기존 다른 그룹 데이터만 보이고, 새로 신청한 그룹의 group_members 행을 직접 조작해
active_group_id 를 억지로 그 그룹으로 바꾸더라도 ensure_group_member() 가 403 not_member 로 막는다 —
PR 3 코드를 한 줄도 안 바꿔도 "승인 전에는 가족 채팅·문서·사진 등에 접근할 수 없다"는 요구사항이 만족된다.
```

## 6. 초대코드 정책 — 결정됨

- **코드 형식**: 암호학적으로 안전한 난수(`secrets.choice`, 기존 알파벳 유지), **10~12자**(기존 8자에서 연장).
- **원문 비저장**: 코드 원문은 로그는 물론, `join_requests`/`invite_attempts` 등 어떤 보조 테이블에도 복제해 저장하지 않는다 — 전부 `invites.id`(서로게이트) 참조로 연결한다(보완 1). 꼭 로그를 남겨야 하면 코드 마지막 일부(예: 뒤 4자)만 남긴다.
- **기본 정책**: 신규 발급 코드는 **24시간 만료, 기본 1회 사용**(`invites.expires_at`/`max_uses`에 값 세팅).
- **발급**: 그룹 생성 시 1개 자동 발급(지금과 동일, 위 기본 정책 적용).
- **재발급**: 기존 코드를 `revoked=true` 처리하고 새 코드를 발급(기존 코드 값 자체를 바꾸지 않음 — 감사 추적).
- **폐기**: `revoked=true`만 세팅(삭제하지 않음).
- **기존(레거시) 무만료·무제한 코드의 안전한 폐기 — 결정됨, 변경(2026-10-22)**: **PR 4-A에서는 폐기하지 않는다.** PR 4-A는 컬럼 추가와 역할 백필만 하는 순수 스키마 확장이고, 초대코드의 실제 동작·유효성은 전혀 안 바뀐다. 폐기·교체는 **PR 4-D 배포 시점**에, 레거시 코드 일괄 `revoked=true` 처리와 그룹별 신규 정책(24시간·1회) 코드 자동 발급을 **같은 단계에서 함께** 수행해 "활성 코드 없음" 공백이 생기지 않게 한다(4번 "보완" 참고 — 수동 재발급을 기다리지 않는다는 점이 이전 설계와의 차이).
- **사용 횟수**: 코드가 **검증을 통과해 `join_requests`가 생성되는 시점**에 `use_count`를 조건부 원자적 UPDATE로 증가시킨다(보완 2 — check-then-act 레이스 방지). `max_uses` 초과/만료/폐기 시 `invalid_invite`(기존 에러 코드 재사용). **결정됨**: 요청이 나중에 거절(`reject`)되어도 `use_count`는 **환불하지 않는다** — "시도 자체"가 소모다.
- **관리자 승인(신규 요구사항)**: 코드 검증은 멤버십을 바로 주지 않는다. `join_requests`에 `pending` 행만 생기고, owner/admin이 승인해야 비로소 `group_members` 행이 생긴다. 승인 전에는 어떤 가족 데이터에도 접근할 수 없다(5번 시퀀스 참고) — PR 3의 권한 검증 코드는 손대지 않는다.
- **추측·무차별 방지(레이트리밋) — 결정됨**: FastAPI가 필수로 구현하고 Cloudflare는 보조 수단으로만 쓴다. `invite_attempts`에 IP·계정(인증된 경우)별 실패를 기록하고, **최근 15분 이내 실패 5회 이상이면 추가 시도를 차단한다**(슬라이딩 윈도우 — 가장 오래된 실패가 15분을 넘어가면 자동으로 다시 시도 가능해진다. 별도 고정 잠금 시간을 두지 않는다).
- **중복 참여(이미 멤버) 방지**: **결정됨 — 명확한 에러로 알린다**(`already_member`), 지금처럼 조용히 통과시키지 않는다. 이를 위해 `family_group/repository.py`의 `join()`(현재는 `is_member`면 조용히 넘어감)을 4-D에서 수정해야 한다(5번 시퀀스 참고).
- **중복 pending 요청**: **결정됨 — 재사용한다.** 같은 그룹에 이미 내 `pending` 요청이 있으면 새로 만들지 않고 그 요청을 그대로 돌려준다(`use_count`도 다시 증가시키지 않는다). DB 레벨에서는 `UNIQUE(group_id, user_id) WHERE status='pending'` 부분 유니크 인덱스로 동시 요청 경합을 막는다(보완 2).

## 7. 가족 관계 · 표시 이름 · 개인별 별명 정책

- 관계값: `mom, dad, son, daughter, grandma, grandpa, other` + `other` 선택 시 `family_relation_detail`(자유 입력, 길이 제한 40자 제안).
- 관계는 **그룹 멤버십별**(`group_members.family_relation`)로 둔다 — 한 사용자가 여러 그룹에 속하면 그룹마다 다른 관계를 가질 수 있다(예: 내 가족에선 "딸", 배우자 가족에선 "며느리"=기타+직접입력).
- 시스템 권한(owner/admin/member)과 관계는 **완전히 독립**이다 — "할머니"가 owner일 수도, "아들"이 admin일 수도 있다. UI에서 둘을 같은 선택지로 섞지 않는다.
- **가족 관리자 정책 — 결정됨(보완 6, 2026-10-22 확정)**:
  - **Owner는 그룹당 정확히 1명**(`groups.owner_id` = `group_members.role='owner'`인 그 한 사람, 지금 구조 그대로).
  - **Admin은 인원 제한 없이 여러 명** 지정할 수 있다(`group_members.role='admin'`, 0명이어도 무방).
  - **Admin이 할 수 있는 것**: 초대코드 발급(`invites/reissue`·`revoke`)과 가입 요청 승인·거절(`join-requests/{id}/approve`·`reject`) — 전부 기존 엔드포인트 초안(8번)에 이미 "owner/admin만"으로 설계돼 있어 추가 변경 없음.
  - **Admin이 할 수 없는 것**: 다른 멤버를 admin으로 지정하거나 admin에서 해제하는 것 — 이건 **owner만** 가능(admin끼리는 서로 admin을 주거나 뺏을 수 없다).
  - **Owner 권한 이전(소유권 양도)은 이번 PR 4 범위에서 명시적으로 제외한다** — `groups.owner_id`는 "최초 생성자" 기록으로 계속 고정이고, `group_members.role='owner'`도 그 한 사람만 유지한다. 필요해지면 별도 기능(향후 설계)으로 다룬다.
- 표시 이름(`group_members.display_name`)이 없으면 `users.name`을 그대로 보여준다. 변경은 본인만(자기 멤버십 행만) 가능 — 다른 사람의 표시 이름을 내가 바꿀 수 없다(이건 아래 "개인별 별명"과 다른 것).
- 개인별 별명(`member_nicknames`): "내가 OO를 OO라고 부른다"는 나만 보는 라벨. `owner_user_id`(별명을 지은 사람) 기준으로만 조회·수정 가능 — 다른 사람에게는 영향이 전혀 없다(요구사항의 "개인별 별명 변경이 가족 전체 프로필에 영향을 주지 않도록" 그대로).
- 개인 메모(`member_nicknames.memo`)도 같은 행에 두고, 조회 API는 `owner_user_id == 요청자`일 때만 그 필드를 채워서 돌려준다(다른 사람이 쓴 메모는 애초에 안 보임 — 권한 체크가 아니라 쿼리 자체를 그렇게 짠다).

## 8. FastAPI 엔드포인트 초안 (요청/응답 필드, 구현 전 — 실제 값·검증 규칙은 PR 4-B/4-C/4-D/4-E에서 확정)

```
POST /family-group/auth/signup        {login_id, password, email, name}            -> {user, access_token, refresh_token}
POST /family-group/auth/login         {login_id, password}                          -> {user, access_token, refresh_token}
POST /family-group/auth/refresh       {refresh_token}                               -> {access_token, refresh_token}
POST /family-group/auth/logout        {refresh_token}                               -> 204 (해당 refresh_token 폐기)
POST /family-group/auth/email/verify/request   {}(인증된 사용자)                     -> 204 (이메일 발송)
POST /family-group/auth/email/verify/confirm   {token}                              -> 200
POST /family-group/auth/password/reset/request {email}                              -> 204 (항상 204 — 이메일 존재 여부 노출 금지)
POST /family-group/auth/password/reset/confirm {token, new_password}                -> 200

POST /family-group/auth/social/{provider}         {provider_token}                  -> {user, access_token, refresh_token} | {candidate_account: true, masked_email}
  # provider_token: Google=ID 토큰(JWT), Kakao=액세스 토큰. 서버가 provider별로 다르게 검증한다(5번 참고).
POST /family-group/auth/social/{provider}/link    {provider_token}(인증된 사용자)    -> 200
GET  /family-group/auth/social                    (인증된 사용자)                    -> [{provider, linked_at}]
DELETE /family-group/auth/social/{provider}       (인증된 사용자)                    -> 204 (연동 해제)
  # 결정됨(보완 6): 해제 후 로그인 수단이 0개가 되면 거부한다 — "(연동된 social_accounts 수) +
  # (password_hash 가 있으면 1)"이 1 이하로 떨어지면 403 last_login_method. users 행을 FOR UPDATE
  # 로 잠근 뒤 체크 → 동시 해제 요청도 안전(보완 2 참고).

PUT  /family-group/groups/me/profile   {display_name?, family_relation?, family_relation_detail?} -> GroupOut (내 멤버십만)
PUT  /family-group/groups/members/{user_id}/role  {role: "admin"|"member"}          -> GroupOut  (결정됨: owner만, 4-E)
POST /family-group/groups/invites/reissue  {}                                       -> {invite_code}  (owner/admin만, PR3 권한 재사용)
POST /family-group/groups/invites/revoke   {}                                       -> 204            (owner/admin만)

POST /family-group/groups/join             {code}                                   -> {status: "pending", group_name, requested_at}
  # 기존 엔드포인트, 동작이 바뀐다(즉시 GroupOut → pending 응답) — 하위 호환 깨짐, PR 설명에 반드시 기재.
GET  /family-group/groups/me/join-requests                                          -> [{id, user_id, user_name, requested_at}]  (owner/admin만)
POST /family-group/groups/join-requests/{id}/approve  {}                            -> GroupOut  (owner/admin만, 이때 group_members 생성)
POST /family-group/groups/join-requests/{id}/reject   {}                            -> 204       (owner/admin만)

PUT  /family-group/groups/me/nicknames/{target_user_id}  {nickname?, memo?}         -> 200
GET  /family-group/groups/me/nicknames                                              -> [{target_user_id, nickname, memo}]  (내가 쓴 것만)
```

기존 `POST /family-group/users`(익명 가입, 환경별 차단 — 10번 참고), `POST /family-group/groups`, `GET /family-group/groups/me`는 경로·응답 형태 그대로 둔다. `POST /family-group/groups/join`만 위에서 설명한 대로 동작이 바뀐다(승인 대기 응답으로 변경).

## 9. 단계별 PR 목록과 선행 의존성

**결정됨(보완 7)**: 원래 4-D 하나에 묶여 있던 "초대코드 보안·승인"과 "가족 관계·표시이름·별명"을 분리한다 — 전자는 보안에 가깝고 변경 폭이 크며(신규 테이블 2개, 레이트리밋, 승인 플로우), 후자는 순수 프로필 기능이라 서로 다른 리스크·리뷰 포인트를 가진다. 둘 다 `group_members.role`에 의존하는 건 같지만, 같은 PR일 필요는 없다. 전체가 6단계(4-A~4-F)가 된다.

```
PR 4-A  DB 스키마 확장           (새 컬럼 전부 nullable, 새 테이블 7개 — social_accounts/refresh_tokens/
                                   password_resets/email_verifications/member_nicknames/join_requests/
                                   invite_attempts — role 백필 + invites.id 추가. **레거시 초대코드는**
                                   **폐기하지 않음**(2026-10-22 변경, 4-D로 이동). 순수 스키마 확장만,
                                   Alembic 리비전만, 서비스 동작 변화 없음)
           ↓
PR 4-B  일반 회원가입·로그인·      (current_user() 가 Bearer 토큰도 받도록 확장, allow_anonymous_signup/
        비밀번호 재설정·이메일 인증   allow_legacy_token_auth 전환기 플래그 추가[기본값 false] — 10번,
                                   이메일 인증 상태별 허용 범위 가드 — 5번)
           ↓
PR 4-C  소셜 로그인(Google/Kakao) (4-B 의 Access/Refresh 발급 로직 재사용, PKCE/네이티브 SDK, 임베디드
                                   웹뷰 금지 — 5번 참고)
           ↓
PR 4-D  초대코드 보안·승인 플로우  (PR 3 의 ensure_group_member 그대로 재사용. 코드 길이·만료·1회성·
                                   레이트리밋[15분 5회]·승인/거절 엔드포인트·재가입 에러·중복 pending
                                   재사용 — 전부 group_members.role 로 owner/admin 판정, 6번. **배포 시**
                                   **레거시 초대코드 일괄 폐기 + 그룹별 신규 코드 자동 발급을 같은**
                                   **단계에서 수행**(2026-10-22 변경, 4번·6번))
           ↓
PR 4-E  가족 관계·표시이름·별명·   (표시이름/관계/별명/메모 엔드포인트 + owner 전용 관리자 지정·해제 +
        관리자 지정/해제            소셜 연동 해제 시 마지막 로그인 수단 보호 — 7번)
           ↓
PR 4-F  모바일 로그인/온보딩 UI    (4-B~4-E 전부 의존, expo-secure-store + 소셜 로그인용 Dev Build
                                   설정 등 신규 의존성 추가, docs/contracts/ui.md 토큰으로 화면 구성,
                                   승인 대기 화면·가입 요청 승인 화면 신규 — 10번)
```

4-A는 다른 모든 PR의 전제(스키마가 먼저 있어야 함). 4-B/4-C는 서로 독립적으로 병렬 진행 가능. 4-D/4-E는 둘 다 4-A의 `role` 백필에 의존하지만 서로는 독립적이라 병렬 가능(둘 다 `family_group` 파일을 건드리므로 동시 진행 시 머지 충돌 조율은 필요 — 10-c 참고). 4-F는 백엔드(4-B~4-E)가 어느 정도 끝나야 의미가 있다.

### 테스트 계획(각 PR 공통)

- PR 3 패턴 그대로: SQLite 전체 pytest + 새 기능 happy-path + 크로스-그룹/비인가 차단 테스트.
- 4-A: 새 Alembic 리비전을 빈 DB와(이미 모델이 있던) 기존 PR 3 테스트 DB 양쪽에 적용해보고 PR 2 때 썼던 `apps/api/scripts/check_schema_matches_models.py` 재사용. 기존 `invites` 행의 `expires_at`/`max_uses`가 여전히 null(= 무만료·무제한으로 계속 해석됨)인지, 기존 활성 코드가 리비전 적용 후에도 그대로 조회되는지 확인(폐기 로직이 없는 순수 스키마 확장임을 증명).
- 4-B: 비밀번호 틀림/만료된 refresh/재사용된 refresh(탈취 대응) 케이스, `allow_anonymous_signup=false`(기본값)일 때 익명 가입이 막히는지 + 환경변수로 true 설정 시 열리는지, `allow_legacy_token_auth`도 동일하게 양방향 확인, 이메일 미인증 상태에서 그룹 생성/참여가 막히고 `/me`는 되는지.
- 4-C: provider 토큰 검증 실패, 이메일 후보 응답이 자동 로그인으로 이어지지 않는지(명시적 연동 없이는 거부), 이미 다른 계정에 연동된 provider_uid 재사용 거부.
- 4-D: 레이트리밋(15분 5회) 초과 시 차단, 승인 전 5개 도메인 전부 403(PR 3 패턴과 동일하게 교차-그룹 테스트로 작성), owner/admin 아닌 멤버가 승인/거절 시도 시 거부, 거절 후 `use_count` 환불 안 됨, 중복 pending 제출 시 같은 요청 반환, 이미 멤버가 다시 join 시도 시 `already_member`, 동시 요청(두 스레드/요청으로 1회용 코드 동시 제출)에서 하나만 성공하는지. **배포 데이터 단계**: 레거시(무만료·무제한) 코드가 폐기와 동시에 신규 코드로 교체되는지, 교체 직후 그룹에 활성 코드가 항상 1개 이상 존재하는지(공백 없음), 이미 `expires_at`이 있던(레거시가 아닌) 코드는 안 건드리는지.
- 4-E: 본인 아닌 사람 표시이름 변경 거부, 다른 사람이 쓴 메모가 안 보이는지, admin이 다른 멤버를 admin으로 못 올리는지(owner만 가능), 마지막 로그인 수단 해제 시도 거부.

## 10. 기존 데이터·API·모바일 호환성 위험

- **(a) 익명 가입(`POST /family-group/users`) — 결정됨, 보완 3 반영.** 개발·테스트 호환 목적으로만 임시 유지한다. 운영(외부 접근 가능) 환경에서는 신규 익명 가입을 막는다 — 메커니즘: `app/shared/config.py`에 `allow_anonymous_signup: bool = False`(**기본값 false — 개발 환경도 예외 없음**, 로컬에서 쓰려면 `.env`에 `ALLOW_ANONYMOUS_SIGNUP=true`를 명시적으로 켜야 한다) 추가, `signup()` 서비스 시작에서 false면 `ApiError(403, "anonymous_signup_disabled", ...)`. 일반 회원가입·소셜 로그인이 완성되면 모바일 `StartScreen.js`의 "시작하기" 흐름을 정식 가입으로 전환한다. 기존 익명 사용자의 데이터 이전·계정 연결(예: 나중에 비밀번호/이메일을 추가해 "정식 계정화")을 검증한 뒤에 레거시 가입 API 자체를 제거한다 — 제거는 이 문서의 4-A~4-F 범위 밖(후속 PR).
- **(b) `users.token`(기존 고정 토큰) — 결정됨, 보완 3 반영.** 새 Access/Refresh 토큰 도입 후, 기존 `X-Gyeot-Token`은 **명시적으로 제한된 개발·전환 환경에서만** 한시적으로 허용한다 — 메커니즘: (a)와 같은 패턴으로 `allow_legacy_token_auth: bool = False`(**기본값 false**, 켜려면 `.env`에 `ALLOW_LEGACY_TOKEN_AUTH=true` 명시) 플래그를 두고, `current_user()`는 `Authorization: Bearer`를 우선 확인하고, 없을 때만(그리고 플래그가 true일 때만) `X-Gyeot-Token`을 본다. **주의**: 이 플래그가 기본 false라 4-B 배포 직후 기존 모바일 앱(아직 `Authorization: Bearer`를 안 보내는 버전)이 바로 끊길 수 있다 — 실제 사용자가 있는 환경에서는 4-B 배포 시점에 반드시 `.env`에서 이 플래그를 일시적으로 true로 켜두고, 모바일 전환이 끝난 뒤에 꺼야 한다(개발·테스트 환경은 기본 false 그대로 두어도 무방). 운영 환경에서 두 방식을 **무기한 병행하지 않는다** — 전환이 끝나면 플래그를 false로 돌려 레거시 인증을 중단한다. `users.token` 컬럼 자체의 삭제는 이후 별도 Alembic 마이그레이션(4-A~4-F 범위 밖)으로 한다.
- **(c) 담당자 배정** — 5명이 각자 다른 기능(ai_assistant, schedule, family_chat, billing-care)을 맡고 있는데, 이번 PR들은 전부 `family_group`/`shared/auth.py`를 건드린다. 동시에 여러 PR이 같은 파일(`auth.py`, `family_group/models.py`)을 고치면 충돌 위험이 크다 — 4-A(스키마)를 가장 먼저 **한 사람**이 끝내고 merge한 뒤 4-B/C/D/E를 나눠 맡는 순서를 권장한다(4-D·4-E는 같은 파일을 건드리므로 특히 순서나 조율이 필요).
- **(d) `docs/contracts/openapi.json`** — 지금은 자동 생성 스크립트(`scripts/export_openapi.py`)로 서버 코드에서 뽑는다. 이번 설계의 엔드포인트가 실제로 구현되면 그때마다 갱신해야 하고, 모바일의 `shared/api/client.js`도 `Authorization: Bearer` 헤더를 보내도록 바뀌어야 한다(지금은 `X-Gyeot-Token`만 하드코딩).
- **(e) 모바일 신규 의존성** — 토큰을 안전하게 저장하려면 `expo-secure-store`(현재 `package.json`에 없음)가 필요하고, 소셜 로그인에는 `expo-auth-session` 계열이 필요하다. CLAUDE.md 규칙상 "의존성 임의 추가 금지 — 필요하면 이유와 함께 먼저 제안"에 해당하므로 4-F PR에서 별도로 제안해야 한다.
- **(f) group_members 백필** — 4-A의 `role` 컬럼 백필이 유일하게 "로직"이 들어가는 마이그레이션이다. `groups.owner_id`와 `group_members.user_id`가 같은 행을 `role='owner'`로 세팅하는데, 지금 데이터 기준으로는 그룹마다 owner가 정확히 1명이라 안전하지만, 실행 전 실제 개발 DB에서 owner가 group_members에 없는 예외 케이스(이론상 없어야 하지만)가 있는지 먼저 조회해서 확인해야 한다.
- **(g) 기존 PR 3 테스트(`conftest.py`의 `family`/`other_family` fixture, `test_membership_enforcement.py`)** — `users`/`group_members`에 컬럼이 추가되는 것뿐이라 영향 없음(nullable 추가라 기존 fixture가 그대로 동작). 단, `signup()` 헬퍼가 이름/역할만 받는 지금 시그니처를 유지할지, 새 가입 방식에 맞춰 바꿀지는 4-B 구현 시 결정.
- **(h) Expo Development Build 필요 — 결정됨.** Google/Kakao 네이티브 SDK를 쓰는 순간 플레인 Expo Go로는 실행·테스트가 안 된다(네이티브 모듈이라 커스텀 네이티브 코드가 필요). `expo-dev-client` 기반 Dev Build를 준비해야 한다 — CLAUDE.md의 "SDK 는 Expo Go 가 지원하는 버전에 맞춘다" 규칙과 상충하지 않지만(이건 SDK 버전 얘기, Dev Build는 실행 방식 얘기), 팀 전체가 Expo Go만으로 개발하던 흐름에 Dev Build 빌드·배포 단계가 새로 생긴다는 점은 분명히 인지해야 한다(4-C/4-F 영향).
- **(i) 가입 흐름 자체가 바뀜 — 결정됨, 범위 확정(2026-10-22)**. "초대코드 입력 → 즉시 입장"이 "초대코드 입력 → 관리자 승인 대기 → 입장"으로 바뀐다. **모바일 신규 화면 2개를 4-F 범위에 포함한다**: ① 신청자용 "승인 대기 중" 상태 화면, ② 관리자용 "가입 요청 목록·승인/거절" 화면. 둘 다 `docs/contracts/ui.md`의 기존 디자인 토큰(색상·버튼·입력·카드·배지)과 Noto Sans KR을 그대로 쓴다 — 디자인 파일에 이 두 화면 자체의 목업은 없지만(화면이 UI Kit에 없다는 뜻이지 토큰이 없다는 뜻이 아님), 상세 비주얼 레이아웃은 4-F 구현 시점에 확정한다. **`docs/contracts/ui.md`에 남아있는 나머지 UI Kit 미반영 사항(부모님 모드 큰 버튼, Badge/Unrecorded 중립색, Input/Card radius·Shadow 토큰화)은 이번 인증 기능(PR 4-A~4-F)의 필수 구현 범위에서 제외한다** — 필요해지면 별개 UI 개선 작업으로 다룬다.

## 완료 조건 (이 설계 문서 자체의)

- 위 "미정" 항목 전부에 대해 팀이 결정을 내린다.
- 4-A ERD/백필 계획을 실제 개발 DB(가능하면 `docs/contracts/db.md` 갱신 포함)에 적용하기 전에 한 번 더 리뷰한다.
- 이 문서를 각 PR(4-A~4-F) 작업 시작 전에 다시 읽고, 구현하면서 바뀐 결정이 있으면 이 문서를 갱신한다(코드가 아니라 문서가 먼저 바뀌는 걸 기본으로 한다).

## 결정됨 (2026-10-22 팀 확정)

- **내비게이션**: 하단 탭은 지금 구조(AI 채팅/소통/일정/가계/돌봄) 유지, 디자인 파일의 탭 제안은 채택 안 함.
- **Noto Sans KR**: 도입 확정, `apps/mobile`에 이미 적용 완료(`docs/contracts/ui.md` 참고).
- **익명 가입**: 개발·테스트 전용으로 한시 유지, 운영에서는 플래그로 차단, 전환 완료 후 레거시 API 제거(10-a).
- **구 토큰(`X-Gyeot-Token`)**: 제한된 개발·전환 환경에서만 한시 허용(플래그), 운영에서 무기한 병행 안 함, `users.token` 컬럼은 후속 마이그레이션에서 제거(10-b).
- **초대코드**: 10~12자 암호학적 난수(6번), 기본 24시간 만료·1회 사용(6번), FastAPI 필수 레이트리밋 + Cloudflare 보조(6번), 원문 로깅 금지(6번).
- **초대 승인**: 코드 검증만으로 멤버십 부여 안 함 — 가족 관리자(owner/admin) 승인 후 멤버십 등록, 승인 전 전면 접근 차단(5·6·8번).
- **소셜 로그인**: Google=네이티브 SDK 또는 시스템 브라우저 OAuth/OIDC+PKCE, Kakao=네이티브 SDK 우선·불가 시 시스템 브라우저 OAuth, 임베디드 WebView 금지, Expo Development Build 전제, 비밀키는 서버 전용, 이메일 자동 병합 금지(5번).
- **(2026-10-22, 보완) 초대코드 원문 비저장**: `join_requests`/`invite_attempts`는 코드 원문을 저장하지 않고 `invites.id`(신규 서로게이트) 참조만 쓴다(보완 1).
- **(보완) 이메일 인증 상태별 허용 범위**: 미인증 상태에서도 로그인·내 정보·비밀번호 변경은 되지만, 가족 그룹 생성·참여는 이메일 인증 후에만 가능(5번). 소셜 로그인 계정은 이 제약 대상이 아님.
- **(보완) 레이트리밋·환불·중복요청·재가입 정책**: 15분 내 실패 5회로 제한(슬라이딩 윈도우), 거절 시 `use_count` 미환불, 중복 pending은 기존 요청 재사용, 이미 멤버인 재가입 시도는 `already_member` 에러(6번).
- **(보완) 관리자 권한**: admin 지정·해제는 owner만 가능(admin끼리는 불가), owner 자체의 이전은 범위 밖(7번). 소셜 연동 해제 시 로그인 수단이 0개가 되는 해제는 거부(8번).
- **(보완) PR 분리**: 4-D(초대코드 보안·승인)와 4-E(가족 관계·표시이름·별명·관리자 지정)로 분리, 모바일 UI는 4-F로 조정(9번).

## 2026-10-22 최종 확정 (설계 리뷰 2차 보완)

- **초대코드 폐기 시점 변경**: PR 4-A는 **레거시 초대코드를 폐기하지 않는다** — 순수 스키마 확장(+역할 백필)만 한다. 폐기·교체는 **PR 4-D**로 옮겨서, 폐기(`revoked=true`)와 신규 코드 자동 발급을 **같은 단계**에서 함께 처리해 "활성 코드 없음" 공백을 없앤다(4번·6번). 레거시 코드는 승인 플로우 자체(코드와 무관하게 전부 적용)를 우회할 수 없고, 4-D 배포 즉시 신규 정책으로 교체되므로 "무만료·무제한" 특성도 더 이상 우회 수단이 못 된다.
- **마지막 로그인 수단 보호 강화**: `users` 행을 `SELECT ... FOR UPDATE`로 잠근 뒤 로그인 수단 개수를 확인하는 방식으로 동시 해제 요청을 직렬화한다(보완 2). 비밀번호 없는 소셜 전용 계정이 마지막 소셜 연동을 끊으려는 시도도 같은 체크로 자동 거부.
- **가족 관리자 정책 확정**: Owner 1명(변경 없음), Admin은 인원 제한 없음, Admin은 초대 발급·가입 승인/거절 가능(기존 설계 그대로), Admin 지정·해제는 Owner만, Owner 이전은 PR 4 범위에서 명시적으로 제외(7번).
- **모바일 UI 범위 확정**: 승인 대기 화면·관리자 가입요청 목록 화면 2개를 4-F에 포함, `docs/contracts/ui.md` 토큰·Noto Sans KR 사용. UI Kit의 나머지 미반영 격차(부모님 모드 버튼 등)는 이번 인증 기능 구현의 필수 범위에서 **제외**(10-i).

## 미정 (팀 결정이 필요한 전체 목록)

현재 없음 — 이전까지 남아있던 5개 항목(모바일 화면 디자인, UI Kit 격차, 복수 owner/소유권 이전, 동시성 강화, 레거시 코드 공백 기간)은 2026-10-22 최종 확정으로 전부 해소됐다(바로 위 목록 참고). 구현 중 새로 발견되는 미정 사항은 이 절에 추가한다.
