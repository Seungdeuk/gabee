# 메인 Agent 하이브리드 라우팅 — 구현 현황

요구사항: [docs/requirements/main-hybrid-routing.md](../requirements/main-hybrid-routing.md)

## 상태 (2026-11-27)
- 구현: 규칙 기반 출처 판정(`apps/api/app/features/ai_assistant/routing.py`), 모델 도구 목록 줄이기와 실행 게이트(`knowledge/rag_chat.py`), 설정 `MAIN_ROUTING_MODE`(기본 `off`), 평가 관찰 `eval_hook.observe_routing_block`.
- 운영 영향: 기본 `off` 라 없음. `shadow`·`enforce` 는 실모델 국소 평가와 승인 뒤에 켠다.

## 구조
1. `routing.decide(question, audience)` → `Decision(sources, rule)`. 출처 표현 사전과 채널만 보고, 새 LLM 호출은 없다. 애매하면 `unclear`(제한 없음).
2. `enforce`: 모델에 보내는 `ask_*` 목록에서 허용 밖 담당을 뺀다.
3. `_handle_calls` 게이트: 허용 밖 담당 호출을 `shadow` 는 기록만 하고, `enforce` 는 실행하지 않고 "이 질문에는 이 담당을 쓰지 않습니다"를 도구 결과로 돌려준다.
4. 기록은 평가 관찰(`Recording.routing_blocks`: stage·mode·name·rule)에만 남기고, 질문 문장은 넣지 않는다. 운영 로그에는 남기지 않는다. `Observation` 형식은 바꾸지 않았다.
5. 1:1 방의 일정 차단(`agents.call`)은 그대로이고, 라우팅이 허용해도 먼저 적용된다.

## 검증
- 새 시험 `ai_assistant/tests/test_main_hybrid_routing.py`: 판정(일반화 문장), 세 모드의 게이트, 도구 목록, 설정 검증.
- dev 36사례의 질문에 판정을 적용했을 때 정답 `ask_*` 를 허용 밖으로 둔 사례 0건.
- Fake Runner dev 36사례: off·shadow 모두 35/36. 실패 1건(routing-01 `answer_mismatch`)은 수정 전 `release/1.4` 에서도 같다. shadow 에서 막았을 호출 0건(Fake 스크립트는 정답 도구만 부른다).

## 실모델 국소 평가 (2026-11-27, 승인 범위 안, 합성 데이터)
- 같은 코드에서 `off` 와 `enforce` 를 따로 실행했다. `cases_dev.json`(공식) 9사례 × 3회, claude-haiku-5-5. 두 번에 나눠 돌렸고 각 실행 결과는 합산하지 않는다.
  - 1차 `hybrid-local-{off,enforce}-r1`: routing-01·02, chat-02·03. chat-03 보안 위반 판정으로 자동 중단(off 10/27, enforce 11/27 실행).
  - 2차 `hybrid-local-{off,enforce}-r2`: compound-01~03, isolation-01·03(30회 모두 실행).
  - 비용: 1차 $0.1303, 2차 $0.2009, 합계 $0.3311(모드별 승인 한도 각 $1.00).
- 결과는 `evals/agent_eval/results/`(git 추적 제외)에 있다.

| 사례(판정) | off | enforce |
|---|---|---|
| routing-02 (chat_history) | 일정 Agent 실행 2/3, 평균 입력 43.9K 토큰 | 일정 Agent 실행 0/3, 평균 32.4K. 1회는 모델이 요청해 게이트가 막음 |
| chat-03 (chat_history+family_todo) | 1회 중 1회 일정 조회 실행 | 2회 중 0회. 1회는 요청이 나와 막음 |
| routing-01 (schedule_tab) | 일정 Agent 3/3 | 3/3(필요 도구를 막지 않음) |
| chat-02·compound-01~03·isolation-01·03 (unclear 또는 복합) | — | 막은 호출 0건(판정상 제한 없음 또는 모두 허용) |

- 필요한 도구를 막은 호출: 0건(막은 4건 모두 출처가 대화로 명시된 질문의 `ask_schedule`).
- 모델은 도구 목록에서 뺀 `ask_schedule` 도 요청한다. 시스템 프롬프트에 그 이름이 남아 있기 때문으로 보인다. 그래서 목록 줄이기만으로는 부족하고 실행 게이트가 필요하다.
- chat-03 의 보안 위반 판정(`common[12]` scope_leak)은 최종 평가 보고서 7절의 채점기 대리 조건 문제와 같은 유형으로 판단한다. enforce 에서는 막힌 요청도 "호출"로 기록돼 대화 유래 면제가 꺼졌지만, 일정 조회(`schedule.query`)는 실행되지 않았다. 공식 기록·채점기는 바꾸지 않았다.
- compound-02 는 판정이 `unclear`(제한 없음)라 off·enforce 의 도구 목록·실행 경로가 같다. 그런데도 enforce 실행에서 `missing_tool` 2/3 이 나왔다(off 는 0/3). 라우팅 효과가 아니라 모델 변동으로 보며, 사례당 3회라 이 차이는 변동 범위 안일 수 있다.
- answer_mismatch(routing-01, compound-01)는 두 모드 모두에서 나왔고 도구 호출은 같다(답 표현 문제).

## 남은 일
- 운영에서 켜기 전: 막힌 호출을 채점에서 어떻게 셀지(요청과 실행을 나눌지) 평가 쪽 정리가 필요하다(채점기 변경은 별도 승인).
- 시스템 프롬프트에 담당 도구 이름이 남아 모델이 목록 밖 도구를 요청하는 문제. 프롬프트 변경은 별도 PR·평가로 한다.
- 출처 표현이 없는 질문(isolation-01·chat-02)은 `unclear` 라 그대로다. 가족방 unclear 규칙은 shadow 기록을 본 뒤 정한다.
