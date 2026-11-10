# 0010. 모델 호출을 `shared/llm/transport.py` 한 곳으로 모은다

- 날짜: 2026-11-02
- 상태: 적용됨(랭체인 도입의 1단계)

## 맥락

Anthropic Messages API 를 부르는 코드가 세 곳에 따로 있었다.

| 위치 | 쓰임 | 재시도 | 제한 시간 |
|---|---|---|---|
| `shared/llm/client.py` | 글 답·구조화 출력(`complete`, `complete_json`) | 없음 | 30초·40초 |
| `shared/llm/agent.py` | 탭 에이전트 도구 루프 | 429·5xx·연결 실패에 1회 | 60초 |
| `ai_assistant/knowledge/rag_chat.py` | 메인 채팅 도구 루프 | 없음 | 60초 |

메인 채팅은 팀 규칙("LLM 호출은 `shared/llm` 래퍼로만")을 따르지 않고 자체 HTTP 를 불렀고, 앞 대화를 모델 형식으로 바꾸는
함수와 토큰 집계 코드도 중복이었다. 랭체인을 도입하려면 갈아 끼울 자리가 한 곳이어야 한다.

## 결정

- HTTP 호출은 `transport.post_messages(body, timeout=..., retry=...)` 한 함수만 한다. Anthropic 주소를 아는 코드는 이 파일뿐이다
  (`tests/test_llm_transport.py::test_only_transport_knows_the_anthropic_endpoint` 가 지킨다).
- **호출 방식은 호출한 쪽이 인자로 고른다**(현재 동작 유지): 탭 에이전트는 `retry=True`, 메인 채팅과 `client` 는 `retry=False`.
  메인 채팅은 호출 수를 `ai_guard` 한도에 세므로 몰래 다시 부르지 않는다(`test_external_call_failure_is_503...` 의 의도).
- 재시도 규칙(대상 상태 코드, 대기 시간)은 `transport` 의 상수 한 곳에 둔다.
- 토큰 집계는 `transport.usage_of(reply)`, 앞 대화 변환은 `agent.build_messages` 하나로 합친다(`rag_chat._messages` 삭제).
- 시험이 가짜 모델을 끼우는 자리(`rag_chat._post`, `agent._post`, `ask(post=...)`)는 이름과 모양을 그대로 둔다.
- `LLMUnavailable` 은 `transport` 에 정의하고 `client.LLMUnavailable` 로도 계속 쓸 수 있다.

## 하지 않은 것

- `shared/llm/jev.py`(TypeSafe Jev, 문서 분류)는 다른 서비스라 이번에 건드리지 않았다.
- 동작 변경 없음: 재시도 정책, 제한 시간, 오류 문구, 한도 집계는 그대로다.

## 다음

2단계: `transport` 안쪽 구현만 랭체인(`ChatAnthropic`)으로 바꾼다. 바깥(호출 모양, `post` 대역, 오류 처리)은 이 결정대로 유지한다.
