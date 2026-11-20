# 골든벨·이게 뭐게 가비 추천 사용자별 보이기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 골든벨·이게 뭐게 가비 추천을 사용자마다 다른 일부만 보여 주고, 이게 뭐게 저장 그림의 30일 제한을 없앤다.

**Architecture:** 생성·가족 캐시는 그대로 두고, `recommend` 가 가족 목록을 만든 뒤 공통 함수 `pick_for_user` 로 사용자·날짜별 절반 올림만 골라 돌려준다. 이게 뭐게 저장소는 기간 필터와 만료 삭제만 뺀다.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest, ruff (`apps/api`, 서버만 바뀜).

**Spec:** `prj/rec-per-user/design.md`

## Global Constraints
- 작업 폴더 `C:\Users\403\Documents\gabee`, 브랜치 `fix/hellobk-play-rec-user`(이미 생성, `origin/release/1.3` `5ec3ec88` 기준). 브랜치·커밋 메시지는 아래 것을 그대로 쓴다.
- 보여 줄 개수 = 후보 수의 절반 올림(1→1, 2→1, 3→2, 4→2, 5→3, 6→3, 7→4). 섞는 기준은 `가족|사용자|날짜|항목 id`.
- 이게 뭐게 그림 5개 생성·캐시·`STOCK_MAX=3` 은 그대로. 앱·DB 마이그레이션·찰칵 코드는 건드리지 않는다.
- 커밋에 넣지 않는 미추적 파일: `apps/api/app/features/play/bomb_dev_skip.py`, `apps/api/scripts/dev_bomb_bot.py`, `apps/api/scripts/seed_play_dev.py`. `git add` 는 파일을 지정해서만 한다(`git add -A`·`.` 금지).
- 시험은 변경과 연결된 것만 돌린다(전체 pytest 는 CI). 실행은 `apps/api` 에서 `.venv/Scripts/python.exe -m pytest <파일>`, 린트 `.venv/Scripts/python.exe -m ruff check <파일>`.
- 푸시·PR 은 이 계획에 없다(사용자 지시 뒤). 코드 주석·문서는 한국어, 기존 파일 문체를 따른다.

## Review Focus
- 후보 0개: 빈 목록·기존 상태(`used_up` 등)가 그대로여야 한다.
- 같은 사용자가 같은 날 여러 번 불러도 같은 목록이어야 한다.
- 날짜가 바뀌거나 사용자가 다르면 (후보 3개 이상일 때) 목록이 달라질 수 있어야 한다.
- 이게 뭐게 일부만(partial)→5개로 채워질 때 이미 본 카드가 통째로 바뀌지 않아야 한다(항목별 해시라 대부분 유지).
- 저장소: 31일 이상 된 그림도 쓰이고, 4번째 그림은 가장 오래된 것을 대체해 3종을 유지해야 한다.

---

### Task 1: 공통 선택 함수

**Files:**
- Create: `apps/api/app/features/play/rec_pick.py`
- Test: `apps/api/app/features/play/tests/test_rec_pick.py`

**Interfaces:**
- Produces: `show_count(n: int) -> int` (= `(n + 1) // 2`, n=0 이면 0), `pick_for_user(items: list[dict], group_id: str, user_id: str, today: date) -> list[dict]` — 각 항목의 `"id"` 를 해시 키로 정렬해 앞의 `show_count(len(items))` 개를 고르고 원래 순서로 돌려준다. 입력을 바꾸지 않는다.

- [ ] **Step 1: 실패하는 시험 작성** — 이름·단언:
  - `test_show_count_is_half_rounded_up`: `[show_count(n) for n in range(0, 8)] == [0, 1, 1, 2, 2, 3, 3, 4]`
  - `test_pick_keeps_original_order_and_count`: id `a`~`e` 5개 → 길이 3, 결과 id 가 원래 순서의 부분 수열.
  - `test_same_user_same_day_is_stable`: 같은 인자로 두 번 호출한 결과가 같다.
  - `test_different_users_can_differ`: 후보 7개, 사용자 id 20개로 돌려 서로 다른 목록이 둘 이상 나온다.
  - `test_other_day_can_differ`: 같은 사용자, 날짜 30일치 중 서로 다른 목록이 둘 이상.
  - `test_adding_an_item_keeps_most_of_the_pick`: 후보 3개의 선택(2개)과 4개를 더한 선택(2개)에서, 3개 선택에 있던 항목이 새 선택에 하나 이상 남는다(여러 사용자 id 로 확인).
  - `test_empty_and_single`: `[]→[]`, 항목 하나→그 항목.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_rec_pick.py` → ImportError/FAIL.
- [ ] **Step 3: 구현** — `hashlib.sha256` 로 `f"{group_id}|{user_id}|{today.isoformat()}|{item['id']}"` 를 정렬 키로 쓴다(찰칵 `_sorted_by_key` 와 같은 방식, 그 함수를 import 하지 않고 이 파일에 둔다).
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS, `ruff check` 통과.
- [ ] **Step 5: 커밋** — `git add apps/api/app/features/play/rec_pick.py apps/api/app/features/play/tests/test_rec_pick.py` → `git commit -m "feat(play): 추천문제 공통함수"`

### Task 2: 골든벨 적용

**Files:**
- Modify: `apps/api/app/features/play/quiz_rec.py` (`recommend`, 362~411행)
- Test: `apps/api/app/features/play/tests/test_quiz_rec.py`

**Interfaces:**
- Consumes: `rec_pick.pick_for_user`.
- Produces: `recommend(db, user, group_id) -> dict` 는 시그니처 그대로, `OK` 응답의 `items` 만 사용자별 절반 올림으로 줄어든다. 가족 캐시(`ai_guard.run` 결과)는 전체 목록 그대로 저장한다.

- [ ] **Step 1: 실패하는 시험** — 가짜 LLM 이 문제 4개를 주는 기존 시험 구성으로: `test_items_are_half_for_each_user`(응답 items 2개), `test_two_family_members_can_see_different_questions`(같은 가족 두 사용자 응답이 모두 전체의 부분집합이고, 사용자 여럿으로 돌렸을 때 서로 다른 조합이 나옴), `test_same_user_gets_same_items_on_reopen`(같은 날 두 번 호출 동일, 캐시된 두 번째 호출도 동일), `test_used_up_when_all_hidden_still_used_up`(이미 낸 문제로 모두 숨겨지면 `USED_UP`·빈 items, 기존 시험이 있으면 유지).
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_quiz_rec.py` → 새 시험 FAIL.
- [ ] **Step 3: 구현** — 마지막 줄 직전: `items = [q for q ... not in used]` 를 만든 뒤 `items = pick_for_user(items, group_id, user.id, today)`, 그 다음 기존 `OK`/`USED_UP` 분기. `today` 는 함수 앞부분의 값을 쓴다.
- [ ] **Step 4: 통과 확인** — `test_quiz_rec.py`, `test_quiz_api.py` 실행. 개수를 전체로 가정한 기존 단언이 깨지면 새 규칙(절반 올림)에 맞게 고친다(동작을 되돌리지 않는다). `ruff check` 통과.
- [ ] **Step 5: 커밋** — 변경한 파일만 `git add` → `git commit -m "feat(play): 골든벨 가비 추천 사람마다 다르게"`

### Task 3: 이게 뭐게 적용

**Files:**
- Modify: `apps/api/app/features/play/draw_rec.py` (`recommend`, 294~388행)
- Test: `apps/api/app/features/play/tests/test_draw_rec_api.py`, `test_draw_rec_assemble.py`

**Interfaces:**
- Consumes: `rec_pick.pick_for_user`.
- Produces: 현재 `recommend` 를 `_recommend_family(db, user, group_id, rng=None) -> dict` 로 이름만 바꾸고(본문 그대로), 새 `recommend(db, user, group_id, rng=None) -> dict` 가 그것을 부른 뒤 `reply["items"]` 가 있으면 `pick_for_user(reply["items"], group_id, user.id, today)` 로 줄여 돌려준다. 이렇게 해서 정상·일부만(`partial`)·한도 소진 때 저장소 그림 세 반환 지점이 모두 적용된다. `state` 는 바꾸지 않는다. `router.py` 의 호출은 그대로.

- [ ] **Step 1: 실패하는 시험** — `test_returns_three_of_five_drawings_per_user`(API 응답 items 3개, 모두 가족 5개의 부분집합), `test_two_members_can_get_different_drawings`, `test_partial_state_is_also_picked_per_user`(그림이 3개만 만들어진 상태 → items 2개, state `partial`), `test_cached_family_list_is_unchanged`(두 번째 사용자 호출이 AI 를 다시 부르지 않고 같은 가족 5개에서 고른다).
- [ ] **Step 2: 실패 확인** — 두 시험 파일 실행, 새 시험 FAIL.
- [ ] **Step 3: 구현** — 위 Interfaces 대로. `today` 는 `datetime.now(UTC).astimezone(local_tz()).date()`(본문과 같은 계산).
- [ ] **Step 4: 통과 확인** — `test_draw_rec_api.py`, `test_draw_rec_assemble.py`, `test_draw_rec.py`. 항목 5개를 단언하던 기존 시험(예: `test_returns_five_drawings_for_a_family`)은 새 규칙(3개)으로 고친다. 가족 캐시 내용을 보려는 시험은 `_recommend_family` 를 직접 부르도록 바꿀 수 있다. `ruff check` 통과.
- [ ] **Step 5: 커밋** — 변경한 파일만 `git add` → `git commit -m "feat(play): 이게뭐게 가비 추천 사람마다 다르게"`

### Task 4: 이게 뭐게 저장된 그림 보관 기간 제거

**Files:**
- Modify: `apps/api/app/features/play/draw_stock.py`, `apps/api/app/features/play/draw_rec.py`(주석·설명에 "30일" 재사용 표현이 있으면 맞춘다)
- Test: `apps/api/app/features/play/tests/test_draw_stock.py`

**Interfaces:**
- Produces: `stock_variants(db, word, now)` 는 기간 필터 없이 그 단어의 저장된 그림을 오래된 것부터 돌려준다(시그니처 유지). `add_variant` 는 만료 삭제 없이, 이미 3종이면 가장 오래된 것만 지우고 추가한다. `STOCK_DAYS` 상수는 삭제한다.

- [ ] **Step 1: 시험 수정** — `test_stock_variants_only_within_30_days` 를 `test_stock_variants_keep_old_pictures`(100일 전 그림도 나옴)로 바꾸고, 만료 삭제를 확인하던 시험(50행 근처)은 "오래된 것도 안 지워지고 3종 초과 때만 가장 오래된 것이 대체됨"으로 고친다. 파일 상단 설명(`30일 재사용`)도 맞춘다.
- [ ] **Step 2: 실패 확인** — `pytest app/features/play/tests/test_draw_stock.py` → 수정한 시험 FAIL.
- [ ] **Step 3: 구현** — 위 Interfaces 대로. 설명 문구(모듈 docstring 등)에서 30일을 지운다.
- [ ] **Step 4: 통과 확인** — `test_draw_stock.py` 와 `test_draw_rec_assemble.py`(저장소 재사용 시험) 실행, `ruff check` 통과. `STOCK_DAYS` 참조가 남았는지 `grep` 으로 확인.
- [ ] **Step 5: 커밋** — 변경한 파일만 `git add` → `git commit -m "feat(play): 이게뭐게 저장된 그림 보관 기간 제거"`

### 마무리(구현 뒤, 사용자 승인 뒤에만)
- 커밋하지 않은 로컬 파일 3개가 커밋에 안 들어갔는지 `git show --stat` 로 확인한다.
- 앱 `apps/mobile` 이 개수(이게뭐게 5개·골든벨 개수)에 의존하는지 `tests/playdrawrec.test.js`·`playground.test.js`·화면 코드를 읽어 확인한다(서버만 바꾸므로 깨지지 않을 것으로 보지만 확인 대상). 깨질 만한 곳이 있으면 구현을 멈추고 사용자에게 알린다.
- HISTORY·STATS·wiki 를 한 세트로 갱신한다(확정 결과만). 푸시·PR 은 사용자 지시를 기다린다. PR 제목은 `feat(play): 골든벨 이게뭐게 가비추천 사용자마다 다르게 처리`, 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 양식(무엇을/왜/테스트/참고).
