"""문서함 핵심 흐름을 PostgreSQL 16 + pgvector(최신 Alembic head)에서 처음부터 끝까지 잇는다(T30).

가족방에 문서 사진을 올림 → 문서함 자동 등록(항목·벡터 조각) → 가족 구성원의 검색에 나옴(다른 가족에는 안 나옴)
→ 메시지를 지우면 검색에서 사라지고 항목·조각 줄도 사라짐 → 다시 올린 뒤 가족을 지우면(마지막 구성원이 나감) 모든 줄이 지워짐.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
외부 AI 는 부르지 않는다: 가짜 OCR(정해 둔 글자 줄)과 해시 임베더(384칸)만 쓴다.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.features.ai_assistant import files, library
from app.features.ai_assistant.knowledge import embedding
from app.features.ai_assistant.knowledge.models import EMBED_DIM
from app.features.ai_assistant.tests.test_chat_library_photos import (
    NOTICE_LINES,
    ScriptedOcr,
    _send_photo,
)
from app.features.family_chat import file_service, photo_service
from app.main import app
from app.shared import db as shared_db
from app.shared.config import settings
from tests.test_join_pg_e2e import account
from tests.test_schema_gate_pg_e2e import admin, create_db, migrate, pg16, url  # noqa: F401
from tests.test_signup_pg_e2e import rows
from tests.test_weekly_news_pg_e2e import _family

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"
QUERY = "현장체험학습"


class Hashing384(embedding.HashingEmbedder):
    """vector(384) 칸에 맞는 길이로 맞춘 시험용 임베더(외부 모델·인터넷 없음)."""

    dim = EMBED_DIM

    def __init__(self) -> None:
        self.name = "hashing-384-test"


@pytest.fixture
def pg_flow(pg16, monkeypatch, tmp_path):  # noqa: F811
    create_db(pg16)
    migrate(pg16, "head")
    engine = create_engine(url(pg16), pool_size=12)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as db:
            yield db

    # 서버 코드가 요청 밖(백그라운드)에서 직접 여는 세션도 같은 PostgreSQL 을 보게 한다.
    for module in (shared_db, files, library):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_pending.clear()
    library._photo_inflight.clear()
    file_service.upload_limiter._failures.clear()
    photo_service.upload_limiter._failures.clear()
    photo_service.library_limiter._failures.clear()
    old_embedder = embedding._embedder  # 시험 뒤 원래 상태(아직 안 읽은 상태 포함)로 되돌린다
    old_processors = files.processors
    try:
        embedding.set_embedder(Hashing384())
        files.processors = files.Processors(ocr=ScriptedOcr(NOTICE_LINES))
        app.dependency_overrides[shared_db.get_db] = override
        with TestClient(app) as client:
            yield client, pg16
    finally:
        app.dependency_overrides.pop(shared_db.get_db, None)
        files.processors = old_processors
        embedding.set_embedder(old_embedder)
        engine.dispose()


def _library_rows(pg, group_id):
    """(항목 수, 벡터 조각 수, 벡터가 빈 조각 수)."""
    (items,) = rows(pg, "SELECT count(*) FROM knowledge_items WHERE group_id = %s", group_id)[0]
    (chunks,) = rows(pg, "SELECT count(*) FROM knowledge_chunks WHERE group_id = %s", group_id)[0]
    (empty,) = rows(
        pg,
        "SELECT count(*) FROM knowledge_chunks WHERE group_id = %s AND embedding IS NULL",
        group_id,
    )[0]
    return items, chunks, empty


def _search(client, headers):
    r = client.post("/ai-assistant/knowledge/search", json={"query": QUERY}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["hits"]


def test_document_photo_flows_from_upload_to_search_to_delete_on_postgres(pg_flow):
    client, pg = pg_flow
    owner, guest, group = _family(client)
    gid = group["id"]
    stranger = account(client, "other_park")  # 다른 가족: 같은 문서가 보이면 안 된다
    r = client.post(f"{P}/groups", json={"name": "남의 가족"}, headers=stranger)
    assert r.status_code in (200, 201), r.text

    # 1) 문서 사진을 올리면 등록되고 벡터 조각이 만들어진다
    msg = _send_photo(client, owner)
    items, chunks, empty = _library_rows(pg, gid)
    assert items == 1 and chunks >= 1 and empty == 0
    ((attachment,),) = rows(
        pg, "SELECT source_attachment_id FROM knowledge_items WHERE group_id = %s", gid
    )
    assert attachment == msg["attachment"]["id"]

    # 2) 가족 구성원은 찾고, 다른 가족은 못 찾는다
    hits = _search(client, guest)
    assert hits and "가정통신문" in (hits[0]["title"] + hits[0]["snippet"] + hits[0]["kind_label"])
    assert _search(client, stranger) == []

    # 3) 메시지를 지우면 검색에서 사라지고 줄도 사라진다
    r = client.delete(f"/family-chat/messages/{msg['id']}", headers=owner)
    assert r.status_code in (200, 204), r.text
    assert _library_rows(pg, gid) == (0, 0, 0)
    assert _search(client, guest) == []

    # 4) 다시 올린 뒤 가족을 지우면(모두 나감) 이 가족의 줄이 하나도 남지 않는다
    _send_photo(client, owner)
    assert _library_rows(pg, gid)[0] == 1
    for who in (guest, owner):
        r = client.post(f"{P}/groups/me/leave", headers=who)
        assert r.status_code == 204, r.text
    assert _library_rows(pg, gid) == (0, 0, 0)
    for table in ("messages", "message_attachments", "knowledge_items", "knowledge_chunks"):
        ((n,),) = rows(pg, f"SELECT count(*) FROM {table} WHERE group_id = %s", gid)
        assert n == 0, table
    ((n,),) = rows(pg, "SELECT count(*) FROM groups WHERE id = %s", gid)
    assert n == 0, "groups"
