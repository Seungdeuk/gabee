"""찍힌 사람 찾기 테스트. 진짜 얼굴 모델은 쓰지 않는다(CI 에 모델 없음) — 가짜 엔진이 정해 둔 얼굴을 돌려준다."""

import io

import numpy as np
import pytest
from PIL import Image

from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.ingest.faces import Face, FaceBook, Faces
from app.features.ai_assistant.ingest.raw_store import LocalRawStore
from app.features.ai_assistant.ingest.service import ingest_file
from app.shared.config import settings


@pytest.fixture(autouse=True)
def no_real_jev(monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "")


def vec(*xs) -> np.ndarray:
    v = np.zeros(128, np.float32)
    v[: len(xs)] = xs
    return v / np.linalg.norm(v)


MOM = vec(1, 0)
KID = vec(0, 1)
STRANGER = vec(0, 0, 1)


class FakeEngine:
    def __init__(self, faces):
        self._faces = faces
        self.calls = 0

    def faces(self, data):
        self.calls += 1
        return self._faces


class FakeOcr:
    def __init__(self, lines=()):
        self.lines = [OcrLine(t, 0.95) for t in lines]

    def read(self, image):
        return self.lines


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(buf, "PNG")
    return buf.getvalue()


def face(v, size=100, turn=0.2):
    return Face([10, 10, size, size], 0.95, v, turn)


def test_identify_names_family_and_leaves_strangers_unknown(tmp_path):
    finder = Faces(FakeEngine([face(MOM), face(STRANGER), face(KID, size=20)]), tmp_path)
    book = finder.book("g01")
    book.add("엄마", MOM)
    book.add("지민", KID)
    r = finder.identify("g01", b"")
    assert r["count"] == 3 and r["names"] == ["엄마"]
    assert r["unknown"] == 1  # 모르는 사람
    assert r["faces"][2]["too_small"] and r["faces"][2]["name"] is None  # 작으면 이름 안 붙임
    assert all("embedding" not in f for f in r["faces"])  # 얼굴 숫자는 결과에 없음


def test_profile_face_needs_higher_similarity(tmp_path):
    almost = vec(0.47, 0.88)  # 엄마와 유사도 ≈ 0.47: 정면이면 이름, 옆얼굴이면 모름
    finder = Faces(FakeEngine([face(almost, turn=1.2)]), tmp_path)
    finder.book("g01").add("엄마", MOM)
    assert finder.identify("g01", b"")["names"] == []
    finder.engine = FakeEngine([face(almost)])
    assert finder.identify("g01", b"")["names"] == ["엄마"]


def test_face_books_are_separate_per_group_and_deletable(tmp_path):
    a = FaceBook("g01", tmp_path)
    a.add("엄마", MOM)
    a.add("엄마", vec(1, 0.1))
    assert FaceBook("g02", tmp_path).match(MOM) == (None, 0.0)  # 다른 가족은 모른다
    assert FaceBook("g01", tmp_path).people() == {"엄마": 2}  # 파일로 남는다
    assert a.delete("엄마") == 2 and FaceBook("g01", tmp_path).people() == {}
    with pytest.raises(ValueError):
        FaceBook("../g01", tmp_path)


def test_enroll_rejects_bad_photos(tmp_path):
    for faces, msg in (
        ([], "찾지 못"),
        ([face(MOM, size=20)], "작아요"),
        ([face(MOM, turn=2.0)], "옆얼굴"),
    ):
        with pytest.raises(ValueError, match=msg):
            Faces(FakeEngine(faces), tmp_path).enroll("g01", "엄마", b"")
    ok = Faces(FakeEngine([face(MOM)]), tmp_path).enroll("g01", " 엄마 ", b"")
    assert ok["name"] == "엄마"


def test_ingest_finds_people_only_in_shared_photos(tmp_path):
    finder = Faces(FakeEngine([face(MOM)]), tmp_path / "faces")
    finder.book("g01").add("엄마", MOM)
    store = LocalRawStore(tmp_path / "raw")
    photo = ingest_file("g01", png(), "a.png", store=store, ocr=FakeOcr(), faces=finder)
    assert photo.classification.route == "daily_share"
    assert photo.people.names == ["엄마"] and photo.people.faces[0].similarity == 1.0

    engine = FakeEngine([face(MOM)])
    receipt = ingest_file(
        "g01",
        png(),
        "b.png",
        store=store,
        ocr=FakeOcr(["영수증", "카드 승인번호 1234", "합계 5,000원"]),
        faces=Faces(engine, tmp_path / "faces"),
    )
    assert receipt.people is None and engine.calls == 0  # 문서 사진은 얼굴을 찾지 않는다
