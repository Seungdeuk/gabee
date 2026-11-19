"""Pixabay 에서 탐정단 "흔한 사진" 시드 후보를 내려받는다(사람이 눈으로 고를 후보와 한눈에 보는 목록 이미지까지).

사용법 (apps/api 에서):
    PIXABAY_API_KEY=... python scripts/fetch_pixabay_seed.py --out C:\\temp\\seed_candidates [--total 90]

- 키는 환경변수 `PIXABAY_API_KEY` 또는 `apps/api/.env` 의 같은 이름 줄에서 읽는다(화면·파일에 찍지 않는다).
- Pixabay API 규칙을 지킨다: 응답은 24시간 캐시(출력 폴더 `.cache/`)하고, 요청은 분당 100건 한참 아래로 쉬어 가며 보내고,
  사진은 핫링크하지 않고 직접 내려받아 우리 쪽에 저장한다(큰 이미지 1280px).
- 사람·글자·브랜드가 태그에 보이는 사진은 자동으로 뺀다. 태그로 다 걸러지지 않으므로 목록 이미지(`contact_sheet.jpg`)를 보고 사람이 최종 선택한다.
- 출력: `img/NNN.jpg`(긴 변 1280px JPEG), `candidates.json`(번호·Pixabay id·분류·태그·작성자·원본 페이지·라이선스), `contact_sheet.jpg`.
"""

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

API = "https://pixabay.com/api/"
LICENSE = "Pixabay Content License"
CACHE_SECONDS = 24 * 3600  # Pixabay 는 응답을 24시간 캐시하라고 요구한다
REQUEST_GAP = 1.2  # 초. 분당 100건 제한보다 훨씬 천천히
SIDE_PX = 1280
# (Pixabay 분류, 후보 수). 일상 소재 위주(사람 분류는 쓰지 않는다)
CATEGORIES = [
    ("food", 20),
    ("animals", 20),
    ("nature", 15),
    ("transportation", 10),
    ("travel", 10),
    ("places", 10),
    ("buildings", 5),
]
# 태그에 하나라도 있으면 뺀다: 사람·얼굴, 글자·브랜드·간판
_BAD_TAGS = {
    "people", "person", "man", "men", "woman", "women", "girl", "boy", "child", "children", "kid",
    "kids", "baby", "toddler", "portrait", "face", "couple", "family", "model", "lady", "human",
    "crowd", "student", "students", "wedding", "bride", "groom", "selfie", "smile", "athlete",
    "player", "runner", "dancer", "farmer", "worker", "tourist", "adult", "teen", "teenager",
    "text", "sign", "logo", "poster", "typography", "letter", "letters", "label", "brand",
    "advertisement", "menu", "banner", "billboard", "newspaper", "book", "words", "quote",
}  # fmt: skip
_TOKEN = re.compile(r"[a-z]+")


def api_key(env_file: Path | None = None) -> str:
    """환경변수 → `.env` 순으로 키를 읽는다. 없으면 SystemExit(키 값은 어디에도 찍지 않는다)."""
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        env_file = env_file or Path(__file__).resolve().parents[1] / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "PIXABAY_API_KEY":
                    key = value.strip().strip("\"'")
                    break
    if not key:
        raise SystemExit("PIXABAY_API_KEY 가 없어요(환경변수 또는 apps/api/.env)")
    return key


def is_scenery(hit: dict) -> bool:
    """태그에 사람·얼굴·글자·브랜드 단어가 하나도 없으면 참."""
    tokens = set(_TOKEN.findall(str(hit.get("tags", "")).lower()))
    return not (tokens & _BAD_TAGS)


def pick_hits(hits: list[dict], n: int, seen: set[int]) -> list[dict]:
    """걸러진 사진을 앞에서부터 최대 n 개(이미 고른 id 는 건너뛰고 seen 에 더한다)."""
    chosen: list[dict] = []
    for hit in hits:
        if len(chosen) >= n:
            break
        pid = hit.get("id")
        if pid in seen or not hit.get("largeImageURL") or not is_scenery(hit):
            continue
        seen.add(pid)
        chosen.append(hit)
    return chosen


def search(
    client: httpx.Client, key: str, category: str, per_page: int, cache_dir: Path, *, now=time.time
) -> list[dict]:
    """한 분류의 인기 사진을 검색한다. 24시간 안의 캐시가 있으면 그것을 쓰고 요청하지 않는다."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{category}_{per_page}.json"
    if cache.is_file() and now() - cache.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache.read_text(encoding="utf-8")).get("hits", [])
    params = {
        "key": key,
        "category": category,
        "image_type": "photo",
        "orientation": "horizontal",
        "safesearch": "true",
        "order": "popular",
        "min_width": 1280,
        "per_page": per_page,
    }
    response = client.get(API, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(REQUEST_GAP)
    return data.get("hits", [])


def save_resized(client: httpx.Client, url: str, dest: Path) -> None:
    """사진을 직접 내려받아 긴 변 1280px JPEG(품질 80)로 저장한다."""
    response = client.get(url, timeout=60)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    image.thumbnail((SIDE_PX, SIDE_PX), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "JPEG", quality=80)


def contact_sheet(files: list[Path], out: Path, columns: int = 10, cell: int = 180) -> None:
    """사진마다 번호를 붙여 한 장에 모은 목록 이미지(사람이 고를 때 보는 용도)."""
    rows = max(1, -(-len(files) // columns))
    sheet = Image.new("RGB", (columns * cell, rows * cell), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(files):
        with Image.open(path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((cell - 6, cell - 6))
        x, y = (i % columns) * cell, (i // columns) * cell
        sheet.paste(thumb, (x + 3, y + 3))
        draw.rectangle([x + 3, y + 3, x + 40, y + 19], fill=(0, 0, 0))
        draw.text((x + 6, y + 5), f"{i + 1:03d}", fill=(255, 255, 0))
    sheet.save(out, "JPEG", quality=85)


def run(out: Path, key: str, total: int, client: httpx.Client) -> list[dict]:
    """후보를 내려받아 `img/`·`candidates.json`·`contact_sheet.jpg` 를 만들고 후보 목록을 돌려준다."""
    out.mkdir(parents=True, exist_ok=True)
    scale = total / sum(n for _, n in CATEGORIES)
    seen: set[int] = set()
    candidates: list[dict] = []
    files: list[Path] = []
    for category, share in CATEGORIES:
        want = max(1, round(share * scale))
        hits = search(client, key, category, min(200, want * 4), out / ".cache")
        for hit in pick_hits(hits, want, seen):
            no = len(candidates) + 1
            dest = out / "img" / f"{no:03d}.jpg"
            save_resized(client, hit["largeImageURL"], dest)
            files.append(dest)
            candidates.append(
                {
                    "no": no,
                    "pixabay_id": hit["id"],
                    "category": category,
                    "tags": hit.get("tags", ""),
                    "user": hit.get("user", ""),
                    "page_url": hit.get("pageURL", ""),
                    "license": LICENSE,
                    "file": f"img/{no:03d}.jpg",
                }
            )
    (out / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if files:
        contact_sheet(files, out / "contact_sheet.jpg")
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="후보를 저장할 새 폴더")
    parser.add_argument("--total", type=int, default=90, help="후보 사진 수(기본 90)")
    args = parser.parse_args(argv)
    with httpx.Client(follow_redirects=True) as client:
        found = run(args.out, api_key(), args.total, client)
    print(f"후보 {len(found)}장 저장: {args.out} (contact_sheet.jpg 로 확인하세요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
