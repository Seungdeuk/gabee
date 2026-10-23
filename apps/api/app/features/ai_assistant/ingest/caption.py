"""글자 없는 사진에 한국어 설명과 키워드를 붙인다.

로컬 이미지 모델(Ollama 의 qwen2.5vl)만 쓰고 사진은 서버 밖으로 나가지 않는다. 모델이 꺼져 있거나 답이 깨지면
None 을 돌려주고, 호출한 쪽은 설명 없이 계속한다(사진은 분류 이름과 날짜·찍힌 사람으로만 검색된다).
작은 모델이라 틀릴 수 있다: 없는 것을 쓰지 않게 하고, 사람 이름·나이는 추측하지 않게 하고, 글자는 옮기지 않게 한다.
"""

import base64
import io
import json
import re
from collections import Counter
from typing import Protocol

import httpx
from PIL import Image, ImageOps

from app.shared.config import settings

from . import masking
from .schemas import Caption

MAX_SIDE = 768  # 모델에 보내기 전 긴 변을 줄인다(속도를 크게 줄이고 설명 품질은 거의 같다)
MAX_DESCRIPTION = 200
MAX_KEYWORDS = 5
PROMPT = (
    "이 사진을 보고 JSON 객체 하나로만 답하세요. description 에는 사진에 실제로 보이는 장소·사물·동물·"
    "사람 수와 하는 일을 한국어 한 문장으로 쓰고, keywords 에는 검색에 쓸 한국어 낱말을 5개 이하로 넣으세요.\n"
    '예: {"description": "공원 벤치에서 두 사람이 책을 읽고 있다", "keywords": ["공원", "벤치", "독서"]}\n'
    "예시를 그대로 따라 쓰지 말고 이 사진에 보이는 것만 쓰세요. 확실하지 않으면 쓰지 마세요. "
    "사람의 이름·나이·직업을 추측하지 마세요. 사진 속 글자는 옮겨 적지 말고 무엇인지만 말하세요."
)
MAX_TOKENS = (
    200  # 모델이 같은 말을 되풀이하며 끝나지 않는 경우를 끊는다(한국어 한 문장은 보통 60토큰 안쪽)
)
# 지시문이나 예시를 설명으로 되돌려 주는 경우를 걸러낸다
_ECHOES = ("사진에 실제로 보이는", "검색에 쓸", "공원 벤치에서 두 사람이 책을")


class Captioner(Protocol):
    def describe(self, image: bytes) -> Caption | None: ...


class OllamaCaptioner:
    def describe(self, image: bytes) -> Caption | None:
        try:
            small = _shrink(image)
        except Exception:  # noqa: BLE001  깨진 이미지는 전처리가 이미 걸러 낸다. 여기서는 설명만 건너뛴다
            return None
        body = {
            "model": settings.caption_model,
            "stream": False,
            "format": "json",
            "keep_alive": settings.ollama_keep_alive,
            "options": {"temperature": 0, "num_predict": MAX_TOKENS},
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [base64.b64encode(small).decode()],
                }
            ],
        }
        try:
            res = httpx.post(
                f"{settings.local_llm_url.rstrip('/')}/api/chat",
                json=body,
                timeout=settings.caption_timeout,
            )
            res.raise_for_status()
            data = json.loads(res.json()["message"]["content"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return _clean(data)


def default_captioner() -> Captioner | None:
    return OllamaCaptioner() if settings.caption_enabled else None


def _shrink(image: bytes) -> bytes:
    with Image.open(io.BytesIO(image)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)  # EXIF(위치 정보)는 저장하지 않는다
        return out.getvalue()


def _text(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    return masking.mask_text(
        text, "none", counts=Counter()
    )  # 모델이 지어낸 번호가 있어도 한 번 더 가린다


def _clean(data) -> Caption | None:
    if not isinstance(data, dict):
        return None
    description = _text(data.get("description"), MAX_DESCRIPTION)
    if not description or description.startswith(_ECHOES):
        return None
    raw = data.get("keywords")
    words = [_text(w, 20) for w in raw] if isinstance(raw, list) else []
    keywords = list(dict.fromkeys(w for w in words if w))[:MAX_KEYWORDS]
    return Caption(description=description, keywords=keywords)
