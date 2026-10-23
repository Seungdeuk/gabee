"""원본 전처리 테스트. 진짜 OCR 모델은 쓰지 않는다(CI 에 모델·GPU 없음) — 가짜 OCR 을 넣는다."""

import io
import sys
import threading
import types
import zipfile

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import converters
from app.features.ai_assistant.ingest.converters import KoreanOcr, OcrLine, markdown_blocks
from app.features.ai_assistant.ingest.detect import Unsupported, detect
from app.features.ai_assistant.ingest.service import MAX_BYTES, preprocess


class FakeOcr:
    def __init__(self, lines=()):
        self.lines = [OcrLine(t, c) for t, c in lines]
        self.seen = None

    def read(self, image):
        self.seen = image
        return self.lines


def png(size=(400, 300), exif_orientation=None) -> bytes:
    img = Image.new("RGB", size, (240, 240, 240))
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[274] = exif_orientation
        img.save(buf, "JPEG", exif=exif.tobytes())
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def docx(paragraphs) -> bytes:
    """최소 docx: (스타일, 글자) 목록. 스타일 'Heading1' 은 제목."""
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        if s
        else f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"
        for s, t in paragraphs
    )
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    styles = (
        f'<w:styles xmlns:w="{w}"><w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/></w:style></w:styles>'
    )
    files = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>',
        "word/styles.xml": styles,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)
    return buf.getvalue()


def xlsx(rows) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pptx(title) -> bytes:
    from pptx import Presentation

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = title
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def pdf(pages) -> bytes:
    """글자 층이 있는 최소 PDF (영문만 — 기본 글꼴). 빈 문자열이면 글자 없는 쪽."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# ---------- 형식 판별 ----------


@pytest.mark.parametrize(
    "data,name,kind",
    [
        (png(), "a.jpg", "image"),  # 확장자가 아니라 내용으로 판별
        (png(exif_orientation=6), "a.png", "image"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, "a.heic", "image"),
        (pdf(["Hello"]), "a.pdf", "pdf"),
        (docx([(None, "x")]), "a.docx", "docx"),
        (xlsx([["a"]]), "a.xlsx", "xlsx"),
        (pptx("t"), "a.pptx", "pptx"),
        ("이름,금액\n".encode(), "a.csv", "csv"),
        ("<!DOCTYPE html><p>안녕</p>".encode(), "page", "html"),
        ("메모".encode("cp949"), "memo.txt", "text"),
    ],
    ids=[
        "png-as-jpg",
        "jpeg-exif",
        "heic",
        "pdf",
        "docx",
        "xlsx",
        "pptx",
        "csv",
        "html",
        "cp949-txt",
    ],
)
def test_detect_by_content(data, name, kind):
    assert detect(data, name)[0] == kind


@pytest.mark.parametrize(
    "data",
    [
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32,  # 예전 hwp·doc
        b"\x00\x01\x02\x03binary",
    ],
    ids=["old-ole", "binary"],
)
def test_detect_unsupported(data):
    with pytest.raises(Unsupported):
        detect(data, "x.bin")


def test_hwpx_is_unsupported_for_now():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Contents/section0.xml", "<x/>")
    with pytest.raises(Unsupported, match="hwpx"):
        detect(buf.getvalue(), "a.hwpx")


# ---------- 검사 ----------


def test_empty_too_large_and_unsupported_fail_without_raising():
    assert preprocess(b"", "a.jpg").quality.error == "empty_file"
    assert preprocess(b"x" * (MAX_BYTES + 1), "a.bin").quality.error == "too_large"
    r = preprocess(b"\x00\x01binary", "a.bin")
    assert r.quality.status == "failed" and r.quality.error == "unsupported_type"
    assert r.source.sha256 and r.source.size == 8


def test_broken_image_fails():
    r = preprocess(b"\xff\xd8\xff" + b"garbage" * 10, "a.jpg", ocr=FakeOcr())
    assert r.quality.status == "failed" and r.quality.error == "broken_file"


# ---------- 사진 ----------


def test_image_rotated_scaled_and_ocr_lines():
    ocr = FakeOcr([("동대문마트", 0.95), ("합계 2,950", 0.91)])
    r = preprocess(png(size=(400, 300), exif_orientation=6), "receipt.jpg", ocr=ocr)
    assert ocr.seen.mode == "L"  # 흑백
    assert ocr.seen.size[0] < ocr.seen.size[1]  # EXIF 6 → 세로로 돌림
    assert ocr.seen.size == (600, 800)  # 작은 사진은 키운다(최대 2배)
    assert [b.type for b in r.content.blocks] == ["ocr_line", "ocr_line"]
    assert r.content.text == "동대문마트\n합계 2,950"
    assert r.quality.status == "ok" and r.quality.text_confidence == 0.93
    assert r.source.mime == "image/jpeg" and r.source.filename == "receipt.jpg"


def test_image_low_confidence_is_partial_and_no_text_is_ok():
    blurry = preprocess(png(), "a.png", ocr=FakeOcr([("흐린글자", 0.4)]))
    assert blurry.quality.status == "partial" and blurry.quality.warnings
    empty = preprocess(png(), "sea.png", ocr=FakeOcr())
    assert empty.quality.status == "ok" and empty.content.text == ""
    assert "글자가 없어요" in empty.quality.warnings[0]


def test_group_lines_joins_boxes_on_same_row():
    boxes = [
        [[100, 10], [150, 10], [150, 30], [100, 30]],
        [[10, 12], [60, 12], [60, 32], [10, 32]],
        [[10, 60], [60, 60], [60, 80], [10, 80]],
    ]
    lines = converters.group_lines(boxes, ["12,500", "카드결제", "합계"], [0.9, 0.8, 0.7])
    assert [ln.text for ln in lines] == ["카드결제 12,500", "합계"]


def test_ocr_first_read_without_warmup_does_not_deadlock(monkeypatch):
    class Engine:
        def __init__(self, params=None):
            pass

        def __call__(self, arr):
            return types.SimpleNamespace(boxes=[], txts=[], scores=[])

    fake = types.SimpleNamespace(
        RapidOCR=Engine,
        LangRec=types.SimpleNamespace(KOREAN="ko"),
        OCRVersion=types.SimpleNamespace(PPOCRV5="v5"),
        ModelType=types.SimpleNamespace(MOBILE="m"),
    )
    monkeypatch.setitem(sys.modules, "rapidocr", fake)
    done = []
    t = threading.Thread(target=lambda: done.append(KoreanOcr().read(Image.new("L", (8, 8)))))
    t.start()
    t.join(5)
    assert done == [[]]


# ---------- 문서 ----------


def test_docx_heading_and_paragraph():
    r = preprocess(
        docx([("Heading1", "현장체험학습 안내"), (None, "10월 15일 출발")]), "통신문.docx"
    )
    assert r.quality.status == "ok"
    assert [(b.type, b.text) for b in r.content.blocks] == [
        ("heading", "현장체험학습 안내"),
        ("paragraph", "10월 15일 출발"),
    ]


def test_xlsx_becomes_table_block():
    r = preprocess(xlsx([["항목", "금액"], ["전기요금", 48200]]), "관리비.xlsx")
    tables = [b for b in r.content.blocks if b.type == "table"]
    assert tables and "전기요금" in tables[0].text and "48200" in tables[0].text


def test_pptx_title():
    r = preprocess(pptx("가족 여행 계획"), "여행.pptx")
    assert r.quality.status == "ok" and "가족 여행 계획" in r.content.text


def test_pdf_pages_and_scanned_pdf():
    r = preprocess(pdf(["Electricity bill 48200 KRW", "Due date 2026-10-25"]), "bill.pdf")
    assert r.quality.status == "ok" and r.content.pages == 2
    assert {b.page for b in r.content.blocks} == {1, 2}
    scanned = preprocess(pdf(["", ""]), "scan.pdf")
    assert scanned.quality.status == "partial" and "스캔본" in scanned.quality.warnings[0]


def test_csv_in_cp949_and_text():
    r = preprocess("항목,금액\n전기요금,48200\n".encode("cp949"), "가계부.csv")
    assert r.content.blocks[0].type == "table" and "전기요금" in r.content.text
    t = preprocess("# 메모\n\n- 우유\n- 계란\n".encode(), "장보기.md")
    assert [b.type for b in t.content.blocks] == ["heading", "list"]


def test_markdown_blocks_split():
    blocks, pages = markdown_blocks(
        "# 제목\n문단 한 줄\n둘째 줄\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n1. 하나\n2. 둘"
    )
    assert [(b.type, b.level) for b in blocks] == [
        ("heading", 1),
        ("paragraph", None),
        ("table", None),
        ("list", None),
    ]
    assert blocks[1].text == "문단 한 줄\n둘째 줄" and pages is None


# ---------- 번호 (쪽·슬라이드·시트, 순번) ----------


def test_pptx_slides_are_numbered_and_images_dropped():
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = "가족 여행 계획"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "준비물"
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (250, 250, 250)).save(buf, "PNG")
    buf.seek(0)
    s2.shapes.add_picture(buf, Inches(1), Inches(2))
    out = io.BytesIO()
    prs.save(out)
    r = preprocess(out.getvalue(), "여행.pptx")
    assert r.content.pages == 2
    assert [(b.page, b.text) for b in r.content.blocks] == [(1, "가족 여행 계획"), (2, "준비물")]
    assert [b.index for b in r.content.blocks] == [0, 1]
    assert "Slide number" not in r.content.text and "![" not in r.content.text
    # 넘기는 글자: 슬라이드 제목 + 블록 번호가 붙은 마크다운
    assert r.content.text == "## 슬라이드 1\n[1] # 가족 여행 계획\n\n## 슬라이드 2\n[2] # 준비물"


def test_xlsx_sheets_are_numbered():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "10월"
    wb.active.append(["항목", "금액"])
    wb.active.append(["전기요금", 48200])
    ws = wb.create_sheet("11월")
    ws.append(["항목", "금액"])
    ws.append(["관리비", 210000])
    buf = io.BytesIO()
    wb.save(buf)
    r = preprocess(buf.getvalue(), "가계부.xlsx")
    tables = [b for b in r.content.blocks if b.type == "table"]
    assert r.content.pages == 2
    assert [(t.page, t.sheet) for t in tables] == [(1, "10월"), (2, "11월")]
    assert "관리비" in tables[1].text
    text = r.content.text
    assert text.startswith("## 시트 1: 10월\n[")
    assert "## 시트 2: 11월" in text and text.count("10월") == 1  # 시트 이름은 구역 제목에만
    assert [b.index for b in r.content.blocks] == [0, 1]  # 번호가 건너뛰지 않는다
    first_table = text.split("\n")[2]
    assert first_table.startswith(
        "| 항목"
    )  # 표는 번호 다음 줄에서 시작해 마크다운 표가 깨지지 않는다
    assert f"[{tables[1].index + 1}]" in text


def test_numbered_markdown_masks_rrn_before_numbering():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "연락처"
    wb.active.append(["이름", "전화", "주민번호"])
    wb.active.append(["담임", "010-1234-5678", "900101-1234567"])
    buf = io.BytesIO()
    wb.save(buf)
    r = preprocess(buf.getvalue(), "연락처.xlsx")
    text = r.content.text
    assert "## 시트 1: 연락처" in text and "900101-1234567" not in text
    assert "010-1234-5678" not in text and "010-****-****" in text  # 일반 문서도 전화번호는 가린다


# ---------- 개인정보 가리기 ----------

PERSONAL = (
    "성명: 홍길동\n주민등록번호 900101-1234567\n카드 5598-6912-3456-8002\n"
    "전화 010-1234-5678\n이메일 jimin.park@example.com\n입금계좌 110-234-567890\n"
    "결제일 2026-10-22 합계 48,200원"
)


def test_ordinary_documents_mask_contacts_too():
    from app.features.ai_assistant.ingest.masking import mask_text

    counts = __import__("collections").Counter()
    out = mask_text(PERSONAL, counts=counts)
    assert "900101-1234567" not in out and "******-*******" in out
    for gone in ("5598-6912-3456-8002", "010-1234-5678", "jimin.park@example.com"):
        assert gone not in out
    assert "홍**" in out and "5598-****-****-8002" in out
    assert counts["rrn"] == 1 and counts["card"] == 1 and counts["phone"] == 1


def test_sensitive_documents_mask_everything_but_amounts_or_dates():
    from app.features.ai_assistant.ingest.masking import mask_text

    counts = __import__("collections").Counter()
    out = mask_text(PERSONAL, "prescription", counts=counts)
    assert "홍길동" not in out and "홍**" in out
    assert "900101-1234567" not in out and "******-*******" in out
    assert "5598-****-****-8002" in out and "1234-5678" not in out
    assert "j***@example.com" in out and "110-234-567890" not in out
    assert "2026-10-22" in out and "48,200원" in out  # 날짜·금액은 그대로
    assert +counts == {"rrn": 1, "card": 1, "phone": 1, "email": 1, "account": 1, "name": 1}


def test_prescription_extra_masking_keeps_drug_names():
    ocr = FakeOcr(
        [
            ("처방전", 0.95),
            ("성명", 0.9),
            ("김영희", 0.9),
            ("질병분류기호 I10", 0.9),
            ("면허번호 제12345호", 0.9),
            ("주소: 서울시 강남구 테헤란로 1", 0.9),
            ("아모잘탄정 1정 1일 1회 투약일수 30", 0.9),
        ]
    )
    r = preprocess(png(), "처방전.jpg", ocr=ocr)
    text = r.content.text
    assert r.privacy.sensitive == "prescription"
    assert "김영희" not in text and "I10" not in text and "12345" not in text
    assert "테헤란로" not in text and "[주소 가림]" in text
    assert "아모잘탄정" in text and "투약일수 30" in text  # 복약 챙기기에 필요한 것은 남김
    assert len(r.content.blocks) == 7  # 가리기가 줄 수를 바꾸지 않음
    assert r.privacy.masked["name"] == 1 and r.privacy.masked["disease_code"] == 1


def test_documents_are_masked_before_blocks():
    r = preprocess(
        docx([(None, "고객명 박지민 연락처 010-9876-5432 주민등록번호 900101-1234567")]),
        "신청서.docx",
    )
    block = r.content.blocks[0].text
    assert "1234567" not in block and "010-9876-5432" not in block and "박**" in block
    assert r.privacy.sensitive == "none" and r.privacy.masked["rrn"] == 1


def test_id_card_is_fully_masked_then_sent_to_classify():
    from app.features.ai_assistant.ingest.classify import classify

    ocr = FakeOcr(
        [
            ("주민등록증", 0.95),
            ("홍길동(洪吉童)", 0.9),
            ("900101-1234567", 0.9),
            ("서울특별시 종로구 세종대로 209", 0.9),
            ("2020.1.2.", 0.9),
            ("서울특별시 종로구청장", 0.9),
        ]
    )
    r = preprocess(png(), "신분증.jpg", ocr=ocr)
    text = r.content.text
    assert r.privacy.sensitive == "id_card"
    assert "길동" not in text and "1234567" not in text and "세종대로" not in text
    assert len(r.content.blocks) == 6  # 줄 수는 그대로

    sent = []

    def jev(state, questions):
        sent.append(state["text"])
        return {
            "doc_type": {"choice": "주민등록증", "confidence": 0.95},
            "is_document": {"noul": 0.99},
            "domain": {"choice": "행정·공공", "confidence": 0.9},
        }

    c = classify(r, None, jev)
    assert sent == [text]  # 가린 글자만 간다
    assert c.doc_type == "주민등록증" and c.by == "jev"


def test_driver_license_and_passport_numbers_are_masked():
    from app.features.ai_assistant.ingest.masking import is_id_card, mask_text

    lic = "자동차운전면허증\n11-12-345678-90\n홍길동\n서울지방경찰청장"
    assert is_id_card(lic) and "345678" not in mask_text(lic, "id_card")
    pp = "PASSPORT 여권\nPassport No. M12345678\nHONG GILDONG"
    masked_pp = mask_text(pp, "id_card")
    assert is_id_card(pp) and "M12345678" not in masked_pp and "GILDONG" not in masked_pp
    # '여권 챙기기' 같은 여행 메모는 신분증이 아니다(증거가 없음)
    assert not is_id_card("제주 여행 준비물: 여권 챙기기, 선크림")


def test_bankbook_account_numbers_are_masked_but_not_dates():
    from collections import Counter

    from app.features.ai_assistant.ingest.masking import mask_text, sensitive_kind

    book = "KB국민은행 보통예금 통장\n예금주 홍길동\n123456-12-123456\n신규일 2026-10-22"
    assert sensitive_kind(book) == "bankbook"
    counts = Counter()
    out = mask_text(book, "bankbook", counts=counts)
    assert "123456-12-123456" not in out and "******-**-******" in out
    assert "길동" not in out and "2026-10-22" in out
    assert counts["account"] == 1
    assert sensitive_kind("통장에 돈 넣기 2026-10-22") == "none"  # 증거 없는 메모는 아님


def test_family_certificate_masks_every_member():
    from app.features.ai_assistant.ingest.masking import mask_text, sensitive_kind

    cert = (
        "가족관계증명서\n등록기준지 서울특별시 종로구 세종로 1\n"
        "| 구분 | 성명 | 출생연월일 | 주민등록번호 |\n"
        "| 본인 | 홍길동 | 1980년 01월 01일 | 800101-1234567 |\n"
        "| 부 | 홍판서 | 1950년 03월 03일 | 500303-1234567 |\n"
        "| 배우자 | 김영희 | 1982년 05월 05일 | 820505-2234567 |"
    )
    assert sensitive_kind(cert) == "family_cert"
    out = mask_text(cert, "family_cert")
    for gone in ("길동", "판서", "영희", "1234567", "1980년", "세종로"):
        assert gone not in out
    assert "| 본인 | 홍** |" in out and "[등록기준지 가림]" in out


# ---------- 원본 데이터 센터 ----------


def test_ingest_file_keeps_raw_original_and_masks_result(tmp_path):
    from app.features.ai_assistant.ingest.raw_store import LocalRawStore
    from app.features.ai_assistant.ingest.service import ingest_file

    store = LocalRawStore(tmp_path)
    data = png()
    ocr = FakeOcr([("주민등록번호 900101-2345678", 0.9)])
    r = ingest_file("g01", data, "a.png", store=store, ocr=ocr, llm=lambda p, system: {})
    assert "2345678" not in r.content.text  # 결과는 가린 글자
    assert store.get(r.raw_path) == data  # 원본은 그대로
    assert r.raw_path.startswith("g01/") and r.raw_path.endswith(".png")
    again = ingest_file("g01", data, "b.png", store=store, ocr=ocr, llm=lambda p, system: {})
    assert (
        again.raw_path == r.raw_path and len(list(tmp_path.rglob("*.png"))) == 1
    )  # 같은 원본은 한 번만


# ---------- 사진 전처리: 화면용 사본 ----------


def test_display_copy_is_small_webp_without_location():
    from app.features.ai_assistant.ingest.converters import make_display_copy

    big = Image.new("RGB", (4000, 3000), (200, 120, 40))
    exif = Image.Exif()
    exif[274] = 6  # 휴대폰을 세워 찍음 → 90도 돌려야 함
    exif[0x8825] = {1: "N", 2: (37.0, 34.0, 0.0)}  # GPS
    buf = io.BytesIO()
    big.save(buf, "JPEG", exif=exif.tobytes())
    out = Image.open(io.BytesIO(make_display_copy(buf.getvalue())))
    assert out.format == "WEBP" and out.size == (810, 1080)  # 회전 반영 + 긴 변 1080
    assert not out.getexif()  # 촬영 위치·기기 정보 없음


def test_display_copy_does_not_upscale_and_flattens_transparency():
    from app.features.ai_assistant.ingest.converters import make_display_copy

    buf = io.BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(buf, "PNG")
    out = Image.open(io.BytesIO(make_display_copy(buf.getvalue())))
    assert out.size == (300, 200) and out.mode == "RGB"
    assert out.getpixel((10, 10))[0] > 240  # 투명한 곳은 흰 바탕


def test_ingest_file_keeps_original_and_adds_display_copy(tmp_path):
    from app.features.ai_assistant.ingest.raw_store import LocalRawStore
    from app.features.ai_assistant.ingest.service import ingest_file

    store = LocalRawStore(tmp_path)
    data = png((2000, 1500))
    r = ingest_file("g01", data, "a.png", store=store, ocr=FakeOcr(), faces=None)
    assert store.get(r.raw_path) == data  # 원본은 손대지 않음
    assert r.display_path.endswith(".display.webp")
    assert Image.open(io.BytesIO(store.get(r.display_path))).size == (1080, 810)
    doc = ingest_file("g01", "메모".encode(), "a.txt", store=store, llm=lambda p, system: {})
    assert doc.display_path is None  # 사진이 아니면 사본 없음
    with __import__("pytest").raises(ValueError):
        store.put_copy("g01", "0" * 64, "../x", ".webp", b"")


def test_ingest_file_keeps_unsupported_original_but_not_empty(tmp_path):
    from app.features.ai_assistant.ingest.raw_store import LocalRawStore
    from app.features.ai_assistant.ingest.service import ingest_file

    store = LocalRawStore(tmp_path)
    old = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
    r = ingest_file("g01", old, "문서.hwp", store=store)
    assert r.quality.error == "unsupported_type" and r.raw_path.endswith(".bin")
    assert ingest_file("g01", b"", "x", store=store).raw_path is None


def test_raw_store_rejects_bad_ids_and_paths(tmp_path):
    from app.features.ai_assistant.ingest.raw_store import LocalRawStore

    store = LocalRawStore(tmp_path)
    with pytest.raises(ValueError):
        store.put("../etc", "a" * 64, ".png", b"x")
    with pytest.raises(ValueError):
        store.get("../../secret.txt")


@pytest.mark.parametrize(
    "line", ["주민등록번호 5x0101-2****", "주민번호: 900101-2", "외국인등록번호 910101 5123456"]
)
def test_rrn_after_label_is_masked_even_if_ocr_garbled(line):
    from app.features.ai_assistant.ingest.masking import mask_text

    out = mask_text(line)
    assert out.endswith("******-*******") and "0101" not in out
