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

## 남은 일
- 실모델 국소 평가(`enforce`, 과잉 라우팅 사례 isolation-01·03, chat-02·03, compound 와 반대 사례 × 3회): 비용 승인 필요.
- 현재 규칙으로 줄어드는 사례는 출처가 명시된 질문(예: chat-03)뿐이다. isolation-01·chat-02 처럼 출처 표현이 없는 질문은 `unclear` 라 그대로다. 가족방 unclear 규칙은 shadow 기록을 본 뒤 정한다.
