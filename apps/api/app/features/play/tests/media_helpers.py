"""그림·사진 시험 공통 도구. 파일은 시험마다 임시 폴더에만 쓴다."""

import io

from PIL import Image


def png_bytes(size=(120, 90), color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, color + (255,)).save(out, format="PNG")
    return out.getvalue()


def jpeg_bytes(size=(800, 600)) -> bytes:
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = (x * 255 // size[0], y * 255 // size[1], 128)
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size
