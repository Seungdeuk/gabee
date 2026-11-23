# 이게 뭐게 가비 추천 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이게 뭐게 문제 내기에서 서버가 공개 단어 5개를 뽑고 AI(Haiku)가 선 좌표 그림을 만들어 주는 "가비 추천"을 추가한다.

**Architecture:** 서버는 `draw_rec.py` 한 모듈이 단어 뽑기(목록+일정·대화 매칭) → 단어별 그림 재사용/생성(동시 호출) → `ai_guard.run` 하루 캐시를 맡는다. 골든벨 추천(`quiz_rec.py`)과 같은 모양이고 `quiz_rec.py` 는 건드리지 않는다. 앱은 그림판 `strokes` 에 추천 좌표를 채워 넣는다(업로드 흐름 그대로).

**Tech Stack:** FastAPI·SQLAlchemy·Alembic·pytest(서버 `gabee/apps/api`), React Native·Expo·node:test(앱 `gabee/apps/mobile`), Kiwi(`kiwipiepy`, 이미 설치됨), Anthropic Haiku 5.5(`app.shared.llm.client`).

**Spec:** `C:\Users\403\Documents\prj\draw-rec\design.md`

## Global Constraints
- 작업은 최신 `origin/release/1.3` 에서 새 브랜치(이름은 사용자가 정함)로 시작한다. 커밋 메시지도 사용자가 정한다 — 커밋 단계마다 사용자에게 메시지를 확인받고 커밋한다.
- 정답 단어는 띄어쓰기·합성어 없는 한 단어(한글만, 1~5자), 고유명사·이름·장소 제외. 그림은 어린이가 손으로 그린 낙서 느낌의 선 좌표(0~255)이고 글자·숫자·색칠 금지.
- 한 번 열 때 그림 5개, 동시 호출, 가족 단위 캐시는 오늘 자정까지, 단어별 그림은 30일 재사용·단어당 최대 3종, 저장된 게 있으면 기본 재사용하고 확률 0.3으로 새로 그려 쌓는다. 최근 30일 가족이 낸 단어는 뺀다. 먼저 준비(백그라운드)는 하지 않는다.
- 일정·대화 원문은 AI 로 보내지 않는다(AI 는 단어만 받는다). 재료 범위는 골든벨과 같다: 공동 일정(공유 원본, 지난 30일~앞으로 30일, 부탁에서 생긴 일정 제외)과 가족 전체방 최근 14일(1:1·개인 AI 방 제외).
- 실패·한도는 오류가 아니라 200 + `state` 로 돌려준다. 시험은 실제 AI 를 부르지 않고 `llm.complete_json` 을 가짜로 바꾼다(`test_quiz_rec.py` 방식). 로컬 시험은 바뀐 부분과 연결된 것만 돌린다(전체 pytest 는 CI).
- Expo·폰 접속 문제는 기록하지 않는다.

## Review Focus
1. 일정·대화에 목록 단어가 하나도 없다 → 5개 모두 흔한 단어로 채워 `ok`(재료 없음 상태는 없다) — Task 4
2. 한 글자 단어(집·눈·배)가 "집에서"·"눈치" 같은 말에 오탐으로 걸린다 → Kiwi 명사 토큰일 때만 인정 — Task 1
3. 5개 중 일부만 생성 성공 → 1장 이상이면 `ok` 로 캐시, 0장이면 `failed`(캐시 안 함) — Task 4
4. 최근 30일 낸 단어를 빼면 후보가 5개보다 적다 → 가능한 만큼만 돌려주고 억지로 중복하지 않는다 — Task 4
5. 모델이 범위 밖 좌표·빈 선·너무 많은 선을 돌려준다 → 서버가 버리고 한 번 다시 시도한다 — Task 2

---

### Task 1: 공개 단어 목록과 단어 찾기

**Files:**
- Create: `apps/api/app/features/play/draw_words.json`, `apps/api/app/features/play/draw_words.py`
- Test: `apps/api/app/features/play/tests/test_draw_words.py`

**Interfaces:**
- Produces: `DrawWord(word: str, alts: tuple[str, ...])` (frozen dataclass); `load_words() -> dict[str, DrawWord]`(한 번 읽어 재사용); `find_words(text: str) -> list[str]`(글자에서 목록 단어를 등장 순서대로, 중복 없이).
- JSON 형식: `[{"word": "케이크", "alts": ["케익"]}, ...]`.

- [ ] **Step 1: 실패하는 시험 작성** — `test_word_list_is_clean`: 모든 단어가 `re.fullmatch(r"[가-힣]{1,5}", w)`, 중복 없음, 150개 이상, alts 도 한글 한 단어이고 단어와 다름, 설계 예시 9개(케이크·딸기·선물·텐트·꽃다발·해바라기·돈가스·돼지·바다)가 모두 들어 있음. `test_find_words_examples`: `find_words("딸기 케이크 사 갈게")==["딸기","케이크"]`, `find_words("흑돼지 먹었다")==["돼지"]`, `find_words("협재 바다색")==["바다"]`, `find_words("협재 해변")==[]`(고유 지명), `find_words("해바라기 꽃다발 준비")==["해바라기","꽃다발"]`.
- [ ] **Step 2: 한 글자 오탐 시험** — `test_single_char_words_need_noun_token`: 목록에 "집"이 있을 때 `find_words("집에 갔다")==["집"]`, `find_words("집중해서 봤다")==[]`.
- [ ] **Step 3: 실패 확인** — `cd apps/api && .venv/Scripts/python.exe -m pytest app/features/play/tests/test_draw_words.py -q` → 모듈 없음으로 FAIL.
- [ ] **Step 4: 구현** — 목록 파일은 에이전트가 먼저 작성한다(동물·음식·과일·탈것·옷·집안 물건·자연·학용품 등 선 그림으로 알아볼 수 있는 흔한 사물, 고유명사·행동·추상어 제외, 한 글자 단어는 꼭 필요한 것만). `find_words`: 공백을 뺀 글자에서 2글자 이상 단어는 부분 문자열로 찾고, 1글자 단어는 `bomb_judge._get_kiwi()` 로 형태소 분석해 명사(NNG)로 나온 토큰이 정확히 그 글자일 때만 인정한다.
- [ ] **Step 5: 통과 확인** — 위 명령 → PASS.
- [ ] **Step 6: 사용자에게 단어 목록 검토를 요청**한 뒤 커밋(메시지는 사용자가 정함).

### Task 2: 그림 검증·프롬프트·생성 함수 (`effort` 옵션 포함)

**Files:**
- Modify: `apps/api/app/shared/llm/client.py` (`complete_json` 에 `effort: str | None = None` 추가, 본문 `"effort": effort or settings.ai_effort`)
- Create: `apps/api/app/features/play/draw_rec.py`
- Test: `apps/api/app/features/play/tests/test_draw_rec.py`, 기존 `app/shared/llm/tests/` 의 `complete_json` 시험 방식에 맞춰 `effort` 한 개

**Interfaces:**
- Produces: `validate_strokes(raw: object) -> list[list[list[int]]] | None`; `draw_prompt(word: str) -> str`; `draw_word(word: str) -> tuple[list[list[list[int]]], llm.JsonResult]`(검증에 실패하면 한 번 더 부르고 그래도 안 되면 `ValueError`); 상수 `ASK_COUNT=5`, `STOCK_DAYS=30`, `STOCK_MAX=3`, `REDRAW_RATE=0.3`, `RECENT_DAYS=30`, `EVENT_PAST_DAYS=30`, `EVENT_AHEAD_DAYS=30`, `CHAT_DAYS=14`, `FEATURE="play_draw_rec"`, `PROMPT_VERSION="v1"`.

- [ ] **Step 1: 실패하는 시험** — `test_validate_strokes_accepts_and_rejects`: 선 3개(각 점 2개 이상)이고 좌표가 0~255 정수면 그대로 돌려줌, 소수 좌표는 반올림해 정수로, 선이 2개 이하·13개 이상이면 `None`, 점이 1개인 선·31개 이상인 선이 있으면 `None`, 좌표가 -1·256이면 `None`, 숫자가 아닌 값이면 `None`. `test_draw_prompt_has_rules`: 프롬프트에 단어, "0~255", "손으로 삐뚤빼뚤", "글자·숫자" 금지 문구가 들어 있고 가족 정보는 없음. `test_draw_word_retries_once`: 가짜 `complete_json` 이 첫 호출에 범위 밖 좌표, 둘째에 정상을 주면 정상 결과와 호출 2번, 둘 다 나쁘면 `ValueError`. `test_complete_json_effort_override`: `effort="low"` 가 요청 본문 `output_config.effort` 로 간다.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_draw_rec.py app/shared/llm/tests -q -k "draw or effort"` → FAIL.
- [ ] **Step 3: 구현** — 위 시그니처대로. 모델 출력 스키마는 `{"strokes": [[[int, int], ...], ...]}`(`additionalProperties: False`). `draw_word` 는 `llm.complete_json(prompt, SCHEMA, system=SYSTEM, max_tokens=3000, effort="low", timeout=60)`. 시스템 프롬프트 문구는 설계 6장("어린이가 손으로 그린 낙서 느낌", 선 3~12개·점 2~30개, 좌표 0~255, 글자·숫자·색칠 금지, 대표 특징을 살림)을 따른다. 돌려주는 `JsonResult` 는 호출 한 번의 것이다.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS. 커밋(메시지는 사용자가 정함).

### Task 3: 단어별 그림 저장소(모델·마이그레이션)

**Files:**
- Modify: `apps/api/app/features/play/models.py`(모델 `PlayDrawStock` 추가)
- Create: `apps/api/alembic/versions/<새 id>_play_draw_stock.py`(expand 전용, `down_revision` 은 `alembic heads` 가 가리키는 현재 head), `apps/api/app/features/play/draw_stock.py`
- Test: `apps/api/app/features/play/tests/test_draw_stock.py`

**Interfaces:**
- Produces: 모델 `PlayDrawStock`(테이블 `play_draw_stock`; 칸: `id` 문자열 기본키, `word` 문자열(8) 색인, `strokes` JSON, `created_at` 시각); `stock_variants(db: Session, word: str, now: datetime) -> list[PlayDrawStock]`(30일 안, 오래된 순); `add_variant(db: Session, word: str, strokes: list, now: datetime) -> PlayDrawStock`(이미 3종이면 가장 오래된 것을 지우고 추가).

- [ ] **Step 1: 실패하는 시험** — `test_stock_variants_only_within_30_days`: 31일 전 것은 안 나오고 29일 전 것은 나옴. `test_add_variant_replaces_oldest_when_full`: 3종 뒤에 하나 더 넣으면 3종이고 가장 오래된 것이 없어짐. `test_other_words_are_separate`.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_draw_stock.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 마이그레이션은 `scripts/check_alembic_migrations.py`·`scripts/check_schema_matches_models.py` 를 통과해야 한다.
- [ ] **Step 4: 통과 확인** — 시험 + `.venv/Scripts/python.exe scripts/check_alembic_migrations.py` 와 `check_schema_matches_models.py` → PASS. 로컬 DB(`127.0.0.1:5433`)에 `alembic upgrade head` 로 적용해 보고 되돌려 보기(`downgrade -1`).
- [ ] **Step 5: 커밋**(메시지는 사용자가 정함). 공용 DB 반영은 DB 담당자(PR 본문에 적는다).

### Task 4: 추천 조립(단어 뽑기·재사용·동시 생성·캐시·한도)

**Files:**
- Modify: `apps/api/app/features/play/draw_rec.py`, `apps/api/app/shared/config.py`(`ai_play_draw_rec_cooldown_seconds=5`, `ai_play_draw_rec_max_calls_per_user_per_day=3`, `ai_play_draw_rec_max_calls_per_group_per_day=5`)
- Test: `apps/api/app/features/play/tests/test_draw_rec.py`

**Interfaces:**
- Consumes: Task 1 `find_words`, `load_words`; Task 2 `draw_word`, 상수; Task 3 `stock_variants`, `add_variant`; `quiz_rec.shared_events(db, group_id, today)` 와 `app.features.family_chat.ai_repository.recent_messages(db, group_id, limit)`(`chat_digest` 가 쓰는 함수, `(메시지, 이름)` 줄을 돌려줌, 가족 전체방만) — 재료 범위를 골든벨과 같게 읽는다.
- Produces: `register_limits() -> None`(모듈 끝에서 호출); `family_words(db, group_id, today, now) -> list[tuple[str, str]]`((단어, `"schedule"|"chat"`), 등장 순서·중복 없음, 일정 제목·장소·메모와 14일 대화 원문에서 찾음); `recent_words(db, group_id, now) -> set[str]`(최근 30일 이 가족이 이게 뭐게에서 낸 정답 `PlayDraw.answer` 와 그 alts, 공백 없앰); `pick_words(found, recent, rng) -> list[tuple[str, str]]`(최대 5개, 단어 중복 없음, 부족하면 목록에서 흔한 단어를 `"common"` 으로 채움, 최근 단어 제외); `recommend(db: Session, user: User, group_id: str, rng: random.Random | None = None) -> dict`(`{"state": ..., "items": [{"id", "source", "word", "alt_answers", "strokes"}]}`).
- 상태 문자열은 `quiz_rec` 의 `OK·USED_UP·PREPARING·COOLDOWN·FAILED·AI_OFF` 와 같다. `no_data` 는 돌려주지 않는다.

- [ ] **Step 1: 실패하는 시험 작성**(가짜 `llm.complete_json`, 임시 DB 데이터):
  - `test_family_words_from_events_and_chat`: 일정 메모 "딸기 케이크"·대화 "흑돼지" → `[("딸기","schedule"),("케이크","schedule"),("돼지","chat")]`, 1:1 방·개인 AI 방 메시지와 부탁에서 생긴 일정의 단어는 빠짐.
  - `test_pick_words_fills_with_common`: 재료 단어 2개 → 5개이고 앞 2개는 재료 출처, 나머지는 `"common"`, 중복 없음, `recent` 에 든 단어는 없음. 재료가 0개여도 5개(Review Focus 1). 목록에서 `recent` 를 빼고도 5개가 안 되면 있는 만큼만(Review Focus 4).
  - `test_recommend_reuses_stock_and_redraws_by_rate`: 단어 그림이 저장돼 있고 `rng` 가 0.5(≥0.3)이면 호출 없이 저장된 그림을 돌려줌, `rng` 가 0.1 이면 새로 그려 `stock_variants` 가 늘어남.
  - `test_recommend_partial_failure_is_ok`: 5개 중 2개 그림 실패 → `state=="ok"` 에 3개, 캐시됨(같은 날 두 번째 호출은 AI 안 부름). `test_recommend_all_failed`: 전부 실패 → `failed`, 캐시 안 됨(두 번째 호출이 다시 부름).
  - `test_recommend_states`: AI 꺼진 가족 → `ai_off`, 다른 구성원이 만드는 중(`ai_busy`) → `preparing`, 쿨다운 → `cooldown`, 하루 한도 → `used_up`(`quiz_rec._state_of` 와 같은 매핑).
  - `test_recommend_item_shape`: 항목에 `alt_answers`(예: 케이크 → `["케익"]`)·`strokes`·`id`·`source` 가 있고 가족 이름·일정 제목은 없음. AI 에 보낸 프롬프트에 일정·대화 글자가 없음.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_draw_rec.py -q` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 재료는 `quiz_rec.shared_events` 와 같은 범위, 대화는 `ai_repository.recent_messages(db, group_id, 500)` 중 `created_at` 이 최근 `CHAT_DAYS` 일 안인 것(`chat_digest` 와 같은 방식, 가족 전체방만, 원문 그대로 단어만 찾는다). 단어마다 저장된 그림이 있으면 `rng.random() < REDRAW_RATE` 일 때만 새로 그리고 아니면 저장된 것 중 하나를 `rng.choice`, 없으면 항상 새로 그린다. 새로 그리는 단어만 `ThreadPoolExecutor(max_workers=ASK_COUNT)` 로 `draw_word` 를 동시에 부르되 DB 접근(저장소 추가)은 메인 스레드에서 한다. `ai_guard.run(feature=FEATURE, cache_key=_cache_key(today), call=..., cache_until=local_day_start(now)+1일)` 로 감싸고, `call()` 은 `(result, response)` 를 돌려주며 `response` 는 `model`·`input_tokens`·`output_tokens`·`calls`(실제 부른 횟수, 0이면 1로 세짐)를 가진 간단한 객체다. 그림이 하나도 없으면 `ValueError` 로 캐시하지 않는다. 읽을 때 `recent_words` 에 든 단어는 숨긴다. 같은 날 같은 가족은 `rng` 를 가족·날짜 해시로 시드한 기본값을 써서 재호출해도 단어가 같게 한다.
- [ ] **Step 4: 통과 확인** — `pytest app/features/play/tests/test_draw_rec.py app/features/play/tests/test_quiz_rec.py -q` → PASS(골든벨 시험이 그대로 통과해야 함).
- [ ] **Step 5: 커밋**(메시지는 사용자가 정함).

### Task 5: API 엔드포인트·스키마·문서

**Files:**
- Modify: `apps/api/app/features/play/schemas.py`, `apps/api/app/features/play/router.py`, 레포 루트의 `docs/contracts/openapi.json`(갱신은 이 레포가 쓰는 방식을 따르고 다른 경로가 바뀌면 되돌린다), 레포 루트의 `docs/features/play.md`
- Test: `apps/api/app/features/play/tests/test_draw_rec.py`

**Interfaces:**
- Produces: `GET /play/draw/recommendations` → `PlayDrawRecOut(state: Literal["ok","preparing","cooldown","failed","used_up","ai_off"], items: list[PlayDrawRecItem])`; `PlayDrawRecItem(id: str, source: Literal["schedule","chat","common"], word: str, alt_answers: list[str], strokes: list[list[list[int]]])`.

- [ ] **Step 1: 실패하는 시험** — `test_draw_rec_endpoint`: 로그인한 가족 구성원이 `GET /play/draw/recommendations` 를 부르면 200과 `state`·`items`(위 모양), 로그인 없으면 401, 가족 그룹이 없으면 기존 `current_group_id` 오류와 같음.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_draw_rec.py -k endpoint -q` → FAIL.
- [ ] **Step 3: 구현** — `quiz_recommendations` 와 같은 모양으로 `draw_recommendations` 라우트를 추가(`PlayDrawRecOut(**draw_rec.recommend(db, user, group_id))`). `docs/features/play.md` 에 이게 뭐게 추천 절(단어 목록·재사용 규칙·상태·한도)을 추가하고 `openapi.json` 을 레포 방식으로 다시 만든다(다른 경로가 바뀌면 되돌린다).
- [ ] **Step 4: 통과 확인** — `pytest app/features/play/tests/test_draw_rec.py app/features/play/tests/test_draw_api.py -q` → PASS, `ruff check app` 통과.
- [ ] **Step 5: 커밋**(메시지는 사용자가 정함).

### Task 6: 앱 데이터층(api·hook·시안·변환)

**Files:**
- Modify: `apps/mobile/src/features/playground/api.js`, `hooks.js`, `mock.js`, `adapt.js`
- Test: `apps/mobile/tests/`의 놀이터 변환 시험 파일(없으면 `playdrawrec.test.js` 새로 만들고 기존 놀이터 시험의 import 방식을 따른다)

**Interfaces:**
- Produces: `getDrawRecs()`(= `apiFetch("/play/draw/recommendations")`, 15~40초를 기다리도록 요청 제한 시간이 60초 이상인지 `shared/api/client.js` 의 기본값을 확인하고 짧으면 이 호출에만 늘림); `useDrawRecs()`(= `useQuizRecs` 와 같은 모양, 서버 주소가 없으면 `MOCK_DRAW_RECS`); `drawRecView(recs) -> {items} | {items: [], notice: string, refresh: boolean}`; `strokesFromRec(item, width, height, color) -> {color: string, pts: {x:number,y:number}[]}[]`.

- [ ] **Step 1: 실패하는 시험** — `strokesFromRec({strokes:[[[0,0],[255,255]]]}, 360, 280, "#000")` 가 `[{color:"#000", pts:[{x:52,y:12},{x:308,y:268}]}]`(짧은 변에서 여백 12를 빼 정사각형으로 맞추고 가로는 가운데 정렬; `Number.toFixed` 없이 소수는 반올림해 정수). `drawRecView`: `ok`+항목 있음 → 항목, `failed`/`preparing`/`cooldown` → `refresh: true`, `used_up`/`ai_off` → `refresh: false`, 문구는 비어 있지 않음, `recs` 가 없으면 `failed` 취급.
- [ ] **Step 2: 실패 확인** — `cd apps/mobile && node --import ./tests/register-alias.mjs --test tests/playdrawrec.test.js` → FAIL.
- [ ] **Step 3: 구현** — 위 인터페이스. 상태별 문구는 `adapt.js` 의 `REC_NOTICE`(골든벨)와 같은 말투로 그림에 맞게 쓴다(예: 준비 중 "가비가 그림을 준비 중이에요"). `MOCK_DRAW_RECS` 는 `{state:"ok", items:[...]}` 단어 2개와 간단한 선 그림.
- [ ] **Step 4: 통과 확인** — 위 명령 → PASS, `npx eslint src/features/playground tests` 통과. 커밋(메시지는 사용자가 정함).

### Task 7: 그림 만들기 화면에 "가비 추천" 전환

**Files:**
- Create: `apps/mobile/src/features/playground/components/draw/DrawRecommend.js`
- Modify: `apps/mobile/src/features/playground/screens/DrawCreateScreen.js`

**Interfaces:**
- Consumes: Task 6 `useDrawRecs`, `drawRecView`, `strokesFromRec`; 기존 `stepIndex`(`adapt.js`), `DrawingCanvas`.
- Produces: `DrawRecommend({ recs, index, onIndex, onPick, refreshing, onRefresh })` — 카드(그림 미리보기, 정답 단어, 출처 알약 "일정에서/소통방에서/흔한 단어", `< n / N >`, "이 그림으로 쓰기"), 상태·새로고침은 골든벨 `Recommend` 와 같은 모양.

- [ ] **Step 1: 구현** — `DrawCreateScreen` 에 골든벨(`QuizCreateScreen`)과 같은 "가비 추천 / 직접 그리기" 전환을 추가하고 처음은 가비 추천. 그림 미리보기는 `react-native-svg` 로 선을 그리는 작은 읽기 전용 부품. "이 그림으로 쓰기"를 누르면 정답 칸에 단어, 비슷한 정답 칸에 `alt_answers`(칸이 받는 형식은 기존 제출 코드가 나누는 방식을 읽고 맞춘다), 그림판 `strokes` 에 `strokesFromRec(item, canvasWidth, 280, PALETTE[0].value)` 를 채우고 "직접 그리기"로 넘어가 고칠 수 있게 한다(캔버스 너비는 감싼 `View` 의 `onLayout` 으로 잰다). 서버 주소가 없으면 시안. 추천에서 낸 그림도 기존 PNG 업로드 흐름으로 보낸다.
- [ ] **Step 2: 정적 확인** — `cd apps/mobile && npx eslint src/features/playground tests` 통과, 놀이터 관련 앱 시험(`tests/` 의 play 시험들) 통과.
- [ ] **Step 3: 폰 확인**(사용자와 함께) — 로컬 서버를 켜고 폰에서 이게 뭐게 만들기 → "가비 추천"이 "준비 중"을 보이다가 카드 5개가 나오는지, "이 그림으로 쓰기" 뒤 그림판에 채워져 이어 그릴 수 있고 보내기까지 되는지. 샘플 데이터(케이크·딸기·텐트·해바라기·꽃다발·돼지·바다 등이 일정·대화에 있음)로 `source` 알약이 일정/소통방/흔한 단어로 나뉘는지 본다.
- [ ] **Step 4: 커밋**(메시지는 사용자가 정함).

### Task 8: 실측·조정과 기록

**Files:**
- Modify: `apps/api/app/features/play/draw_rec.py`(필요할 때 `REDRAW_RATE`·`max_tokens`·`timeout` 만)
- Docs(`C:\Users\403\Documents\prj\`): `HISTORY.md`, `STATS.md`, `wiki/decisions/draw-recommendation.md`

- [ ] **Step 1: 실측** — 로컬 서버(실제 AI 키)에서 저장소가 빈 상태로 추천을 열어 걸린 시간과 토큰(`ai_usage` 기록)을 5번 재서(저장소 비운 첫 호출, 저장된 뒤 호출 포함) 표로 남긴다. 처음 열 때가 15~40초 안인지, 호출당 출력 토큰이 시험(1,667)보다 줄었는지 확인한다.
- [ ] **Step 2: 조정** — 40초를 넘으면 `max_tokens`·프롬프트의 선·점 상한을 줄이거나 `timeout` 을 조정하고 결과를 같은 방식으로 다시 잰다. 확률은 비용·다양성을 보고 사용자와 정한다.
- [ ] **Step 3: 기록** — 위 prj 문서 3종을 갱신한다(실측 결과, 병합 PR 번호, 열린 이슈: 알아볼 수 없는 그림 노출, 공용 DB 마이그레이션 적용).
