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

## 보강 (2026-11-27, 커밋 f26e10da)
국소 평가 뒤 사용자 결정으로 세 가지를 더했다.
1. **enforce 프롬프트 한 줄**: 출처가 정해진 질문에만 시스템 프롬프트 끝에 "이번 질문에서 쓸 수 있는 담당 에이전트는 …뿐"을 붙인다. off·shadow 는 그대로다.
2. **막은 호출은 오류 결과**: 서버가 실행하지 않은 담당 호출은 오류(`is_error`)로 돌려주고 관찰에도 오류로 남긴다. 공식 채점기는 바꾸지 않았다. 막힌 요청도 계속 "호출"로 세는 보수적 규칙이다.
3. **가족방 기본 규칙**: 가족방 @가비 질문에 출처·일정·장부 표현이 없으면 그 방 대화(`ask_family_chat`)만 허용한다(`room:default_chat`, 설계 메모 6절). 쓰기·앞 대화 가리킴은 계속 unclear 다.

## dev 36사례 실모델 재평가 (2026-11-27, 커밋 f26e10da)
- 공식 `cases_dev.json` 36사례 × 3회, claude-haiku-5-5. 같은 커밋에서 off 와 enforce 를 9사례씩 4묶음으로 나눠 묶음마다 번갈아 실행했다(`hybrid-dev36-{off,enforce}-b1~b4`, 묶음당 승인 $1.00).
- 비용: off $0.3702(97회), enforce $0.3712(108회), 합계 $0.7414.
- off 의 b2 는 chat-03#0 보안 위반 판정(`common[12]` scope_leak, 앞 절과 같은 채점기 대리 조건)으로 자동 중단돼 11회(chat-03 r1·r2, docs-01~03 × 3)가 미실행이다. enforce 는 108회를 모두 실행했다.
- 아래 표는 **양쪽 모두 실행된 같은 97회**로 비교한 값이다(Precision 은 공식 `metrics.summarize` 정의).

| 지표 | off | enforce |
|---|---|---|
| Task Success | 86/97 (88.7%) | 83/97 (85.6%) |
| Tool Precision | 73/103 (70.9%) | 73/98 (74.5%) |
| Tool Recall | 73/74 (98.6%) | 73/74 (98.6%) |
| 불필요한 담당 호출이 있던 실행 | 15 | 10 |
| 보안 위반 판정 실행 | 1 (chat-03) | 0 (108회 전체에서도 0) |
| 평균 입력 토큰 / 모델 호출 수 | 30.5K / 3.55 | 27.6K / 3.38 |
| 지연 P50 | 4.70초 | 4.64초 |

- 서버가 막은 호출(`routing_blocks`)은 enforce 108회에서 0건이다. 프롬프트 한 줄을 붙인 뒤로 모델이 허용 밖 담당을 요청하지 않았다. 그래서 요청 기준과 실행 기준의 불필요한 호출 수가 같다.
- 사례별로 바뀐 것
  - chat-02: 불필요한 담당 호출 3/3 → 0/3(가족방 기본 규칙).
  - chat-03: 0/1 통과 → 3/3 통과, 불필요한 호출 1 → 0.
  - p1to1-01: 불필요한 호출 1 → 0.
- 그대로인 것: isolation-01·03, compound-03 의 일정 Agent 동시 호출. 개인 채팅이고 출처가 애매해 unclear 다.
- **Task Success 는 개선되지 않았다(−3.1%p).** 실패는 모두 `answer_mismatch`(10 → 14)와 `missing_tool` 1건이다. 도구 호출이 같은데 답 표현이 기대와 다른 경우다.
  - 라우팅이 판정한 사례: 49/58 → 47/58(answer_mismatch 8 → 11).
  - 판정이 unclear 라 off 와 실행 경로·프롬프트가 같은 사례: 37/39 → 36/39.
  - 사례당 3회라 이 차이를 변동과 구분할 수 없다. 다만 프롬프트 한 줄이 답 표현에 영향을 줬을 가능성은 배제하지 못했다(ambig-02·isolation-02·schedq-03 이 판정 사례이고 각 1~2회 줄었다).
- 한계: 개발셋(dev)만 썼고 val·test 는 미실행이다. 사례당 3회라 사례 단위 1회 차이는 변동 범위 안일 수 있다. 앞 절 국소 평가(r1·r2)와는 커밋이 달라 합산하지 않는다.

## 남은 일
- answer_mismatch 증가가 프롬프트 한 줄의 영향인지 확인: 같은 사례를 반복 수를 늘려 다시 재야 한다(비용 승인 필요).
- 개인 채팅의 출처 표현이 없는 질문(isolation-01·03, compound-03 의 일정 동시 호출)은 그대로다.
- 운영 enforce 전환은 위 확인과 승인 뒤에 한다(기본 off 유지).
