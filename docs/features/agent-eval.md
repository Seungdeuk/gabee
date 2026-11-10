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

## 알려진 한계
- 정규식 매처는 사례 작성자가 쓴 패턴을 그대로 쓴다. 중첩 수량자(`(a+)+` 같은 역추적이 폭발하는 패턴)를 거부하는 검사는 E5 사례 검증 시험에서 한다(아직 없음).

## 남은 것
- E2b: 채점기(`score_case`).
- E2c: 지표(윌슨 구간·집계), 비용 계산, 결과 저장, 스크러버.
- E3: 평가 전용 관찰 훅(`shared/llm/tool_graph.py`, `schedule/agent/chat.py`).
- E4: 시드, L2 실행기, 기존 52건 어댑터.
- E5: 1단계 사례 50~100건과 사례 검증 시험.
- E6: L1 고정 응답 모드. E7: 1단계 베이스라인. E8: 루프 실행기.
- E9 이후: 2·3단계 사례 확장(단계마다 사용자 승인).
