"""형식별 변환기. 사진은 OCR, 오피스·PDF·텍스트는 MarkItDown 으로 마크다운을 만든 뒤 블록으로 나눈다."""

import datetime as dt
import io
import re
import threading
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, ImageOps

from .schemas import Block, FileKind

try:  # 아이폰 HEIC 사진
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

OCR_MAX_SIDE = 2048
OCR_MIN_SHORT = 720  # 긴 영수증: 짧은 변이 너무 작아지면 글자를 못 읽는다


class BrokenFile(Exception):
    pass


# ---------- 사진 ----------


def prepare_image(data: bytes) -> Image.Image:
    """회전(EXIF) 반영 → 크기 맞추기. 색은 그대로 둔다(OCR 엔진이 스스로 다룬다)."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            img = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as e:  # Pillow 는 깨진 파일에 여러 종류의 예외를 낸다
        raise BrokenFile(f"사진을 열 수 없어요 ({type(e).__name__})") from None
    return _fit_for_ocr(img)


def _fit_for_ocr(img: Image.Image) -> Image.Image:
    w, h = img.size
    long_, short = max(w, h), min(w, h)
    scale = min(1.0, OCR_MAX_SIDE / long_)
    if short * scale < OCR_MIN_SHORT:
        scale = min(OCR_MIN_SHORT / short, 2.0, (OCR_MAX_SIDE * 2) / long_)
    if abs(scale - 1.0) > 0.02:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return img  # 흑백·대비 보정은 하지 않는다(측정: 원본 색 그대로가 글자 오류율이 더 낮다)


DISPLAY_MAX_SIDE = 1080
DISPLAY_QUALITY = 75


def make_display_copy(data: bytes) -> bytes:
    """앱 화면용 사본: 회전(EXIF) 반영 → 긴 변 1080px(키우지 않음) → WebP q75.

    EXIF(촬영 위치·기기 정보)는 옮기지 않는다 — 가족 화면에 위치가 남지 않게.
    이 크기·화질에서는 고지서 글자가 뭉개져서(측정: 글자 일치 0.10~0.38) 보기용으로만 쓰고,
    OCR 은 prepare_image(긴 변 1600px)로 한다.
    """
    try:
        with Image.open(io.BytesIO(data)) as opened:
            img = ImageOps.exif_transpose(opened)
            if img.mode in ("RGBA", "LA", "P"):  # 투명한 부분은 흰 바탕으로
                rgba = img.convert("RGBA")
                img = Image.new("RGB", rgba.size, (255, 255, 255))
                img.paste(rgba, mask=rgba.getchannel("A"))
            else:
                img = img.convert("RGB")
    except Exception as e:  # Pillow 는 깨진 파일에 여러 종류의 예외를 낸다
        raise BrokenFile(f"사진을 열 수 없어요 ({type(e).__name__})") from None
    img.thumbnail((DISPLAY_MAX_SIDE, DISPLAY_MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=DISPLAY_QUALITY, method=4)
    return out.getvalue()


@dataclass
class OcrLine:
    text: str
    confidence: float


class Ocr(Protocol):
    def read(self, image: Image.Image) -> list[OcrLine]: ...


class KoreanOcr:
    """RapidOCR(PP-OCRv5 한국어). 첫 호출 때 모델을 내려받고 만든다(약 13 MB)."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def _get(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

                    self._engine = RapidOCR(
                        params={
                            "Rec.lang_type": LangRec.KOREAN,
                            "Rec.ocr_version": OCRVersion.PPOCRV5,
                            "Rec.model_type": ModelType.MOBILE,
                            "Global.log_level": "warning",
                        }
                    )
        return self._engine

    def read(self, image: Image.Image) -> list[OcrLine]:
        import numpy as np

        engine = (
            self._get()
        )  # 잠금 밖에서: _get 도 같은 잠금을 잡으므로 안에서 부르면 첫 호출이 멈춘다
        arr = np.asarray(image.convert("RGB"))
        with self._lock:
            # 줄 방향 확인(cls)을 켜 두면 짧은 줄을 거꾸로 뒤집어 읽어 줄이 통째로 빠진다(측정: 줄 회수 68% → 끄면 95%).
            # 그래서 끄고 먼저 읽고, 평균 확신도가 낮으면(사진이 뒤집혔을 수 있다) 방향 확인을 켠 결과와
            # 180° 돌려 읽은 결과 중 읽은 줄의 확신도 합이 더 큰 쪽을 쓴다.
            res = engine(arr, use_cls=False)
            if _mean_score(res) < READ_OK_SCORE:
                tries = [
                    res,
                    engine(arr, use_cls=True),
                    engine(np.rot90(arr, 2).copy(), use_cls=False),
                ]
                res = max(tries, key=_score_mass)
        if res is None or not getattr(res, "txts", None):
            return []
        return group_lines(res.boxes, res.txts, res.scores)


READ_OK_SCORE = 0.85  # 평균 확신도가 이 이상이면 한 번 읽은 것으로 끝낸다


def _scores(res) -> list[float]:
    if res is None or not getattr(res, "scores", None):
        return []
    return [float(s) for s in res.scores]


def _mean_score(res) -> float:
    s = _scores(res)
    return sum(s) / len(s) if s else 0.0


def _score_mass(res) -> float:
    """읽은 줄들의 확신도 합: 더 많이, 더 확실하게 읽을수록 크다."""
    return sum(_scores(res))


def group_lines(boxes, txts, scores) -> list[OcrLine]:
    """상자 중심 높이가 비슷한 것끼리 한 줄로 묶고, 줄 안에서는 왼쪽부터 잇는다."""
    items = []
    for box, txt, sc in zip(boxes, txts, scores, strict=False):
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        items.append((sum(ys) / len(ys), min(xs), max(ys) - min(ys), str(txt).strip(), float(sc)))
    items.sort(key=lambda t: (t[0], t[1]))
    rows: list[list[tuple]] = []
    for it in items:
        if rows:
            last = rows[-1]
            ly = sum(r[0] for r in last) / len(last)
            lh = sum(r[2] for r in last) / len(last)
            if abs(it[0] - ly) < 0.6 * max(lh, it[2], 1.0):
                last.append(it)
                continue
        rows.append([it])
    lines = []
    for r in rows:
        r.sort(key=lambda t: t[1])
        text = " ".join(t[3] for t in r if t[3])
        if text:
            lines.append(OcrLine(text=text, confidence=sum(t[4] for t in r) / len(r)))
    return lines


_default_ocr: KoreanOcr | None = None


def default_ocr() -> KoreanOcr:
    global _default_ocr
    if _default_ocr is None:
        _default_ocr = KoreanOcr()
    return _default_ocr


# ---------- 오피스 · PDF · 텍스트 ----------

PDF_OCR_MAX_PAGES = 20  # 스캔 PDF 는 글자 없는 쪽을 앞에서부터 이만큼만 OCR 한다(처리 시간 상한)
PDF_MIN_PAGE_CHARS = (
    8  # 쪽에 글자가 이보다 적으면 스캔 쪽으로 본다(쪽 번호·워터마크 정도는 글자로 치지 않는다)
)


def pdf_page_texts(data: bytes) -> list[str]:
    """PDF 의 쪽별 글자 층(스캔 쪽은 빈 글). 쪽 수는 PDF 자체의 쪽 수다."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:  # 암호가 걸렸거나 깨진 PDF
        raise BrokenFile(f"PDF 를 열 수 없어요 ({type(e).__name__})") from None
    try:
        out = []
        for i in range(len(doc)):
            textpage = doc[i].get_textpage()
            out.append((textpage.get_text_bounded() or "").strip())
            textpage.close()
        return out
    except Exception as e:
        raise BrokenFile(f"PDF 글자를 읽을 수 없어요 ({type(e).__name__})") from None
    finally:
        doc.close()


VIEW_MAX_SIDE = 1600  # 앱에서 원본 PDF 를 볼 때 쪽 그림의 긴 변
VIEW_MAX_PAGES = 100  # 한 PDF 에서 앱으로 보여 주는 최대 쪽 수


def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:
        raise BrokenFile(f"PDF 를 열 수 없어요 ({type(e).__name__})") from None
    try:
        return min(len(doc), VIEW_MAX_PAGES)
    finally:
        doc.close()


def pdf_page_jpeg(data: bytes, index: int) -> bytes:
    """PDF 한 쪽(0부터)을 사람이 보는 용도의 JPEG 로 그린다. 범위를 벗어나면 IndexError."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:
        raise BrokenFile(f"PDF 를 열 수 없어요 ({type(e).__name__})") from None
    try:
        if not 0 <= index < min(len(doc), VIEW_MAX_PAGES):
            raise IndexError(index)
        page = doc[index]
        w, h = page.get_size()
        image = page.render(scale=min(3.0, VIEW_MAX_SIDE / max(w, h, 1.0))).to_pil().convert("RGB")
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
        return out.getvalue()
    finally:
        doc.close()


def pdf_page_images(data: bytes, indexes: list[int]) -> list[Image.Image]:
    """고른 쪽(0부터)을 OCR 하기 좋은 이미지로 바꾼다."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:
        raise BrokenFile(f"PDF 를 열 수 없어요 ({type(e).__name__})") from None
    try:
        images = []
        for i in indexes:
            page = doc[i]
            w, h = page.get_size()  # 단위는 pt(1/72 인치)
            scale = min(3.0, OCR_MAX_SIDE / max(w, h, 1.0))
            images.append(_fit_for_ocr(page.render(scale=scale).to_pil().convert("RGB")))
        return images
    except Exception as e:
        raise BrokenFile(f"PDF 쪽을 그림으로 바꿀 수 없어요 ({type(e).__name__})") from None
    finally:
        doc.close()


DOC_EXT = {
    "pdf": ".pdf",
    "docx": ".docx",
    "xlsx": ".xlsx",
    "pptx": ".pptx",
    "csv": ".csv",
    "html": ".html",
}


XLSX_MAX_ROWS = 5000  # 한 시트에서 읽는 최대 줄 수(아주 큰 표가 서버를 붙잡지 않게)
XLSX_MAX_COLS = 100


def _xlsx_cell(cell) -> str:
    """엑셀 화면에 보이는 모습으로 칸 값을 글로 바꾼다(쉼표·날짜·퍼센트 서식 반영)."""
    v = cell.value
    if v is None:
        return ""
    nf = cell.number_format or "General"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, dt.datetime):
        return (
            v.strftime("%Y-%m-%d %H:%M")
            if (v.hour or v.minute or v.second)
            else v.strftime("%Y-%m-%d")
        )
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.time):
        return v.strftime("%H:%M")
    if isinstance(v, (int, float)):
        decimals = re.search(r"0\.(0+)", nf)
        dec = len(decimals.group(1)) if decimals else 0
        if "%" in nf:
            return f"{v * 100:.{dec}f}%"
        if "," in nf:
            return f"{v:,.{dec}f}"
        if decimals:
            return f"{v:.{dec}f}"
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)
    return str(v).replace("\n", " ").replace("|", "\\|").strip()


def xlsx_to_markdown(data: bytes) -> str:
    """서식을 반영한 엑셀 → 마크다운. MarkItDown(pandas)은 저장된 값 그대로라 금액 쉼표·날짜 서식을 잃고 병합 칸이 `Unnamed`·`NaN` 이 된다.
    여기서는 보이는 값으로 꺼내고, 병합 칸은 걸친 칸마다 같은 값을 채우며, 숨긴 시트는 건너뛴다. 시트마다 `## 시트이름` 과 표 하나."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    out = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        grid: dict[tuple[int, int], str] = {}
        for row in ws.iter_rows(max_row=XLSX_MAX_ROWS, max_col=XLSX_MAX_COLS):
            for c in row:
                grid[(c.row, c.column)] = _xlsx_cell(c)
        for rng in ws.merged_cells.ranges:  # 병합 칸은 걸친 칸마다 같은 값을 채운다
            val = grid.get((rng.min_row, rng.min_col), "")
            for r in range(rng.min_row, min(rng.max_row, XLSX_MAX_ROWS) + 1):
                for c in range(rng.min_col, min(rng.max_col, XLSX_MAX_COLS) + 1):
                    grid[(r, c)] = val
        rows = [
            r
            for r in sorted({r for r, _ in grid})
            if any(grid.get((r, c)) for c in range(1, XLSX_MAX_COLS + 1))
        ]
        if not rows:
            continue
        cols = [c for c in sorted({c for _, c in grid}) if any(grid.get((r, c)) for r in rows)]
        table = [[grid.get((r, c), "") for c in cols] for r in rows]
        lines = [f"## {ws.title}", "| " + " | ".join(table[0]) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(t) + " |" for t in table[1:]]
        out.append("\n".join(lines))
    return "\n\n".join(out)


def to_markdown(data: bytes, kind: FileKind) -> str:
    """마크다운을 만든다. 엑셀은 서식을 반영한 전용 변환(실패하면 MarkItDown), 나머지는 MarkItDown. PDF 는 쪽 사이에 \\f(폼 피드)가 남는다."""
    if kind == "xlsx":
        try:
            return xlsx_to_markdown(data)
        except Exception:  # noqa: BLE001  전용 변환이 못 읽는 파일은 MarkItDown 에 맡긴다
            pass
    from markitdown import MarkItDown, StreamInfo

    try:
        res = MarkItDown(enable_plugins=False).convert_stream(
            io.BytesIO(data), stream_info=StreamInfo(extension=DOC_EXT[kind], charset="utf-8")
        )
    except Exception as e:  # 변환기마다 예외가 다르다
        raise BrokenFile(f"문서를 읽을 수 없어요 ({type(e).__name__})") from None
    return res.markdown or ""


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if _HEADING.match(stripped):
        return "heading"
    if stripped.startswith("|"):
        return "table"
    return "list" if _LIST.match(line) else "paragraph"


_SLIDE = re.compile(r"^<!--\s*Slide number:\s*(\d+)\s*-->$")
_IMAGE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")  # 문서 속 그림 자리 표시 — 글자가 아니다


def _segments(markdown: str, kind: FileKind | None) -> tuple[list[tuple], int | None]:
    """마크다운을 (번호, 시트 이름, 줄 목록) 묶음으로 나눈다. PDF 는 \\f(쪽), PPT 는 슬라이드 표시,
    엑셀은 시트 제목(## 시트이름) 기준. (묶음 목록, 전체 쪽·슬라이드·시트 수)."""
    pages = markdown.split("\f")
    if len(pages) > 1:
        return [(i, None, p.splitlines()) for i, p in enumerate(pages, start=1)], len(pages)
    segs: list[tuple] = []
    no, sheet, cur = None, None, []
    for line in markdown.splitlines():
        stripped = line.strip()
        slide = _SLIDE.match(stripped) if kind == "pptx" else None
        if slide or (kind == "xlsx" and stripped.startswith("## ")):
            segs.append((no, sheet, cur))
            no = int(slide.group(1)) if slide else (no or 0) + 1
            sheet = None if slide else stripped[3:].strip()
            cur = []  # 시트 이름은 블록이 아니라 Block.sheet 로 남긴다(번호가 건너뛰지 않게)
            continue
        cur.append(line)
    segs.append((no, sheet, cur))
    return segs, (no if kind in ("pptx", "xlsx") else None)


def markdown_blocks(markdown: str, kind: FileKind | None = None) -> tuple[list[Block], int | None]:
    """마크다운 → 블록(제목·문단·표·목록)에 쪽·슬라이드·시트 번호와 순번을 붙인다. (블록, 전체 수)."""
    segments, total = _segments(markdown, kind)
    blocks: list[Block] = []

    def add(**kw) -> None:
        blocks.append(Block(index=len(blocks), **kw))

    for page_no, sheet, lines in segments:
        # 빈 줄 하나를 덧붙여 마지막 묶음도 같은 경로로 내보낸다
        buf: list[str] = []
        kind_ = "paragraph"
        for line in [*lines, ""]:
            stripped = "" if _IMAGE.match(line.strip()) else line.strip()
            line_kind = _line_kind(line)
            if buf and (not stripped or line_kind != kind_ or line_kind == "heading"):
                add(type=kind_, text="\n".join(buf).strip(), page=page_no, sheet=sheet)
                buf = []
            if line_kind == "heading" and stripped:
                m = _HEADING.match(stripped)
                add(
                    type="heading",
                    text=m.group(2).strip(),
                    level=len(m.group(1)),
                    page=page_no,
                    sheet=sheet,
                )
            elif stripped:
                buf.append(line.rstrip())
                kind_ = line_kind
    return blocks, total


_SECTION = {"pptx": "슬라이드 {n}", "xlsx": "시트 {n}: {sheet}"}


def numbered_markdown(blocks: list[Block], kind: FileKind | None) -> str:
    """PPT·엑셀 블록을 슬라이드·시트 제목과 블록 번호가 붙은 마크다운으로 다시 쓴다(분류·검색에 넘기는 글자).

        ## 슬라이드 2            ## 시트 1: 10월
        [3] # 준비물            [1]
        [4] 수영복, 선크림      | 항목 | 금액 |

    [n] 은 블록 순번(Block.index + 1)이라 답의 근거를 "몇 번째 블록"으로 되짚을 수 있다.
    표·목록은 번호를 따로 한 줄에 둬서 마크다운 표가 깨지지 않게 한다.
    """
    lines: list[str] = []
    section = None
    for b in blocks:
        if b.page != section:
            section = b.page
            if lines:
                lines.append("")
            fmt = _SECTION.get(kind or "")
            if fmt and b.page is not None:
                lines.append("## " + fmt.format(n=b.page, sheet=b.sheet or "").rstrip(": "))
        tag = f"[{b.index + 1}]"
        if b.type in ("table", "list"):
            lines += [tag, b.text]
        elif b.type == "heading":
            lines.append(f"{tag} {'#' * (b.level or 1)} {b.text}")
        else:
            lines.append(f"{tag} {b.text}")
    return "\n".join(lines).strip()
