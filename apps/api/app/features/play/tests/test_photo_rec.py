"""찰칵! 탐정단 가비 추천 조립: 가족 사진 + 흔한 사진 구성, AI 없는 카드, 내용 질문 저장·재사용, 14일 제외, 한도 상태.
실제 AI 는 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

import io
import random
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat.models import MessageAttachment
from app.features.family_chat.photo_service import attachment_files
from app.features.family_group.models import User
from app.features.play import media
from app.features.play import photo_rec as rec
from app.features.play import photo_rec_store as store
from app.features.play.models import GAME_PHOTO, PlayItem, PlayPhoto, PlayPhotoRec
from app.shared import ai_guard
from app.shared.ai_usage import AiInflight, AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
DAY = date(2026, 3, 5)
TAKEN = datetime(2026, 3, 5, 3, 0, tzinfo=UTC)  # 한국 3월 5일 낮
GOOD = {
    "usable": True,
    "question": "무엇이 보이나요?",
    "options": ["강아지", "고양이"],
    "answer_index": 1,
    "box_x": 0.4,
    "box_y": 0.6,
}
BAD = {"usable": False}


class FakeLLM:
    """부를 때마다 같은 출력을 돌려주는 가짜 LLM(동시 호출이라 순서에 기대지 않는다)."""

    def __init__(self, output):
        self.output = output
        self.calls = []

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, **kw})
        return llm.JsonResult(data=self.output, input_tokens=100, output_tokens=50, model="fake")


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM(GOOD)
    monkeypatch.setattr(llm, "complete_json", f)
    return f


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


def _ids(client, headers):
    me = client.get("/family-group/me", headers=headers).json()["id"]
    gid = client.get("/family-group/groups/me", headers=headers).json()["id"]
    return gid, me


def _photo(client, headers, taken=None, confirm=True) -> str:
    """가족 전체방에 사진을 올리고(옵션: 일반 사진으로 확인, 촬영 시각 지정) 첨부 id 를 돌려준다."""
    r = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=headers)
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    gid, me = _ids(client, headers)
    with SessionLocal() as db:
        db.get(MessageAttachment, att).taken_at = taken
        db.commit()
        if confirm:
            assert checks.record_auto(db, gid, att, "unsure")
            assert checks.confirm_general(db, gid, att, me) == "confirmed"
    return att


def _shared_event(client, a, b, title, day):
    body = {"title": title, "start_date": day.isoformat(), "share_with": [_ids(client, b)[1]]}
    assert client.post("/schedule/events", json=body, headers=a).status_code == 201


def _seed(n: int, start: int = 0) -> list[str]:
    ids = []
    with SessionLocal() as db:
        for i in range(start, start + n):
            row = PlayPhotoRec(
                id=f"seed{i:03d}",
                group_id=None,
                source=store.SOURCE_SEED,
                image=_jpeg(),
                kind=store.KIND_CONTENT,
                question=f"흔한 질문{i}",
                options=["가", "나"],
                answer="01",
                box_x=0.5,
                box_y=0.5,
                zoom=8,
                prompt_version="seed",
            )
            db.add(row)
            ids.append(row.id)
        db.commit()
    return ids


def _enable_ai(client, a):
    gid, me = _ids(client, a)
    with SessionLocal() as db:
        ai_guard.set_enabled(db, gid, me, True)


def _recommend(client, headers, rng=None) -> dict:
    gid, me = _ids(client, headers)
    with SessionLocal() as db:
        return rec.recommend(db, db.get(User, me), gid, rng=rng)


def _send_rec(gid, maker, rec_id, days_ago=0.0) -> None:
    created = datetime.now(UTC) - timedelta(days=days_ago)
    with SessionLocal() as db:
        item = PlayItem(
            group_id=gid,
            game=GAME_PHOTO,
            maker_id=maker,
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


def _kinds(out) -> list[str]:
    return [i["kind"] for i in out["items"]]


# ---------- 조립(순수) ----------
def _cards(prefix, n):
    return [{"id": f"{prefix}{i}"} for i in range(n)]


def test_compose_mixes_family_and_common():
    def ids(fam, com):
        return [c["id"] for c in rec.compose(_cards("f", fam), _cards("c", com))]

    assert ids(3, 5) == ["f0", "f1", "c0"]
    assert ids(1, 5) == ["f0", "c0", "c1"]
    assert ids(0, 5) == ["c0", "c1", "c2"]
    assert ids(0, 1) == ["c0"]
    assert len(set(ids(3, 5))) == 3


def test_rec_rng_depends_on_user_and_day():
    d = date(2026, 3, 5)
    first = rec.rec_rng("g", "u1", d).random()
    assert rec.rec_rng("g", "u1", d).random() == first
    assert rec.rec_rng("g", "u2", d).random() != first
    assert rec.rec_rng("g", "u1", date(2026, 3, 6)).random() != first


# ---------- 추천 ----------
def test_recommend_zero_candidates_returns_common(client, family, fake):
    a, _, _ = family
    _enable_ai(client, a)
    _photo(client, a, taken=TAKEN, confirm=False)  # 판별 줄은 있지만 확인 전
    _seed(5)
    out = _recommend(client, a)
    assert out["state"] == "ok"
    assert [i["source"] for i in out["items"]] == ["common"] * 3
    assert fake.calls == []


def test_recommend_ai_off_uses_no_ai(client, family, fake):
    a, b, _ = family
    gid, _me = _ids(client, a)
    _shared_event(client, a, b, "제주 여행", DAY)
    _shared_event(client, a, b, "할머니 생신", date(2026, 4, 1))
    _photo(client, a, taken=TAKEN)  # 일정이 있는 날
    _photo(client, a, taken=datetime(2026, 7, 9, 3, 0, tzinfo=UTC))  # 촬영 시각만 있는 날
    third = _photo(client, a)  # 촬영 시각 없음 - 저장돼 있던 내용 질문 행이 있어도 안 나온다
    with SessionLocal() as db:
        db.add(
            PlayPhotoRec(
                group_id=gid,
                source=store.SOURCE_ALBUM,
                attachment_id=third,
                kind=store.KIND_CONTENT,
                question="내용 질문",
                options=["가", "나"],
                answer="10",
                box_x=0.5,
                box_y=0.5,
                zoom=8,
                prompt_version="v1",
            )
        )
        db.commit()
    _seed(3)
    out = _recommend(client, a)
    assert out["state"] == "ok"
    assert fake.calls == []
    assert sorted(_kinds(out)[:2]) == ["event", "month"]
    assert [i["source"] for i in out["items"]] == ["album", "album", "common"]
    assert "내용 질문" not in [i["question"] for i in out["items"]]


def test_recommend_content_question_stored_and_reused(client, family, fake):
    a, _, _ = family
    gid, _me = _ids(client, a)
    _enable_ai(client, a)
    att = _photo(client, a)  # 촬영 시각·일정 없음: 내용 질문만 가능
    _seed(3)
    first = _recommend(client, a)
    assert _kinds(first)[0] == "content" and first["items"][0]["question"] == "무엇이 보이나요?"
    assert first["items"][0]["answer_index"] == 1 and len(fake.calls) == 1
    assert len(fake.calls[0]["images"]) == 1  # 사진 한 장만
    with SessionLocal() as db:
        row = store.row_for_attachment(db, att)
        assert (row.kind, row.usable, row.answer, row.group_id) == (3, True, "01", gid)
    second = _recommend(client, a)
    assert second["items"][0]["id"] == first["items"][0]["id"]
    assert len(fake.calls) == 1  # 다시 부르지 않는다


def test_recommend_unusable_content_saved_and_skipped(client, family, monkeypatch):
    a, _, _ = family
    f = FakeLLM(BAD)
    monkeypatch.setattr(llm, "complete_json", f)
    _enable_ai(client, a)
    att = _photo(client, a)
    _seed(3)
    out = _recommend(client, a)
    assert [i["source"] for i in out["items"]] == ["common"] * 3
    with SessionLocal() as db:
        assert store.row_for_attachment(db, att).usable is False
    assert _recommend(client, a)["state"] == "ok"
    assert len(f.calls) == 1  # 다시 묻지 않는다


def test_recommend_excludes_sent_14_days(client, family, fake):
    a, _, _ = family
    gid, me = _ids(client, a)
    att = _photo(client, a, taken=TAKEN)
    seeds = _seed(1)
    with SessionLocal() as db:
        row = rec._save_question(
            db, gid, att, rec.month_question(TAKEN, random.Random(1)), random.Random(2)
        )
        row_id = row.id
    now = datetime.now(UTC)
    _send_rec(gid, me, row_id, days_ago=13)
    _send_rec(gid, me, seeds[0], days_ago=13)
    with SessionLocal() as db:
        assert rec.family_candidates(db, gid, now) == []
    assert _recommend(client, a)["items"] == []  # 흔한 사진도 13일 전에 보냈다
    # 15일 전에 보낸 것은 다시 나온다
    with SessionLocal() as db:
        for item in db.scalars(select(PlayItem)):
            item.created_at = now - timedelta(days=15)
        db.commit()
        assert [x.id for x in rec.family_candidates(db, gid, now)] == [att]
    items = _recommend(client, a)["items"]
    assert [i["source"] for i in items] == ["album", "common"]


def test_recommend_user_seed_varies(client, family, fake):
    a, b, _ = family
    for _i in range(5):
        _photo(client, a, taken=TAKEN)
    _seed(3)

    def picks(headers, seed):
        out = _recommend(client, headers, rng=random.Random(seed))
        return [i["id"] for i in out["items"] if i["source"] == "album"]

    assert picks(a, 1) == picks(a, 1)
    assert len({tuple(picks(a, s)) for s in range(8)}) > 1
    assert _recommend(client, a) == _recommend(client, a)  # 같은 사용자·같은 날은 같다
    assert len(_recommend(client, b)["items"]) == 3


def test_recommend_done_for_today(client, family, fake):
    a, _, _ = family
    gid, me = _ids(client, a)
    _seed(3)
    for i in range(3):
        _send_rec(gid, me, f"r{i}")
    assert _recommend(client, a) == {"state": "used_up", "items": []}


def _log(gid, me, calls, age_seconds):
    with SessionLocal() as db:
        for _ in range(calls):
            db.add(
                AiUsageLog(
                    group_id=gid,
                    user_id=me,
                    feature="play_photo_rec",
                    api_calls=1,
                    status="ok",
                    created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
                )
            )
        db.commit()


@pytest.mark.parametrize("how, state", [("cooldown", "cooldown"), ("limit", "used_up")])
def test_recommend_ai_states(client, family, fake, how, state):
    a, _, _ = family
    gid, me = _ids(client, a)
    _enable_ai(client, a)
    _photo(client, a)  # 내용 질문이 필요한 사진
    if how == "cooldown":
        _log(gid, me, 1, 0)
    else:
        _log(gid, me, 3, 30)
    assert _recommend(client, a) == {
        "state": state,
        "items": [],
    }  # 카드가 하나도 없으면 상태가 나온다
    assert fake.calls == []
    _photo(client, a, taken=TAKEN)  # AI 없이 되는 사진이 생기면 카드는 그대로 ok
    _seed(3)
    out = _recommend(client, a)
    assert out["state"] == "ok" and _kinds(out)[0] == "month" and len(out["items"]) == 3


def test_recommend_busy_state(client, family, fake):
    a, _, _ = family
    gid, me = _ids(client, a)
    _enable_ai(client, a)
    _photo(client, a)
    with SessionLocal() as db:
        for slot in range(max(1, settings.ai_max_concurrent_requests_per_group)):
            db.add(
                AiInflight(
                    group_id=gid,
                    slot=slot,
                    token=f"t{slot}",
                    user_id="other",
                    feature="analysis",
                    started_at=datetime.now(UTC),
                )
            )
        db.commit()
    assert _recommend(client, a) == {"state": "preparing", "items": []}


def test_recommend_ai_failure_state(client, family, monkeypatch):
    a, _, _ = family
    f = FakeLLM({"usable": True, "question": "x" * 30})  # 규칙에 안 맞는 출력
    monkeypatch.setattr(llm, "complete_json", f)
    _enable_ai(client, a)
    _photo(client, a)
    assert _recommend(client, a) == {"state": "failed", "items": []}
    assert len(f.calls) == 2  # 한 번 더 시도하고 포기


def test_recommend_item_shape(client, family, fake):
    a, b, _ = family
    _shared_event(client, a, b, "민수 생일파티", DAY)
    _shared_event(client, a, b, "할머니 생신", date(2026, 4, 1))
    _enable_ai(client, a)
    _photo(client, a, taken=TAKEN)
    _seed(3)
    out = _recommend(client, a)
    assert out["state"] == "ok" and len(out["items"]) == 3
    keys = {
        "id", "kind", "source", "question", "options", "answer_index",
        "box_x", "box_y", "zoom", "image_url",
    }  # fmt: skip
    for item in out["items"]:
        assert set(item) == keys
        assert item["kind"] in ("month", "event", "content")
        assert item["source"] in ("album", "common")
        assert 0 <= item["answer_index"] < len(item["options"])
        assert item["image_url"] == f"/play/photo/recommendations/{item['id']}/image"
    album = out["items"][0]
    assert album["kind"] == "event" and album["options"][album["answer_index"]] == "민수 생일파티"
    assert 0.25 <= album["box_x"] <= 0.75 and 0.25 <= album["box_y"] <= 0.75
    assert fake.calls == []  # 일정 문제라 AI 를 부르지 않았다


# ---------- 추천·이미지 API ----------
def test_photo_rec_endpoint(client, family, fake):
    a, b, _ = family
    _photo(client, a, taken=TAKEN)
    _seed(3)
    r = client.get("/play/photo/recommendations", headers=b)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ok" and len(body["items"]) == 3
    keys = {
        "id", "kind", "source", "question", "options", "answer_index",
        "box_x", "box_y", "zoom", "image_url",
    }  # fmt: skip
    assert all(set(item) == keys for item in body["items"])
    assert client.get("/play/photo/recommendations").status_code == 401


def _album_row(client, headers) -> str:
    att = _photo(client, headers, taken=TAKEN)
    gid, _ = _ids(client, headers)
    with SessionLocal() as db:
        row = store.add_row(
            db,
            group_id=gid,
            source=store.SOURCE_ALBUM,
            attachment_id=att,
            kind=store.KIND_MONTH,
            question="몇 월?",
            options=["3월", "4월"],
            answer="10",
            box_x=0.5,
            box_y=0.5,
            zoom=8,
            prompt_version="t",
        )
        return row.id


def test_rec_image_access(client, family, other_family):
    a, b, _ = family
    album = _album_row(client, a)
    seed = _seed(1)[0]
    for headers in (a, b):
        r = client.get(f"/play/photo/recommendations/{album}/image", headers=headers)
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    # 다른 가족의 가족 행은 404, 공통 행은 어느 가족이든 200
    assert (
        client.get(f"/play/photo/recommendations/{album}/image", headers=other_family).status_code
        == 404
    )
    r = client.get(f"/play/photo/recommendations/{seed}/image", headers=other_family)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get(f"/play/photo/recommendations/{seed}/image").status_code == 401
    assert client.get("/play/photo/recommendations/nope/image", headers=a).status_code == 404
    # 첨부가 사라지면 404
    with SessionLocal() as db:
        row = db.get(PlayPhotoRec, album)
        att = db.get(MessageAttachment, row.attachment_id)
        files = attachment_files(att)
    files[0].unlink()
    assert client.get(f"/play/photo/recommendations/{album}/image", headers=a).status_code == 404


# ---------- "이 문제로 쓰기" 전송 ----------
SEND = {
    "zoom": 8,
    "box_x": 0.3,
    "box_y": 0.7,
    "question": "고쳐 쓴 질문",
    "options": ["3월", "4월"],
    "answer_index": 1,
}


def _send(client, headers, rec_id=None, file=False, **over):
    data = {**SEND, **over}
    if rec_id is not None:
        data["rec_id"] = rec_id
    files = {"file": ("p.jpg", _jpeg(), "image/jpeg")} if file else None
    return client.post("/play/photos", data=data, files=files, headers=headers)


def _photo_row(item_id):
    with SessionLocal() as db:
        return db.get(PlayPhoto, item_id)


def test_send_with_rec_id_copies_image(client, family):
    a, _, _ = family
    album = _album_row(client, a)
    r = _send(client, a, album)
    assert r.status_code == 201, r.text
    row = _photo_row(r.json()["id"])
    assert (row.rec_id, row.source) == (album, 1)
    assert (row.question, row.zoom, row.box_x, row.answer) == ("고쳐 쓴 질문", 8, 0.3, "01")
    with SessionLocal() as db:
        att = db.get(MessageAttachment, db.get(PlayPhotoRec, album).attachment_id)
        orig = attachment_files(att)[0].read_bytes()
    assert media.read(row.image_path) == media.make_photo_jpeg(orig)  # 같은 원본에서 만든다
    # 공통 행은 source=3
    seed = _seed(1)[0]
    r = _send(client, a, seed, source=2)  # 요청의 source 는 무시된다
    assert r.status_code == 201, r.text
    row = _photo_row(r.json()["id"])
    assert (row.rec_id, row.source) == (seed, 3)


def test_send_blocked_when_photo_excluded(client, family):
    a, _, _ = family
    album = _album_row(client, a)
    gid, me = _ids(client, a)
    with SessionLocal() as db:
        att = db.get(PlayPhotoRec, album).attachment_id
        assert checks.exclude_photo(db, gid, att, me) == "excluded"
    r = _send(client, a, album)
    assert r.status_code == 409 and r.json()["code"] == "photo_not_available"


def test_send_blocked_when_row_unusable_or_attachment_gone(client, family):
    a, _, _ = family
    album = _album_row(client, a)
    with SessionLocal() as db:
        db.get(PlayPhotoRec, album).usable = False
        db.commit()
    assert _send(client, a, album).json()["code"] == "photo_not_available"
    with SessionLocal() as db:
        db.get(PlayPhotoRec, album).usable = True
        db.commit()
        files = attachment_files(
            db.get(MessageAttachment, db.get(PlayPhotoRec, album).attachment_id)
        )
    files[0].unlink()
    r = _send(client, a, album)
    assert r.status_code == 409 and r.json()["code"] == "photo_not_available"


def test_send_blocked_when_recently_sent(client, family):
    a, _, _ = family
    gid, me = _ids(client, a)
    album = _album_row(client, a)
    seed = _seed(1)[0]
    _send_rec(gid, me, album, days_ago=13)
    _send_rec(gid, me, seed, days_ago=13)
    for rid in (album, seed):
        r = _send(client, a, rid)
        assert r.status_code == 409 and r.json()["code"] == "rec_already_sent"
    other = _album_row(client, a)
    _send_rec(gid, me, other, days_ago=15)
    assert _send(client, a, other).status_code == 201


def test_send_twice_second_is_409(client, family):
    a, _, _ = family
    album = _album_row(client, a)
    assert _send(client, a, album).status_code == 201
    r = _send(client, a, album)
    assert r.status_code == 409 and r.json()["code"] == "rec_already_sent"


def test_send_rec_of_other_family_404(client, family, other_family):
    a, _, _ = family
    album = _album_row(client, a)
    r = _send(client, other_family, album)
    assert r.status_code == 404 and r.json()["code"] == "rec_not_found"
    r = _send(client, a, "nope")
    assert r.status_code == 404 and r.json()["code"] == "rec_not_found"


def test_send_without_file_or_rec_id_400(client, family):
    a, _, _ = family
    assert _send(client, a, source=2).status_code == 400
    assert _send(client, a).status_code == 400


def test_send_with_both_rec_id_and_file_uses_file(client, family):
    a, _, _ = family
    album = _album_row(client, a)
    r = _send(client, a, album, file=True, source=1)
    assert r.status_code == 201, r.text
    row = _photo_row(r.json()["id"])
    assert (row.rec_id, row.source) == (None, 2)


def test_send_file_upload_unchanged(client, family):
    a, _, _ = family
    for src in (1, 2):
        r = _send(client, a, file=True, source=src)
        assert r.status_code == 201, r.text
        assert _photo_row(r.json()["id"]).source == src
    assert _send(client, a, file=True, source=3).status_code == 400
    assert _send(client, a, file=True).status_code == 400  # source 없음
