"""PostgreSQL + pgvector 에서 저장·검색이 되는지 확인한다(개인 로컬 DB 전용).

`PGVECTOR_TEST_DATABASE_URL` 이 없으면 건너뛴다. 공용 DB 를 지키려고 이미 knowledge 테이블이 있는 DB 에서는
시작하지 않고, 이 테스트가 만든 테이블만 끝에 지운다. 실행 예:
  PGVECTOR_TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@127.0.0.1:5433/gabee pytest -k pgvector
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.features.ai_assistant.knowledge import embedding, service
from app.features.ai_assistant.knowledge.models import EMBED_DIM, KnowledgeChunk, KnowledgeItem
from app.shared.db import Base

PG_URL = os.environ.get("PGVECTOR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="PGVECTOR_TEST_DATABASE_URL 이 설정되지 않음 (개인 로컬 Postgres 필요)"
)


class Hashing384(embedding.HashingEmbedder):
    """vector(384) 칸에 맞는 길이로 맞춘 테스트용 임베더."""

    dim = EMBED_DIM

    def __init__(self) -> None:
        self.name = "hashing-384-test"


def test_postgres_vector_search_roundtrip():
    engine = create_engine(PG_URL)
    tables = [KnowledgeItem.__table__, KnowledgeChunk.__table__]
    existing = {t.name for t in tables} & set(inspect(engine).get_table_names())
    assert not existing, (
        f"이미 {sorted(existing)} 테이블이 있어요. 비어 있는 개인 DB 에서만 실행하세요"
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine, tables=tables)
    old = embedding.get_embedder()
    embedding.set_embedder(Hashing384())
    try:
        with sessionmaker(bind=engine)() as db:
            for title, kind, body, day in [
                (
                    "10월 전기요금",
                    "전기요금 고지서",
                    "# 10월 전기요금\n분류: 전기요금 고지서\n- 48,200원",
                    date(2026, 10, 1),
                ),
                (
                    "10월 수도요금",
                    "수도요금 고지서",
                    "# 10월 수도요금\n분류: 수도요금 고지서\n- 23,400원",
                    date(2026, 10, 3),
                ),
            ]:
                service.ingest(
                    db, "g1", "u1", kind_label=kind, title=title, body_md=body, occurred_on=day
                )
            service.ingest(
                db,
                "g2",
                "u2",
                kind_label="전기요금 고지서",
                title="남의 가족",
                body_md="# 남의 가족\n분류: 전기요금 고지서",
            )

            hits = service.search(db, "g1", "전기요금")
            assert hits[0].item.title == "10월 전기요금" and 0 < hits[0].score <= 1
            assert all(h.item.title != "남의 가족" for h in hits)  # 그룹 격리
            only_water = service.search(db, "g1", "요금", kind_label="수도요금 고지서")
            assert [h.item.title for h in only_water] == ["10월 수도요금"]
            assert (
                service.search(db, "g1", "요금", date_from=date(2026, 10, 2))[0].item.title
                == "10월 수도요금"
            )
    finally:
        embedding.set_embedder(old)
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()
