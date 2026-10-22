import os

import pytest
from sqlalchemy import create_engine, text

PG_URL = os.environ.get("PGVECTOR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="PGVECTOR_TEST_DATABASE_URL 이 설정되지 않음 (docker compose 의 Postgres 가 필요)",
)


def test_pgvector_extension_and_similarity():
    """pgvector 확장이 켜져 있고, 벡터 유사도 연산이 동작하는지 확인한다 (TEMP TABLE 만 사용)."""
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        extension_exists = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
        assert extension_exists is not None

        conn.execute(text("CREATE TEMP TABLE pgvector_smoke (id int, embedding vector(3))"))
        conn.execute(
            text(
                "INSERT INTO pgvector_smoke (id, embedding) VALUES "
                "(1, '[1,0,0]'), (2, '[0,1,0]'), (3, '[0.9,0.1,0]')"
            )
        )

        nearest_id = conn.execute(
            text(
                "SELECT id FROM pgvector_smoke WHERE id != 1 "
                "ORDER BY embedding <-> (SELECT embedding FROM pgvector_smoke WHERE id = 1) "
                "LIMIT 1"
            )
        ).scalar()
        assert nearest_id == 3
    engine.dispose()
