"""빈 서식 PDF 의 칸을 찾아 가상 값을 그려 넣는다.

칸은 PDF 에 그려진 가는 선(표 테두리)으로 찾는다: 이름 글자(글자층)가 든 칸을 찾고, 그 오른쪽·아래 칸이 비어 있으면 값을 쓴다.
"""

import ctypes
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageDraw, ImageFont

SCALE = 2.6  # PDF 1pt = 2.6px (A4 가 약 1547x2187)
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
INK = (22, 24, 58)
TOL = 1.8  # 선이 칸 안쪽 범위를 덮는지 볼 때의 오차(pt)


@dataclass
class Cell:
    left: float
    bottom: float
    right: float
    top: float  # PDF 좌표(원점 아래쪽, 단위 pt)

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2

    @property
    def cy(self) -> float:
        return (self.bottom + self.top) / 2


class FormPage:
    """한 쪽짜리 서식: 선, 글자층, 칸 찾기."""

    def __init__(self, pdf_path: str) -> None:
        self.doc = pdfium.PdfDocument(pdf_path)
        self.page = self.doc[0]
        self.width, self.height = self.page.get_size()
        self.text = self.page.get_textpage()
        self.vlines: list[tuple[float, float, float]] = []  # x, 아래, 위
        self.hlines: list[tuple[float, float, float]] = []  # y, 왼, 오른
        for obj in self.page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_PATH]):
            self._collect_lines(obj)

    def _collect_lines(self, obj) -> None:
        """경로의 가로·세로 선분을 모은다(사각형 테두리도 네 변으로 들어온다). 글자 모양처럼 마디가 많은 경로는 건너뛴다."""
        count = pdfium_raw.FPDFPath_CountSegments(obj.raw)
        if count > 40:
            return
        a, b, c, d, e, f = obj.get_matrix().get()
        points: list[tuple[float, float, int]] = []
        for i in range(count):
            seg = pdfium_raw.FPDFPath_GetPathSegment(obj.raw, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            pdfium_raw.FPDFPathSegment_GetPoint(seg, x, y)
            points.append(
                (
                    a * x.value + c * y.value + e,
                    b * x.value + d * y.value + f,
                    pdfium_raw.FPDFPathSegment_GetType(seg),
                )
            )
        for (x0, y0, _), (x1, y1, kind) in zip(points, points[1:], strict=False):
            if kind != 0:  # LINETO 만
                continue
            if abs(x1 - x0) < 0.6 and abs(y1 - y0) > 3:
                self.vlines.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
            elif abs(y1 - y0) < 0.6 and abs(x1 - x0) > 3:
                self.hlines.append(((y0 + y1) / 2, min(x0, x1), max(x0, x1)))

    def find_label(self, label: str) -> list[tuple[float, float, float, float]]:
        """글자층에서 label 이 나오는 자리들(위에서 아래로, 같은 줄이면 왼쪽부터)."""
        found = []
        searcher = self.text.search(label)
        while True:
            hit = searcher.get_next()
            if hit is None:
                break
            index, count = hit
            boxes = [self.text.get_charbox(i) for i in range(index, index + count)]
            found.append(
                (
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                )
            )
        found.sort(key=lambda b: (-round((b[1] + b[3]) / 2 / 6), b[0]))
        return found

    def cell_at(self, x: float, y: float) -> Cell | None:
        """(x, y) 를 감싸는 가장 작은 칸. 사방이 선으로 막혀 있어야 한다."""
        xs_left = [lx for lx, b, t in self.vlines if lx <= x and b - TOL <= y <= t + TOL]
        xs_right = [lx for lx, b, t in self.vlines if lx >= x and b - TOL <= y <= t + TOL]
        ys_down = [ly for ly, lo, hi in self.hlines if ly <= y and lo - TOL <= x <= hi + TOL]
        ys_up = [ly for ly, lo, hi in self.hlines if ly >= y and lo - TOL <= x <= hi + TOL]
        if ys_down and ys_up and not (xs_left and xs_right):
            # 표 바깥 테두리가 따로 안 그려진 서식: 위·아래 가로선의 끝을 왼쪽·오른쪽 경계로 본다
            near = (max(ys_down), min(ys_up))
            ends = [
                (lo, hi) for ly, lo, hi in self.hlines if ly in near and lo - TOL <= x <= hi + TOL
            ]
            if ends and not xs_left:
                xs_left = [max(lo for lo, _ in ends)]
            if ends and not xs_right:
                xs_right = [min(hi for _, hi in ends)]
        if not (xs_left and xs_right and ys_down and ys_up):
            return None
        return Cell(max(xs_left), max(ys_down), min(xs_right), min(ys_up))

    def is_blank(self, cell: Cell, pad: float = 1.2) -> bool:
        left, bottom = cell.left + pad, cell.bottom + pad
        right, top = cell.right - pad, cell.top - pad
        if right <= left or top <= bottom:
            return False
        return not self.text.get_text_bounded(left, bottom, right, top).strip()

    def _step(self, label_cell: Cell, mode: str) -> tuple[Cell | None, str]:
        """표 칸 이동(r, r2, d): 이름 칸에서 오른쪽·아래 칸이 비어 있는지."""
        target = label_cell
        for _ in range({"r2": 2, "d2": 2, "d3": 3}.get(mode, 1)):
            if mode.startswith("d"):
                nxt = self.cell_at(target.cx, target.bottom - 2.0)
            else:
                nxt = self.cell_at(target.right + 2.0, target.cy)
            if nxt is None:
                return None, "neighbor_open"
            target = nxt
        if not self.is_blank(target):
            return None, "occupied"
        if target.right - target.left < 14 or target.top - target.bottom < 7:
            return None, "too_small"
        return target, "ok"

    def _inline(self, box: tuple, cell: Cell | None) -> tuple[Cell | None, str]:
        """이름 글자 오른쪽, 같은 줄의 빈 자리(다음 글자나 칸 끝까지)."""
        left, bottom, right, top = box
        limit = cell.right if cell else self.width - 36
        x = right + 1.5
        while (
            x < limit and not self.text.get_text_bounded(x, bottom - 0.5, x + 2, top + 0.5).strip()
        ):
            x += 2
        end = min(limit, x)
        region = Cell(right + 1.5, bottom - 1.5, end - 1.0, top + 1.5)
        if region.right - region.left < 28:
            return None, "no_room"
        return region, "ok"

    def _below(self, box: tuple, cell: Cell | None) -> tuple[Cell | None, str]:
        """이름 글자와 같은 칸 안, 글자 아래쪽 빈 자리."""
        if cell is None:
            return None, "label_cell_open"
        region = Cell(cell.left, cell.bottom, cell.right, box[1] - 0.5)
        if region.top - region.bottom < 11:
            return None, "no_room"
        return (region, "ok") if self.is_blank(region) else (None, "occupied")

    def candidates(self, label: str, mode: str, nth: int) -> tuple[list[Cell], str]:
        """값을 쓸 수 있는 칸 후보(정한 방향, 같은 칸 안(in), 칸 아래(below) 순). (후보들, 하나도 없을 때 사유)"""
        boxes = self.find_label(label)
        if len(boxes) <= nth:
            return [], "label_not_found"
        box = boxes[nth]
        label_cell = self.cell_at((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        why = "label_cell_open"
        found_cells: list[Cell] = []
        for how in dict.fromkeys([mode, "in", "below"]):
            if how in ("r", "r2", "d", "d2", "d3"):
                if label_cell is None:
                    continue
                found, why_now = self._step(label_cell, how)
            elif how == "in":
                found, why_now = self._inline(box, label_cell)
                if found is not None and not self.is_blank(found, pad=0.3):
                    found, why_now = None, "occupied"
            else:
                found, why_now = self._below(box, label_cell)
            if found is not None:
                found_cells.append(found)
            else:
                why = why_now
        return found_cells, why

    def render(self) -> Image.Image:
        return self.page.render(SCALE).to_pil().convert("RGB")


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: float
) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    return [*lines, cur] if cur else lines


def draw_value(
    img: Image.Image, page_h: float, cell: Cell, text: str, align: str = "left"
) -> tuple[int, int, int, int] | None:
    """칸 안에 글자를 맞춰 그린다. 들어가지 않으면 None. 반환: 그린 글자 상자(px)."""
    draw = ImageDraw.Draw(img)
    pad = 2.5 * SCALE
    x0, x1 = cell.left * SCALE + pad, cell.right * SCALE - pad
    y0 = (page_h - cell.top) * SCALE + 1.5 * SCALE
    y1 = (page_h - cell.bottom) * SCALE - 1.5 * SCALE
    width, height = x1 - x0, y1 - y0
    if width < 10 or height < 8:
        return None
    size = min(11.0 * SCALE, height * 0.78)
    while size >= 6.0 * SCALE:
        font = ImageFont.truetype(FONT_PATH, int(size))
        lines = _wrap(draw, text, font, width)
        line_h = size * 1.2
        fits = all(draw.textlength(ln, font=font) <= width for ln in lines)
        if fits and len(lines) * line_h <= height + 1:
            break
        size -= 0.5 * SCALE
    else:
        return None
    top = y0 + (height - len(lines) * line_h) / 2
    y = top
    xmin, xmax = x1, x0
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = x1 - w if align == "right" else x0
        draw.text((x, y), ln, font=font, fill=INK)
        xmin, xmax = min(xmin, x), max(xmax, x + w)
        y += line_h
    return int(xmin), int(top), int(xmax), int(y)
