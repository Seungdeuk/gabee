"""평가용 가짜 시나리오를 모두 읽고 요약 조각으로 바꾸는 공통 코드(LLM·DB 를 쓰지 않는다).

- 기본 시나리오 `data/scenario.json` 과 추가 시나리오 `data/scenarios/*.json` 을 읽는다. 사람·장소 id 는 시나리오마다 접두사가 달라 겹치지 않는다.
- 조각은 서버와 같은 코드(`summary.build_chunks`)로 만든다. 질문 생성과 개발용/최종 점수용 분리가 이 조각을 기준으로 한다.
실제 위치 데이터는 쓰지 않는다."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.features.location.summary import ChunkDraft, Span, build_chunks

DATA = Path(__file__).parent / "data"


def load_all() -> list[tuple[str, dict]]:
    """[(이름, 시나리오)]. 기본 시나리오가 먼저, 추가 시나리오는 파일 이름순."""
    out = [("base", json.loads((DATA / "scenario.json").read_text(encoding="utf-8")))]
    for path in sorted((DATA / "scenarios").glob("*.json")):
        out.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return out


def _naive(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=None)


def spans_of(scenario: dict) -> list[Span]:
    names = {p["id"]: p["name"] for p in scenario["people"]}
    places = {p["id"]: p["name"] for p in scenario["places"]}
    spans = []
    for x in scenario["segments"]:
        kind = x["type"]
        place = (
            places.get(x.get("place"))
            if kind == "stay"
            else places.get(x.get("to"))
            if kind == "move"
            else None
        )
        origin = places.get(x.get("from")) if kind == "move" else None
        spans.append(
            Span(
                x["person"],
                names[x["person"]],
                _naive(x["start"]),
                _naive(x["end"]),
                kind,
                place,
                origin,
            )
        )
    return spans


def chunks_of(scenario: dict) -> list[ChunkDraft]:
    return build_chunks(spans_of(scenario))


def chunk_key(c: ChunkDraft) -> str:
    """조각을 가리키는 바뀌지 않는 키(종류|사람|시작|끝|장소). 같은 시나리오면 항상 같다."""
    return "|".join(
        [
            c.kind,
            c.person_id,
            c.starts_at.isoformat(timespec="minutes"),
            c.ends_at.isoformat(timespec="minutes"),
            c.place or "",
        ]
    )


def group_key(c: ChunkDraft) -> str:
    """분리의 단위. 하루 요약(day)은 그날 구간 조각(span·move)을 요약한 것이라 같은 사람·같은 날을 한 묶음으로 본다.
    장소 요약(place)은 사람·장소 단위로 묶는다."""
    if c.kind == "place":
        return f"place|{c.person_id}|{c.place}"
    return f"day|{c.person_id}|{c.starts_at.date().isoformat()}"


def split_of(c: ChunkDraft, final_ratio: float = 0.3, seed: str = "gabee-loc-1") -> str:
    """'dev'(개선하면서 보는 질문) 또는 'final'(마지막에 한 번만 보는 질문). 키의 해시로 정해서 시나리오를 늘려도 이미 나뉜 조각은 바뀌지 않는다."""
    h = hashlib.sha1(f"{seed}|{group_key(c)}".encode()).hexdigest()
    return "final" if int(h[:8], 16) / 16**8 < final_ratio else "dev"
