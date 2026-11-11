# 구현 현황: 주간 가족 뉴스

- 상태: 진행 중 (T26-a1: 주 경계·근거 검증기, T26-a2: 재료 수집 통로, T26-a3: 새 표·읽기 API)
- 담당: Seungdeuk
- 요구사항: docs/requirements/weekly-news.md

## 구현된 것
서버 `apps/api/app/features/weekly_news/` — 순수 함수(a1)와 저장 표·읽기 API(a3)가 있다. 생성(LLM)과 화면은 아직 없다.
- `week.py`: 주 경계(서비스 시간대 `ai_day_utc_offset_hours`, 기본 KST 월~일)와 허용 범위. `week_start_of`(월요일), `week_end_of`(일요일), `validate_week`(월요일이 아니거나 미래 주이거나 8주 전보다 오래되면 400 `invalid_week`), `ready_to_generate`(이번 주는 일요일 `READY_HOUR`=18시 이후만, 지난 주는 항상, 미래 주는 불가). 모두 `now` 를 인자로 받는다.
- `evidence.py`: 근거 목록 만들기 `build_sources`(약속 e1.., 할 일 t1.., 문서 d1.. 불투명 id, 날짜→시간→ref 순이라 같은 입력이면 같은 id·순서, 메모·장소·본문 없음)와 문장 검증기 `validate`(없는 근거 id·빈 근거·재료에 없는 숫자·인용 근거에 없는 구성원 이름·길이/중복/개수 상한 위반 문장을 버리고, 제목이 실패하면 고정 제목, 남은 문장이 없으면 `Failed(reason)`). 규칙의 한계(숫자·이름은 단순 비교)는 모듈 docstring 에 적어 두었다.
- T26-a3 새 표·읽기 API: 표 `member_weekly_news`(모델 `models.py`, Alembic 리비전 `8b4e2a71c9d3`, 추가 전용)에 구성원 한 명의 한 주 뉴스를 저장한다 — `(group_id, user_id, week_start)` 유일, 상태 `ok|failed|pending|empty`, 본문·근거는 JSON, 외래키 2개는 ON DELETE CASCADE. `GET /report/news?week_start=YYYY-MM-DD`(비우면 이번 주 월요일)는 **저장본을 읽기만 하고 만들지 않는다**: 저장본이 있으면 상태를 `ready|pending|failed|empty` 로 바꿔 돌려주고, 없으면 이번 주이면서 아직 일요일 18시 전이면 `too_early`, 그 밖은 `not_generated`. 월요일이 아니거나 미래 주·9주 전은 400 `invalid_week`. 조회 키는 `(current_group_id, 로그인한 본인, 주)` 로 고정이라 다른 구성원·다른 가족의 저장본은 `not_generated` 와 구분되지 않는다. 응답은 `status, week_start, week_end, title, items, sources, generated_at, ai_generated, model` 뿐이고 프롬프트 버전·토큰 수·오류 코드는 내보내지 않는다. 가족 삭제(`group_purge`)에는 `group_id` 열로 자동 포함된다. 이 표가 없는 DB 에서는 이 API 만 503(`weekly_news` 기능)이다. 시간은 의존성 `current_time` 으로 고정해 시험한다.
- 시험: `tests/test_week.py`, `tests/test_evidence.py`, `tests/test_sources.py`(a2), `tests/test_news_api.py`(저장본 매핑·본인만·주 검증·too_early·UNIQUE·가족 삭제·스키마 게이트), PostgreSQL `apps/api/tests/test_weekly_news_pg_e2e.py`(`GABEE_PG16_E2E=1`).

### T26-a2: 재료 수집 통로(다른 기능의 데이터를 기능 경계를 지켜 읽기)
- `app/shared/weekly_sources.py`: `register_provider(name, owner_feature, fn)` 와 `collect(db, group_id, user_id, start, end) -> Collected(records, unavailable, truncated)`. 주인 기능이 시작할 때 읽는 함수를 등록하고(`chat_share` 와 같은 방식) weekly_news 는 `collect` 만 부른다. `SourceRecord` 는 shared 가 기능 폴더를 import 하지 않도록 `evidence.py` 에서 이 모듈로 옮겼다(`evidence.SourceRecord` 로도 그대로 쓸 수 있다).
  - 제공자가 없거나(`schedule`·`documents`), 주인 기능의 표가 준비되지 않았거나(`monitor.status().feature_ready`), 읽다가 예외가 나면 그 재료의 이름만 `unavailable` 에 넣고 나머지는 유지한다(예외는 `db.rollback()` 후 클래스 이름만 로그).
  - 입력 상한: 약속 30·할 일 30·문서 20(`LIMITS`). 종류별로 날짜·시간 순 앞에서 자르고 잘리면 `truncated=True`.
  - 부르는 쪽이 `ensure_group_member` 로 구성원 여부를 먼저 확인해야 한다(제공자는 다시 확인하지 않는다).
- `schedule/news_source.py`(+ `repository.list_week`): 내 줄(+ 주인 없는 옛 줄, 지운 줄 제외)의 **공유 약속**과 **완료한 공유 할 일**. "공유"는 `service.with_sharing` 의 계산 결과(보낸 사람의 원본·받은 사람의 복사본 모두 공유)를 쓴다. `start_date` 범위로 거르고 `start_date` 가 없는 옛 줄은 `starts_at`(서비스 시간대) 로 가른다. 대기(`pending`) 일정도 포함(규칙 기반 리포트와 숫자를 맞추려는 결정). 제목·날짜·시작 시각만 내고 메모·장소·함께하는 사람은 내지 않는다. `schedule/router.py` 가 import 하면 등록된다.
- `ai_assistant/knowledge/news_source.py`: 그 가족의 민감하지 않은 문서함 기록 중 `created_at`(서비스 시간대 날짜)이 그 주 안인 것의 `"<종류 라벨>: <제목>"`·날짜만(본문·가린 글·조각은 읽지 않음). 제목 속 `[가족:<id>]` 는 `family_names.restore` 로 현재 이름(나간 사람은 '가족 구성원')으로 되돌린다. `ai_assistant/router.py` 가 import 하면 등록된다.
- 할 일의 "완료"는 완료 시각이 아니라 **`start_date` 가 그 주인 체크된(`checked=True`) 할 일**이다(규칙 기반 리포트와 같은 기준으로 맞췄다는 뜻이며, 실제로 숫자가 일치하는지는 확인 필요).
- 문서 제목의 `[가족:id]` 는 `restore` 로 실제 표시 이름으로 되돌려 `SourceRecord.title` 에 넣는다. **이 되돌린 구성원 이름도 T26-b 에서 가명화 게이트웨이(`known_names` 에 구성원 표시 이름 전달)를 반드시 다시 거쳐야 외부로 보낼 수 있다.** a3 가 `sources` 를 DB(JSON)에 저장하면 실제 이름(표시용)이 저장된다 — 화면 표시용으로 허용할지, LLM 입력에는 토큰을 유지하고 화면에서만 되돌릴지는 **T26-b 전에 정할 과제**다.
- 호출 순서 계약: 제공자가 실패하면 `collect` 가 `db.rollback()` 을 부르므로, 커밋하지 않은 쓰기가 있는 세션으로 부르지 말고 `collect` 를 먼저 한 뒤 쓰기·커밋한다(T26-b 호출 순서). 세이브포인트는 SQLite·PostgreSQL 차이 위험 때문에 쓰지 않았다.
- **알려진 한계 — 1:1 방과의 어긋남(2026-11-11 사용자 결정: A, 한계로 두고 진행)**: 일정(`events`)에는 방 정보가 없다. 그래서 1:1 방 메시지에서 등록한 공유 일정(앱이 `share_with=[상대]` 로 만든 것, `family_chat.ChatMessageLink` 로 연결)도 `with_sharing` 계산상 공유라서 뉴스 재료에 들어갈 수 있다. 이는 요구사항의 "1:1 방의 모든 것 제외"와 어긋나는 사실이다. 이 수집기는 1:1 방 제외를 보장하지 않으며(이전 현황 문서에 있던 "T26-a2 … 1:1 방 제외" 문구는 이 사실 기록으로 대체했다), 사용자가 2026-11-11 에 "한계로 문서화하고 그대로 진행"(A)으로 결정했다. 일정에 방 정보가 생기면 제외(B)를 후속으로 검토한다.
- 부탁(같이해요)을 수락해서 생긴 일정(`request_id`)도 `with_sharing` 계산상 공유라서 재료에 들어간다. 문서는 `sensitivity` 가 직접 `sensitive` 이거나 종류 라벨이 `SENSITIVE_WORDS`(병원·진료 등)에 걸려 서비스가 민감으로 저장한 것도 빠진다.
- 알려진 한계: 공유한 상대가 복사본을 지워도 보낸 사람의 원본은 계속 공유로 본다(`with_sharing` 계산 그대로). 옛 줄은 `starts_at` 에서 시각을 뽑지 않아 시작 시각이 없다. 주인 없는 옛 원본은 복사본을 받은 사람 쪽에서 보면 공유 상대가 없어 공유로 계산되지 않는다(보낸 쪽은 공유로 계산). 문서 제목에 가려지지 않은 실명이 적혀 있으면 그대로 나간다(가명화는 LLM 호출 단계에서). 문서함은 가족 공유라 같은 가족 구성원의 재료가 같다.

### T26-b 1단계: 검증기 보강·깨진 JSON 방어(생성 API 전 준비)
- 검증기: 단위 접미사 `명·개·번·원·건` 이 바로 붙은 숫자(`11명`·`10번`, 전각·공백 포함)는 날짜·시각 숫자와 겹치면 버리고 건수·호출자가 준 추가 집계·인용 근거 제목의 숫자만 허용한다. 건수와 같은 작은 숫자(`2명`)는 집계와 구분할 수 없어 여전히 통과한다. 이름 비교는 결합 문자(Mn·Me)도 지운 뒤 한다(`김\u0301철수` 우회 차단).
- 리뷰 반영: 숫자를 쪼개는 보이지 않는 결합 문자(CGJ·변이 선택자 등)는 지우고 숫자·단위·이름은 결합 부호를 뺀 사본으로 비교한다. 단위 정규식은 단어 첫 글자(`원격`·`명동`·`건강`·`개학`·`번개`)와 `번째` 를 단위로 보지 않는다. 한계: 존칭 `11분`·`11회`·`11만원`은 검증하지 못하고, `11번 버스` 같은 번호는 단위로 보아 버린다.
- 읽기: 저장된 `body`·`sources` JSON 이 깨졌거나 옛 형식이면 500 이 아니라 `status=failed`(제목·문장·근거 없음)로 돌려준다.

## 남은 것
- T26-a3 후속: 별도 `POST` 생성 API(경로·필드)는 T26-b 와 함께 정한다. 읽기 API 는 구현됨.
- T26-b: LLM 호출(`app/shared/llm`, `ai_guard`, 가명화)·폴백·평가셋.
- T26-c: 앱 "가족 뉴스" 영역(시안 확인 필요).
- T26-d: 가족을 나갈 때 본인 뉴스 삭제, `group_purge` 포함.
