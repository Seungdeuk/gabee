"""전처리 결과(PreprocessResult)를 knowledge 기록 한 건으로 바꾼다.

글은 전처리가 이미 개인정보를 가린 뒤의 것(`content.text`)만 쓰고, 원본 글자나 파일 이름은 쓰지 않는다
(파일 이름에 이름 같은 개인정보가 들어 있을 수 있다). 글자 없는 사진은 분류 이름·날짜·찍힌 사람·자동 설명으로
검색되게 글을 만들어 준다.
"""

import re
from datetime import date

from app.features.ai_assistant.ingest.schemas import PreprocessResult

from .chunking import UNREAD_MARK

_BLOCK_NUMBER = re.compile(
    r"^\[(\d+)\]", re.M
)  # 전처리의 블록 번호 [3] 은 답의 출처 번호 [n] 과 헷갈리므로 바꾼다
_TITLE_LIMIT = 50
# 전화번호·가려진 번호·날짜로 시작하는 줄은 제목으로 쓰지 않는다(영수증 맨 윗줄이 가게 전화번호인 경우가 많다)
_NOT_A_TITLE = re.compile(
    r"^(?:전화|TEL|Tel|tel|T\.|연락처)|^[\d\s\-:.*]+$|^\d{4}[-./]\d{1,2}[-./]\d{1,2}"
)


def to_item(result: PreprocessResult) -> dict:
    """knowledge.service.ingest 에 그대로 넘길 인자들을 만든다."""
    c = result.classification
    text = _body_text(result.content.text)
    caption = result.caption
    kind = (
        c.doc_type if c and c.doc_type else ("사진" if result.source.kind == "image" else "문서")
    ).strip()
    occurred = _first_date(c.dates if c else [])
    title = _title(text, caption.description if caption else "", kind, occurred)

    lines = [f"# {title}", f"분류: {kind}"]
    if c:
        _add(lines, "태그", ", ".join(c.tags))
        _add(lines, "날짜", ", ".join(c.dates))
        _add(lines, "금액", ", ".join(f"{a.label} {a.value:,}원".strip() for a in c.amounts))
        _add(lines, "장소", ", ".join(c.places))
        for key, value in c.fields.items():
            _add(lines, key, value)
    people = result.people
    if people and (people.names or people.unknown):
        _add(lines, "찍힌 사람", ", ".join(people.names) or "가족이 아닌 사람")
        if people.unknown and people.names:
            _add(lines, "그 밖의 사람", f"{people.unknown}명")
    if caption:
        _add(lines, "자동 설명", f"{caption.description} (자동으로 만든 설명이라 틀릴 수 있어요)")
        _add(lines, "키워드", ", ".join(caption.keywords))
    if text:
        lines.append(text)
    if result.quality.status == "partial":
        lines.append(UNREAD_MARK)

    sensitive = result.privacy.sensitive != "none" or bool(people and people.count)
    return {
        "kind_label": kind[:100],
        "title": title,
        "body_md": "\n".join(lines),
        "source_path": result.raw_path,
        "occurred_on": occurred,
        "sensitivity": "sensitive" if sensitive else None,
    }


def needs_review(result: PreprocessResult) -> bool:
    c = result.classification
    return bool(c and c.needs_review) or result.quality.status == "partial"


def _add(lines: list[str], label: str, value: str) -> None:
    if value and value.strip():
        lines.append(f"- {label}: {value.strip()}")


def _body_text(text: str) -> str:
    return _BLOCK_NUMBER.sub(lambda m: f"(블록 {m.group(1)})", text.strip())


def _title(text: str, description: str, kind: str, day: date | None) -> str:
    for raw in text.splitlines():
        line = re.sub(r"^\(블록 \d+\)\s*", "", raw).strip()
        line = re.sub(r"^[#>*\-\s|]+", "", line).replace("**", "").strip()
        if len(line) >= 2 and not _NOT_A_TITLE.match(line):
            return line[:_TITLE_LIMIT]
    if description:
        return description[:_TITLE_LIMIT]
    return f"{kind} {day.isoformat()}" if day else kind


def _first_date(values: list[str]) -> date | None:
    for v in values:
        try:
            return date.fromisoformat(v)
        except ValueError:
            continue
    return None
