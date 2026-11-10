"""구성원이 소유자 혼자뿐인 가족은 소유자가 나갈 수 있고, 나가면 그 가족의 데이터가 모두 지워진다(되돌릴 수 없다).
구성원이 더 있으면 소유자는 여전히 나갈 수 없다."""

import io

import pytest
from PIL import Image
from sqlalchemy import func, select, text

import app.main  # noqa: F401  모든 모델을 불러온다(아래 전 테이블 점검용)
from app.features.family_group.models import Group, GroupMember, Invite, JoinRequest, User
from app.shared.config import settings
from app.shared.db import Base, SessionLocal

from .test_join_approval import P, account, create_group, join, new_code
from .test_leave import LEAVE, family

MSG = "/family-chat/messages"


def _solo(client):
    owner, owner_id = account(client, "mom_kim", "엄마")
    group = create_group(client, owner)
    return owner, owner_id, group


def _photo(client, headers) -> dict:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 200, 200)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]


def _counts(group_id: str) -> dict[str, int]:
    """group_id 열이 있는 모든 테이블에서 이 가족의 줄 수(0 이 아닌 것만)."""
    found: dict[str, int] = {}
    with SessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            if "group_id" not in table.c:
                continue
            n = db.scalar(
                select(func.count()).select_from(table).where(table.c.group_id == group_id)
            )
            if n:
                found[table.name] = n
    return found


def test_the_only_member_can_leave_and_the_group_disappears(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    owner, owner_id, group = _solo(client)
    assert client.post(MSG, json={"text": "안녕"}, headers=owner).status_code == 201
    attachment = _photo(client, owner)
    photo_files = list((tmp_path / "chat_photos").glob(f"{attachment['id']}*"))
    assert photo_files  # 사진 파일이 디스크에 있다
    assert _counts(group["id"])  # 지울 데이터가 있다

    r = client.post(LEAVE, headers=owner)
    assert r.status_code == 204, r.text

    assert _counts(group["id"]) == {}  # 어느 테이블에도 이 가족 줄이 남지 않는다
    assert not list((tmp_path / "chat_photos").glob(f"{attachment['id']}*"))  # 사진 파일도 지워진다
    with SessionLocal() as db:
        assert db.get(Group, group["id"]) is None
        assert db.get(User, owner_id) is not None  # 계정은 남는다
        assert db.get(User, owner_id).active_group_id is None


def test_pending_join_requests_and_invites_go_away_and_the_code_stops_working(client):
    owner, _, group = _solo(client)
    code = new_code(client, owner)
    client.put(f"{P}/groups/invites/settings", json={"auto_approve": False}, headers=owner)
    joiner, _ = account(client, "jimin_lee", "지민")
    join(client, joiner, code)

    assert client.post(LEAVE, headers=owner).status_code == 204

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JoinRequest)) == 0
        assert db.scalar(select(func.count()).select_from(Invite)) == 0
    again = join(client, joiner, code)
    assert again.status_code != 200  # 사라진 가족의 초대 코드로는 들어갈 수 없다


def test_an_owner_with_other_members_still_cannot_leave(client):
    owner, owner_id, _, _, group = family(client)
    r = client.post(LEAVE, headers=owner)
    assert r.status_code == 400 and r.json()["code"] == "cannot_leave_owner", r.text
    with SessionLocal() as db:
        assert db.get(Group, group["id"]) is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(GroupMember)
                .where(GroupMember.group_id == group["id"])
            )
            == 3
        )


def test_a_failure_in_the_middle_deletes_nothing(client, monkeypatch):
    owner, _, group = _solo(client)
    client.post(MSG, json={"text": "남아야 해요"}, headers=owner)
    before = _counts(group["id"])
    from app.shared import group_purge

    def boom(db, group_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(group_purge, "_delete_group_row", boom)
    with pytest.raises(RuntimeError):  # 시험 클라이언트는 서버 오류를 그대로 던진다
        client.post(LEAVE, headers=owner)
    assert _counts(group["id"]) == before  # 한 트랜잭션이라 아무것도 지워지지 않는다
    with SessionLocal() as db:
        assert db.get(Group, group["id"]) is not None
        assert db.scalar(text("select count(*) from groups")) == 1
