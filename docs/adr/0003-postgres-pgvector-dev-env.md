# 0003. 개발용 PostgreSQL 에 pgvector 를 켠다 (기존 db 서비스를 그 자리에서 교체)

- 날짜: 2026-10-21
- 결정: `docker-compose.yml`의 기존 `db` 서비스 이미지를 `postgres:16` → `pgvector/pgvector:pg16`으로 바꾼다. 서비스명·볼륨명·포트는 그대로 두고(호스트 바인딩만 `127.0.0.1`로 좁힌다), 별도의 db 서비스를 새로 추가하지 않는다. `apps/api/app/shared/db.py`의 `init_db()`가 시작할 때 `CREATE EXTENSION IF NOT EXISTS vector`를 실행해 확장을 켠다.
- 이유: `pgvector/pgvector:pg16`은 `postgres:16`과 데이터 포맷이 같은 상위집합 이미지라 기존 볼륨의 데이터를 잃지 않고 이미지만 바꿀 수 있다. 별도 서비스/포트로 DB를 하나 더 두는 방안도 검토했지만, 실존하지 않는 충돌을 피하려고 DB를 이중으로 운영하는 것은 과설계이고, Docker Compose가 폴더명으로 볼륨/네트워크 이름을 접두사 처리하므로 다른 프로젝트와는 이미 자동으로 분리된다.
- 영향: 실제 벡터 컬럼을 가진 테이블이나 `pgvector-python` 의존성은 이번 PR에서 추가하지 않았다(기존 업무 테이블 변경 금지 범위). CI(`ci-check.yml`)는 건드리지 않았고, 새 pgvector 테스트(`apps/api/tests/test_pgvector.py`)는 `PGVECTOR_TEST_DATABASE_URL`이 없으면 자동 스킵된다.
- PR 2 인계: Alembic을 도입하면 `init_db()`의 수동 `CREATE EXTENSION`을 마이그레이션 파일(`supabase/migrations/*.sql` 또는 Alembic 리비전)로 옮겨야 한다. 실제 임베딩 테이블(문서·사진)을 추가할 때 `pgvector-python` 의존성과 `Vector` 컬럼 타입을 함께 추가한다.
