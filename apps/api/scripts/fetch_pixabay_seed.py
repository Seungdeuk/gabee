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
    # 징그럽거나 무서운 동물(뱀·도마뱀·곤충·파충류·개구리 등)
    "snake", "lizard", "gecko", "reptile", "reptiles", "insect", "insects", "spider", "beetle",
    "bug", "wasp", "bee", "bees", "ant", "ants", "fly", "mosquito", "cockroach", "worm",
    "caterpillar", "butterfly", "moth", "dragonfly", "frog", "toad", "crocodile", "alligator",
    "scorpion", "skull",
    # 일상에서 보기 어려운 풍경·분위기(우주·극지·사막·섬·성 등)
    "galaxy", "milky", "nebula", "space", "universe", "fantasy", "surreal", "arctic", "antarctic",
    "glacier", "iceberg", "castle", "ruins", "desert", "volcano", "aurora", "mirage", "island",
    "lagoon", "atoll", "waterfall", "canyon", "cliff", "fjord",
}  # fmt: skip
_TOKEN = re.compile(r"[a-z]+")
# 일상 모드: (묶음, 한국어 이름, 검색어, 후보 수). 가족이 흔히 보는 음식·과일·친숙한 동물·쉬운 꽃·일상 풍경·일상 물건만 고른다.
EVERYDAY = [
    ("food", "햄버거", "hamburger", 2), ("food", "피자", "pizza", 2),
    ("food", "짜장면", "jajangmyeon", 2), ("food", "라면", "ramen noodles", 2),
    ("food", "치킨", "fried chicken", 2), ("food", "김밥", "kimbap", 2),
    ("food", "떡볶이", "tteokbokki", 2), ("food", "비빔밥", "bibimbap", 2),
    ("food", "샌드위치", "sandwich", 2), ("food", "스파게티", "spaghetti", 2),
    ("food", "초밥", "sushi", 2), ("food", "케이크", "cake", 2),
    ("food", "아이스크림", "ice cream", 2), ("food", "도넛", "donuts", 2),
    ("food", "감자튀김", "french fries", 2), ("food", "토스트", "toast", 2),
    ("fruit", "사과", "apple", 2), ("fruit", "바나나", "banana", 2),
    ("fruit", "딸기", "strawberry", 2), ("fruit", "수박", "watermelon", 2),
    ("fruit", "포도", "grapes", 2), ("fruit", "귤", "tangerine", 2),
    ("fruit", "복숭아", "peach", 2), ("fruit", "방울토마토", "cherry tomatoes", 2),
    ("fruit", "파인애플", "pineapple", 2), ("fruit", "키위", "kiwi fruit", 2),
    ("animal", "강아지", "puppy", 2), ("animal", "개", "dog", 2),
    ("animal", "고양이", "cat", 2), ("animal", "병아리", "chick", 2),
    ("animal", "기린", "giraffe", 2), ("animal", "다람쥐", "squirrel", 2),
    ("animal", "코끼리", "elephant", 2), ("animal", "호랑이", "tiger", 2),
    ("animal", "원숭이", "monkey", 2), ("animal", "레서판다", "red panda", 2),
    ("animal", "고래", "whale", 2), ("animal", "돌고래", "dolphin", 2),
    ("animal", "토끼", "rabbit", 2), ("animal", "판다", "panda", 2),
    ("animal", "펭귄", "penguin", 2),
    ("flower", "장미", "rose", 2), ("flower", "튤립", "tulip", 2),
    ("flower", "개나리", "forsythia", 1), ("flower", "진달래", "azalea", 1),
    ("flower", "벚꽃", "cherry blossom", 1), ("flower", "해바라기", "sunflower", 1),
    ("flower", "민들레", "dandelion", 1),
    ("scene", "공원 산책로", "park path", 1), ("scene", "단풍길", "autumn leaves road", 1),
    ("scene", "바다 해변", "beach sea", 1), ("scene", "벚꽃길", "cherry blossom street", 1),
    ("scene", "공원 벤치", "park bench", 1), ("scene", "놀이터", "playground", 1),
    ("scene", "눈 쌓인 공원", "snow park", 1), ("scene", "가로수길", "tree lined road", 1),
    ("item", "커피", "coffee cup", 2), ("item", "카페", "cafe interior", 1),
    ("item", "교실", "classroom", 1), ("item", "자전거", "bicycle", 1),
    ("item", "버스", "bus", 1), ("item", "기차", "train", 1),
    ("item", "가방", "backpack", 1), ("item", "우산", "umbrella", 1),
    ("item", "연필", "pencils", 1), ("item", "알람시계", "alarm clock", 1),
    ("item", "운동화", "sneakers", 1), ("item", "곰인형", "teddy bear", 1),
    ("item", "풍선", "balloons", 1), ("item", "빵", "bread", 1),
]  # fmt: skip


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


def search_query(
    client: httpx.Client, key: str, q: str, per_page: int, cache_dir: Path, *, now=time.time
) -> list[dict]:
    """검색어 하나로 인기 사진을 검색한다(24시간 캐시, 없으면 요청 뒤 잠시 쉼)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / ("q_" + re.sub(r"[^a-z0-9]+", "_", q.lower()) + f"_{per_page}.json")
    if cache.is_file() and now() - cache.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache.read_text(encoding="utf-8")).get("hits", [])
    params = {
        "key": key,
        "q": q,
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


def run_queries(
    out: Path, key: str, client: httpx.Client, queries: list[tuple] | None = None
) -> list[dict]:
    """일상 모드: 검색어마다 사진을 받아 `img/`·`candidates.json`(묶음·이름·검색어 포함)·`contact_sheet.jpg` 를 만든다."""
    out.mkdir(parents=True, exist_ok=True)
    seen: set[int] = set()
    candidates: list[dict] = []
    files: list[Path] = []
    for group, label, q, want in queries if queries is not None else EVERYDAY:
        hits = search_query(client, key, q, 20, out / ".cache")
        for hit in pick_hits(hits, want, seen):
            no = len(candidates) + 1
            dest = out / "img" / f"{no:03d}.jpg"
            save_resized(client, hit["largeImageURL"], dest)
            files.append(dest)
            candidates.append(
                {
                    "no": no,
                    "pixabay_id": hit["id"],
                    "category": group,
                    "label": label,
                    "query": q,
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
    parser.add_argument("--total", type=int, default=90, help="분류 모드의 후보 사진 수(기본 90)")
    parser.add_argument(
        "--mode",
        choices=["everyday", "category"],
        default="everyday",
        help="everyday: 음식·과일·친숙한 동물·쉬운 꽃·일상 풍경·일상 물건을 검색어로(기본), category: Pixabay 분류별 인기",
    )
    args = parser.parse_args(argv)
    with httpx.Client(follow_redirects=True) as client:
        if args.mode == "everyday":
            found = run_queries(args.out, api_key(), client)
        else:
            found = run(args.out, api_key(), args.total, client)
    print(f"후보 {len(found)}장 저장: {args.out} (contact_sheet.jpg 로 확인하세요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
