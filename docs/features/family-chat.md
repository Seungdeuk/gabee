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

### 사진·파일 모음 (서버)

- `GET /family-chat/media?room_id=&kind=image|file|video|all&limit=&before_id=` — 채팅방 설정(⋮)의 모음 화면용. 인증 필수, 그룹은 `current_group_id`. `room_id` 가 없으면 가족 전체방(옛 NULL room 메시지 포함), 있으면 `resolve_room` 으로 확인하고 못 들어가는 방(다른 가족·참여하지 않은 1:1·없는 방)은 모두 404.
- 응답: `{items:[{attachment_id, message_id, kind, user_id, user_name, created_at, url, thumb_url, width, height, size_bytes}], next_before_id, counts:{image, file, video}}`. 최신순이고 `before_id`(메시지 id) 커서로 다음 쪽을 받는다(`next_before_id` 가 null 이면 끝). `limit` 1~100(기본 40). `counts` 는 쪽과 상관없는 그 방 전체 개수. `url`·`thumb_url` 은 기존 `/family-chat/photos/{id}[?size=thumb]` 이고 권한 검사는 그 엔드포인트가 그대로 한다.
- 권한은 SQL 조건이다: 첨부를 메시지에 join 하고 그 방의 메시지 조건으로만 조회해, 다른 방 첨부는 목록과 `counts` 어디에도 나오지 않는다. 사용자별 분당 60회 제한(초과 429 `too_many_requests`). AI·외부 호출 없음, 로그에 사용자 데이터 없음.
- 종류 확장: 종류는 `media_service.attachment_kind()` 한 곳에서만 정한다. 지금은 서버가 받는 첨부가 사진뿐이라 모두 `image` 이고, `kind=file|video` 는 빈 목록, `counts.file/video` 는 0 이다. 파일·동영상 업로드는 **미구현**이다. 생기면 `message_attachments` 에 종류 칼럼(Alembic)을 추가하고 `attachment_kind`·목록·개수의 SQL 필터를 그 칼럼으로 바꾼다.
- 파일: `media_router.py`·`media_service.py`·`media_repository.py`·`media_schemas.py`. 시험: `tests/test_chat_media.py`(최신순·커서·종류 필터·개수·방 분리·권한 격리·URL 로 사진 받기·429).

### 대화 검색 (서버)

카카오톡 돋보기처럼 **글자 일치(키워드) 검색만** 한다(사용자 결정). 임베딩·벡터·AI 를 쓰지 않고 외부 호출도 없다. 스키마 변경(Alembic)도 없다.

- `GET /family-chat/search?q=&room_id=&limit=&before_id=`
  - `q`: 공백 정리 후 1~100자(아니면 422 `invalid_query`). 공백으로 나눈 **모든 낱말**이 글자로 들어 있는 텍스트 메시지를 최신순으로 돌려준다. 대소문자는 구분하지 않는다(PostgreSQL `ILIKE`, SQLite `LIKE`). `%`, `_`, `\` 는 와일드카드가 아니라 글자 그대로 찾는다(`ESCAPE`). 사진 메시지(글자 없음)는 제외.
  - `room_id`: 있으면 그 방만(권한이 없거나 없는 방은 404). 없으면 접근 가능한 모든 방 = 가족 전체방 + 내가 참여한 1:1 방(`room_id` 가 없는 옛 메시지는 가족 전체방).
  - `limit` 1~50(기본 20), `before_id`: 이 id 보다 오래된 결과(다음 쪽 커서).
  - 응답 `{items:[{id, room_id, room_kind:"family"|"direct", peer_user_id, user_id, user_name, text, created_at}], next_before_id}`. `room_id` 는 가족 전체방 메시지도 그 방 id 로 채운다. `next_before_id` 는 더 있으면 마지막 항목의 id, 없으면 null.
- 권한은 **SQL 조건**이다(`group_id` + `room_id IN (접근 가능한 방)` + 가족방이면 `room_id IS NULL`). 가져온 뒤 숨기지 않는다. 그룹은 `current_group_id` 로만 받는다(탈퇴자는 403). 스캔 상한 없이 `messages(room_id, id)`·`(group_id, id)` 인덱스를 따라 최신 쪽부터 훑는다. `%글자%` 일치는 인덱스로 못 좁히므로 가족 하나의 메시지가 아주 많아지면 느려질 수 있다(그때 PostgreSQL `pg_trgm` 인덱스를 별도 리비전으로 검토).
- 사용자별 분당 30회 제한(429 `too_many_searches`, `Retry-After`; 프로세스 메모리 `FailureLimiter`). 검색어와 결과 글자는 로그에 남기지 않는다.
- `GET /family-chat/messages?around_id=<메시지 id>`: 검색 결과로 점프할 때 쓴다. **가운데 1개 + 앞뒤 각 `limit//2`개**(기본 `limit` 50, 최대 200이면 201개, `limit` 이 짝수면 `limit+1`개)를 오래된 순으로 돌려준다(사진 첨부 포함). `latest`·`before_id`·`after_id` 와 함께 쓰면 400 `invalid_range`, 그 방의 메시지가 아니면(`room_id` 와 안 맞거나 없는 id) 400 `invalid_message`, 방 권한은 기존과 같다(404). `limit` 을 주지 않으면 기존대로 100(around_id 일 때 50).
- `q` 에 NUL 등 제어문자(C0/C1, 탭·줄바꿈 제외)가 있으면 DB 를 부르기 전에 422 `invalid_query`. 탭·줄바꿈·전각 공백은 공백으로 정리한다.
- 시험: `app/features/family_chat/tests/test_search.py`, `tests/test_membership_enforcement.py`(엔드포인트 목록).

**알려진 한계**
- (a) `q` 가 쿼리 문자열이라 uvicorn 접근 로그(Dockerfile 기본)에 퍼센트 인코딩된 채 남을 수 있다. 앱 로거는 남기지 않지만 접근 로그는 `deploy/`·uvicorn 설정 소관이며 이번 PR 에서는 바꾸지 않았다(운영 확인 항목: 접근 로그에서 쿼리 문자열 제거 또는 비활성화). `test_no_query_or_text_in_logs` 는 앱 로거(caplog)만 검사한다.
- (b) `%글자%` 검색은 인덱스를 타지 못한다. 가족 전체방을 포함한 검색은 `OR room_id IS NULL` 때문에 순차 스캔이며, 6만 건 PostgreSQL 16 에서 드문 낱말 약 30ms, 1:1 방을 지정하면 약 9ms 였다. 100만 건 규모가 되면 `pg_trgm` GIN 인덱스를 별도 리비전으로 검토한다.
- (c) 속도 제한은 프로세스 메모리 기반이라 워커별로 센다.
- (d) SQLite 시험 환경은 비ASCII 대소문자 비교가 PostgreSQL 과 다르다(운영 PostgreSQL 기준으로 정상).

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
- 아직 없는 것: 여러 장 한 번에 보내기, 네이티브 사진 공유(저장은 위 "채팅방 서랍 · 사진 모음" 절), 동영상·파일, 사진 업로드 취소.

### 채팅방 서랍 · 사진 모음 (앱)

- **서랍**(`components/RoomDrawer.js`): 채팅방 상단 ⋮ 를 누르면 오른쪽에서 열린다(React Native `Modal` 투명 + `Animated`, 폭은 화면의 85% 최대 360, 180ms). 어두운 덮개·X·안드로이드 뒤로가기로 닫는다. AI 는 기존 ✨ 버튼에 그대로 있다. 위에서부터 방 이름(가족 전체방은 가족 이름, 1:1 은 상대 표시 이름)과 X, 구성원 줄(`MemberStrip`: "가족 구성원 N명"과 사진/이니셜 아바타 가로 스크롤, 나 먼저·표시 이름 우선 / 1:1 은 "대화 상대"와 상대 한 명), "채팅 관리"·"채팅방 설정" 두 구역. 행 정의와 방 종류별 차이는 순수 함수 `mediaUtils.buildDrawerSections`·`drawerMembers`·`drawerTitle` 에 있다.
- **동작하는 행**: 사진 · 동영상(→ `/chat-media`), 구성원 초대 · 관리(가족 전체방만 → 기존 `/family`), 대화 내용 검색(채팅방 안 돋보기 검색 바를 연다 — `onOpenSearch`, 헤더 돋보기와 같은 기능).
- **서랍 이동은 한 번만**: 이동 행(사진 · 동영상, 구성원 초대 · 관리, 검색)은 한 번 누르면 즉시 잠기고 닫히는 180ms 동안의 연속 누름은 무시한다(`canNavigateFromDrawer`). 서랍은 방 이름을 주소에 싣지 않고 `roomId`·`peer` 만 넘긴다.
- **준비 중인 행**(제목 옆 "준비 중" 배지, 누르면 서랍 안에 "준비 중이에요" 안내만): 고정 메시지, 공유 문서, 가족 일정 · 할 일, 알림 설정, AI · 개인정보 보호 설정, 채팅방 정보 수정. **채팅방 나가기**(빨간 글자): 가족 전체방은 가족 탈퇴 기능이 없어 "가족 채팅방은 나갈 수 없어요", 1:1 은 "준비 중이에요" 안내만 한다.
- **1:1 방에서 숨기는 행**: 구성원 초대 · 관리(가족 전체의 일), 공유 문서, AI · 개인정보 보호 설정(1:1 대화는 AI 로 보내지 않는다). 나머지는 가족 전체방과 같다.
- **사진 · 동영상 모음**(`/chat-media`, `screens/ChatMediaScreen.js`, 경로 인자 `roomId`(없으면 가족 전체방)·`peer`(1:1 상대 id). 방 이름은 주소(웹 주소창·기록)에 싣지 않고 화면 안에서 구성원 정보로 계산한다): 탭 "사진 N · 파일 N · 동영상 N"(개수는 서버 `counts`), 사진 탭은 3열 정사각 썸네일 격자(`AuthImage`, 월별 헤더 "2026년 10월"), 끝에 가까워지면 `next_before_id` 커서로 다음 쪽을 자동으로 불러온다(`useChatMedia.js`; 응답을 받아들일지 정하는 상태 전이는 순수 함수 `mediaState.js` 에 있어, 탭·방이 바뀌면 옛 응답은 버려지고 다음 쪽 실패 뒤에도 목록은 남은 채 "다시 시도"할 수 있다). `thumb_url`·`width`·`height`·`size_bytes` 는 서버 스키마상 null 일 수 있어 썸네일은 `thumb_url ?? url` 로 대신한다. `before_id` 는 1 이상일 때만 보낸다. 로딩·오류("다시 시도"; 다음 쪽 오류는 목록 끝에서 다시 시도)·빈 상태("아직 공유된 사진이 없어요")를 처리한다. 파일·동영상 탭은 같은 경로로 불러오고(서버가 빈 목록을 준다) 빈 상태 문구만 "아직 파일은 보낼 수 없어요. 사진부터 모아 둘게요"처럼 다르다.
- **전체 화면 보기·저장**(`components/MediaViewer.js`): 원본, 닫기, 보낸 사람(별명 우선)·날짜·시각, "저장" 버튼(저장 중·결과 문구는 사진별로 기억해서 다른 사진으로 넘어가면 새 사진에는 보이지 않는다). **웹**은 `api.downloadPhoto` 가 로그인 헤더로 받은 blob 을 a 태그 `download` 로 내려받는다(파일명 `gabee-YYYYMMDD-HHmmss-<id>.jpg`, 서버가 준 사진 경로만 받는다). **네이티브(iOS/Android)**는 사진 앱에 저장한다(`savePhoto.js` 의 `savePhotoNative`): ① `photoDownloadRequest`(api.js)가 서버가 준 사진 경로만 받아 주소와 로그인 헤더를 만든다(토큰은 주소에 없다, 낯선 주소는 권한 요청 전에 거절) ② `expo-media-library` **쓰기 전용 권한**(`getPermissionsAsync(true)` → 거절이면 `requestPermissionsAsync(true)`)을 확인한다. 거절·영구 거절이면 "사진 저장 권한이 필요해요. 설정에서 허용해 주세요" ③ `expo-file-system` 새 객체형 API(`File.downloadFileAsync(url, new File(Paths.cache, ...), { headers })`)로 앱 캐시 폴더의 임시 파일에 받는다 ④ `MediaLibrary.saveToLibraryAsync` 로 저장 ⑤ 임시 파일은 성공·실패 모두 `finally` 에서 지운다. 앨범("가비")은 만들지 않는다: `createAlbumAsync` 는 라이브러리 읽기 권한까지 요구해 권한 범위가 커지고, 쓰기 전용 권한이면 충분하기 때문이다. 모듈이 없거나 권한 API 가 실패하는 환경(Expo Go 의 미디어 라이브러리 제한 등)은 "이 환경에서는 저장할 수 없어요" 로 안내하고 앱은 멈추지 않는다. expo 모듈은 웹 번들에 섞이지 않도록 네이티브 분기 안에서 동적 import 한다. 시험은 의존성 주입 가짜 객체로 권한 허용·거절·영구 거절, 받기·저장 실패, 임시 파일 삭제, 낯선 경로, 모듈 없음, 웹 분기를 본다. 임시 파일 이름은 작업마다 시각+난수로 달라서 같은 사진을 동시에 저장해도 서로의 파일을 덮어쓰거나 지우지 않고, 화면은 저장 중인 사진 id 를 모두 기억해 같은 사진의 동시 재저장을 막는다. 인증 헤더는 권한을 받은 뒤 다운로드 직전에 만든다(경로 검증은 권한 창보다 먼저). **의존성**: `expo-file-system ~19.0.24`(SDK 54 호환, 사용자 승인으로 추가)와 `expo-media-library ~18.2.1`(앱 권한 문구는 app.json). **Expo Go 제한 가능성**: expo-media-library 가 "Expo Go 는 Android 권한 정책 때문에 미디어 라이브러리 전체 접근을 제공하지 못한다" 고 경고하므로 Expo Go 에서는 저장이 막힐 수 있다(막히면 위 안내 문구) — **개발 빌드(expo-dev-client)에서 확인을 권장한다.** **실기기(iOS·Android, 개발 빌드와 Expo Go)에서의 저장·권한 창은 아직 확인하지 못했다.**
- **서버 계약(별도 PR)**: `GET /family-chat/media?room_id=<선택>&kind=image|file|video|all&limit=<1~100, 기본 40>&before_id=<선택>` → `{items:[{attachment_id, message_id, kind, user_id, user_name, created_at, url, thumb_url, width, height, size_bytes}], next_before_id, counts:{image, file, video}}`. 오류 404(권한 없는 방)·429(분당 60회)·401. 앱 래퍼는 `api.listMedia`. 서버 PR 이 병합되기 전에는 모음 화면이 오류("사진을 불러오지 못했어요" 등)로 보인다.
- 시험: `apps/mobile/tests/chatmedia.test.js`(월 그룹핑 경계·격자 줄·이어 붙이기·counts·빈 상태/오류 문구·캡션·저장 파일명, 서랍 행 구성(가족방/1:1 차이·준비 중·나가기 문구·검색 연결), `listMedia` 경로·쿼리·커서·오류, `savePhoto` 분기). 실기기·웹 화면, 애니메이션, 서버 연동, 웹 내려받기는 아직 직접 확인하지 못했다.

### 대화 검색 (돋보기, 앱)

서버 계약은 **별도 PR** 의 `GET /family-chat/search`(`q`·`room_id`·`limit`·`before_id`, 응답 `{items, next_before_id}`)와 `GET /family-chat/messages?around_id=`(그 메시지를 가운데로 앞뒤 창)다. 이 브랜치에는 서버가 없어 가짜 fetch 로만 시험했다. **키워드(글자 일치) 전용**이며 임베딩·AI 를 쓰지 않는다. 검색어·결과 글자는 요청 주소 외에는 로그·저장소·오류 문구 어디에도 남기지 않는다.

- **채팅방 안 검색**(`ChatRoomScreen`): 상단 바의 돋보기(접근성 라벨 "대화 검색")를 누르면 상단이 검색 바(`ChatSearchBar`)로 바뀌고 메시지 목록 위에 결과(`ChatSearchResults`)가 덮인다(목록은 그대로라 닫아도 보던 위치가 유지된다). 입력은 300ms 쉬었다가 한 번 부르고(`useChatSearch`), 공백만이면 부르지 않으며, 같은 검색어는 다시 부르지 않고, 더 새 요청이 시작되면 오래된 응답은 버린다. 결과는 최신순: 보낸 사람, 시각(오늘이면 시각 / 올해 월일 / 다른 해 연월일), 두 줄 미리보기(`Highlighted`: 낱말 모두 굵게+옅은 꿀색 바탕, 대소문자 무시), 결과 개수("N개", 더 있으면 "N개 이상"), 끝에 닿으면 `next_before_id` 로 다음 쪽 자동 불러오기(또는 "더 보기" 버튼). 없음·오류(429 "너무 자주 검색", 422 검색어 길이)·로딩 상태가 있다.
- **소통 탭 검색**(`FamilyChatScreen`, `ChatListHeader`): 기존 입력에 글자를 넣으면 방 이름 일치 행 아래에 "대화 내용" 섹션(`ContentSearchSection`)이 나온다. 모든 방(가족 전체방 + 내 1:1)에서 찾고, 각 결과에 방 이름(가족 전체방은 가족 이름, 1:1 은 상대 표시 이름, 모르면 "대화")을 붙인다. 결과를 누르면 `/chat-room` 으로 가며(가족 전체방은 `focus` 만, 1:1 은 `roomId`·`peer`·`focus`) 그 메시지 위치로 열린다. `src/app/chat-room.js` 의 화면 key 가 `방:focus` 라 같은 방이라도 focus 가 다르면 새로 열린다.
- **과거 보기(포커스 모드)**(`useChatMessages`): 결과를 누르면 `focusOn(id)` 이 `listMessages({aroundId})` 로 앞뒤 50개 창을 받아 서버 메시지를 **통째로 교체**(임시 전송 중/실패 메시지는 유지, 떨어진 구간이 이어 붙지 않게)하고, 화면이 해당 메시지로 스크롤하며 2초간 배경색(`honeySoft`)으로 강조한다. 이 동안 새 메시지 확인(폴링)은 멈추고 확인 기준(cursor)은 라이브 끝에 그대로 둔다(읽음 상태 조회는 계속). 위로 스크롤하면 `loadOlder`, 아래 끝에 닿으면 `loadNewer`(after_id)로 이어 받고, 요청한 개수보다 적게 오면 라이브 끝에 닿은 것이라 자동으로 라이브로 돌아간다. 화면 아래의 "최신 대화로 이동" 버튼은 최근 50개를 다시 받아 라이브(폴링 재개)로 돌아간다. 과거 보기에서 글·사진을 보내면 먼저 라이브로 돌아간 뒤 보낸다. 포커스 요청이 실패(400 `invalid_message`/404)하면 최근 대화로 열고 안내 문구를 띄운다. 모드가 바뀔 때 올라가는 세대 번호(`modeGen`)로, 바뀌기 전에 시작한 요청의 응답은 버린다.
- **읽음 처리**: 과거 창을 보는 동안은 `useReadMarker` 에 빈 목록을 넘겨 읽음 위치를 올리지 않는다(보고 있지 않은 최신 메시지를 읽음 처리하지 않기 위해). 라이브로 돌아오면 평소처럼 최신 id 로 올린다.
- 순수 함수는 `searchUtils.js`(낱말 분리·정규화, 강조 구간, 시각 라벨, 결과 병합, 방 라벨, 이동 경로, 창 교체, 라이브 끝 판단), 오류 문구는 `chatUtils.searchErrorMessage`·`focusErrorMessage`, API 는 `api.js` 의 `searchMessages`·`listMessages({aroundId})` 다.
- 시험: `apps/mobile/tests/chatsearch.test.js`(낱말 분리, 중복 호출·오래된 응답 판단, 강조 구간(여러 낱말·겹침·특수문자·한글·이모지), 시각 라벨, 결과 병합, 방 라벨, 이동 경로·focus 파싱, 창 교체·라이브 복귀 판단, 오류 문구, API 경로·인코딩·커서·`around_id`). 실기기·웹 화면의 스크롤 이동(`scrollToIndex`)·강조·키보드 동작과 실제 서버 연동은 아직 직접 확인하지 못했다.
- 아직 없는 것: 사진 메시지 검색(서버가 제외), 날짜로 이동, 검색어 기록, 결과 개수 전체 표시(서버가 전체 개수를 주지 않아 "N개 이상").

### AI 기능 (서버, `/family-chat/ai` 아래)

코드: `ai_router.py`(경로) → `ai_service.py`(업무 규칙) → `ai_repository.py`(DB 접근), 스키마는 `ai_schemas.py`. 모든 호출은 `app/shared/ai_guard.py` 의 `run` 을 거친다.

**엔드포인트**

| 메서드·경로 | 요청 | 응답 | 설명 |
|---|---|---|---|
| `GET /family-chat/ai/settings` | — | `AiSettingsOut` | 동의 여부, 내가 켤 수 있는지, 자동 분석 설정, 한도, 오늘 사용량. AI 를 부르지 않는다 |
| `PUT /family-chat/ai/settings` | `{enabled: bool}` | `AiSettingsOut` | 가족 소유자·관리자만 AI 기능을 켜고 끈다. AI 를 부르지 않는다 |
| `POST /family-chat/ai/preview` | `RangeIn` | `PreviewOut` | Claude 가 **실제로 받게 될 가명화된 대화**를 미리 보여 준다. **AI 를 부르지 않고** 하루·쿨다운 한도도 쓰지 않으며, 가족 AI 동의와 무관하게 볼 수 있다(`ai_enabled` 로 동의 여부를 알림). 사용자당 분당 20회, 넘으면 429 `too_many_previews` |
| `POST /family-chat/ai/analysis` | `RangeIn` | `AnalysisOut` | 통합 분석: 요약·중요 메시지·일정 후보·할 일 후보를 한 번에 |
| `POST /family-chat/ai/replies` | `RangeIn` | `RepliesOut` | 마지막 메시지에 이어 보낼 답장 후보(3개) |
| `POST /family-chat/ai/topics` | `RangeIn` | `TopicsOut` | 이어갈 대화 주제 추천(3~5개) |

- `RangeIn`: `limit`(기본 100, 1~200), `after_id`(기본 0). `after_id` 뒤의 최근 `limit` 개를 쓴다. 분석은 최대 200개, 답장은 최대 15개, 주제는 최대 30개까지 본다.
- `AnalysisOut`: `summary`, `important_messages[{message_id, reason}]`, `schedule_candidates[{title, date, time, place, source_message_ids}]`, `todo_candidates[{title, assignee_name, due, source_message_ids}]`, `meta`.
- `RepliesOut`: `replies[]`, `meta`. `TopicsOut`: `topics[]`, `meta`.
- `meta`(`AiMeta`): `cached`, `api_calls`(0 또는 1), `input_tokens`, `output_tokens`, `model`, `message_count`, `from_message_id`, `to_message_id`, `generated_at`, `privacy`(선택, `{masked: {종류: 개수}, blocked_messages: 개수}` — 글자·값 없이 개수만, 캐시 적중에도 같은 값).
- `PreviewOut`: `message_count`, `masked{종류: 개수}`, `blocked_messages`, `lines[{id, speaker, text, blocked}]`, `ai_enabled`, `sendable`(차단되지 않은 메시지가 3개 이상이라 AI 에 보낼 수 있는지. False 면 분석·답장·주제가 400 `too_few_messages` 이므로 앱은 요청 버튼을 막고 "민감정보가 있어 제외된 메시지가 많아요" 같은 안내를 보인다). `lines` 는 분석 요청이 Claude 로 보내는 줄과 같은 가명화된 줄(토큰 상태, 예: `[PERSON_1]`·`[PHONE_1]`, 차단된 메시지는 `[민감정보가 있어 제외된 메시지]`)이다. 원문 개인정보와 토큰 대응표는 담지 않는다. 답장(최근 15개)·주제(최근 30개)는 같은 규칙을 더 짧은 범위에 적용하므로 토큰 번호가 다를 수 있다.

**개인정보 가명화 (`app/shared/privacy`, 분석·답장·주제 공통)**

- 서버가 DB 에서 읽은 대화를 Claude 로 보내기 전에 가명화한다(앱은 대화 글자를 보내지 않는 기존 구조 그대로). 전화·이메일·주소·이름은 `[PHONE_1]`·`[EMAIL_1]`·`[ADDR_1]`·`[PERSON_1]` 토큰으로, 주민번호·카드·계좌·비밀번호가 든 메시지는 통째로 자리표시로 바꿔 보낸다. 이름 사전은 그 가족 구성원의 실제 이름·표시 이름이다. 종단간 암호화(E2EE)가 아니며 서버는 원문을 읽는다. 탐지는 규칙 기반이라 놓칠 수 있다(`docs/security/PRIVACY_PIPELINE_MODULE.md`).
- 한 사람의 실제 이름과 표시 이름(`group_members.display_name`)은 같은 토큰으로 묶는다(대표 이름은 실제 이름). 차단된 줄은 시각을 비워 보낸다(발화자 토큰은 간다). 차단되지 않은 메시지가 3개 미만이면 AI 를 부르지 않고 400 `too_few_messages`(미리보기는 `sendable: false`). 담당자는 복원 뒤에도 이 가족 구성원의 이름·표시 이름과 일치할 때만 남기고 아니면 null(후보는 유지). 응답에 남은 `‹PERSON_2›`·`[RRN]` 같은 토큰 모양은 `(알 수 없는 항목)`·`(민감 정보)` 로 바꾼다. 글자 수 한도는 재가명화 뒤에도 다시 확인한다(최대 5회 더 줄임).
- 프롬프트는 토큰을 풀어쓰지 말고 글자 그대로 복사하라고 지시한다(`PROMPT_VERSION` v3).
- **캐시에는 토큰 상태의 결과**를 저장한다(DB 의 `ai_result_cache` 에 실제 이름·전화·이메일·주소가 남지 않는다). 응답할 때마다(캐시 적중 포함) 같은 대화 범위를 다시 가명화해 같은 대응표를 만들고(같은 입력이면 같은 토큰 번호) 복원한다. 대응표는 요청 메모리에만 있고 DB·캐시·로그·응답에 넣지 않는다.
- 복원 범위는 정책(`restore_kinds`)을 따른다. 분석: 이름·주소만 복원(담당자 연결, 일정 장소), 전화·이메일 토큰은 `(연락처)`·`(이메일)`. 답장·주제: 이름만 복원, 나머지는 `(연락처)`·`(주소)` 등 일반화.
- 담당자(`assignee_name`)는 **대화에 나온 `[PERSON_n]` 토큰일 때만** 인정하고 복원된 실제 이름이 응답에 담긴다(앱의 구성원 이름 매칭은 그대로). 차단된 메시지 id 는 `important_messages`·`source_message_ids` 에서 뺀다.
- 위조·변형 토큰(이 요청이 만들지 않은 `[PERSON_9]`, `[phone_1]` 등): 일정·할 일 후보의 제목·장소·담당자에 있으면 그 후보를 버리고, 요약·이유·답장·주제 문장에서는 `(알 수 없는 항목)` 으로 바꾼다.
- 날짜·시간·담당자·기한은 대화에 없으면 null 이다. `schedule_candidates`·`todo_candidates` 는 **후보**이며 사용자가 확인해야 등록된다. AI 서버 쪽에는 등록 API 가 없고, 앱이 확인한 일정 후보를 기존 `POST /schedule/events` 로 등록한다(날짜·시간이 있는 후보만). 할 일 후보의 등록 경로는 아직 없다.

**오류 코드**

| HTTP | code | 언제 |
|---|---|---|
| 403 | `not_manager` | 관리자가 아닌 구성원이 `PUT settings` 를 호출 |
| 403 | `ai_not_enabled` | 가족 그룹이 AI 기능을 켜지 않음 (분석·답장·주제) |
| 400 | `too_few_messages` | 분석 범위의 대화가 3개 미만(AI 를 부르지 않는다) |
| 409 | `ai_busy` | 같은 가족 그룹에서 다른 AI 호출이 진행 중(동시 실행 제한 초과). 자동 재시도 없음 |
| 429 | `too_many_previews` | 미리보기를 사용자당 분당 20회 넘게 요청. `Retry-After` 헤더 (AI 한도와 별개) |
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

- **캐시 키**: 프롬프트 버전, 가명화 모듈 버전·정책(이름·차단 점수·복원 종류), 기능, 모델 이름, 날짜, 분석 범위의 첫 메시지 id·마지막 메시지 id·개수, **가명화된 줄의 해시**(원문 해시 아님). **새 메시지가 범위에 들어오면 마지막 id 가 바뀌어 키가 달라지므로** 결과가 새로 만들어진다. 프롬프트를 바꾸면 버전을 올려 옛 캐시를 쓰지 않는다.
- **글자 수 한도**: `AI_ANALYSIS_MAX_CHARS`(기본 12,000자)를 **가명화된 줄 기준**으로 넘으면 가장 오래된 메시지부터 뺀다. 실제로 쓴 범위는 `meta.message_count`, `from_message_id`, `to_message_id` 로 알려 준다.
- 일반 메시지 전송은 이 가드를 거치지 않는다(AI 호출 0).
- **AI 어시스턴트 진입점도 같은 가드를 쓴다**: `POST /ai-assistant/chat`(기능 `assistant_chat`), `POST /ai-assistant/knowledge/ask`(`knowledge_ask`), 문서 요약·답변(`doc_summary`·`doc_answer`). 대화형이라 결과 캐시는 쓰지 않는다(`cache_key=None`, 대화 원문을 남기지 않는다). 도구 루프로 한 요청이 Anthropic 을 여러 번(최대 4) 부르면 실제 호출 수를 사용 기록과 하루 한도에 센다. 어시스턴트 두 기능은 이 문서의 기본 한도(10/30/30초)가 아니라 **따로 센다**(묶음 `assistant`: 사용자 100회/일, 가족 300회/일, 쿨다운 없음, `docs/features/ai_assistant-upload-chat.md`)(`ai_guard.run` 이 응답의 `calls` 를 읽는다). 키가 없으면 외부 호출 없이 검색 결과만 돌려주므로 가드를 거치지 않는다.

### 호출 횟수 (동작별 AI 호출 수)

| 동작 | AI 호출 수 | 상태 |
|---|---|---|
| 일반 채팅 메시지 전송 (`POST /family-chat/messages`) | **0** | 구현됨 |
| 설정 조회·변경 (`GET`/`PUT /ai/settings`) | 0 | 구현됨 |
| 대화 분석 (`POST /ai/analysis`) | 최대 **1**, 캐시 적중이면 **0** | 구현됨 |
| 보낼 내용 미리보기 (`POST /ai/preview`) | **0** (한도·동의와 무관, 분당 20회) | 구현됨 |
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
