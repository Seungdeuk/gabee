"""찍힌 사람 찾기. 얼굴 찾기(YuNet) → 얼굴을 숫자 128개로(SFace) → 그 가족의 얼굴 DB 에서 가장 닮은 사람.

    사진 ─▶ 얼굴 찾기 ─▶ 바로 세워 112×112 ─▶ 숫자 128개 ─▶ 가족 얼굴 DB 와 비교
                                                         ├ 0.45 이상(옆얼굴 0.5) ─▶ 이름
                                                         └ 미만 · 얼굴이 너무 작음 ─▶ 모르는 사람

- 모델: OpenCV Zoo (YuNet MIT, SFace Apache-2.0) 두 파일을 `FACE_MODEL_DIR` 에 둔다. 없으면 얼굴 찾기를 건너뛴다.
  https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
  https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface
- 얼굴 숫자는 생체정보(민감정보)다. 서버 안에서만 쓰고 어떤 외부 AI 로도 보내지 않으며, 결과에도 담지 않는다.
  가족 그룹마다 따로 `DATA_DIR/faces/<group_id>/` 에 두고, 사람 단위로 지울 수 있다(동의 철회).
- 기준값은 원본 프로젝트 측정(공인 5명 69장 + 모르는 얼굴 28개, 2026-10-21): 39장 중 36장 맞힘, 잘못 붙인 이름 0.
"""

import io
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.shared.config import settings

DETECTOR = "face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface_2021dec.onnx"
# 공식 값 0.363 은 한 사람에 3장만 등록하면 비슷한 또래의 모르는 사람이 0.42~0.43 까지 올라와 이름이 잘못 붙었다.
# 모르는 사람에게 가족 이름을 붙이는 것이 놓치는 것보다 나쁘므로 0.45.
THRESHOLD = 0.45
PROFILE_TURN = 1.0  # 고개 돌린 정도가 이 이상이면 옆얼굴 (정면 ≈ 0.2)
PROFILE_THRESHOLD = 0.5  # 옆얼굴끼리는 다른 사람이어도 닮아 보여서 기준을 높인다
ENROLL_MAX_TURN = 1.5  # 완전한 옆얼굴은 등록하지 않는다
MIN_SCORE = 0.8  # 얼굴 찾기 확신도
MIN_SIZE = 40  # 이보다 작은 얼굴(px)은 이름을 붙이지 않는다
MAX_SIDE = 1280
_GROUP_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def model_dir() -> Path:
    return Path(settings.face_model_dir or Path(settings.data_dir) / "models" / "faces")


def available() -> bool:
    d = model_dir()
    return (d / DETECTOR).exists() and (d / RECOGNIZER).exists()


def load_bgr(data: bytes, max_side: int = MAX_SIDE) -> np.ndarray:
    """사진 바이트 → EXIF 회전 반영, 긴 변 max_side 이하의 BGR 배열(OpenCV 형식)."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    s = min(1.0, max_side / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)))
    return np.asarray(im)[:, :, ::-1].copy()


@dataclass
class Face:
    box: list[int]  # x, y, w, h (줄인 사진 기준)
    score: float  # 얼굴 확신도
    embedding: np.ndarray  # (128,) 길이 1로 맞춘 얼굴 숫자
    turn: float = 0.0  # 고개 돌린 정도

    @property
    def profile(self) -> bool:
        return self.turn >= PROFILE_TURN

    @property
    def too_small(self) -> bool:
        return min(self.box[2], self.box[3]) < MIN_SIZE


def head_turn(row: np.ndarray) -> float:
    """YuNet 점 5개(오른눈·왼눈·코·입꼬리 2)로: |코 x − 두 눈 가운데 x| / 눈 사이 거리."""
    right, left, nose = row[4:6], row[6:8], row[8:10]
    eyes = float(np.linalg.norm(left - right))
    return float(abs(nose[0] - (right[0] + left[0]) / 2) / max(eyes, 1.0))


class FaceEngine:
    """YuNet + SFace. OpenCV DNN 은 스레드 안전하지 않아 잠금으로 감싼다."""

    def __init__(self, directory: Path | None = None) -> None:
        import cv2

        d = directory or model_dir()
        self.detector = cv2.FaceDetectorYN.create(
            str(d / DETECTOR), "", (320, 320), MIN_SCORE, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(d / RECOGNIZER), "")
        self._lock = threading.Lock()

    def faces(self, data: bytes) -> list[Face]:
        img = load_bgr(data)
        h, w = img.shape[:2]
        out = []
        with self._lock:
            self.detector.setInputSize((w, h))
            _, rows = self.detector.detect(img)
            for r in rows if rows is not None else []:
                aligned = self.recognizer.alignCrop(img, r)  # 눈·코·입 5점으로 바로 세워 112×112
                f = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
                f /= np.linalg.norm(f) + 1e-9
                out.append(Face([int(v) for v in r[:4]], float(r[14]), f, head_turn(r)))
        return sorted(out, key=lambda x: -x.box[2] * x.box[3])  # 큰 얼굴 먼저


class FaceBook:
    """한 가족 그룹의 얼굴 DB. 한 사람에 여러 장을 두고, 가장 닮은 장의 유사도를 그 사람 점수로 쓴다."""

    def __init__(self, group_id: str, root: str | Path | None = None) -> None:
        if not _GROUP_ID.match(group_id):
            raise ValueError("잘못된 그룹 id 예요")
        self.dir = Path(root or Path(settings.data_dir) / "faces") / group_id
        self._lock = threading.Lock()
        self.rows: list[dict] = []
        self.emb = np.zeros((0, 128), np.float32)
        meta, vec = self.dir / "book.json", self.dir / "book.npy"
        if meta.exists() and vec.exists():
            self.rows = json.loads(meta.read_text(encoding="utf-8"))
            self.emb = np.load(vec).astype(np.float32)

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = json.dumps(self.rows, ensure_ascii=False, indent=1)
        (self.dir / "book.json").write_text(meta, encoding="utf-8")
        np.save(self.dir / "book.npy", self.emb)

    def add(self, name: str, embedding: np.ndarray) -> str:
        name = name.strip()[:30]
        if not name:
            raise ValueError("이름이 비어 있어요")
        fid = uuid.uuid4().hex[:12]
        with self._lock:
            self.rows.append({"id": fid, "name": name, "added": time.strftime("%Y-%m-%dT%H:%M:%S")})
            self.emb = np.vstack([self.emb, embedding.reshape(1, -1).astype(np.float32)])
            self._save()
        return fid

    def delete(self, name: str) -> int:
        """그 사람의 얼굴 숫자를 모두 지운다(동의 철회). 지운 장 수."""
        with self._lock:
            keep = [i for i, r in enumerate(self.rows) if r["name"] != name]
            n = len(self.rows) - len(keep)
            self.rows = [self.rows[i] for i in keep]
            self.emb = self.emb[keep] if keep else np.zeros((0, 128), np.float32)
            self._save()
        return n

    def people(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r["name"]] = out.get(r["name"], 0) + 1
        return out

    def match(
        self, embedding: np.ndarray, threshold: float = THRESHOLD
    ) -> tuple[str | None, float]:
        """(이름 또는 None, 가장 닮은 사람의 유사도)."""
        if not self.rows:
            return None, 0.0
        sims = self.emb @ embedding.astype(np.float32)
        best: dict[str, float] = {}
        for r, s in zip(self.rows, sims, strict=True):
            best[r["name"]] = max(best.get(r["name"], -1.0), float(s))
        name, sim = max(best.items(), key=lambda kv: kv[1])
        return (name if sim >= threshold else None), sim


class Faces:
    """ingest 가 부르는 얼굴 찾기. 엔진(모델)은 하나를 같이 쓰고, 얼굴 DB 는 가족 그룹마다 따로."""

    def __init__(self, engine: FaceEngine, root: str | Path | None = None) -> None:
        self.engine = engine
        self.root = root

    def book(self, group_id: str) -> FaceBook:
        return FaceBook(group_id, self.root)

    def identify(self, group_id: str, data: bytes) -> dict:
        t0 = time.perf_counter()
        book = self.book(group_id)
        found = self.engine.faces(data)
        faces, names = [], []
        for f in found:
            th = max(THRESHOLD, PROFILE_THRESHOLD) if f.profile else THRESHOLD
            name, sim = (None, 0.0) if f.too_small else book.match(f.embedding, th)
            faces.append(
                {
                    "box": f.box,
                    "name": name,
                    "similarity": round(sim, 3),
                    "profile": f.profile,
                    "too_small": f.too_small,
                }
            )
            if name and name not in names:
                names.append(name)
        return {
            "count": len(found),
            "names": names,
            "unknown": sum(1 for x in faces if not x["name"] and not x["too_small"]),
            "faces": faces,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    def enroll(self, group_id: str, name: str, data: bytes) -> dict:
        """사진에서 가장 큰 얼굴 하나를 그 사람으로 등록한다. 못 하면 ValueError(이유는 사람이 읽는 말)."""
        found = self.engine.faces(data)
        if not found:
            raise ValueError("얼굴을 찾지 못했어요")
        f = found[0]
        if f.too_small:
            raise ValueError("얼굴이 너무 작아요. 얼굴이 크게 나온 사진을 써 주세요")
        if f.turn > ENROLL_MAX_TURN:
            raise ValueError("옆얼굴이에요. 정면에 가까운 사진으로 등록해 주세요")
        return {"id": self.book(group_id).add(name, f.embedding), "name": name.strip()[:30]}


_default: Faces | None = None
_default_lock = threading.Lock()


def default_faces() -> Faces | None:
    """모델 파일이 있으면 공용 Faces, 없으면 None(얼굴 찾기를 건너뜀)."""
    global _default
    if not available():
        return None
    with _default_lock:
        if _default is None:
            _default = Faces(FaceEngine())
    return _default
