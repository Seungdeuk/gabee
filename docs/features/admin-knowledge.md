# 통합관리자 챗봇

관리자 화면 오른쪽 아래 챗봇이다. 질문을 Claude API 로 바로 보내고 답을 보여 준다(2026-11-06 결정: 임베딩, 하이브리드 검색, 온톨로지를 쓰지 않는다).

## 구현 현황

- 폴더: `app/features/admin_knowledge/`. DB 표 없음.
- API: `POST /admin/knowledge/ask` `{q}` → `{answer}`. 권한은 `require_operator("admin")`.
- 자료: Claude 는 가비의 규칙을 모르므로 `faq.md` 전체를 시스템 지시에 함께 준다. 규칙이 바뀌면 이 파일을 고친다. 매 질문마다 전체를 보내므로 파일이 길어지면 비용이 는다.
- 답 형식: 첫 줄에 결론, 필요할 때만 `- ` 줄 최대 3개, 볼 곳이 있으면 마지막 줄에 `보는 곳: 메뉴`. 꾸밈 없음. 지시문은 `answer_format.md` 에 있고 고친 뒤 서버를 다시 켠다.
- 일상 질문은 Claude 가 공손하게 거절한다. 이때도 호출 비용이 든다.
- 질문은 `mask_text` 로 가린 뒤 보낸다.
- 숫자: 각 기능이 자기 폴더의 `admin_facts.py` 에서 `shared/admin_facts.register()` 로 숫자 함수를 도구 명단에 올린다(`service_admin`: 회원·가족·문의·AI·이용 분석 등, `ops_admin`: 서버 요청·오류, Cloud Run 트래픽·최근 버전·오류 로그 건수(`cloud_status.py`, `OPS_INFRA_ENABLED` 를 따르고 로그 본문은 보내지 않는다)). 관리자 화면과 같은 조회 함수를 써서 숫자가 화면과 같다. 개수와 오류 종류·경로·횟수만 담고 이름, 이메일, 사용자 id, 오류 message, trace id 는 보내지 않는다(시험으로 확인). 수집이 꺼진 값은 0 이라고 하지 않는다.
- 구조: `live.py` 가 명단을 랭체인 도구(`StructuredTool`)로 바꾸고, `graph.py`(랭그래프)가 Claude ⇄ 도구 반복을 돈다(Claude 호출 최대 4번). 회원·AI 사용량은 날짜 기간을 골라 물을 수 있다(최대 90일, 입력은 서버가 다시 검사). 도구 하나가 실패하면 그 도구만 "확인할 수 없음"을 돌려준다.
- 담당 나누기(서브 에이전트): `ADMIN_CHATBOT_SUBAGENTS`(기본 false)를 켜면 메인 챗봇이 숫자 도구와 FAQ 를 직접 갖지 않고 `ask_service`(서비스 숫자, 도구 `area="service"`)·`ask_ops`(서버 요청·오류, `area="ops"`)·`ask_rules`(도구 없이 `faq.md`) 담당에게 나눠 묻고 보고를 합쳐 답한다(`subagents.py`, 지시문 `prompts/`). 담당은 같은 그래프를 다른 지시·도구로 한 번 더 돈다. 메인과 담당이 호출 한도 하나를 나눠 써서 질문 하나에 Claude 최대 8번이다. 담당 호출이 실패하면 그 담당만 "확인할 수 없음"을 돌려준다. 단계 소식은 "서비스 담당 · 회원 수 확인"처럼 보인다. 시험: `tests/test_admin_subagents.py`. 평가로 기존 방식과 비교한 뒤 켠다.
- 랭스미스: `ADMIN_LANGSMITH_ENABLED`(기본 false) 와 `ADMIN_LANGSMITH_API_KEY` 가 있을 때만 이 그래프의 실행을 기록한다. 서버 전체 추적은 쓰지 않는다. 켜면 가린 질문·답 규칙·도구 숫자·답이 LangSmith 에 저장된다.
- 답변 단계 표시: `POST /admin/knowledge/ask/stream` 이 `/ask` 와 같은 답을 단계 소식(SSE, `AdminAskEvent`)과 함께 보낸다. 순서는 received(질문 확인) → masked(가림) → understand(Claude 첫 호출) → tool(도구마다, 화면용 이름 `label`) → write(답 작성) → answer, 실패하면 마지막이 error(`llm_failed`). 키가 없으면 소식 전에 503. 소식은 `graph.py` 노드가 `get_stream_writer()` 로 내보내고, 질문·도구 숫자·내부 도구 이름은 담지 않는다. 화면(`service_admin/static/app.js` 의 `chatStream`·`chatProgress`)은 fetch 본문을 읽어 5단계 카드를 그린다. 숫자 조회(약 0.03초)·답 작성이 너무 빨라 단계별 최소 표시 시간(0.5~1.5초)을 두고, 단계 옆 시간·총 시간은 실제 값을 보인다. 다 끝나면 2초 뒤 카드를 접고 "처리 과정 보기"로 펼친다.
- 도구 화면용 이름: `register(..., label="회원 수 확인")`. 도구 metadata 에만 담고 Claude 에게 보내는 도구 정의에는 넣지 않는다.
- 시험: `tests/test_admin_knowledge.py`(랭그래프 구조, 도구 명단, 날짜 기간, 반복 한도, 개인정보 미전송, 랭스미스 기본 꺼짐, 단계 소식 순서·실패·권한 등).
- 키: 서버 환경변수 `ANTHROPIC_API_KEY`. 모델은 `ANTHROPIC_MODEL`(기본 `claude-haiku-5-5`).
- 오류: 키 없음 503 `ai_key_missing`, 호출 실패 503 `llm_failed`. 하루 한도는 두지 않는다(2026-11-09 결정).

## 남은 것

- 실제 키로 답 품질 확인.
- 하루 한도가 없어서 비용은 월 예산·Claude 콘솔 사용 한도로 지켜야 한다. `ai_usage_logs` 는 가족 id 가 필요해서 아직 기록하지 않는다.
- 질문 가리기(`mask_text`)는 아직 `ai_assistant` 내부 함수를 직접 부른다. 공통으로 옮길지 정해야 한다.
- 공통 AI 관문(`ai_guard`)을 거치지 않는다(가족 기준이라 관리자에 맞지 않음).
- `faq.md` 의 AI 비서 하루 한도(10/30)가 코드 기본값(100/300)과 다르다. 실제 서버 값을 확인하고 고친다.
- 답변 단계 표시의 한계: 1·2단계 소식은 "끝남", 3~5단계 소식은 "시작"을 뜻하는데 화면은 같은 "진행 중"으로 보인다. 규칙 질문처럼 Claude 가 첫 호출에서 바로 답하면 "답 작성"이 건너뜀으로 보인다. 최소 표시 시간 때문에 답이 실제보다 약 3~4초 늦게 뜬다. 실제 서버(Caddy·Cloud Run)에서 소식이 모이지 않고 바로 오는지 확인해야 한다.
- 관리자 화면 파일에 `Cache-Control` 이 없어 브라우저가 옛 `index.html`·`app.js` 를 다시 쓸 수 있다.
