# 구현 현황: family-chat (가족 채팅)

- 요구사항: docs/requirements/family-chat.md
- 결정 기록: docs/adr/0009-ai-call-minimization.md

## 구현된 것

### 기존 (뼈대)

- `GET /family-chat/messages`(`latest`·`before_id`·`after_id`·`limit`, 결과는 항상 오래된 순), `POST /family-chat/messages` — 가족 그룹 단체 대화(`messages` 테이블). 일반 전송은 AI 를 부르지 않는다. 쿼리 규칙은 아래 "채팅방" 절.
- 모바일 소통 탭: 방 목록(가족 전체방 + 1:1 방)은 서버의 `GET /family-chat/rooms` 로 그리고, 가족 연락처 카드는 실제 가족 구성원이다.

### 대화방 (서버, Chat 2)

- 가족마다 **가족 전체방**(kind=family) 하나, 가족 구성원 둘의 **1:1 방**(kind=direct)을 여러 개 둘 수 있다. 테이블 `chat_rooms`·`chat_room_members`·`chat_room_reads`, `messages.room_id`(Alembic `b6e2c9f4a187`, expand 만). 마이그레이션이 가족마다 전체방을 만들고 기존 메시지를 그 방에 연결하며 옛 읽음 위치를 `chat_room_reads` 로 복사한다. 옛 `chat_read_states` 는 지우지 않고 남겨 둔다.
- `GET /family-chat/rooms`: 가족 전체방(맨 위)과 내가 참여한 1:1 방(최근 메시지 순). 방마다 `{id, kind, peer_user_id, last_message, unread}`.
- `POST /family-chat/rooms/direct {user_id}`: 같은 가족 구성원과의 1:1 방을 돌려준다(없으면 만든다, 같은 두 사람의 방은 하나뿐). 자기 자신·가족이 아닌 사람은 400 `invalid_member`.
- 기존 `messages`·`read`·`read-states`·`unread` 는 **`room_id`(쿼리/본문, 선택)** 를 받는다. 생략하면 가족 전체방이라 기존 앱은 그대로 동작한다. 다른 가족의 방, 내가 참여자가 아닌 1:1 방, 없는 방은 모두 404(존재 여부를 숨김). 다른 방의 메시지 id 로 읽음 위치를 올리면 400 `invalid_message`.
- 읽음·안 읽은 수는 방별로 센다. 가족 전체방만 합류 시점 기준선을 쓰고, 1:1 방은 기준선 0 이다.
- `room_id` 가 비어 있는 옛 메시지(배포 중 구 서버가 쓴 것 포함)는 가족 전체방으로 본다.
- **1:1 대화는 AI 로 보내지 않는다**: AI 분석·추천은 가족 전체방 메시지만 쓴다(`ai_repository.recent_messages`). 시험: `tests/test_rooms.py`.
- 방 목록은 1:1 방 수와 상관없이 쿼리 수가 일정하다(`rooms_summary` 가 마지막 메시지·안 읽은 수·상대를 묶어서 조회).
- 알려진 한계: 상대가 가족을 나가도 1:1 방과 대화는 남는다(같은 가족에 다시 들어오면 다시 보임, 정책 미정). 구 서버 코드로 되돌리면 1:1 메시지가 가족 전체방 조회와 AI 분석에 섞이므로 롤백 전에 1:1 메시지를 먼저 처리해야 한다. 배포 중 구 서버가 `chat_read_states` 에 쓴 읽음 위치는 반영되지 않는다.
- 모바일의 방 목록·1:1 화면은 아직 없다(다음 PR).

### 공동 할 일 (서버, Chat 4)

- **가족 전체가 공유**한다: 같은 가족 구성원이면 누구나 보고, 추가하고, 고치고, 완료·되돌리기를 할 수 있다. 지우는 것은 만든 사람이나 가족 관리자(owner/admin)만 한다(그 밖은 403 `not_allowed`). 다른 가족의 할 일은 모두 404.
- 필드: 제목(1~120자, 공백 정리), 담당자 0~1명(같은 가족 구성원만, 아니면 400 `invalid_member`), 기한(날짜만, 선택), 완료 여부(`done`, `done_at`, `done_by`), 만든 사람, `source`(`manual` 직접 / `chat` AI 후보를 사용자가 확인해 등록). 반복·알림·하위 항목·댓글은 없다.
- `GET /family-chat/todos?status=open|done|all&limit=`: 안 끝난 일은 기한 빠른 순(기한 없는 것은 뒤), 끝난 일은 최근 순, `all` 은 안 끝난 것 다음 끝난 것. `POST /family-chat/todos`, `PATCH /family-chat/todos/{id}`(보낸 항목만 바꿈, `assignee_id`·`due_date` 에 null 을 보내면 비움, `done` true/false 로 완료·되돌리기, 빈 본문은 400 `empty_update`), `DELETE /family-chat/todos/{id}`(204).
- 가족당 최대 300개(완료 포함, 넘으면 400 `todo_limit`). 만든 사람 등은 요청 본문에서 받지 않고 로그인한 사용자에서 유도한다.
- **일정과의 구분**: 날짜와 시간이 있는 약속은 기존 일정(`/schedule/events`), 날짜가 없거나 "언제까지"만 있는 부탁·할 일은 여기에 둔다. AI 분석의 일정 후보는 일정으로, 할 일 후보는 확인 후 할 일로 등록한다(AI 가 직접 등록하지 않는다).
- AI 를 부르지 않는다. 테이블 `family_todos`(Alembic `d7b3a9f1c248`), 시험 `tests/test_todos.py`. 모바일 화면은 아직 없다(다음 PR).

### 사진 보내기 (서버, Chat 3)

- `POST /family-chat/photos`(multipart `file`, 선택 `room_id`): 사진 메시지를 보낸다. JPEG/PNG/WebP 8MB 이하(초과 413 `photo_too_large`), 긴 변 12000px·2500만 화소 이하, 실제 이미지가 아니면 400 `invalid_image`. 서버가 EXIF 회전을 반영한 뒤 **EXIF·GPS 등 메타데이터를 모두 지우고** 긴 변 1600px 이하 JPEG와 400px 이하 썸네일로 다시 만들어 저장한다. 응답은 `MessageOut` 이고 `text` 는 빈 문자열, `attachment` 에 `{id, kind, url, thumb_url, width, height}`.
- `GET /family-chat/photos/{id}?size=full|thumb`: 그 방에 들어갈 수 있는 사람만 본다(가족 전체방은 가족 구성원, 1:1 방은 두 사람). 못 들어가는 방·다른 가족·없는 사진은 모두 같은 404. 사진은 바뀌지 않으므로 `Cache-Control: private, max-age=31536000, immutable`, ETag(304), `nosniff`.
- 메시지 목록·방 목록의 마지막 메시지에 `attachment`(없으면 null)가 붙는다(첨부는 한 번의 쿼리로 모아 조회). 사진 메시지도 안 읽은 수에 센다.
- **AI 로 가지 않는다**: 사진 파일은 AI 에 보내지 않고, 글자 없는 사진 메시지는 AI 분석 대화에서 제외한다. 사진 보내기·보기는 AI 를 부르지 않는다.
- 저장: `DATA_DIR/chat_photos/<첨부 id>.jpg`, `<첨부 id>_t.jpg`(파일 이름은 서버가 만든 id, DB 경로가 서버가 만든 형태가 아니면 읽지 않는다). 파일을 먼저 쓰고 메시지·첨부를 한 번에 저장하며, 저장에 실패하면 파일을 지운다. 테이블 `message_attachments`(Alembic `c9a4d7e2b605`).
- 방어: 디코딩 전 크기·화소 거절, 축소 디코딩, 동시 처리 2건(초과 503 `photo_busy`), 사용자당 분당 20장(429 + `Retry-After`), 인증 전 큰 본문은 Content-Length 8MB(+여유) 초과 시 파싱 전에 413(해당 경로 한정 ASGI 미들웨어, 프로필 사진 미들웨어를 경로·한도만 바꿔 재사용).
- **운영 확인 필요**: `DATA_DIR` 이 컨테이너 볼륨에 있어야 사진이 유지된다(프로필 사진과 같다). Caddy 를 쓴다면 `/family-chat/photos` 업로드 경로에 `request_body { max_size 8.2MB }` 를 권고한다(`deploy/` 는 요청 없이 수정하지 않아 문서에만 적는다). 사진 저장량 한도·정리(삭제)는 아직 없다.
- 시험: `tests/test_chat_photos.py`. 모바일의 사진 고르기·보내기·보기는 아직 없다(다음 PR).

### 읽음 상태 (서버, PR C)

- `POST /family-chat/read {message_id}`: 내 읽음 위치를 올린다. 앞으로만 간다(더 작은 값은 무시하고 현재 값을 돌려줌). 이 그룹의 메시지가 아니면 400 `invalid_message`. 최초 저장이 동시에 겹쳐 기본키가 충돌하면 다시 읽어 갱신한다. 응답 `{last_read_message_id}`.
- `GET /family-chat/read-states`: 이 그룹 현재 구성원 전원의 `{user_id, last_read_message_id}`(기록이 없으면 합류 시점 기준선, 구성원이 아닌 사람은 제외). 앱이 이 목록과 메시지 id 로 '아직 안 읽은 사람 수'를 계산한다.
- `GET /family-chat/unread`: `{unread, last_read_message_id}`. 내가 안 읽은 다른 사람이 보낸 메시지 수(내 메시지 제외). 정확한 수를 1000 에서 자르고 99+ 표시는 앱이 한다.
- 합류 시점 기준선: 읽음 기록이 없는 구성원의 위치는 `GroupMember.joined_at` 이하의 마지막 메시지 id(없거나 joined_at 이 null 이면 0)다. 저장하지 않고 조회 때 계산하며(스키마 변경 없음), 기록이 있으면 기록과 기준선 중 큰 값을 쓴다. `unread`·`read-states` 가 같은 값을 쓰므로 나중에 합류한 사람은 가입 이전 메시지가 '안 읽음'이 아니다. `read` 의 `message_id` 는 1~2^31-1(범위 밖 422).
- 메시지를 보내면 보낸 사람의 읽음 위치가 그 메시지 id 로 자동 갱신된다. 읽음 처리·일반 전송은 AI 를 부르지 않는다.
- 테이블 `chat_read_states`, `messages(group_id, id)` 인덱스는 Alembic `d4b8f2a6c013`. 시험: `tests/test_read_state.py`. 모바일 연결(배지·안 읽은 사람 수)은 아직 없다.

### 채팅방 (Chat 1 일부, 모바일 + 서버 쿼리)

**화면 흐름**

- 소통 탭(`src/app/(tabs)/family-chat.js` → `screens/FamilyChatScreen.js`)의 "채팅방" 아래 실제 가족 채팅방 한 줄(가족 이름, 마지막 메시지 한 줄, 시각)을 누르면 `router.push("/chat-room")` 로 간다. `src/app/chat-room.js` 는 `screens/ChatRoomScreen.js` 를 다시 내보낸다.
- 소통 탭은 화면에 올 때마다 가족 정보(`GET /family-group/groups/me`)와 대화방 목록(`GET /family-chat/rooms`: 마지막 메시지·안 읽은 수 포함)을 한 번 읽는다. 폴링은 없다. 상단 검색창은 방 이름으로 거른다.
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
- 앱은 결과를 기기 저장소에 쓰지 않는다. 마지막 결과는 화면이 살아 있는 동안만 남는다. 서버는 AI 결과를 잠시(약 10분) 캐시해 같은 요청에 다시 쓴다(안내 문구: "분석 결과는 잠시(약 10분) 저장돼 같은 요청에 다시 쓰여요").

**보내기 전 확인(미리보기·승인)** (`components/AiConfirmCard.js`, 순수 함수 `privacyPreview.js`)

서버 계약 `POST /family-chat/ai/preview` 는 **별도 PR**(서버 가명화)이다. 앱은 이 계약대로 `api.js` 의 `previewAiRange(range)` 를 만들었고 서버 연동은 아직 확인하지 못했다.

- 요청 `{limit?, after_id?}`(분석 요청과 같은 범위, 앱 기본값 100/0) → 응답 `{message_count, masked:{PHONE?,EMAIL?,RRN?,CARD?,ACCOUNT?,SECRET?,ADDRESS?,PERSON?: 개수}, blocked_messages, lines:[{id, speaker, text, blocked}], ai_enabled, sendable}`. 차단된 줄의 text 는 `[민감정보가 있어 제외된 메시지]`(시각 없음), `sendable` 은 보낼 수 있는(차단되지 않은) 메시지가 3개 이상이면 true 이고 false 면 분석·답장·주제가 400 `too_few_messages` 를 돌려준다(이 오류는 기존 오류 문구로 보인다). 가명화된 줄(`[PERSON_1]`, `[PHONE_1]` 같은 토큰 상태)이며 AI 를 부르지 않고 하루 한도도 쓰지 않는다. 오류: 400 `too_few_messages`·`no_group`, 401 등.
- **흐름**: "대화 분석하기"·"답장 추천"·"대화 주제 추천"을 누르면 바로 AI 를 부르지 않고 먼저 미리보기를 불러 "이 내용이 AI로 전송돼요" 카드를 보인다. 카드에는 설명, 가려지는 항목 칩("전화번호 2개 가림", "이름 5개 가림" 등, 0 개 종류는 뺌), 고위험 정보로 제외되는 메시지 N개 경고(있을 때만, 경고 색), 접어 둔 "보낼 내용 보기"(가명화된 줄 목록, 차단된 줄은 "(제외됨)"), "AI에 보내기"·"취소"가 있다. **"AI에 보내기"를 누를 때만** 기존 분석/답장/주제 API 를 호출한다. 취소하면 아무 호출도 없다.
- **미리보기 실패**: 오류 문구(`chatErrorMessage` 재사용)와 "다시 시도". AI 는 부르지 않는다. 늦게 도착한 옛 미리보기 응답은 버린다.
- **`ai_enabled=false`**: 보내기 버튼을 막고 "AI 기능이 꺼져 있어요" 안내를 보이며 설정을 다시 읽어 기존 동의 켜기 영역으로 안내한다.
- **`sendable=false`**: "AI에 보내기"를 막고 경고색으로 "민감정보가 있어 제외된 메시지가 많아서 지금은 AI에 보낼 수 있는 대화가 부족해요"를 보인다(보낼 내용 보기는 계속 가능). `ai_enabled=false` 와 겹치면 동의 안내가 먼저다(`sendBlockReason`).
- **결과 아래 한 줄**: 응답 `meta.privacy`(`{masked, blocked_messages}`, 선택 필드)가 있으면 "개인정보 N개를 가려서 보냈고 메시지 M개는 제외했어요"(한쪽만 0 이면 해당 부분만, 둘 다 0 이면 생략)를 분석·답장·주제 결과 모두에 보인다. "저장된 결과(AI 호출 없음)" 안내와 함께 보인다.
- **승인 정책**: 일정 후보 "일정으로 등록"·할 일 후보 "할 일로 등록"은 사용자가 누를 때만 동작하고, 답장·주제 추천은 누르면 입력창에 **넣기만** 한다(`pickReply` 는 `setDraft` 만, 자동 전송 없음). AI 호출은 확인 카드의 "AI에 보내기"에서만 일어난다.
- 단순함을 위해 같은 범위를 이미 분석한 경우(서버 캐시)에도 항상 확인 단계를 거친다. 미리보기 범위는 분석과 같은 기본 범위이며, 답장(최대 15개)·주제(최대 30개)는 서버가 더 적게 보내므로 미리보기가 실제 전송보다 넓게 보일 수 있다.
- 시험: `apps/mobile/tests/privacypreview.test.js`(칩 문구·순서, 차단 경고, `meta.privacy` 한 줄, 줄 표시, 오류 문구, `previewAiRange` 경로·메서드·본문, 승인 정책 소스 확인). 실기기·서버 연동은 직접 확인하지 못했다.

**소통 탭에서 AI 를 뺀 것**: 소통 탭에는 AI 카드(`AiCard.js`)를 두지 않는다(작업 트리에서 파일 삭제). AI 진입점은 채팅방의 ✨ 하나다.

**테스트**

- 앱 `apps/mobile/tests/chatroom.test.js`(11개): 메시지 병합·중복 제거, 임시 메시지 정리, 마지막·처음 id, 시각 표시, 날짜 묶기·이름 생략, 입력 판정, 미리보기, 폴링 간격, 오류 문구, 메시지 API 경로·쿼리.
- 앱 `apps/mobile/tests/chat.test.js`(7개): AI 오류 문구, 결과 설명, 일정 후보 등록 판정, 설정 응답 해석, AI 호출 경로·본문(대화 글자 없음), 일정 등록 호출 조건, 패널 호출 규칙(닫혀 있으면 호출 없음).
- 서버 `apps/api/app/features/family_chat/tests/test_message_paging.py`(5개): latest 오름차순, latest 가 limit 보다 적을 때, before_id 로 빈틈·중복 없이 넘기기, before_id 가 그 id 를 빼는지, after_id 기존 동작.

### 대화방·1:1 채팅 (앱, 서버 `GET /family-chat/rooms`·`POST /family-chat/rooms/direct` 계약 사용)

- **소통 탭**(`FamilyChatScreen`): 서버 방 목록을 `buildRoomRows`(`listUtils.js`)로 행으로 바꿔 보인다. 가족 전체방이 맨 위, 1:1 방은 서버 순서(최근 메시지 순). 1:1 행은 상대 프로필 사진/이니셜(`UserAvatar`)과 상대 이름(별명 우선), 마지막 메시지 미리보기, 안 읽은 수 배지를 보인다. 상대가 구성원 목록에 없으면 이름을 "가족"으로 둔다. 접근성 라벨은 "<이름>님과 1:1 대화, …".
- **새 대화**(상단 ✎ 버튼): 나를 뺀 가족 구성원 목록(`NewChatPicker`)을 펼치고, 한 명을 누르면 `POST /family-chat/rooms/direct` 로 1:1 방을 열거나(없으면 만들고) 그 방으로 간다. 열고 있는 동안 다른 줄은 눌리지 않고, 실패하면 목록 아래에 오류 문구를 보인다.
- **채팅방**(`ChatRoomScreen`): 경로 인자 `roomId`(없으면 가족 전체방)와 `peer`(1:1 상대 id, 방 이름을 정하는 데만 사용)를 받는다. 1:1 방에는 구성원 수와 **AI 도우미(✨) 버튼·패널이 없다** — 1:1 대화는 AI 로 보내지 않는다. 메시지 조회/전송, 읽음 올리기, 읽음 상태 조회가 모두 `roomId` 를 같이 보낸다(`api.js`; `roomId` 가 없으면 이전과 같은 요청). 안 읽은 사람 수는 그 방의 읽음 상태(1:1 이면 두 사람)로 센다.
- 시험: `tests/rooms.test.js`(행 만들기·상대 이름/사진·나간 상대·후보 목록·접근성 라벨·API 경로와 본문).
- 아직 없는 것: 1:1 방 나가기/삭제, 방 이름 바꾸기, 두 명 넘는 그룹 방.

### 읽음 표시·안 읽은 수 (앱, 서버 PR #54 계약 사용)

- **자동 읽음 처리**(`useReadMarker.js`): 눌러서가 아니라 채팅방 화면이 보이는 동안(포커스 + 앱이 앞에 있을 때) 목록의 가장 큰 서버 메시지 id 가 지금까지 올린 값보다 커졌을 때만 `POST /family-chat/read {message_id}` 를 보낸다. 연속 변화는 약 0.8초 모아 한 번만 보내고, 낙관적 임시 메시지는 제외하며, 같은 id 는 다시 보내지 않는다. 내가 보낸 메시지가 가장 최신이면 서버가 이미 내 읽음 위치를 올렸으므로 호출하지 않는다. 실패하면 조용히 두고 다음에 id 가 바뀔 때 다시 시도하며(폴링 간격은 건드리지 않음), 화면이 안 보이게 되거나 닫힐 때 대기 중인 값이 있으면 디바운스를 기다리지 않고 즉시 한 번 올린다(flush). 진행 중인 호출은 `pendingRead.js` 에 추적해, 소통 탭이 `GET /unread` 를 부르기 전에 기다린다(배지가 옛 숫자로 남지 않게).
- **설계 의도(카카오톡 방식)**: 위로 스크롤해 지난 대화를 읽는 중이어도 방을 열어 둔 동안 새로 온 메시지는 읽음으로 처리한다 — "방을 열면 읽음".
- **읽지 않은 사람 수**: 기존 3초 새 메시지 폴링 틱에서 `GET /family-chat/read-states` 도 함께 부른다(별도 타이머 없음, 화면이 보일 때만). 폴링 호출이 틱마다 1개 늘어난다. 폴링 간격은 메시지 조회 실패만 반영한다(최대 30초). 읽음 조회는 실패하면 자체 횟수에 따라 2^n 틱(최대 10틱)마다 한 번 재시도하고, 404 면 이 세션 동안 끄며, `retry()` 는 읽음 조회도 즉시 한 번 부른다. 아직 못 받았거나 실패 중이면 숫자를 숨긴다. `chatUtils.unreadCount` 가 내가 보낸 서버 메시지에 대해 "read-states 응답(서버가 현재 구성원 전원+합류 기준선을 준다)에서 나를 제외하고 `last_read_message_id` < 메시지 id 인 사람 수"를 센다(구성원 목록은 쓰지 않아 나간 구성원이 영구 안 읽음으로 세어지지 않는다). 임시·실패 메시지와 상대 메시지에는 표시하지 않는다.
- **말풍선**(`MessageBubble`): 내 말풍선의 시각 위(왼쪽 아래)에 0 보다 클 때만 작은 꿀색 숫자를 보인다(접근성 라벨 "아직 N명이 읽지 않았어요"). 모두 읽었으면 아무것도 보이지 않는다.
- **소통 탭 방 행**(`RoomRow`, `FamilyChatScreen`): 화면이 올 때마다 한 번 `GET /family-chat/unread` 를 `getRoomInfo`·`listMessages` 와 함께 부른다(폴링 없음, 실패해도 목록은 그대로). 오른쪽 아래에 복숭아색 원 배지(99 초과는 "99+", 0 이면 숨김)를 보이고 안 읽은 수가 있으면 마지막 메시지를 굵게 한다. 접근성 라벨에 수가 들어간다. 채팅방에서 돌아오면(포커스) 다시 불러 갱신된다.
- 대화 글자는 이 호출들에 없다(메시지 번호와 사용자 id 만 오간다). 일반 전송과 읽음 처리는 AI 를 부르지 않는다.
- 시험: `apps/mobile/tests/readreceipts.test.js`(`unreadCount` 경계, `shouldMarkRead`, 배지 문구 "99+", 접근성 라벨, API 경로·본문·Bearer). 실제 기기·웹 화면에서의 동작(포커스 전환, 배지 갱신 등)은 아직 직접 확인하지 못했다.

### 공동 할 일·가족 연락처 (앱, Chat 4)

서버 계약은 PR #62(`/family-chat/todos`, 위 서버 절 참고)와 기존 `GET/PUT /family-group/groups/me/nicknames` 를 따른다. 앱은 `api.js` 에서 공통 래퍼로 직접 호출한다(다른 기능의 내부 파일은 가져오지 않음). 이 호출들은 AI 를 부르지 않는다.

- **가족 할 일 화면**(`/family-todos`, `FamilyTodosScreen`, 상태는 `useTodos.js`): 안 끝난 일 목록(체크 원, 제목, 담당자, 기한 라벨 — 지난 기한은 danger 색 "지남 · M월 D일"), 접이식 "완료한 일"(펼칠 때 처음 `status=done` 을 불러오며, 불러오기 전에는 개수를 쓰지 않고 불러온 뒤 "완료한 일 N"), 하단 추가줄(제목 입력 + 담당자 칩 + 기한 칩). 화면이 보일 때(`useFocusEffect`)와 당겨서 새로고침할 때만 불러온다(폴링 없음).
- **완료·되돌리기는 낙관적 갱신**: 먼저 화면에 반영하고 `PATCH {done}` 을 보낸다. 실패하면 원래 항목으로 되돌리고 오류 문구를 띄운다(404 면 목록에서 뺀다). 같은 항목의 요청 중 중복 누름은 막는다(보내기 버튼도 ref 로 막음).
- **기한 칩**: 기한 없음/오늘/내일/3일 뒤/1주일 뒤. 날짜 선택 라이브러리는 쓰지 않고 기기 시간대의 날짜를 `YYYY-MM-DD` 로 계산한다(월말·연말은 `Date` 가 넘김). 칩에 없는 기존 기한은 고치기 창에서 "현재 …" 칩으로 남아 건드리지 않으면 그대로다.
- **고치기 창**(`TodoEditModal`): 행을 누르면 열린다. 바뀐 항목만 `PATCH` 로 보내고(`buildEditPatch`), 담당자 없음·기한 없음은 `null` 로 비운다. 지우기는 확인 단계 뒤 `DELETE`, 403 이면 "만든 사람이나 가족 관리자만 지울 수 있어요".
- **소통 탭**(`FamilyChatScreen`): 방 목록과 가족 연락처 카드 사이에 "가족 할 일" 카드(`TodoCard`)를 둔다. 화면이 올 때마다 `listTodos('open', 200)` 한 번(목록 로딩과 별개, 실패하면 카드만 조용히 숨김)으로 안 끝난 일 개수와 기한 빠른 앞 두 제목을 보인다. 가족 연락처 카드와 "전체 보기 →" 는 `/family-contacts` 로 간다.
- **AI 패널의 할 일 후보**(`AiPanel`, `TodoCandidateRow`): 각 후보에 "할 일로 등록" 버튼. 사용자가 누를 때만 `POST /family-chat/todos`(`source: "chat"`)를 보내고 AI 는 직접 등록하지 않는다. 후보마다 결과(등록됨/오류)를 보이고 같은 후보의 중복 등록을 막는다(실패하면 다시 누를 수 있음). **담당자 매칭**: 후보의 `assignee_name` 이 구성원의 이름 또는 표시 이름과 정확히 같고 그런 구성원이 한 명뿐일 때만 `assignee_id` 로 쓰고, 아니면 null(짐작하지 않음). 기한은 실제 있는 `YYYY-MM-DD` 일 때만 쓴다(`candidateToTodoBody`). 등록을 누를 때 `GET /family-group/groups/me` 로 구성원을 한 번 읽는다. 기존 일정 후보 등록은 그대로다.
- **가족 연락처 화면**(`/family-contacts`, `FamilyContactsScreen`): 구성원의 사진·이름(표시 이름 우선)·관계 라벨(`contactUtils.relationLabel`, other 는 직접 적은 관계 또는 "가족")·메모 한 줄. 내가 붙인 별명이 있으면 별명이 크고 본래 이름이 작게 보인다. 나 자신 줄에는 "대화하기"와 별명 편집이 없다. "대화하기"는 `openDirectRoom` 후 `/chat-room` 으로 가며 중복 누름은 ref 로 막는다. 줄을 누르면 별명·메모 편집 창(별명 40자, 메모 1000자 — 서버 규칙, 둘 다 비우고 저장하면 서버가 지움). 별명·메모는 나에게만 보인다(서버 규칙). **전화번호는 다루지 않는다.** 별명 조회가 실패해도 연락처는 보인다.
- 순수 함수: `todoUtils.js`(기한 칩·라벨, 정렬/분리, 낙관적 갱신, 고치기 본문, 후보 매핑, 오류 문구), `contactUtils.js`(관계 라벨, 별명 표시 규칙, 검사). 시험: `apps/mobile/tests/familytodos.test.js`(순수 함수, API 경로·메서드·본문·쿼리, 토큰이 URL 에 없음, null 로 비우기).
- 직접 확인하지 못한 것: 실제 기기·웹 화면 동작(모달, 키보드, 당겨서 새로고침, 칩 스크롤), 서버 연동 실호출.
- 아직 없는 것: 할 일 알림·반복·하위 항목·댓글(요구사항에서 제외), 날짜 직접 고르기, 연락처 전화번호.

### 사진 보내기 (앱, Chat 3)

서버 계약(`POST /family-chat/photos`, `GET /family-chat/photos/{id}?size=full|thumb`, 메시지의 `attachment`)은 PR #60 의 서버 절을 참고한다(이 브랜치에는 서버 문서가 없다).

- **보내기**: 입력줄의 + 버튼이 갤러리(시스템 선택기, 권한 요청 없음)에서 사진 한 장 고르기로 바뀌었다(`components/Composer.js`, `pickPhoto.js`). 웹은 올리기 전에 긴 변 2048px 이하 JPEG(0.85)로 줄이고(`shared/shrinkImage.js`, 실패하면 원본), 네이티브는 선택기 `quality` 0.8 로 줄인다. 8MB 를 넘는 것이 분명하면 올리지 않고 안내한다. `api.js` 의 `sendPhoto(asset, roomId)` 가 multipart `file`(+ `roomId` 가 있을 때만 form `room_id`)로 보낸다(Content-Type 은 직접 지정하지 않는다). 1:1 방에서도 같은 방 id 로 동작한다.
- **진행·오류**: 고르는 동안·보내는 동안 + 버튼이 비활성(진행 표시)이고, 중복 누름은 ref 로 막는다(`ChatRoomScreen` 의 `picking`, `useChatMessages` 의 `photoLock`). 실패하면 입력줄 위에 오류 문구를 보이고(닫기 가능), 다시 + 를 눌러 고르면 재시도다. 문구는 `chatUtils.photoSendErrorMessage`(413 `photo_too_large`, 400 `invalid_image`, 429 `too_many_uploads`, 503 `photo_busy`, 404 방 없음). 사진·대화 내용은 문구·로그에 넣지 않는다.
- **목록 반영**: 성공하면 서버가 돌려준 메시지를 `useChatMessages.sendImage` 가 `mergeMessages` 로 병합하고 아래로 스크롤한다(임시 "전송 중" 메시지는 없다. 폴링이 먼저 가져와도 id 로 중복 제거).
- **보기**: `MessageBubble` 이 `attachment` 가 있으면 말풍선 안에 썸네일(`thumb_url`)을 보인다. 크기는 `attachment.width/height` 로 `photo.fitSize` 가 미리 계산한다(최대 220x280, 확대 없음, 크기를 모르면 정사각형이라 레이아웃이 점프하지 않는다). 누르면 `PhotoViewer`(Modal, 원본 `attachment.url`, contain, "사진 닫기" 버튼)로 전체 화면으로 본다. 시각·읽음 숫자는 기존 규칙 그대로다.
- **인증 이미지**: 공용 `shared/components/AuthImage.js` 가 `useProfilePhoto`(네이티브 expo-image 헤더, 웹 blob 캐시)로 받는다. `shared/photoCache.js` 의 `photoPath` 는 프로필 사진 경로에 더해 서버가 준 `/family-chat/photos/<id>` 와 `?size=thumb|full` 형태만 허용한다(그 밖의 주소에는 로그인 헤더가 나가지 않는다). 채팅 사진은 바뀌지 않으므로 캐시에서 원본·썸네일을 서로 밀어내지 않는다. 토큰은 주소·캐시 키에 들어가지 않는다. `UserAvatar` 동작은 그대로다.
- **미리보기**: 마지막 메시지가 사진(글자 없음)이면 소통 탭 방 목록과 접근성 라벨에 "사진"(내 것은 "나: 사진")으로 보인다(`chatUtils.previewText`, `buildRoomRows` 가 이를 사용).
- 시험: `apps/mobile/tests/chatphotos.test.js`(미리보기, 경로 허용/거부, 캐시 키, `sendPhoto` 요청 모양, 오류 문구, 표시 크기, 파일 형식·한도). 실기기·웹의 파일 선택, canvas 줄이기, 네이티브 헤더 로딩, 전체 화면 보기는 아직 직접 확인하지 못했다.
- 아직 없는 것: 여러 장 한 번에 보내기, 사진 저장·공유, 동영상·파일, 사진 업로드 취소.

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
- **AI 어시스턴트 진입점도 같은 가드를 쓴다**: `POST /ai-assistant/chat`(기능 `assistant_chat`), `POST /ai-assistant/knowledge/ask`(`knowledge_ask`), 문서 요약·답변(`doc_summary`·`doc_answer`). 대화형이라 결과 캐시는 쓰지 않는다(`cache_key=None`, 대화 원문을 남기지 않는다). 도구 루프로 한 요청이 Anthropic 을 여러 번(최대 4) 부르면 실제 호출 수를 사용 기록과 하루 한도에 센다. 어시스턴트 두 기능은 이 문서의 기본 한도(10/30/30초)가 아니라 **따로 센다**(묶음 `assistant`: 사용자 100회/일, 가족 300회/일, 쿨다운 없음, `docs/features/ai_assistant-upload-chat.md`)(`ai_guard.run` 이 응답의 `calls` 를 읽는다). 키가 없으면 외부 호출 없이 검색 결과만 돌려주므로 가드를 거치지 않는다.

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
| 문서 요약 | **1** (요청할 때만) | 구현됨 |
| 문서 질문 답변 | **1** (요청할 때만) | 구현됨 |
| AI 어시스턴트 채팅 (`POST /ai-assistant/chat`, 그룹 있음) | 질문 1건당 **1~4** (도구 루프, 실제 횟수를 센다). 동의가 꺼져 있으면 **0** | 구현됨 |
| 시험용 기록 질문 (`POST /ai-assistant/knowledge/ask`) | 위와 같다 | 구현됨 |
| AI 어시스턴트 채팅, 가족 그룹 없음 | **0** (고정 안내 문장만) | 구현됨 |
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
- 할 일 후보는 패널에서 "할 일로 등록" 으로 등록한다(위 "공동 할 일·가족 연락처 (앱, Chat 4)" 절).

## 남은 것

- 사진·파일 공유는 앱에서 아직 구현되지 않았다(1:1 채팅·공동 할 일·가족 연락처 앱 화면은 위 절 참고).
- 푸시 알림은 없다. 새 메시지 확인은 채팅방이 열려 있고 앱이 앞에 있을 때만 3초마다 하는 폴링이며, 실시간 소켓이 아니다.
- 자동 분석(설계는 요구사항 문서 참고): 열린 질문 결정 후 구현, 마지막 분석 범위를 저장할 컬럼 추가(Alembic) 필요.
- @가비 문서 검색(키워드 우선, pgvector 필요 시), 문서 요약, 문서 질문 답변.
- `docs/contracts/openapi.json` 과 `docs/contracts/db.md` 갱신(서버 변경 후 스크립트로 생성).
- 로컬 모델(Ollama) 선택 옵션(개인정보가 많은 글자를 외부로 보내지 않을 때).
- 대화방 여러 개(Chat 2 이후 범위).
