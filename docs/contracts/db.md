# DB 구조

서버는 SQLAlchemy 2 로 접근한다(`apps/api/app/shared/db.py`).
로컬 기본값은 SQLite(`apps/api/data/gabee.db`) — 테스트와 로컬 간단 실행용으로 `init_db()`가 시작 시 `create_all()`로 테이블을 만든다.
docker compose 의 개발용 PostgreSQL(`pgvector/pgvector:pg16` 이미지, `pgvector` 확장 포함)은 **Alembic**(`apps/api/alembic/`)이 스키마를 전담한다 — `init_db()`는 PostgreSQL에서 테이블을 만들거나 바꾸지 않고, `alembic_version`이 최신인지만 확인한다(아니면 기동을 막는 에러). `supabase/migrations`는 더 이상 스키마 변경에 쓰지 않는다. 새 마이그레이션 만드는 법은 [README.md](../../README.md) 참고. 테이블을 바꾸면 이 문서도 갱신한다.

| 테이블 | 기능 | 설명 |
|---|---|---|
| users | family_group | 이름, 역할(parent/child/other), 로그인 토큰, 현재 가족 그룹 |
| groups | family_group | 가족 그룹(이름, 소유자) |
| group_members | family_group | 그룹 구성원(그룹+사용자가 기본키) |
| invites | family_group | 초대 코드(그룹, 만든 사람, 철회 여부) |
| messages | family_chat | 그룹 대화 메시지 |
| events | schedule | 가족 일정(제목, 시작 시각, 상태 pending/confirmed, 출처) |
| expenses | billing | 공동 지출(제목, 금액, 날짜, 분류, 낸 사람, 나눌 사람 `split_among`). 삭제는 `deleted_at` 소프트 삭제 |
| settlement_payments | billing | '송금 완료'로 표시한 송금(월, 보낸 사람, 받은 사람, 금액). 송금 목록 자체는 매번 계산한다 |
| subscription_items | billing | OTT·통신비 가족 할인 상태(check/available/active). 금액은 저장하지 않는다 |
| allowances | billing | 자녀별 월 용돈 예산 |
| allowance_uses | billing | 용돈 사용 기록 |
| care_records | care | 돌봄 기록(대상, 종류, 값, 날짜). 같은 그룹·대상·종류·날짜는 하나만 둔다 |
| care_items | care | 데일리 체크 항목(기록 방식, 목표, 예정 시각, 끼니). 삭제는 `deleted_at` 소프트 삭제 |
| care_entries | care | 항목의 하루 기록. 같은 항목·날짜는 하나만 둔다 |
| photos | ai_assistant | 앱이 올린 사진(파일은 `DATA_DIR/photos`에 저장) |

모든 기능 테이블은 `group_id`로 가족 그룹을 구분하고, 다른 그룹의 데이터는 볼 수 없다.

TODO: 원본의 pgvector 테이블(문서·사진 임베딩) — 실제 추가 시 `pgvector-python` 의존성과 `Vector` 컬럼 타입, 새 Alembic 리비전을 함께 추가한다.
