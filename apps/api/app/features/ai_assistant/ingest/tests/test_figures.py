"""PPT 속 그림을 설명해 글의 그림 자리표시를 바꾼다(AI 호출은 가짜로 대신한다)."""

import io
from functools import partial

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from app.features.ai_assistant.ingest import converters, figures
from app.shared.config import settings
from app.shared.llm import doc_ai

# 이 시험은 외부 전송이 허용된 가족(동의 있음) 기준이다. `external` 은 필수 인자라 여기서 한 번만 넘긴다. 동의 없는 경우는 test_external_consent.py·test_consent_ingest_flow.py 가 본다.
describe_pptx = partial(figures.describe_pptx, external=True)


def _png(side: int, color: str) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (side, side), color).save(buf, "PNG")
    buf.seek(0)
    return buf


def _deck(slides: list[list[int]]) -> bytes:
    """슬라이드마다 정사각형 그림을 지정한 한 변(px)으로 넣은 PPT. 그림마다 색이 달라 설명을 구분할 수 있다."""
    prs = Presentation()
    colors = iter(["red", "green", "blue", "yellow", "purple"])
    for sides in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "제목"
        for i, side in enumerate(sides):
            slide.shapes.add_picture(_png(side, next(colors)), Inches(1 + i * 2), Inches(2))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    seen: list[bytes] = []

    def fake(jpeg: bytes) -> doc_ai.OcrOut:
        seen.append(jpeg)
        im = Image.open(io.BytesIO(jpeg))
        r, g, b = im.getpixel((5, 5))
        name = (
            "빨간"
            if r > 200 and g < 80
            else "초록"
            if g > 80 and r < 80
            else "파란"
            if b > 200
            else "기타"
        )
        return doc_ai.OcrOut(f"{name} 네모 그림", False, 1, 1)

    monkeypatch.setattr(doc_ai, "describe_figure", fake)
    return seen


def test_pictures_are_read_per_slide_in_order():
    pics = figures.pptx_pictures(_deck([[200], [], [200, 200]]))
    assert [len(s) for s in pics] == [1, 0, 2]


def test_placeholders_become_figure_notes_in_slide_order(llm_on):
    data = _deck([[200], [200, 200]])
    md = converters.to_markdown(data, "pptx")
    out, note = describe_pptx(data, md)
    assert out.count("[그림:") == 3
    assert "![" not in out
    assert out.index("빨간") < out.index("초록") < out.index("파란")
    # 슬라이드 경계가 유지된다: 빨간은 1번, 초록·파란은 2번 슬라이드 안
    first, second = out.split("<!-- Slide number: 2 -->")
    assert "빨간" in first and "초록" in second and "파란" in second
    assert note is None


def test_small_pictures_are_skipped_and_keep_their_placeholder(llm_on):
    data = _deck([[200, 40]])
    md = converters.to_markdown(data, "pptx")
    out, _ = describe_pptx(data, md)
    assert out.count("[그림:") == 1
    assert out.count("![") == 1  # 40px 그림은 설명하지 않고 원래 자리표시가 남는다
    assert len(llm_on) == 1


def test_none_word_means_decoration_and_keeps_placeholder(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(doc_ai, "describe_figure", lambda j: doc_ai.OcrOut("없음", False, 1, 1))
    data = _deck([[200]])
    out, note = describe_pptx(data, converters.to_markdown(data, "pptx"))
    assert "[그림:" not in out and "![" in out
    assert note is None


def test_call_failure_leaves_text_and_reports(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)

    def boom(jpeg):
        raise RuntimeError("down")

    monkeypatch.setattr(doc_ai, "describe_figure", boom)
    data = _deck([[200, 200]])
    md = converters.to_markdown(data, "pptx")
    out, note = describe_pptx(data, md)
    assert out == md
    assert note == "그림 2장은 설명하지 못했어요"


def test_figure_count_is_capped(monkeypatch, llm_on):
    monkeypatch.setattr(figures, "MAX_FIGURES", 2)
    data = _deck([[200, 200, 200]])
    out, note = describe_pptx(data, converters.to_markdown(data, "pptx"))
    assert out.count("[그림:") == 2
    assert note == "그림이 많아 앞 2장만 설명했어요(전체 3장)"


def test_off_when_llm_ocr_is_off(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    called = []
    monkeypatch.setattr(doc_ai, "describe_figure", lambda j: called.append(1))
    data = _deck([[200]])
    md = converters.to_markdown(data, "pptx")
    assert describe_pptx(data, md) == (md, None)
    assert not called


def test_broken_file_does_not_raise(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    assert figures.pptx_pictures(b"not a zip") == []
    assert describe_pptx(b"not a zip", "본문") == ("본문", None)
