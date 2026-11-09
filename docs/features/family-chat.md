# 구현 현황: family-chat (가족 채팅)

- 요구사항: docs/requirements/family-chat.md
- 결정 기록: docs/adr/0011-ai-call-minimization.md

## 구현된 것

### 기존 (뼈대)

- `GET /family-chat/messages`(`latest`·`before_id`·`after_id`·`limit`, 결과는 항상 오래된 순), `POST /family-chat/messages` — 가족 그룹 단체 대화(`messages` 테이블). 일반 전송은 AI 를 부르지 않는다. 쿼리 규칙은 아래 "채팅방" 절.
- 모바일 소통 탭: 방 목록(가족 전체방 + 1:1 방)은 서버의 `GET /family-chat/rooms` 로 그리고, 가족 연락처는 "전체 보기 →" 줄만 두고 안의 카드 박스는 뺐다.

### 대화방 (서버, Chat 2)

- 가족마다 **가족 전체방**(kind=family) 하나, 가족 구성원 둘의 **1:1 방**(kind=direct)을 여러 개 둘 수 있다. 테이블 `chat_rooms`·`chat_room_members`·`chat_room_reads`, `messages.room_id`(Alembic `b6e2c9f4a187`, expand 만). 마이그레이션이 가족마다 전체방을 만들고 기존 메시지를 그 방에 연결하며 옛 읽음 위치를 `chat_room_reads` 로 복사한다. 옛 `chat_read_states` 는 지우지 않고 남겨 둔다.
- `GET /family-chat/rooms`: 가족 전체방(맨 위)과 내가 참여한 1:1 방(최근 메시지 순). 방마다 `{id, kind, peer_user_id, last_message, unread}`.
- `POST /family-chat/rooms/direct {user_id}`: 같은 가족 구성원과의 1:1 방을 돌려준다(없으면 만든다, 같은 두 사람의 방은 하나뿐). 자기 자신·가족이 아닌 사람은 400 `invalid_member`.
- 기존 `messages`·`read`·`read-states`·`unread` 는 **`room_id`(쿼리/본문, 선택)** 를 받는다. 생략하면 가족 전체방이라 기존 앱은 그대로 동작한다. 다른 가족의 방, 내가 참여자가 아닌 1:1 방, 없는 방은 모두 404(존재 여부를 숨김). 다른 방의 메시지 id 로 읽음 위치를 올리면 400 `invalid_message`.
- 읽음·안 읽은 수는 방별로 센다. 가족 전체방만 합류 시점 기준선을 쓰고, 1:1 방은 기준선 0 이다.
- `room_id` 가 비어 있는 옛 메시지(배포 중 구 서버가 쓴 것 포함)는 가족 전체방으로 본다.
- **1:1 방에서도 AI 도우미(분석·답장·주제·미리보기)를 쓴다**(2026-11-05 결정, 이전 "1:1 은 AI 로 보내지 않는다" 정책을 바꿈): `/family-chat/ai/*` 요청에 `room_id` 를 주면 그 1:1 방 대화만 읽는다(`ai_repository.recent_messages(room_id=)`). `room_id` 가 없으면 예전처럼 가족 전체방만 읽는다. 동의 화면·설정은 따로 두지 않고 가족방과 같은 게이트(한도·쿨다운·개인정보 가리기)를 쓴다. 호출한 사람이 그 방의 참가자가 아니면 404(방이 있는지도 드러내지 않음), **상대가 가족을 나갔으면 403 `peer_left`** 로 막는다(`ai_service._room_scope`). 분석 캐시는 메시지 id 범위·가명화한 내용 해시에 **요청한 사용자**가 더해진 키라 방마다·사람마다 따로 쌓인다(답장·주제 추천이 요청한 사람 본인의 입장으로 만들어지기 때문이다. 같은 1:1 방의 두 사람도 각자 새로 만든다). 프롬프트에 "요청한 사람"(그 사람이 대화에서 쓰인 가명화 이름, 말한 적이 없으면 그렇게 표시)을 알려, 상대가 할 말이 아니라 요청한 사람이 보낼 말을 추천하고, 요약은 친근한 말투로 쓰게 한다(`PROMPT_VERSION=v5`). 1:1 에서 '함께하기'는 받는 사람이 상대 한 명으로 고정된다(`candidateToRequestBody(..., peerId)`). 시험: `tests/test_ai_direct.py`. @가비·일정 에이전트의 1:1 사용은 후속 PR 이다(`docs/superpowers/specs/2026-11-05-direct-chat-ai-design.md`).
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

- `POST /family-chat/photos`(multipart `file`, 선택 `room_id`, 선택 `batch_id`): 사진 메시지를 보낸다. JPEG/PNG/WebP 8MB 이하(초과 413 `photo_too_large`), 긴 변 12000px·2500만 화소 이하, 실제 이미지가 아니면 400 `invalid_image`. 서버가 EXIF 회전을 반영한 뒤 **EXIF·GPS 등 메타데이터를 모두 지우고** 긴 변 1600px 이하 JPEG와 400px 이하 썸네일로 다시 만들어 저장한다. 응답은 `MessageOut` 이고 `text` 는 빈 문자열, `attachment` 에 `{id, kind, url, thumb_url, width, height, batch_id}`. `batch_id`(영문·숫자·`_-` 8~32자, 형식이 틀리면 422)는 한 번에 여러 장 올릴 때 장마다 같은 번호를 보내 서버가 `message_attachments.batch_id` 로 저장하고, 메시지·사진 모음(`/family-chat/media`) 응답에 그대로 내려 앱이 같은 번호끼리 한 묶음(앨범)으로 보이게 한다(없으면 null=한 장짜리, 옛 사진도 null).
- `GET /family-chat/photos/{id}?size=full|thumb`: 그 방에 들어갈 수 있는 사람만 본다(가족 전체방은 가족 구성원, 1:1 방은 두 사람). 못 들어가는 방·다른 가족·없는 사진은 모두 같은 404. 사진은 바뀌지 않으므로 `Cache-Control: private, max-age=31536000, immutable`, ETag(304), `nosniff`.
- 메시지 목록·방 목록의 마지막 메시지에 `attachment`(없으면 null)가 붙는다(첨부는 한 번의 쿼리로 모아 조회). 사진 메시지도 안 읽은 수에 센다.
- **AI 로 가지 않는다**: 사진 파일은 AI 에 보내지 않고, 글자 없는 사진 메시지는 AI 분석 대화에서 제외한다. 사진 보내기·보기는 AI 를 부르지 않는다.
- 저장: `DATA_DIR/chat_photos/<첨부 id>.jpg`, `<첨부 id>_t.jpg`(파일 이름은 서버가 만든 id, DB 경로가 서버가 만든 형태가 아니면 읽지 않는다). 파일을 먼저 쓰고 메시지·첨부를 한 번에 저장하며, 저장에 실패하면 파일을 지운다. 테이블 `message_attachments`(Alembic `c9a4d7e2b605`).
- 방어: 디코딩 전 크기·화소 거절, 축소 디코딩, 동시 처리 2건(초과 503 `photo_busy`), 사용자당 분당 20장(429 + `Retry-After`), 인증 전 큰 본문은 Content-Length 8MB(+여유) 초과 시 파싱 전에 413(해당 경로 한정 ASGI 미들웨어, 프로필 사진 미들웨어를 경로·한도만 바꿔 재사용).
- **운영 확인 필요**: `DATA_DIR` 이 컨테이너 볼륨에 있어야 사진이 유지된다(프로필 사진과 같다). Caddy 를 쓴다면 `/family-chat/photos` 업로드 경로에 `request_body { max_size 8.2MB }` 를 권고한다(`deploy/` 는 요청 없이 수정하지 않아 문서에만 적는다). 사진 저장량 한도·정리(삭제)는 아직 없다.
- 시험: `tests/test_chat_photos.py`, 묶음 번호는 `tests/test_photo_batch.py`.
- **앨범 묶음(앱)**: 사진 고르기에서 최대 10장을 순서대로 고르고(`pickChatPhotos`), 2장 이상이면 앱이 묶음 번호(`makeBatchId`)를 만들어 장마다 같은 번호로 올린다(한 장은 번호 없음, 한 장이 실패하면 거기서 멈춘다). 같은 사람이 같은 번호로 **연달아**(사이에 다른 글 없이, 같은 날짜) 올린 사진은 목록에서 말풍선 하나(앨범)로 묶인다: 2장은 나란히, 3장은 위 한 장+아래 두 장, 4장 이상은 2×2 에 마지막 칸 "+N"(`album.js`·`chatUtils.buildItems`). 앨범을 누르면 좌우로 넘기는 뷰어(`AlbumViewer`), 사진을 길게 누르면 그 사진의 메뉴가 열린다. 시각·읽음·반응은 마지막 사진 기준이다. 검색·고정·답장 원본 이동은 앨범 안 사진도 찾아간다(`itemHasMessage`). 시험: `tests/album.test.js`.

### 문서 파일 보내기 (서버)

- `POST /family-chat/files`(multipart `file`, 선택 `room_id`): 문서 메시지를 보낸다(201 `MessageOut`, `text` 는 빈 문자열). **문서류만, 20MB 이하**: pdf, doc/docx, xls/xlsx, ppt/pptx, hwp/hwpx, txt, csv. 이미지는 사진 경로, 실행 파일·zip 등 압축 파일·HTML·SVG·스크립트는 400 `invalid_file`, 20MB 초과는 413 `file_too_large`, 빈 파일은 400.
- 검증: 확장자 허용 목록 + 파일 앞부분 시그니처(pdf `%PDF-`, doc/xls/ppt/hwp OLE, docx/xlsx/pptx 는 zip 이면서 `[Content_Types].xml` 과 해당 폴더, hwpx 는 zip, txt/csv 는 NUL 바이트 없고 HTML·SVG·스크립트·실행 파일 머리말이 아닌 텍스트).
- 저장: `DATA_DIR/chat_files/<서버가 만든 id><허용 확장자>`. 사용자 파일명은 DB `filename` 에만(경로는 마지막 성분만, 제어·방향 문자 제거, 120자 이하).
- 응답 `attachment`: `{id, kind:"file", url:"/family-chat/files/{id}", thumb_url:null, width:null, height:null, filename, size_bytes, content_type}`. 사진 첨부는 `kind:"image"` 이고 `size_bytes` 가 추가됐다(나머지 값 그대로).
- `GET /family-chat/files/{id}`: 사진과 같은 권한(방에 들어갈 수 있는 사람만, 아니면 모두 404). `Content-Disposition: attachment; filename*=UTF-8''<퍼센트 인코딩>`, `X-Content-Type-Options: nosniff`, 허용 목록의 미디어 타입(아니면 `application/octet-stream`).
- 사진·파일 모음: `kind=file` 은 문서만, `kind=image` 는 사진만(SQL 조건), `all` 은 둘 다, `counts.file` 은 문서 수. 삭제하면 디스크 파일도 지운다.
- **AI·검색으로 가지 않는다**: 문서 메시지의 `text` 는 빈 문자열이라 검색·AI 분석에서 제외되고, 문서 내용·파일명은 로그에 남기지 않는다. 분당 20건(429), 동시 처리 2건(503 `file_busy`), 본문 20MB(+여유) 초과는 파싱 전에 413(경로 한정 ASGI 미들웨어).
- 파일: `file_router.py`·`file_service.py`, 리비전 `f06220eb955a`. 시험: `tests/test_chat_files.py`. 앱의 문서 고르기·보내기·받기는 별도 작업.

### 사진·파일 모음 (서버)

- `GET /family-chat/media?room_id=&kind=image|file|video|all&limit=&before_id=` — 채팅방 설정(⋮)의 모음 화면용. 인증 필수, 그룹은 `current_group_id`. `room_id` 가 없으면 가족 전체방(옛 NULL room 메시지 포함), 있으면 `resolve_room` 으로 확인하고 못 들어가는 방(다른 가족·참여하지 않은 1:1·없는 방)은 모두 404.
- 응답: `{items:[{attachment_id, message_id, kind, user_id, user_name, created_at, url, thumb_url, width, height, size_bytes}], next_before_id, counts:{image, file, video}}`. 최신순이고 `before_id`(메시지 id) 커서로 다음 쪽을 받는다(`next_before_id` 가 null 이면 끝). `limit` 1~100(기본 40). `counts` 는 쪽과 상관없는 그 방 전체 개수. `url`·`thumb_url` 은 기존 `/family-chat/photos/{id}[?size=thumb]` 이고 권한 검사는 그 엔드포인트가 그대로 한다.
- 권한은 SQL 조건이다: 첨부를 메시지에 join 하고 그 방의 메시지 조건으로만 조회해, 다른 방 첨부는 목록과 `counts` 어디에도 나오지 않는다. 사용자별 분당 60회 제한(초과 429 `too_many_requests`). AI·외부 호출 없음, 로그에 사용자 데이터 없음.
- 종류: `media_service.attachment_kind()` 한 곳에서만 정하고 `message_attachments.kind` 를 읽는다. 목록·개수의 종류 필터도 같은 칼럼의 SQL 조건이다. `kind=file` 은 문서(`url=/family-chat/files/{id}`, `thumb_url`·`width`·`height` 는 null), `video` 는 아직 없어 빈 목록이다.
- 파일: `media_router.py`·`media_service.py`·`media_repository.py`·`media_schemas.py`. 시험: `tests/test_chat_media.py`(최신순·커서·종류 필터·개수·방 분리·권한 격리·URL 로 사진 받기·429).

### 고정 메시지 (서버)

채팅방 위에 공지처럼 띄워 두는 **메시지 고정**. 가족 전체방과 1:1 방 모두 쓴다. 서버만 구현했고 앱 화면은 아직 없다.

- 규칙(사용자 결정): **방 안의 모든 구성원이 고정·해제**할 수 있다(쓴 사람·고정한 사람이 아니어도). **방당 최대 2개**이고 3번째를 고정하면 가장 오래된 고정이 **자동으로 풀린다**(오류 없음, 응답의 `replaced_message_id` 로 알린다). **텍스트 메시지만** 고정한다(사진 첨부가 있거나 글이 비어 있으면 400 `not_pinnable`; 사진 고정은 이후 검토). 고정은 메시지를 가리키기만 하고 메시지를 지우거나 바꾸지 않는다(본문은 복사하지 않고 조회할 때 `messages` 와 join).
- `GET /family-chat/pins?room_id=` — `{items:[{message_id, text, text_truncated, user_id, user_name, created_at, pinned_by, pinned_by_name, pinned_at}]}`. 최근 고정 2개, 고정 시각 최신순. `room_id` 가 없으면 가족 전체방. `text` 는 메시지 본문을 200자로 자른 것이고(말줄임 없음) 잘렸으면 `text_truncated=true`.
- `POST /family-chat/pins {room_id?, message_id}` — `{item, replaced_message_id: int|null, already_pinned: bool}`(새 고정도 이미 고정된 경우도 200). 그 방의 메시지가 아니거나 없는 id 면 400 `invalid_message`. **같은 메시지를 다시 고정하면 멱등**: 새로 만들지 않고 기존 고정(고정한 사람·고정 시각)을 그대로 두며 `already_pinned=true`, 순서도 바뀌지 않는다.
- `DELETE /family-chat/pins/{message_id}?room_id=` — 204. 고정돼 있지 않으면 404 `not_found`.
- 권한: 인증과 `current_group_id` 필수, 방은 `resolve_room` 으로 확인한다. 다른 가족의 방·내가 참여하지 않은 1:1 방·없는 방은 조회/고정/해제 모두 같은 404 라 존재 단서가 없다(`room_id` 가 없는 옛 메시지는 가족 전체방 메시지로 고정할 수 있다). 메시지-방 일치는 SQL 조건(`room_messages`)으로 확인한다.
- 제한: 고정·해제(POST/DELETE) 합쳐 사용자별 분당 30회(429 `too_many_requests` + `Retry-After`, 프로세스 메모리 `FailureLimiter`). 조회에는 제한이 없다.
- **동시성**: 같은 방의 고정 변경은 방 행(`chat_rooms`)을 `SELECT ... FOR NO KEY UPDATE`(SQLAlchemy `with_for_update(key_share=True)`)로 잠가 고정끼리 한 번에 하나씩 처리한다. 일반 `FOR UPDATE` 는 같은 방 메시지 INSERT(FK 검사의 KEY SHARE)를 잠깐 막지만 `FOR NO KEY UPDATE` 는 막지 않아 메시지 전송·읽음은 고정 중에도 지연되지 않는다(PostgreSQL 에서 확인). SQLite 는 FOR UPDATE 가 없어 무시되지만 쓰기가 원래 직렬이다. 잠근 뒤 다시 읽고, 새 고정을 추가한 같은 트랜잭션에서 최근 2개를 넘는 오래된 고정을 지우고 **응답 항목도 commit 전에(잠금 안에서) 만들어** commit 하므로(commit 뒤 재조회로 인한 끼어든 해제와의 충돌·500 이 없다) 동시 요청에도 2개를 넘는 상태가 남지 않는다. 같은 메시지를 동시에 고정하는 경우는 `(room_id, message_id)` 유니크 제약이 막고 한 요청만 새 고정, 나머지는 `already_pinned=true`. 사후 정리 방식 대신 잠금을 택한 이유: 고정은 방별 쓰기 빈도가 낮아 잠금 경합이 문제가 되지 않고, 잠깐이라도 3개가 보이는 구간이 없다.
- **AI·외부로 보내지 않는다**: 고정은 AI 를 부르지 않고 고정된 메시지가 AI 분석 입력에 따로 들어가지도 않는다. 로그에 메시지 글자를 남기지 않는다.
- 테이블 `chat_pinned_messages`(Alembic `e8c1f4a7b903`, 새 테이블만 추가하는 expand 리비전). 스키마 게이트에서는 `family_chat` 기능의 전제로 자동 잡힌다(기능 `models.py` 의 모델).
- 파일: `pin_router.py`·`pin_service.py`·`pin_repository.py`·`pin_schemas.py`. 시험: `app/features/family_chat/tests/test_pins.py`(고정·해제·멱등·자동 교체·최신순 2개·텍스트만·다른 방 메시지·모든 구성원·권한 격리·속도 제한·로그·동시성), `tests/test_membership_enforcement.py`(엔드포인트 목록). PostgreSQL 동시성은 임시 컨테이너에서 별도 스크립트로 확인했다(12개 스레드가 같은 방에 동시에 고정 x5회, 항상 2개).

### 메시지-일정 연결 (서버)

채팅에서 AI 후보를 확인해 **일정/할 일로 등록**할 때 원본 대화 메시지와의 연결을 저장한다. 말풍선 "등록됨" 표시와 가족 할 일 화면의 "원본" 보기(원본 메시지로 이동)에 쓴다. 서랍의 "가족 일정 · 할 일" 목록은 가족 할 일로 통합하면서 없앴다.

- 저장 위치: `chat_message_links`(family_chat). **일정(schedule) 테이블·모델은 건드리지 않고 import 하지도 않는다**(다른 기능 담당·교차 import 금지). 연결은 `(방, 메시지, 종류 event|todo, 대상 id)` 한 줄이고, 등록 시점의 제목·날짜·시간 **복사본**과 만든 사람을 가진다. 원본 메시지 본문은 복사하지 않고 조회할 때 `messages` 와 join 으로만 가져온다.
- `POST /family-chat/links {room_id?, message_id, kind:"event"|"todo", target_id, title, date?: "YYYY-MM-DD"|null, time?: "HH:MM"|null}` — 201 `LinkOut`. **멱등**: 같은 (방, 메시지, 종류, 대상)이 이미 있으면 새로 만들지 않고 기존 연결(제목 등 그대로)을 **200** 으로 돌려준다(겹친 요청은 유니크 제약이 막는다). `message_id` 는 그 방의 **텍스트 메시지**여야 한다(다른 방·없는 id·사진·빈 글은 400 `invalid_message`). `title` 은 공백을 정리한 뒤 1~120자(아니면 422), `time` 은 `HH:MM`. `kind="todo"` 면 `target_id` 가 **이 가족의** `family_todos` 에 있어야 한다(없거나 다른 가족 것이면 같은 400 `invalid_target` 이라 존재 단서가 없다). 방당 연결은 최대 200개(초과 400 `too_many_links`, 방 행 잠금 아래에서 세어 동시 요청에도 지킨다).
- `GET /family-chat/links?room_id=&kind=&target_id=&limit=` — `{items:[LinkOut]}` 최신순(시각이 같으면 id 큰 쪽). `limit` 1~100(기본 50), `kind`·`target_id` 는 선택 필터. 조회에는 속도 제한이 없다.
- `DELETE /family-chat/links/{link_id}?room_id=` — 204. **연결을 만든 사람만** 지운다(같은 방의 다른 구성원은 403 `forbidden`, 없는 id 는 404). 메시지·일정·할 일은 그대로 남는다.
- `LinkOut`: `{id, room_id, message_id, kind, target_id, title, date, time("HH:MM"), created_by, created_by_name, created_at, message_text(원본 앞 100자), message_user_name}`.
- 권한: 인증과 `current_group_id` 필수, 방은 `resolve_room` 으로 확인하고 모든 조회·삭제는 그 방 id 를 SQL 조건에 넣는다. 다른 가족의 방·참여하지 않은 1:1 방·없는 방은 조회/생성/삭제 모두 같은 404 다(가족 전체방은 방 id 로 저장하고 `room_id` 가 비어 있는 옛 메시지도 연결할 수 있다).
- 제한: 생성·삭제 합쳐 사용자별 분당 30회(429 `too_many_requests` + `Retry-After`, 프로세스 메모리 `FailureLimiter`).
- 입력 검사: 제목·`target_id`·`room_id`·`link_id` 에 NUL 을 포함한 제어문자(C0/C1, 탭·개행 제외)가 있으면 DB 를 부르기 전에 422(`invalid_title`/`invalid_query`)로 거절한다(PostgreSQL 에서 500 이 되고 로그에 입력이 남는 것을 막는다). 제목은 보이지 않는 글자(Cf, 예: ZWSP)를 뺀 뒤 비면 422 `invalid_title`.
- **동시성**: 생성과 삭제 모두 같은 방 행 잠금(`FOR NO KEY UPDATE`) 아래에서 확인·변경하고 commit 은 서비스에서 한다(이미 지워진 연결을 200 으로 돌려주는 경쟁을 막기 위함). SQLite 시험으로는 이 경쟁을 재현하지 못했고 PostgreSQL 동시 실행은 이번에 직접 확인하지 못했다.
- **한계(복사본)**: `kind="event"` 는 일정 기능을 import 할 수 없어 `target_id` 의 존재를 검증하지 않는다. 일정이 나중에 지워지거나 바뀌어도 연결 목록은 등록 시점의 복사본(제목·날짜·시간)을 그대로 보여준다. 할 일도 연결을 만든 뒤 제목을 고치거나 지우면 복사본과 달라질 수 있고 연결은 자동으로 지워지지 않는다(앱이 최신 대상과 맞추거나 연결을 지운다).
- **일정 화면에서 '원본 대화 보기'(이번 범위 아님)**: 일정 앱이 일정의 원본 대화로 가려면 `GET /family-chat/links?kind=event&target_id=<일정 id>`(가족 전체방은 `room_id` 생략, 1:1 방은 `room_id`)로 `message_id`·`room_id` 를 찾고 채팅의 `focusOn(message_id)`(around_id 조회)로 이동하면 된다. 이를 위해 `target_id` 필터를 서버에 미리 넣어 두었다. 방마다 조회해야 하는 한계는 있다(여러 방을 한 번에 찾는 조회는 필요해지면 추가).
- **AI·외부로 보내지 않는다**: AI 를 부르지 않고 로그에 제목·메시지 글자를 남기지 않는다.
- 파일: `link_router.py`·`link_service.py`·`link_repository.py`·`link_schemas.py`, 리비전 `c4d8a2e6b157`(새 테이블만, expand). 시험: `app/features/family_chat/tests/test_links.py`(생성·멱등·목록 최신순·필터·limit·삭제 권한·검증·todo 대상·200개 제한·권한 격리·1:1 방·속도 제한·로그·join 본문), `tests/test_membership_enforcement.py`(엔드포인트 목록).

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
- 소통 탭은 화면에 올 때마다 가족 정보(`GET /family-group/groups/me`)와 대화방 목록(`GET /family-chat/rooms`: 마지막 메시지·안 읽은 수 포함)을 한 번 읽는다. 화면이 보이는 동안에는 10초마다(`ROOM_REFRESH_MS`) 방 목록만 조용히 다시 읽어 방별 안 읽은 수·마지막 말·시각을 갱신한다(가족 정보는 다시 읽지 않고, 실패하면 화면을 그대로 두며, 앱이 뒤에 있거나 읽는 중이면 건너뛴다). 하단 탭의 전체 합계(30초 폴링)와 같은 데이터라 숫자가 어긋나지 않는다. 하단 탭 합계(`useTotalUnread`)도 방을 막 나왔다면 읽음 올리기가 끝난 뒤에 읽어(`waitForPendingMarkRead`), 방 목록과 같은 기준으로 합산한다. 상단 검색창은 방 이름으로 거른다. 가족이 없으면 빈 화면의 "가족 만들기"·"초대 코드로 참여" 버튼이 가족 그룹 화면을 거치지 않고 바로 `/family-create`·`/family-join` 으로 간다.
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
- **알려진 우회(팀 영역)**: `features/ai-assistant/components/AiOffCard.js`(`enableAi`)는 같은 PUT 을 확인 카드 없이 보낸다(그 카드의 "관리자에게 요청" 안내는 AI 켜기 권한이 구성원 누구나로 바뀐 뒤 맞지 않아 팀 정리가 필요하다). `tests/privacycopy.test.js` 가 PUT 호출 위치를 허용 목록으로 검사해 새 우회가 생기면 실패한다. 담당 팀과 확인 카드를 shared 로 올려 통합해야 한다.
- **동의 문구의 근거와 한 곳 관리**: 문구는 `features/family-chat/privacyCopy.js` 상수에만 있다. 서버에서 이 동의(`ai_guard.is_enabled`/`run` 의 동의 단계)는 가족 채팅 AI(analysis·reply·topics, 가명화), AI 비서(`assistant_chat`: 질문·찾은 문서가 가려지지 않음), 일정(`schedule` 질문·일정 제목 정규식 마스킹), 가계·돌봄 도우미(`billing_agent`·`care_agent`: 질문만 `mask_text`, 조회 결과의 이름·금액·위치는 가려지지 않음)에 모두 쓰인다. 그래서 안내는 "대화 분석(답장·주제 추천 포함)만 가려서 보내고 나머지는 가려지지 않을 수 있다"고 쓴다. 대화 분석 줄은 "한 번에 보내고, 켜 두면 누를 때마다 별도 확인 없이 바로 전송되며 가려진 내용은 결과 화면에 개수로 알린다"까지 밝히고(요약 두 번째 줄에도 "별도 확인 없이 바로 AI로 전송"을 쓴다), AI 비서 줄은 "주민번호·카드·계좌·비밀번호가 든 입력은 서버가 막는다"를 덧붙인다. 서버가 다른 기능에도 가명화를 넓히면 `privacyCopy.js` 만 고친다. 시험 `tests/privacycopy.test.js`.
- **켜져 있으면**: 오늘 사용량을 횟수 없이 **Claude 사용량 화면처럼 게이지 바 두 줄(나·가족)과 "N% 사용됨"** 으로 보인다(`parseAiSettings` 의 `userUsedRatio`·`groupUsedRatio`, `shared/aiUsage.js` 의 `usageGauges`, `shared/components/UsageGauge.js`). 80% 이상 썼으면 붉은색과 함께 "거의 다 썼어요" 글을 붙인다. 스크린리더에는 사용한 퍼센트를 읽어 준다. 패널에는 상시 안내문을 두지 않는다("대화 분석하기" 버튼과 사용량만). 개인정보 가림·바로 전달·결과 약 10분 저장 안내는 마이 > 가비 AI 이용 안내(`aiGuide.js`)와 동의 상세(`CONSENT_DETAILS` 의 대화 분석 줄)에 있다. 호출이 끝날 때마다 설정을 다시 읽는다.
- **버튼은 "대화 분석하기" 하나**(분석한 뒤에는 "다시 분석하기"). 답장 추천·대화 주제 추천 버튼은 없다. **누르면 확인 카드 없이 바로** `POST /family-chat/ai/analysis` 를 한 번 부른다. 개인정보 설명·동의는 "AI 기능 켜기" 동의 카드(소유자·관리자가 켤 때 한 번)에서 받고, 켜진 패널에는 버튼 위에 항상 "“대화 분석하기”를 누르면 개인정보를 가린 최근 대화가 바로 AI로 전달돼요. 분석 결과는 잠시(약 10분) 저장돼 같은 요청에 다시 쓰여요." 안내(`privacyCopy.js` 의 `PANEL_NOTICE`)를 보인다.
- **결과는 한 화면**: 요약 -> 중요 메시지 -> 일정 후보 -> 할 일·부탁 후보 -> 답장 추천 -> 대화 주제 추천 순서. 비어 있는 섹션은 "…가 없어요" 안내를 보인다. 결과 아래에 "대화 N개 기준 · 시각", "방금 분석 · AI 호출 N번 · 토큰 N" 또는 "저장된 결과(AI 호출 없음)", 그리고 가려진 개수(`meta.privacy`)를 보인다.
  - 일정 후보는 날짜·시간이 모두 있어야 "일정으로 등록"이 켜진다. 누르면 기존 `POST /schedule/events` 로 등록한다(`scheduleEventBody`: 날짜·시간은 기기 시간대로 해석해 UTC 로 보내고, 장소는 메모에 "장소: …"로 넣는다). 등록 결과는 후보마다 따로 보인다. **날짜나 시간이 빠진 후보는 그 자리에서 채울 수 있다**(`ScheduleCandidateRow`, 순수 함수 `scheduleCandidateUtils.js`): 날짜가 없으면 날짜 칩(오늘·내일·직접 입력 YYYY-MM-DD, 지난 날짜·없는 날짜는 안 됨), 시간이 없으면 시간 입력(HH:MM, 숫자를 치면 콜론이 붙고 00:00~23:59 만 인정)이 나타나고, 둘 다 정해지면 바로 등록 버튼이 켜진다. 후보에 이미 있는 값은 덮어쓰지 않고 없는 값은 지어내지 않는다. 가족방에서 가비가 올린 긴 답(목록)이 어색하게 꺾이지 않도록 가비 말풍선 폭은 92%까지 넓다.
  - 할 일 후보는 "할 일로 등록"으로 등록한다(아래 "할 일" 절).
  - **답장 추천·대화 주제 추천**은 분석 응답의 `replies`·`topics`(문자열 목록)를 쓴다. 한 줄을 누르면 채팅 입력창에 넣고 패널을 닫는다(입력창에 이미 글이 있으면 공백을 두고 이어 붙인다). 보내기는 구성원이 직접 누른다. 구 서버 응답에 이 필드가 없으면 빈 목록으로 본다(`messages.js` 의 `parseAnalysis`). 앱은 `/family-chat/ai/replies`·`/topics` 를 더 부르지 않는다(`suggestReplies`·`suggestTopics` 삭제).
- 분석 요청은 범위를 따로 고르지 않는다(최근 대화 100개, `after_id=0` 기본값).
- 오류 문구는 `messages.js` 의 `chatErrorMessage` 가 서버 코드를 한국어 문장으로 바꾼다. 쿨다운은 대기 시간을 덧붙인다.
- 앱은 결과를 기기 저장소에 쓰지 않는다. 마지막 결과는 화면이 살아 있는 동안만 남는다. 서버는 AI 결과를 잠시(약 10분) 캐시해 같은 요청에 다시 쓴다(안내 문구: "분석 결과는 잠시(약 10분) 저장돼 같은 요청에 다시 쓰여요").

**분석 결과의 가려진 개수와 승인 정책** (순수 함수 `privacyPreview.js`)

- 예전의 "보내기 전 확인" 카드(`AiConfirmCard`, 미리보기 `POST /family-chat/ai/preview` 호출, "AI에 보내기"/"취소")는 **없앴다**. 앱은 `previewAiRange` 를 더 쓰지 않는다(서버 엔드포인트는 남아 있다).
- **결과 아래 한 줄**: 응답 `meta.privacy`(`{masked, blocked_messages}`, 선택 필드)가 있으면 "개인정보 N개를 가려서 보냈고 메시지 M개는 제외했어요"(한쪽만 0 이면 해당 부분만, 둘 다 0 이면 생략)를 분석 결과 아래에 보인다(`privacyCaption`). "저장된 결과(AI 호출 없음)" 안내와 함께 보인다.
- **보낼 수 있는 대화가 부족하면** 분석이 400 `too_few_messages` 를 돌려주고 기존 오류 문구(`chatErrorMessage`)로 보인다.
- **승인 정책**: AI 호출은 가족 AI 동의(`enabled`)가 켜진 패널에서 "대화 분석하기"/"다시 분석하기"를 누를 때만 일어난다(동의가 꺼져 있으면 버튼이 없다). 일정 후보 "일정으로 등록"·할 일 후보 "할 일로 등록"은 사용자가 누를 때만 동작하고, 답장·주제 추천(분석 결과 안)은 누르면 입력창에 **넣기만** 한다(`pickReply` 는 `setDraft` 만, 자동 전송 없음).
- **등록한 후보 표시는 다시 분석해도 이어진다(release/1.1 수정)**: 일정으로 등록하거나 함께하기로 보낸 후보는 순번이 아니라 내용(`candidateKey`: 필드를 정렬한 값, 일정·할 일 구분)으로 기억해 두어서, "다시 분석하기"를 눌러 같은 후보가 다시 와도 "일정으로 등록했어요"/보냄 표시가 유지되고 버튼이 다시 켜지지 않는다. 기록은 앱을 켜 둔 동안만 메모리에 있고(`candidateKey.js`, 저장소·서버에 남기지 않는다) 앱을 다시 켜면 사라진다. 등록 실패·진행 중 상태는 기억하지 않는다. 시험 `tests/chatcandidatekey.test.js`.
- 시험: `apps/mobile/tests/privacypreview.test.js`(`privacyCaption`·`maskedTotal`, 승인 정책 소스 확인: 확인 카드 없음, 버튼 한 번에 `analyzeChat`, 동의 게이트, 상시 안내문). 실기기·서버 연동은 직접 확인하지 못했다.

**소통 탭에서 AI 를 뺀 것**: 소통 탭에는 AI 카드(`AiCard.js`)를 두지 않는다(작업 트리에서 파일 삭제). AI 진입점은 채팅방의 ✨ 하나다.

**테스트**

- 앱 `apps/mobile/tests/chatroom.test.js`(11개): 메시지 병합·중복 제거, 임시 메시지 정리, 마지막·처음 id, 시각 표시, 날짜 묶기·이름 생략, 입력 판정, 미리보기, 폴링 간격, 오류 문구, 메시지 API 경로·쿼리.
- 앱 `apps/mobile/tests/chat.test.js`(7개): AI 오류 문구, 결과 설명, 일정 후보 등록 판정, 설정 응답 해석, AI 호출 경로·본문(대화 글자 없음), 일정 등록 호출 조건, 패널 호출 규칙(닫혀 있으면 호출 없음).
- 서버 `apps/api/app/features/family_chat/tests/test_message_paging.py`(5개): latest 오름차순, latest 가 limit 보다 적을 때, before_id 로 빈틈·중복 없이 넘기기, before_id 가 그 id 를 빼는지, after_id 기존 동작.

### 대화방·1:1 채팅 (앱, 서버 `GET /family-chat/rooms`·`POST /family-chat/rooms/direct` 계약 사용)

- **소통 탭**(`FamilyChatScreen`): 서버 방 목록을 `buildRoomRows`(`listUtils.js`)로 행으로 바꿔 보인다. 가족 전체방이 맨 위, 1:1 방은 서버 순서(최근 메시지 순). 1:1 행은 상대 프로필 사진/이니셜(`UserAvatar`)과 상대 이름(별명 우선), 마지막 메시지 미리보기, 안 읽은 수 배지를 보인다. 상대가 구성원 목록에 없으면 이름을 "가족"으로 둔다. 접근성 라벨은 "<이름>님과 1:1 대화, …".
- **새 대화**(상단 ✎ 버튼): 나를 뺀 가족 구성원 목록(`NewChatPicker`)을 펼치고, 한 명을 누르면 `POST /family-chat/rooms/direct` 로 1:1 방을 열거나(없으면 만들고) 그 방으로 간다. 열고 있는 동안 다른 줄은 눌리지 않고, 실패하면 목록 아래에 오류 문구를 보인다.
- **채팅방**(`ChatRoomScreen`): 경로 인자 `roomId`(없으면 가족 전체방)와 `peer`(1:1 상대 id, 방 이름을 정하는 데만 사용)를 받는다. 1:1 방에도 **AI 도우미(✨) 버튼·패널**이 있고 `AiPanel` 이 `roomId` 를 분석 요청에 실어 보낸다(상대가 가족을 나갔으면 서버가 `peer_left` 로 거절하고 앱이 안내 문구를 보인다). 메시지 조회/전송, 읽음 올리기, 읽음 상태 조회가 모두 `roomId` 를 같이 보낸다(`api.js`; `roomId` 가 없으면 이전과 같은 요청). 안 읽은 사람 수는 그 방의 읽음 상태(1:1 이면 두 사람)로 센다.
- 시험: `tests/rooms.test.js`(행 만들기·상대 이름/사진·나간 상대·후보 목록·접근성 라벨·API 경로와 본문).
- 아직 없는 것: 1:1 방 나가기/삭제, 방 이름 바꾸기, 두 명 넘는 그룹 방.

### 읽음 표시·안 읽은 수 (앱, 서버 PR #54 계약 사용)

- **자동 읽음 처리**(`useReadMarker.js`): 눌러서가 아니라 채팅방 화면이 보이는 동안(포커스 + 앱이 앞에 있을 때) 목록의 가장 큰 서버 메시지 id 가 지금까지 올린 값보다 커졌을 때만 `POST /family-chat/read {message_id}` 를 보낸다. 연속 변화는 약 0.8초 모아 한 번만 보내고, 낙관적 임시 메시지는 제외하며, 같은 id 는 다시 보내지 않는다. 내가 보낸 메시지가 가장 최신이면 서버가 이미 내 읽음 위치를 올렸으므로 호출하지 않는다. 실패하면 조용히 두고 다음에 id 가 바뀔 때 다시 시도하며(폴링 간격은 건드리지 않음), 화면이 안 보이게 되거나 닫힐 때 대기 중인 값이 있으면 디바운스를 기다리지 않고 즉시 한 번 올린다(flush). 진행 중인 호출은 `pendingRead.js` 에 추적해, 소통 탭이 `GET /unread` 를 부르기 전에 기다린다(배지가 옛 숫자로 남지 않게).
- **설계 의도(카카오톡 방식)**: 위로 스크롤해 지난 대화를 읽는 중이어도 방을 열어 둔 동안 새로 온 메시지는 읽음으로 처리한다 — "방을 열면 읽음".
- **읽지 않은 사람 수**: 기존 3초 새 메시지 폴링 틱에서 `GET /family-chat/read-states` 도 함께 부른다(별도 타이머 없음, 화면이 보일 때만). 폴링 호출이 틱마다 1개 늘어난다. 폴링 간격은 메시지 조회 실패만 반영한다(최대 30초). 읽음 조회는 실패하면 자체 횟수에 따라 2^n 틱(최대 10틱)마다 한 번 재시도하고, 404 면 이 세션 동안 끄며, `retry()` 는 읽음 조회도 즉시 한 번 부른다. 아직 못 받았거나 실패 중이면 숫자를 숨긴다. `chatUtils.unreadCount` 가 내가 보낸 서버 메시지에 대해 "read-states 응답(서버가 현재 구성원 전원+합류 기준선을 준다)에서 나를 제외하고 `last_read_message_id` < 메시지 id 인 사람 수"를 센다(구성원 목록은 쓰지 않아 나간 구성원이 영구 안 읽음으로 세어지지 않는다). 임시·실패 메시지와 상대 메시지에는 표시하지 않는다.
- **말풍선**(`MessageBubble`): 내 말풍선의 시각 위(왼쪽 아래)에 0 보다 클 때만 작은 꿀색 숫자를 보인다(접근성 라벨 "아직 N명이 읽지 않았어요"). 모두 읽었으면 아무것도 보이지 않는다.
- **말풍선 폭 수정**: 웹(react-native-web)에서 상대(왼쪽) 말풍선이 내용 폭인 column 의 70% 로 계산돼 "강/남/구" 처럼 한 글자씩 줄바꿈되던 문제를, 상대 column 에 `maxWidth: "80%"`(row 기준) 를 주고 상대 말풍선의 70% 를 100% 로 바꿔 고쳤다(`tests/bubblelayout.test.js`).
- **소통 탭 방 행**(`RoomRow`, `FamilyChatScreen`): 화면이 올 때마다 한 번 `GET /family-chat/unread` 를 `getRoomInfo`·`listMessages` 와 함께 부른다(폴링 없음, 실패해도 목록은 그대로). 오른쪽 아래에 복숭아색 원 배지(99 초과는 "99+", 0 이면 숨김)를 보이고 안 읽은 수가 있으면 마지막 메시지를 굵게 한다. 접근성 라벨에 수가 들어간다. 채팅방에서 돌아오면(포커스) 다시 불러 갱신된다.
- 대화 글자는 이 호출들에 없다(메시지 번호와 사용자 id 만 오간다). 일반 전송과 읽음 처리는 AI 를 부르지 않는다.
- **"여기까지 읽었습니다" 구분선(17번)**: 방에 들어올 때 내 마지막 읽음 메시지 바로 뒤, 첫 안 읽은 메시지 위에 가운데 정렬 한 줄(양쪽 가는 선 + 꿀색 글자)을 보이고, 입장하면 그 위치(화면 위쪽)로 스크롤한다(카카오톡 방식). 구분선이 없으면 이전처럼 맨 아래로 간다.
  - **기준 고정**(`useReadBaseline.js`): 방 정보가 준비되면 즉시 `GET /family-chat/unread` 를 한 번 불러 `{lastRead, unread}` 를 고정한다(서버 변경 없음). 읽음 올리기(`useReadMarker`)는 입장 약 0.8초 뒤라 그보다 먼저 요청이 나가고, 이후 읽음이 올라가도 구분선은 그대로다. 방이 바뀌면 초기화, 실패하거나 1.2초 안에 못 받으면 구분선 없이 열린다.
  - **위치 규칙**(`chatUtils.unreadDividerId`, `buildItems(messages, { dividerBeforeId })`): 기준보다 id 가 큰 첫 서버 메시지 앞(임시·실패·가비 개인 답 제외, 삭제된 메시지는 센다). 그 뒤에 남이 보낸 메시지가 없거나 안 읽은 수가 0 이거나 기준이 없으면 없다. 안 읽은 메시지가 처음 불러온 50개를 넘어 기준이 목록 밖이면 목록 맨 위(가장 오래된 메시지 앞)에 놓인다. 날짜가 바뀌는 곳에서는 날짜 줄 다음에 온다. 과거 창(`focusing`)이나 검색·고정 공지로 열 때는 만들지 않는다. 열린 방에서 새 메시지가 와도 같은 자리에 머문다. 안 읽은 메시지가 50개를 넘어 구분선이 맨 위일 때는 위로 불러오기(`loadOlder`)가 그대로 동작하며, 새로 불러온 메시지의 id 가 기준보다 크면 구분선이 새 맨 위로 옮겨 간다. 구분선 바로 아래 메시지는 이름을 다시 보인다(카카오톡 방식). 입장 직후(자리 잡기 전) 내가 보내면 구분선으로 가지 않고 맨 아래에 둔다.
  - **입장 스크롤**: 기준과 첫 메시지가 모두 준비될 때까지 목록은 숨겨 둔 채(기존 `listReady`, 최대 1.5초) 맨 아래 따라가기를 잠시 멈추고, 구분선 줄로 `scrollToIndex`(`viewPosition` 0.05)한다. 이동 동안 `nearBottom=false`·`settling=true` 로 두어 `scrollToEnd` 나 위로 불러오기가 위치를 덮어쓰지 않게 하고, 실패하면 `onScrollToIndexFailed` 재시도(같은 위치 값)를 쓰고, 재시도가 모두 끝난 뒤에 목록을 보이고 구분선 모드를 푼다. 사용자가 맨 아래 근처로 내려오면 기존 `onScroll` 이 `nearBottom=true` 로 되돌린다. 이동한 뒤 새 메시지가 오면 "새 메시지, 맨 아래로" 버튼이 뜬다.
  - **읽음 올리기와의 관계**: 읽음 올리기는 이번 작업 범위 밖이라 기존대로 입장 0.8초 뒤 최신 id 로 올린다. 그래서 구분선 위치에서 시작하면 아직 화면에 보이지 않은 아래 메시지도 읽음 처리된다(구분선은 방 화면을 닫을 때 사라진다. 서랍에서 다른 화면을 열었다 돌아오면 구분선은 그대로 두고 화면만 맨 아래로 간다).
  - 시험: `tests/readdivider.test.js`(위치 규칙·buildItems 끼우기·날짜 경계). 실제 기기·웹에서의 스크롤 위치와 재시도는 아직 직접 확인하지 못했다.
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
- **가비 기록에 저장(B안, 서버 변경 없음)**: 가족 전체방의 사진을 전체 화면으로 볼 때 아래에 "가비 기록에 저장" 버튼이 있다(`PhotoViewer` 의 `onSaveToRecord`, 1:1 방의 사진에는 없다 — 기록은 가족 그룹 단위로만 나뉘어 있어 한번 저장되면 가족 누구나 볼 수 있기 때문에 `canSaveToRecord({direct, attachment})` 가 막는다). 누르면 `saveToRecord.js` 가 사진 원본을 받아 **기존 파일 올리기 `POST /ai-assistant/files`** 로 올린다(`api.uploadToAssistantRecord`, AI 비서의 api 파일을 가져오지 않고 공통 래퍼로 직접 호출). 서버는 받자마자 `received` 로 응답하고 원본 보관 -> 글자 읽기(OCR) -> 개인정보 가리기 -> 분류 -> 기록 저장을 뒤에서 한다. 그 뒤 `@가비` 가 기록 검색으로 찾을 수 있다(처리에 몇 초~1분, 글자가 없는 사진은 설명 입력이 필요할 수 있다). **웹**은 `downloadPhoto` 로 받은 blob 을 multipart `file` 로 올리고(AI 비서 `uploadFile` 의 웹 422 문제는 이 경로에 없다), **네이티브**는 `loadNativeDeps` 로 캐시 파일에 받아 `{uri, name, type: "image/jpeg"}` 로 올린 뒤 임시 파일을 성공·실패 모두 지운다. 서버가 준 사진 경로만 받고(낯선 경로는 받기 전에 거절), 저장 중이거나 이미 저장한 사진은 다시 올리지 않는다(같은 사진이 기록에 두 번 쌓이지 않게, 앱 안의 상태이고 서버가 중복을 막는 것은 아니다). 결과 문구는 "가비 기록에 저장했어요. 읽는 데 잠시 걸릴 수 있어요" / "가비 기록에 저장하지 못했어요" / "이 환경에서는 저장할 수 없어요". 시험 `tests/chatphotorecord.test.js`. 앱 화면과 실제 기록 저장은 아직 직접 확인하지 못했다.
- **인증 이미지**: 공용 `shared/components/AuthImage.js` 가 `useProfilePhoto`(네이티브 expo-image 헤더, 웹 blob 캐시)로 받는다. `shared/photoCache.js` 의 `photoPath` 는 프로필 사진 경로에 더해 서버가 준 `/family-chat/photos/<id>` 와 `?size=thumb|full` 형태만 허용한다(그 밖의 주소에는 로그인 헤더가 나가지 않는다). 채팅 사진은 바뀌지 않으므로 캐시에서 원본·썸네일을 서로 밀어내지 않는다. 토큰은 주소·캐시 키에 들어가지 않는다. `UserAvatar` 동작은 그대로다.
- **미리보기**: 마지막 메시지가 사진(글자 없음)이면 소통 탭 방 목록과 접근성 라벨에 "사진"(내 것은 "나: 사진")으로 보인다(`chatUtils.previewText`, `buildRoomRows` 가 이를 사용).
- 시험: `apps/mobile/tests/chatphotos.test.js`(미리보기, 경로 허용/거부, 캐시 키, `sendPhoto` 요청 모양, 오류 문구, 표시 크기, 파일 형식·한도). 실기기·웹의 파일 선택, canvas 줄이기, 네이티브 헤더 로딩, 전체 화면 보기는 아직 직접 확인하지 못했다.
- 아직 없는 것: 여러 장 한 번에 보내기, 네이티브 사진 공유(저장은 위 "채팅방 서랍 · 사진 모음" 절), 동영상·파일, 사진 업로드 취소.

### 채팅방 서랍 · 사진 모음 (앱)

- **서랍**(`components/RoomDrawer.js`): 채팅방 상단 ⋮ 를 누르면 오른쪽에서 열린다(React Native `Modal` 투명 + `Animated`, 폭은 화면의 85% 최대 360, 180ms). 어두운 덮개·X·안드로이드 뒤로가기로 닫는다. AI 는 기존 ✨ 버튼에 그대로 있다. 위에서부터 방 이름(가족 전체방은 가족 이름, 1:1 은 상대 표시 이름)과 X, 구성원 드롭다운(`MemberStrip`: "가족 구성원 N명"을 누르면 사진/이니셜+이름 목록이 펼쳐진다, 나 먼저·표시 이름 우선 / 1:1 은 "대화 상대"와 상대 한 명), "채팅 관리"·"채팅방 설정" 두 구역. 행 정의와 방 종류별 차이는 순수 함수 `mediaUtils.buildDrawerSections`·`drawerMembers`·`drawerTitle` 에 있다.
- **동작하는 행**: 사진 · 동영상(→ `/chat-media`), 가족 할 일(→ `/family-todos`). 게시판(서랍을 닫고 지난 공지까지 모아 보는 `/chat-board` 화면으로 이동 — 아래 "게시판 목록 화면(앱)").
- **서랍 이동은 한 번만**: 이동 행(사진 · 동영상, 게시판, 가족 할 일)은 한 번 누르면 즉시 잠기고 닫히는 180ms 동안의 연속 누름은 무시한다(`canNavigateFromDrawer`). 서랍은 방 이름을 주소에 싣지 않고 `roomId`·`peer` 만 넘긴다.
- **준비 중인 행**(제목 옆 "준비 중" 배지, 누르면 서랍 안에 "준비 중이에요" 안내만): 알림 설정만 남았다(공유 문서·AI · 개인정보 보호 설정·채팅방 정보 수정 행은 서랍에서 뺐다). **채팅방 나가기**(빨간 글자): 가족 전체방은 가족 탈퇴 기능이 없어 "가족 채팅방은 나갈 수 없어요", 1:1 은 "준비 중이에요" 안내만 한다.
- 1:1 방과 가족 전체방의 서랍 행은 같다(예전의 "1:1 에서 숨기는 행"은 없어졌다).
- **사진 · 동영상 모음**(`/chat-media`, `screens/ChatMediaScreen.js`, 경로 인자 `roomId`(없으면 가족 전체방)·`peer`(1:1 상대 id). 방 이름은 주소(웹 주소창·기록)에 싣지 않고 화면 안에서 구성원 정보로 계산한다): 탭 "사진 N · 파일 N · 동영상 N"(개수는 서버 `counts`), 사진 탭은 3열 정사각 썸네일 격자(`AuthImage`, 월별 헤더 "2026년 10월"), 끝에 가까워지면 `next_before_id` 커서로 다음 쪽을 자동으로 불러온다(`useChatMedia.js`; 응답을 받아들일지 정하는 상태 전이는 순수 함수 `mediaState.js` 에 있어, 탭·방이 바뀌면 옛 응답은 버려지고 다음 쪽 실패 뒤에도 목록은 남은 채 "다시 시도"할 수 있다). `thumb_url`·`width`·`height`·`size_bytes` 는 서버 스키마상 null 일 수 있어 썸네일은 `thumb_url ?? url` 로 대신한다. `before_id` 는 1 이상일 때만 보낸다. 로딩·오류("다시 시도"; 다음 쪽 오류는 목록 끝에서 다시 시도)·빈 상태("아직 공유된 사진이 없어요")를 처리한다. 파일·동영상 탭은 같은 경로로 불러오고(서버가 빈 목록을 준다) 빈 상태 문구만 "아직 파일은 보낼 수 없어요. 사진부터 모아 둘게요"처럼 다르다.
- **전체 화면 보기·저장**(`components/MediaViewer.js`): 원본, 닫기, 보낸 사람(별명 우선)·날짜·시각, "저장" 버튼(저장 중·결과 문구는 사진별로 기억해서 다른 사진으로 넘어가면 새 사진에는 보이지 않는다). **웹**은 `api.downloadPhoto` 가 로그인 헤더로 받은 blob 을 a 태그 `download` 로 내려받는다(파일명 `gabee-YYYYMMDD-HHmmss-<id>.jpg`, 서버가 준 사진 경로만 받는다). **네이티브(iOS/Android)**는 사진 앱에 저장한다(`savePhoto.js` 의 `savePhotoNative`): ① `photoDownloadRequest`(api.js)가 서버가 준 사진 경로만 받아 주소와 로그인 헤더를 만든다(토큰은 주소에 없다, 낯선 주소는 권한 요청 전에 거절) ② `expo-media-library` **쓰기 전용 권한**(`getPermissionsAsync(true)` → 거절이면 `requestPermissionsAsync(true)`)을 확인한다. 거절·영구 거절이면 "사진 저장 권한이 필요해요. 설정에서 허용해 주세요" ③ `expo-file-system` 새 객체형 API(`File.downloadFileAsync(url, new File(Paths.cache, ...), { headers })`)로 앱 캐시 폴더의 임시 파일에 받는다 ④ `MediaLibrary.saveToLibraryAsync` 로 저장 ⑤ 임시 파일은 성공·실패 모두 `finally` 에서 지운다. 앨범("가비")은 만들지 않는다: `createAlbumAsync` 는 라이브러리 읽기 권한까지 요구해 권한 범위가 커지고, 쓰기 전용 권한이면 충분하기 때문이다. 모듈이 없거나 권한 API 가 실패하는 환경(Expo Go 의 미디어 라이브러리 제한 등)은 "이 환경에서는 저장할 수 없어요" 로 안내하고 앱은 멈추지 않는다. expo 모듈은 웹 번들에 섞이지 않도록 네이티브 분기 안에서 동적 import 한다. 시험은 의존성 주입 가짜 객체로 권한 허용·거절·영구 거절, 받기·저장 실패, 임시 파일 삭제, 낯선 경로, 모듈 없음, 웹 분기를 본다. 임시 파일 이름은 작업마다 시각+난수로 달라서 같은 사진을 동시에 저장해도 서로의 파일을 덮어쓰거나 지우지 않고, 화면은 저장 중인 사진 id 를 모두 기억해 같은 사진의 동시 재저장을 막는다. 인증 헤더는 권한을 받은 뒤 다운로드 직전에 만든다(경로 검증은 권한 창보다 먼저). **의존성**: `expo-file-system ~19.0.24`(SDK 54 호환, 사용자 승인으로 추가)와 `expo-media-library ~18.2.1`(앱 권한 문구는 app.json). **Expo Go 제한 가능성**: expo-media-library 가 "Expo Go 는 Android 권한 정책 때문에 미디어 라이브러리 전체 접근을 제공하지 못한다" 고 경고하므로 Expo Go 에서는 저장이 막힐 수 있다(막히면 위 안내 문구) — **개발 빌드(expo-dev-client)에서 확인을 권장한다.** **실기기(iOS·Android, 개발 빌드와 Expo Go)에서의 저장·권한 창은 아직 확인하지 못했다.**
- **서버 계약(별도 PR)**: `GET /family-chat/media?room_id=<선택>&kind=image|file|video|all&limit=<1~100, 기본 40>&before_id=<선택>` → `{items:[{attachment_id, message_id, kind, user_id, user_name, created_at, url, thumb_url, width, height, size_bytes}], next_before_id, counts:{image, file, video}}`. 오류 404(권한 없는 방)·429(분당 60회)·401. 앱 래퍼는 `api.listMedia`. 서버 PR 이 병합되기 전에는 모음 화면이 오류("사진을 불러오지 못했어요" 등)로 보인다.
- 시험: `apps/mobile/tests/chatmedia.test.js`(월 그룹핑 경계·격자 줄·이어 붙이기·counts·빈 상태/오류 문구·캡션·저장 파일명, 서랍 행 구성(새 구성·제거한 행이 없는지·준비 중·나가기 문구), `listMedia` 경로·쿼리·커서·오류, `savePhoto` 분기). 실기기·웹 화면, 애니메이션, 서버 연동, 웹 내려받기는 아직 직접 확인하지 못했다.

### 고정 메시지 (앱)

- **규칙(사용자 확정)**: 방 안 모든 구성원이 고정·해제할 수 있고, 방당 최대 2개다(3번째를 고정하면 가장 오래된 것이 자동 해제 — 앱이 "가장 오래된 고정이 해제됐어요"를 알린다). 텍스트 메시지만 고정한다(사진이 있거나 글이 없는 메시지, 전송 중·실패 메시지에는 고정 메뉴가 없다). 가족 전체방과 1:1 방 모두 같다.
- **길게 누르기 메뉴**(`components/MessageActionSheet.js`, 이전에는 일반 메시지에 길게 누르기 동작이 없었다): 서버에 저장된 텍스트 메시지의 말풍선을 길게 누르면 아래에서 작은 메뉴(React Native `Modal`, 웹에서도 같다)가 열린다 — "복사"(`expo-clipboard`), "공지로 고정" 또는 이미 고정된 메시지면 "고정 해제", "닫기". 이 메시지 말풍선은 네이티브에서 글자 선택을 끄고(`selectable` prop 과 스타일 `userSelect` 를 함께 — 스타일이 prop 을 이기므로, 판단은 `pinUtils.bubbleSelectable`) 복사를 메뉴로 옮겼다. 복사 결과는 "복사했어요"/"복사하지 못했어요"로 알리고, 말풍선에는 접근성 동작 "메뉴 열기"가 있다. 메뉴 아래 여백은 안전 영역 inset(없으면 플랫폼 기본값)을 따른다. 웹은 선택을 그대로 둔다. 전송 실패 메시지의 길게 누르기(삭제)는 그대로다.
- **고정 바**(`components/PinnedBar.js`): 헤더 아래에 최근 고정을 한 줄씩(핀 아이콘, 보낸 사람 이름, 본문 한 줄 말줄임). 고정이 없으면 그리지 않는다. 기본 펼침이고 오른쪽 화살표로 접으면 가장 최근 1개만 보인다(고정이 2개일 때만 화살표). 펼친 상태에서는 줄 아래에 "엄마 고정 · 10월 24일 오후 3:20" 보조 줄이 있고, 접근성 라벨에도 보낸 사람·고정한 사람·시각이 들어간다. 줄을 누르면, 라이브 상태이고 그 메시지가 이미 목록에 있으면 그 자리로 스크롤+잠깐 강조만 하고(`pinTapAction`), 목록에 없거나 과거 창을 보는 중이면 기존 `focusOn(messageId)`(그 위치 창 불러오기)를 쓴다. 과거(포커스) 모드에서도 유지되고, 검색 바가 열려 있는 동안은 숨는다. 고정·해제 결과 안내(3.5초)도 이 바 아래에 나온다.
- **서랍의 "고정 메시지" 행**: 동작 행(부제 "중요 공지와 약속 모아보기"). 누르면 서랍을 닫고 고정 바를 펼친다(고정이 없으면 안내만). 별도 목록 시트를 만들지 않고 고정 바를 재사용하는 쪽이 단순해서 골랐다 — 고정은 방당 최대 2개라 바에서 해제 메뉴(말풍선 길게 누르기)까지 모두 닿는다. 해제 버튼이 있는 전용 시트는 없다(해제는 그 메시지를 길게 눌러서 한다. 고정 바 줄로 이동 → 길게 누르기).
- **데이터 갱신**(`useChatPins.js`, 순수 규칙은 `pinUtils.js`): 방에 들어오면 불러오고, 고정·해제는 먼저 화면에 반영(낙관적)한 뒤 실패하면 그 동작만 거꾸로 적용해 되돌리고(고정 실패는 그 항목을 빼고 교체로 빠진 항목 복원, 해제 실패는 그 항목만 복원 — 겹친 요청이 서로 덮어쓰지 않는다) 문구를 둔다. 새 고정은 기기 시계와 무관하게 항상 맨 앞에 둔다. 같은 메시지를 처리 중에 또 누르면 "처리 중이에요"를 알린다(해제 중 404 는 "이미 해제된 고정이에요"로 목록에서 뺀 채 둔다). 요청이 끝나면 서버 기준으로 한 번 더 맞추고(조회 중이면 끝난 뒤 한 번 더), 안내는 iOS 에서 `announceForAccessibility` 로도 읽어 준다. 다른 구성원의 변경은 별도 타이머로 30초마다 조용히 다시 조회해 반영한다(화면이 보이고 앱이 앞에 있을 때만, 연속 실패마다 간격을 두 배로 늘려 최대 2분, 언마운트·백그라운드에서 정리). 메시지 폴링(3초)에 얹지 않은 이유는 그 훅이 과거 모드에서 폴링을 멈추는데 고정 바는 과거 모드에서도 유지돼야 해서다. 조회는 순번(seq)을 달아 내가 그 뒤에 바꾼 것이 있거나 바꾸는 중이면 오래된 응답을 버린다.
- **서버 계약(별도 PR, 미병합)**: `GET /family-chat/pins?room_id=<선택>` → `{items:[{message_id, text, text_truncated, user_id, user_name, created_at, pinned_by, pinned_by_name, pinned_at}]}`(최근 고정 최대 2개, 최신순, 본문은 앞 200자) / `POST /family-chat/pins {room_id?, message_id}` → `{item, replaced_message_id|null, already_pinned}` / `DELETE /family-chat/pins/{message_id}?room_id=` → 204. 오류: 400 `invalid_message`(그 방의 메시지 아님)·`not_pinnable`(사진이 있거나 빈 글), 404, 429(쓰기 분당 30회). 앱 래퍼는 `api.listPins`·`pinMessage`·`unpinMessage`, 오류 문구는 `chatUtils.pinErrorMessage`.
- 시험: `apps/mobile/tests/chatpins.test.js`(고정 가능 판정, 목록 정리·최대 2개, 낙관적 고정/해제·되돌리기·오래된 응답 버림 reducer, replaced_message_id 처리, 안내·오류 문구, 접기 보기, 폴링 간격, API 경로·메서드·본문, 서랍 행). 실기기·웹 화면(길게 누르기가 웹에서 글자 드래그 선택과 부딪치는지 포함), 메뉴·고정 바 모양, 서버 연동은 아직 직접 확인하지 못했다.

### 메시지-일정 연결 (앱)

- **동작**: AI 대화 도우미에서 일정 후보("일정으로 등록")나 할 일 후보("할 일로 등록")를 사용자가 눌러 **등록에 성공하면**, 후보의 `source_message_ids` **첫 번째 메시지**와 등록된 일정/할 일의 연결을 서버에 저장한다(`POST /family-chat/links`, `kind` event/todo, `target_id` 는 등록 응답의 id, 제목·날짜·시간은 후보값). 사용자 확인 없이 자동 등록되는 일은 없다(기존 구조 그대로). `source_message_ids` 가 비어 있거나 등록 응답에 id 가 없으면 연결을 생략한다. 연결 저장은 부가 기능이라 **실패해도 등록은 성공으로 두고** 안내 없이 미리 그린 항목만 뺀다(등록 흐름을 막지 않는다). 등록 함수는 어떤 경우에도 던지지 않고 진행 중 카운터를 반드시 되돌린다(`linkUtils.runGuarded`). 변환 규칙은 `linkUtils.linkInputFromCandidate`(날짜·시간은 올바른 형식만, 할 일은 `due` 를 날짜로, 제목은 공백 정리 후 120 글자(코드포인트 단위)).
- **말풍선 표시**: 연결된 메시지에는 글 아래에 작은 칩 "일정으로 등록됨"/"할 일로 등록됨"(종류마다 하나)이 붙는다. 표시만 하고 눌러도 동작은 없다(접근성 라벨은 같은 문구). `MessageBubble` 에는 `linkBadges` prop 만 추가했다.
- **서랍 "가족 일정 · 할 일" 행은 없앴다(가족 할 일로 통합, release/1.1)**: 하단 시트(`LinksSheet.js`)와 서랍 연결(`onOpenLinks`·`onClosed`)을 지웠다. 대화에서 등록한 **할 일**은 원래 공동 할 일에 만들어지므로 가족 할 일 화면에서 보고, 그 화면의 할 일 줄 오른쪽에 "원본" 버튼(대화에서 만든 할 일에만, `useTodoOrigins.js` 가 가족방 연결 목록의 할 일 종류로 할 일 id → 메시지 id 를 만들고 `TodoRow` 가 보인다)을 눌러 원본 메시지 위치의 채팅방으로 이동한다(`/chat-room?focus=`). **일정**은 일정 탭에서 보고, 대화 말풍선의 "일정으로 등록됨" 표시는 그대로다(대화에서 등록한 일정의 원본 이동 목록은 사라졌다). 연결 데이터·말풍선 표시·`useChatLinks` 는 그대로 쓴다. `linkUtils.js` 의 시트용 도우미(`filterByKind`, `formatLinkWhen`, `linkSourceLine` 등)는 지금 화면에서 쓰지 않지만 시험이 남아 있어 두었다.
- **데이터 갱신**(`useChatLinks.js`, 순수 규칙은 `linkUtils.js` — `useChatPins` 와 같은 방식): 방에 들어오면 최근 100개를 불러오고, 화면이 보이고 앱이 앞에 있을 때 30초마다(연속 실패 시 두 배, 최대 2분) 조용히 다시 조회한다. 등록은 먼저 임시 항목으로 그리고 서버 응답으로 바꾸며, 실패하면 그 임시 항목만 뺀다. 삭제는 먼저 뺀 뒤 실패하면 그 항목만 되살리고 문구를 보인다(404 는 이미 없는 것이라 뺀 채 둔다). 요청 중에는 오래된 조회 응답을 버리고(seq), 같은 연결 요청은 한 번만 보낸다. **1:1 방은 연결을 만드는 경로가 없어(AI 도우미가 가족방에만 있다) 30초 반복 조회를 하지 않고, 들어갈 때만 조회한다**(예전에는 시트를 열 때도 조회했지만 시트가 없어졌다)(`poll: false`; 가장 단순한 쪽을 골랐다). 서랍에서 시트를 여는 시점은 서랍 닫힘 애니메이션이 끝났을 때(`RoomDrawer` 의 `onClosed`)이고, 한 번만 열며(`takeFlag`) 콜백이 오지 않으면 600ms 뒤 폴백으로 연다. 임시 항목은 지울 수 없다.
- **서버 계약(별도 PR, 앱은 이 형태를 기준으로 만들었다)**: `POST /family-chat/links {room_id?, message_id, kind, target_id, title(1~120), date?, time?}` → 201(새로) 또는 200(이미 있음, 멱등) `LinkOut`. `GET /family-chat/links?room_id=&kind=&limit=`(1~100, 기본 50) → `{items:[LinkOut]}` 최신순. `DELETE /family-chat/links/{link_id}?room_id=` → 204, 만든 사람만(다른 구성원 403 `forbidden`, 없으면 404). `LinkOut = {id, room_id, message_id, kind, target_id, title, date, time, created_by, created_by_name, created_at, message_text(원본 앞 100자), message_user_name}`. 오류: 400 `invalid_message`·`invalid_target`·`too_many_links`, 404, 422, 429(분당 30). 앱 래퍼는 `api.listLinks`·`createLink`·`deleteLink`, 오류 문구는 `chatUtils.linkErrorMessage`.
- **일정 화면 연결**: 일정 화면(팀원 담당)에서 "원본 대화로 이동"을 보여 주는 일은 이 작업에 넣지 않았다. 팀원과 합의한 뒤 별도로 한다.
- 시험: `apps/mobile/tests/chatlinks.test.js`(후보→연결 본문 변환·생략, 목록 정리·필터, 낙관적 추가·확정·되돌림·겹친 요청·오래된 응답, 메시지별 맵·말풍선 표시, 삭제 권한, 날짜·시간·원본 줄, 이동 판단, 오류 문구, API 경로·메서드·본문·쿼리, 서랍 행). **확인 못한 것**: 실기기·웹 화면(칩·시트 모양, 서랍 닫힘 뒤 시트가 iOS 에서 정말 한 번에 열리는지), 서버 연동(서버 PR 병합 전이라 `/family-chat/links` 는 실제로 호출해 보지 못했다), 서버 `LinkOut` 필드는 병렬 작업 폴더의 `link_schemas.py`·`link_router.py` 와 읽어서 대조했고 일치했다(서버 쪽 `invalid_target` 은 지금 할 일만 확인하고, 409 `link_changed`·422 `invalid_title` 은 앱이 따로 문구를 두지 않고 일반 오류 문구를 쓴다), 후보의 `source_message_ids` 가 항상 이 방의 텍스트 메시지를 가리키는지.

### 대화 검색 (돋보기, 앱)

> 소통 탭 목록 상단: 돋보기 버튼을 없애고 검색창만 항상 보인다. 오른쪽 위 "새 대화" 버튼은 제목 줄 높이에 따라 내려가지 않도록 절대 위치로 고정해(오른쪽 끝 6, 세로 가운데 28) 다른 탭과 같은 자리에 둔다. 채팅방 안 검색의 돋보기는 그대로다.

서버 계약은 **별도 PR** 의 `GET /family-chat/search`(`q`·`room_id`·`limit`·`before_id`, 응답 `{items, next_before_id}`)와 `GET /family-chat/messages?around_id=`(그 메시지를 가운데로 앞뒤 창)다. 이 브랜치에는 서버가 없어 가짜 fetch 로만 시험했다. **키워드(글자 일치) 전용**이며 임베딩·AI 를 쓰지 않는다. 검색어·결과 글자는 요청 주소 외에는 로그·저장소·오류 문구 어디에도 남기지 않는다.

- **채팅방 안 검색**(`ChatRoomScreen`, 카톡 방식): 상단 바의 돋보기(접근성 라벨 "대화 검색")를 누르면 상단이 검색 바(`ChatSearchBar`)로 바뀌고, **결과 목록 화면은 없다**(대화 화면이 그대로 보인다). 검색어가 있으면 검색 바 아래 줄에 안내 문구와 현재 위치 `n/m`(서버가 20개씩 주므로 더 있으면 `1/20+`), 더 오래된 일치(▲)·더 최근 일치(▼) 버튼이 보이고 키보드의 검색 키는 ▲ 와 같다. 검색이 끝나면 가장 최근 일치로 바로 이동하고(`useChatSearch` 의 `current`, 이동은 고정 바와 같은 `pickPin`: 이미 목록에 있으면 스크롤, 아니면 그 위치 창), ▲▼ 는 `stepSearchIndex` 로 한 칸씩 옮기며 ▲ 가 끝에 닿았는데 서버에 더 있으면 다음 쪽을 받아 이어 간다. 말풍선(`MessageBubble`) 안 검색어는 옅은 꿀색 바탕+굵게, 지금 가리키는 일치 메시지는 줄 배경과 검색어가 더 진하게(`Highlighted` 의 `highlightNodes`) 보인다. 결과 없음("일치하는 대화가 없어요")·오류(429 "너무 자주 검색", 422 검색어 길이, 다시 시도)·검색 중·방 정보 대기는 같은 줄의 안내 문구로 나온다. 검색 바를 닫으면 보던 위치에 그대로 있고 강조만 사라진다. 입력은 300ms 쉬었다가 한 번 부르고(`useChatSearch`), 공백만이면 부르지 않으며, 같은 검색어는 다시 부르지 않고, 더 새 요청이 시작되면 오래된 응답은 버린다. 앱 화면은 아직 실기기에서 직접 확인하지 못했다.
- **소통 탭 검색**(`FamilyChatScreen`, `ChatListHeader`): 제목 아래에 **항상 보이는 검색창**(돋보기 버튼과 열고 닫는 토글은 없앴다, 2026-11)에 글자를 넣으면 방 이름 일치 행 아래에 "대화 내용" 섹션(`ContentSearchSection`)이 나온다. 모든 방(가족 전체방 + 내 1:1)에서 찾고, 각 결과에 방 이름(가족 전체방은 가족 이름, 1:1 은 상대 표시 이름, 모르면 "대화")을 붙인다. 결과를 누르면 `/chat-room` 으로 가며(가족 전체방은 `focus` 만, 1:1 은 `roomId`·`peer`·`focus`) 그 메시지 위치로 열린다. `src/app/chat-room.js` 의 화면 key 가 `방:focus` 라 같은 방이라도 focus 가 다르면 새로 열린다.
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
| `PUT /family-chat/ai/settings` | `{enabled: bool}` | `AiSettingsOut` | **가족 구성원 누구나** AI 기능을 켜고 끈다(회원가입 때 AI 동의를 하므로, 2026-10-29 변경. 예전에는 소유자·관리자만 `403 not_manager`). `can_manage` 는 앱 호환을 위해 남겼고 구성원이면 항상 true 다. AI 를 부르지 않는다 |
| `POST /family-chat/ai/preview` | `RangeIn` | `PreviewOut` | Claude 가 **실제로 받게 될 가명화된 대화**를 미리 보여 준다. **AI 를 부르지 않고** 하루·쿨다운 한도도 쓰지 않으며, 가족 AI 동의와 무관하게 볼 수 있다(`ai_enabled` 로 동의 여부를 알림). 사용자당 분당 20회, 넘으면 429 `too_many_previews` |
| `POST /family-chat/ai/analysis` | `RangeIn` | `AnalysisOut` | 통합 분석: 요약·중요 메시지·일정 후보·할 일 후보·**답장 추천·대화 주제 추천**을 AI 한 번 호출로 |
| `POST /family-chat/ai/replies` | `RangeIn` | `RepliesOut` | 마지막 메시지에 이어 보낼 답장 후보(3개). 앱은 더 이상 부르지 않는다(분석에 합쳐짐, 하위 호환으로 남김) |
| `POST /family-chat/ai/topics` | `RangeIn` | `TopicsOut` | 이어갈 대화 주제 추천(3~5개). 위와 같이 앱은 부르지 않는다 |

- `RangeIn`: `limit`(기본 100, 1~200), `after_id`(기본 0). `after_id` 뒤의 최근 `limit` 개를 쓴다. 분석은 최대 200개, 따로 부르는 답장은 최대 15개, 주제는 최대 30개까지 본다.
- `AnalysisOut`: `summary`, `important_messages[{message_id, reason}]`, `schedule_candidates[{title, date, time, place, source_message_ids}]`, `todo_candidates[{title, assignee_name, due, source_message_ids}]`, **`replies[]`(0~3개, 각 80자 이내), `topics[]`(0~5개, 각 40자 이내)**, `meta`. `replies`·`topics` 는 추가 필드(기본값 빈 목록)라 하위 호환이 깨지지 않는다.
- **답장·주제 정리**: 글자가 아닌 값·빈 값은 버리고 길이·개수 상한을 지키며, 이 요청이 만들지 않은 위조·변형 토큰이 든 항목은 버린다. 둘 다 비어 있어도 분석은 실패하지 않는다(요약이 비면 기존처럼 실패). 분석의 AI 출력 상한은 3000토큰(`ANALYSIS_MAX_TOKENS`)이다(답장·주제까지 만들어 기본 2048보다 넉넉하게, 잘리면 전체가 실패하므로). `PROMPT_VERSION` 을 v4 로 올려 이전 캐시는 쓰이지 않는다.
- `RepliesOut`: `replies[]`, `meta`. `TopicsOut`: `topics[]`, `meta`.
- `meta`(`AiMeta`): `cached`, `api_calls`(0 또는 1), `input_tokens`, `output_tokens`, `model`, `message_count`, `from_message_id`, `to_message_id`, `generated_at`, `privacy`(선택, `{masked: {종류: 개수}, blocked_messages: 개수}` — 글자·값 없이 개수만, 캐시 적중에도 같은 값).
- `PreviewOut`: `message_count`, `masked{종류: 개수}`, `blocked_messages`, `lines[{id, speaker, text, blocked}]`, `ai_enabled`, `sendable`(차단되지 않은 메시지가 3개 이상이라 AI 에 보낼 수 있는지. False 면 분석·답장·주제가 400 `too_few_messages` 이므로 앱은 요청 버튼을 막고 "민감정보가 있어 제외된 메시지가 많아요" 같은 안내를 보인다). `lines` 는 분석 요청이 Claude 로 보내는 줄과 같은 가명화된 줄(토큰 상태, 예: `[PERSON_1]`·`[PHONE_1]`, 차단된 메시지는 `[민감정보가 있어 제외된 메시지]`)이다. 원문 개인정보와 토큰 대응표는 담지 않는다. 앱은 이 미리보기를 더 부르지 않는다(분석 한 번이 같은 기본 범위를 가명화해 보낸다. 따로 부르는 `/replies`(최근 15개)·`/topics`(최근 30개)는 같은 규칙을 더 짧은 범위에 적용하므로 토큰 번호가 다를 수 있다).

**개인정보 가명화 (`app/shared/privacy`, 분석·답장·주제 공통)**

- 서버가 DB 에서 읽은 대화를 Claude 로 보내기 전에 가명화한다(앱은 대화 글자를 보내지 않는 기존 구조 그대로). 전화·이메일·주소·이름은 `[PHONE_1]`·`[EMAIL_1]`·`[ADDR_1]`·`[PERSON_1]` 토큰으로, 주민번호·카드·계좌·비밀번호가 든 메시지는 통째로 자리표시로 바꿔 보낸다. 이름 사전은 그 가족 구성원의 실제 이름·표시 이름이다. 종단간 암호화(E2EE)가 아니며 서버는 원문을 읽는다. 탐지는 규칙 기반이라 놓칠 수 있다(`docs/security/PRIVACY_PIPELINE_MODULE.md`).
- 한 사람의 실제 이름과 표시 이름(`group_members.display_name`)은 같은 토큰으로 묶는다(대표 이름은 실제 이름). 차단된 줄은 시각을 비워 보낸다(발화자 토큰은 간다). 차단되지 않은 메시지가 3개 미만이면 AI 를 부르지 않고 400 `too_few_messages`(미리보기는 `sendable: false`). 담당자는 복원 뒤에도 이 가족 구성원의 이름·표시 이름과 일치할 때만 남기고 아니면 null(후보는 유지). 응답에 남은 `‹PERSON_2›`·`[RRN]` 같은 토큰 모양은 `(알 수 없는 항목)`·`(민감 정보)` 로 바꾼다. 글자 수 한도는 재가명화 뒤에도 다시 확인한다(최대 5회 더 줄임).
- 프롬프트는 토큰을 풀어쓰지 말고 글자 그대로 복사하라고 지시한다(`PROMPT_VERSION` v3).
- **캐시에는 토큰 상태의 결과**를 저장한다(DB 의 `ai_result_cache` 에 실제 이름·전화·이메일·주소가 남지 않는다). 응답할 때마다(캐시 적중 포함) 같은 대화 범위를 다시 가명화해 같은 대응표를 만들고(같은 입력이면 같은 토큰 번호) 복원한다. 대응표는 요청 메모리에만 있고 DB·캐시·로그·응답에 넣지 않는다.
- 복원 범위는 정책(`restore_kinds`)을 따른다. 분석: 이름·주소만 복원(담당자 연결, 일정 장소), 전화·이메일 토큰은 `(연락처)`·`(이메일)`. 답장·주제: 이름만 복원, 나머지는 `(연락처)`·`(주소)` 등 일반화. **분석 응답의 `replies`·`topics` 도 같은 규칙**이다: 한 번의 분석 호출로 받지만 복원은 필드마다 달라서, 같은 응답 안에서 일정 장소는 주소가 복원되고 답장·주제 문장의 주소 토큰은 `(주소)` 가 된다(`_restore(..., policy=REPLY)`, 답장·주제는 입력창에 넣어 보내는 문장이라 주소 원문이 되살아나지 않게 한다. 시험 `test_analysis_restores_address_in_the_schedule_but_not_in_replies_and_topics`).
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
- **AI 어시스턴트 진입점도 같은 가드를 쓴다**: `POST /ai-assistant/chat`(기능 `assistant_chat`), `POST /ai-assistant/knowledge/ask`(`knowledge_ask`). 대화형이라 결과 캐시는 쓰지 않는다(`cache_key=None`, 대화 원문을 남기지 않는다). 도구 루프로 한 요청이 Anthropic 을 여러 번(최대 4) 부르면 실제 호출 수를 사용 기록과 하루 한도에 센다. 어시스턴트 두 기능은 이 문서의 기본 한도(10/30/30초)가 아니라 **따로 센다**(묶음 `assistant`: 사용자 100회/일, 가족 300회/일, 쿨다운 없음, `docs/features/ai_assistant-upload-chat.md`)(`ai_guard.run` 이 응답의 `calls` 를 읽는다). 키가 없으면 외부 호출 없이 검색 결과만 돌려주므로 가드를 거치지 않는다.

### 호출 횟수 (동작별 AI 호출 수)

| 동작 | AI 호출 수 | 상태 |
|---|---|---|
| 일반 채팅 메시지 전송 (`POST /family-chat/messages`) | **0** | 구현됨 |
| 설정 조회·변경 (`GET`/`PUT /ai/settings`) | 0 | 구현됨 |
| 대화 분석 (`POST /ai/analysis`, 답장·주제 추천 포함) | 최대 **1**, 캐시 적중이면 **0** (이전에는 분석·답장·주제로 최대 3번) | 구현됨 |
| 보낼 내용 미리보기 (`POST /ai/preview`) | **0** (한도·동의와 무관, 분당 20회) | 구현됨 |
| 답장 추천 (`POST /ai/replies`) | **1**, 캐시 적중이면 0 | 구현됨(앱은 안 씀, 분석에 합쳐짐) |
| 주제 추천 (`POST /ai/topics`) | **1**, 캐시 적중이면 0 | 구현됨(앱은 안 씀, 분석에 합쳐짐) |
| @가비 키워드 검색 | **0** (PostgreSQL 키워드 검색 우선, 필요할 때만 pgvector) | 예정 |
| 원본 문서 확인·공유 | **0** | 예정 |
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

- 모든 상태를 PostgreSQL 에 둬서 여러 워커에서도 한도·캐시·동시 실행이 일관된다. **Redis 는 쓰지 않는다**(이유는 ADR 0011).
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

## 별명을 모든 탭에 반영 (앱 공통)

내가 구성원에게 붙인 별명(서버 `GET /family-group/groups/me/nicknames`, 보는 사람 본인에게만 적용)을 소통·일정·가계·돌봄 화면의 이름에 쓴다. 우선순위는 별명 > (일정 탭만) 관계 이름(엄마·아빠) > 가족에서 쓰는 표시 이름 > 계정 이름이고, 나 자신은 그대로다.
- 공통 모듈 `apps/mobile/src/shared/members/nicknames.js`: `getGroupWithNicknames()` 가 가족 그룹과 별명 목록을 함께 불러 별명이 있는 구성원의 `display_name` 을 별명으로 바꾸고 `nickname` 에도 넣는다(`display_name || name` 으로 읽던 화면이 고치지 않고 별명을 보여 준다). 별명 조회가 실패하면 원래 이름으로 보인다. 서버·DB 변경은 없다.
- 소통 `getRoomInfo()`, 가계 `getMembers()`, 일정 가족 이름표(`buildFamily`, 화면이 다시 보일 때 `refreshItems` 가 이름표도 새로 만든다), 돌봄 `getLatestLocations()` 가 이 모듈을 쓴다. 채팅 말풍선 이름은 `MessageBubble` 의 `nameOf` 로 바꾼다. 가계 `getMembers()` 는 화면이 그리는 `name` 을 별명으로 바꿔 준다. 연락처 화면과 AI 할 일 등록(AI 가 준 담당자 이름 매칭)은 실명이 필요해 `getRoomInfo({ raw: true })` 를 쓴다. 연락처 화면만 실명을 부제로 보이므로 `getRoomInfo({ raw: true })` 로 서버 값을 그대로 받는다.
- 시험: `apps/mobile/tests/nicknames.test.js`.
- **아직 못 한 것(후속)**: 서버가 이름을 글자로만 내려 주는 곳(정산 내역 낸 사람·정산 이동, 용돈 기록자·결정자, 돌봄 기록자·식단 기록자, 링크 만든 사람, 대화 검색 결과의 보낸 사람, 사진 보관함 접근성 문구)과 AI 답변·알림 문구는 별명이 반영되지 않는다. 서버가 "보는 사람 기준 이름"으로 내려 주도록 바꿔야 한다. 실기기 확인은 못 했다.

## 메시지 삭제 (서버, release/1.1)
- `DELETE /family-chat/messages/{message_id}?room_id=` → 200 `MessageOut`(`deleted: true`, `text: ""`, `attachment: null`). 코드는 `delete_service.py`(라우터 → 서비스 → `repository.soft_delete`).
- 규칙: 방에 들어갈 수 없거나 이 방의 메시지가 아니면 404(존재 여부를 숨김), 내가 보낸 것이 아니면(가비의 답 포함) 403 `forbidden`, 이미 지운 메시지는 그대로 200(멱등).
- 소프트 삭제: `messages.deleted_at` 을 기록하고 `text` 를 비운다. 행을 남겨 읽음 위치·메시지 순서가 바뀌지 않는다. 사진 메시지는 **원본·썸네일 파일을 먼저 지운 뒤** DB(`deleted_at`, 첨부 행 삭제)를 저장한다. 파일을 지우다 실패하면 DB 는 그대로이고 500 `delete_failed` 로 답하므로 다시 눌러 지울 수 있다(DB 가 먼저면 첨부 행이 사라져 남은 파일의 경로를 찾을 수 없다). 경고 로그에 경로·내용은 남기지 않는다.
- **삭제를 열어 둔 화면에 알리기**: 앱은 처음에만 `latest` 로 받고 이후 `after_id` 로 새 메시지만 조회하므로 이미 받은 메시지가 지워졌음은 폴링으로 알 수 없다. `GET /family-chat/messages/deleted?since=<ISO 시각>&room_id=` → `{message_ids, server_time}`(since 이후 지워진 이 방의 메시지 id, 지운 순서, 최대 200개). 앱은 응답의 `server_time` 을 다음 조회의 `since` 로 쓴다(서버 시계라 기기 시계가 어긋나도 놓치지 않는다). 방 접근 규칙은 메시지 조회와 같다. 앱 연결은 후속 작업이다. **사진은 `Cache-Control: private, max-age=31536000, immutable` 로 받으므로, 앱은 삭제된 메시지의 사진 캐시도 지워야 한다.**
- 조회: 메시지 목록·방 목록의 마지막 메시지에는 삭제된 메시지가 `deleted: true` 로 나온다. AI 분석(`ai_repository.recent_messages`)과 대화 검색에서는 제외한다. 사진 모음에서는 첨부 행이 없어져 빠진다. 고정 메시지·연결 목록은 본문을 `messages` 와 join 해서 읽으므로 삭제된 메시지는 빈 글자로 나온다(내용은 새지 않지만 앱이 빈 공지와 구분할 `deleted` 표시가 없고, 고정 2자리 중 하나를 차지한다). 게시판 작업에서 해결하며, **게시판이 본문 사본을 저장하게 되면 메시지를 지울 때 그 사본도 함께 지워야 한다.** 연결(`chat_message_links`)의 `title` 등은 사용자가 확인한 일정·할 일 제목의 사본이라 삭제 뒤에도 남는다(의도).
- 시험: `tests/test_message_delete.py`(작성자만, 멱등, 다른 가족·1:1 방 격리, 가비의 답, 검색·AI 제외(`deleted_at` 필터 자체), 사진 파일 삭제와 삭제 실패 후 재시도, 삭제 알림 조회, 1:1 방 사진, around·읽음 위치).
- 안 읽은 수: 삭제된 메시지도 읽기 전까지는 안 읽은 수에 센다(열어 보면 "삭제된 메시지입니다"가 보이는 것과 같은 기준, 행을 남기므로 읽음 위치·기준선은 바뀌지 않는다).
- 한계: 삭제 요청에는 호출 한도가 없다(고정·연결에는 분당 30회 한도가 있음). AI 분석 결과 캐시에는 지우기 전 대화로 만든 요약이 만료(약 10분)까지 남을 수 있다(캐시 키가 대화 내용에 따라 달라져 삭제 뒤에는 옛 결과가 다시 쓰이지 않는다).
- 앱 화면(팝업 메뉴의 삭제, "삭제된 메시지입니다" 표시)은 아직 없다.

## 메시지 답장 (서버, release/1.1)
- `POST /family-chat/messages` 에 선택 필드 `reply_to_id`(1 이상 정수) 추가. 서비스(`service.post`)가 같은 방의 메시지인지(`repo.get_in_room`) 확인한다: 없는 id·다른 방·다른 가족의 메시지는 400 `invalid_message`(존재 여부를 숨김), 지운 메시지는 400 `reply_deleted`. 1:1 방의 제3자는 방 접근에서 404.
- DB: `messages.reply_to_id`(nullable, 자기 참조 외래키, 리비전 `432e249f600c`, expand). 기존 메시지는 모두 null. 소프트 삭제라 원본 행은 지워지지 않아 연결이 유지된다.
- 응답: `MessageOut.reply_to`(`ReplyOut`: `id`, `user_name`, `text` 40자까지, `deleted`, `has_attachment`). 원본이 지워졌으면 `deleted: true`, `text: ""`. 사진 원본은 `text: ""`, `has_attachment: true`(원본을 지우면 false). 지운 답장 메시지는 `reply_to` 를 붙이지 않고, 지울 때 `reply_to_id` 도 비워 어느 글에 답했는지 남기지 않는다. 목록·around 조회는 원본을 `repo.reply_parents(db, room, messages)` 로 한 번에 모아 붙이므로 메시지 수와 상관없이 쿼리 수가 일정하다. 이 조회에도 **방 조건(`room_messages`)을 걸어**, 답장을 넣을 때의 방 검사가 빠진 잘못된 데이터가 있어도 다른 방 메시지 내용이 미리보기로 새지 않는다. **방 목록의 `last_message` 에는 `reply_to` 가 붙지 않는다(항상 null).** 사진 보내기(`POST /family-chat/photos`)는 아직 답장을 받지 않는다.
- 시험: `tests/test_message_reply.py`(미리보기, 40자 자르기, 사진 원본, 없는 id·다른 가족·다른 방, 1:1 방 제3자, 지운 원본에는 답장 불가, 나중에 지워진 원본 표시, 가비 메시지에 답장, 답장의 답장, 입력 검증, 원본이 페이지 밖인 목록의 쿼리 수, 잘못된 데이터에서도 다른 방 내용이 새지 않음, 지운 답장, before·around 조회, 방 목록 마지막 메시지).
- 한계: 답장 생성과 원본 삭제가 동시에 일어나면 "지운 메시지에 대한 답장" 행이 생길 수 있다(잠금 없음). 목록 표시는 `deleted` 로 처리해 내용은 새지 않는다. 마이그레이션의 외래키 추가는 테이블 전체를 검증하며 잠깐 쓰기를 막는다(가족 앱 규모에서는 문제 없다고 보고 `NOT VALID` 는 쓰지 않았다). `reply_to_id` 에는 인덱스가 없다(원본에 달린 답장을 찾거나 원본을 하드 삭제하는 기능이 생기면 추가).
- 앱 화면은 아직 없다.

## 메시지 반응 (서버, release/1.1)
- `PUT /family-chat/messages/{message_id}/reaction {emoji}?room_id=` → 200 `MessageOut`(내 반응을 정한다: 없으면 만들고, 다른 이모지면 바꾸고, 같은 이모지면 그대로). `DELETE …/reaction?room_id=` → 200 `MessageOut`(내 반응을 지운다, 없어도 같은 결과). 코드는 `reaction_service.py`.
- 규칙: 허용 이모지 6개(❤️ 👍 😂 😮 😢 🙏)만, 아니면 400 `invalid_reaction`(변형 문자 U+FE0F 는 있든 없든 같은 이모지로 보고 허용 표기로 저장, 4글자를 넘는 입력·피부색·텍스트 변형 등은 거절). 방에 들어갈 수 없거나 이 방의 메시지가 아니면 404(존재 여부를 숨김). 지운 메시지에는 400 `message_deleted`. 내 메시지·가비의 답에도 누를 수 있다.
- DB: 새 테이블 `message_reactions`(기본키 `(message_id, user_id)`, 리비전 `8ba852cd9c10`, expand). 내 반응은 한 번의 upsert(`INSERT … ON CONFLICT DO UPDATE`, PostgreSQL·SQLite)로 저장해서, 같은 사람의 취소·다른 이모지 요청이 겹쳐도 오류 없이 마지막 요청대로 된다. 메시지를 지우면(`repo.soft_delete`) 그 메시지의 반응 행도 지운다. 반응을 저장하는 사이에 메시지가 지워졌으면 저장 뒤 메시지를 다시 읽어(`db.refresh`) 남은 반응 행을 치우고 400 `message_deleted` 로 답한다.
- 응답: `MessageOut.reactions: [{emoji, count, mine}]`(많은 순, 같으면 허용 목록 순서). 목록·before·after·around 조회는 `repo.reaction_summary` 한 번의 쿼리로 모아 붙인다(메시지 수와 상관없음). **방 목록의 `last_message` 에는 채우지 않는다(항상 빈 목록).** 지운 메시지는 항상 빈 목록.
- 한계: 누가 눌렀는지는 응답에 없다(사람 수와 내가 눌렀는지만). 반응 요청에는 호출 한도가 없다. 새 반응이 알림함으로 가지 않는다. **이미 받아 둔 메시지의 반응이 바뀐 것을 다른 사람 화면에 알리는 조회는 아직 없다**(앱은 새 메시지만 조회하므로 상대 화면에는 방을 다시 열기 전까지 안 보인다). 더블탭 하트·팝업 반응 앱 작업(6·5번)에서 방식을 정한다(예: 반응 변경 시각 기준 조회, 또는 최근 메시지를 다시 받기). 방 목록 `last_message.reactions` 는 "반응 없음"이 아니라 "채우지 않음"이라, 앱이 이 값으로 메시지 캐시를 덮어쓰면 반응이 사라져 보일 수 있다.
- 배포 주의: `MessageReaction` 이 family_chat 모듈의 모델이라, 공용 DB 에 `message_reactions` 테이블이 없으면 `schema_ready` 가 채팅 전체를 503 으로 막는다(ADR 0006). 공용 DB 통합 때는 코드보다 먼저 이 리비전(`8ba852cd9c10`)을 올려야 한다.
- 시험: `tests/test_message_reactions.py`(내 반응, 사람별 mine·집계 순서, 교체, 멱등, 취소, 허용 목록·변형 문자, 지운 메시지·삭제 시 정리, 다른 가족·1:1 방 제3자·잘못된 방, 가비의 답, before·around, 목록 쿼리 1번, 방 목록).
- 앱 화면은 아직 없다.

## 게시판(고정 메시지) 개선 (서버, release/1.1)
- **본문 사본**: 공지로 올릴 때 게시판에 보이는 범위(앞 200자 + 잘렸는지 알아볼 1자)의 본문을 `chat_pinned_messages.text` 에 복사해 저장한다(`pin_service.pin`, 지운 긴 메시지의 나머지는 남기지 않는다). 응답(`PinItem.text`)은 사본을 쓰므로 원본 메시지를 보낸 사람이 지워도(4-a) 게시판에는 남고, `PinItem.message_deleted` 로 원본이 지워졌음을 알려 준다. 사본이 없는 옛 행(`text` null)은 원본 본문으로 대신한다. 공지에서 내리면(`unpin`) 사본도 함께 사라진다. 지운 메시지는 새로 올릴 수 없다(400 `not_pinnable`).
- **개인정보**: 보낸 사람이 원본을 지워도 게시판 본문은 남는다. 이는 의도한 동작(사용자 결정)이고, 지우고 싶으면 공지에서 내려야 한다.
- **나만 숨기기**: `PUT /family-chat/pins/{message_id}/hide?room_id=` → `PinItem`(`hidden: true`, 이미 숨겼어도 같은 결과), `DELETE …/hide` → 다시 보이게(`hidden: false`, 숨기지 않았어도 같은 결과). 올라가 있지 않은 공지·접근할 수 없는 방은 404. 사용자마다 따로(`chat_pin_hides`, 기본키 `(pin_id, user_id)`)이고 다른 구성원의 목록에는 영향이 없다. `GET /pins` 와 올리기 응답의 각 항목에 내 `hidden` 이 붙는다(숨긴 공지도 목록에는 나오고 앱이 감춘다). 공지가 내려가거나 3번째 공지 때문에 교체되면 그 공지의 숨김 기록도 지워(`pin_id` 외래키 ON DELETE CASCADE + 서비스가 같은 순서로 삭제), 다시 올리면 모두에게 보인다. CASCADE 라서 숨기기와 내리기·교체가 겹쳐도, 이 리비전 이전의 옛 코드가 공지만 지워도 외래키 위반이 나지 않는다(expand 호환). 숨기기·되돌리기는 고정·해제와 **따로** 분당 30회 한도를 센다(`chatpinhide:`).
- 개수(방당 2개)와 권한(구성원 누구나 올리고 내림)은 그대로다. API 경로는 하위 호환을 위해 `/family-chat/pins` 를 유지한다(앱 화면 이름만 "게시판").
- 시험: `tests/test_pin_board.py`(원본 삭제 후 유지, 사본 우선·옛 행 대체, 내릴 때 사본 삭제, 사용자별 숨기기·멱등·404·방 접근, 내림·교체 시 숨김 정리, 지운 메시지 고정 거절). 기존 `test_pins.py::test_pinned_text_is_the_copy_saved_when_pinned` 는 "본문을 복사하지 않는다"던 옛 정책을 사본 저장 정책에 맞게 바꿨다.
- 앱 화면(이름 변경, 원본 삭제 표시, 나만 숨기기 버튼)은 8-b 작업이다.

## 게시판 앱 화면 (8-b, release/1.1)
- **이름 변경**: 앱 화면의 "고정 메시지"를 "게시판"으로 바꿨다(채팅방 설정 행 "게시판 · 공지 모아보기", 바의 접근성 라벨 "게시판 접기 / 게시판 공지 N개 더 보기", 안내 문구 "게시판에 올렸어요 / 게시판에서 내렸어요 / 가장 오래된 공지가 내려갔어요 / 이미 게시판에 있는 메시지예요 / 게시판에 공지가 없어요", 메시지 시트의 "공지로 등록 / 게시판에서 내리기", 보조 줄 "○○ 올림 · 시각"). 서버 주소 `/family-chat/pins` 는 그대로다. 메시지 시트 자체는 5번 작업(팝업 메뉴)에서 바뀐다.
- **원본 삭제 표시**: 서버가 준 `message_deleted` 가 true 인 공지는 보조 줄 끝에 " · 원본 삭제됨"을 붙이고 접근성 라벨에도 "원본 메시지는 삭제됐어요"를 넣는다. 본문은 올릴 때의 사본이라 그대로 보인다.
- **나만 숨기기**: 게시판 바의 각 줄에 눈 아이콘 버튼("이 공지 나만 숨기기")이 있어 누르면 먼저 화면에서 감추고(낙관적) `PUT /family-chat/pins/{id}/hide` 를 보낸다. 실패하면 이전 상태로 되돌리고, 이미 내려간 공지(404)는 그대로 둔다. 숨긴 공지가 있으면 바 맨 아래에 "숨긴 공지 N개 · 다시 보기"가 있어 누르면 모두 다시 보인다(`DELETE …/hide`). 다른 구성원에게는 영향이 없다. 목록(`GET /pins`)에는 숨긴 공지도 `hidden: true` 로 들어 있고 바가 감춘다(`pinBarView`). 보이는 공지가 하나도 없고 숨긴 공지만 있으면 "다시 보기" 줄만 남는다.
- 코드: `pinUtils.js`(문구, `normalizePin` 의 `message_deleted`·`hidden`, `setPinHidden`, `pinBarView` 의 `hiddenByMe`, reducer `set_hidden`, `failureEffect`), `useChatPins.js`(`hide`·`showHidden`), `components/PinnedBar.js`, `api.js`(`hidePin`·`showPin`). 시험: `tests/chatpins.test.js`(기존 문구 기대값을 새 이름에 맞게 갱신하고 숨기기·원본 삭제 표시·API 경로 시험 추가).
- 한계: 숨김 상태는 이 기기의 목록 조회(30초 간격)와 내가 누른 직후에만 갱신된다. 서버가 "공지 없음"과 "방 접근 불가"를 같은 404 로 줘서 앱은 숨기기·되돌리기·내리기의 404 를 "이미 내려갔거나 볼 수 없는 공지예요"로만 안내한다(서버가 구분 코드를 주면 좁힌다 — 후속). 숨긴 공지 다시 보기는 요청을 병렬로 보내되 안내는 결과를 모아 한 번만 낸다. 훅(`useChatPins`)·`PinnedBar` 는 렌더 시험 환경이 없어 순수 함수만 시험한다. 실기기에서는 확인하지 못했다.

## 메시지 메뉴·답장·반응·삭제 앱 화면 (5·6·7번, release/1.1)
- **팝업 메뉴**(`components/MessageMenu.js`): 메시지를 길게 누르면 하단 시트 대신 **그 말풍선 바로 아래**에 작은 팝업(너비 196, 항목 높이 38)이 뜬다. 말풍선 위치는 `measureInWindow` 로 재서 내 말풍선은 오른쪽 끝, 상대는 왼쪽 끝에 맞추고, 화면 밖으로 나가지 않게 하며 아래가 모자라면 말풍선 위로 올린다(`messageActions.menuPosition`, 위치를 못 재면 누른 지점 근처). **삭제 확인은 화면 가운데**에 따로 뜬다. 맨 위에 반응 이모지 6개(내가 누른 것은 꿀색 강조, 다시 누르면 취소), 아래로 **답장 · 공지로 등록(또는 게시판에서 내리기) · 복사 · 삭제**. 항목은 `menuKeys` 가 정한다: 답장·반응은 저장된 지우지 않은 메시지 모두(사진 포함), 복사는 글자가 있는 메시지, 공지는 글자만 있는 텍스트 메시지, **삭제는 내가 보낸 메시지만(가비의 답 제외)**. 삭제를 누르면 같은 팝업이 "이 메시지를 삭제할까요? 삭제하면 모두에게서 삭제돼요" 확인(취소·삭제)으로 바뀐다. 이전의 하단 시트(`MessageActionSheet`)는 없앴다.
- **반응**: `PUT/DELETE /family-chat/messages/{id}/reaction`(`api.reactToMessage`·`removeReaction`). 말풍선 아래 작은 칩(이모지는 작은 글자 크기의 60%, 사람 수, 내가 누른 칩은 강조, 누르면 내 반응을 켜거나 취소)으로 보인다(`components/ReactionRow.js`). 한 사람이 한 메시지에 하나라 다른 이모지를 누르면 바뀐다. 먼저 화면에 반영하고(`withMyReaction`) 서버가 센 값으로 맞추며, 실패하면 이전 반응으로 되돌리고 안내 줄에 이유를 보인다.
- **더블탭 하트**: 말풍선(글자)을 두 번 누르면(300ms 이내) 하트 반응을 켜고, 이미 하트면 취소한다(`isDoubleTap`, `reactionAction`). 사진은 한 번 누르면 더블탭인지 잠깐 기다렸다가 크게 보고, 두 번 누르면 하트다. 웹에서는 글자 선택이 유지되어 더블클릭하면 낱말이 선택될 수 있다(네이티브는 선택을 끈다).
- **답장**(`api.sendMessage(text, roomId, replyToId)`): 메뉴의 "답장"을 누르면 입력창 위에 "○○에게 답장" 바(원본 한 줄 미리보기, 닫기)가 뜨고 입력칸에 커서가 간다(`Composer`). 보내면 답장 말풍선 안 위쪽에 **원본 인용**(`components/ReplyQuote.js`: 이름과 한 줄, 사진이면 "사진", 지웠으면 "삭제된 메시지입니다")이 붙고 누르면 원본 메시지로 이동한다(게시판 바와 같은 이동). 전송 실패한 답장을 다시 보내도 답장으로 간다. 원본이 지워지면 답장 바가 닫힌다.
- **삭제 표시**: `DELETE /family-chat/messages/{id}`(`api.deleteMessage`). 지운 메시지는 말풍선 대신 **가운데 정렬 "삭제된 메시지입니다"** 로 보이고(시각·이름·아바타·반응 없음), 방 목록 미리보기와 답장 인용에도 같은 문구가 나온다(`previewText`, `replyLine`). 먼저 화면에서 바꾸고(`markDeleted`, 그 메시지를 인용한 답장도 `markRepliesDeleted`) 실패하면 되돌린다. 사진을 지우면 말풍선이 사라져 사진 캐시도 풀린다.
- **다른 사람의 반응·삭제 따라가기**: 서버에 변경 조회가 아직 없어서, 열린 채팅방이 기존 3초 폴링 틱 **3번(약 9초)마다 최근 50개 메시지를 다시 받아** 이미 가진 메시지의 반응·삭제·본문만 갱신한다(`refreshExisting`, 새 메시지는 넣지 않아 새 메시지 확인 기준과 겹치지 않는다). 내가 반응·삭제 요청 중이거나 과거(검색 이동) 창을 볼 때는 건너뛰고, 실패는 조용히 넘긴다. 실시간 전달은 별도 검토 대상이다.
- 코드: `messageActions.js`(순수 함수), `useChatMessages.js`(`send(text, reply)`, `reactTo`, `deleteMine`, `refreshVisible`), `components/{MessageMenu,ReactionRow,ReplyQuote,MessageBubble,Composer}.js`, `screens/ChatRoomScreen.js`. 시험: `tests/chatmenu.test.js`(메뉴 항목, 반응 계산·불변, 삭제 표시, 답장 미리보기, 위치 계산, 더블탭 판정, 갱신 병합, 문구, API 경로·본문).
- 웹 브라우저에서 두 사용자(한 명은 화면, 한 명은 API)로 확인했다: 반응 칩과 내가 누른 강조, 더블탭 하트(내 이전 반응이 하트로 교체), 답장 인용과 답장 보내기(서버에 `reply_to` 저장), 삭제 확인과 삭제 후 표시, 상대의 반응·삭제가 새로고침 없이 따라오는 것. **실기기(안드로이드·iOS)의 길게 누르기·더블탭은 확인하지 못했다.**
- **리뷰 반영**: 내 반응·삭제 뒤에 도착한 오래된 갱신 응답은 변경 세대 번호로 버린다. 서버의 `GET /messages/deleted` 로 최근 50개 밖의 오래된 메시지·과거 창의 삭제도 따라간다(`syncDeleted`, 첫 불러온 직후 서버 시각을 기준으로 삼는다). 사진·원본 인용을 길게 눌러도 같은 메뉴가 열리고, 스크린리더에는 "메뉴 열기 / 사진 크게 보기 / 답장한 원본으로 이동" 동작을 노출한다. 답장하려던 원본이 지워져 보내기가 400 `reply_deleted` 로 실패하면 이유를 알리고 답장 표시를 떼서 다시 보내기는 답장 없이 간다. 지운 메시지 다음 말풍선에는 이름·시각을 보인다.
- **맨 아래 따라가기 수정(기존 문제)**: 대화가 길 때 처음 열면 중간에서 멈추고, 보낸 직후 마지막 메시지가 입력창에 가려지던 문제(변경 전 코드에서도 재현)를 고쳤다. 원인은 아직 그려지지 않은 아래 항목 때문에 내용이 길어지면 스크롤 이벤트가 "바닥에서 멀다"로 판정해 따라가기를 멈춘 것이다. 이제 `nearBottom`(바닥을 따라가는 중)은 "바닥 근처에 닿았다"와 "사용자가 위로 올렸다(스크롤 위치가 줄었다)"로만 바뀌고, 맨 아래로 간 뒤 150ms 뒤 한 번 더 맞춰 마지막 항목 높이(전송 중 → 시각·읽음 수) 변화를 따라간다. 웹에서 메시지 40여 개로 처음 열기·보낸 직후·위로 올려 읽는 중 새 메시지가 오는 경우를 확인했다.
- 한계: 훅과 컴포넌트는 렌더 시험 환경이 없어 순수 함수만 시험한다. 사진 메시지 더블탭의 지연(300ms), 삭제 메시지가 연달아 있을 때의 표시, 사진 단말 캐시 삭제(말풍선이 사라지는 것 외의 별도 처리 없음)는 후속으로 다듬을 수 있다.

## 게시판 목록(지난 공지 포함) (서버, release/1.1)
- **기록 보관**: 새 테이블 `chat_board_posts`(리비전 `e727c6b5f41e`)에 공지로 올릴 때마다 한 줄을 남긴다(`pin_service.pin` → `board_repository.upsert_post`). 같은 방의 같은 메시지는 한 줄이라 다시 올리면 그 줄의 올린 사람·시각·본문을 새로 고쳐 최신으로 올린다. 상단 고정 바(최신 2개, 내리기·교체)는 그대로이고, **내리거나 교체해도 기록은 남는다.** 본문은 올릴 때의 **전체 본문**(최대 2000자)이다(고정 바용 사본 `chat_pinned_messages.text` 는 200자 + 1자). 이미 올라가 있던 공지는 마이그레이션이 기록으로 복사한다(원본이 남아 있으면 원본 전체 본문, 지워졌으면 저장된 사본). 옛 공지에 기록이 없으면 다시 올릴 때 만든다.
- `GET /family-chat/board?room_id=&limit=&before=` → `{items, next_before}`. 올린 시각 최신순(`(posted_at, id)` 키셋), `limit` 1~50(기본 20), `before` 는 앞 응답의 `next_before`(base64 로 감싼 불투명 값, 잘못되면 400 `invalid_cursor`). 항목: `id`(글 id), `message_id`(채팅에서 보기용), `text`(전체 본문), `user_id`·`user_name`(원본을 쓴 사람), `message_created_at`, `posted_by`·`posted_by_name`, `posted_at`, `is_current`(지금 공지 바에 있는지), `message_deleted`(원본이 지워졌는지).
- `DELETE /family-chat/board/{post_id}?room_id=` → 204. **구성원 누구나** 지울 수 있다. 지금 공지로 올라 있으면 고정 바에서도(나만 숨기기 기록 포함) 같은 트랜잭션에서 내려간다. 원본 메시지는 그대로다. 없는 글·다른 방의 글·접근할 수 없는 방은 404. 고정과 같은 방 행 잠금 아래에서 처리하고, 호출 한도는 따로(`chatboard:`) 분당 30회를 센다.
- 방마다 따로다(가족 전체방, 1:1 방). 방에 들어갈 수 없으면 404(존재 여부를 숨김).
- **개인정보**: 공지의 전체 본문이 서버에 계속 남고, 원본 메시지를 지워도 게시판에는 남는다(사용자 결정). 지우려면 게시판에서 글을 삭제해야 한다. 로그에 본문을 남기지 않는다.
- 시험: `tests/test_board.py`(전체 본문, 내려가거나 교체돼도 보관, 최신순, 다시 올리면 한 줄 유지·최신으로, 원본 삭제 후 유지, 키셋 페이지·다시 올릴 때의 일관성, 커서·limit 검증, 누구나 삭제와 고정 바 정리, 지난 글 삭제가 현재 공지에 영향 없음, 방 격리·다른 가족·로그인, 기록 없는 옛 공지 보완).
- 앱 화면: 아래 "게시판 목록 화면(앱)" 참고.

## 게시판 목록 화면(앱, release/1.1)
- 채팅방 서랍(⋮)의 "게시판" 행을 누르면 새 화면 `/chat-board`(`ChatBoardScreen`, 가족 전체방은 인자 없음, 1:1 은 `roomId`·`peer`)가 열린다. 예전처럼 채팅방 위 공지 바를 펼치지 않는다. 공지 바(최신 2개, 나만 숨기기)는 그대로다.
- 목록: 올린 시각 최신순 카드(본문 앞 90자·올린 사람·시각·쓴 사람(다를 때만)·"현재 공지"/"지난 공지"·"원본 삭제됨" 표시), 칩 "전체"/"현재 공지"(받아 둔 목록 안에서 거름), 아래 "더 보기"(20개씩, 커서). 별명은 `nameOf` 로 반영.
- 카드를 누르면 상세 창: 전체 본문(복사 가능), "채팅에서 보기"(원본이 남아 있을 때만, 검색 결과와 같은 `focus` 경로로 이동), "삭제"(한 번 더 확인, 구성원 누구나; 성공이나 404 면 목록에서 뺀다, 실패하면 창에 사유 표시).
- 코드: `boardUtils.js`(순수 함수·상태 전이), `useChatBoard.js`, `components/BoardRow.js`·`BoardDetail.js`, `screens/ChatBoardScreen.js`, `src/app/chat-board.js`, `api.js`(`listBoard`·`deleteBoardPost`). 시험 `tests/chatboard.test.js`.
- 한계: 목록 새로고침은 화면을 다시 열 때뿐이다(다른 사람이 올리거나 지운 것은 다시 열어야 보인다). 직접 글쓰기는 없다. 실기기(iOS·Android) 확인은 하지 못했고 웹으로 목록·칩·상세·채팅에서 보기·삭제(공지 바에서도 내려감)를 확인했다.

### 서랍 정리 (앱, release/1.1)
- 서랍에서 **뺀 행**: 대화 내용 검색(채팅방 위 돋보기로 한다), 공유 문서, 구성원 초대 · 관리, AI · 개인정보 보호 설정, 채팅방 정보 수정. 구성원 초대·관리는 "더보기"의 가족 그룹에서 하고, 가족 채팅 AI 켜기·끄기는 앱에서 하지 않는다(AI 패널에서 제거, 아래 절 참고)(AI · 개인정보 설정 행은 원래 준비 중이라 잃은 기능은 없다).
- **남은 행**: 채팅 관리 — 게시판 · 사진 · 동영상 · **가족 할 일**(새 행, `/family-todos`, 공동 할 일과 대화에서 등록한 할 일, 가족방·1:1 모두 보임). 예전 "가족 일정 · 할 일" 행은 이 행으로 통합했다(위 "서랍 '가족 일정 · 할 일' 행은 없앴다") / 채팅방 설정 — 알림 설정(준비 중) · 채팅방 나가기. 위 "서랍 · 사진 모음" 절의 행 설명 중 검색·공유 문서·초대·개인정보·정보 수정 행은 이 절이 우선한다.
- **구성원 드롭다운**: 맨 위 "가족 구성원 N명"(1:1 은 "대화 상대")을 누르면 사진(이니셜)+이름 목록이 펼쳐지고 다시 누르면 접힌다(처음엔 접힘, `components/MemberStrip.js`).
- 코드: `mediaUtils.js`(`buildDrawerSections` 에서 `searchReady` 인자 제거, `resolveRowAction` 은 media·pins·familytodos — 이후 "가족 일정 · 할 일" 통합으로 links 는 없어졌다), `RoomDrawer.js`(`onOpenSearch` 제거). 시험: `chatmedia.test.js`·`chatlinks.test.js`·`chatpins.test.js` 의 서랍 구성 시험을 새 구성에 맞게 고쳤다(정책 변경).
- 확인 못한 것: 실기기·웹 화면에서 서랍을 직접 열어 보는 확인은 하지 못했다(순수 함수 시험과 린트만).

### 가족 일정 · 할 일 통합의 한계 (release/1.1)
- **앱에서 연결을 지울 방법이 없다**: 연결을 지우던 곳은 연결 시트의 "삭제"뿐이었고 시트가 없어졌다(`useChatLinks.remove` 는 호출하는 곳이 없다). 할 일을 지워도 서버가 연결을 정리하지 않는다. 서버는 방마다 연결을 **최대 200개**만 받으므로(`link_repository.MAX_LINKS`), 가족방에서 200개에 닿으면 새 연결이 `too_many_links` 로 거절되어 일정·할 일 등록 자체는 되지만 말풍선 "등록됨" 표시와 할 일 "원본" 버튼이 생기지 않는다(앱은 이 실패를 조용히 넘긴다). 해결 후보: 할 일을 지울 때 서버가 그 연결도 함께 지운다(같은 family_chat 안), 상한 조정.
- "원본" 버튼은 가족방 연결 중 최근 100개(`listLinks` limit)만 쓰므로 할 일 연결이 100개를 넘으면 오래된 할 일에서 빠진다. 서버는 `target_id` 필터를 지원한다.
- 원본 메시지가 지워져도 "원본" 버튼은 보이고(서버 연결이 지운 메시지를 거르지 않는다), 누르면 최근 대화로 돌아가고 안내가 뜬다. 게시판과 달리 "원본 삭제됨" 표시는 없다.
- 이동은 `router.push` 라 뒤로 가면 가족 할 일 화면으로 돌아온다(게시판은 `replace`).
- 시트 전용 도우미(`filterByKind`, `formatLinkWhen`, `linkSourceLine`, `linkA11yLabel`, `canDeleteLink` 등)와 `useChatLinks` 의 `links`·`remove`·`refresh` 등은 지금 화면에서 쓰지 않는다(말풍선 배지는 `badgesOf`, 등록은 `registerCandidate`).

### 공동 할 일 앱 제거 · 가족 할 일 = 일정 탭 내역 · 할 일 후보는 함께하기로 (앱, release/1.1)
- **채팅의 할 일 후보 → 함께하기**: AI 패널의 "할 일·부탁 후보"는 이제 **함께하기**(일정 탭의 같이 요청, `POST /schedule/requests`)로 보낸다. 일정 후보는 지금처럼 일정 탭의 일정(`POST /schedule/events`)으로 등록된다. 후보 줄의 버튼은 "함께하기로 보내기", 성공 문구는 "함께하기로 보냈어요". 함께하기는 **날짜가 필수**라 후보에 날짜가 없으면 날짜 칩(**오늘 · 내일 · 직접 입력**)을 먼저 골라야 보낼 수 있다. 직접 입력을 고르면 날짜 칸이 나타나 숫자를 치면 `YYYY-MM-DD` 로 하이픈이 자동으로 붙고(`formatDayInput`), 실제 있는 날짜이고 오늘 이후여야 한다(아니면 "날짜를 정확히 적어 주세요"). 받는 사람은 담당자 이름이 구성원 이름·표시 이름과 정확히 같은 한 명(나 제외)이면 그 사람, 아니면 나를 뺀 가족 모두다. 가족이 나뿐이면 "함께할 가족이 아직 없어요". **원본 대화 연결(말풍선 표시)은 만들지 않는다** — 서버 연결(`POST /family-chat/links`)은 `kind=todo` 의 대상으로 공동 할 일 id(`family_todos`)만 받아서 함께하기 요청 id 는 거절된다(`invalid_target`). 일정 후보의 연결(말풍선 "일정으로 등록됨")은 그대로다. 이미 있는 옛 `kind=todo` 연결(공동 할 일)의 배지는 "할 일로 등록됨"으로 남는다. 후보 기한이 오늘보다 앞선 날짜면 쓰지 않고 날짜 칩으로 새로 고르게 한다. 코드: `togetherUtils.js`(`candidateToRequestBody`, `dayFromChip`…), `components/TodoCandidateRow.js`, `components/AiPanel.js`, `api.sendTogetherRequest`.
- **서랍 "가족 할 일"**(`/family-together`, `screens/FamilyTogetherScreen.js`, `useFamilyTogether.js`): **일정 탭의 일정(약속, kind 1)·할 일**(`GET /schedule/events?include_past=true` 중 kind 2·안 끝낸 것·오늘 이후 — 시간 없는 오늘 할 일이 자정에 "앞으로의 것"에서 빠지지 않게 지난 것까지 받는다)과 **함께하기**(`GET /schedule/requests`: 받은 것·보낸 것)를 날짜순(같은 날은 함께하기 먼저)으로 최대 30개 간소화해 보여 준다. 보기만 하고, 줄을 누르면 일정 탭의 그 화면(할 일 상세 `/schedule/detail`, 받은 함께하기 `/schedule/together-receive`, 보낸 함께하기 `/schedule/together-detail`)으로 간다. 거절한 요청·취소된 요청·날짜 지난 요청, 수락해서 생긴 내 할 일은 요청의 `my_event_id` 로 찾아 뺀다(요청과 겹침). 보낸 요청의 답이 모두 거절이면 "모두 어려워요". 화면이 보일 때·당겨서 새로고침할 때만 불러온다. 일정 기능의 파일은 가져오지 않고 서버 계약대로 공통 래퍼로 호출한다.
- **공동 할 일(family_chat 할 일)은 앱에서 없앴다**: 화면(`FamilyTodosScreen`, `/family-todos`), 훅(`useTodos`, `useTodoOrigins`), 컴포넌트(`TodoRow`·`TodoComposer`·`TodoEditModal`·`TodoCard`), `todoUtils.js`, 소통 탭의 가족 할 일 카드, 할 일 API 래퍼(`listTodos` 등)를 지웠다. 이 때문에 위 "공동 할 일·가족 연락처 (앱, Chat 4)" 절의 가족 할 일 화면 설명과 "원본" 버튼(가족 일정 · 할 일 통합 한계 절)은 더 이상 맞지 않는다(가족 연락처 부분은 그대로다).
- **서버는 그대로 둔다**: `/family-chat/todos` API 와 `family_todos` 테이블·데이터는 남겨 둔다(데이터가 사라지는 변경은 DB 담당자 승인이 필요해 이번에 하지 않았다). 서버·테이블 삭제는 승인 뒤 별도 PR 로 한다. 이미 만들어진 공동 할 일은 앱에서 볼 수 없다.
- 시험: `tests/chattogether.test.js`(변환·날짜·받는 사람·내역 만들기·API 경로·서랍 행), 가족 연락처 시험은 `tests/contacts.test.js` 로 옮겼다.
- 확인 못한 것: 실기기 확인은 하지 못했다. 가족 할 일 화면과 AI 패널의 함께하기 전송은 웹에서 확인한다.
- **알려진 한계(리뷰, 실기기·일정 담당 협의 필요)**: 서랍 화면의 줄을 눌러 일정 탭의 함께하기 화면으로 갈 때, 일정 탭의 요청 저장소가 한 번 읽으면 다시 읽지 않아 새로 생긴 요청이 비어 보일 수 있다(일정 기능 쪽 새로고침 필요). 탭 바깥 화면에서 탭 안 라우트로 push 하는 첫 사례라 뒤로가기·탭 전환 동작을 실기기에서 확인해야 한다.
- **AI 대화 도우미의 "중요 메시지"는 형광펜 배경**(`AiPanel.js` 의 `marker` 스타일, 테마 `surfaceStrong`)으로 강조한다.
- 서랍 "가족 할 일"은 일정 탭의 **일정**(약속)도 함께 보여 준다(태그 "내 일정", 끝낸 표시는 할 일에만 적용). 채팅에서 일정으로 등록한 것이 여기서 보인다.
- **서랍에서 연 화면(게시판·가족 할 일·사진 모음)에서 뒤로 돌아오면 채팅은 가장 최근 메시지로 이동한다**(`ChatRoomScreen` 의 포커스 처리, 검색 결과로 이동한 과거 창을 보는 중이면 그대로). 웹에서 위로 올려 둔 상태로 확인했고 실기기는 확인하지 못했다.

### AI 패널의 켜기·끄기 제거 (앱, release/1.1)
- **전제(사용자 결정)**: 모든 회원이 회원가입 단계에서 AI 동의를 한다. 다만 **이 동의 화면은 `release/1.1` 에 아직 없다**(현재 가입 화면에는 AI 동의가 없고, 동의서 화면은 테스트 참여 동의다 — 팀원 작업 중). 이 전제가 갖춰지기 전에는 AI 전송에 대한 설명·동의를 받는 화면이 없다. 이 전제 아래에서 AI 패널(`AiPanel.js`)에서 **"AI 기능 켜기"·"AI 끄기" 버튼, 동의 안내 카드(`AiConsentCard`, 파일 삭제), 켜기 직전 확인, 관리자 안내 문구를 모두 없앴다.** 패널에는 상시 안내문(`PANEL_NOTICE`)·남은 횟수·**"대화 분석하기"** 만 남는다.
- 이 가족의 AI 설정이 꺼져 있는 경우(예전에 꺼 둔 가족)에는 "대화 분석하기"를 눌러도 바로 켜지 않고, 켜는 것이 **가족 전체에 적용된다**는 확인 카드(`ENABLE_ON_ANALYZE_*`: "가족의 AI 기능이 꺼져 있어요" + 설명 + "켜고 분석하기"/"취소")를 먼저 보인다. **"켜고 분석하기"를 눌렀을 때만** `PUT /family-chat/ai/settings`(enabled true)로 켠 뒤 분석하고, 취소하면 아무것도 켜지지 않는다(안 켜면 서버가 `ai_not_enabled` 로 막는다). 이미 켜져 있으면 확인 없이 곧바로 분석한다. 끄는 UI는 없다(서버 API 는 구성원 누구나 가능, #160 — 앱에 끄는 화면이 없는 점은 후속 과제).
- `tests/privacycopy.test.js`·`privacypreview.test.js` 의 동의 흐름 시험(켜기 확인·관리자만 끄기 등)은 이 정책 변경으로 새 시험(버튼 없음, 꺼져 있을 때만 분석 직전에 켬, PUT 호출 위치 허용 목록 유지)으로 바꿨다. 동의 문구(`privacyCopy.js`)는 가입 동의 화면 등에서 쓸 수 있어 남겼다.

## 채팅방 알림 끄기 (서버, release/1.1)
- `PUT /family-chat/rooms/{room_id}/mute {muted}` → 200 `{room_id, muted}`(멱등). 방 접근 규칙은 `resolve_room` 과 같다: 다른 가족의 방·내가 참여자가 아닌 1:1 방·없는 방은 404. `GET /family-chat/rooms` 의 각 방과 1:1 방 열기(`POST /rooms/direct`) 응답에 `muted: bool`(기본 false)이 붙는다.
- DB: 새 테이블 `chat_room_mutes`(기본키 `(room_id, user_id)`, 리비전 `c606f5b0deb6`, expand). 행이 있으면 끈 것, 켜면 행을 지운다. 방 목록은 내 방들의 muted 를 쿼리 한 번(`repo.muted_room_ids`)으로 모아 방 수와 상관없이 쿼리 수가 일정하다.
- 범위: 설정 저장만. 푸시는 아직 없고, 읽지 않은 수(`unread`) 계산은 그대로다.
- 시험: `tests/test_room_mute.py`(기본값, 가족 전체방·1:1 방 켜기/끄기, 멱등, 사용자별 독립, 안 읽은 수 유지, 접근 거부, 요청 검증).
- 앱 화면(방 행 스와이프·채팅방 서랍 스위치)은 아래 앱 절을 본다.

### 방별 알림 끄기 (앱, release/1.1)

- 서버 계약: 방 목록 각 방의 `muted`(없으면 false), `PUT /family-chat/rooms/{room_id}/mute` 본문 `{muted}` → `{room_id, muted}`. 푸시는 아직 없어 설정 저장만 하고, 소통 탭 읽지 않음 숫자 배지는 그대로다.
- 소통 탭: 방 행을 왼쪽으로 밀면(오른쪽에 액션이 드러난다) 종 아이콘 액션("알림 끄기"/"알림 켜기")이 드러난다(`SwipeableRoomRow`, gesture-handler `ReanimatedSwipeable`; 루트 `_layout.js` 에 `GestureHandlerRootView` 추가). 꺼진 방은 방 이름 오른쪽에 꺼짐 아이콘과 접근성 제목 "알림 꺼짐"이 붙는다. 웹은 스와이프 없이 일반 행이고, 스크린 리더는 접근성 액션으로 같은 토글을 쓴다. 토글은 화면에 먼저 반영하고 저장하며, 실패하면 되돌리고 안내 문구를 보인다(같은 방은 저장 중 재탭 무시).
- 채팅방 서랍: "알림 설정"(준비 중) 행이 "이 방 알림" 스위치 행으로 바뀌었다(`useRoomMute`: 서랍을 열 때 방 목록에서 이 방 값을 읽고, 알기 전에는 비활성, 낙관적 갱신+실패 시 되돌림). 소통 탭은 화면에 올 때마다 목록을 다시 읽어 서랍에서 바꾼 값이 반영된다.
- 실기기 동작(스와이프 감, 접근성 액션)은 아직 확인하지 못했다.

### 소통 탭 UI 정리 (앱, release/1.1)

- "가족 연락처" 섹션이 방 목록 위(헤더·검색 바로 아래)로 올라왔다. 카드 모양과 동작(전체 보기, 카드 누르기)은 그대로다.
- 방 행 사이에 얇은 구분선이 생겼다(`RoomRow` 의 `divider`, 프로필 사진 오른쪽부터 시작하는 들여쓴 선, 마지막 행은 없음). 스와이프로 행을 밀어도 선이 행과 함께 움직인다.
- 알림을 끈 방의 아이콘(`notifications-off-outline`)을 시각 옆에서 방 이름(구성원 수) 오른쪽으로 옮기고 16px 로 키웠다. 시각 칸에는 시각만 남는다. 접근성 제목의 "알림 꺼짐"은 그대로다.
- 실기기 화면은 아직 확인하지 못했다.

### 입력줄 개편·문서 첨부·저장 (앱, release/1.1)

- 입력줄: 왼쪽 + 는 아래에서 올라오는 시트(사진·파일·일정·정산·안부)를 연다. 사진을 누르면 시트를 닫고 바로 갤러리가, 파일을 누르면 문서 선택 화면이 열려 보낸다(보내는 동안 + 버튼이 진행 표시). 일정·정산·안부는 아직 준비 중이라 누르면 시트를 닫고 입력줄 위에 "준비 중이에요"를 보인다. 입력칸 안 오른쪽에는 보내기 버튼만 있고 글자가 있을 때만 켜진다(`Composer`, `PlusSheet`, 순수 로직 `fileUtils.js`).
- 문서 보내기: `pickChatDocument.js`(expo-document-picker)에서 pdf·doc(x)·xls(x)·ppt(x)·hwp(x)·txt·csv, 20MB 이하만 앱에서 먼저 검사하고(서버도 다시 검사) `POST /family-chat/files` 로 보낸다(`api.sendFile`, `useChatMessages.sendDocument`). 서버 계약은 서버 작업 완료 전이라 `kind`/`filename`/`size_bytes`/`content_type` 를 가정했다.
- 말풍선: `attachment.kind === "file"` 이면 파일 카드(`FileCard`: 파일명 2줄, 크기). 카드 본문은 열기/공유(`openFile.js`: 캐시에 받아 expo-sharing 공유 시트, 웹은 내려받기). 방 목록·답장 미리보기는 "파일".
- 저장 방법: 사진은 사진 보기의 "사진첩에 저장"(기존 `savePhoto.js`, expo-media-library, 쓰기 전용 권한). 문서는 카드 오른쪽 다운로드 아이콘("내 파일/드라이브에 저장"): 안드로이드는 폴더 선택(SAF, 드라이브 포함)에 쓰고 안 되면 공유 시트, 아이폰은 공유 시트의 "파일에 저장", 웹은 내려받기.
- 실기기(Expo Go)에서 파일 열기·저장(안드로이드 폴더/드라이브, 아이폰 파일 저장, 사진첩 저장)과 새 입력줄 모양은 아직 확인하지 못했다.

### @가비 기능 예시 목록 (15번, 앱, release/1.1)

- 입력창 글(앞뒤 공백 제외)이 `@`, 한글 조합 중간(`@ㄱ`·`@갑`·`@가ㅂ`), `@가비`, 또는 `@가비 `(질문이 빈 상태)일 때만 입력줄 위에 예시 목록을 보인다. 질문을 쓰기 시작하면(`@가비 이번…`) 사라진다. `@가비야` 처럼 이어 붙은 글은 부름이 아니라 보이지 않는다. 판단은 순수 함수 `mentionHintsVisible(text, direct)`(`mention.js`, `parseMention` 과 같은 규칙).
- 1:1 방에서도 `@` 예시 목록을 가족 전체방과 같게 보인다. `@가비` 는 1:1 방에서도 부를 수 있고(`useMention(roomId)` → `askAssistantInRoom(q, history, roomId)`), 서버가 답을 그 1:1 방에 가비 이름으로 저장해 두 사람에게만 보인다(상대가 가족을 나갔으면 403 `peer_left`, 참가자가 아니면 404). 1:1 에서는 일정 에이전트를 아직 쓰지 않는다(상대 한 명 기준 조회·공유는 후속 PR). **이전 대화 복원**: 방에 들어올 때(처음 불러온 메시지) 내 `@가비 질문` 바로 다음 메시지가 가비의 답이면 한 쌍으로 되살려 이어 간다(`restoreThread`, `useMention.seed`; 사이에 다른 사람 글이 끼면 건너뛰고, 서버로는 여전히 15분 이내 최근 6개만 보낸다).
- 항목을 누르면 예시 문장 전체가 입력창에 채워진다(보내지 않음, 포커스 유지, 고쳐서 보낼 수 있음). 채워지면 목록은 저절로 사라진다. 목록은 입력줄 위 일반 흐름에 있고 최대 4줄 높이에서 스크롤한다.
- 예시(`MENTION_EXAMPLES`)와 서버 근거: 지출 "이번 달 지출 알려줘", 일정 "내일 일정 알려줘", 일정 등록 "토요일 저녁 가족 식사 일정 넣어줘"(`ai_assistant/agents.py` 탭 에이전트), 채팅 검색·요약(`family_chat/agent.py`), 문서 "올려 둔 영수증 찾아줘"(`ai_assistant/knowledge/rag_chat.py`). 날씨·일반 질문은 서버가 처리하지 않아 넣지 않았다.
- 예시를 바꿀 때는 서버 프롬프트·탭 에이전트가 그 질문을 실제로 처리하는지 대조한다. `EMPTY_QUESTION_HINT` 의 예는 첫 예시에서 만든다.
- 실기기 확인 전: 키보드가 올라온 상태의 목록 높이, 항목을 눌렀을 때 포커스 유지(웹·안드로이드·iOS).
- 가족 전체방에서 실제 동작: 일정 등록은 바로 반영되지 않고 다른 구성원에게 공유하는 확인 카드가 질문한 사람에게만 보이며, 공유 확인 뒤에 반영된다(`schedule/agent/ask.py`). 공유해서 등록을 확인하면 가비가 결과("'제목' 일정을 11/07 18:00에 등록하고 가족 N명에게 공유했어요")를 방에 알린다. 그래서 예시는 개인 일정이 아닌 공동 일정 문구로 했다. @가비 의 AI 답은 가비 이름으로 방에 저장되어 가족 모두에게 보이고 기록으로 남는다(일정 조회는 공동 일정만 읽고 날짜·시간·제목만 보인다). 확인 카드가 딸린 질문("등록할까요?")과 AI 가 답하지 못한 안내는 방에 올리지 않고 질문한 사람 화면에만 보이며 화면을 닫으면 사라진다. 지출 요약·용돈 장부·문서 답은 방 전체에 올라가므로 사용자가 알고 써야 한다.
- 예시 문구를 바꿀 때는 서버 프롬프트와 탭 에이전트 도구와 대조해야 한다.
- 예시를 채운 직후에만 `TextInput` 의 `selection` 을 끝으로 지정해 안드로이드에서 커서가 끝에 가게 하고, 다음 글자 입력·선택 변경 때 해제한다.
- **가족 연락처 카드 박스 제거**: 소통 탭의 "가족 연락처 · 전체 보기 →" 제목 줄은 그대로 두고, 그 아래 구성원 사진·"가족 N명 등록됨" 카드 박스만 뺐다. `/family-contacts` 화면은 그대로다.

## 가족 전체방 문서 → 가족 공유 문서함 자동 등록 (GaBee 2.0 1단계, 2026-11)
- 요구사항·결정: `docs/requirements/family-library.md`. 가족 **전체방**에 올린 **문서 첨부**(`POST /family-chat/files`)가 저장되면 `shared/chat_library.document_posted` → `ai_assistant/library.py` 가 백그라운드에서 읽어(`files.process_file` 재사용: 원본 보관·가리기·분류) 가족 공유 문서함(`knowledge_items`)에 등록한다. `family_chat` 이 `ai_assistant` 를 직접 import 하지 않도록 `ai_assistant` 가 시작할 때(`router` 가 `library.register()`) 처리 함수를 통로에 등록한다.
- 연결 키: `knowledge_items.source_attachment_id`(채팅 첨부 id, 유일). 같은 첨부는 한 번만 등록되고(재시도·중복 요청 포함), 같은 파일을 다른 메시지로 다시 올리면 기록은 메시지마다 한 건이고 보관 원본은 한 번만이다.
- **등록하지 않는 것**: 1:1 방의 파일, 일반 사진(문서를 찍은 사진은 판별해서 등록하고, 애매한 사진은 "문서로 저장"으로 직접 넣는다 — `docs/requirements/family-library.md`), **민감 문서**(처방전·신분증 등, 가리기 전 원본 사본도 남기지 않음), ingest 가 지원하지 않는 형식(hwp·hwpx·예전 doc/xls/ppt, 읽기 전에 거르고 보관하지 않음), 읽지 못한 문서(실패 기록을 남기지 않음, 채팅 파일로는 남는다).
- 채팅에 이미 올라온 파일이라 "가족 문서함에 새 문서가 올라왔어요" 알림은 보내지 않는다(`files._process_once` 가 `source_attachment_id` 가 있으면 건너뜀).
- **삭제 동기화**: `DELETE /family-chat/messages/{id}` 가 첨부를 지우면 `chat_library.attachment_removed` 로 연결된 기록·검색 조각·원본(다른 기록이 쓰지 않을 때)도 `files.delete_record` 로 함께 지운다.
- 등록은 어떤 경우에도 채팅 전송·삭제를 깨지 않는다(실패는 로그에 종류만 남김).
- **문서 사진 자동 등록·"문서로 저장"(PR 1b, 서버 2026-11-09)**: 가족 전체방 사진을 보내면 `photo_service.send_photo` 가 `chat_library.photo_posted` 로 알리고, `ai_assistant/library.py` 가 뒤에서 판별(`ingest/photo_judge.py`: 로컬 OCR 의 글자 수·줄 수 → 필요하면 `doc_ai.classify_photo` 로 Claude haiku 판별, `PHOTO_JUDGE_LLM`)해 문서면 같은 읽기 경로로 등록한다. 가족당 하루 30장·대기 20장 상한. 애매한 사진은 `POST /family-chat/photos/{attachment_id}/library`("문서로 저장", 판별·상한 건너뜀, `queued`/`already`, 1:1 방 409)로 직접 넣는다. 결정·평가는 `docs/adr/0015-family-room-photo-to-library.md`.
- 앱: 가족 전체방에서 문서를 처음 올리기 전에 "가족 문서함에 자동으로 모여요" 안내를 한 번 보인다(`libraryNotice.js`, `AsyncStorage` 키 `gabee.library.notice.v1`, 1:1 방은 보이지 않음).
- DB: `knowledge_items.source_attachment_id` 추가(Alembic, `docs/contracts/db.md`).
- 시험: `ai_assistant/tests/test_chat_library.py`(14개), 앱 `tests/librarynotice.test.js`.
