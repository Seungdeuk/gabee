# 찰칵! 탐정단 가비 추천 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 탐정단 문제 내기에서 서버가 가족 사진 1~2개 + 흔한 사진 1~2개로 카드 3개(질문·보기·정답·확대 위치)를 만들어 주는 "가비 추천"을 추가한다.

**Architecture:** 서버는 `photo_rec.py`(조립)·`photo_rec_questions.py`(월·일정·내용 질문)·`photo_rec_store.py`(저장·정리) 세 모듈이 맡는다. 후보 사진은 팀원의 `confirmed_photo_ids` 로 거르고, 구성은 저장하지 않고 가족·사용자·날짜 시드로 매번 같은 방식으로 고른다. AI 는 동의한 가족의 내용 질문 한 장당 한 번만 `ai_guard.run` 아래에서 부른다. 앱은 이게 뭐게 추천(`DrawRecommend`)과 같은 모양의 카드를 탐정단 만들기 화면에 붙이고, "이 문제로 쓰기"는 `rec_id` 로 기존 `POST /play/photos` 를 보낸다.

**Tech Stack:** FastAPI·SQLAlchemy·Alembic·pytest(서버 `gabee/apps/api`), React Native·Expo·node:test(앱 `gabee/apps/mobile`), Anthropic Haiku 5.5(`app.shared.llm.client`).

**Spec:** `C:\Users\403\Documents\prj\photo-rec\design.md`

## Global Constraints
- 작업은 최신 `origin/release/1.3` 에서 새 브랜치(이름은 사용자가 정함)로 시작한다. 커밋 메시지도 사용자가 정한다 — 커밋 단계마다 사용자에게 메시지를 확인받고 커밋한다.
- 후보 사진 = 가족 전체방 사진 중 `photo_check_repository.confirmed_photo_ids` 에 든 것(상태 `photo` 만, fail-closed). 후보에서 그 가족이 **최근 14일 안에 보낸 것**(`play_photos.rec_id`)은 뺀다. 14일은 상수 `RECENT_DAYS=14`.
- 카드는 3개(`ASK_COUNT=3`): 가족 사진은 후보 2장 이상이면 2개·1장이면 1개·0장이면 0개(`FAMILY_MAX=2`), 나머지는 흔한 사진(1~3개). 오늘(한국 시간) 이 추천으로 보낸 문제(`rec_id` 있는 것)가 3개이면 추천은 빈 목록 + `used_up`.
- 구성은 저장·캐시하지 않는다. 가족 사진은 `rec_rng(group_id, user_id, today)`, 흔한 사진도 같은 시드로 고른다. `ai_guard.run` 의 캐시는 쓰지 않는다(동의 꺼진 가족을 403으로 막기 때문). `ai_guard.run` 은 내용 질문 AI 호출에만 쓴다.
- 문제 종류: 촬영 월(`taken_at` 있는 사진만, 한국 시간, 보기 월 4개), 일정 맞추기(촬영일과 같은 날의 공동 일정이 정확히 하나일 때만, 제목·장소가 20자를 넘으면 건너뜀), 내용 질문(AI 동의 가족만, 사진 한 장당 AI 한 번). 사진 한 장당 문제는 하나(`attachment_id` 유일).
- AI 에는 사진(`ingest/photo_judge.to_judge_jpeg` 로 EXIF 제거·1024px)만 보낸다. 일정·가족 정보는 보내지 않는다. 가족이 AI 동의를 끄면 그 가족의 내용 질문 행을 지운다. 채팅 사진을 지우면 그 사진의 행도 함께 지운다.
- 질문 20자 이하, 보기 2~4개(각 1~20자, 중복 없음), 정답은 보기 중 하나, 확대 위치 0~1, 확대 배율은 4·6·8·16·32(`PHOTO_ZOOMS`) — 기본 8(탐정단 `play_photos` 와 같은 한도).
- 실패·한도·동의 꺼짐은 오류가 아니라 200 + `state`. AI 동의가 꺼졌거나 한도를 다 써도 월·일정 문제와 흔한 사진으로 3개를 채운다. 시험은 실제 AI 를 부르지 않고 `llm.complete_json` 을 가짜로 바꾼다(`test_draw_rec.py` 방식). 로컬 시험은 바뀐 부분과 연결된 것만 돌린다(전체 pytest 는 CI).
- 공용 DB 마이그레이션은 DB 담당자가 적용한다(PR 본문에 적는다). **팀원의 `chat_photo_checks`·`chat_photo_check_events` 마이그레이션(`d7a41c9e5b02` 등)이 먼저 적용돼 있어야 한다.** Expo·폰 접속 문제는 기록하지 않는다.

## Review Focus
1. 예전 사진뿐이라 후보가 0장(판별 줄 없음) → 흔한 사진 3개로 `ok` — Task 5
2. AI 동의 꺼진 가족 → AI 호출 0번, 월·일정 문제 + 흔한 사진으로 3개, 저장돼 있던 그 가족의 내용 질문 행은 보이지 않고 지워짐 — Task 1·5
3. 촬영 시각이 없는 사진·같은 날 일정이 둘 이상·일정 제목이 20자 초과 → 그 종류는 건너뛴다(오답을 만들지 않음) — Task 2
4. 추천 뒤 업로더가 사진을 타임라인에서 빼 `excluded` 가 됨 → "이 문제로 쓰기" 전송이 409 — Task 7
5. 같은 가족이 14일 안에 보낸 사진·흔한 사진이 다시 나오지 않고, 시드 50장은 하루 3개 14일(42개)로 바닥나지 않는다 — Task 4·5

---

### Task 1: 사진 문제 저장 표·`rec_id` 칸·정리(삭제·동의 끔)

**Files:**
- Modify: `apps/api/app/features/play/models.py`(`PlayPhotoRec` 추가, `PlayPhoto.rec_id` 칸), `apps/api/app/shared/ai_guard.py`(동의를 끌 때 부르는 정리 등록), `apps/api/app/features/family_chat/repository.py`(채팅 사진 삭제 시 이 표의 행도 지움 — 이 파일은 `family_chat/repository.py` 175~177행의 첨부 삭제 근처)
- Create: `apps/api/alembic/versions/<새 id>_play_photo_rec.py`(expand 전용, `down_revision` 은 `alembic heads` 가 가리키는 현재 head), `apps/api/app/features/play/photo_rec_store.py`
- Test: `apps/api/app/features/play/tests/test_photo_rec_store.py`

**Interfaces:**
- Produces: 모델 `PlayPhotoRec`(테이블 `play_photo_rec`; 칸: `id` 문자열(32) 기본키, `group_id` 문자열(32) NULL 가능·색인·`groups.id` ON DELETE CASCADE, `source` SmallInteger[1 가족 앨범, 3 흔한 사진 시드, 4 흔한 사진 자동], `attachment_id` 문자열(32) NULL 가능·유일·`message_attachments.id` ON DELETE CASCADE, `image` LargeBinary NULL 가능(흔한 사진만, JPEG), `kind` SmallInteger[1 월, 2 일정, 3 내용], `usable` Boolean 기본 참, `question` 문자열(20), `options` JSON, `answer` 문자열(4, `play_photos` 와 같은 비트 글자), `box_x`·`box_y` Float, `zoom` SmallInteger, `prompt_version` 문자열(8), `created_at` 시각); `PlayPhoto.rec_id`(문자열(32) NULL 가능, FK 없음).
- `photo_rec_store`: `row_for_attachment(db, attachment_id) -> PlayPhotoRec | None`; `add_row(db, **fields) -> PlayPhotoRec`; `sent_rec_ids(db, group_id, now, days=14) -> set[str]`(그 가족이 최근 `days` 일 안에 보낸 `rec_id`, `play_items` 의 가족·시각과 `play_photos.rec_id` 조인); `sent_today(db, group_id, user_id, today_start) -> int`(오늘 이 사용자가 이 추천으로 보낸 문제 수); `purge_content_rows(db, group_id) -> int`(그 가족의 `kind=3` 행 삭제, 지운 수).
- `ai_guard.on_disabled(callback: Callable[[Session, str], None]) -> None`(등록) — `set_enabled(..., False)` 가 등록된 콜백을 `(db, group_id)` 로 부른다. `photo_rec_store` 모듈 끝에서 `purge_content_rows` 를 등록한다.

- [ ] **Step 1: 실패하는 시험** — `test_attachment_unique_one_row_per_photo`(같은 `attachment_id` 로 두 번 넣으면 `IntegrityError`), `test_cascade_on_attachment_delete`(채팅 메시지를 지우면 그 첨부의 `PlayPhotoRec` 행도 없어짐, SQLite 에서는 삭제 코드가 처리), `test_purge_content_rows_on_ai_disable`(`ai_guard.set_enabled(db, g, u, False)` 가 그 가족의 `kind=3` 행만 지우고 `kind=1`·`kind=2`·다른 가족·공통 행은 그대로), `test_sent_rec_ids_within_14_days`(13일 전에 `rec_id` 로 보낸 것은 나오고 15일 전 것·다른 가족 것은 안 나옴), `test_sent_today_counts_only_this_user_today`.
- [ ] **Step 2: 실패 확인** — `cd apps/api && .venv/Scripts/python.exe -m pytest app/features/play/tests/test_photo_rec_store.py -q` → 모듈 없음으로 FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. `ai_guard.set_enabled` 는 `enabled` 가 거짓일 때만 콜백을 부른다(기존 `AiResultCache` 삭제는 그대로). 채팅 사진 삭제 코드(`repository.py` 의 첨부 `db.delete`)는 `chat_photo_checks` 줄을 지우는 같은 자리에서 `PlayPhotoRec` 행도 지운다(play 모델을 import 하지 말고 `app/shared` 의 삭제 후크가 없으면 `family_chat` 이 import 하지 않도록 `ai_guard.on_disabled` 와 같은 방식의 `chat_library` 등록 후크를 쓴다 — 기존 `chat_library` 의 `_on_removed` 방식을 읽고 따른다).
- [ ] **Step 4: 통과 확인** — 시험 + `.venv/Scripts/python.exe scripts/check_alembic_migrations.py`·`check_schema_matches_models.py` → PASS. 로컬 DB(`127.0.0.1:5433`)에서 `alembic upgrade head` 후 `downgrade -1` 로 되돌려 보기.
- [ ] **Step 5: 커밋**(메시지는 사용자가 정함).

### Task 2: AI 없는 문제(촬영 월·일정 맞추기)

**Files:**
- Create: `apps/api/app/features/play/photo_rec_questions.py`
- Test: `apps/api/app/features/play/tests/test_photo_rec_questions.py`

**Interfaces:**
- Consumes: `quiz_rec` 의 일정 조회 규칙(`Event`, `current_when`, 공동 일정 = `origin_id` 로 가리켜진 원본 한 건씩, 부탁에서 생긴 일정 제외)을 같은 질의로 재사용하되 날짜 범위는 촬영일 하루. `timeutil.local_tz`.
- Produces: `@dataclass(frozen=True) PhotoQuestion(kind: int, question: str, options: list[str], answer_index: int, zoom: int = 8)`(확대 위치는 호출한 쪽이 정함); `month_question(taken_at: datetime | None, rng: random.Random) -> PhotoQuestion | None`; `event_question(db: Session, group_id: str, taken_at: datetime | None, rng: random.Random) -> PhotoQuestion | None`; `events_on(db: Session, group_id: str, day: date) -> list[Event]`(그날 공동 일정, 지워진 것 제외).

- [ ] **Step 1: 실패하는 시험** — `test_month_question_shape`: `taken_at` 2026-03-05 12:00 UTC(→ 한국 03-05) 이면 질문 `"이 사진은 몇 월에 찍었을까요?"`, 보기 4개가 `"N월"` 형식·서로 다름·`"3월"` 포함, `options[answer_index]=="3월"`. `test_month_uses_local_time`: UTC 2026-02-28 20:00 은 한국 3월 1일이라 정답 `"3월"`. `test_month_none_when_no_taken_at`: `None` 이면 `None`(올린 날로 대신하지 않음). `test_event_question_single_event`: 그날 공동 일정이 정확히 하나("제주 여행")이면 질문 `"이 사진은 어느 일정 때 찍었을까요?"`, 보기 3~4개(정답 제목 + 같은 가족의 다른 일정 제목, 없는 만큼은 보기를 줄여 최소 2개), 정답이 그 제목. 보기가 2개도 안 나오면 `None`. 장소가 있고 제목이 일반적이면 질문이 `"어디서 찍었을까요?"`(보기 = 장소들)로 바뀌는 시험은 일정에 장소가 있을 때 정답이 그 장소. `test_event_skipped_when_ambiguous_or_long`: 같은 날 일정이 둘이면 `None`, 제목(또는 장소 질문이면 장소)이 20자를 넘으면 `None`, 부탁에서 생긴 일정만 있으면 `None`, 지운 일정은 안 셈.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec_questions.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 시그니처. 월 오답 3개는 `rng.sample` 로 정답 월 제외 11개 중, 일정 오답은 그 가족의 공동 일정 제목(촬영일과 다른 날, 같은 제목·20자 초과 제외)에서 `rng.sample`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS. 커밋(메시지는 사용자가 정함).

### Task 3: 내용 질문 AI 호출(검증·프롬프트·한도 설정)

**Files:**
- Modify: `apps/api/app/shared/config.py`(`ai_play_photo_rec_cooldown_seconds=5`, `ai_play_photo_rec_max_calls_per_user_per_day=3`, `ai_play_photo_rec_max_calls_per_group_per_day=5`)
- Create: `apps/api/app/features/play/photo_rec_ai.py`
- Test: `apps/api/app/features/play/tests/test_photo_rec_ai.py`

**Interfaces:**
- Consumes: `ingest.photo_judge.to_judge_jpeg(data: bytes) -> bytes`; `llm.complete_json`(이미지 블록을 받는 호출은 `doc_ai` 의 이미지 블록 호출 방식(`_call`)을 읽고(예전 `classify_photo` 는 ADR 0025 로 지웠다), `complete_json` 에 이미지 입력이 없으면 같은 방식으로 `client.py` 에 `images: list[bytes] | None = None` 선택 인자를 더한다).
- Produces: 상수 `FEATURE="play_photo_rec"`, `PROMPT_VERSION="v1"`, `MAX_TOKENS=4000`, `TIMEOUT=60.0`, `EFFORT="low"`; `@dataclass ContentResult(usable: bool, question: str, options: list[str], answer_index: int, box_x: float, box_y: float, input_tokens: int, output_tokens: int, model: str)`; `validate_content(raw: object) -> dict | None`(스키마·20자·보기 2~4·중복 없음·정답 위치·0~1); `content_question(jpeg: bytes) -> ContentResult`(검증에 실패하면 한 번 더, 그래도 안 되면 `ContentFailed(ValueError)` 에 토큰 수를 담아 던짐); `register_limits() -> None`(`ai_guard.register_bucket(FEATURE, Limits(...), (FEATURE,))`, 모듈 끝에서 호출).

- [ ] **Step 1: 실패하는 시험** — `test_validate_content_rules`: 질문 21자·보기 1개·보기 5개·같은 보기·`answer_index` 범위 밖·`box_x` 1.2 는 `None`, 정상은 그대로, `usable=false` 는 질문 없이도 통과. `test_content_question_retries_once`: 가짜 `complete_json` 이 첫 호출에 나쁜 값, 둘째에 정상을 주면 정상 결과·호출 2번, 둘 다 나쁘면 `ContentFailed`. `test_prompt_rules`: 프롬프트에 "사람 얼굴이 크게"·"글자·서류"는 `usable=false`, 질문 20자, 보기 2~4개, 가족 이름·일정이 없음, 요청에 이미지 한 장만 있음. `test_limits_registered`: `ai_guard` 에 `play_photo_rec` 버킷이 이 설정 값으로 등록됨.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec_ai.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 시그니처. 시스템 프롬프트: 사진에 보이는 것만 묻는 선택식 문제 한 개, 사람 얼굴이 크게 나오거나 글자·서류면 `usable=false`, 확대할 흥미로운 위치(0~1)를 `box_x`·`box_y` 로, 질문 20자·보기 2~4개(각 20자 이하)·정답은 보기 중 하나(`answer_index`)·사진에서 분명히 확인되는 사실만. 출력 스키마는 `{"usable": bool, "question": str, "options": [str], "answer_index": int, "box_x": float, "box_y": float}`(`additionalProperties: False`).
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS. 커밋(메시지는 사용자가 정함).

### Task 4: 흔한 사진 풀(시드 넣기·고르기)

**Files:**
- Create: `apps/api/scripts/seed_photo_rec.py`, `apps/api/app/features/play/photo_rec_pool.py`
- Test: `apps/api/app/features/play/tests/test_photo_rec_pool.py`

**Interfaces:**
- Consumes: Task 1 `PlayPhotoRec`, `photo_rec_store.sent_rec_ids`.
- Produces: `pool_rows(db: Session, exclude_ids: set[str]) -> list[PlayPhotoRec]`(`group_id IS NULL` 이고 `usable` 인 행, `id` 오름차순, `exclude_ids` 제외); `pick_common(rows: list[PlayPhotoRec], n: int, rng: random.Random) -> list[PlayPhotoRec]`(중복 없이 최대 `n`개, 행이 모자라면 있는 만큼); 시드 스크립트 `python scripts/seed_photo_rec.py <폴더>` — 폴더의 `seed.json`(`[{"key":"001","image":"img/001.jpg","kind":3,"question":"...","options":[...],"answer_index":0,"box_x":0.5,"box_y":0.4,"zoom":8}, ...]`)을 읽어 행 `id=f"seed{key}"`, `source=3`, `image`=JPEG 바이트로 **멱등**으로 넣는다(있으면 건너뜀, `--update` 면 덮어씀).

- [ ] **Step 1: 실패하는 시험** — `test_pick_common_distinct_and_bounded`: 행 10개에서 3개 → 서로 다른 3개, 행 2개에서 3개 → 2개, 같은 `rng` 시드는 같은 결과. `test_pool_excludes_sent_and_unusable`: `exclude_ids` 에 든 행과 `usable=False`·`group_id` 있는 행은 안 나옴. `test_seed_script_is_idempotent`: 임시 폴더(`seed.json` + 작은 JPEG 2장)로 두 번 돌려도 행이 2개, `--update` 로 질문이 바뀜, 이미지가 없는 항목은 오류로 멈춤. `test_pool_50_seeds_survive_14_days`: 50개 행에서 14일 동안 매일 `pick_common` 3개를 보내(`exclude_ids` 에 누적) 마지막 날에도 3개를 고를 수 있음(14×3=42<50).
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec_pool.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 스크립트는 `apps/api/scripts/` 의 기존 스크립트(DB 접속은 `app.shared.db.SessionLocal`)와 같은 방식. 시드 행은 `attachment_id`·`group_id` 가 비고 `prompt_version` 은 `"seed"`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS, `ruff check app scripts` 통과. 커밋(메시지는 사용자가 정함).

### Task 5: 추천 조립(`recommend`)

**Files:**
- Create: `apps/api/app/features/play/photo_rec.py`
- Modify: `apps/api/app/features/play/photo_rec_store.py`(후보 조회 함수 추가)
- Test: `apps/api/app/features/play/tests/test_photo_rec.py`

**Interfaces:**
- Consumes: Task 1 `photo_rec_store.*`, `PlayPhotoRec`; Task 2 `month_question`, `event_question`; Task 3 `content_question`, `ContentFailed`, `FEATURE`; Task 4 `pool_rows`, `pick_common`; `photo_check_repository.confirmed_photo_ids(db, group_id, attachment_ids) -> set[str]`; `ai_guard.is_enabled`, `ai_guard.run`; `quiz_rec._state_of`·상태 문자열(`OK·USED_UP·PREPARING·COOLDOWN·FAILED·AI_OFF`); `family_chat.photo_service.attachment_files(attachment) -> tuple[Path, Path] | None`(원본 경로로 사진 바이트를 읽는다).
- Produces: 상수 `ASK_COUNT=3`, `FAMILY_MAX=2`, `RECENT_DAYS=14`, `CANDIDATE_LIMIT=200`; `rec_rng(group_id: str, user_id: str, today: date) -> random.Random`(sha256 시드); `family_candidates(db, group_id, now) -> list[MessageAttachment]`(가족 전체방 이미지 첨부를 최근순 `CANDIDATE_LIMIT` 개 읽어 `confirmed_photo_ids` 로 거르고 `sent_rec_ids` 에 든 행·`usable=False` 행의 첨부는 뺌); `compose(family_cards: list[dict], common_cards: list[dict], total: int = 3, family_max: int = 2) -> list[dict]`(순수 함수: 가족 카드 `min(len, family_max)` 개 + 나머지를 흔한 카드로, 가족 카드가 아무리 많아도 흔한 카드가 최소 1개 들어가도록 `total - family_max` 이상을 확보, 항목 순서는 가족 → 흔한); `recommend(db: Session, user: User, group_id: str, rng: random.Random | None = None) -> dict` → `{"state": ..., "items": [{"id", "kind", "source", "question", "options", "answer_index", "box_x", "box_y", "zoom", "image_url"}]}`.
- 카드의 `kind` 는 `"month"|"event"|"content"`, `source` 는 `"album"|"common"`, `image_url` 은 `/play/photo/recommendations/{id}/image`.

- [ ] **Step 1: 실패하는 시험**(가짜 `llm.complete_json`, 임시 DB):
  - `test_compose_mixes_family_and_common`: 가족 3·흔한 5 → 가족 2(앞)+흔한 1, 가족 1·흔한 5 → 1+2, 가족 0·흔한 5 → 흔한 3, 흔한이 1개뿐이고 가족 0 → 1개, 모두 `id` 중복 없음.
  - `test_recommend_zero_candidates_returns_common` (Review Focus 1): 판별 줄이 없는 사진만 있는 가족 → 흔한 사진 3개, `state=="ok"`, AI 호출 0번.
  - `test_recommend_ai_off_uses_no_ai` (Review Focus 2): 동의 꺼진 가족에 확인된 사진 2장(일정이 있는 날·촬영 시각만 있는 날) → AI 호출 0번, 항목은 일정·월 문제 + 흔한 1개, `state=="ok"`, 저장돼 있던 그 가족의 `kind=3` 행이 있어도 항목에 안 나옴.
  - `test_recommend_content_question_stored_and_reused`: 동의 가족, 월·일정이 불가능한 사진은 AI 내용 질문으로 한 번 부르고 행이 저장되며, 두 번째 `recommend` 는 AI 를 다시 부르지 않음. `usable=false` 면 그 사진은 이후 후보에서 빠짐(행은 `usable=False`).
  - `test_recommend_excludes_sent_14_days` (Review Focus 5): 사진 A 를 `rec_id` 로 13일 전에 보냈으면 후보에서 빠지고 15일 전이면 다시 나옴. 흔한 사진도 같은 규칙.
  - `test_recommend_user_seed_varies`: 후보가 5장일 때 같은 가족의 다른 사용자는 (대부분) 다른 가족 카드, 같은 사용자·같은 날은 항상 같음.
  - `test_recommend_done_for_today`: 오늘 이 사용자가 `rec_id` 로 보낸 문제가 3개이면 `{"state":"used_up","items":[]}`.
  - `test_recommend_ai_states`: 한도·쿨다운·다른 구성원이 만드는 중 → 해당 상태가 되지만 AI 가 필요 없는 카드(월·일정·흔한 사진)는 그대로 `items` 에 담긴다(`quiz_rec._state_of` 와 같은 매핑, 항목이 하나도 없을 때만 빈 목록).
  - `test_recommend_item_shape`: 위 키가 모두 있고 `options[answer_index]` 가 정답, 가족 이름·일정 원문은 AI 요청에 없음.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 가족 사진마다 종류를 `event_question` → (동의 가족이면) 내용 질문 → `month_question` 순서로 시도하고 첫 성공을 쓰되, 가족 사진 2개는 가능하면 서로 다른 종류가 되게 두 번째는 이미 쓴 종류를 뒤로 미룬다. 월·일정 문제는 확대 위치를 `rng` 로 가운데 쪽(0.25~0.75)에서 뽑고 행으로 저장한다(`kind` 1·2). 내용 질문 AI 호출은 한 번 열 때 필요한 사진만 모아 `ThreadPoolExecutor` 로 동시에 부르고(DB 는 이 스레드에서만 씀) 전체를 `ai_guard.run(feature=FEATURE, cache_key=<오늘 날짜 키, 캐시 읽기에 쓰이지 않게 호출마다 다르게>, call=..., cache_until=<지금>)` 아래에서 한 번의 호출 묶음으로 센다(`calls` 는 실제 부른 수). 동의가 꺼졌으면 `ai_guard.run` 을 부르지 않는다.
- [ ] **Step 4: 통과 확인** — `pytest app/features/play/tests/test_photo_rec.py app/features/play/tests/test_photo_rec_questions.py app/features/play/tests/test_draw_rec.py -q` → PASS(이게 뭐게 추천 시험이 그대로 통과해야 함). 커밋(메시지는 사용자가 정함).

### Task 6: 추천·이미지 API

**Files:**
- Modify: `apps/api/app/features/play/schemas.py`, `apps/api/app/features/play/router.py`, 레포 루트의 `docs/contracts/openapi.json`(이 레포가 쓰는 방식으로 다시 만들고 다른 경로가 바뀌면 되돌린다), 레포 루트의 `docs/features/play.md`
- Test: `apps/api/app/features/play/tests/test_photo_rec.py`

**Interfaces:**
- Produces: `GET /play/photo/recommendations` → `PlayPhotoRecOut(state: Literal["ok","used_up","preparing","cooldown","failed","ai_off"], items: list[PlayPhotoRecItem])`; `PlayPhotoRecItem(id: str, kind: Literal["month","event","content"], source: Literal["album","common"], question: str, options: list[str], answer_index: int, box_x: float, box_y: float, zoom: int, image_url: str)`; `GET /play/photo/recommendations/{rec_id}/image` → 사진 JPEG(가족 행: 그 가족 구성원만·공통 행: 로그인한 가족 구성원 누구나, 가족 행인데 다른 가족이면 404, 첨부가 사라졌으면 404).

- [ ] **Step 1: 실패하는 시험** — `test_photo_rec_endpoint`: 로그인한 구성원은 200 과 `state`·`items`(위 모양), 로그인 없으면 401. `test_rec_image_access`: 자기 가족 행은 200·`image/jpeg`, 다른 가족의 가족 행은 404, 공통 행은 어느 가족이든 200.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec.py -k "endpoint or image_access" -q` → FAIL.
- [ ] **Step 3: 구현** — `draw_recommendations` 와 같은 모양의 라우트. 가족 행의 이미지는 첨부 원본을 `media.make_photo_jpeg` 로 줄여 돌려준다. `docs/features/play.md` 에 탐정단 추천 절(카드 구성·문제 종류·14일·상태·한도·동의)을 추가하고 `openapi.json` 을 다시 만든다.
- [ ] **Step 4: 통과 확인** — `pytest app/features/play/tests/test_photo_rec.py -q` → PASS, `ruff check app` 통과. 커밋(메시지는 사용자가 정함).

### Task 7: "이 문제로 쓰기" 전송(`POST /play/photos` 확장)

**Files:**
- Modify: `apps/api/app/features/play/router.py`(`file` 선택, `rec_id` 선택), `apps/api/app/features/play/service.py`(`create_photo`: `source in (1,2,3)`, `rec_id` 처리), 레포 루트의 `docs/features/play.md`, `docs/contracts/openapi.json`
- Test: `apps/api/app/features/play/tests/test_photo_rec.py`, 기존 `test_photo_api.py`(탐정단 만들기 시험)가 그대로 통과해야 함

**Interfaces:**
- Consumes: Task 1 `photo_rec_store.sent_rec_ids`, `PlayPhotoRec`; 팀원 `photo_check_repository.confirmed_photo_ids`.
- Produces: `create_photo(db, user, group_id, *, data: bytes | None, source: int, ..., rec_id: str | None = None) -> PlayItemOut` — `rec_id` 가 있으면 `data` 는 비어 있어도 되고 서버가 그 행의 사진 바이트를 읽어 쓴다(가족 행: 첨부 원본, 공통 행: `image`). `source` 는 가족 행이면 1·공통 행이면 3 이어야 한다(요청 값과 달라도 서버가 행 기준으로 덮어쓴다). 새 오류: 409 `photo_not_available`(가족 행의 사진이 더는 `photo` 상태가 아님·첨부 없음·`usable` 거짓), 409 `rec_already_sent`(같은 가족이 이 `rec_id` 로 최근 14일 안에 보냄), 404 `rec_not_found`(없거나 다른 가족의 가족 행). `play_photos.rec_id` 를 채운다. 질문·보기·정답·확대·배율은 요청 값(출제자가 고친 값)을 쓴다.

- [ ] **Step 1: 실패하는 시험** — `test_send_with_rec_id_copies_image`(가족 행: 파일 없이 `rec_id` 만 보내면 201, 저장된 `play_photos.rec_id`·`source=1`·사진이 첨부 사진과 같음; 공통 행은 `source=3`), `test_send_blocked_when_photo_excluded` (Review Focus 4: 사이에 업로더가 `exclude_photo` 하면 409 `photo_not_available`), `test_send_blocked_when_recently_sent`(409 `rec_already_sent`, 15일 뒤에는 201), `test_send_rec_of_other_family_404`, `test_send_without_file_or_rec_id_400`, `test_send_with_both_rec_id_and_file_uses_file`(내 폰 사진으로 바꾼 경우 `rec_id` 를 보내지 않는 것이 앱 규칙이지만 둘 다 오면 파일과 `source=2` 로 처리하고 `rec_id` 는 버림), 기존 `source` 1·2 업로드는 그대로.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_photo_rec.py -k send -q` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 문제 내기 점수·하루 3건 한도·받는 사람 처리는 기존 `create_photo` 흐름 그대로.
- [ ] **Step 4: 통과 확인** — `pytest app/features/play/tests/test_photo_rec.py app/features/play/tests/test_photo_api.py -q` → PASS, `ruff check app` 통과. 커밋(메시지는 사용자가 정함).

### Task 8: 앱 데이터층(api·hook·시안·변환)

**Files:**
- Modify: `apps/mobile/src/features/playground/api.js`, `hooks.js`, `mock.js`, `adapt.js`, `apps/mobile/src/shared/api/`의 이미지 허용 목록(`/play/photo/recommendations/{id}/image` 경로를 `/play/items/{id}/image` 와 같은 방식으로 허용)
- Test: `apps/mobile/tests/playphotorec.test.js`(기존 놀이터 시험의 import 방식을 따른다)

**Interfaces:**
- Produces: `getPhotoRecs()`(= `apiFetch("/play/photo/recommendations")`, 요청 제한 시간이 15초 이상인지 `shared/api/client.js` 기본값을 확인하고 짧으면 이 호출에만 늘림); `usePhotoRecs()`(= `useDrawRecs` 와 같은 모양, 서버 주소가 없으면 `MOCK_PHOTO_RECS`); `photoRecView(recs) -> {items} | {items: [], notice: string, refresh: boolean}`; `createPhoto({..., recId})`(`recId` 가 있으면 `FormData` 에 `rec_id` 를 넣고 파일은 붙이지 않는다).

- [ ] **Step 1: 실패하는 시험** — `photoRecView`: `ok`+항목 있음 → 항목, `ok`+항목 없음·`used_up` → `refresh:false`+문구("오늘 추천은 여기까지예요 — 직접 내 보세요" 류, 비어 있지 않음), `failed`/`preparing`/`cooldown` → `refresh:true`, `ai_off` 는 항목이 있으면 항목(동의와 무관하게 나온다), `recs` 가 없으면 `failed` 취급. `createPhoto({recId:"abc", ...})` 가 만드는 폼에 `rec_id=abc` 가 있고 파일 필드가 없음.
- [ ] **Step 2: 실패 확인** — `cd apps/mobile && node --import ./tests/register-alias.mjs --test tests/playphotorec.test.js` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. `MOCK_PHOTO_RECS` 는 `{state:"ok", items:[...]}` 3개(월·일정·흔한 사진 각 하나, `image_url` 없이 색 블록).
- [ ] **Step 4: 통과 확인** — 위 명령 → PASS, `npx eslint src/features/playground tests` 통과. 커밋(메시지는 사용자가 정함).

### Task 9: 탐정단 만들기 화면에 "가비 추천" 전환

**Files:**
- Create: `apps/mobile/src/features/playground/components/photo/PhotoRecommend.js`
- Modify: `apps/mobile/src/features/playground/screens/PhotoCreateScreen.js`

**Interfaces:**
- Consumes: Task 8 `usePhotoRecs`, `photoRecView`, `createPhoto`; 기존 `DrawRecommend`(모양 참고), `AuthImage`, `PhotoStage`.
- Produces: `PhotoRecommend({ recs, index, onIndex, onPick, refreshing, onRefresh })` — 카드(사진 미리보기와 확대 위치 상자, 질문, 보기, 출처 알약 "가족 사진"/"가비가 고른 사진", `< n / N >`, "이 문제로 쓰기"), 상태·새로고침은 이게 뭐게 `DrawRecommend` 와 같은 모양.

- [ ] **Step 1: 구현** — `PhotoCreateScreen` 에 이게 뭐게(`DrawCreateScreen`)와 같은 "가비 추천 / 직접 내기" 전환을 추가하고 처음은 가비 추천. "이 문제로 쓰기"는 `photo` 상태를 `{kind: "rec", recId, imageUrl, boxX, boxY}`(서버 사진은 `AuthImage` 로 표시)로 바꾸고 질문·보기·정답 위치·배율·확대 위치를 채워 "직접 내기"로 넘어가 고칠 수 있게 한다. 보낼 때 `photo.kind === "rec"` 이면 `createPhoto({recId, ...})`(파일 없이), 출제자가 사진을 내 폰 사진으로 바꾸면 `recId` 는 보내지 않는다(서버 규칙과 같음). 가족 앨범 고르기(`kind: "album"`)는 이번 범위에서 건드리지 않는다. 서버 주소가 없으면 시안. 409 `photo_not_available`·`rec_already_sent` 는 "이 사진은 지금 쓸 수 없어요, 다른 추천을 골라 주세요" 안내와 새로고침.
- [ ] **Step 2: 정적 확인** — `cd apps/mobile && npx eslint src/features/playground tests` 통과, 놀이터 관련 앱 시험 통과.
- [ ] **Step 3: 폰 확인**(사용자와 함께) — 로컬 서버를 켜고 폰에서 탐정단 만들기 → 가비 추천 카드 3개(가족 사진 + 흔한 사진), "이 문제로 쓰기" 뒤 질문·보기·확대 위치가 채워져 고쳐 보낼 수 있는지, 보낸 뒤 추천에서 그 사진이 빠지는지, AI 동의를 끈 가족에서도 3개가 나오는지.
- [ ] **Step 4: 커밋**(메시지는 사용자가 정함).

### Task 10: 시드 50장 만들기·검수(사용자 참여)

**Files:**
- Create: `apps/api/scripts/draft_photo_seed.py`, 시드 폴더(예: `apps/api/seed/photo_rec/`의 `seed.json`·`img/`·`review.md`)
- Test: `apps/api/app/features/play/tests/test_draft_photo_seed.py`

**Interfaces:**
- Consumes: Task 3 `content_question`, `to_judge_jpeg`; Task 4 시드 형식.
- Produces: `python scripts/draft_photo_seed.py <사진폴더> <출력폴더>` — 사진마다 긴 변 1280px JPEG(품질 80)로 줄여 `img/NN.jpg` 로 저장하고 Task 3 의 AI 호출로 질문·보기·정답·확대 위치 초안을 만들어 `seed.json` 과 사용자가 검수할 `review.md`(번호·사진 파일명·질문·보기·정답·확대 위치·승인 칸) 표를 쓴다. `usable=false` 는 표에 "제외 추천"으로 표시한다.

- [ ] **Step 1: 실패하는 시험** — `test_draft_writes_seed_and_review`: 가짜 `content_question` 으로 사진 2장을 돌리면 `seed.json` 2항목(Task 4 형식과 같은 키), `img/` 2개(긴 변 1280 이하), `review.md` 에 두 줄, `usable=false` 인 사진은 "제외 추천".
- [ ] **Step 2: 구현·통과 확인** — `pytest app/features/play/tests/test_draft_photo_seed.py -q` → PASS.
- [ ] **Step 3: 사용자 준비** — 사용자가 **라이선스를 확인한 사진 50장 이상**을 사진폴더에 넣어 준다(출처 사이트·약관은 사용자가 나중에 확인하기로 함; 사진마다 출처·라이선스를 `review.md` 에 적을 칸이 있다).
- [ ] **Step 4: 초안 생성** — 스크립트를 돌려 `review.md` 를 사용자에게 보여 준다(AI 호출은 사진 50장 × 1회, 약 몇 센트).
- [ ] **Step 5: 사용자 검수** — 사용자가 `review.md` 에서 승인·수정·제외를 표시하면 `seed.json` 에 반영해 50장을 맞춘다(제외된 만큼 사진을 더 받아 다시 돌림).
- [ ] **Step 6: 시드 넣기·커밋** — 로컬 DB 에 `python scripts/seed_photo_rec.py <시드 폴더>` 로 넣어 추천이 흔한 사진을 돌려주는지 본다. 시드 폴더 커밋은 사용자가 크기(약 10MB)와 메시지를 정한 뒤. 공용·운영 DB 반영은 DB 담당자(스크립트 실행 방법을 PR 본문에 적는다).

### Task 11: 실측·조정과 기록

**Files:**
- Modify: `apps/api/app/features/play/photo_rec_ai.py`(필요할 때 `MAX_TOKENS`·`TIMEOUT` 만)
- Docs(`C:\Users\403\Documents\prj\`): `HISTORY.md`, `STATS.md`, `wiki/decisions/photo-recommendation.md`

- [ ] **Step 1: 실측** — 로컬 서버(실제 AI 키, 동의 가족)에서 가족 사진 후보 5~10장으로 추천을 열어 걸린 시간과 토큰(`ai_usage` 기록), 일정·월·내용 질문 비율, `usable=false` 비율을 5번 재서 표로 남긴다. 처음 열 때 시간이 이게 뭐게(6.5초)와 비슷한 범위인지 본다.
- [ ] **Step 2: 조정** — 느리거나 AI 거부(`usable=false`)가 많으면 프롬프트·`MAX_TOKENS` 를 조정하고 다시 잰다.
- [ ] **Step 3: 기록** — prj 문서 3종을 갱신한다(실측 결과, 병합 PR 번호, 열린 이슈: 공용 DB 마이그레이션 적용 순서(팀원 사진 판별 표 → 이 표), 시드 반영, 사진 사이트·약관(2차), 정답 노출 별도 논의).
