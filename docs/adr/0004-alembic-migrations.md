# 0004. Alembic 으로 스키마 마이그레이션을 일원화한다

- 날짜: 2026-10-22
- 결정: `apps/api/alembic/`에 Alembic을 도입하고, PostgreSQL 스키마 변경의 유일한 수단으로 삼는다. `supabase/migrations`는 더 이상 스키마 변경에 쓰지 않는다(비워둔 채 유지). `apps/api/app/shared/db.py`의 `init_db()`는 더 이상 PostgreSQL에서 `create_all()`이나 `CREATE EXTENSION`을 직접 실행하지 않고, `alembic_version`이 최신 리비전인지만 확인한다(아니면 명확한 오류로 기동을 막는다). SQLite(테스트)는 그대로 `create_all()`을 쓴다 — 테스트는 Alembic을 거치지 않는다.
- 이유: 두 가지 스키마 변경 경로(Alembic과 Supabase SQL)를 동시에 두면 어느 쪽이 진실인지 헷갈리고, 서버가 시작할 때마다 몰래 스키마를 바꾸는 것(`create_all`/자동 `ALTER`)은 운영 DB에서 위험하다. ADR 0003에서 이미 "PR 2에서 Alembic으로 이전" 하기로 예고했다.
- 초기 리비전(`alembic/versions/355a1a748ec5_initial_schema.py`): 기존 9개 테이블(`users`, `groups`, `group_members`, `invites`, `messages`, `events`, `expenses`, `care_records`, `photos`)을 `create_all()`이 만들던 것과 동일하게(PK/FK/unique/인덱스/nullable 그대로) 재현하고, PostgreSQL일 때 `CREATE EXTENSION IF NOT EXISTS vector`를 실행한다. 벡터 컬럼은 아직 추가하지 않았다(범위 밖).
- 기존 개발 DB 인수: 이미 `create_all()`로 9개 테이블이 만들어져 있던 로컬 개발 DB는, `apps/api/scripts/check_schema_matches_models.py`로 실제 스키마와 모델이 일치함을 먼저 확인한 뒤에만 `alembic stamp head`로 이력을 등록했다(테이블 재생성·데이터 삭제 없음).
- 영향: Docker 이미지(`apps/api/Dockerfile`)에 `alembic.ini`/`alembic/`을 포함해, `docker compose run --rm api alembic upgrade head`로 명시적으로 마이그레이션을 적용한다. `api` 서비스 기동 자체는 스키마를 바꾸지 않으며, 마이그레이션이 안 되어 있으면 기동 시 에러로 알려준다.
- 알려진 제약: Windows(cp949 로캘)에서 `alembic.ini`에 비-ASCII 문자가 있으면 `configparser`가 깨진다 — 이 파일은 ASCII만 쓴다.
- **(2026-10-22 갱신)** 위의 "마이그레이션이 최신이 아니면 오류로 기동을 막는다"는 [0006](0006-schema-gate-degraded-start.md)에서 "서버는 시작하고 스키마가 준비되지 않은 기능만 503"으로 대체됐다. Alembic 이 스키마 변경의 유일한 수단이라는 결정은 그대로다.
