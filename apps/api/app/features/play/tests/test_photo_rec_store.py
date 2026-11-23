"""찰칵! 탐정단 가비 추천의 사진 문제 보관 표: 한 사진 한 문제, 채팅 사진 삭제·AI 동의 끔 정리, 가족이 보낸 추천 추적."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.features.family_chat.models import MessageAttachment
from app.features.family_group.models import User
from app.features.play import photo_rec_store as store
from app.features.play.models import GAME_PHOTO, PlayItem, PlayPhoto, PlayPhotoRec
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=UTC)
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
ALBUM, SEED, AUTO = 1, 3, 4
MONTH, EVENT, CONTENT = 1, 2, 3


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


def _send(client, headers) -> dict:
    r = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _row(group_id, kind, attachment_id=None, source=ALBUM, **over) -> PlayPhotoRec:
    fields = dict(
        group_id=group_id,
        source=source,
        attachment_id=attachment_id,
        kind=kind,
        question="이 사진은 몇 월에 찍었을까요?",
        options=["1월", "2월", "3월", "4월"],
        answer="0010",
        box_x=0.5,
        box_y=0.5,
        zoom=8,
        prompt_version="v1",
        created_at=NOW,
    )
    fields.update(over)
    return PlayPhotoRec(**fields)


def _add(*rows) -> None:
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def _exists(rec_id) -> bool:
    with SessionLocal() as db:
        return db.get(PlayPhotoRec, rec_id) is not None


def _gid(client, headers) -> str:
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _first_user_id() -> str:
    with SessionLocal() as db:
        return db.scalars(select(User.id)).first()


def test_attachment_unique_one_row_per_photo(client, family):
    a, _, _ = family
    group_id = _gid(client, a)
    att = _send(client, a)["attachment"]["id"]
    _add(_row(group_id, MONTH, att))
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(_row(group_id, EVENT, att))
        db.commit()


def test_deleting_chat_photo_removes_its_rec_row(client, family):
    a, _, _ = family
    group_id = _gid(client, a)
    sent = _send(client, a)
    keep = _row(group_id, MONTH)  # 다른 사진(첨부 없음)의 행은 그대로
    rec = _row(group_id, CONTENT, sent["attachment"]["id"])
    _add(rec, keep)
    rec_id, keep_id = rec.id, keep.id
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
    assert not _exists(rec_id)
    assert _exists(keep_id)
    with SessionLocal() as db:
        assert db.get(MessageAttachment, sent["attachment"]["id"]) is None


def test_purge_content_rows_on_ai_disable(client, family, other_family):
    a, _, _ = family
    group_id = _gid(client, a)
    other_id = _gid(client, other_family)
    mine_content = _row(group_id, CONTENT)
    mine_month = _row(group_id, MONTH)
    mine_event = _row(group_id, EVENT)
    other_content = _row(other_id, CONTENT)
    common = _row(None, CONTENT, source=SEED, image=b"x")
    _add(mine_content, mine_month, mine_event, other_content, common)
    ids = {
        n: r.id
        for n, r in dict(
            c=mine_content, m=mine_month, e=mine_event, o=other_content, s=common
        ).items()
    }
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, _first_user_id(), True)
        ai_guard.set_enabled(db, group_id, _first_user_id(), False)
    assert not _exists(ids["c"])
    assert all(_exists(ids[k]) for k in ("m", "e", "o", "s"))


def test_turning_ai_on_keeps_rows(client, family):
    a, _, _ = family
    group_id = _gid(client, a)
    rec = _row(group_id, CONTENT)
    _add(rec)
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, _first_user_id(), True)
    assert _exists(rec.id)


def _send_item(group_id, maker_id, days_ago, rec_id, now=NOW) -> None:
    created = now - timedelta(days=days_ago)
    with SessionLocal() as db:
        item = PlayItem(
            group_id=group_id,
            game=GAME_PHOTO,
            maker_id=maker_id,
            player_ids=[],
            close_at=created + timedelta(days=1),
            created_at=created,
        )
        db.add(item)
        db.flush()
        db.add(
            PlayPhoto(
                play_id=item.id,
                image_path="play/photos/x/y.jpg",
                source=1,
                zoom=8,
                box_x=0.5,
                box_y=0.5,
                question="q",
                options=["a", "b"],
                answer="10",
                rec_id=rec_id,
            )
        )
        db.commit()


def test_sent_rec_ids_within_14_days(client, family, other_family):
    a, _, _ = family
    group_id = _gid(client, a)
    other_id = _gid(client, other_family)
    user = _first_user_id()
    _send_item(group_id, user, 13, "recA")
    _send_item(group_id, user, 15, "recB")
    _send_item(group_id, user, 1, None)  # 추천이 아닌 일반 문제
    _send_item(other_id, user, 1, "recC")  # 다른 가족
    with SessionLocal() as db:
        assert store.sent_rec_ids(db, group_id, NOW) == {"recA"}
        assert store.sent_rec_ids(db, group_id, NOW, days=20) == {"recA", "recB"}
        assert store.sent_rec_ids(db, other_id, NOW) == {"recC"}


def test_sent_today_counts_only_this_user_today(client, family):
    a, _, _ = family
    group_id = _gid(client, a)
    with SessionLocal() as db:
        user, other = db.scalars(select(User.id).order_by(User.id)).all()[:2]
    today_start = datetime(2026, 11, 19, 0, 0, tzinfo=UTC) - timedelta(hours=9)  # 한국 자정
    _send_item(group_id, user, 0, "r1", now=NOW)
    _send_item(group_id, user, 0, "r2", now=NOW)
    _send_item(group_id, user, 0, None, now=NOW)  # 추천이 아닌 문제는 안 셈
    _send_item(group_id, other, 0, "r3", now=NOW)  # 다른 사람
    _send_item(group_id, user, 2, "r4", now=NOW)  # 어제 이전
    with SessionLocal() as db:
        assert store.sent_today(db, group_id, user, today_start) == 2
        assert store.sent_today(db, group_id, other, today_start) == 1
