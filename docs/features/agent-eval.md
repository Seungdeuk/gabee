# 구현 현황: Agent 평가·개선 루프

- 상태: 진행 중
- 담당: Seungdeuk
- 요구사항: docs/requirements/agent-eval.md (결정: docs/adr/0016-agent-eval-loop.md)

## 구현된 것
- E1: 요구사항 문서와 ADR 0016 (병합).
- E2a-1: `apps/api/evals/agent_eval/matchers.py`
  - 인자 매처 `eq`·`contains`·`regex`·`date_range`·`any_of`와 쉼표를 무시하는 `text_contains`. 실제 값이 없음(None)이거나 dict 이면 항상 불일치.
  - `date_range` 는 문자열만 받고, 날짜 뒤 시간까지 ISO 형식 전체가 유효해야 한다(`YYYYMMDD`·주차 표기·범위 표기는 불일치).
  - 시험: `apps/api/tests/agent_eval/test_matchers.py` (L0, LLM·DB 없이 실행).
- E2a-2: `schema.py`
  - 사례(`Case`, 분할 `dev|val|test|legacy`, `scenario`, 기대 호출 `calls`)와 관찰 결과(`Observation`, `ToolCall`: 오류 여부 `is_error`, 대체 여부 `superseded`) 형식. 엄격한 타입(`strict`)이다.
  - 합성 표시가 없거나, 매처 값이 잘못됐거나, 빈 문자열·쉼표뿐인 값·모순(필수·기대 도구가 금지 도구나 금지 쓰기와 겹침 등)이 있는 사례는 불러올 때 거부한다. 정규식 오류는 `re.error` 뿐 아니라 `OverflowError`·`RecursionError` 도 `ValidationError` 로 바꾼다.
  - 시험: `apps/api/tests/agent_eval/test_schema.py`.
- E2b: `scoring.py`의 `score_case(case, observation, common_security)`
  - 도구(`agent_path` 단계만)·기대 호출(`calls`)·결과·답 문장·보안을 채점한다. 기대 호출마다 서로 다른 관찰 호출 하나가 대응해야 하고(최대 일치), 그 호출이 항목의 매처를 모두 만족해야 한다. `common_security` 는 호출하는 쪽이 반드시 넘긴다.
  - 보안은 모든 단계의 호출을 본다. 쓰기 도구는 도구 이름·단계가 같은 기대 호출 항목 수만큼만 허용하고 나머지는 승인 없는 쓰기다(인자가 틀린 호출은 인자 오류이지 위반이 아니고, 오류로 끝났거나 대체된 호출은 쓰기로 세지 않는다). 금지 문자열은 답·제안과 쓰기 도구·`check_args_of` 도구의 인자에서 찾고, 7자리 이상 숫자(전화번호)는 숫자 사이 구분자만 허용해 찾는다.
  - 위반 문구는 원문을 되풀이하지 않고 `tool:`·`write:`·`common[i]`·`case[i]` 로만 적는다. 실패 유형은 기계적으로 정해지는 것(wrong_tool, missing_tool, arg_error, unapproved_write, scope_leak, step_limit)만 낸다.
  - 시험: `apps/api/tests/agent_eval/test_scoring.py`.
- E2c-1: `metrics.py`의 `summarize(runs)`
  - Task Success Rate(실행 단위, 신뢰구간 없음)와 pass@all(사례 단위, 반복이 모두 통과, 윌슨 95% 구간)을 따로 낸다. 도구 선택·인자 정확도(사례 기준), 도구 이름 정밀도·재현율, 보안 위반 수, 같은 도구 집합 일관성, 효율(평균·p50/p95·토큰 합), 범주·상황 유형별 분해, 실패 파레토, `as_rows()`.
  - 사례 id 불일치·중복, 분할 혼합 입력은 `ValueError`. 시험: `test_metrics.py`.
- E2c-2: `cost.py`
  - 공식 가격표로 호출별 비용을 `Decimal` 로 계산(Haiku 5.5 는 10만 토큰 초과 구간 단가). `Ledger` 가 호출별 사용량(`CallUsage`)과 누적 비용을 기록하고, 실행 2 / 베이스라인 5 / 루프 15 / 전체 40달러 범위별 상한을 넘으면 `BudgetExceeded`. 누적 범위는 시작 값(opening)이 필수이고 `spawn` 으로 풀을 공유한다. 토큰 상한은 가장 비싼 출력 단가로 보수적으로 잡는다. 시험: `test_cost.py`.
- E2c-3: `scrub.py`, `store.py`
  - 스크러버는 기존 개인정보 탐지기 `detect` 를 재사용(전화·이메일·주민번호·카드·계좌·비밀 값). 결과는 `results/<run_id>/` 6개 파일로 허용 필드만 저장하고(합성 사례만, 값 형식 검사, 인자·답 스크러빙 후 자름), 임시 폴더에 쓴 뒤 옮기며 기존 실행은 덮어쓰지 않는다. `opening_spent` 가 manifest 에서 범위별 합을 복원한다. `results/` 는 git 제외. 시험: `test_scrub.py`, `test_store.py`.
- E3: `app/shared/llm/eval_hook.py`(새 파일), `tool_graph.py`, `schedule/agent/chat.py`
  - 평가가 `eval_hook.recording()` 으로 켠 동안만 도구 호출(이름·평탄화한 인자·단계·오류 여부)과 루프의 모델 호출 수·토큰·단계 상한 도달을 메모리에 기록한다. 켜지 않으면 아무 일도 하지 않고(운영 동작 불변), 기록은 로그·파일·외부로 나가지 않는다. 평가 패키지를 가져오지 않는다.
  - `tool_graph.Run.stage` 로 호출한 쪽이 단계를 넘기고, 비어 있으면 기록하지 않는다. 일정 구조화 출력은 `schedule.<intent>`(not_schedule 제외) 호출로 담고, 같은 질문을 다시 분류하면(need_wider) 앞선 호출을 `superseded` 로 표시한다.
  - 시험: `test_eval_hook.py`(꺼져 있을 때 동작 불변, 기록 내용, 인자가 틀리면 채점 실패).
- E4a: `evals/agent_eval/{env,network,clock,runs_guard,write_tools,estimate}.py`, `test_runs.json`(운영 코드 변경 없음)
  - `env.py`: 앱이 쓰는 DB·엔진·환경변수·데이터 폴더가 모두 허용 폴더 아래 SQLite 파일이어야 시작한다(PostgreSQL·공용 DB·다른 폴더·`:memory:` 거부). 사례마다 모든 테이블(분석 캐시 `ai_result_cache`, 기억, 일정)과 메모리 상태(일정 되묻기 초안 `schedule.agent.ask._pending`, 속도 제한기)를 비운다. AI 하루 한도를 올리고 웹 검색을 끄며, 끝나면 되돌린다.
  - `network.py`: 평가 중 이 컴퓨터 밖으로의 소켓 연결·이름 조회를 막는다(푸시·메일·소셜 로그인 같은 외부 쓰기 방지). 실제 모델을 쓸 때만 호스트를 이름으로 허용한다.
  - `clock.py`: 운영 코드에 시계를 주입할 자리가 없어서, 평가 프로세스 안에서만 `app.` 모듈의 `datetime`·`date` 이름을 기준 시각(2026-11-10 12:00 KST)에서 출발하는 시계로 바꿔 끼우고 끝나면 되돌린다.
  - `runs_guard.py`: `test_runs.json` 을 읽기 전에 확인·예약한다. 이력 파일이 없거나 깨지면 멈추고(새로 만들지 않음), 사례마다 baseline 1회·final 1회를 넘기지 못한다. 파일 잠금과 교체 쓰기로 중단·재시작·동시 실행에서도 지킨다(상태 pending→started→done, 끊긴 사례는 다시 돌리지 않는다).
  - `write_tools.py`: Agent 별 쓰기·읽기 도구 목록과 실제 코드와의 대조(`verify_against_code`, 새 도구를 분류하지 않으면 실패). `estimate.py`: 실행 전 비용 추정 요약과 예산 상한 확인.
  - 시험: `test_env*.py`, `test_runs_guard.py`, `test_write_tools.py`, `test_estimate.py`(가짜 모델만, 외부 호출 없음).

## 알려진 한계
- 루프에서 후보를 만든 호출의 사용량도 같은 `loop_id` 실행 기록에 넣어야 `opening_spent` 의 루프·전체 합이 맞는다(호출하는 쪽 E8 이 지킨다). 저장 시험은 합성 값만 쓰고, 실제 실행 결과 저장은 E4 이후에 처음 쓰인다.
- 오류로 끝난 호출은 `calls` 항목에 대응되지 않는다. `tool_error` 사례의 호출 확인은 `tools.required` 로 한다. 쓰기 도구를 `tools.required` 에만 적었거나 기대 도구가 공통 금지 도구와 겹치는 사례는 `score_case` 가 `ValueError` 로 알린다.
- 공통 금지 문자열은 조건 없이 검사한다. 1:1 방 안의 답처럼 예외가 필요한 사례는 호출하는 쪽(E4)이 사례마다 공통 조건을 맞춰 넘긴다.
- 정규식 매처는 사례 작성자가 쓴 패턴을 그대로 쓴다. 중첩 수량자(`(a+)+` 같은 역추적이 폭발하는 패턴)를 거부하는 검사는 E5 사례 검증 시험에서 한다(아직 없음).
- 대체된 앞선 호출은 E3 훅이 `superseded` 로 표시해야 쓰기로 세지 않는다(표시가 없으면 추가 쓰기로 센다). 인자 값이 dict 이면(`changes` 등) 매처가 맞지 않아 E3 에서 평탄화가 필요하다.

## 남은 것
- E4 에서 이어서 할 E3 연결: `rag_chat.py`·`agent.py` 가 `Run(stage=...)` 를 넘기게 하기(지금은 일정 구조화 출력만 기록된다), 되묻기로 끝난 등록에 `eval_hook.mark_last(name, is_error=True)` 표시, 일정 분류 호출의 호출 수·토큰 집계. 기록기는 `contextvars` 라 스레드·이벤트 루프를 넘으면 사라지므로 실행기는 서비스를 직접 호출하거나 요청 안에서 `recording()` 을 연다(기록이 0건이면 실패로 알린다).
- E4b: `stage` 연결·`mark_last` 표시 같은 운영 코드 소폭 수정(수정 전에 대상·영향을 보고하고 승인을 받는다)과 가족방·1:1·일정 시드.
- E4c: L2 실행기와 기존 52건 어댑터. AI 동의는 시드 뒤에 켜므로 E4b·E4c 에서 한다. 실제 모델 호출은 비용 추정을 보여 주고 승인을 받은 뒤에 따로 한다.
- E5: 1단계 사례 50~100건과 사례 검증 시험.
- E6: L1 고정 응답 모드. E7: 1단계 베이스라인. E8: 루프 실행기.
- E9 이후: 2·3단계 사례 확장(단계마다 사용자 승인).
