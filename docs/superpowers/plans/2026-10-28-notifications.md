# 알림함(notifications) 1차 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메인 화면(AI 채팅) 상단 종 아이콘에서 열리는 앱 안 알림함을 만든다. 서버 공용 기반과 가족 그룹 가입 이벤트 연결, 앱 알림 화면까지가 1차다.

**Architecture:** `app/shared/notifications.py`에 모델 `Notification`과 `notify()`를 두고(다른 기능이 서로를 import하지 않게), `app/features/notifications/`가 내 알림 조회·읽음 API를 제공한다. 가족 그룹 서비스가 사건 자리에서 `notify()`를 호출한다. 앱은 `features/notifications/`에서 서버를 읽고 `AppHeader`에 종 아이콘을 붙인다.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic(expand만), Pydantic v2, pytest(SQLite) · Expo SDK 54 JS(TypeScript 금지), node 내장 test runner.

**Spec:** `docs/superpowers/specs/2026-10-28-notifications-design.md`

## 스펙과 달라진 점 (코드를 읽고 확정한 것)

- 1차 연결은 **가입 요청(관리자에게)·가입 승인(신청자에게)** 만 한다. 가입 **거절**은 신청자가 아직 구성원이 아니라(조회가 `group_members` 기준이고 `notify()`도 비구성원을 건너뜀) 알림함에 남지 않으므로 제외한다 — 신청자는 기존 대기 화면에서 상태를 본다. 구성원 변경(탈퇴·역할 변경)과 AI 기록 처리 완료는 호출 자리가 팀원 영역이거나 아직 없어 2차로 미룬다. `ai_record` 분류는 데이터·앱 표시에만 미리 정의한다.
- 스펙의 열린 질문 "탈퇴한 사람의 알림": **조회할 때 `group_members`로 걸러 낸다**(정리 작업 없음).

## Global Constraints

- 앱은 JavaScript만, `.ts/.tsx/tsconfig` 금지. 파일 확장자 `.js`. 의존성 추가 금지(`expo-notifications` 포함).
- 색·간격·글자 크기는 `@/theme` 토큰만 쓴다(`colors.primary`, `colors.peach`, `colors.success`, `colors.accent` 등 기존 토큰).
- 서버 구조는 `router.py → service.py → repository.py`, 요청·응답은 `schemas.py`. 다른 기능의 내부 파일을 import하지 않고 공통 코드는 `app/shared`에 둔다.
- 그룹 데이터 라우터는 `group_id`를 요청에서 받지 않는다. 알림은 항상 `current_user` 기준 내 것만 다룬다.
- DB 스키마 변경은 Alembic expand 리비전 1개만(`alembic heads` 단일 head, 격리 PostgreSQL 16 임시 컨테이너에서 검증). 공용 DB·MVP DB·개인 Docker DB에는 연결하지 않는다. 파괴적 변경·`destructive-approved` 문구 금지.
- 알림 문구는 고정 템플릿. 금액·위치·건강 정보·AI 요약·채팅 내용을 넣지 않는다. 개인 데이터를 로그에 남기지 않는다.
- `.env`·pgpass 읽기·출력 금지. 서버 API를 바꾸면 `PYTHONPATH=. python scripts/export_openapi.py`로만 `docs/contracts/openapi.json`을 갱신한다. `docs/contracts/db.md`, `docs/features/notifications.md`, `docs/requirements/notifications.md`를 갱신한다.
- 팀원 영역(`ai_assistant`·`billing`·`care`·`schedule`)은 이번 계획에서 수정하지 않는다.
- 커밋 트레일러: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01QWrnAr1LSzwjkxt2eLqZyD`. 로컬의 `apps/api/.env.example` 변경은 커밋하지 않는다.

## Review Focus

스펙은 말하지 않지만 사용자가 만날 가능성이 큰 경우(각 줄은 해당 task의 시험으로 고정한다):

1. 알림 저장이 실패해도 가입 요청·승인 자체는 성공해야 한다 (Task 2).
2. 같은 사람이 두 번 요청(중복 제출)해도 관리자에게 알림이 중복되지 않아야 한다 — `request_to_join`이 기존 대기 요청을 그대로 돌려주는 경로 (Task 4).
3. 그룹에서 빠진 사람은 그 그룹의 옛 알림이 목록·개수에 나오면 안 된다 (Task 3).
4. 알림이 0개이거나 `kind`에 없는 값을 주면 빈 목록 / 422가 되고 서버 오류가 나면 안 된다 (Task 3).
5. 알림 목록을 못 불러와도(서버 오류·오프라인) 종 아이콘이 화면을 깨뜨리지 않고 배지만 숨겨야 한다 (Task 6).

## 파일 구조

| 파일 | 역할 |
|---|---|
| `apps/api/app/shared/notifications.py` (신규) | 모델 `Notification`, 상수 `KINDS`, 함수 `notify()` |
| `apps/api/app/shared/schema.py` (수정) | `SHARED_MODEL_FEATURES["notifications"]` 등록 |
| `apps/api/alembic/versions/<new>_notifications.py` (신규) | 테이블 `notifications` 생성(expand) |
| `apps/api/app/features/notifications/{__init__,router,service,repository,schemas}.py` (신규) | 내 알림 조회·읽음 API |
| `apps/api/app/main.py` (수정) | 라우터 등록 `("notifications", notifications_router)` |
| `apps/api/app/features/family_group/join_service.py` (수정) | 가입 요청·승인에서 `notify()` 호출 |
| `apps/mobile/src/features/notifications/{api.js,kinds.js,useUnread.js}` (신규) | 서버 호출, 분류 표시·이동 규칙, 안 읽은 개수 훅 |
| `apps/mobile/src/features/notifications/screens/NotificationsScreen.js` (신규) | 알림 목록 화면 |
| `apps/mobile/src/app/notifications.js` (신규) | 라우트(re-export만) |
| `apps/mobile/src/shared/components/AppHeader.js` (수정) | 종 아이콘·배지 props |
| `apps/mobile/src/features/ai-assistant/screens/AiAssistantScreen.js` (수정) | 종 아이콘 연결 한 줄 |
| `docs/contracts/{openapi.json,db.md}`, `docs/features/notifications.md`, `docs/requirements/notifications.md` | 문서 |

---

### Task 1: 공용 모델 + Alembic 리비전

**Files:**
- Create: `apps/api/app/shared/notifications.py`, `apps/api/alembic/versions/<rev>_notifications.py`
- Modify: `apps/api/app/shared/schema.py` (`SHARED_MODEL_FEATURES`에 `"notifications": ("notifications",)`), `docs/contracts/db.md`
- Test: `apps/api/tests/test_notifications_model.py`

**Interfaces:**
- Produces: `app.shared.notifications.KINDS: tuple[str, ...] = ("schedule","billing","care","family_group","ai_record")`; `class Notification(Base)` — 테이블 `notifications`, 컬럼은 스펙 1번 표 그대로(`id String(32)` PK 기본값 `uuid4().hex[:12]`, `user_id`·`group_id`·`actor_user_id` FK, `kind String(16)`, `event String(40)`, `title String(120)`, `body String(200) nullable`, `target_type String(32) nullable`, `target_id String(64) nullable`, `created_at`·`read_at` timezone-aware DateTime). 인덱스 `ix_notifications_user_created (user_id, created_at)`, `ix_notifications_user_read (user_id, read_at)`.

- [ ] **Step 1: 실패하는 시험** — `test_notifications_model.py::test_schema_registered_and_table_created`: `feature_tables()`에 `"notifications"` 키가 있고 그 안에 `notifications` 테이블이 있으며 `KINDS`가 5개 값이다. `::test_create_all_creates_columns`: `SessionLocal`로 `Notification`을 `read_at=None`으로 저장·조회하면 `id`가 12자리, `created_at`이 채워진다(먼저 users·groups 행 필요: `tests.helpers.signup` + 그룹 생성 응답 사용).
- [ ] **Step 2: 실행해 실패 확인** — `cd apps/api && pytest tests/test_notifications_model.py -v` → FAIL(모듈 없음).
- [ ] **Step 3: 모델과 등록 구현** — `app/shared/used_proposals.py`의 스타일(`Base`, `Mapped`, `mapped_column`)을 따라 `notifications.py`를 만들고 `schema.py`에 등록한다.
- [ ] **Step 4: 리비전 작성·검증** — 최신 head(`2b5b752790b9` 이후 main의 실제 head를 `alembic heads`로 확인) 위에 `notifications` 테이블과 두 인덱스를 만드는 리비전을 쓴다(downgrade는 테이블 drop; 새 테이블이라 데이터 손실 없음을 docstring에 적는다). 격리 PostgreSQL 16 임시 컨테이너(`docker run`)에서 `alembic upgrade head`, `python scripts/check_alembic_migrations.py`, `python scripts/check_schema_matches_models.py`를 통과시키고 컨테이너를 지운다. `docs/contracts/db.md`에 테이블 설명을 추가한다.
- [ ] **Step 5: 시험 통과 확인** — `pytest tests/test_notifications_model.py -v` → PASS, `ruff check . && ruff format --check .` 통과.
- [ ] **Step 6: 커밋** — `feat: 알림함 공용 모델과 Alembic 리비전 추가`.

### Task 2: `notify()` 서비스 함수

**Files:**
- Modify: `apps/api/app/shared/notifications.py`
- Test: `apps/api/tests/test_notifications_notify.py`

**Interfaces:**
- Consumes: Task 1의 `Notification`, `KINDS`; `app.shared.auth.GroupMember` 조회는 `db.get(GroupMember, (group_id, user_id))`(auth.py의 `ensure_group_member`와 같은 방식, 예외 대신 건너뜀).
- Produces: `notify(db: Session, *, group_id: str, kind: str, event: str, recipients: Iterable[str], title: str, body: str | None = None, target_type: str | None = None, target_id: str | None = None, actor_user_id: str | None = None) -> int` — 만든 알림 수를 돌려준다. 커밋은 호출하는 쪽이 한다.

- [ ] **Step 1: 실패하는 시험** — 각각 `assert`로 고정:
  - `test_creates_one_row_per_member_recipient`: 구성원 2명·`recipients` 3명(1명은 비구성원) → 반환 2, 비구성원 행 없음.
  - `test_excludes_actor`: `actor_user_id`가 `recipients`에 있으면 그 사람 행이 없다.
  - `test_dedupes_recipients`: 같은 id를 두 번 줘도 1행.
  - `test_unknown_kind_raises_value_error`: `kind="chat"` → `ValueError`(개발 실수를 일찍 알린다. 이것만 예외).
  - `test_failure_is_isolated`: `Notification` 저장 중 예외가 나도(`monkeypatch`로 `db.add`가 `RuntimeError`) 반환 0이고, 같은 세션의 앞선 변경(예: 이미 `add`한 다른 행)은 `commit`으로 유지된다(Review Focus 1).
- [ ] **Step 2: 실행해 실패 확인** — `pytest tests/test_notifications_notify.py -v` → FAIL.
- [ ] **Step 3: 구현** — 대상 정리(중복 제거, `actor_user_id` 제외, 구성원 확인) 후 `with db.begin_nested():` 안에서 행을 추가하고 `Exception`은 잡아서 `logging.getLogger(__name__).warning("notify failed kind=%s event=%s", kind, event)`만 남기고 0을 돌려준다(개인 데이터는 로그에 쓰지 않는다).
- [ ] **Step 4: 시험 통과 확인** — 같은 명령 PASS, `ruff` 통과.
- [ ] **Step 5: 커밋** — `feat: 알림 기록 함수 notify() 추가(수신자 검증·실패 격리)`.

### Task 3: 알림 API (`features/notifications`)

**Files:**
- Create: `apps/api/app/features/notifications/{__init__,router,service,repository,schemas}.py`, `apps/api/app/features/notifications/tests/{__init__,test_notifications_api}.py`
- Modify: `apps/api/app/main.py`, `docs/contracts/openapi.json`(스크립트로만), `docs/requirements/notifications.md`(신규), `docs/features/notifications.md`(신규)

**Interfaces:**
- Consumes: `Notification`, `KINDS`(Task 1), `notify()`(시험 데이터 생성용, Task 2); 인증은 `app.shared.auth.current_user`.
- Produces (`schemas.py`): `NotificationOut{id,kind,event,title,body,target_type,target_id,actor_user_id,created_at,read_at}`, `NotificationList{items: list[NotificationOut], next_cursor: str | None}`, `UnreadCount{total: int, by_kind: dict[str, int]}`, `ReadAllResult{updated: int}`. 경로: `GET /notifications?kind=&limit=&cursor=`(limit 기본 30·최대 100, 최신순, `cursor`는 `"<created_at ISO>|<id>"`를 base64url로 인코딩한 불투명 값), `GET /notifications/unread-count`, `POST /notifications/{id}/read` → `NotificationOut`, `POST /notifications/read-all`(본문 `{kind?: str}`) → `ReadAllResult`.
- 모든 조회의 기준: `Notification.user_id == user.id` **그리고** `(group_id, user_id)`가 `group_members`에 있는 행만(탈퇴한 그룹의 옛 알림 제외).

- [ ] **Step 1: 실패하는 시험** — `test_notifications_api.py`(정식 계정 헬퍼는 `family_group/tests/test_join_approval.py`의 `account`/`create_group` 패턴을 같은 파일에 복사하지 말고 `tests.helpers`의 `signup`+`join_family`로 구성원을 만든다):
  - `test_list_newest_first_and_paginates`: 알림 5개, `limit=2` 세 번 호출로 모두 중복·누락 없이 받는다, 마지막 `next_cursor`는 `None`.
  - `test_kind_filter_and_invalid_kind`: `kind=schedule`은 해당 것만, `kind=chat`은 422(Review Focus 4). 알림 0개면 `{"items": [], "next_cursor": null}`.
  - `test_unread_count_by_kind`: 읽음 처리 전후 `total`·`by_kind`가 맞다.
  - `test_read_marks_and_is_idempotent`: 두 번 눌러도 200, `read_at`이 처음 시각 그대로.
  - `test_other_users_notification_is_404`: 남의 알림 id로 읽음 → 404, 내 목록·개수에 영향 없음.
  - `test_read_all_optionally_by_kind`: `kind` 지정 시 그 분류만 읽음, `updated` 개수 일치.
  - `test_left_group_notifications_hidden`: 구성원에서 빠진(`group_members` 행 삭제) 사용자는 그 그룹 알림이 목록·개수에 안 나온다(Review Focus 3).
  - `test_requires_login`: 토큰 없이 401.
- [ ] **Step 2: 실행해 실패 확인** — `pytest app/features/notifications -v` → FAIL.
- [ ] **Step 3: 구현** — `main.py`의 등록 반복문 튜플에 `("notifications", notifications_router)`를 추가한다(`GUARDED_FEATURES`에는 넣지 않는다). 읽음 처리는 `UPDATE ... WHERE user_id=:me AND read_at IS NULL`처럼 이미 읽은 건 건드리지 않는다.
- [ ] **Step 4: 문서·계약 갱신** — `PYTHONPATH=. python scripts/export_openapi.py`, `docs/requirements/notifications.md`(스펙 요약과 링크), `docs/features/notifications.md`(구현 현황) 작성.
- [ ] **Step 5: 전체 확인** — `pytest`(전체)·`ruff check . && ruff format --check .` 통과. 실패를 약화·삭제로 해결하지 않는다.
- [ ] **Step 6: 커밋** — `feat: 내 알림 조회·읽음 API 추가(/notifications)`.

### Task 4: 가족 그룹 가입 이벤트 연결

**Files:**
- Modify: `apps/api/app/features/family_group/join_service.py` (`request_to_join`, `approve`)
- Test: `apps/api/app/features/family_group/tests/test_join_notifications.py`

**Interfaces:**
- Consumes: `notify()`(Task 2); `MANAGER_ROLES`, `jrepo`(기존).
- Produces: 알림 `kind="family_group"`. 이벤트와 문구(고정):
  - `event="join_requested"`, 수신자는 해당 그룹 `role in MANAGER_ROLES`인 구성원 전원, `title="가족 그룹 참여 요청이 왔어요"`, `body="{신청자 이름}님이 참여를 요청했어요"`, `target_type="join_request"`, `target_id=<요청 id>`, `actor_user_id=<신청자 id>`.
  - `event="join_approved"`, 수신자는 신청자 한 명(`add_member` 이후라 구성원), `title="가족 그룹에 참여했어요"`, `body=None`, `target_type="group"`, `target_id=<group_id>`, `actor_user_id=<승인한 관리자 id>`.

- [ ] **Step 1: 실패하는 시험** — `test_join_notifications.py`(기존 `test_join_approval.py`의 흐름 함수 사용):
  - `test_request_notifies_all_managers_only`: owner·admin·member가 있는 그룹에 신청 → owner·admin에게만 `join_requested` 1건씩, member·신청자에게는 없다.
  - `test_duplicate_request_does_not_duplicate_notification`: 같은 사람이 두 번 신청해도 관리자 알림은 1건(Review Focus 2).
  - `test_approve_notifies_applicant`: 승인하면 신청자에게 `join_approved`가 생기고 신청자 알림 목록(`GET /notifications`)에 보인다.
  - `test_reject_creates_no_notification`: 거절하면 어떤 알림도 새로 생기지 않는다(스펙과 달라진 점 참고).
  - `test_notify_failure_does_not_break_join`: `monkeypatch`로 `notify`가 예외를 내도 신청·승인 응답은 기존과 같다(Review Focus 1).
- [ ] **Step 2: 실행해 실패 확인** — `pytest app/features/family_group/tests/test_join_notifications.py -v` → FAIL.
- [ ] **Step 3: 구현** — `request_to_join`은 **새 `JoinRequest` 행을 만든 경로에서만**, 커밋 직전에 `notify()`를 호출한다(기존 대기 요청을 돌려주는 경로에서는 호출하지 않는다). `approve`는 `add_member`와 `active_group_id` 설정 뒤, 커밋 직전에 호출한다. 관리자 id 목록은 `GroupMember`에서 `role in MANAGER_ROLES`로 읽는 작은 헬퍼를 `join_repository.py`에 `manager_ids(db, group_id) -> list[str]`로 추가한다.
- [ ] **Step 4: 시험 통과·회귀 확인** — 신규 시험 PASS, `pytest app/features/family_group -q` 기존 236개가 그대로 통과, `ruff` 통과.
- [ ] **Step 5: 커밋** — `feat: 가족 그룹 가입 요청·승인 때 알림 기록`.

### Task 5: 앱 서버 호출 + 분류 규칙 + 개수 훅

**Files:**
- Create: `apps/mobile/src/features/notifications/{api.js,kinds.js,useUnread.js}`, `apps/mobile/tests/notifications.test.js`

**Interfaces:**
- Produces:
  - `api.js`: `listNotifications({kind, cursor, limit}) → {items, next_cursor}`, `getUnreadCount() → {total, by_kind}`, `markRead(id) → NotificationOut`, `markAllRead(kind?) → {updated}` — 모두 `shared/api`의 `apiFetch` 사용(화면에서 직접 fetch 금지). JSDoc `@param/@returns`.
  - `kinds.js`: `KIND_META: Record<kind, {label, icon, color}>` — `schedule`: 일정/`calendar-outline`/`colors.primary`, `billing`: 가계/`wallet-outline`/`colors.accent`, `care`: 돌봄/`heart-outline`/`colors.success`, `family_group`: 가족/`people-outline`/`colors.peach`, `ai_record`: 기록/`document-text-outline`/`colors.textMuted`; `metaFor(kind)`(모르는 kind는 기본 메타 반환); `routeFor(n) → string | null` — `family_group`+`join_requested` → `"/family-requests"`, `family_group`+`join_approved` → `"/family"`, 그 외·대상 없음은 `null`.
  - `useUnread.js`: `useUnread() → {total: number, refresh: () => Promise<void>}` — 화면에 포커스될 때마다 `getUnreadCount`를 부르고, **실패하면 `total`을 0으로 두고 예외를 밖으로 던지지 않는다**(Review Focus 5).

- [ ] **Step 1: 실패하는 시험** — `notifications.test.js`(`chatpins.test.js`와 같은 node:test 스타일, `globalThis.fetch` 가짜):
  - `listNotifications`가 `GET /notifications?kind=care&limit=30&cursor=...` 경로를 만든다, `markRead`가 `POST /notifications/{id}/read`, `markAllRead("care")`가 본문 `{kind:"care"}`.
  - `metaFor("unknown")`이 예외 없이 기본 메타를, `routeFor`가 위 표대로 매핑하고 대상 없는 알림은 `null`.
  - `useUnread`의 실패 처리 로직(순수 함수로 분리한 `safeTotal(promise) → Promise<number>`)이 거절된 요청에서 0을 돌려준다.
- [ ] **Step 2: 실행해 실패 확인** — `cd apps/mobile && npm test -- tests/notifications.test.js` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스대로. 색은 `@/theme` 토큰만.
- [ ] **Step 4: 시험·린트 통과** — 해당 시험 PASS, `npm run lint` 통과.
- [ ] **Step 5: 커밋** — `feat: 알림 앱 API·분류 규칙·안 읽은 개수 훅`.

### Task 6: 알림 화면 + 종 아이콘

**Files:**
- Create: `apps/mobile/src/features/notifications/screens/NotificationsScreen.js`, `apps/mobile/src/app/notifications.js`(`export { default } from "@/features/notifications/screens/NotificationsScreen";`)
- Modify: `apps/mobile/src/shared/components/AppHeader.js`(새 props `onBell?: () => void`, `bellCount?: number` — 종 `IconButton`(`notifications-outline`)을 오른쪽 묶음 맨 앞에 두고, `bellCount > 0`이면 배지 숫자(99+ 상한)와 접근성 라벨 `알림, 안 읽은 알림 N개`), `apps/mobile/src/features/ai-assistant/screens/AiAssistantScreen.js`(`useUnread()`를 쓰고 `<AppHeader onBell={() => router.push("/notifications")} bellCount={total} .../>` 한 줄 변경), `docs/features/notifications.md`
- Test: `apps/mobile/tests/notifications.test.js`에 추가

**Interfaces:**
- Consumes: Task 5의 `listNotifications`, `markRead`, `markAllRead`, `KIND_META`, `metaFor`, `routeFor`, `useUnread`; 기존 `Screen`(`@/shared/components/Screen`), `Tag`, `Card`/`ListItem`.
- Produces: `NotificationsScreen`: 분류 칩(전체+5개 분류) 필터, 항목마다 분류 아이콘·색 + 분류 이름 `Tag` + 제목·본문·상대 시간, 안 읽은 항목은 굵은 제목 + 점(`colors.peach`), 항목을 누르면 `markRead` 후 `routeFor`가 있으면 `router.push`, "모두 읽음" 버튼(현재 필터의 분류만), 아래로 당기면 새로고침, 끝에서 `next_cursor`로 이어 불러오기, 빈 목록 문구 "아직 알림이 없어요", 불러오기 실패 시 "알림을 불러오지 못했어요" 와 다시 시도 버튼.

- [ ] **Step 1: 실패하는 시험** — 화면 렌더링은 자동화하지 않는 기존 방식을 따라 순수 로직만: `notifications.test.js`에 `badgeLabel(total) → string | null`(0이면 `null`, 100 이상이면 `"99+"`)와 `relativeTime(iso, now) → string`(1분 미만 "방금", 분·시간·일 단위, 7일 넘으면 `M월 D일`) 시험을 추가한다(둘 다 `kinds.js` 또는 `format.js`에 순수 함수로 둔다).
- [ ] **Step 2: 실행해 실패 확인** — `npm test -- tests/notifications.test.js` → FAIL.
- [ ] **Step 3: 구현** — 위 순수 함수와 화면·라우트·헤더 변경. 화면은 400줄을 넘기지 않게 항목 행을 `features/notifications/components/NotificationRow.js`로 분리한다(이 파일도 이 task의 Create 대상이다).
- [ ] **Step 4: 시험·린트·웹 번들 확인** — `npm test`(전체)·`npm run lint` 통과. 로컬 Metro 웹(`npx expo start --web` 또는 기존 실행 중인 것)에서 알림 화면 진입이 오류 없이 열리는지 확인한다. 실기기·에뮬레이터 확인은 **하지 못한 것으로 보고**한다.
- [ ] **Step 5: 문서·커밋** — `docs/features/notifications.md` 구현 현황 갱신(서버·앱·연결된 이벤트·2차로 미룬 것). 커밋 `feat: 알림 화면과 메인 종 아이콘 추가`.

### Task 7: 마무리 확인

- [ ] **Step 1: 전체 재확인** — 서버 `pytest`·`ruff`, 앱 `npm test`·`npm run lint`, `alembic heads` 단일, openapi 재생성 후 변경 없음(`git diff --exit-code docs/contracts/openapi.json`).
- [ ] **Step 2: 수동 흐름 확인(로컬, 임시 SQLite 서버)** — 계정 2개로 가입 → 가족 그룹 → 두 번째 계정이 초대 코드로 신청 → 관리자 계정의 `GET /notifications`에 `join_requested` 1건 → 승인 → 신청자 계정에 `join_approved` 1건. 이 과정은 임시 SQLite만 쓰고 공용·개인 DB를 건드리지 않는다.
- [ ] **Step 3: 푸시** — 브랜치(`feature/seungdeuk-notifications` 등)를 푸시하고 시험·린트 결과와 "확인 못한 것(실기기, PostgreSQL 운영 환경)"을 보고한다. PR은 사용자가 요청할 때만 만든다.

---

## 2차 (이 계획 밖, 팀원 협의 후)

일정(공유 일정 등록·수정·삭제, 함께 일정 요청·응답), 가계(정산 요청), 돌봄(실종 안내·위치 공유 시작), AI 기록 처리 완료, 구성원 변경에 `notify()` 호출을 한 줄씩 추가한다. `KIND_META`·`routeFor`에 이동 경로를 더하는 앱 변경이 함께 필요하다.
