"""찰칵 흔한 사진 자동 보충의 Pixabay 클라이언트: 검색어로 후보를 찾고, 사진은 서버로 직접 내려받아 JPEG 로 줄인다.

- 키는 `settings.pixabay_api_key`(환경변수 `PIXABAY_API_KEY`)에서만 읽는다. 로그·오류 글에는 키(요청 주소 포함)를 넣지 않는다.
- Pixabay 규칙: 응답은 24시간 캐시하고(같은 검색어는 다시 요청하지 않음), 요청 사이를 띄우며, 사진은 핫링크하지 않고 우리 쪽에 저장한다.
- 검색어는 `scripts/fetch_pixabay_seed.py` 의 일상 목록과 같은 소재 기준이다(scripts 는 서버 이미지에 안 들어가서 여기에 둔다).
"""

import io
import ipaddress
import json
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

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
MAX_SEARCH_BYTES = 2 * 1024 * 1024  # 검색 응답(JSON)의 상한
MAX_IMAGE_PIXELS = 50_000_000  # 가로×세로 상한(작은 파일이 거대한 그림으로 풀리는 압축 폭탄 방지)
MAX_REDIRECTS = 3
# 서버가 직접 요청해도 되는 주소는 Pixabay 가 공식 문서(https://pixabay.com/api/docs/)에서 보이는 호스트뿐이다:
# 검색은 pixabay.com/api/, 사진(largeImageURL)은 pixabay.com/get/…, 미리보기 등은 cdn.pixabay.com. 응답 JSON 이 가리키는 주소를 그대로 믿지 않는다.
API_HOSTS = frozenset({"pixabay.com"})
IMAGE_HOSTS = frozenset({"pixabay.com", "cdn.pixabay.com"})

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


class UnsafeUrl(PixabayError):
    """허용 호스트(`API_HOSTS`·`IMAGE_HOSTS`) 밖이거나 https 가 아닌 주소. 이 주소로는 요청을 보내지 않는다."""


def check_url(url: object, hosts: frozenset[str]) -> str:
    """서버가 요청해도 되는 주소면 그대로, 아니면 `UnsafeUrl`. https 만, 호스트 이름이 허용 목록과 정확히 같을 때만,
    사용자 정보(`user@`)·443 아닌 포트·제어 문자·공백이 없어야 한다. IP 주소 표기(10진·16진 정수 포함)와 `localhost`·내부 이름은 목록에 없어 막힌다."""
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise UnsafeUrl("unsafe url: malformed")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeUrl("unsafe url: malformed") from None
    if parts.scheme != "https":
        raise UnsafeUrl("unsafe url: scheme")
    if parts.username is not None or parts.password is not None or "\\" in url:
        raise UnsafeUrl("unsafe url: userinfo")
    if port not in (None, 443):
        raise UnsafeUrl("unsafe url: port")
    if (parts.hostname or "") not in hosts:  # urlsplit 이 호스트를 소문자로 준다
        raise UnsafeUrl("unsafe url: host")
    return url


def assert_public_host(host: str) -> None:
    """호스트 이름이 가리키는 주소가 모두 공개 주소여야 한다(사설·루프백·링크 로컬·예약 대역이면 `UnsafeUrl`).
    허용 호스트가 사설 주소로 풀리는 경우(DNS 조작)를 막는다. 연결 직전 확인이라 완전한 차단은 아니며 호스트 허용 목록과 함께 쓴다."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise UnsafeUrl("unsafe url: unresolved") from None
    if not infos:
        raise UnsafeUrl("unsafe url: unresolved")
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise UnsafeUrl("unsafe url: non-public address")


def clean_credit_url(url: object) -> str | None:
    """사진 출처 링크(`pageURL`)로 저장해도 되는 주소만(앱에서 눌러 여는 링크라 Pixabay 주소만 둔다). 아니면 None."""
    try:
        return check_url(url, IMAGE_HOSTS)
    except UnsafeUrl:
        return None


def is_clean(hit: dict) -> bool:
    """사진 주소가 있고 태그에 나쁜 단어가 하나도 없으면 참."""
    if not hit.get("largeImageURL") or hit.get("id") is None:
        return False
    if clean_credit_url(hit["largeImageURL"]) is None:  # 허용 호스트 밖의 사진 주소는 후보에서 뺀다
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
        resolver=assert_public_host,
    ):
        self._key = key
        self._client = client or httpx.Client(follow_redirects=False)
        self._resolver = (
            resolver  # 연결 전에 호스트가 공개 주소인지 본다(시험은 가짜로 바꿔 끼운다)
        )
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
            body = self._fetch(str(httpx.URL(API, params=params)), API_HOSTS, 30, MAX_SEARCH_BYTES)
            hits = json.loads(body).get("hits", [])
        except Exception as exc:  # noqa: BLE001  주소에 키가 있어 종류만 남긴다
            raise PixabayError(f"search failed: {type(exc).__name__}") from None
        self._cache[q] = (self._now(), hits)
        return hits

    def _fetch(self, url: str, hosts: frozenset[str], timeout: float, max_bytes: int) -> bytes:
        """허용 호스트의 https 주소만 받는다. 리다이렉트는 따라가지 않고 직접 따라가되 매번 같은 검사를 한다(최대 `MAX_REDIRECTS` 번).
        응답은 조각으로 읽다가 `max_bytes` 를 넘으면 멈춘다(선언된 길이가 크면 읽지도 않는다)."""
        for _ in range(MAX_REDIRECTS + 1):
            target = check_url(url, hosts)
            self._resolver(urlsplit(target).hostname)
            with self._client.stream(
                "GET", target, timeout=timeout, follow_redirects=False
            ) as response:
                if response.is_redirect:
                    url = urljoin(target, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise ValueError("too large")
                data = bytearray()
                for (
                    chunk
                ) in response.iter_bytes():  # 압축을 푼 바이트로 센다(압축 폭탄도 상한에서 멈춘다)
                    data += chunk
                    if len(data) > max_bytes:
                        raise ValueError("too large")
                return bytes(data)
        raise ValueError("too many redirects")

    def download(self, hit: dict) -> bytes:
        """`largeImageURL` 을 내려받아 긴 변 1280px JPEG(품질 80)로 돌려준다. 주소는 허용 호스트(`IMAGE_HOSTS`)만, API 키는 보내지 않는다."""
        try:
            raw = self._fetch(hit["largeImageURL"], IMAGE_HOSTS, 60, MAX_DOWNLOAD_BYTES)
            opened = Image.open(io.BytesIO(raw))
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ValueError("too many pixels")
            image = opened.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise PixabayError(f"download failed: {type(exc).__name__}") from None
        image.thumbnail((SIDE_PX, SIDE_PX), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80)
        return out.getvalue()
