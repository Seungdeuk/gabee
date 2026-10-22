# DB 구조

서버는 SQLAlchemy 2 로 접근한다(`apps/api/app/shared/db.py`).
로컬 기본값은 SQLite(`apps/api/data/gabee.db`) — 테스트와 로컬 간단 실행용으로 `init_db()`가 시작 시 `create_all()`로 테이블을 만든다.
docker compose 의 개발용 PostgreSQL(`pgvector/pgvector:pg16` 이미지, `pgvector` 확장 포함)은 **Alembic**(`apps/api/alembic/`)이 스키마를 전담한다 — `init_db()`는 PostgreSQL에서 테이블을 만들거나 바꾸지 않는다. DB가 코드보다 뒤처져도 서버는 시작하고, 기능별로 실제 스키마(테이블·컬럼)를 점검해 준비되지 않은 기능의 API만 503을 돌려준다(`GET /health/db`로 상태 확인, [ADR 0006](../adr/0006-schema-gate-degraded-start.md)). `supabase/migrations`는 더 이상 스키마 변경에 쓰지 않는다. 새 마이그레이션 만드는 법은 [README.md](../../README.md) 참고. 테이블을 바꾸면 이 문서도 갱신한다.

개인 로컬 Docker DB와 팀 공용 DB의 구분, 계정 역할(`gabee_app`/`gabee_migrator`)은 [README.md](../../README.md)의 "팀 공용 PostgreSQL 에 연결하기"와 [docs/adr/0005-shared-postgres-env.md](../adr/0005-shared-postgres-env.md) 참고.

| 테이블 | 기능 | 설명 |
|---|---|---|
| users | family_group | 이름, 역할(parent/child/other), 로그인 토큰, 현재 가족 그룹, (PR 4-A, 스키마만) `login_id`/`email`/`email_verified_at`/`password_hash` — 전부 nullable, 익명 계정은 전부 NULL. 위치 공유 동의 시각 `location_consent_at`(없으면 미동의) |
| groups | family_group | 가족 그룹(이름, 소유자) |
| group_members | family_group | 그룹 구성원(그룹+사용자가 기본키). (PR 4-A, 스키마만) `role`(owner/admin/member, 그룹당 owner 최대 1명을 부분 유니크 인덱스로 강제), `family_relation`/`family_relation_detail`/`display_name` |
| invites | family_group | 초대 코드(그룹, 만든 사람, 철회 여부). (PR 4-A, 스키마만) 서로게이트 `id`(UNIQUE, join_requests/invite_attempts 가 참조), `expires_at`/`max_uses`/`use_count` |
| social_accounts | family_group | (PR 4-A, 스키마만) Google/Kakao 소셜 로그인 연동(`provider`+`provider_uid` 유니크) |
| refresh_tokens | family_group | (PR 4-A, 스키마만) 로그인 세션(토큰 원문 대신 `token_hash`만 저장) |
| password_resets | family_group | (PR 4-A, 스키마만) 비밀번호 재설정 토큰(해시만 저장) |
| email_verifications | family_group | (PR 4-A, 스키마만) 이메일 인증 토큰(해시만 저장) |
| member_nicknames | family_group | (PR 4-A, 스키마만) 구성원이 다른 구성원에게 붙이는 개인별 별명·메모. `(group_id,owner_user_id)`/`(group_id,target_user_id)` 둘 다 `group_members`를 참조하는 복합 FK — 실제 그룹 멤버만 작성자/대상이 될 수 있다 |
| join_requests | family_group | (PR 4-A, 스키마만) 초대코드로 참여 신청 후 관리자 승인 대기(`status` pending/approved/rejected). 같은 `(group_id,user_id)`로 pending 중복 금지(부분 유니크) |
| invite_attempts | family_group | (PR 4-A, 스키마만) 초대코드 레이트리밋용 시도 기록(ip/user_id/invite_id, 성공 여부) — 코드 원문·해시는 저장하지 않는다 |
| messages | family_chat | 그룹 대화 메시지 |
| events | schedule | 가족 일정(제목, 시작 시각, 상태 pending/confirmed, 출처) |
| expenses | billing | 공동 지출(제목, 금액, 날짜, 분류, 낸 사람, 나눌 사람 `split_among`, 정산 대상 태그 `target_tag`: parents/children/all/custom, 정산하기 시각·사람 `settled_at`·`settled_by`). 삭제는 `deleted_at` 소프트 삭제 |
| billing_settings | billing | 가족 그룹의 가계 설정: 정산 담당자(월말 알림 대상, 행이 없으면 그룹을 만든 사람)와 미성년 자녀 목록 `minor_ids` |
| settlement_payments | billing | '송금 완료'로 표시한 송금(월, 보낸 사람, 받은 사람, 금액). 송금 목록 자체는 매번 계산한다 |
| subscription_items | billing | OTT·통신비 가족 할인 상태(check/available/active). 금액은 저장하지 않는다 |
| allowances | billing | 자녀별 월 용돈 예산 |
| allowance_uses | billing | 용돈 사용 기록 |
| care_records | care | 돌봄 기록(대상, 종류, 값, 날짜). 같은 그룹·대상·종류·날짜는 하나만 둔다 |
| care_locations | care | 동의한 사람이 보낸 위치(좌표·정확도·잰 시각). 7일이 지나면 삭제, 동의 철회 시 즉시 삭제. 좌표는 로그에 남기지 않는다 |
| location_consent_events | shared | 위치 공유 동의·철회 이력(사용자, 동의 여부, 경로, 시각). 좌표 없음 |
| care_items | care | 데일리 체크 항목(기록 방식, 목표, 예정 시각, 끼니). 삭제는 `deleted_at` 소프트 삭제 |
| care_entries | care | 항목의 하루 기록. 같은 항목·날짜는 하나만 둔다 |
| photos | ai_assistant | 앱이 올린 사진(파일은 `DATA_DIR/photos`에 저장) |

모든 기능 테이블은 `group_id`로 가족 그룹을 구분하고, 다른 그룹의 데이터는 볼 수 없다.

"(PR 4-A, 스키마만)"로 표시한 컬럼·테이블은 통합 인증·가족 구성원 기능(`docs/requirements/family-group.md`)을 위한 스키마만 미리 만든 것이고, 이를 채우는 회원가입/로그인/소셜 연동/초대 승인 API는 PR 4-B~4-F에서 추가된다 — 지금은 기존 API 동작이 바뀌지 않는다.

TODO: 원본의 pgvector 테이블(문서·사진 임베딩) — 실제 추가 시 `pgvector-python` 의존성과 `Vector` 컬럼 타입, 새 Alembic 리비전을 함께 추가한다.
