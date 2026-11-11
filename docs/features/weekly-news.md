# 구현 현황: 주간 가족 뉴스

- 상태: 진행 중 (T26-a1: 주 경계·근거 검증기, T26-a3: 새 표·읽기 API 스켈레톤)
- 담당: Seungdeuk
- 요구사항: docs/requirements/weekly-news.md

## 구현된 것
서버 `apps/api/app/features/weekly_news/` — 순수 함수(a1)와 저장 표·읽기 API(a3)가 있다. 생성(LLM)과 화면은 아직 없다.
- `week.py`: 주 경계(서비스 시간대 `ai_day_utc_offset_hours`, 기본 KST 월~일)와 허용 범위. `week_start_of`(월요일), `week_end_of`(일요일), `validate_week`(월요일이 아니거나 미래 주이거나 8주 전보다 오래되면 400 `invalid_week`), `ready_to_generate`(이번 주는 일요일 `READY_HOUR`=18시 이후만, 지난 주는 항상, 미래 주는 불가). 모두 `now` 를 인자로 받는다.
- `evidence.py`: 근거 목록 만들기 `build_sources`(약속 e1.., 할 일 t1.., 문서 d1.. 불투명 id, 날짜→시간→ref 순이라 같은 입력이면 같은 id·순서, 메모·장소·본문 없음)와 문장 검증기 `validate`(없는 근거 id·빈 근거·재료에 없는 숫자·인용 근거에 없는 구성원 이름·길이/중복/개수 상한 위반 문장을 버리고, 제목이 실패하면 고정 제목, 남은 문장이 없으면 `Failed(reason)`). 규칙의 한계(숫자·이름은 단순 비교)는 모듈 docstring 에 적어 두었다.
- 시험: `tests/test_week.py`, `tests/test_evidence.py`.
- T26-a3 새 표·읽기 API: 표 `member_weekly_news`(모델 `models.py`, Alembic 리비전 `8b4e2a71c9d3`, 추가 전용)에 구성원 한 명의 한 주 뉴스를 저장한다 — `(group_id, user_id, week_start)` 유일, 상태 `ok|failed|pending|empty`, 본문·근거는 JSON, 외래키 2개는 ON DELETE CASCADE. `GET /report/news?week_start=YYYY-MM-DD`(비우면 이번 주 월요일)는 **저장본을 읽기만 하고 만들지 않는다**: 저장본이 있으면 상태를 `ready|pending|failed|empty` 로 바꿔 돌려주고, 없으면 이번 주이면서 아직 일요일 18시 전이면 `too_early`, 그 밖은 `not_generated`. 월요일이 아니거나 미래 주·9주 전은 400 `invalid_week`. 조회 키는 `(current_group_id, 로그인한 본인, 주)` 로 고정이라 다른 구성원·다른 가족의 저장본은 `not_generated` 와 구분되지 않는다. 응답은 `status, week_start, week_end, title, items, sources, generated_at, ai_generated, model` 뿐이고 프롬프트 버전·토큰 수·오류 코드는 내보내지 않는다. 가족 삭제(`group_purge`)에는 `group_id` 열로 자동 포함된다. 이 표가 없는 DB 에서는 이 API 만 503(`weekly_news` 기능)이다. 시간은 의존성 `current_time` 으로 고정해 시험한다.
- 시험: `tests/test_week.py`, `tests/test_evidence.py`, `tests/test_news_api.py`(저장본 매핑·본인만·주 검증·too_early·UNIQUE·가족 삭제·스키마 게이트), PostgreSQL `apps/api/tests/test_weekly_news_pg_e2e.py`(`GABEE_PG16_E2E=1`).

## 남은 것
- T26-a2: 재료 수집(내 줄의 공유 일정·완료한 공유 할 일·민감 제외 문서, 1:1 방 제외).
- T26-a3 후속: 별도 `POST` 생성 API(경로·필드)는 T26-b 와 함께 정한다. 읽기 API 는 구현됨.
- T26-b: LLM 호출(`app/shared/llm`, `ai_guard`, 가명화)·폴백·평가셋.
- T26-c: 앱 "가족 뉴스" 영역(시안 확인 필요).
- T26-d: 가족을 나갈 때 본인 뉴스 삭제, `group_purge` 포함.
