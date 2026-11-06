# 통합관리자 챗봇

관리자 화면 오른쪽 아래 챗봇이다. 질문을 Claude API 로 바로 보내고 답을 보여 준다(2026-11-06 결정: 임베딩, 하이브리드 검색, 온톨로지를 쓰지 않는다).

## 구현 현황

- 폴더: `app/features/admin_knowledge/`. DB 표 없음.
- API: `POST /admin/knowledge/ask` `{q}` → `{answer}`. 권한은 `require_operator("admin")`.
- 자료: Claude 는 가비의 규칙을 모르므로 `faq.md` 전체를 시스템 지시에 함께 준다. 규칙이 바뀌면 이 파일을 고친다. 매 질문마다 전체를 보내므로 파일이 길어지면 비용이 는다.
- 답 형식: 첫 줄에 결론, 필요할 때만 `- ` 줄 최대 3개, 볼 곳이 있으면 마지막 줄에 `보는 곳: 메뉴`. 꾸밈 없음. 지시문은 `answer_format.md` 에 있고 고친 뒤 서버를 다시 켠다.
- 일상 질문은 Claude 가 공손하게 거절한다. 이때도 호출 비용이 든다.
- 질문은 `mask_text` 로 가린 뒤 보낸다.
- 숫자: `live.py` 가 관리자 화면과 같은 조회 함수를 불러 개수와 오류 종류·경로·횟수만 골라 Claude 에게 준다. 이름, 이메일, 사용자 id, 오류 message, trace id 는 보내지 않는다(시험으로 확인). 수집이 꺼진 값은 0 이라고 하지 않는다. 데이터 분석 탭 숫자는 무거워서 넣지 않았다.
- 키: 서버 환경변수 `ANTHROPIC_API_KEY`. 모델은 `ANTHROPIC_MODEL`(기본 `claude-haiku-5-5`).
- 오류: 키 없음 503 `ai_key_missing`, 호출 실패 503 `llm_failed`, 하루 한도(한 명 100번, 서버 메모리) 429 `ai_daily_limit`.

## 남은 것

- 실제 키로 답 품질 확인.
- 하루 한도 값과 월 예산 결정. `ai_usage_logs` 는 가족 id 가 필요해서 아직 기록하지 않는다.
- `live.py` 가 `service_admin`, `ops_admin` 내부 함수를 직접 부른다(기능 간 import 규칙과 충돌, 공유 필요).
