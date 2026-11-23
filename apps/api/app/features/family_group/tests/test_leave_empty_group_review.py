"""혼자인 소유자가 가족을 나갈 때 데이터 삭제의 범위·잠금(Opus 리뷰 반영): 다른 가족 데이터를 건드리지 않고, 빠지는 것 없이 지운다."""

import pytest
from sqlalchemy import event, select

import app.main  # noqa: F401  모든 모델을 불러온다
from app.shared.config import settings
from app.shared.db import Base, SessionLocal

from .test_leave import LEAVE
from .test_leave_empty_group import _solo


def test_bomb_turn_condition_uses_the_whole_composite_key():
    """폭탄방 말 기록은 (play_id, round_no) 두 열 키로 라운드를 가리킨다.
    열마다 따로 OR 로 묶으면 다른 가족의 같은 라운드 번호 기록까지 지워진다."""
    from app.shared import group_purge

    table = Base.metadata.tables["play_bomb_turns"]
    names = {t.name for t in group_purge._scoped_tables()}
    sql = str(group_purge._condition(table, "g1", names))
    assert "play_bomb_turns.play_id, play_bomb_turns.round_no" in sql  # 두 열을 한 쌍으로 비교한다
    assert "play_bomb_turns.round_no IN" not in sql  # 열 하나짜리 비교가 따로 없다


def test_a_support_ticket_survives_with_its_group_cleared(client):
    owner, _, _ = _solo(client)
    r = client.post(
        "/support/tickets", json={"kind": "inquiry", "title": "문의", "body": "내용"}, headers=owner
    )
    assert r.status_code == 201, r.text
    assert client.post(LEAVE, headers=owner).status_code == 204
    with SessionLocal() as db:
        tickets = Base.metadata.tables["support_tickets"]
        rows = db.execute(select(tickets.c.id, tickets.c.group_id)).all()
        assert [row.group_id for row in rows] == [
            None
        ]  # 문의는 남고, 지워진 가족을 가리키지 않는다


def test_orphan_tables_without_foreign_keys_are_removed_too(client):
    """allowance_uses 는 allowance_id 열만 있고 외래 키가 없어도 가족의 용돈 줄과 함께 지운다."""
    from app.features.billing.models import Allowance, AllowanceUse

    owner, owner_id, group = _solo(client)
    with SessionLocal() as db:
        db.add(
            Allowance(
                id="al1", group_id=group["id"], child_id=owner_id, month="2026-11", budget=1000
            )
        )
        db.add(AllowanceUse(id="au1", allowance_id="al1", amount=100, memo="", date="2026-11-01"))
        db.add(Allowance(id="al2", group_id="other_group", child_id="x", month="2026-11", budget=1))
        db.add(AllowanceUse(id="au2", allowance_id="al2", amount=1, memo="", date="2026-11-01"))
        db.commit()
    assert client.post(LEAVE, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(AllowanceUse, "au1") is None
        assert db.get(AllowanceUse, "au2") is not None  # 다른 가족의 것은 그대로
        assert db.get(Allowance, "al2") is not None


def test_other_stored_files_are_removed_but_other_groups_files_stay(client, tmp_path, monkeypatch):
    from app.features.ai_assistant.models import Photo

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "raw_dir", "")
    owner, owner_id, group = _solo(client)
    gid = group["id"]

    def put(rel):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    mine = [
        put("photos/ph1.jpg"),
        put(f"raw/{gid}/ab/{'a' * 64}.pdf"),
        put(f"play/drawings/{gid}/d1.png"),
        put(f"play/photos/{gid}/p1.jpg"),
    ]
    others = [
        put("photos/ph2.jpg"),
        put("raw/other_group/ab/x.pdf"),
        put("play/drawings/other_group/d.png"),
    ]
    with SessionLocal() as db:
        db.add(
            Photo(
                id="ph1",
                group_id=gid,
                uploaded_by=owner_id,
                filename="a.jpg",
                content_type="image/jpeg",
                size=1,
            )
        )
        db.add(
            Photo(
                id="ph2",
                group_id="other_group",
                uploaded_by="x",
                filename="b.jpg",
                content_type="image/jpeg",
                size=1,
            )
        )
        db.commit()
    assert client.post(LEAVE, headers=owner).status_code == 204
    assert [p.exists() for p in mine] == [False] * 4
    assert [p.exists() for p in others] == [True] * 3


def test_the_group_row_is_locked_before_members_are_counted(client, monkeypatch):
    """동시에 들어온 가입과 겹치지 않게, 구성원 수를 세기 전에 groups 줄을 잠근다."""
    from app.features.family_group import profile_repository as prepo

    owner, _, _ = _solo(client)
    calls: list[str] = []
    real_lock, real_count = prepo.lock_group, prepo.count_members

    def lock(db, gid):
        calls.append("lock")
        return real_lock(db, gid)

    def count(db, gid):
        calls.append("count")
        return real_count(db, gid)

    monkeypatch.setattr(prepo, "lock_group", lock)
    monkeypatch.setattr(prepo, "count_members", count)
    assert client.post(LEAVE, headers=owner).status_code == 204
    assert calls[:2] == ["lock", "count"]


@pytest.fixture
def enforce_foreign_keys():
    """SQLite 는 기본으로 외래 키를 검사하지 않아 삭제 순서 오류를 숨긴다. 이 시험 동안만 검사를 켠다(PostgreSQL 과 같게)."""
    from app.shared.db import engine

    def on_connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", on_connect)
    engine.dispose()
    yield
    event.remove(engine, "connect", on_connect)
    engine.dispose()


def test_leaving_with_chat_data_passes_foreign_key_checks(
    client, enforce_foreign_keys, tmp_path, monkeypatch
):
    """채팅 메시지·사진·반응·고정이 있는 가족을 지워도 외래 키 위반이 나지 않는다(자식부터 지우는 순서)."""
    import io

    from PIL import Image

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    owner, _, group = _solo(client)
    msg = client.post("/family-chat/messages", json={"text": "안녕"}, headers=owner)
    assert msg.status_code == 201, msg.text
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (9, 9, 9)).save(out, format="JPEG")
    photo = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=owner,
    )
    assert photo.status_code == 201, photo.text
    react = client.put(
        f"/family-chat/messages/{msg.json()['id']}/reaction", json={"emoji": "👍"}, headers=owner
    )
    assert react.status_code in (200, 204), react.text
    assert client.post(LEAVE, headers=owner).status_code == 204
    with SessionLocal() as db:
        from app.features.family_group.models import Group

        assert db.get(Group, group["id"]) is None


def test_a_document_still_being_read_when_the_family_is_deleted_leaves_nothing(
    client, tmp_path, monkeypatch
):
    """문서를 읽는 중에 가족이 지워지면, 읽기가 끝난 뒤 지워진 가족의 기록·사진 줄·원본이 새로 남지 않는다."""
    from app.features.ai_assistant import files, service
    from app.features.ai_assistant.knowledge.models import KnowledgeItem
    from app.features.ai_assistant.models import Photo

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "raw_dir", "")
    owner, owner_id, group = _solo(client)
    gid = group["id"]
    lines = [f"{i}월 가족 모임 안내 장소 우리 집 준비물 음식" for i in range(1, 9)]
    data = "\n".join(lines).encode()
    with SessionLocal() as db:
        photo = service.receive_file(db, gid, owner_id, "notice.txt", "text/plain", data)
        photo_id = photo.id
    assert (
        client.post(LEAVE, headers=owner).status_code == 204
    )  # 읽기가 끝나기 전에 가족이 지워진다
    files.process_file(
        photo_id, gid, owner_id, data, "notice.txt", purpose=files.Purpose.MAIN_AI_DIRECT_UPLOAD
    )
    with SessionLocal() as db:
        assert db.scalar(select(KnowledgeItem.id).where(KnowledgeItem.group_id == gid)) is None
        assert db.scalar(select(Photo.id).where(Photo.group_id == gid)) is None
    leftover = [f for f in (tmp_path / "raw" / gid).rglob("*") if f.is_file()]
    assert leftover == []  # 빈 폴더는 남아도 파일은 하나도 남지 않는다
