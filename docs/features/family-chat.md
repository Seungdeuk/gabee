# 구현 현황: family-chat (가족 채팅)

- 요구사항: docs/requirements/family-chat.md

## 구현된 것

- **기존(뼈대)**: `GET /family-chat/messages`(`after_id`·`limit`, 오래된 순), `POST /family-chat/messages` — 가족 그룹 단체 대화(`messages` 테이블). 모바일 소통 탭은 아직 임시 데이터(`mock.js`)로 그려져 서버 대화와 연결돼 있지 않다.
- **대화 자동 요약(AI)**: `POST /family-chat/summary {limit?, after_id?}` → `{summary, message_count, from_message_id, to_message_id, model, generated_at}`.
  - 그 가족 그룹의 (after_id 뒤) 최근 대화를 `app/shared/llm` 래퍼로 Anthropic 에 보내 요약한다. 그룹은 `current_group_id` 로만 정해 다른 그룹 대화는 쿼리에 나오지 않는다.
  - 대화가 3개 미만이면 400 `too_few_messages`(AI 를 부르지 않는다), AI 키가 없으면 503 `llm_unavailable`, 호출 실패 503 `llm_failed`(오류 문구에 대화 글자를 넣지 않는다), 사용자별 시간당 한도(`CHAT_SUMMARY_MAX_PER_HOUR`, 기본 10) 초과 429 `too_many_requests` + `Retry-After`.
  - 글자 수 한도(`CHAT_SUMMARY_MAX_CHARS`, 기본 12,000)를 넘으면 가장 오래된 메시지부터 뺀다(최신 대화를 남기고 `message_count`/`from_message_id` 가 실제로 쓴 범위를 알려 준다).
  - **개인정보**: 구성원이 눌렀을 때만 보내고, 대화 글자와 이름만 보낸다(id·연락처 제외). 요약·대화는 DB·로그에 남기지 않는다(스키마 변경 없음). 프롬프트는 연락처·계좌 같은 개인정보를 일반화하고 대화 속 지시를 따르지 않도록 한다.
  - **모델 선택**: `ANTHROPIC_MODEL` 환경변수(예: `claude-sonnet-5-5`)로 고른다. 예전 이름 `LLM_MODEL` 도 읽고, 비어 있으면 기본값 `claude-haiku-5-5`. 같은 설정을 `ai_assistant` 도 쓴다. 키는 `ANTHROPIC_API_KEY`. 둘 다 서버 환경변수(`apps/api/.env`)에만 둔다.
  - 코드: `summary_service.py`/`summary_repository.py`/`summary_schemas.py`(기존 `router.py` 는 엔드포인트 하나 추가). 테스트: `tests/test_chat_summary.py`(실제 Anthropic 을 부르지 않고 가짜로 시험, 12건 중 요약 11건).
- **모바일**: 소통 탭 위쪽의 "AI 대화 요약" 카드(`SummaryCard`) — 누르면 요약을 보여 주고(`다시 요약하기`), 설정 없음·대화 부족·한도 초과·오류를 한국어로 안내한다. 결과는 화면에만 보인다.

## 남은 것

- 모바일 소통 탭을 서버 대화와 연결(채팅방 목록·대화 화면·전송·새 메시지 가져오기)해야 요약 카드를 실제 대화로 쓸 수 있다 — Chat 1.
- 대화방 여러 개, 1:1 채팅, 읽음 표시, 사진·파일 공유, 공동 할 일, 가족 연락처(요구사항 문서의 Chat 1~4).
- 요약 결과 저장·공유(지금은 저장하지 않는다), 안 읽은 대화만 요약, 로컬 모델(Ollama) 선택 옵션.
