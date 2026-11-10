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

## 알려진 한계
- 오류로 끝난 호출은 `calls` 항목에 대응되지 않는다. `tool_error` 사례의 호출 확인은 `tools.required` 로 한다. 쓰기 도구를 `tools.required` 에만 적었거나 기대 도구가 공통 금지 도구와 겹치는 사례는 `score_case` 가 `ValueError` 로 알린다.
- 공통 금지 문자열은 조건 없이 검사한다. 1:1 방 안의 답처럼 예외가 필요한 사례는 호출하는 쪽(E4)이 사례마다 공통 조건을 맞춰 넘긴다.
- 정규식 매처는 사례 작성자가 쓴 패턴을 그대로 쓴다. 중첩 수량자(`(a+)+` 같은 역추적이 폭발하는 패턴)를 거부하는 검사는 E5 사례 검증 시험에서 한다(아직 없음).
- 대체된 앞선 호출은 E3 훅이 `superseded` 로 표시해야 쓰기로 세지 않는다(표시가 없으면 추가 쓰기로 센다). 인자 값이 dict 이면(`changes` 등) 매처가 맞지 않아 E3 에서 평탄화가 필요하다.

## 남은 것
- E2c: 지표(윌슨 구간·집계), 비용 계산, 결과 저장, 스크러버.
- E3: 평가 전용 관찰 훅(`shared/llm/tool_graph.py`, `schedule/agent/chat.py`).
- E4: 시드, L2 실행기, 기존 52건 어댑터.
- E5: 1단계 사례 50~100건과 사례 검증 시험.
- E6: L1 고정 응답 모드. E7: 1단계 베이스라인. E8: 루프 실행기.
- E9 이후: 2·3단계 사례 확장(단계마다 사용자 승인).
