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

- **랭체인 추적(LangSmith)은 꺼져 있어야 한다.** `langchain-core` 가 클라이언트를 같이 설치하고, 환경변수(`LANGSMITH_TRACING` 등) 하나로
  켜지면 프롬프트와 가족 정보가 외부로 나갈 수 있다. 기본은 꺼짐이며 `tests/test_rag_graph.py::test_langsmith_tracing_is_off` 가 확인한다.
  운영 환경변수에 추적 관련 값을 넣지 않는다.
- 랭체인 계열은 버전이 빨리 바뀐다. 상한(`<2`)을 두었고, 올릴 때는 `tests/test_rag_graph.py`·`tests/test_llm_chat_model.py` 와
  `ai_assistant` 시험으로 확인한다.
- 운영 이미지(`apps/api/Dockerfile`)는 `pip install .` 로 의존성을 받는다. 이 PC 가상환경에는 이미 설치돼 있었지만 이미지에는 처음 들어가므로
  배포 전에 이미지 빌드와 기동을 한 번 확인한다.

## 결과

- 흐름을 그림으로 볼 수 있다(`GRAPH.get_graph()`). 마스킹·알림 같은 단계는 노드를 추가하고 화살표를 바꾸면 된다.
- 기존 `ai_assistant` 시험 262개가 그대로 통과했고, 어댑터·그래프 시험 32개를 추가했다.
- 코드는 줄지 않았다(반복문 약 99줄 → 그래프 110줄 + 어댑터 138줄). 이득은 앞으로 붙일 단계에서 나온다.
