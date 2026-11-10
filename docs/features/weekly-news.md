# 구현 현황: 주간 가족 뉴스

- 상태: 진행 중 (T26-a1: 주 경계·근거 검증기만)
- 담당: Seungdeuk
- 요구사항: docs/requirements/weekly-news.md

## 구현된 것
서버 `apps/api/app/features/weekly_news/` — LLM·DB·API 없이 시험할 수 있는 순수 함수만 있다. 라우터 등록·표·화면은 아직 없다.
- `week.py`: 주 경계(서비스 시간대 `ai_day_utc_offset_hours`, 기본 KST 월~일)와 허용 범위. `week_start_of`(월요일), `week_end_of`(일요일), `validate_week`(월요일이 아니거나 미래 주이거나 8주 전보다 오래되면 400 `invalid_week`), `ready_to_generate`(이번 주는 일요일 `READY_HOUR`=18시 이후만, 지난 주는 항상, 미래 주는 불가). 모두 `now` 를 인자로 받는다.
- `evidence.py`: 근거 목록 만들기 `build_sources`(약속 e1.., 할 일 t1.., 문서 d1.. 불투명 id, 날짜→시간→ref 순이라 같은 입력이면 같은 id·순서, 메모·장소·본문 없음)와 문장 검증기 `validate`(없는 근거 id·빈 근거·재료에 없는 숫자·인용 근거에 없는 구성원 이름·길이/중복/개수 상한 위반 문장을 버리고, 제목이 실패하면 고정 제목, 남은 문장이 없으면 `Failed(reason)`). 규칙의 한계(숫자·이름은 단순 비교)는 모듈 docstring 에 적어 두었다.
- 시험: `tests/test_week.py`, `tests/test_evidence.py`.

## 남은 것
- T26-a2: 재료 수집(내 줄의 공유 일정·완료한 공유 할 일·민감 제외 문서, 1:1 방 제외).
- T26-a3: 새 표 `member_weekly_news`(Alembic)·모델·`GET` 읽기와 별도 `POST` 생성 API·권한 시험.
- T26-b: LLM 호출(`app/shared/llm`, `ai_guard`, 가명화)·폴백·평가셋.
- T26-c: 앱 "가족 뉴스" 영역(시안 확인 필요).
- T26-d: 가족을 나갈 때 본인 뉴스 삭제, `group_purge` 포함.
