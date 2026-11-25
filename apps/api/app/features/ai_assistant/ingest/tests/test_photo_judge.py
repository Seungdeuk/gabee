"""외부 AI 로 보낼 사진 JPEG 만들기(`photo_judge.to_judge_jpeg`, 놀이 기능이 쓴다)는 위치·주석 메타데이터를 남기지 않는다.

예전의 로컬 OCR 문서 판별(`photo_judge.judge`)과 그 시험은 로컬 OCR 을 서비스에서 제거하면서 지웠다(ADR 0025).
사진 판별은 로컬 SigLIP2 단독이다(`test_siglip_margin.py`, `ai_assistant/tests/test_photo_classify_siglip.py`)."""

import io

from PIL import Image

from app.features.ai_assistant.ingest import photo_judge


def test_the_jpeg_sent_outside_has_no_exif_location_or_comment():
    img = Image.new("RGB", (800, 600), (240, 240, 240))
    exif = img.getexif()
    exif[0x010F] = "TestCam"
    exif[0x8825] = {1: "N", 2: (37.0, 33.0, 59.0)}
    src = io.BytesIO()
    img.save(src, format="JPEG", exif=exif, comment=b"secret-comment")
    sent = photo_judge.to_judge_jpeg(src.getvalue())
    with Image.open(io.BytesIO(sent)) as out:
        assert max(out.size) <= photo_judge.READ_SIDE_PX
        assert 0x8825 not in out.getexif() and 0x010F not in out.getexif()
        assert not out.info.get("comment")


def test_the_local_ocr_judge_is_gone():
    assert not hasattr(photo_judge, "judge")  # 로컬 OCR 판별은 서비스에 없다(ADR 0025)
