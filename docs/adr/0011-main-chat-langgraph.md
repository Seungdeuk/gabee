# 0011. 메인 AI 채팅의 도구 반복 루프를 랭그래프로 옮긴다

- 날짜: 2026-11-02
- 상태: 적용됨(랭체인 도입의 2단계). 1단계는 [0010](0010-llm-transport.md)

## 맥락

메인 AI 채팅(`ai_assistant/knowledge/rag_chat.py` 의 `ask`)은 "모델이 도구를 부르면 서버가 실행하고 결과를 돌려주는" 반복을
손으로 짠 `for` 문(약 100줄)으로 처리했다. 모델 호출, 도구 실행, 출처 모으기, 직통 응답 판단, 반복 상한이 한 덩어리였다.
앞으로 이 흐름에 개인정보 가리기(질문 가리기·답 복원), 알림, 확인 단계를 끼워야 하고, 탭 에이전트도 같은 모양으로 맞추려 한다.

## 결정

- 반복 흐름을 **랭그래프** 그래프로 옮긴다(`knowledge/rag_graph.py`): `model`(모델 호출) ↔ `tools`(도구 실행) 두 노드.
  도구 호출이 없으면 끝, 직통 응답이거나 모델을 `MAX_STEPS`(4)번 불렀으면 도구 실행 뒤 끝, 그 밖에는 다시 `model`.
- 도구를 실제로 실행하고 출처·쓰기 제안·확인 카드를 모으는 일은 `rag_chat._handle_calls` 에 그대로 둔다(동작 변경 없음).
  그래프는 흐름만 알고, 요청마다 다른 값은 `Run` 으로 `config["configurable"]` 에 넘긴다(그래프는 한 번만 만들어 공유).
- 모델은 `shared/llm/chat_model.py` 의 `PostChatModel`(랭체인 `BaseChatModel`)로 감싼다. 이 클래스는 지금처럼 `post(body)` 를
  부르므로 운영은 `transport.post_messages`(재시도 없음), 시험은 가짜 `post` 를 쓴다. **`rag_chat._post`·`ask(post=...)` 시험 자리와
  `ai_guard` 호출 수 집계가 그대로 유지된다.** 요청 본문(`model`, `max_tokens`, `system`, `tools`, `messages`)은 예전과 같다.
- 의존성은 `langchain-core>=1.6,<2` 와 `langgraph>=1.2,<2` 두 개만 추가한다.

## 하지 않은 것

- **`langchain-anthropic`(`ChatAnthropic`)은 넣지 않았다.** Anthropic SDK 와 별도 HTTP 클라이언트(httpx2)가 들어와 호출 수 집계,
  재시도 정책, 시험의 `httpx.post` 가로채기가 달라진다. 어댑터가 한 자리라 필요하면 그 자리만 바꾼다.
- 탭 에이전트(가계·돌봄·가족채팅·일정)와 `client.complete_json` 은 건드리지 않았다(탭 통합 단계에서 알림과 함께 다룬다).
- 상태 저장소(checkpointer), 스트리밍, 사람 확인 끼우기(interrupt)는 쓰지 않는다.

## 주의

- **랭체인 추적(LangSmith)은 꺼져 있어야 한다.** `langchain-core` 가 클라이언트를 같이 설치하고, 환경변수(`LANGSMITH_TRACING`,
  `LANGCHAIN_TRACING_V2` 등) 하나로 켜지면 질문·도구 결과·답이 외부로 나갈 수 있다(`LANGSMITH_TRACING=false` 만으로는 `LANGCHAIN_TRACING_V2=true`
  가 같이 있을 때 꺼지지 않는다). 그래서 기본값에 기대지 않고 `tool_graph.run_graph` 와 `doc_ai.plan_reminders` 가 `shared/llm/no_trace.py` 의
  `langsmith.tracing_context(enabled=False)` 로 감싸 환경과 상관없이 끈다(안쪽 하위 그래프도 함께 꺼진다).
  `tests/test_rag_graph.py` 가 두 환경변수를 각각 켠 채로 평면·중첩 `run_graph` 와 `plan_reminders` 에서 추적 이벤트가 0건임을 확인한다
  (보호를 빼면 실패함을 확인했다). 운영 환경변수에 추적 관련 값을 넣지 않는다.
- 랭체인 계열은 버전이 빨리 바뀐다. 상한(`<2`)을 두었고, 올릴 때는 `tests/test_rag_graph.py`·`tests/test_llm_chat_model.py` 와
  `ai_assistant` 시험으로 확인한다.
- 운영 이미지(`apps/api/Dockerfile`)는 `pip install .` 로 의존성을 받는다. 이 PC 가상환경에는 이미 설치돼 있었지만 이미지에는 처음 들어가므로
  배포 전에 이미지 빌드와 기동을 한 번 확인한다.

## 결과

- 흐름을 그림으로 볼 수 있다(`GRAPH.get_graph()`). 마스킹·알림 같은 단계는 노드를 추가하고 화살표를 바꾸면 된다.
- 기존 `ai_assistant` 시험 262개가 그대로 통과했고, 어댑터·그래프 시험 32개를 추가했다.
- 코드는 줄지 않았다(반복문 약 99줄 → 그래프 110줄 + 어댑터 138줄). 이득은 앞으로 붙일 단계에서 나온다.

## 갱신 (2026-11-06): 공용 그래프로 옮기고 탭 에이전트 루프도 올렸다

위 "하지 않은 것" 중 탭 에이전트 항목은 일부만 바뀌었다. 본문은 당시 결정이라 그대로 두고, 달라진 점만 적는다.

- 그래프를 `knowledge/rag_graph.py` 에서 **`app/shared/llm/tool_graph.py`** 로 옮겼다(기능끼리 import 하지 않으므로 공용 자리에 둔다). `rag_graph.py` 는 지웠다.
- 메인 채팅은 2026-11-04 에 가명화를 걷어냈다(ADR 0014). 그래프의 `mask`·`restore` 노드와 `Run.mask`·`Run.restore` 는 쓰는 곳이 없어 지웠고,
  그래프는 `START → model → (tools ↔ model) → END` 다. 실제 이름 되돌리기(`ask(restore=)`)는 그래프 밖에서 그대로 한다.
- **가계(지갑)·가족채팅 탭 에이전트의 도구 반복**(`shared/llm/agent.run_agent`)이 같은 그래프 위에서 돈다. 다시 시도하는 기본 `_post`(`retry=True`),
  도구 결과 12000자 제한, `LLMUnavailable` 로의 오류 변환, 횟수를 다 쓰면 오류, 개인정보 엔진 오류 통과, `AgentReply` 의 내용은 그대로이고 `run_agent` 안에 남아 있다.
  모델 호출은 여전히 `PostChatModel` → `post` → `transport` 라서 `langchain-anthropic` 은 넣지 않았다.
- **일정 탭 에이전트(`schedule/agent/chat.py`)는 일부러 옮기지 않았다.** `complete_json` 을 한 번 부르고 코드가 결과를 처리할 뿐 도구 반복이 없어,
  그래프로 감싸도 얻는 것이 없다. `client.complete_json` 도 건드리지 않았다(일정·전화 이야깃거리·가족채팅 분석이 함께 쓴다).
- 여전히 쓰지 않는 것: 상태 저장소(checkpointer), 스트리밍, interrupt, 병렬 실행. 모든 노드는 호출한 스레드에서 차례로 돈다
  (`ai_guard.tally_scope` 와 DB 세션이 그 스레드에 묶여 있다).
- 시험: `tests/test_rag_graph.py`(그래프), `tests/test_llm_agent_loop.py`(탭 에이전트 루프), `ai_assistant/tests/test_handle_calls_restore.py`.
