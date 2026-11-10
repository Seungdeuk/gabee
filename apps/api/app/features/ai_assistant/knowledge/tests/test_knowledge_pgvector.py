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


class FakeOnnx384(embedding.OnnxE5Embedder):
    """isinstance(OnnxE5Embedder) 를 통과하는 시험용 가짜(모델 파일 없이 384차원 해시 벡터)."""

    dim = EMBED_DIM

    def __init__(self) -> None:
        self.name = "onnx-fake-384"
        self._inner = Hashing384()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_passages(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)


def test_postgres_reindex_updates_vector_and_model(monkeypatch, capsys):
    """옛 모델 이름 조각 → 점검 스크립트 → 일부 재계산 → reindex(배치) → vector(384)·모델 이름 갱신 → 검색됨."""
    from app.features.ai_assistant.knowledge import repository as repo
    from scripts import reindex_embeddings

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
    new = FakeOnnx384()
    embedding.set_embedder(new)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(
        reindex_embeddings, "SessionLocal", session_factory
    )  # 스크립트도 이 DB 를 쓴다
    try:
        with session_factory() as db:
            for i in range(5):
                item = KnowledgeItem(
                    group_id="g1",
                    created_by="u1",
                    kind_label="전기요금 고지서",
                    title=f"전기요금 {i}",
                    body_md="x",
                )
                db.add(item)
                db.flush()
                db.add(
                    KnowledgeChunk(
                        item_id=item.id,
                        group_id="g1",
                        seq=0,
                        text=f"전기요금 고지서 {i}월 청구금액",
                        embedding=[0.0] * EMBED_DIM,
                        embedding_model="onnx-old-name",
                    )
                )
            db.commit()
            assert repo.count_by_model(db) == {"onnx-old-name": 5}
            assert repo.count_stale(db, new.name) == 5
            assert repo.count_items_missing_model(db, new.name) == 5
            item_ids = [i for (i,) in db.execute(text("SELECT id FROM knowledge_items")).all()]

        # 스크립트: --check 는 읽기 전용, --apply --yes --limit 3 은 3개만 다시 만든다. 출력에 본문·id 가 없다.
        assert reindex_embeddings.main(["--check"]) == 0
        assert (
            reindex_embeddings.main(["--apply", "--yes", "--limit", "3", "--batch-size", "2"]) == 0
        )
        out = capsys.readouterr().out
        assert "reindex 3/3 (100%)" in out
        assert "전기요금 고지서" not in out and not any(i in out for i in item_ids)

        with session_factory() as db:
            assert repo.count_by_model(db) == {"onnx-old-name": 2, new.name: 3}
            assert service.reindex(db, batch_size=2) == 2  # 남은 것만

            rows = db.execute(
                text("SELECT embedding_model, vector_dims(embedding) FROM knowledge_chunks")
            ).all()
            assert {tuple(r) for r in rows} == {(new.name, EMBED_DIM)}
            assert repo.count_by_model(db) == {new.name: 5}
            assert repo.count_items_missing_model(db, new.name) == 0
            hits = repo.search_chunks(
                db, "g1", new.name, new.embed_query("전기요금"), None, None, None, True
            )
            assert len(hits) == 5
            assert service.reindex(db, batch_size=2) == 0  # 다시 해도 할 일이 없다
    finally:
        embedding.set_embedder(old)
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()
