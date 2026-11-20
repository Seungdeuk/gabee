"""찰칵 흔한 사진 자동 보충의 Pixabay 클라이언트: 검색어로 후보를 찾고, 사진은 서버로 직접 내려받아 JPEG 로 줄인다.

- 키는 `settings.pixabay_api_key`(환경변수 `PIXABAY_API_KEY`)에서만 읽는다. 로그·오류 글에는 키(요청 주소 포함)를 넣지 않는다.
- Pixabay 규칙: 응답은 24시간 캐시하고(같은 검색어는 다시 요청하지 않음), 요청 사이를 띄우며, 사진은 핫링크하지 않고 우리 쪽에 저장한다.
- 검색어는 `scripts/fetch_pixabay_seed.py` 의 일상 목록과 같은 소재 기준이다(scripts 는 서버 이미지에 안 들어가서 여기에 둔다).
"""

import io
import logging
import re
import time

import httpx
from PIL import Image

# httpx 는 요청 주소를 INFO 로 찍는데 Pixabay 요청 주소에는 API 키가 들어 있다. 로그에 키가 남지 않게 올려 둔다
logging.getLogger("httpx").setLevel(logging.WARNING)

API = "https://pixabay.com/api/"
LICENSE = "Pixabay Content License"
CACHE_SECONDS = 24 * 3600
REQUEST_GAP = 1.2  # 초. 분당 100건 제한보다 훨씬 천천히
SIDE_PX = 1280
PER_PAGE = 20
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024

# (묶음, 검색어). 11/19 사용자 검토: 열기구·기차·우산·연필·알람시계·초밥·운동화는 뺐다. 가족이 흔히 보는 음식·과일·친숙한 동물·쉬운 꽃·일상 풍경·일상 물건만.
QUERIES: list[tuple[str, str]] = [
    ("food", "hamburger"),
    ("food", "pizza"),
    ("food", "jajangmyeon"),
    ("food", "ramen noodles"),
    ("food", "fried chicken"),
    ("food", "kimbap"),
    ("food", "tteokbokki"),
    ("food", "bibimbap"),
    ("food", "sandwich"),
    ("food", "spaghetti"),
    ("food", "cake"),
    ("food", "ice cream"),
    ("food", "donuts"),
    ("food", "french fries"),
    ("food", "toast"),
    ("food", "cookies"),
    ("food", "crackers"),
    ("food", "pudding"),
    ("fruit", "apple"),
    ("fruit", "banana"),
    ("fruit", "strawberry"),
    ("fruit", "watermelon"),
    ("fruit", "grapes"),
    ("fruit", "tangerine"),
    ("fruit", "peach"),
    ("fruit", "cherry tomatoes"),
    ("fruit", "pineapple"),
    ("fruit", "kiwi fruit"),
    ("animal", "puppy"),
    ("animal", "dog"),
    ("animal", "cat"),
    ("animal", "chick"),
    ("animal", "giraffe"),
    ("animal", "squirrel"),
    ("animal", "elephant"),
    ("animal", "tiger"),
    ("animal", "monkey"),
    ("animal", "red panda"),
    ("animal", "whale"),
    ("animal", "dolphin"),
    ("animal", "rabbit"),
    ("animal", "panda"),
    ("animal", "penguin"),
    ("flower", "rose"),
    ("flower", "tulip"),
    ("flower", "forsythia"),
    ("flower", "azalea"),
    ("flower", "cherry blossom"),
    ("flower", "sunflower"),
    ("flower", "dandelion"),
    ("flower", "freesia"),
    ("flower", "rose of sharon"),
    ("flower", "lily"),
    ("scene", "park path"),
    ("scene", "autumn leaves road"),
    ("scene", "beach sea"),
    ("scene", "cherry blossom street"),
    ("scene", "park bench"),
    ("scene", "playground"),
    ("scene", "snow park"),
    ("scene", "tree lined road"),
    ("scene", "classroom"),
    ("scene", "bedroom"),
    ("scene", "movie theater"),
    ("scene", "library"),
    ("scene", "living room"),
    ("scene", "kitchen"),
    ("scene", "bathroom"),
    ("scene", "supermarket"),
    ("scene", "bakery"),
    ("scene", "restaurant"),
    ("scene", "amusement park"),
    ("scene", "swimming pool"),
    ("scene", "zoo"),
    ("scene", "museum"),
    ("scene", "bookstore"),
    ("scene", "ocean"),
    ("scene", "mountain path"),
    ("item", "coffee cup"),
    ("item", "cafe interior"),
    ("item", "bicycle"),
    ("item", "bus"),
    ("item", "backpack"),
    ("item", "teddy bear"),
    ("item", "bread"),
]

# 태그에 하나라도 있으면 뺀다: 얼굴 중심(초상·셀카·웨딩), 글자·브랜드·간판(사람·손발이 함께 찍힌 건 허용), 무섭거나 징그러운 동물, 낯선 풍경, 술, 장례·병원
BAD_TAGS = {
    "portrait", "face", "wedding", "bride", "groom", "selfie", "smile", "text", "sign", "logo", "poster", "typography", "letter", "letters", "label", "brand",
    "advertisement", "menu", "banner", "billboard", "newspaper", "words", "quote",
    "snake", "lizard", "gecko", "reptile", "reptiles", "insect", "insects", "spider", "beetle",
    "bug", "wasp", "bee", "bees", "ant", "ants", "fly", "mosquito", "cockroach", "worm",
    "caterpillar", "butterfly", "moth", "dragonfly", "frog", "toad", "crocodile", "alligator",
    "scorpion", "skull",
    "galaxy", "milky", "nebula", "space", "universe", "fantasy", "surreal", "arctic", "antarctic",
    "glacier", "iceberg", "castle", "ruins", "desert", "volcano", "aurora", "mirage", "island",
    "lagoon", "atoll", "waterfall", "canyon", "cliff", "fjord",
    "beer", "wine", "alcohol", "cocktail", "whisky", "whiskey", "liquor", "champagne", "vodka",
    "chrysanthemum", "funeral", "grave", "cemetery", "hospital", "medical", "syringe",
}  # fmt: skip
_TOKEN = re.compile(r"[a-z]+")


class PixabayError(RuntimeError):
    """Pixabay 요청이 실패했다. 메시지에는 요청 주소(키가 들어 있다)를 넣지 않는다."""


def is_clean(hit: dict) -> bool:
    """사진 주소가 있고 태그에 나쁜 단어가 하나도 없으면 참."""
    if not hit.get("largeImageURL") or hit.get("id") is None:
        return False
    tokens = set(_TOKEN.findall(str(hit.get("tags", "")).lower()))
    return not (tokens & BAD_TAGS)


class PixabayClient:
    """검색(`search`)과 사진 내려받기(`download`)."""

    def __init__(
        self,
        key: str,
        client: httpx.Client | None = None,
        gap: float = REQUEST_GAP,
        now=time.monotonic,
        sleep=time.sleep,
    ):
        self._key = key
        self._client = client or httpx.Client(follow_redirects=True)
        self._gap = gap
        self._now = now
        self._sleep = sleep
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._last = 0.0

    def _wait(self) -> None:
        wait = self._last + self._gap - self._now()
        if wait > 0 and self._last:
            self._sleep(wait)
        self._last = self._now()

    def search(self, q: str) -> list[dict]:
        """검색어 하나의 인기 사진(24시간 안에 같은 검색어는 캐시)."""
        cached = self._cache.get(q)
        if cached and self._now() - cached[0] < CACHE_SECONDS:
            return cached[1]
        self._wait()
        params = {
            "key": self._key,
            "q": q,
            "image_type": "photo",
            "orientation": "horizontal",
            "safesearch": "true",
            "order": "popular",
            "min_width": 1280,
            "per_page": PER_PAGE,
        }
        try:
            response = self._client.get(API, params=params, timeout=30)
            response.raise_for_status()
            hits = response.json().get("hits", [])
        except Exception as exc:  # noqa: BLE001  주소에 키가 있어 종류만 남긴다
            raise PixabayError(f"search failed: {type(exc).__name__}") from None
        self._cache[q] = (self._now(), hits)
        return hits

    def download(self, hit: dict) -> bytes:
        """`largeImageURL` 을 내려받아 긴 변 1280px JPEG(품질 80)로 돌려준다."""
        try:
            response = self._client.get(hit["largeImageURL"], timeout=60)
            response.raise_for_status()
            if len(response.content) > MAX_DOWNLOAD_BYTES:
                raise ValueError("too large")
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise PixabayError(f"download failed: {type(exc).__name__}") from None
        image.thumbnail((SIDE_PX, SIDE_PX), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80)
        return out.getvalue()
