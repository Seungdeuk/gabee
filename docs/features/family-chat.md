# 구현 현황: family-chat (가족 채팅)

- 요구사항: docs/requirements/family-chat.md
- 결정 기록: docs/adr/0009-ai-call-minimization.md

## 구현된 것

### 기존 (뼈대)

- `GET /family-chat/messages`(`latest`·`before_id`·`after_id`·`limit`, 결과는 항상 오래된 순), `POST /family-chat/messages` — 가족 그룹 단체 대화(`messages` 테이블). 일반 전송은 AI 를 부르지 않는다. 쿼리 규칙은 아래 "채팅방" 절.
- 모바일 소통 탭: 채팅방 줄은 서버의 가족 그룹 정보와 최근 메시지 한 줄로 그린다. 가족 연락처 카드만 아직 임시 데이터(`mock.js`)다.

### 채팅방 (Chat 1 일부, 모바일 + 서버 쿼리)

**화면 흐름**

- 소통 탭(`src/app/(tabs)/family-chat.js` → `screens/FamilyChatScreen.js`)의 "채팅방" 아래 실제 가족 채팅방 한 줄(가족 이름, 마지막 메시지 한 줄, 시각)을 누르면 `router.push("/chat-room")` 로 간다. `src/app/chat-room.js` 는 `screens/ChatRoomScreen.js` 를 다시 내보낸다.
- 소통 탭은 화면에 올 때마다 가족 정보(`GET /family-group/groups/me`)와 최근 메시지 1개(`latest=true&limit=1`)를 한 번 읽는다. 폴링은 없다. 상단 검색창은 가족 이름으로 거른다.
- 채팅방 상단: 뒤로가기, 가족 이름과 "구성원 N명", ✨ AI 도우미 버튼. 가족 정보를 아직 읽지 못했으면 ✨ 는 꺼져 있다. 가족이 없으면 "가족 만들기 · 참여하기" 버튼을 보여 준다.

**메시지 목록·전송** (`useChatMessages.js`, `chatUtils.js`, `components/MessageBubble.js`, `components/Composer.js`)

- 처음 열면 최근 50개를 `latest=true&limit=50` 으로 가져온다.
- 날짜가 바뀌면 날짜 구분선을 넣고, 같은 사람이 이어서 말하면 이름을 생략한다. 내 말은 오른쪽(복숭아색), 상대 말은 왼쪽. 말풍선 옆에 시각을 보인다.
- 화면이 보이고 앱이 백그라운드가 아닐 때 **3초마다** `after_id=마지막 서버 id&limit=100` 으로 새 메시지만 가져온다. 100개가 가득 오면 바로 이어서 한 번 더 가져온다. 화면을 떠나거나 앱이 백그라운드로 가면 멈춘다. 이 확인은 AI 를 부르지 않는다.
- 확인이 실패하면 간격을 두 배씩 늘려 최대 30초까지 기다리고, 성공하면 3초로 돌아간다.
- 목록 위쪽 120px 안까지 스크롤하면 `before_id=가장 오래된 서버 id&limit=50` 으로 이전 대화를 50개씩 가져온다. 50개보다 적게 오면 더 없는 것으로 본다.
- 바닥 근처(120px 안)에 있을 때만 새 메시지가 오면 바닥으로 자동 스크롤한다.
- 입력은 앞뒤 공백을 지운 뒤 1~2000자일 때만 보낼 수 있다(`canSend`). 입력창 글자 수는 1800자부터 보인다.
- **낙관적 전송**: 보내기를 누르면 "보내는 중…" 임시 말풍선을 먼저 보이고 `POST /family-chat/messages` 를 부른다. 성공하면 서버 id 메시지로 바꾼다. 같은 글이 확인 과정에서 먼저 도착해도 두 번 보이지 않는다.
- **실패 재전송**: 실패하면 "전송 실패 · 다시 보내기"를 보인다. 누르면 같은 글을 다시 보내고, 길게 누르면 임시 말풍선을 지운다.
- 불러오기 오류는 상단 배너와 "다시 시도" 버튼으로 알린다. 오류 문구에는 대화 내용을 넣지 않는다.

**서버 쿼리 규칙** (`GET /family-chat/messages`, `router.py` → `service.py` → `repository.py`)

- `latest=true&limit=N`: 가장 최근 N개, 오래된 순.
- `before_id=ID&limit=N`: id 가 ID 보다 작은 것 중 가장 최근 N개, 오래된 순.
- `after_id=ID&limit=N`: id 가 ID 보다 큰 것을 오래된 순으로 N개(기존 동작).
- `latest`, `before_id`, `after_id>0` 중 둘 이상을 함께 주면 400 `invalid_range`. 아무것도 없으면 가장 오래된 것부터.
- `limit` 기본 100, 1~200.

**채팅방 안 AI 패널** (`components/AiPanel.js`, ✨ 버튼으로 연다)

- 아래에서 올라오는 시트(React Native Modal). 열 때만 `GET /family-chat/ai/settings` 로 동의·권한·남은 횟수를 읽는다. 패널이 닫혀 있으면 AI 호출은 한 번도 없다.
- **동의가 꺼져 있으면**: 설명과 "AI 기능 켜기" 버튼(`PUT /family-chat/ai/settings`)을 보인다. 버튼은 소유자·관리자에게만 보이고, 그 밖의 구성원에게는 "가족 소유자나 관리자가 켜야 해요"를 보인다.
- **켜져 있으면**: "오늘 남은 횟수: 나 N번 · 가족 N번"을 보인다(`parseAiSettings`). 호출이 끝날 때마다 설정을 다시 읽는다.
- **대화 분석하기** → `POST /family-chat/ai/analysis`: 요약, 중요 메시지(이유 목록), 일정 후보, 할 일 후보를 보인다. 결과 아래에 "대화 N개 기준 · 시각"과 "방금 분석 · AI 호출 N번 · 토큰 N" 또는 "저장된 결과(AI 호출 없음)"를 보인다.
  - 일정 후보는 날짜·시간이 모두 있어야 "일정으로 등록"이 켜진다. 누르면 기존 `POST /schedule/events` 로 등록한다(`scheduleEventBody`: 날짜·시간은 기기 시간대로 해석해 UTC 로 보내고, 장소는 메모에 "장소: …"로 넣는다). 등록 결과는 후보마다 따로 보인다.
  - 할 일 후보는 보기만 한다. 등록은 없고 "공동 할 일은 준비 중이에요"를 보인다.
- **답장 추천** → `POST /family-chat/ai/replies`, **대화 주제 추천** → `POST /family-chat/ai/topics`: 추천 한 줄을 누르면 채팅 입력창에 넣고 패널을 닫는다. 입력창에 이미 글이 있으면 공백을 두고 이어 붙인다. 보내기는 구성원이 직접 누른다.
- 분석·추천 요청은 범위를 따로 고르지 않는다(최근 대화 100개, `after_id=0` 기본값).
- 오류 문구는 `messages.js` 의 `chatErrorMessage` 가 서버 코드를 한국어 문장으로 바꾼다. 쿨다운은 대기 시간을 덧붙인다.
- 패널은 결과를 저장소에 쓰지 않는다. 마지막 결과는 화면이 살아 있는 동안만 남는다.

**소통 탭에서 AI 를 뺀 것**: 소통 탭에는 AI 카드(`AiCard.js`)를 두지 않는다(작업 트리에서 파일 삭제). AI 진입점은 채팅방의 ✨ 하나다.

**테스트**

- 앱 `apps/mobile/tests/chatroom.test.js`(11개): 메시지 병합·중복 제거, 임시 메시지 정리, 마지막·처음 id, 시각 표시, 날짜 묶기·이름 생략, 입력 판정, 미리보기, 폴링 간격, 오류 문구, 메시지 API 경로·쿼리.
- 앱 `apps/mobile/tests/chat.test.js`(7개): AI 오류 문구, 결과 설명, 일정 후보 등록 판정, 설정 응답 해석, AI 호출 경로·본문(대화 글자 없음), 일정 등록 호출 조건, 패널 호출 규칙(닫혀 있으면 호출 없음).
- 서버 `apps/api/app/features/family_chat/tests/test_message_paging.py`(5개): latest 오름차순, latest 가 limit 보다 적을 때, before_id 로 빈틈·중복 없이 넘기기, before_id 가 그 id 를 빼는지, after_id 기존 동작.

### AI 기능 (서버, `/family-chat/ai` 아래)

코드: `ai_router.py`(경로) → `ai_service.py`(업무 규칙) → `ai_repository.py`(DB 접근), 스키마는 `ai_schemas.py`. 모든 호출은 `app/shared/ai_guard.py` 의 `run` 을 거친다.

**엔드포인트**

| 메서드·경로 | 요청 | 응답 | 설명 |
|---|---|---|---|
| `GET /family-chat/ai/settings` | — | `AiSettingsOut` | 동의 여부, 내가 켤 수 있는지, 자동 분석 설정, 한도, 오늘 사용량. AI 를 부르지 않는다 |
| `PUT /family-chat/ai/settings` | `{enabled: bool}` | `AiSettingsOut` | 가족 소유자·관리자만 AI 기능을 켜고 끈다. AI 를 부르지 않는다 |
| `POST /family-chat/ai/analysis` | `RangeIn` | `AnalysisOut` | 통합 분석: 요약·중요 메시지·일정 후보·할 일 후보를 한 번에 |
| `POST /family-chat/ai/replies` | `RangeIn` | `RepliesOut` | 마지막 메시지에 이어 보낼 답장 후보(3개) |
| `POST /family-chat/ai/topics` | `RangeIn` | `TopicsOut` | 이어갈 대화 주제 추천(3~5개) |

- `RangeIn`: `limit`(기본 100, 1~200), `after_id`(기본 0). `after_id` 뒤의 최근 `limit` 개를 쓴다. 분석은 최대 200개, 답장은 최대 15개, 주제는 최대 30개까지 본다.
- `AnalysisOut`: `summary`, `important_messages[{message_id, reason}]`, `schedule_candidates[{title, date, time, place, source_message_ids}]`, `todo_candidates[{title, assignee_name, due, source_message_ids}]`, `meta`.
- `RepliesOut`: `replies[]`, `meta`. `TopicsOut`: `topics[]`, `meta`.
- `meta`(`AiMeta`): `cached`, `api_calls`(0 또는 1), `input_tokens`, `output_tokens`, `model`, `message_count`, `from_message_id`, `to_message_id`, `generated_at`.
- 날짜·시간·담당자·기한은 대화에 없으면 null 이다. `schedule_candidates`·`todo_candidates` 는 **후보**이며 사용자가 확인해야 등록된다. AI 서버 쪽에는 등록 API 가 없고, 앱이 확인한 일정 후보를 기존 `POST /schedule/events` 로 등록한다(날짜·시간이 있는 후보만). 할 일 후보의 등록 경로는 아직 없다.

**오류 코드**

| HTTP | code | 언제 |
|---|---|---|
| 403 | `not_manager` | 관리자가 아닌 구성원이 `PUT settings` 를 호출 |
| 403 | `ai_not_enabled` | 가족 그룹이 AI 기능을 켜지 않음 (분석·답장·주제) |
| 400 | `too_few_messages` | 분석 범위의 대화가 3개 미만(AI 를 부르지 않는다) |
| 409 | `ai_busy` | 같은 가족 그룹에서 다른 AI 호출이 진행 중(동시 실행 제한 초과). 자동 재시도 없음 |
| 429 | `ai_cooldown` | 같은 사용자의 직전 AI 호출 뒤 쿨다운 안. `Retry-After` 헤더 |
| 429 | `ai_daily_limit_user` | 사용자 하루 한도 초과 |
| 429 | `ai_daily_limit_group` | 가족 그룹 하루 한도 초과 |
| 503 | `llm_unavailable` | 서버에 `ANTHROPIC_API_KEY` 가 없음 |
| 503 | `llm_failed` | 호출 실패 또는 결과 검증 실패. 재시도하지 않는다. 오류 문구에 대화 글자를 넣지 않는다 |
| 503 | `schema_not_ready` / `db_unavailable` | DB 스키마가 준비되지 않았거나 DB 연결 불가(`app/shared/schema.py` 의 기능 게이트) |

- 그룹 멤버십은 `current_group_id` 가 확인한다(그룹 id를 요청에서 받지 않는다). 다른 그룹의 대화는 쿼리에 나오지 않는다.

### 공통 가드 (`app/shared/ai_guard.py`)

요청은 아래 순서로 처리하고, 앞 단계에서 걸리면 다음 단계는 실행하지 않는다.

1. **동의 확인**: 가족 그룹 설정이 꺼져 있으면 403 `ai_not_enabled`.
2. **결과 캐시**: 같은 가족 그룹·기능·캐시 키가 TTL 안에 있으면 저장된 결과를 돌려준다(호출 0, `cached: true`).
3. **키 확인**: `ANTHROPIC_API_KEY` 가 없으면 503 `llm_unavailable`.
4. **쿨다운**: 같은 사용자의 마지막 호출 뒤 `AI_REQUEST_COOLDOWN_SECONDS`(기본 30초) 안이면 429 `ai_cooldown`.
5. **하루 한도**: 사용자 `AI_MAX_CALLS_PER_USER_PER_DAY`(10), 가족 그룹 `AI_MAX_CALLS_PER_GROUP_PER_DAY`(30). 날짜 경계는 한국 시간 자정(`ai_day_utc_offset_hours`=9).
6. **동시 실행**: 가족 그룹마다 진행 칸(`AI_MAX_CONCURRENT_REQUESTS_PER_GROUP`, 기본 1)을 DB 에 먼저 잡는다. 칸이 없으면 409 `ai_busy`. 120초가 지난 진행 표시는 죽은 요청으로 보고 치운다.
7. **사용 기록 선기록**: `api_calls=1` 로 먼저 남겨, 한도 계산에 바로 반영한다.
8. **호출 1번**: `complete_json`(구조화 출력, 호출 1번). 실패하면 재시도 없이 503 `llm_failed`(한도에는 센다). 성공하면 토큰·모델을 기록하고 결과를 캐시에 저장한다.

- **캐시 키**: 프롬프트 버전, 기능, 모델 이름, 분석 범위의 첫 메시지 id·마지막 메시지 id·개수의 해시. **새 메시지가 범위에 들어오면 마지막 id 가 바뀌어 키가 달라지므로** 결과가 새로 만들어진다. 프롬프트를 바꾸면 버전을 올려 옛 캐시를 쓰지 않는다.
- **글자 수 한도**: `AI_ANALYSIS_MAX_CHARS`(기본 12,000자)를 넘으면 가장 오래된 메시지부터 뺀다. 실제로 쓴 범위는 `meta.message_count`, `from_message_id`, `to_message_id` 로 알려 준다.
- 일반 메시지 전송은 이 가드를 거치지 않는다(AI 호출 0).

### 호출 횟수 (동작별 AI 호출 수)

| 동작 | AI 호출 수 | 상태 |
|---|---|---|
| 일반 채팅 메시지 전송 (`POST /family-chat/messages`) | **0** | 구현됨 |
| 설정 조회·변경 (`GET`/`PUT /ai/settings`) | 0 | 구현됨 |
| 대화 분석 (`POST /ai/analysis`) | 최대 **1**, 캐시 적중이면 **0** | 구현됨 |
| 답장 추천 (`POST /ai/replies`) | **1**, 캐시 적중이면 0 | 구현됨 |
| 주제 추천 (`POST /ai/topics`) | **1**, 캐시 적중이면 0 | 구현됨 |
| @가비 키워드 검색 | **0** (PostgreSQL 키워드 검색 우선, 필요할 때만 pgvector) | 예정 |
| 원본 문서 확인·공유 | **0** | 예정 |
| 문서 요약 | **1** (요청할 때만) | 예정 |
| 문서 질문 답변 | **1** (요청할 때만) | 예정 |
| 자동 분석 | 설계상 0~1 (기본 꺼짐) | 예정(설계만) |

- 한도 계산에는 **실제로 호출한 것만** 센다(캐시 적중 0, 쿨다운·한도·409 로 막힌 요청은 기록하지 않는다). 호출이 실패해도 1로 센다.

### 설정 (`.env.example` 의 AI 항목)

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `ANTHROPIC_API_KEY` | (없음) | 서버에만 둔다. 없으면 503 `llm_unavailable` |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | 모델 이름(예전 이름 `LLM_MODEL` 도 읽는다) |
| `ANTHROPIC_MAX_TOKENS` | 2048 | 한 응답의 출력 토큰 상한 |
| `AI_AUTO_ANALYSIS_ENABLED` | false | 자동 분석(설계만, 아직 동작 없음) |
| `AI_MAX_CALLS_PER_USER_PER_DAY` | 10 | 사용자별 하루 호출 수 |
| `AI_MAX_CALLS_PER_GROUP_PER_DAY` | 30 | 가족 그룹별 하루 호출 수 |
| `AI_REQUEST_COOLDOWN_SECONDS` | 30 | 같은 사용자의 호출 간격 |
| `AI_RESULT_CACHE_TTL_SECONDS` | 600 | 결과 캐시 유지 시간(0 이면 끔) |
| `AI_MAX_CONCURRENT_REQUESTS_PER_GROUP` | 1 | 가족 그룹 동시 실행 수 |

- `AI_EFFORT`(코드 설정 `ai_effort`) 의 기본값은 `low` 다(추론 비용 절감). `.env.example` 에는 아직 없다.

## DB 테이블 (Alembic 리비전 `71db8f00993a`, 모델은 `app/shared/ai_usage.py`)

| 테이블 | 용도 | 원문 저장 |
|---|---|---|
| `ai_group_settings` | 가족 그룹의 AI 동의(`enabled`, 켠 사람 `enabled_by`, 갱신 시각). 기본 꺼짐 | 없음 |
| `ai_usage_logs` | 요청별 사용 기록: 기능, `api_calls`, 입력·출력 토큰, `cache_hit`, `status`(pending·ok·error·cached), `error_code`, 모델, 시각. 한도 계산에 쓴다 | **없음** (대화·문서 원문, API 키 모두 저장하지 않는다) |
| `ai_result_cache` | 검증된 결과 JSON(분석 결과만), 가족 그룹·기능·캐시 키 단위 유일, 만료 시각까지만 사용 | 결과 요약 JSON 은 TTL 동안 저장(대화 원문은 아님) |
| `ai_inflight` | 가족 그룹별 진행 중 AI 호출 칸(`group_id`, `slot` 복합 키). 동시 실행 제한 | 없음 |

- 모든 상태를 PostgreSQL 에 둬서 여러 워커에서도 한도·캐시·동시 실행이 일관된다. **Redis 는 쓰지 않는다**(이유는 ADR 0009).
- SQLite(로컬)에서도 같은 테이블이 생기지만 여러 프로세스 간 일관성은 PostgreSQL 에서만 의미가 있다.
- 스키마 변경은 Alembic 으로만 한다. `ai_usage` 모델을 공유하므로 `schema.py` 의 `SHARED_MODEL_FEATURES` 에 `family_chat`, `ai_assistant` 가 등록되어 있다.

## 모바일 (주의)

- 소통 탭의 AI 카드(`AiCard.js`)는 없어졌다(작업 트리에서 파일 삭제). AI 기능은 채팅방 안의 `AiPanel`(`components/AiPanel.js`)로 옮겼고, `/family-chat/ai/*` 를 부른다(동의 켜기, 분석, 답장·주제 추천, 일정 후보 등록, 남은 횟수).
- 채팅방 화면(`screens/ChatRoomScreen.js`)은 서버 메시지와 연결돼 있다(Chat 1, 폴링). 자세한 내용은 위 "채팅방" 절.
- 할 일 후보 등록 화면은 아직 없다. 패널에는 "공동 할 일은 준비 중이에요"만 보인다.

## 남은 것

- 1:1 채팅, 읽음 표시, 사진·파일 공유, 공동 할 일, 가족 연락처 관리는 아직 구현되지 않았다(Chat 2~4). 소통 탭의 가족 연락처 카드는 `mock.js` 임시 데이터다.
- 푸시 알림은 없다. 새 메시지 확인은 채팅방이 열려 있고 앱이 앞에 있을 때만 3초마다 하는 폴링이며, 실시간 소켓이 아니다.
- 할 일 후보 등록 API·화면은 없다.
- 자동 분석(설계는 요구사항 문서 참고): 열린 질문 결정 후 구현, 마지막 분석 범위를 저장할 컬럼 추가(Alembic) 필요.
- @가비 문서 검색(키워드 우선, pgvector 필요 시), 문서 요약, 문서 질문 답변.
- `docs/contracts/openapi.json` 과 `docs/contracts/db.md` 갱신(서버 변경 후 스크립트로 생성).
- 로컬 모델(Ollama) 선택 옵션(개인정보가 많은 글자를 외부로 보내지 않을 때).
- 대화방 여러 개(Chat 2 이후 범위).
