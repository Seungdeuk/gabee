# 앱 푸시 알림 1단계(기반) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 푸시 토큰 등록·사용자별 푸시 설정·Expo 푸시 발송을 만들고, 알림함 사건(가입 요청·승인, 고객센터 답변, 일정 같이해요)을 폰 푸시로 보낸다.

**Architecture:** 서버는 `app/shared/push_models.py`(테이블)와 `app/shared/push.py`(차단 규칙·메시지 만들기·발송)를 두고, `notify()` 가 알림 저장 뒤 보낼 푸시를 세션에 쌓아 커밋 후(`after_commit`)에 백그라운드로 발송한다. API 는 기존 `features/notifications` 에 붙인다. 앱은 `expo-notifications` 로 토큰을 받아 로그인 뒤 등록하고, 로그아웃 때 해제한다.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, httpx(이미 의존성), Expo SDK 54 `expo-notifications`, EAS development build, Expo 푸시 API(→ FCM).

**Spec:** `docs/superpowers/specs/2026-11-05-push-notifications-design.md` (4절 서버, 5절 앱, 7절 PR 분할). 사용자 승인: `expo-notifications` 추가·EAS Build·Firebase FCM·FastAPI 서버 발송(2026-11-05).

## Global Constraints

- 요청·응답은 Pydantic(`schemas.py`), 구조는 router → service → repository, 라우터에 로직 없음. 새 엔드포인트마다 테스트 최소 1개.
- 앱 서버 호출은 `features/notifications/api.js` 에서만, 함수마다 JSDoc, 색·간격은 `theme/` 토큰만, 파일은 `.js`, `src/app/` 에는 라우트 파일만.
- 푸시 문구는 고정 템플릿 제목만. 금액·장소·건강·AI 요약 없음. 토큰은 로그에 남기지 않는다(앞 6자리만).
- 푸시 실패·타임아웃은 호출 쪽에 예외를 던지지 않고 알림함 저장과 원래 기능에 영향이 없다. 재시도 없음, 타임아웃 5초.
- `PUSH_ENABLED` 기본 false. 새 환경변수는 `apps/api/.env.example` 에만 추가(로컬의 미커밋 `.env.example` 수정은 커밋하지 않는다 — 새 worktree 에서 작업한다).
- Alembic: 단일 head 확인, expand 만(테이블 추가), 임시 PostgreSQL 에서만 검증, 공용 DB 는 건드리지 않는다. `destructive-approved` 문구 금지.
- 브랜치는 `release/1.2` 에서 따고 PR base 도 `release/1.2`. 커밋 끝에 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` 와 `Claude-Session: https://claude.ai/code/session_01VqKm2T3aZc9VcwYMF82g3N`.
- 서버 시험은 `cd apps/api && PYTHONPATH=. python -m pytest <경로> -q`, 린트는 `ruff check . && ruff format --check .`, 앱은 `cd apps/mobile && npm test && npx eslint src tests`.

## Review Focus

1. 같은 토큰이 다른 사용자로 다시 등록됨(기기 공유·재로그인) → 소유자만 바뀌고 줄이 중복되지 않는다. (Task 3)
2. 방해금지가 자정을 넘김(22:00~07:00) → 23:30·06:30 은 억제, 12:00 은 발송. (Task 4)
3. 한 사용자가 기기 2대 → 두 토큰 모두 받는다. 같은 사건·같은 받는 사람 중복은 한 번. (Task 5)
4. 푸시 테이블이 아직 없는 DB(스키마 미적용)에서 `notify()` 호출 → 예외 없이 알림함만 저장. (Task 5)
5. Expo 가 응답 없음·5xx·잘못된 JSON → 원래 요청이 성공하고 토큰은 지워지지 않는다. (Task 5)

---

## PR 1 — 서버 A: 테이블·설정·토큰 API

### Task 1: 푸시 테이블과 마이그레이션

**Files:**
- Create: `apps/api/app/shared/push_models.py`, `apps/api/alembic/versions/<새 id>_push_tokens_settings.py`
- Modify: `apps/api/app/shared/schema.py:35-40`(`SHARED_MODEL_FEATURES`), `apps/api/app/shared/db.py:56`(모델 임포트), `docs/contracts/db.md`
- Test: `apps/api/app/shared/tests/test_push_models.py`(없으면 `apps/api/tests/test_push_models.py`)

**Interfaces:**
- Produces: `PushToken(id: str PK, user_id: str FK users.id index, token: str unique, platform: str, device_label: str|None, created_at, last_seen_at)`, `PushSetting(user_id: str PK FK users.id, enabled: bool=True, preview_mode: str="full", muted_kinds: list[str] JSON=[], quiet_start: time|None, quiet_end: time|None, updated_at)`. `Base` 는 `app.shared.db` 의 기존 것.

- [ ] **Step 1: 실패하는 시험** — `test_push_tables_registered_to_notifications_feature`: `feature_tables()["notifications"]` 에 `push_tokens`, `push_settings` 가 들어 있다. (`SHARED_MODEL_FEATURES` 에 `"push_models": ("notifications",)` 가 없으면 core 로 분류돼 실패한다.)
- [ ] **Step 2: 실행해서 실패 확인** — `pytest apps/api/.../test_push_models.py -q` → FAIL(모듈 없음).
- [ ] **Step 3: 구현** — `push_models.py` 에 두 모델(문자열 id 는 기존 `Notification` 과 같은 방식, `token` 은 `unique=True`, `muted_kinds` 는 `JSON` 컬럼 기본 빈 목록). `schema.py` 에 `"push_models": ("notifications",)` 추가. `apps/api/app/shared/db.py:56` 의 `init_db` 안 모델 임포트 줄(`from app.shared import notifications as _notifications  # noqa: F401`) 바로 아래에 `from app.shared import push_models as _push_models  # noqa: F401` 를 같은 방식으로 추가한다.
- [ ] **Step 4: 마이그레이션** — 임시 PostgreSQL(docker `pgvector/pgvector:pg16`)에서 `alembic revision --autogenerate -m "push tokens settings"`(down_revision 은 `alembic heads` 의 현재 단일 head), DDL 을 눈으로 확인(테이블 2개 추가뿐, `DROP`/`ALTER` 없음), `alembic upgrade head`, `python scripts/check_alembic_migrations.py`, `python scripts/check_schema_matches_models.py`, `python scripts/migration_risk.py` 가 위험 없음, `alembic heads` 1개.
- [ ] **Step 5: 시험 통과·`db.md` 갱신** — 같은 pytest PASS. `docs/contracts/db.md` 에 두 테이블 설명 줄 추가(리비전 id 포함).
- [ ] **Step 6: 커밋** — `feat: 푸시 토큰·푸시 설정 테이블 추가`.

### Task 2: 푸시 설정 API

**Files:**
- Modify: `apps/api/app/features/notifications/{schemas.py,repository.py,service.py,router.py}`
- Test: `apps/api/app/features/notifications/tests/test_push_settings_api.py`

**Interfaces:**
- Consumes: `PushSetting` (Task 1), 기존 `current_user`, `get_db`, `Kind`.
- Produces: `GET /notifications/push-settings` → `PushSettingsOut{enabled: bool, preview_mode: Literal["full","sender","hidden"], muted_kinds: list[Kind], quiet_start: time|None, quiet_end: time|None}`(줄이 없으면 기본값 `true/"full"/[]/None/None`, 줄을 만들지 않는다). `PUT /notifications/push-settings` 본문 `PushSettingsIn` 같은 필드 → `PushSettingsOut`. `quiet_start`·`quiet_end` 는 둘 다 있거나 둘 다 없어야 하고, 아니면 422. 서비스 함수 `get_push_settings(db, user) -> PushSettingsOut`, `put_push_settings(db, user, body) -> PushSettingsOut`.

- [ ] **Step 1: 시험 작성** — `test_defaults_when_no_row`(기본값, DB 에 줄 없음), `test_put_then_get_roundtrip`(`muted_kinds=["billing"]`, `preview_mode="sender"`, `quiet_start="22:00"`, `quiet_end="07:00"`), `test_invalid_preview_mode_and_kind_are_422`, `test_quiet_hours_need_both_or_neither`(422), `test_requires_login`(401), `test_settings_are_per_user`.
- [ ] **Step 2: 실행해서 실패 확인** — `pytest .../test_push_settings_api.py -q` → FAIL(404).
- [ ] **Step 3: 구현** — 기존 알림 라우터와 같은 구조로 repository(get/upsert)·service·router 추가. `/push-settings` 경로는 `/{notification_id}/read` 와 겹치지 않으므로 순서 영향 없음.
- [ ] **Step 4: 통과 확인** — 같은 pytest PASS, `ruff check`·`ruff format --check` 통과.
- [ ] **Step 5: 커밋** — `feat: 푸시 설정 조회·저장 API 추가`.

### Task 3: 푸시 토큰 등록·해제 API + 문서·ADR·openapi

**Files:**
- Modify: `apps/api/app/features/notifications/{schemas.py,repository.py,service.py,router.py}`, `docs/contracts/openapi.json`(스크립트 생성), `docs/requirements/notifications.md`, `docs/features/notifications.md`, `docs/adr/README.md`
- Create: `docs/adr/<가장 큰 번호+1>-push-via-expo.md`
- Test: `apps/api/app/features/notifications/tests/test_push_token_api.py`

**Interfaces:**
- Consumes: `PushToken` (Task 1).
- Produces: `PUT /notifications/push-token` 본문 `PushTokenIn{token: str, platform: Literal["android","ios"], device_label: str|None}` → 204. 토큰은 `ExponentPushToken[` 또는 `ExpoPushToken[` 로 시작하고 `]` 로 끝나며 길이 ≤ 255, 아니면 422. 같은 토큰이 이미 있으면 `user_id`·`platform`·`device_label`·`last_seen_at` 을 갱신한다(소유자 이동). `DELETE /notifications/push-token` 본문 `PushTokenDelete{token: str}` → 204, 본인 소유만 삭제(없거나 남의 것이면 아무것도 안 하고 204).

- [ ] **Step 1: 시험 작성** — `test_register_creates_row`, `test_reregister_same_user_updates_not_duplicates`, `test_token_moves_to_new_owner`(A 가 등록한 토큰을 B 가 등록 → 줄 1개, 소유자 B), `test_bad_token_format_422`(`"abc"`, `"ExponentPushToken[x"`), `test_delete_own_token`, `test_cannot_delete_others_token`(남의 토큰은 그대로 남음), `test_requires_login`.
- [ ] **Step 2: 실행해서 실패 확인** — FAIL(404).
- [ ] **Step 3: 구현** — repository `upsert_push_token`, `delete_push_token(db, user_id, token)`, 라우터에 PUT·DELETE(`status_code=204`, `Response`).
- [ ] **Step 4: openapi·문서** — `cd apps/api && PYTHONPATH=. python scripts/export_openapi.py`. `notifications.md`(요구사항)의 "폰 푸시는 범위 밖"을 "푸시는 `docs/superpowers/specs/2026-11-05-push-notifications-design.md` 의 단계로 연결한다"로 고치고 1단계 범위를 적는다. `docs/features/notifications.md` 에 API 두 묶음 추가. ADR: `git fetch` 뒤 `docs/adr/README.md` 최대 번호+1 로 "푸시는 Expo 푸시 서비스(→FCM)를 거친다, 소통 메시지 푸시는 `full` 기본, 알림함 비저장"을 기록하고 README 표에 한 줄 추가.
- [ ] **Step 5: 전체 확인** — `pytest app/features/notifications tests -q -k "notif or push"`, `ruff check . && ruff format --check .`, `alembic heads` 1개.
- [ ] **Step 6: 커밋·푸시** — `feat: 푸시 토큰 등록·해제 API와 설계 문서 추가`, 브랜치 `feature/seungdeuk-push-server-a` 를 푸시(PR 은 사용자가 요청할 때).

---

## PR 2 — 서버 B: 발송

### Task 4: 차단 규칙과 메시지 만들기 (순수 함수)

**Files:**
- Create: `apps/api/app/shared/push.py`
- Test: `apps/api/tests/test_push_rules.py`

**Interfaces:**
- Produces:
  - `in_quiet_hours(now: datetime, start: time|None, end: time|None) -> bool` — `ZoneInfo("Asia/Seoul")` 로 환산한 시각이 `[start, end)` 안이면 True. `start > end`(자정 넘김)도 처리. 둘 중 하나라도 None 이면 False.
  - `PushPlan = TypedDict(user_id, token, title, body, data)`; `plan_recipients(db, *, user_ids: Iterable[str], kind: str, title: str, body: str|None, data: dict, now: datetime) -> list[PushPlan]` — 사용자마다 설정(없으면 기본)에서 `enabled` 가 꺼졌거나 `kind in muted_kinds` 이거나 `in_quiet_hours` 이면 제외하고, 남은 사용자의 모든 토큰마다 한 줄. 같은 (user_id, token) 은 한 번.
- Consumes: `PushToken`, `PushSetting` (Task 1).

- [ ] **Step 1: 시험 작성** — `test_quiet_hours_same_day`(09:00~18:00: 12:00 True, 20:00 False), `test_quiet_hours_cross_midnight`(22:00~07:00: 23:30·06:30 True, 12:00 False, 07:00 False), `test_quiet_hours_none`, `test_plan_skips_disabled_muted_and_quiet`, `test_plan_one_row_per_device`(기기 2대 → 2줄), `test_plan_default_settings_when_no_row`. DB 가 필요한 것은 `SessionLocal()` 로 직접 줄을 넣는다.
- [ ] **Step 2: 실행해서 실패 확인** — FAIL(모듈 없음).
- [ ] **Step 3: 구현** — 위 두 함수. 시각은 UTC 인자를 `ZoneInfo("Asia/Seoul")` 로 바꿔 비교한다(앱 시간대가 서울 하나라는 가정 — 설계서 열린 질문에 같은 가정을 적는다).
- [ ] **Step 4: 통과 확인** — pytest PASS, ruff 통과.
- [ ] **Step 5: 커밋** — `feat: 푸시 차단 규칙과 받는 사람 계산 추가`.

### Task 5: 발송기와 `notify()` 연결, `push_only()`

**Files:**
- Modify: `apps/api/app/shared/push.py`, `apps/api/app/shared/notifications.py`(`notify()` 끝부분), `apps/api/app/shared/config.py`(`push_enabled: bool = False`, `push_expo_access_token: str = ""`), `apps/api/.env.example`, `docs/features/notifications.md`
- Test: `apps/api/tests/test_push_send.py`

**Interfaces:**
- Consumes: `plan_recipients` (Task 4), `settings.push_enabled`.
- Produces:
  - `queue_push(db: Session, *, user_ids: Iterable[str], kind: str, title: str, body: str|None, data: dict) -> None` — `db.info.setdefault("pending_push", []).append(...)` 만 한다(차단 규칙은 발송 직전에 적용). `push_enabled` 가 꺼져 있으면 아무것도 쌓지 않는다.
  - `push_only(db, *, user_ids, kind, title, body, data) -> None` — `queue_push` 의 공개 이름(알림함 저장 없음, 2단계 소통용).
  - 세션 `after_commit` 리스너(모듈 임포트 때 한 번 등록): `db.info.pop("pending_push", [])` 를 꺼내 `_submit(_deliver, items)` 로 넘긴다. 롤백(`after_rollback`)이면 목록을 비운다.
  - `_submit(fn, *args) -> None` — 모듈 수준 `ThreadPoolExecutor(max_workers=2)` 로 실행(시험은 이 함수를 즉시 실행으로 바꾼다).
  - `_deliver(items) -> None` — 새 `SessionLocal()` 로 `plan_recipients` 계산 → 100개씩 `httpx.post("https://exp.host/--/api/v2/push/send", json=[{"to","title","body","data","channelId":"default","priority":"high","sound":"default"}...], timeout=5)`(access token 이 있으면 `Authorization: Bearer`) → 응답 `data[i].details.error == "DeviceNotRegistered"` 인 토큰을 `push_tokens` 에서 삭제하고 커밋. 모든 예외를 삼키고(로그는 예외 종류와 토큰 앞 6자리만).
  - `notify()` 는 알림을 `db.add` 한 뒤 같은 받는 사람 집합(구성원 확인·본인 제외를 통과한 사람)으로 `queue_push(..., kind=kind, title=title, body=None, data={"notification_id": <row.id>, "kind": kind, "event": event, "target_type": target_type, "target_id": target_id})` 를 부른다. `queue_push` 의 어떤 오류도 `notify()` 를 실패시키지 않는다.

- [ ] **Step 1: 시험 작성** — `httpx.post` 를 가짜로 바꾸고 `push._submit` 을 즉시 실행으로 바꾼다. `test_push_sent_only_after_commit`(커밋 전 호출 0회, 커밋 후 1회), `test_no_push_on_rollback`, `test_push_title_only_no_body`(`json` 에 `body` 가 None, 금액·장소 문자열 없음), `test_actor_not_pushed`, `test_two_devices_two_messages`, `test_device_not_registered_deletes_token`, `test_expo_failure_is_swallowed`(타임아웃·500·깨진 JSON 에서 호출 쪽 성공, 토큰 유지), `test_disabled_flag_sends_nothing`, `test_missing_push_tables_does_not_break_notify`(푸시 테이블을 지운 DB 에서 `notify()` 는 알림함만 저장), `test_personal_notification_pushed`(`group_id=None` 고객센터).
- [ ] **Step 2: 실행해서 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스대로. `notify()` 변경은 기존 savepoint 블록 밖, 반환 직전에 한 번만. 기존 알림 시험이 깨지지 않게 `push_enabled` 기본 false 라 아무것도 쌓이지 않는다.
- [ ] **Step 4: 기존 범위 회귀** — `pytest app/features/notifications app/features/admin tests/test_notifications_notify.py tests/test_push_send.py tests/test_push_rules.py -q`, `ruff check . && ruff format --check .`. (가족 그룹 범위의 기존 실패 48개는 이전과 같아야 한다 — 같은 조건으로 전후 비교.)
- [ ] **Step 5: 문서·커밋** — `.env.example` 에 `PUSH_ENABLED=false`, `PUSH_EXPO_ACCESS_TOKEN=` 설명 추가. `docs/features/notifications.md` 에 발송 규칙 요약. 커밋 `feat: Expo 푸시 발송과 notify 연결 추가`, 브랜치 `feature/seungdeuk-push-server-b`(서버 A 병합 뒤 `release/1.2` 에서 새로 따거나 서버 A 위에 쌓는다).

---

## PR 3 — 앱

### Task 6: 의존성·설정·순수 도우미

**Files:**
- Modify: `apps/mobile/package.json`(+lock, `npx expo install expo-notifications` 가 만든 그대로), `apps/mobile/app.json`(`plugins` 에 `expo-notifications` 추가, 알림 색 `color` 는 `theme` 의 포인트 색과 같은 hex), `apps/mobile/src/features/notifications/api.js`
- Create: `apps/mobile/src/features/notifications/push.js`
- Test: `apps/mobile/tests/push.test.js`

**Interfaces:**
- Produces(`api.js`): `registerPushToken({ token, platform, deviceLabel }) -> Promise<void>`(`PUT /notifications/push-token`), `unregisterPushToken(token) -> Promise<void>`(`DELETE`), `getPushSettings() -> Promise<{enabled, preview_mode, muted_kinds, quiet_start, quiet_end}>`, `savePushSettings(settings) -> Promise<same>`.
- Produces(`push.js`, 순수): `isUsableToken(token: unknown) -> boolean`(서버와 같은 형식 규칙), `routeForPush(data: {kind?: string} | null | undefined) -> string`(항상 `"/notifications"`, 2단계에서 소통 방으로 확장), `PUSH_CHANNEL_ID = "default"`.

- [ ] **Step 1: 시험 작성** — `isUsableToken("ExponentPushToken[abc]") === true`, `"abc"`·빈 문자열·`null` 은 false, `routeForPush(undefined) === "/notifications"`.
- [ ] **Step 2: 실행해서 실패 확인** — `npm test` → FAIL(모듈 없음).
- [ ] **Step 3: 구현** — `npx expo install expo-notifications`, `app.json` 플러그인, `api.js`·`push.js`(JSDoc 필수).
- [ ] **Step 4: 통과 확인** — `npm test`, `npx eslint src tests` 오류 없음.
- [ ] **Step 5: 커밋** — `feat: expo-notifications 추가와 푸시 API·도우미`.

### Task 7: 토큰 등록·해제와 알림 탭 이동

**Files:**
- Create: `apps/mobile/src/features/notifications/usePushRegistration.js`
- Modify: `apps/mobile/src/shared/auth/AuthProvider.js`(로그인 뒤 등록 호출, `signOut` 에서 서버 로그아웃 전에 해제), `apps/mobile/src/app/_layout.js`(수신 핸들러 설정 한 번)
- Test: `apps/mobile/tests/push.test.js` 에 추가

**Interfaces:**
- Consumes: Task 6 의 `api.js`·`push.js`, `useAuth()`.
- Produces: `usePushRegistration() -> void`(`status === "authenticated"` 일 때만, 웹이면 아무것도 안 함: 안드로이드 채널 `default` 생성 → 권한 요청 → `getExpoPushTokenAsync({ projectId: Constants.expoConfig.extra.eas.projectId })` → `registerPushToken`. 거절·실패는 삼키고 마지막 토큰은 모듈 변수에 보관), `releasePushToken() -> Promise<void>`(보관한 토큰이 있으면 `unregisterPushToken`, 실패해도 던지지 않음). 앱이 켜져 있을 때 푸시는 배너로 보이게 `Notifications.setNotificationHandler` 를 `_layout.js` 에서 한 번 설정하고, 푸시를 누르면 `router.push(routeForPush(data))`.

- [ ] **Step 1: 시험 작성** — 훅 자체는 시험하지 않는다. 대신 `push.js` 에 `shouldRegister({ status, platform }) -> boolean`(`status === "authenticated"` 이고 `platform !== "web"`)을 순수 함수로 두고 `test_should_register_only_when_authenticated_native` 를 작성한다.
- [ ] **Step 2: 실행해서 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — `usePushRegistration`·`releasePushToken`, `AuthProvider.signOut` 에서 `await releasePushToken()`(예외 무시) 후 기존 서버 로그아웃, `_layout.js` 의 핸들러·탭 이동, 첫 권한 요청 전 안내 문구 "알림에 메시지 내용이 보일 수 있어요. 마이 > 알림 설정에서 바꿀 수 있어요"(`features/notifications/messages.js` 에 둔다).
- [ ] **Step 4: 통과 확인** — `npm test`, `npx eslint src tests`.
- [ ] **Step 5: 커밋** — `feat: 푸시 토큰 등록·해제와 푸시 탭 이동`.

### Task 8: 마이 > 알림 설정 화면

**Files:**
- Create: `apps/mobile/src/features/notifications/screens/PushSettingsScreen.js`, `apps/mobile/src/app/push-settings.js`
- Modify: `apps/mobile/src/features/more/screens/MoreScreen.js`(메뉴 한 줄 "알림 설정"), `docs/features/{notifications,more}.md`
- Test: `apps/mobile/tests/push.test.js` 에 추가

**Interfaces:**
- Consumes: `getPushSettings`·`savePushSettings` (Task 6).
- Produces: 화면 — 전체 켜기·끄기, 분류별 켜기·끄기(일정·정산·돌봄·가족·기록·고객센터, `notifications/kinds.js` 의 `KIND_META` 사용), 소통 메시지 내용 표시 선택(내용 보이기 `full` / 보낸 사람만 `sender` / 숨기기 `hidden`), 방해금지 시작·끝 시간(없음 가능). 순수 함수 `toggleKind(muted: string[], kind: string) -> string[]` 를 `push.js` 에 둔다.

- [ ] **Step 1: 시험 작성** — `test_toggle_kind_adds_then_removes`, `test_toggle_kind_does_not_mutate_input`.
- [ ] **Step 2: 실행해서 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — 화면과 라우트 파일(얇게 조립만), 마이 메뉴 항목. 저장 실패는 화면 안 안내문으로 보여 준다.
- [ ] **Step 4: 통과·확인** — `npm test`, `npx eslint src tests`. 로컬 웹에서 화면이 열리고 저장되는지 서버(8010)와 함께 눈으로 확인한다.
- [ ] **Step 5: 커밋** — `feat: 마이 알림 설정 화면 추가`.

### Task 9: 개발용 빌드로 푸시 확인 (사람과 함께)

**Files:** 없음(확인 절차). 필요한 메모는 `docs/features/notifications.md` 에 한 단락.

- [ ] **Step 1: FCM 자격 준비(사람)** — Firebase 프로젝트를 만들고(소유자는 팀 결정), 안드로이드 앱 `com.kangminhun.gabee` 를 등록해 FCM 서비스 키를 `eas credentials` 로 EAS 에 올린다. 서버에는 비밀 키를 두지 않는다.
- [ ] **Step 2: 빌드** — `cd apps/mobile && eas build --profile development --platform android` 로 APK 를 만들어 팀 폰과 BlueStacks 에 설치한다.
- [ ] **Step 3: 서버 켜기** — `PUSH_ENABLED=true` 로 API 를 켜고 Metro 는 `EXPO_OFFLINE=1`.
- [ ] **Step 4: 확인** — 로그인 → 권한 허용 → 토큰이 `push_tokens` 에 생김 → 시험 계정 둘로 같이해요를 보내 푸시가 오는지, 앱을 닫은 상태에서도 오는지, 푸시를 누르면 알림함이 열리는지, 설정에서 일정을 끄면 안 오는지, 방해금지 시간에 안 오는지 확인한다. BlueStacks 에서 토큰 발급이 안 되면 실제 폰으로 확인하고 그 사실을 문서에 적는다.
- [ ] **Step 5: 기록** — 결과(되는 것·안 되는 것)를 `docs/features/notifications.md` 에 사실대로 적는다.
