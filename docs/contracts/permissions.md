# 권한 규칙

## 인증과 권한은 다르다

- **인증(누구인가)**: `Authorization: Bearer <Access Token(JWT)>` 가 있으면 `app.shared.auth.current_user()`가 JWT 를 검증해 `User`를 찾는다(실패해도 레거시로 넘어가지 않는다). 헤더가 없을 때만 익명 계정용 `X-Gyeot-Token`. 토큰이 없거나 틀리거나 만료면 401. role·그룹은 JWT 가 아니라 DB 에서 확인한다. 아이디/비밀번호로 가입한 정식 회원은 이 레거시 토큰으로 인증할 수 없다(401) — 정식 회원 인증은 로그인 API(PR 4-B 후속)가 발급하는 Access 토큰만 쓴다.
- **권한(이 가족 그룹에 접근할 자격이 있는가)**: `app.shared.auth.current_group_id()`가 요청자의 `user.active_group_id`를 돌려주는데, **단순히 그 값이 있다는 것만으로 허용하지 않는다** — `group_members` 테이블로 실제 소속인지 확인한 뒤에만 그룹 id를 돌려준다. 멤버가 아니면 403 `not_member`.

`active_group_id`는 "지금 선택된 그룹"을 가리키는 캐시값일 뿐, 그 자체가 접근 권한의 증거가 아니다. 접근 권한의 유일한 근거는 **`group_members` 테이블**이다.

## 가족 데이터 격리 규칙

1. 그룹에 속한 데이터(메시지·일정·지출·돌봄 기록·사진 등)를 다루는 라우터는 `group_id`를 요청(URL/쿼리/바디)에서 절대 받지 않고, 반드시 `Depends(current_group_id)`로만 받는다. 클라이언트가 보낸 `group_id`는 신뢰하지 않는다.
2. `created_by`/`paid_by`/`uploaded_by`처럼 "누가 썼는지"를 나타내는 값도 요청 바디에서 받지 않고 `Depends(current_user)`로 받은 사용자에서 유도한다. Pydantic 스키마에 그런 필드를 아예 넣지 않는 것이 기본 방어선이다(지금 모든 도메인이 이렇게 돼 있다).
3. 단일 리소스를 id로 조회·수정·삭제할 때(예: 일정 하나를 `event_id`로)는 **SQL 쿼리 자체에 `group_id` 조건을 포함**시킨다. PK로만 조회한 뒤 파이썬에서 `obj.group_id == group_id`를 비교하는 방식은 누군가 "단순화"하면서 그 비교를 지우기 쉬우므로 쓰지 않는다 (`schedule/repository.get()` 참고: `select(Event).where(Event.id == event_id, Event.group_id == group_id)`).
4. 구성원 개인 상태(문서 읽음 `knowledge_item_reads`, 대화방 읽음 `chat_room_reads` 등)는 요청한 사용자 **본인 것만** 조회·기록한다. 다른 구성원의 읽음 여부는 어떤 API로도 알 수 없다.
5. 새 도메인(Report 등)을 추가할 때도 위 1~4를 그대로 따른다.

## 공통 권한 함수 (`apps/api/app/shared/auth.py`)

| 함수 | 역할 | 쓰는 곳 |
|---|---|---|
| `current_user(x_gyeot_token, db)` | 인증 — 토큰으로 사용자를 찾는다 | 모든 라우터, `Depends(current_user)` |
| `current_group_id(user, db)` | 인증 + 권한 — 활성 그룹이 있고 **실제 그 그룹의 구성원**인지까지 확인한 뒤 group_id를 돌려준다 | 그룹 데이터를 다루는 모든 라우터, `Depends(current_group_id)` |
| `ensure_group_member(db, user_id, group_id)` | 순수 함수(FastAPI와 무관) — `group_members`에 그 조합이 있는지만 확인하고, 없으면 `ApiError(403, "not_member", ...)`를 던진다 | `current_group_id` 내부에서 쓰고, **라우터를 거치지 않고 Service를 직접 호출하는 모든 코드도 호출 전에 직접 써야 한다** |

이 표의 개념은 과제에서 말한 `require_authenticated_user`/`require_family_member`/`require_family_permission`/`assert_resource_family_access`에 각각 대응한다: `current_user`가 "인증된 사용자 요구", `current_group_id`가 "가족 구성원 요구", 규칙 3번(SQL 조건)이 "리소스가 그 가족에 속하는지 확인"에 해당한다. 기존 코드 스타일(`current_*`, `ensure_*`)을 그대로 따르기 위해 이름을 새로 바꾸지 않았다.

## AI Agent 등 Service를 직접 호출하는 코드의 원칙 (중요)

지금은 라우터를 거치지 않고 도메인 `service.py`를 직접 부르는 코드가 없다. 하지만 앞으로 AI Agent가 `family_chat.service.post(...)`, `schedule.service.create(...)` 같은 함수를 FastAPI 라우터 밖에서 직접 호출하게 된다면:

- 그 호출자는 **호출 전에 반드시 `ensure_group_member(db, user_id, group_id)`를 실행**해서 예외가 안 나는지 확인해야 한다. Service 함수 자체는 `group_id`가 이미 검증됐다고 가정하고 동작하므로(기존 팀원 코드를 넓게 고치지 않기 위한 설계), 그 가정을 지키는 책임은 호출자에게 있다.
- 사용자가 직접 선택하지 않은 그룹(`active_group_id`가 아닌 그룹)에 대해 쓰기 작업을 하려면, 왜 그 그룹을 대상으로 하는지와 `ensure_group_member` 검사를 통과했는지를 호출 지점에서 분명히 해야 한다.
- 이 규칙을 지키지 않고 Service를 직접 호출하는 PR은 리뷰에서 반려한다.

## 가입 승인 규칙

- **초대 코드 발급·폐기와 가입 요청 승인·거절은 가족 관리자(`group_members.role` 이 owner/admin)만** 할 수 있다(`join_service.require_manager`). 권한은 요청값이 아니라 DB 의 role 로만 판단하고, 승인된 사람은 항상 member 로 들어간다. **익명(레거시 토큰) 계정도 예외 없이** 초대 코드(레거시 코드 포함)로는 승인 대기 요청만 만들 수 있고, 승인 전에는 `group_members` 행이 없어 모든 그룹 API 가 막힌다(`no_group`/`not_member`). 다른 그룹의 가입 요청은 404 로 존재 자체를 숨긴다. 자세한 내용은 `docs/features/family-group.md`.

- **잔여 위험(레거시 초대 코드)**: 익명 계정이 만든 그룹의 레거시 코드(8자, 만료·사용 횟수 제한 없음)는 승인 우회는 아니지만, 거절·취소된 뒤에도 같은 사용자가 계속 재신청해 관리자 대기 목록을 채울 수 있다(코드 입력 실패 제한은 틀린 코드에만 적용). 관리자가 코드를 재발급하면 새 정책 코드(10자·24시간·1회)로 바뀌어 줄어든다.

## 아직 없는 기능 (이번 PR에서 만들지 않음)

- **활성 그룹 전환** API는 코드에 없다.
- **가족 이름 변경**: `PUT /family-group/groups/me/name`(본문 `{name}`, 1~60자, 앞뒤 공백 제거, 공백뿐이면 422). **가족 관리자(owner/admin)만** 바꿀 수 있고 일반 구성원은 403 `not_manager`, 가족이 없으면 400 `no_group`. 권한은 `group_members.role` 로만 판단한다.
- **가족 나가기**: `POST /family-group/groups/me/leave`(204). 일반 구성원·관리자(admin)는 자발적으로 나갈 수 있고, **소유자(owner)는 다른 구성원이 있으면 나갈 수 없다**(400 `cannot_leave_owner`, 소유권 이전이 생기기 전까지). 구성원이 소유자 혼자뿐이면 나갈 수 있고 가족의 모든 데이터가 지워진다. 멤버십 삭제(`role != 'owner'` 조건부 DELETE)·그 사람이 쓰거나 받은 별명 삭제·`active_group_id` 정리(이 그룹이 활성이었으면 남은 가족 중 가장 최근에 들어간 곳으로 바꾸고, 없으면 NULL)를 한 트랜잭션에서 처리한다. **토큰은 폐기하지 않는다** — 나간 뒤의 접근은 토큰이 아니라 `current_group_id` 의 `group_members` 확인(400 `no_group`/403 `not_member`)으로 막힌다. 이름 변경·구성원 강제 퇴출 API는 제품 결정으로 만들지 않는다. `apps/api/tests/test_membership_enforcement.py`는 멤버십은 없는데 `active_group_id`는 남은 상태도 시뮬레이션해서 막히는지 확인한다.

## 기존 인증 방식의 잔여 위험

- 토큰이 평문 랜덤 문자열(`secrets.token_urlsafe(24)`)로 `users.token`에 그대로 저장되고, 만료가 없다. DB가 유출되면 토큰도 그대로 노출된다.
- 로그인 절차가 없다(이름/역할만 입력하면 가입) — 신원 확인이 아니라 "기기 보관 토큰"에 가깝다.
- 레이트 리밋, 토큰 재발급/폐기, 세션 무효화가 없다.

이번 PR은 "로그인한 사람이 자기 가족 데이터만 보게" 하는 권한 계층을 고친 것이고, 인증 자체(토큰 방식)는 바꾸지 않았다. 다음 PR(정식 사용자 인증)에서 다룰 항목: 토큰 해시 저장(평문 대신), 만료/재발급, 가능하다면 실제 로그인(소셜 로그인 등 — `current_user`만 바꾸면 되도록 이미 분리돼 있음), 탈퇴 시 토큰 즉시 무효화.

