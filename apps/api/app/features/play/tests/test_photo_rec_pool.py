"""흔한 사진 풀(고르기·시드 넣기) 시험."""

import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.play import photo_rec_store as store
from app.features.play.models import PlayPhotoRec
from app.features.play.photo_rec_pool import pick_common, pool_rows
from app.shared.db import SessionLocal


def _row(i: int, **kw) -> PlayPhotoRec:
    fields = dict(
        id=f"r{i:03d}",
        group_id=None,
        source=store.SOURCE_SEED,
        image=b"x",
        kind=3,
        question="무엇일까요?",
        options=["가", "나"],
        answer="10",
        box_x=0.5,
        box_y=0.5,
        zoom=8,
        prompt_version="seed",
    )
    fields.update(kw)
    return PlayPhotoRec(**fields)


def _put(rows: list[PlayPhotoRec]) -> None:
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def test_pick_common_distinct_and_bounded(client):
    rows = [_row(i) for i in range(10)]
    got = pick_common(rows, 3, random.Random(1))
    assert len(got) == 3 and len({r.id for r in got}) == 3
    assert len(pick_common(rows[:2], 3, random.Random(1))) == 2
    a = [r.id for r in pick_common(rows, 3, random.Random(7))]
    b = [r.id for r in pick_common(rows, 3, random.Random(7))]
    assert a == b


def test_pool_excludes_sent_and_unusable(client):
    _put([_row(1), _row(2), _row(3, usable=False), _row(4, group_id=None)])
    with SessionLocal() as db:
        assert [r.id for r in pool_rows(db, {"r002"})] == ["r001", "r004"]
        assert [r.id for r in pool_rows(db, set())] == ["r001", "r002", "r004"]


def test_pool_skips_family_rows(client, family):
    _, _, group = family
    _put([_row(1), _row(2, group_id=group["id"], source=1)])
    with SessionLocal() as db:
        assert [r.id for r in pool_rows(db, set())] == ["r001"]


def _jpeg(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "JPEG")
    path.write_bytes(buf.getvalue())


def _folder(tmp_path: Path, q2: str = "둘째 질문") -> Path:
    _jpeg(tmp_path / "img/001.jpg", "red")
    _jpeg(tmp_path / "img/002.jpg", "blue")
    items = [
        {
            "key": "001",
            "image": "img/001.jpg",
            "kind": 3,
            "question": "첫째 질문",
            "options": ["가", "나", "다", "라"],
            "answer_index": 1,
            "box_x": 0.5,
            "box_y": 0.4,
            "zoom": 8,
        },
        {
            "key": "002",
            "image": "img/002.jpg",
            "kind": 3,
            "question": q2,
            "options": ["가", "나"],
            "answer_index": 0,
            "box_x": 0.2,
            "box_y": 0.9,
            "zoom": 16,
        },
    ]
    (tmp_path / "seed.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_seed_script_is_idempotent(client, tmp_path):
    from scripts.seed_photo_rec import seed

    folder = _folder(tmp_path)
    assert seed(folder) == {"added": 2, "updated": 0, "skipped": 0}
    assert seed(folder) == {"added": 0, "updated": 0, "skipped": 2}
    with SessionLocal() as db:
        rows = db.scalars(select(PlayPhotoRec).order_by(PlayPhotoRec.id)).all()
        assert [r.id for r in rows] == ["seed001", "seed002"]
        assert rows[0].answer == "0100" and rows[1].answer == "10"
        assert rows[0].source == store.SOURCE_SEED and rows[0].prompt_version == "seed"
        assert rows[0].group_id is None and rows[0].attachment_id is None
        assert rows[0].image[:2] == b"\xff\xd8"
    _folder(tmp_path, q2="바뀐 질문")
    assert seed(folder, update=True) == {"added": 0, "updated": 2, "skipped": 0}
    with SessionLocal() as db:
        assert db.get(PlayPhotoRec, "seed002").question == "바뀐 질문"


def test_seed_script_stops_on_bad_item(client, tmp_path):
    from scripts.seed_photo_rec import SeedError, seed

    folder = _folder(tmp_path)
    (tmp_path / "img/002.jpg").unlink()
    with pytest.raises(SeedError):
        seed(folder)
    with SessionLocal() as db:
        assert db.scalars(select(PlayPhotoRec)).all() == []  # 하나도 안 넣는다


def test_seed_script_validates_fields(client, tmp_path):
    from scripts.seed_photo_rec import SeedError, seed

    folder = _folder(tmp_path)
    path = folder / "seed.json"
    good = json.loads(path.read_text(encoding="utf-8"))
    for key, bad in [
        ("question", "가" * 21),
        ("options", ["가"]),
        ("options", ["가", "가"]),
        ("options", ["가", "나", "다", "라", "마"]),
        ("answer_index", 2),
        ("box_x", 1.5),
        ("zoom", 5),
    ]:
        items = json.loads(json.dumps(good))
        items[1][key] = bad
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(SeedError):
            seed(folder)


def test_pool_50_seeds_survive_14_days(client):
    _put([_row(i) for i in range(50)])
    rng = random.Random(3)
    sent: set[str] = set()
    for _ in range(14):
        with SessionLocal() as db:
            picked = pick_common(pool_rows(db, sent), 3, rng)
        assert len(picked) == 3
        sent |= {r.id for r in picked}
