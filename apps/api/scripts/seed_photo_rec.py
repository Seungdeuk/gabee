"""찰칵! 탐정단 가비 추천의 흔한 사진 시드를 폴더(seed.json + 이미지)에서 DB 로 넣는다.

    cd apps/api
    python -m scripts.seed_photo_rec <폴더>            # 없는 항목만 넣는다
    python -m scripts.seed_photo_rec <폴더> --update   # 있는 항목은 덮어쓴다

- `<폴더>/seed.json` 은 항목 배열: key, image(폴더 기준 상대 경로), kind, question, options, answer_index, box_x, box_y, zoom.
- 행 id 는 `seed<key>`, source 는 흔한 사진(시드), prompt_version 은 "seed", group_id·attachment_id 는 비고 이미지는 JPEG 바이트.
- 모든 항목을 먼저 검사하고 하나라도 틀리면 아무것도 넣지 않고 멈춘다. 여러 번 실행해도 안전하다(멱등).
- 어느 DB 에 쓰는지(호스트)를 출력한다.
"""

import io
import json
import sys
from pathlib import Path

from PIL import Image
from sqlalchemy.engine import make_url

from app.features.play.models import PlayPhotoRec
from app.features.play.photo_rec_store import SOURCE_SEED
from app.shared.config import settings
from app.shared.db import SessionLocal

QUESTION_MAX = 20
OPTION_MAX = 20
ZOOMS = (4, 6, 8, 16, 32)
KINDS = (1, 2, 3)


class SeedError(Exception):
    """시드 파일·항목이 틀렸다."""


def _bits(options: list[str], index: int) -> str:
    return "".join("1" if i == index else "0" for i in range(len(options)))


def _jpeg_bytes(path: Path) -> bytes:
    try:
        with Image.open(path) as im:
            im.load()
            if im.format == "JPEG":
                return path.read_bytes()
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=90)
            return buf.getvalue()
    except Exception as e:
        raise SeedError(f"이미지를 열 수 없음: {path} ({e})") from e


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fields(folder: Path, item: dict) -> dict:
    """항목 하나를 검사해 행 칸 값으로 바꾼다. 틀리면 `SeedError`."""
    key = item.get("key")
    if not isinstance(key, str) or not key.strip():
        raise SeedError(f"key 가 없음: {item}")
    where = f"[{key}]"
    question, options = item.get("question"), item.get("options")
    if not isinstance(question, str) or not 1 <= len(question) <= QUESTION_MAX:
        raise SeedError(f"{where} 질문은 1~{QUESTION_MAX}자")
    if not isinstance(options, list) or not 2 <= len(options) <= 4:
        raise SeedError(f"{where} 보기는 2~4개")
    if any(not isinstance(o, str) or not 1 <= len(o) <= OPTION_MAX for o in options):
        raise SeedError(f"{where} 보기는 각 1~{OPTION_MAX}자")
    if len(set(options)) != len(options):
        raise SeedError(f"{where} 보기가 중복됨")
    idx = item.get("answer_index")
    if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(options):
        raise SeedError(f"{where} answer_index 가 보기 범위 밖")
    for f in ("box_x", "box_y"):
        if not _number(item.get(f)) or not 0 <= item[f] <= 1:
            raise SeedError(f"{where} {f} 는 0~1")
    if item.get("zoom") not in ZOOMS or isinstance(item.get("zoom"), bool):
        raise SeedError(f"{where} zoom 은 {ZOOMS} 중 하나")
    if item.get("kind") not in KINDS:
        raise SeedError(f"{where} kind 는 {KINDS} 중 하나")
    rel = item.get("image")
    if not isinstance(rel, str):
        raise SeedError(f"{where} image 경로가 없음")
    path = folder / rel
    if not path.is_file():
        raise SeedError(f"{where} 이미지 파일이 없음: {path}")
    return dict(
        id=f"seed{key.strip()}",
        group_id=None,
        attachment_id=None,
        source=SOURCE_SEED,
        prompt_version="seed",
        image=_jpeg_bytes(path),
        kind=item["kind"],
        usable=True,
        question=question,
        options=options,
        answer=_bits(options, idx),
        box_x=float(item["box_x"]),
        box_y=float(item["box_y"]),
        zoom=item["zoom"],
    )


def seed(folder: Path, update: bool = False) -> dict:
    """`folder/seed.json` 을 읽어 흔한 사진 행을 넣는다. {"added","updated","skipped"} 를 돌려준다."""
    folder = Path(folder)
    spec = folder / "seed.json"
    if not spec.is_file():
        raise SeedError(f"seed.json 이 없음: {spec}")
    try:
        items = json.loads(spec.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SeedError(f"seed.json 형식 오류: {e}") from e
    if not isinstance(items, list):
        raise SeedError("seed.json 은 항목 배열이어야 함")
    rows = [_fields(folder, it) for it in items]
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SeedError("key 가 중복됨")
    out = {"added": 0, "updated": 0, "skipped": 0}
    with SessionLocal() as db:
        for fields in rows:
            row = db.get(PlayPhotoRec, fields["id"])
            if row is None:
                db.add(PlayPhotoRec(**fields))
                out["added"] += 1
            elif update:
                for k, v in fields.items():
                    setattr(row, k, v)
                out["updated"] += 1
            else:
                out["skipped"] += 1
        db.commit()
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print("사용법: python -m scripts.seed_photo_rec <폴더> [--update]")
        return 2
    print(f"DB 호스트: {make_url(settings.database_url).host}")
    try:
        result = seed(Path(args[0]), update="--update" in argv)
    except SeedError as e:
        print(f"오류: {e}")
        return 1
    print(f"추가 {result['added']} · 갱신 {result['updated']} · 건너뜀 {result['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
