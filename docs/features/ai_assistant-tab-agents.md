# 구현 현황: 탭 에이전트 (정산·돌봄을 메인 에이전트가 묻는 구조)

- 상태: 1단계(읽기 전용) 구현. 단위 테스트는 가짜 LLM, 탭 에이전트 직접 평가는 실제 Haiku 5.5 로 10/10(1회).
- 근거: 멘토링 정리(2026-10-26) "메인 에이전트는 가급적 DB 를 직접 조회하지 않고, DB 와 관련된 기능은 서브 에이전트가 맡는 멀티 에이전트"
- 요구사항: docs/requirements 에 billing·care 문서가 없어 사용자(팀원)와 대화로 범위를 정했다.

## 구조

```
POST /ai-assistant/chat
  메인 에이전트(rag_chat.ask) — 도구: search_knowledge / get_item / list_items / ask_billing / ask_care
     ├─ ask_billing(question) → 정산 에이전트(billing/agent.py) → 읽기 도구 7개 → billing.service → DB
     └─ ask_care(question)    → 돌봄 에이전트(care/agent.py)    → 읽기 도구 8개 → care.service    → DB
```

- 메인은 가계·돌봄 DB 를 읽는 도구가 없다. 질문을 한국어 문장으로 탭 에이전트에게 넘기고 받은 답을 사용자에게 전한다.
- 탭 에이전트는 자기 탭의 `service` 함수만 읽기 전용 도구로 쓴다. `group_id`·사용자는 서버가 도구에 묶어 두고 LLM 은 월·날짜 같은 조회 조건만 정한다.
- 라우터를 거치지 않으므로 탭 에이전트는 호출 전에 `ensure_group_member` 를 실행한다(`docs/contracts/permissions.md`).
- 공통 도구 호출 루프는 `app/shared/llm/agent.py`(Anthropic Messages API, 모델은 `ANTHROPIC_MODEL`, 기본 Haiku). 새 의존성은 없다.
- 탭 에이전트가 실패하면 `can_answer: false` 로 돌려주고 메인이 확인하지 못했다고 안내한다.

## 탭 에이전트와 직접 대화 (멘토링: "서브 에이전트는 채팅이 되도록 만들어 통째로 메인에 붙인다")

- `POST /billing/agent/chat`, `POST /care/agent/chat` — 요청 `{message, history[≤10]}`, 응답 `{reply, source(ai|fallback), tool_calls[]}`. 메인 에이전트를 거치지 않고 그 탭 에이전트에게 바로 묻는다(읽기 전용).
- 가족 구성원만 쓴다(`current_group_id`). 하루 100회 한도는 사용자별 프로세스 메모리 기준(`shared/llm/agent_chat.py`), 초과 시 429 `daily_limit`. API 키가 없으면 200 + `source: fallback`.
- 처리 공통 코드는 `shared/llm/agent_chat.py`, 요청·응답은 `shared/llm/schemas.py`, 탭별 `ask(..., history=)` 가 앞 대화를 LLM 에 전달한다.
- 실제 LLM 으로 이 엔드포인트를 호출해 보는 시험은 아직 안 했다(테스트는 가짜 LLM). 앱 화면·웹 테스트 페이지는 없다.

## 도구

| 에이전트 | 도구 |
|---|---|
| 정산 | get_month_summary, list_expenses, get_settlement, get_settlement_manager, list_subscriptions, get_upcoming_payments, list_allowances |
| 돌봄 | get_daily, get_today_summary, list_records, get_recommendations, get_meal_suggestions, list_meal_log, get_meal_log_summary, get_family_locations |

## 알아둘 점

- **외부 전송**: 탭 에이전트의 도구 결과(지출 내역·금액·구성원 이름·용돈 장부·돌봄 기록·동의한 구성원의 위치 좌표)가 가려지지 않은 채 Claude API 로 간다. 업로드 기록(knowledge)은 가린 글자만 가는 것과 다르다. 위치는 동의한 사람의 좌표만 나간다(`care.service.latest_locations`).
- 일부 읽기 함수는 화면을 열 때와 같은 부수 효과가 있다: `list_allowances` 는 지급일이 지난 자동 용돈을 입금으로 기록하고, 돌봄 `daily` 는 기본 항목이 없으면 만든다.
- 하루 AI 호출 한도(`DAILY_LIMIT`)는 채팅 요청 1건을 1회로 센다. 탭 에이전트 호출은 메인 도구 호출 횟수(`MAX_STEPS=4`) × 탭 에이전트 단계(4)로 제한된다.
- `service.chat` 은 `active_group_id` 를 그대로 쓰지만, 탭 에이전트는 `group_members` 로 멤버십을 다시 확인한다.
- 질문 분류와 "무조건 탭 에이전트를 쓴다"는 프롬프트 기반이라 강제는 아니다. 평가셋은 evals/tab_agents 에 10개(작음).

## 아직 안 한 것 (다음 단계)

- 쓰기 도구(지출 등록, 용돈 승인 등): "제안 → 사용자 확인 → 실행" 두 단계로 추가. 멘토링은 서브 에이전트가 등록도 할 수 있어야 한다고 했다.
- 앱/웹 테스트 화면(단독 채팅 엔드포인트는 만들었다), 평가셋 확대(후속 질문·주입 사례 추가는 완료).
- 일정·소통·자료정리 에이전트, 여러 탭의 데이터를 종합하는 추천.
- 채팅 응답에 어느 에이전트·도구를 썼는지 표시.

## 평가셋 (evals/tab_agents)

- `cases.json`: 정산 6·돌봄 4 사례 + 메인 라우팅 4 사례(agent=main)(질문, 기대 도구, 답에 있어야 할 값). 쓰기 요청은 도구 없이 "직접 해 주세요"로 안내하는지 본다.
- `seed.py`: 가짜 가족 데이터. `tests/test_tab_agent_eval_cases.py` 가 기대 도구의 실제 출력에 기대값이 있는지 LLM 없이 확인한다(평가셋 자체의 정답 검증).
- `run.py`: 실제 LLM 평가(`cd apps/api && python -m evals.tab_agents.run [--case id] [--repeat n]`, ANTHROPIC_API_KEY 필요, 임시 SQLite 만 사용). 키가 없으면 건너뛴다. 2026-10-26 Haiku 5.5: 탭 에이전트 직접 10개 + 메인 라우팅 4개, 각 3회 반복 = 42/42 통과(메인 라우팅: ask_billing / ask_care / 둘 다 / 스몰톡은 탭 에이전트 호출 없음). 사례 수가 적고 문장 품질은 채점하지 않는다.
- 한계: 탭 에이전트 직접 평가와 메인 라우팅 평가를 모두 포함하지만 사례가 적어 통계적 결론은 못 낸다.
