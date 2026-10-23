"""전처리가 넘긴 마크다운을 검색용 조각으로 자른다.

규칙: 제목(`# `)과 `분류:` 줄은 모든 조각 앞에 붙이고, `[p.N]` 쪽 표시와 `## ` 제목(슬라이드 등)에서 구역을
나누고, 구역이 길면 줄 단위로 잘라 max_chars 안에 맞춘다. 읽지 못한 부분 표시는 글에 그대로 둔다."""

import re
from dataclasses import dataclass

UNREAD_MARK = "[읽지 못한 부분]"
DOUBT_MARK = "[불확실]"  # 글자 인식이 흐린 줄 끝에 붙인다. 사용자가 확인하면 지운다

PAGE_RE = re.compile(r"^\[p\.(\d+)\]\s*$")
HEAD_RE = re.compile(r"^##\s+(.+?)\s*$")
DEFAULT_MAX_CHARS = 700  # e5 계열은 512 토큰이 한계이고 한국어는 한 토큰이 1.5자쯤이라 여유를 둔 값


@dataclass(frozen=True)
class Chunk:
    seq: int
    page_label: str | None
    text: str


def _header(lines: list[str]) -> tuple[list[str], list[str]]:
    head: list[str] = []
    rest = list(lines)
    if rest and rest[0].startswith("# "):
        head.append(rest.pop(0))
        if rest and rest[0].startswith("분류:"):
            head.append(rest.pop(0))
    return head, rest


def _pack(lines: list[str], limit: int) -> list[str]:
    pieces: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        while len(line) > limit:  # 줄바꿈 없이 아주 긴 줄
            if cur:
                pieces.append("\n".join(cur))
                cur, size = [], 0
            pieces.append(line[:limit])
            line = line[limit:]
        if cur and size + len(line) + 1 > limit:
            pieces.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        pieces.append("\n".join(cur))
    return [p for p in pieces if p.strip()]


def split_markdown(body_md: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    head, rest = _header(body_md.splitlines())
    prefix = "\n".join(head)
    limit = max(max_chars - len(prefix) - 1, 100)

    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in rest:
        page = PAGE_RE.match(line)
        if page:
            sections.append((f"p.{page.group(1)}", []))
            continue
        heading = HEAD_RE.match(line)
        if heading:
            sections.append((heading.group(1), [line]))
            continue
        sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for label, lines in sections:
        for piece in _pack(lines, limit):
            text = f"{prefix}\n{piece}" if prefix else piece
            chunks.append(Chunk(seq=len(chunks), page_label=label, text=text))
    if not chunks:  # 제목만 있는 기록도 찾을 수 있게 한 조각은 남긴다
        chunks.append(Chunk(seq=0, page_label=None, text=prefix or body_md.strip()))
    return chunks
