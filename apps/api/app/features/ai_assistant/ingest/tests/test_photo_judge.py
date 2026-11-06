"""채팅 사진이 문서 사진인지 일반 사진인지 로컬 OCR 의 글자 수·줄 수로 가른다(외부 전송 없음). 실제 OCR 없이 가짜 OCR 로 돈다.

기준 숫자는 실제 사진 15장(문서 8, 거리·음식 7)을 재서 정했다: 문서 사진은 좋은 글자 147~1050자·8줄 이상, 간판이 많은 거리 사진은 27자 이하."""

import io

from PIL import Image

from app.features.ai_assistant.ingest import photo_judge
from app.features.ai_assistant.ingest.converters import OcrLine


class LinesOcr:
    def __init__(self, lines):
        self.lines = lines
        self.sizes = []

    def read(self, image):
        self.sizes.append(image.size)
        return self.lines


def _jpeg(size=(1600, 1200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (240, 240, 240)).save(out, format="JPEG")
    return out.getvalue()


def _lines(count, chars, confidence=0.9):
    return [OcrLine("가" * chars, confidence) for _ in range(count)]


def test_a_text_heavy_photo_is_a_document():
    verdict = photo_judge.judge(_jpeg(), LinesOcr(_lines(8, 20)))
    assert verdict.kind == photo_judge.DOCUMENT
    assert (verdict.chars, verdict.lines) == (160, 8)


def test_a_photo_with_almost_no_text_is_an_ordinary_photo():
    assert photo_judge.judge(_jpeg(), LinesOcr([])).kind == photo_judge.PHOTO
    street = _lines(6, 4)  # 거리 사진: 간판 글자가 조금 읽힌다(실측 27자)
    assert photo_judge.judge(_jpeg(), LinesOcr(street)).kind == photo_judge.PHOTO


def test_in_between_is_unsure_so_the_user_decides():
    # 글자는 많지만 줄이 적다(큰 글씨 포스터) / 줄은 많지만 글자가 적다
    assert photo_judge.judge(_jpeg(), LinesOcr(_lines(3, 40))).kind == photo_judge.UNSURE
    assert photo_judge.judge(_jpeg(), LinesOcr(_lines(10, 7))).kind == photo_judge.UNSURE


def test_low_confidence_lines_do_not_count_as_text():
    noisy = _lines(10, 20, confidence=0.3)  # 질감을 글자로 잘못 읽은 경우
    verdict = photo_judge.judge(_jpeg(), LinesOcr(noisy))
    assert verdict.kind == photo_judge.PHOTO and (verdict.chars, verdict.lines) == (0, 0)


def test_only_letters_and_digits_count():
    symbols = [OcrLine("-" * 30 + "!" * 30, 0.9) for _ in range(8)]
    assert photo_judge.judge(_jpeg(), LinesOcr(symbols)).kind == photo_judge.PHOTO


def test_the_photo_is_shrunk_before_reading():
    ocr = LinesOcr(_lines(8, 20))
    photo_judge.judge(_jpeg((4000, 3000)), ocr)
    assert max(ocr.sizes[0]) <= photo_judge.READ_SIDE_PX


def test_an_unreadable_image_is_unsure_not_an_error():
    verdict = photo_judge.judge(b"not an image", LinesOcr(_lines(8, 20)))
    assert verdict.kind == photo_judge.UNSURE


def test_an_ocr_failure_is_unsure_not_an_error():
    class Broken:
        def read(self, image):
            raise RuntimeError("model missing")

    assert photo_judge.judge(_jpeg(), Broken()).kind == photo_judge.UNSURE
