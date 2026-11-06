"""가족 문서함에 새 문서가 올라오면(가비가 읽어 저장한 뒤) 올린 사람을 뺀 가족에게 고정 문구 알림이 남는다. 민감 문서·읽기 실패는 알리지 않는다."""

from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.features.ai_assistant import files
from app.shared.db import SessionLocal
from app.shared.notifications import Notification


@pytest.fixture
def home(client, family):
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    return family


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _run(monkeypatch, group_id, user_id, *, sensitivity="normal", status="ok"):
    result = SimpleNamespace(quality=SimpleNamespace(status=status))
    monkeypatch.setattr(files.ingest_service, "ingest_file", lambda *a, **k: result)
    monkeypatch.setattr(
        files.from_ingest,
        "to_item",
        lambda r: {
            "kind_label": "가정통신문",
            "title": "현장체험학습 안내",
            "body_md": "내용",
            "sensitivity": sensitivity,
        },
    )
    monkeypatch.setattr(files.from_ingest, "needs_review", lambda r: False)
    files.process_file("doc123456789", group_id, user_id, b"x", "a.pdf")


def _rows():
    with SessionLocal() as db:
        return list(db.scalars(select(Notification).where(Notification.event == "document_added")))


def test_new_document_notifies_the_family_except_the_uploader(client, home, monkeypatch):
    a, b, group = home
    _run(monkeypatch, group["id"], _me(client, a))
    rows = _rows()
    assert [r.user_id for r in rows] == [_me(client, b)]
    n = rows[0]
    assert n.kind == "ai_record" and n.title == "가족 문서함에 새 문서가 올라왔어요"
    assert "현장체험" not in (n.title + (n.body or ""))  # 문서 제목·내용을 문구에 담지 않는다
    assert n.target_type == "knowledge_item" and n.target_id == "doc123456789"


def test_sensitive_document_is_not_announced(client, home, monkeypatch):
    a, _, group = home
    _run(monkeypatch, group["id"], _me(client, a), sensitivity="sensitive")
    assert _rows() == []


def test_a_failing_announcement_does_not_turn_a_saved_document_into_a_failed_upload(
    client, home, monkeypatch
):
    a, _, group = home
    statuses = []
    monkeypatch.setattr(files.repo, "set_status", lambda db, pid, status: statuses.append(status))

    def boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(files, "_notify_document", boom)
    _run(monkeypatch, group["id"], _me(client, a))
    assert statuses == ["analyzed"]  # 문서는 저장됐으니 알림이 터져도 처리 실패로 바뀌지 않는다


def test_failed_reading_is_not_announced(client, home, monkeypatch):
    a, _, group = home
    _run(monkeypatch, group["id"], _me(client, a), status="failed")
    assert _rows() == []
