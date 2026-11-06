"""위치 구간을 검색용 요약 문장으로 바꾼다(규칙만 쓰고 LLM·DB·네트워크를 쓰지 않는다).

입력은 사람별 시간 구간(Span)이다. 같은 곳에 끊김 없이 이어서 머문 구간은 한 번의 방문으로 합치고, 하루 경계(자정)에서 잘라
조각마다 날짜·요일·시각이 문장에 들어가게 한다. 문장에는 좌표를 넣지 않는다.

조각 종류(kind)
- span: 구간 하나(머묾·일시정지·동의 없음·평소 구역 밖), 하루 경계로 자른 것
- move: 이동 구간 하나(출발지 → 도착지), 하루 경계로 자른 것
- day: 사람별 하루 요약(그날 머문 곳을 순서대로)
- place: 사람별 장소 요약(기간 안 방문 횟수와 시각) — "몇 번 갔어?" 같은 횟수 질문용
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

WEEKDAYS = "월화수목금토일"
KINDS = ("stay", "move", "paused", "no_consent", "anomaly")


@dataclass(frozen=True)
class Span:
    """한 사람의 한 구간. place 는 머문 곳 또는 이동의 도착지 이름, origin 은 이동의 출발지 이름."""

    person_id: str
    person_name: str
    start: datetime
    end: datetime
    kind: str
    place: str | None = None
    origin: str | None = None


@dataclass(frozen=True)
class ChunkDraft:
    person_id: str
    kind: str  # span | move | day | place
    starts_at: datetime
    ends_at: datetime
    text: str
    place: str | None = None  # span(머묾)·place 조각의 장소 이름. 평가와 디버깅에 쓴다


def merge_spans(spans: list[Span]) -> list[Span]:
    """같은 사람의 이어진 같은 종류·같은 장소 구간을 합친다(시간대별·하루별로 쪼개진 구간을 한 번으로 본다)."""
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.person_id, x.start)):
        prev = out[-1] if out else None
        if (
            prev
            and prev.person_id == s.person_id
            and prev.kind == s.kind
            and prev.end == s.start
            and prev.place == s.place
            and prev.origin == s.origin
            and s.kind in ("stay", "paused", "no_consent")
        ):
            out[-1] = Span(
                prev.person_id, prev.person_name, prev.start, s.end, s.kind, s.place, s.origin
            )
        else:
            out.append(s)
    return out


def split_by_day(span: Span) -> list[Span]:
    """구간을 자정 기준으로 잘라 날짜별 조각으로 만든다."""
    out: list[Span] = []
    cur = span.start
    while cur < span.end:
        midnight = datetime.combine(cur.date() + timedelta(days=1), time(0), tzinfo=cur.tzinfo)
        nxt = min(span.end, midnight)
        out.append(
            Span(span.person_id, span.person_name, cur, nxt, span.kind, span.place, span.origin)
        )
        cur = nxt
    return out


def _date(d: datetime) -> str:
    return f"{d.month:02d}-{d.day:02d}({WEEKDAYS[d.weekday()]})"


def _hm(d: datetime, end_of_day: bool = False) -> str:
    if end_of_day and d.hour == 0 and d.minute == 0:
        return "24:00"
    return f"{d.hour:02d}:{d.minute:02d}"


def _what(s: Span) -> str:
    if s.kind == "stay":
        return f"{s.place}에서 머묾"
    if s.kind == "move":
        return f"{s.origin}에서 {s.place}(으)로 이동"
    if s.kind == "paused":
        return "위치 공유 일시정지(여행 모드), 위치 기록 없음"
    if s.kind == "no_consent":
        return "위치 공유에 동의하지 않은 시간, 위치 기록 없음"
    return "평소 활동 구역 밖에 있었음(이상 위치 기록)"


def span_text(s: Span) -> str:
    return f"{s.person_name} | {_date(s.start)} {_hm(s.start)}~{_hm(s.end, True)} | {_what(s)}"


def _duration(a: datetime, b: datetime) -> str:
    minutes = int((b - a).total_seconds() // 60)
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h and m else (f"{h}시간" if h else f"{m}분")


def build_chunks(spans: list[Span]) -> list[ChunkDraft]:
    """모든 사람의 구간에서 검색 조각(span·day·place)을 만든다. 같은 입력이면 항상 같은 결과다."""
    merged = merge_spans(spans)
    drafts: list[ChunkDraft] = []

    # 1) 구간 조각: 하루 경계로 자른다
    day_pieces: list[Span] = []
    for s in merged:
        for piece in split_by_day(s):
            day_pieces.append(piece)
            drafts.append(
                ChunkDraft(
                    piece.person_id,
                    "move" if piece.kind == "move" else "span",
                    piece.start,
                    piece.end,
                    span_text(piece),
                    piece.place if piece.kind == "stay" else None,
                )
            )

    # 2) 하루 요약: 그날 머문 곳을 순서대로, 위치 없는 시간은 그 사실을
    by_day: dict[tuple[str, str], list[Span]] = defaultdict(list)
    for p in day_pieces:
        by_day[(p.person_id, p.start.date().isoformat())].append(p)
    for (_, _), pieces in sorted(by_day.items()):
        pieces.sort(key=lambda x: x.start)
        names = pieces[0].person_name
        first, last = pieces[0].start, pieces[-1].end
        route: list[str] = []
        for p in pieces:
            if p.kind == "stay":
                label = p.place
            elif p.kind == "paused":
                label = "일시정지"
            elif p.kind == "no_consent":
                label = "동의하지 않은 시간"
            elif p.kind == "anomaly":
                label = "평소 구역 밖(이상 위치 기록)"
            else:
                continue
            if not route or route[-1] != label:
                route.append(label)
        text = f"{names} | {_date(first)} 하루 | {' → '.join(route)}"
        drafts.append(ChunkDraft(pieces[0].person_id, "day", first, last, text))

    # 3) 장소 요약: 사람×장소별 방문 횟수와 방문 시작 시각
    visits: dict[tuple[str, str], list[Span]] = defaultdict(list)
    for s in merged:
        if s.kind == "stay":
            visits[(s.person_id, s.place)].append(s)
    for (_, place), vs in sorted(visits.items()):
        vs.sort(key=lambda x: x.start)
        first, last = vs[0].start, vs[-1].end
        when = ", ".join(f"{v.month:02d}-{v.day:02d} {_hm(v)}" for v in (x.start for x in vs))
        text = (
            f"{vs[0].person_name} | {first.month:02d}-{first.day:02d}~{last.month:02d}-{last.day:02d} 기간 | "
            f"{place} 방문 {len(vs)}번 (머문 시간 합계 {_duration(datetime.min, datetime.min + sum((x.end - x.start for x in vs), timedelta()))}): {when}"
        )
        drafts.append(ChunkDraft(vs[0].person_id, "place", first, last, text, place))
    return drafts
