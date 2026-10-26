"""전처리 결과(PreprocessResult)를 knowledge 기록 한 건으로 바꾼다.

글은 전처리가 이미 개인정보를 가린 뒤의 것(`content.text`)만 쓰고, 원본 글자나 파일 이름은 쓰지 않는다
(파일 이름에 이름 같은 개인정보가 들어 있을 수 있다). 글자 없는 사진은 분류 이름·날짜로 검색되게 글을 만들고,
사용자가 한 줄 설명을 달면 `- 설명:` 줄로 넣는다(없으면 "설명 필요").
"""

import re
from datetime import date

from app.features.ai_assistant.ingest.schemas import PreprocessResult

from .chunking import DOUBT_MARK, UNREAD_MARK

_BLOCK_NUMBER = re.compile(
    r"^\[(\d+)\]", re.M
)  # 전처리의 블록 번호 [3] 은 답의 출처 번호 [n] 과 헷갈리므로 바꾼다
_TITLE_LIMIT = 50
DOUBT_BELOW = 0.8  # 글자 인식 확신도가 이보다 낮은 줄은 [불확실] 로 표시한다
MAX_DOUBTS = 6  # 표시하는 줄 수 상한(질문이 너무 많아지지 않게 가장 흐린 것부터)
# 전화번호·가려진 번호·날짜로 시작하는 줄은 제목으로 쓰지 않는다(영수증 맨 윗줄이 가게 전화번호인 경우가 많다)
_NOT_A_TITLE = re.compile(
    r"^(?:전화|TEL|Tel|tel|T\.|연락처)|^[\d\s\-:.*]+$|^\d{4}[-./]\d{1,2}[-./]\d{1,2}"
)


def to_item(result: PreprocessResult) -> dict:
    """knowledge.service.ingest 에 그대로 넘길 인자들을 만든다."""
    c = result.classification
    plain = _body_text(result.content.text)
    text = _mark_doubts(plain, result)  # 본문에는 [불확실] 표시를, 제목에는 표시 없는 글을 쓴다
    kind = (
        c.doc_type if c and c.doc_type else ("사진" if result.source.kind == "image" else "문서")
    ).strip()
    occurred = _first_date(c.dates if c else [])
    title = _title(plain, kind, occurred)

    lines = [f"# {title}", f"분류: {kind}"]
    if c:
        _add(lines, "태그", ", ".join(c.tags))
        _add(lines, "날짜", ", ".join(c.dates))
        _add(lines, "금액", ", ".join(f"{a.label} {a.value:,}원".strip() for a in c.amounts))
        _add(lines, "장소", ", ".join(c.places))
        for key, value in c.fields.items():
            _add(lines, key, value)
    if text:
        lines.append(text)
    if result.quality.status == "partial":
        lines.append(UNREAD_MARK)

    sensitive = result.privacy.sensitive != "none"
    return {
        "kind_label": kind[:100],
        "title": title,
        "body_md": "\n".join(lines),
        "source_path": result.raw_path,
        "occurred_on": occurred,
        "sensitivity": "sensitive" if sensitive else None,
    }


PHOTO_KIND = "사진"
DESCRIPTION_LABEL = "- 설명:"
DESCRIPTION_MAX = 200


def needs_description(kind_label: str, body_md: str) -> bool:
    """글자가 안 읽힌 사진(분류가 "사진")인데 사용자가 단 설명(`- 설명:` 줄)이 아직 없는 기록."""
    return kind_label == PHOTO_KIND and not any(
        ln.startswith(DESCRIPTION_LABEL) for ln in body_md.splitlines()
    )


def current_description(body_md: str) -> str | None:
    for ln in body_md.splitlines():
        if ln.startswith(DESCRIPTION_LABEL):
            return ln.removeprefix(DESCRIPTION_LABEL).strip()
    return None


def with_description(body_md: str, text: str) -> str:
    """본문에 `- 설명: <text>` 줄을 넣거나(없을 때) 바꾼다(있을 때). 머리글(제목·분류·`- ` 줄들) 끝에 둔다."""
    new = f"{DESCRIPTION_LABEL} {text}"
    lines = body_md.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(DESCRIPTION_LABEL):
            lines[i] = new
            return "\n".join(lines)
    at = min(2, len(lines))
    while at < len(lines) and lines[at].startswith("- "):
        at += 1
    lines.insert(at, new)
    return "\n".join(lines)


def is_default_title(title: str, kind_label: str) -> bool:
    """제목이 글에서 뽑지 못해 붙은 기본값("사진", "사진 2026-10-15")인지."""
    return bool(re.fullmatch(rf"{re.escape(kind_label)}(?: \d{{4}}-\d{{2}}-\d{{2}})?", title))


def _mark_doubts(text: str, result: PreprocessResult) -> str:
    """사진 글자 인식(OCR)에서 확신도가 낮은 줄 끝에 [불확실] 을 붙인다. 줄 수가 맞지 않으면 붙이지 않는다."""
    blocks = [b for b in result.content.blocks if b.type == "ocr_line"]
    lines = text.split("\n")
    if not blocks or len(blocks) != len(lines):
        return text
    doubtful = sorted(
        (
            i
            for i, b in enumerate(blocks)
            if b.confidence is not None and b.confidence < DOUBT_BELOW
        ),
        key=lambda i: blocks[i].confidence,
    )[:MAX_DOUBTS]
    for i in doubtful:
        if lines[i].strip():
            lines[i] = f"{lines[i]} {DOUBT_MARK}"
    return "\n".join(lines)


def needs_review(result: PreprocessResult) -> bool:
    c = result.classification
    return bool(c and c.needs_review) or result.quality.status == "partial" or _has_doubts(result)


def _has_doubts(result: PreprocessResult) -> bool:
    return DOUBT_MARK in _mark_doubts(_body_text(result.content.text), result)


def _add(lines: list[str], label: str, value: str) -> None:
    if value and value.strip():
        lines.append(f"- {label}: {value.strip()}")


def _body_text(text: str) -> str:
    return _BLOCK_NUMBER.sub(lambda m: f"(블록 {m.group(1)})", text.strip())


def _title(text: str, kind: str, day: date | None) -> str:
    for raw in text.splitlines():
        line = re.sub(r"^\(블록 \d+\)\s*", "", raw).strip()
        line = re.sub(r"^[#>*\-\s|]+", "", line).replace("**", "").strip()
        if len(line) >= 2 and not _NOT_A_TITLE.match(line):
            return line[:_TITLE_LIMIT]
    return f"{kind} {day.isoformat()}" if day else kind


def _first_date(values: list[str]) -> date | None:
    for v in values:
        try:
            return date.fromisoformat(v)
        except ValueError:
            continue
    return None
