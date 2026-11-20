"""합성 장면 이미지 생성(시험·실제 모델 임베딩 고정 자료용). 실제 가족 사진이 아니다: 색·도형·무늬로 만든 서로 다른 '장면' 3종과, 장면마다 조금씩 다른 변형 사진.
표준 라이브러리와 Pillow 만 쓴다(torch 가 있는 별도 환경의 스크립트 `scripts/siglip2_scene_fixture.py` 도 이 파일을 경로로 불러 쓴다)."""

import io
import random

from PIL import Image, ImageDraw

SCENES = ("red_circle", "blue_stripes", "green_checker")
VARIANTS = 4
SIZE = 224


def scene_image(scene: str, variant: int) -> Image.Image:
    rng = random.Random(f"{scene}-{variant}")
    jitter = rng.randint(-12, 12)
    if scene == "red_circle":
        img = Image.new("RGB", (SIZE, SIZE), (245, 245, 235))
        d = ImageDraw.Draw(img)
        cx, cy, r = 112 + jitter, 112 - jitter // 2, 70 + variant * 3
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(200 + variant * 5, 30, 40))
    elif scene == "blue_stripes":
        img = Image.new("RGB", (SIZE, SIZE), (20, 40, 120 + variant * 8))
        d = ImageDraw.Draw(img)
        for x in range(0 + jitter % 8, SIZE, 28):
            d.rectangle((x, 0, x + 12, SIZE), fill=(230, 235, 250))
    else:
        img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        d = ImageDraw.Draw(img)
        step = 32 + variant * 2
        for i in range(0, SIZE, step):
            for j in range(0, SIZE, step):
                if (i // step + j // step) % 2 == 0:
                    d.rectangle((i, j, i + step, j + step), fill=(30, 140 + variant * 10, 50))
    return img


def jpeg_bytes(scene: str, variant: int, quality: int = 90) -> bytes:
    out = io.BytesIO()
    scene_image(scene, variant).save(out, format="JPEG", quality=quality)
    return out.getvalue()


def signature(data: bytes) -> list[int]:
    """저장·재압축돼도 거의 같은 값이 되는 작은 지문(8×8 RGB 평균). 같은 사진을 가려내는 데만 쓴다."""
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((8, 8), Image.Resampling.BOX)
    return [v for px in img.getdata() for v in px]
