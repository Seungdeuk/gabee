# AI 비서 외부 전송 임시 방어 (경로 스위치 + 고위험 입력 차단)

팀원이 AI 비서(`ai-assistant`)를 가명화 게이트웨이(`app/shared/privacy`)에 연결하기 전까지의 **임시 방어**다.
팀원 코드를 건드리지 않고 `app/shared`·`app/main.py` 에서만 동작한다. **완전한 해결이 아니다.**

## 1. 경로 스위치 — `DISABLED_AI_ROUTES`

`apps/api/app/shared/route_switch.py`(순수 ASGI 미들웨어). 걸린 요청은 라우터·인증보다 먼저
`503 {"code": "route_disabled", "message": ...}` 로 응답한다(외부 호출 없음).

- 형식: 쉼표로 구분한 `METHOD /path`. 경로의 `*` 는 와일드카드(`/` 도 포함해 맞는다). 메서드는 대소문자 무관. 끝의 `/` 는 무시.
- 빈 값(기본)이면 아무 것도 끄지 않는다. 잘못된 항목은 조용히 무시한다(서버 시작을 막지 않는다).
- 값은 프로세스 시작 때 읽는 설정이라 바꾼 뒤 서버를 다시 시작한다.

예시:

```
DISABLED_AI_ROUTES=POST /ai-assistant/knowledge/items
DISABLED_AI_ROUTES=POST /ai-assistant/knowledge/items,POST /ai-assistant/knowledge/*,POST /ai-assistant/chat
```

`POST /ai-assistant/knowledge/items` 는 본문을 가리지 않고 저장해 이후 요약·질문·채팅 도구로 원문이 나가는 경로다(SECURITY_TEST_REPORT 결함 1).
앱이 쓰지 않는 직접 API 라 꺼도 앱 사용에는 영향이 없다.

## 2. 고위험 입력 사전 차단 — `high_risk_guard`

`apps/api/app/shared/high_risk_guard.py`. `main.py` 에서 AI 비서 라우터에 FastAPI 의존성으로 붙는다
(`schema_ready` 와 함께). 대상 요청과 검사 필드(코드의 `_TARGETS` 상수가 기준이고, 적용 기능은 `GUARDED_FEATURES`):

| 요청 | 검사하는 문자열 |
|---|---|
| `POST /ai-assistant/chat` | `message`, `history[].text`(user·assistant 모두: 클라이언트가 위조 가능) |
| `POST /ai-assistant/knowledge/ask` | `question` |
| `POST /ai-assistant/knowledge/answer` | `question` |
| `POST /ai-assistant/knowledge/items` | `title`, `body_md` (앱이 쓰지 않는 직접 입력 경로) |
| `POST /care/agent/chat`, `POST /billing/agent/chat` | `message`, `history[].text` |

care·billing 에이전트 입구를 넣은 이유: 이 입구는 `agent_guard.prepare` 로 질문을 `mask_text` 로 가린 뒤 Claude 로 보내지만,
`mask_text` 는 주민번호·카드만 가리고 **계좌번호·비밀번호·인증번호는 그대로** 보낸다(실측: `국민은행 110-123-456789`, `비밀번호는 abc12345`, `OTP 123456` 이 가려지지 않음).
일정 에이전트(`/schedule/agent/chat`)는 가명화 게이트웨이를 쓰고 자체적으로 0.7 이상을 400 으로 막으므로 대상에서 뺐다.

`privacy.detect()` 가 **RRN·CARD·ACCOUNT·SECRET** 후보를 점수 0.45 이상으로 찾으면 `400 sensitive_content`
("주민등록번호·카드·계좌번호·비밀번호는 AI 비서에 입력하지 마세요")로 거절하고 LLM 을 부르지 않는다.
응답·로그에 탐지된 값이나 종류별 세부 정보를 넣지 않는다.

동작 규칙:
- 인증이 먼저다(의존성이 `current_user` 에 의존): 인증 실패는 기존처럼 401.
- 본문은 FastAPI 가 이미 읽어 Request 에 캐시한 것을 재사용하므로 라우터의 Pydantic 검증은 그대로다.
- 본문이 JSON 이 아니거나 모양이 예상과 다르면 검사를 건너뛴다(라우터가 422).
- 대상 경로에서 본문이 상한(채팅류 512KB, `knowledge/items` 2MB)을 넘으면 검사를 건너뛰지 않고 **413 `payload_too_large`** 로 거절한다.
  건너뛰면 공백이나 모르는 필드로 본문을 부풀려 가드를 우회할 수 있고(Pydantic 은 그런 본문을 422 로 거절하지 않는다), 정상 최대치(문자열 4000자 x 11개:
  한글 JSON 약 135KB, 유니코드 이스케이프로도 약 270KB)보다 충분히 커서 정상 사용에는 영향이 없다. `knowledge/items` 는 본문 길이 제한이 없어 상한을 더 크게 잡았다.
- 탐지는 스레드풀에서 돌려 이벤트 루프를 막지 않는다. 긴 문자열도 잘라 내지 않고 전체를 검사한다.

### 임계값 측정

음성 = Baseline v2 `*.jsonl` 중 `spans` 가 빈 140문장 + 직접 합성한 일상 채팅 40문장(주문번호·운송장·날짜·금액·바코드 등).
양성 = 합성 고위험 17개(RRN 3, CARD 3, ACCOUNT 5, SECRET 6). 대상은 4종 후보의 최고 점수.

| 임계값 | 음성 오탐(180문장) | 재현율(17개) | 종류별 |
|---|---|---|---|
| 0.7 (일정 에이전트 기준) | 0 | 13/17 | RRN 0/3, CARD 2/3, ACCOUNT 5/5, SECRET 6/6 |
| 0.6 | 0 | 16/17 | RRN 2/3 (맥락 없는 13자리 숫자 누락) |
| 0.5 | 0 | 16/17 | 동일 |
| 0.45 (채택) | 0 | 17/17 | 전부 |
| 0.4 | 0 | 17/17 | 전부 |

판단: 메인 채팅은 가명화가 없어 0.7 미만 후보도 원문이 나가므로 일정 에이전트의 0.7 은 부족하다(RRN 이 전부 새어 나감).
음성 180문장에서 4종 후보는 점수와 무관하게 0건이라 0.45 까지 오탐 비용이 없고, 탐지기가 이 4종에 내는 최저 점수가 0.45(맥락 없는 13자리 주민번호 모양)이다. 그래서 0.45 를 쓴다.
표본이 작다(180문장). 맥락 없이 주민번호 모양이 되는 13자리 숫자를 직접 적은 문장은 오탐될 수 있다. 상수 `MIN_SCORE` 만 바꾸면 조정된다.

## 3. 한계 (반드시 읽을 것)

- **전화번호·이메일·이름·주소는 막지 못한다**(시험 `test_known_limit_*` 으로 고정). 이런 값은 팀원이 게이트웨이에 연결할 때까지 가려지지 않은 채 외부 LLM 으로 나갈 수 있다.
- **도구 결과**(일정·가계·돌봄·문서 검색 결과가 LLM 요청에 실리는 부분)는 검사하지 않는다. 사용자가 입력한 문장만 본다.
- 이미 저장된 기록(`knowledge/items` 본문 등)에 든 원문은 이 가드가 보지 못한다. 경로 스위치로 새 입력을 막는 것뿐이다.
- **`PATCH /ai-assistant/knowledge/items/{id}`** 는 앱이 쓰는 경로(읽어 낸 글 고치기)라 UX 영향이 커서 대상에 넣지 않았다. `update_item` 이 `mask_text` 를 거치지만 일반 문서에서는 주민번호·카드만 가려져
  **계좌·비밀번호는 원문으로 저장**되고 이후 요약·질문·채팅 검색으로 Claude 에 나간다. 팀원 협의 항목이다. `POST /ai-assistant/files/{id}/description`(200자)도 같은 한계다.
- **여러 턴에 나눠 쓴 입력**은 통과한다. 각 문자열을 따로 검사하므로 history 에 `900101`, message 에 `1234567` 처럼 나눠 쓰면 걸리지 않는다. 숫자 사이에 문자를 넣거나 한글로 읽어 쓴 값도 마찬가지다.
- 오탐: 연월일(YYMMDD)+1~4 로 시작하는 맥락 없는 13자리 숫자(타임스탬프·상품코드, 예 `2410271430000`)는 주민번호로 보아 400 이 될 수 있다.
- 공백·모르는 필드로 본문을 부풀려 우회하는 방법은 413 으로 막았다.
- 탐지는 규칙 기반이라 변형·분할 입력(숫자를 문장에 나눠 쓰기 등)은 놓칠 수 있다.
- 가족 채팅(`family-chat`)은 이미 가명화 게이트웨이를 쓰므로 이 장치의 대상이 아니다.

## 4. 제거 조건

팀원이 AI 비서의 채팅·knowledge 질문·도구 결과를 가명화 게이트웨이(`prepare_transcript` 등)에 연결하고
`test_assistant_chat_masks_user_text_before_sending`(SECURITY_TEST_REPORT 결함 4)이 **주민번호·카드 단언을 포함한 채로** 통과하면
(이 시험(과 매트릭스 묶음)은 가드를 끈 채 RRN·CARD 를 그대로 보내므로, 게이트웨이가 놓치면 계속 알려 준다):
`main.py` 의 `high_risk_guard` 의존성과 `RouteSwitchMiddleware` 등록, `app/shared/high_risk_guard.py`, `route_switch.py`, 관련 시험, `DISABLED_AI_ROUTES` 설정을 지운다.
