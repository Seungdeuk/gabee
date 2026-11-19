"""PPT 속 그림을 Claude 로 설명해 변환된 글의 그림 자리표시(`![이름](ImageN)`)를 `[그림: …]` 로 바꾼다.

변환기(MarkItDown)는 그림을 이름만 남기고 내용은 버린다. 그림 안의 글자·차트·사진 내용이 검색에 잡히도록
슬라이드마다 그림을 꺼내 한 장씩 설명하게 한다. `INGEST_LLM_OCR` 가 꺼져 있거나 호출이 실패하면 아무것도 바꾸지 않는다.
슬라이드 순서·그림 순서는 파일 안의 관계 파일로 읽는다(새 의존성 없음).
"""

import io
import logging
import posixpath
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

from lxml import etree
from PIL import Image, ImageOps

from app.shared.config import settings
from app.shared.llm import doc_ai

logger = logging.getLogger(__name__)

MAX_FIGURES = 30  # 한 문서에서 설명하는 그림 수 상한(비용)
MIN_SIDE_PX = 150  # 짧은 변이 이보다 작은 그림(아이콘·장식)은 건너뛴다
MAX_MEDIA_BYTES = 15 * 1024 * 1024
SEND_SIDE_PX = 1280
NONE_WORD = "없음"

_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_R_ID = "{" + _NS["r"] + "}id"
_R_EMBED = "{" + _NS["r"] + "}embed"
_PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SLIDE_MARK = re.compile(r"^(<!--\s*Slide number:\s*\d+\s*-->)$", re.M)


def _xml(zf: zipfile.ZipFile, name: str):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(zf.read(name), parser)


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, str]:
    """관계 파일의 {id: 대상 경로(zip 안 절대 경로)}."""
    folder, base = posixpath.split(part)
    rel_name = posixpath.join(folder, "_rels", base + ".rels")
    if rel_name not in zf.namelist():
        return {}
    out = {}
    for r in _xml(zf, rel_name).findall("rel:Relationship", _NS):
        if r.get("TargetMode") == "External":
            continue
        target = r.get("Target", "")
        path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(folder, target))
        )
        out[r.get("Id", "")] = path
    return out


def pptx_pictures(data: bytes) -> list[list[tuple[str, bytes]]]:
    """슬라이드 순서대로, 슬라이드마다 (그림 대체 글, 그림 파일 바이트) 목록. 읽을 수 없으면 빈 목록."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            order = [
                s.get(_R_ID)
                for s in _xml(zf, "ppt/presentation.xml").iterfind(".//p:sldIdLst/p:sldId", _NS)
            ]
            prs_rels = _rels(zf, "ppt/presentation.xml")
            slides = []
            for rid in order:
                slide = prs_rels.get(rid)
                pics: list[tuple[str, bytes]] = []
                if slide and slide in zf.namelist():
                    rels = _rels(zf, slide)
                    for pic in _xml(zf, slide).iterfind(".//p:pic", _NS):
                        blip = pic.find(".//a:blip", _NS)
                        media = rels.get(blip.get(_R_EMBED, "")) if blip is not None else None
                        if not media or media not in zf.namelist():
                            pics.append(("", b""))
                            continue
                        if zf.getinfo(media).file_size > MAX_MEDIA_BYTES:
                            pics.append(("", b""))
                            continue
                        cnv = pic.find("p:nvPicPr/p:cNvPr", _NS)
                        alt = (cnv.get("descr") if cnv is not None else "") or ""
                        pics.append((alt, zf.read(media)))
                slides.append(pics)
            return slides
    except Exception as e:  # noqa: BLE001  깨진 파일은 그림 없이 넘어간다(글 변환은 따로 한다)
        logger.warning("PPT 그림을 꺼내지 못했어요 %s", type(e).__name__)
        return []


def _to_jpeg(raw: bytes) -> bytes | None:
    """보내기 좋은 JPEG 로 바꾼다. 열 수 없는 형식(EMF·SVG 등)이나 너무 작은 그림은 None."""
    if not raw:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            img = ImageOps.exif_transpose(opened)
            if min(img.size) < MIN_SIDE_PX:
                return None
            img = img.convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    img.thumbnail((SEND_SIDE_PX, SEND_SIDE_PX))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _describe(jpeg: bytes) -> str | None:
    """설명 글. 장식뿐이면 빈 글(""), 호출이 실패하면 None."""
    try:
        text = doc_ai.describe_figure(jpeg).text.strip()
    except Exception as e:  # noqa: BLE001  AI 호출 실패는 그림 설명만 비운다
        logger.warning("그림 설명에 실패했어요 %s", type(e).__name__)
        return None
    text = " ".join(text.split())
    return "" if not text or text.strip("`. ") == NONE_WORD else text


def describe_pptx(data: bytes, markdown: str) -> tuple[str, str | None]:
    """변환된 PPT 글의 그림 자리표시를 그림 설명으로 바꾼다. (글, 확인이 필요한 이유)."""
    if not settings.ingest_llm_ocr:
        return markdown, None
    slides = pptx_pictures(data)
    if not any(p for s in slides for p in s):
        return markdown, None
    todo: list[tuple[int, int, bytes]] = []  # (슬라이드 번호 0부터, 그림 순번, jpeg)
    skipped_limit = 0
    for si, pics in enumerate(slides):
        for pi, (_alt, raw) in enumerate(pics):
            jpeg = _to_jpeg(raw)
            if jpeg is None:
                continue
            if len(todo) >= MAX_FIGURES:
                skipped_limit += 1
                continue
            todo.append((si, pi, jpeg))
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda t: _describe(t[2]), todo))
    desc = {(si, pi): d for (si, pi, _), d in zip(todo, results, strict=True)}
    failed = sum(1 for d in results if d is None)

    parts = _SLIDE_MARK.split(markdown)  # [머리글, 표시1, 본문1, 표시2, 본문2, …]
    out = [parts[0]]
    for k in range(1, len(parts), 2):
        si = (k - 1) // 2
        body = parts[k + 1] if k + 1 < len(parts) else ""
        counter = iter(range(len(slides[si]) if si < len(slides) else 0))

        def repl(m, si=si, counter=counter):
            pi = next(counter, None)
            d = desc.get((si, pi))
            return (
                f"[그림: {d}]" if d else m.group(0)
            )  # 설명이 없으면 원래 자리표시(대체 글 포함)를 둔다

        out += [parts[k], _PLACEHOLDER.sub(repl, body) if si < len(slides) else body]
    text = "".join(out)
    notes = []
    if skipped_limit:
        notes.append(
            f"그림이 많아 앞 {MAX_FIGURES}장만 설명했어요(전체 {MAX_FIGURES + skipped_limit}장)"
        )
    if failed:
        notes.append(f"그림 {failed}장은 설명하지 못했어요")
    return text, (". ".join(notes) or None)
