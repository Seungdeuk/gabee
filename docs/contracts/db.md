# DB 구조

서버는 SQLAlchemy 2 로 접근한다(`apps/api/app/shared/db.py`).
로컬 기본값은 SQLite(`apps/api/data/gabee.db`) — 테스트와 로컬 간단 실행용으로 `init_db()`가 시작 시 `create_all()`로 테이블을 만든다.
docker compose 의 개발용 PostgreSQL(`pgvector/pgvector:pg16` 이미지, `pgvector` 확장 포함)은 **Alembic**(`apps/api/alembic/`)이 스키마를 전담한다 — `init_db()`는 PostgreSQL에서 테이블을 만들거나 바꾸지 않는다. DB가 코드보다 뒤처져도 서버는 시작하고, 기능별로 실제 스키마(테이블·컬럼)를 점검해 준비되지 않은 기능의 API만 503을 돌려준다(`GET /health/db`로 상태 확인, [ADR 0006](../adr/0006-schema-gate-degraded-start.md)). `supabase/migrations`는 더 이상 스키마 변경에 쓰지 않는다. 새 마이그레이션 만드는 법은 [README.md](../../README.md) 참고. 테이블을 바꾸면 이 문서도 갱신한다.

개인 로컬 Docker DB와 팀 공용 DB의 구분, 계정 역할(`gabee_app`/`gabee_migrator`)은 [README.md](../../README.md)의 "팀 공용 PostgreSQL 에 연결하기"와 [docs/adr/0005-shared-postgres-env.md](../adr/0005-shared-postgres-env.md) 참고.

| 테이블 | 기능 | 설명 |
|---|---|---|
| users | family_group | 이름, 역할(parent/child/other), 로그인 토큰, 현재 가족 그룹, (PR 4-A, 스키마만) `login_id`/`email`/`email_verified_at`/`password_hash` — 전부 nullable, 익명 계정은 전부 NULL. 가입 시 역할이 기타일 때 직접 적은 관계 `role_detail`(nullable, 40자). 위치 공유 동의 시각 `location_consent_at`(없으면 미동의)프로필 사진(PR B) `profile_photo_path`(상대 경로 `profile_photos/<user_id>.jpg`, 서버가 정함, nullable 255자)·`profile_photo_updated_at`(바꾼 시각, 캐시 무효화용, nullable) — 파일은 DB 가 아니라 `DATA_DIR/profile_photos/` 에 있고 둘 다 NULL 이면 사진 없음 |
| groups | family_group | 가족 그룹(이름, 소유자) |
| group_members | family_group | 그룹 구성원(그룹+사용자가 기본키). (PR 4-A, 스키마만) `role`(owner/admin/member, 그룹당 owner 최대 1명을 부분 유니크 인덱스로 강제), `family_relation`/`family_relation_detail`/`display_name` |
| invites | family_group | 초대 코드(그룹, 만든 사람, 철회 여부). (PR 4-A, 스키마만) 서로게이트 `id`(UNIQUE, join_requests/invite_attempts 가 참조), `expires_at`/`max_uses`/`use_count` |
| social_accounts | family_group | (PR 4-A, 스키마만) Google/Kakao 소셜 로그인 연동(`provider`+`provider_uid` 유니크) |
| refresh_tokens | family_group | (PR 4-A, 스키마만) 로그인 세션(토큰 원문 대신 `token_hash`만 저장) |
| password_resets | family_group | 비밀번호 재설정 토큰(해시만 저장) + 6자리 코드 해시(`code_hash`)·틀린 횟수(`failed_attempts`) |
| email_verifications | family_group | 이메일 인증 토큰(해시만 저장) + 6자리 코드 해시(`code_hash`)·틀린 횟수(`failed_attempts`) |
| member_nicknames | family_group | (PR 4-A, 스키마만) 구성원이 다른 구성원에게 붙이는 개인별 별명·메모. `(group_id,owner_user_id)`/`(group_id,target_user_id)` 둘 다 `group_members`를 참조하는 복합 FK — 실제 그룹 멤버만 작성자/대상이 될 수 있다 |
| join_requests | family_group | (PR 4-A, 스키마만) 초대코드로 참여 신청 후 관리자 승인 대기(`status` pending/approved/rejected). 같은 `(group_id,user_id)`로 pending 중복 금지(부분 유니크) |
| invite_attempts | family_group | (PR 4-A, 스키마만) 초대코드 레이트리밋용 시도 기록(ip/user_id/invite_id, 성공 여부) — 코드 원문·해시는 저장하지 않는다 |
| messages | family_chat | 대화방 메시지. `room_id`(비어 있을 수 있음, `chat_rooms` 참조; 비어 있으면 가족 전체방으로 본다)·`(room_id, id)` 인덱스(`ix_messages_room_id_id`) 추가. `(group_id, id)` 복합 인덱스(`ix_messages_group_id_id`, 안 읽은 수·읽음 위치 조회용). 단일 인덱스 `ix_messages_group_id` 는 복합 인덱스에 포함되므로 후속 contract PR 에서 정리(이번에는 삭제하지 않음). `deleted_at`(시간대 포함, nullable): 보낸 사람이 지운 시각, 지우면 `text` 를 빈 문자열로 비우고 첨부 행도 지운다(행은 남겨 읽음 위치·순서 유지). 리비전 `44171263393c`(expand). `reply_to_id`(nullable, `messages` 자기 참조 외래키 `messages_reply_to_id_fkey`): 답장하는 원본 메시지 id(같은 방), 기존 메시지는 모두 null. 리비전 `432e249f600c`(expand) |
| message_reactions | family_chat | 메시지 반응. `message_id`(`messages` 참조)·`user_id`(`users` 참조)가 함께 기본키라 **한 사람이 한 메시지에 반응 하나**(바꾸면 교체), `emoji`(6개 허용 목록은 서비스가 지킨다, 최대 8자), `created_at`(시간대 포함). 메시지를 지우면 그 메시지의 반응 행도 함께 지운다. 리비전 `8ba852cd9c10`(expand) |
| chat_read_states | family_chat | (옛 구조, 더 이상 읽고 쓰지 않음 — `chat_room_reads` 로 이전, 이후 contract 리비전에서 정리) 구성원별 가족 대화 읽음 위치. `(group_id, user_id)` 기본키(각각 `groups`·`users` 참조), `last_read_message_id`(앞으로만 증가, 행이 없으면 0), `updated_at`. 리비전 `d4b8f2a6c013` |
| chat_rooms | family_chat | 대화방. `kind` family(가족 전체방, 가족마다 하나: 부분 유니크 인덱스 `uq_chat_rooms_one_family_per_group`)·direct(1:1). 1:1 방은 `direct_key`(두 사용자 id 를 정렬해 `:` 로 이은 값)와 `(group_id, direct_key)` 유니크로 같은 두 사람의 방을 하나만 허용. 리비전 `b6e2c9f4a187` |
| chat_room_members | family_chat | 1:1 방 참여자 `(room_id, user_id)`. 가족 전체방은 가족 구성원 전원이라 행이 없다 |
| chat_room_reads | family_chat | 방별 구성원 읽음 위치 `(room_id, user_id)` 기본키, `last_read_message_id`(앞으로만 증가, 행이 없으면 0), `updated_at`. 옛 `chat_read_states` 값은 리비전에서 복사했다 |
| message_attachments | family_chat | 채팅 첨부(사진·문서). 메시지 하나에 첨부 하나(`message_id` 유니크, `messages` 참조), `group_id`·`room_id`(각각 `groups`·`chat_rooms` 참조), `kind`(`image`\|`file`, 기본 `image`, NOT NULL), 서버가 정한 상대 경로 `path`·`thumb_path`(문서는 null), `width`·`height`(문서는 null), `size_bytes`, `filename`·`content_type`(문서만, null 허용). 첨부 메시지의 `messages.text` 는 빈 문자열. 리비전 `c9a4d7e2b605`, 문서 첨부 `f06220eb955a` |
| family_todos | family_chat | 가족 공동 할 일. `group_id`(`groups` 참조)·`title`(120자)·담당자 한 명 `assignee_id`(없을 수 있음)·`due_date`(날짜만, 없을 수 있음)·`done_at`/`done_by`(완료 표시)·`created_by`·`source`(manual/chat)·`created_at`/`updated_at`. 가족 전체가 공유한다. 리비전 `d7b3a9f1c248` |
| chat_pinned_messages | family_chat | 채팅방 게시판(고정 메시지)에 올린 메시지. `group_id`(`groups` 참조)·`room_id`(`chat_rooms` 참조, 가족 전체방도 방 id 를 쓴다)·`message_id`(`messages` 참조)·`pinned_by`(`users` 참조)·`pinned_at`(시간대 포함). `text`(nullable): 올릴 때의 본문 사본(게시판에 보이는 앞 200자 + 잘렸는지 알아볼 1자만)이라 원본 메시지를 보낸 사람이 지워도 게시판에 남고, 내리면 함께 사라진다. 사본이 없는 옛 행은 조회할 때 원본 본문을 쓴다. 유니크 `(room_id, message_id)`(같은 메시지는 한 번만)·인덱스 `(room_id, pinned_at)`. 방당 최근 2개만 남기는 것은 서비스가 방 행 잠금 아래에서 지킨다. 리비전 `e8c1f4a7b903`, 사본 `d079d509f651`(expand, 기존 공지는 현재 본문으로 채움) |
| chat_pin_hides | family_chat | 게시판 공지를 "나만 숨기기"한 기록. `pin_id`(`chat_pinned_messages` 참조)·`user_id`(`users` 참조)가 함께 기본키, `hidden_at`(시간대 포함). 사용자마다 따로이고 다른 구성원에게는 영향이 없다. `pin_id` 외래키는 ON DELETE CASCADE 라 공지가 내려가거나 교체되면 DB 가 함께 지운다(SQLite 는 외래키를 강제하지 않아 서비스도 같은 순서로 지운다). 리비전 `d079d509f651`(expand) |
| chat_board_posts | family_chat | 게시판에 올린 공지의 **기록**(지난 공지 포함). 공지로 올릴 때마다 한 줄이 생기고 공지를 내리거나 교체해도 남는다. `group_id`(`groups` 참조)·`room_id`(`chat_rooms` 참조)·`message_id`(`messages` 참조)·`posted_by`(`users` 참조)·`posted_at`(시간대 포함, 목록은 이 순서 최신순)·`text`(올릴 때의 **전체 본문** 사본, 원본 메시지를 지워도 남는다). 같은 방의 같은 메시지는 한 줄(유니크 `(room_id, message_id)`)이라 다시 올리면 그 줄의 올린 사람·시각·본문을 새로 고친다. 인덱스 `(room_id, posted_at)`·`group_id`. 구성원 누구나 목록에서 지울 수 있다. 리비전 `e727c6b5f41e`(expand, 이미 올라가 있는 공지는 이 리비전에서 복사) |
| chat_room_mutes | family_chat | 구성원이 대화방의 알림을 끈 기록. `(room_id, user_id)` 기본키(각각 `chat_rooms`·`users` 참조), `created_at`(시간대 포함). 행이 있으면 끈 것이고 다시 켜면 행을 지운다(기본은 켜짐). 사용자마다 따로이고 다른 구성원에게는 영향이 없다. 리비전 `c606f5b0deb6`(expand) |
| chat_message_links | family_chat | 채팅 메시지와 그 메시지에서 등록한 일정·할 일의 연결. `group_id`(`groups` 참조)·`room_id`(`chat_rooms` 참조, 가족 전체방도 방 id 를 쓴다)·`message_id`(`messages` 참조)·`kind`(event/todo)·`target_id`(일정 또는 할 일 id, 일정은 다른 기능이라 외래키 없이 복사본만)·`title`(120자 복사본)·`date`·`time`(없을 수 있음)·`created_by`(`users` 참조)·`created_at`. 본문은 복사하지 않고 `messages` 와 join 해서 읽는다. 유니크 `(room_id, message_id, kind, target_id)`·인덱스 `(room_id, created_at)`. 방당 최대 200개는 서비스가 지킨다. 리비전 `c4d8a2e6b157` |
| ai_group_settings | family_chat, ai_assistant | 가족 그룹의 AI 기능 사용 동의(`enabled`, 켠 사람). 기본은 꺼짐. 소유자·관리자만 바꾼다 |
| agent_proposal_uses | billing | 에이전트 쓰기 제안 토큰을 한 번만 쓰게 하는 사용 기록(`jti`, 만료 시각, 사용 시각). 토큰 원문은 저장하지 않고, 만료가 지난 행은 새 토큰을 쓸 때 지운다 |
| notifications | notifications | 알림함. 사건 한 건당 받는 사람마다 한 줄(`user_id`, `group_id`, 분류 `kind`, 세부 종류 `event`, 고정 문구 `title`/`body`, 이동 대상 `target_type`/`target_id`, 행동한 사람 `actor_user_id`, 생성·읽은 시각). 인덱스 `(user_id, created_at)`, `(user_id, read_at)`. 금액·위치·건강 정보·AI 요약·채팅 내용은 담지 않는다 |
| ai_usage_logs | family_chat, ai_assistant | AI 요청별 사용 기록(기능, API 호출 수, 입력·출력 토큰, 캐시 적중, 상태, 오류 코드, 모델). **대화·문서 원문과 API 키는 저장하지 않는다.** 하루 한도·쿨다운 계산에 쓰고 90일이 지난 기록은 정리한다 |
| ai_result_cache | family_chat, ai_assistant | 같은 AI 요청의 검증된 결과(가족 그룹·기능·키로 유일). 만료 시각까지만 재사용하고 새 결과를 저장할 때 만료된 행을 지우며, 동의를 끄면 그 가족의 행을 모두 지운다 |
| ai_inflight | family_chat, ai_assistant | 가족 그룹에서 진행 중인 AI 호출 표시((group_id, slot) 기본키, 소유 `token`). 동시 실행을 여러 워커에서도 막는다. 오래된 표시는 치운다 |
| events | schedule | 일정. 기존 `title`·`starts_at`·`note`·`status`·`source`·`created_by` 에 더해, 사람마다 자기 줄을 갖는 구조용 컬럼을 추가했다(리비전 `e1a5c7b93d20`): 주인 `user_id`(`users` 참조), `kind`(1 약속·2 할 일), `place`, `start_date`·`start_time`·`end_time`(시간이 비면 시간 없음, 종일은 00:00~23:59), `memo`, `checked`, 공유 복사본의 원본 `origin_id`(자기 테이블 참조), `suggestion_id`·`request_id`·`recip_id`(각각 추천·부탁·받는 사람 답과 연결), `topic_id`(주제 `events_topics` 참조, nullable, 리비전 `bfb345450bd6`), `edited_at`, 삭제 시각 `deleted_at`(소프트 삭제). 모두 nullable 이거나 기본값이 있다(`user_id` 는 코드 전환 뒤 NOT NULL 로 조일 예정). 서버는 이제 새 컬럼과 옛 컬럼을 함께 채우고, 조회는 `user_id` 가 나이거나 비어 있는(옛 일정) 줄 중 `deleted_at` 이 빈 것만 읽는다. 공유 복사본은 만든 뒤 독립이라 원본 변경·삭제가 복사본에 번지지 않는다(`origin_id` 는 출처 표시). `source` 에 `request`(부탁으로 만든 일정) 값이 추가된다. 제거 예정: `starts_at`·`note`·`created_by`·`status`(코드 전환 뒤 별도 리비전) |
| events_topics | schedule | 주제(일정 분류). 사람마다 자기 주제를 가진다. `group_id`·`user_id`(각각 `groups`·`users` 참조)·`name`(30자)·`color`(16자)·`created_at`·삭제 시각 `deleted_at`(소프트 삭제). `(group_id, user_id)` 인덱스. 일정은 `events.topic_id` 로 가리킨다. 리비전 `bfb345450bd6` |
| events_requests | schedule | 부탁 본문. `group_id`·`user_id`(부탁한 사람, 각각 `groups`·`users` 참조)·`title`·`place`·`memo`·`start_date`·`start_time`·`end_time`·`created_at`·취소 시각 `canceled_at`·받는 사람을 바꾼 마지막 시각 `edited_at`. 받는 사람 목록은 컬럼이 아니라 `events_request_recipients` 행들(보낸 사람이 받는 사람을 빼면 그 행을 지운다). 리비전 `f2b6d8c04e31`, `edited_at` 은 `b7e4c1a95d36` |
| events_request_recipients | schedule | 부탁의 받는 사람별 답. `request_id`(`events_requests` 참조)·`user_id`(받는 사람)·`status`(1 대기·2 수락·3 어려움)·`created_at`·`answered_at`. `(request_id, user_id)` 는 유일하다. 수락해서 만든 일정은 `events.recip_id` 로 이 행을 가리킨다. 리비전 `f2b6d8c04e31` |
| events_suggestions | schedule | 미리 저장해 두는 추천(사람마다 따로). `group_id`·`user_id`·`title`·`place`·`kind`·`start_date`·`status`(1 제안·2 확정·3 버림)·`created_at`·`confirmed_at`. 시간·메모는 없다. `(group_id, user_id, status)` 인덱스. 일정을 만들면 `events.suggestion_id` 로 연결한다. 리비전 `a3c7e9d15f42` |
| expenses | billing | 공동 지출(제목, 금액, 날짜, 분류, 낸 사람, 나눌 사람 `split_among`, 정산 대상 태그 `target_tag`: parents/children/all/custom, 정산하기 시각·사람 `settled_at`·`settled_by`). 삭제는 `deleted_at` 소프트 삭제. 구독 항목으로 만든 지출이면 `subscription_id`(같은 달 중복 방지) |
| billing_settings | billing | 가족 그룹의 가계 설정: 정산 담당자(월말 알림 대상, 행이 없으면 그룹을 만든 사람)와 미성년 자녀 목록 `minor_ids` |
| settlement_payments | billing | '송금 완료'로 표시한 송금(월, 보낸 사람, 받은 사람, 금액). 송금 목록 자체는 매번 계산한다 |
| subscription_items | billing | OTT·통신비 항목(이름, 통신사 `carrier`, 사용자가 입력한 월 청구 금액 `monthly_fee`·결합 할인 금액 `discount_amount`, 결제일 `billing_day`)과 가족 할인 상태(check/available/active). 할인은 계산하지 않고 입력값만 저장한다. 삭제는 `deleted_at` 소프트 삭제. 구독료 지출용 결제한 사람 `payer_id`·나눌 사람 `split_among`(빈 목록이면 가족 전체) |
| allowances | billing | (이전 방식, 더는 쓰지 않음) 자녀별 월 용돈 예산. 장부(`allowance_entries`)로 복사 완료(719215db61ba). 제거는 `destructive-approved` 를 받는 후속 PR |
| allowance_uses | billing | (이전 방식, 더는 쓰지 않음) 월 예산의 사용 기록 |
| allowance_plans | billing | 자녀별 고정 용돈 주기(매주/매월, 금액, 자동/리마인드, 시작일). 자녀당 1개 |
| allowance_entries | billing | 용돈 장부(입금 credit·사용 use, 취소는 `voided_at`). 주기 입금은 `plan_due_date`로 같은 지급일 중복 방지(unique) |
| allowance_requests | billing | 자녀의 용돈 요청(금액, 사유, 상태 pending/approved/rejected/cancelled, 처리한 사람, 승인 금액, 승인으로 생긴 장부 줄 `entry_id`) |
| location_consent_events | shared | (돌봄 위치 기능을 지워 새 기록은 없음) 위치 공유 동의·철회 이력(사용자, 동의 여부, 경로, 시각). 좌표 없음 |
| photos | ai_assistant | 앱이 올린 사진(파일은 `DATA_DIR/photos`에 저장) |
| knowledge_items | ai_assistant/knowledge | 전처리가 넘긴 기록 한 건(분류 이름, 제목, 마크다운 전체, 원본 경로, 날짜, 민감도) |
| knowledge_chunks | ai_assistant/knowledge | 기록을 쪽·슬라이드·길이로 자른 조각과 임베딩 벡터(PostgreSQL 은 pgvector `vector(384)` + 코사인 HNSW 인덱스, SQLite 는 JSON). Alembic 리비전 c3a9f21d7e54 |

| ops_request_metrics | ops_admin | 운영 관리자 페이지용 요청 지표 집계. 구간 시작 `bucket_start`(기본 5분), `method`, 경로 패턴 `route`(`/items/{id}` 또는 `unmatched`), 상태코드 구분 `status_class`(2xx~5xx)별 요청 수·지연 시간 합·최댓값. 기본키는 앞의 네 컬럼이라 인스턴스가 여러 개여도 같은 행에 더해진다. 보관 90일(기본, `OPS_METRICS_RETENTION_DAYS`). URL 원문·본문·쿼리·헤더·사용자·가족 id 를 담는 컬럼이 없다. 기본 꺼짐(`OPS_METRICS_ENABLED`). Alembic 리비전 fcf5ce5e68e1 |

모든 가족 기능 테이블은 `group_id`로 가족 그룹을 구분하고, 다른 그룹의 데이터는 볼 수 없다. 단 `ops_request_metrics`는 가족 데이터가 아닌 서버 지표라 `group_id`가 없다.

"(PR 4-A, 스키마만)"로 표시한 컬럼·테이블은 통합 인증·가족 구성원 기능(`docs/requirements/family-group.md`)을 위한 스키마만 미리 만든 것이고, 이를 채우는 회원가입/로그인/소셜 연동/초대 승인 API는 PR 4-B~4-F에서 추가된다 — 지금은 기존 API 동작이 바뀌지 않는다.
