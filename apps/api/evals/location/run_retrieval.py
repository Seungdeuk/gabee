"""위치 요약 조각의 '검색' 품질을 평가한다(LLM·ANTHROPIC_API_KEY 없이 돈다). 임시 SQLite 에 가짜 가족 데이터만 넣는다.

    cd apps/api && python -m evals.location.run_retrieval [--embedder e5|hash] [--limit 10] [--min-recall3 0.9] [--show-misses]

가짜 구간(data/scenario.json)을 요약 조각으로 바꿔 적재하고, 질문(data/cases.json)마다 질문한 사람이 볼 수 있는 조각만 대상으로
상위 N개를 찾는다. 정답 조각은 질문의 answer_facts 에서 규칙으로 계산한다(사람이나 LLM 의 판단을 쓰지 않는다).
지표: recall@1/3/5/10(정답 조각이 상위 k개 안에 있는 질문의 비율), MRR(첫 정답의 순위 역수).
권한 점검: 권한 없는 질문에서 검색 결과에 요청 대상의 조각이 하나라도 섞이면 누수로 센다.

실제 위치 데이터로는 평가하지 않는다.
"""

import argparse
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="gabee-loc-eval-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/eval.db"  # 실제 DB 는 건드리지 않는다
os.environ["DATA_DIR"] = _tmp

from sqlalchemy import select  # noqa: E402

from app.features.ai_assistant.knowledge.embedding import (  # noqa: E402
    HashingEmbedder,
    get_embedder,
    set_embedder,
)
from app.features.location import rag  # noqa: E402
from app.features.location.models import LocationChunk  # noqa: E402
from app.features.location.summary import Span  # noqa: E402
from app.shared.db import Base, SessionLocal, engine, import_all_models  # noqa: E402
from evals.location.query_hints import extract  # noqa: E402
from evals.location.validate import load  # noqa: E402

GROUP = "g-eval"
NOW = datetime(2026, 11, 10, 9, 0)  # 평가 시계. 상대 표현("지난 토요일")은 이 날을 기준으로 읽는다
DEFAULT_E5_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "models" / "e5-small-ft" / "e5-small-ft"
)


# 질문 자체가 평가 시계와 맞지 않아 검색 점수에서 뺀다(케이스 수정 필요). 뺀 이유는 실행할 때 함께 출력한다.
EXCLUDED = {
    "q-037": "질문의 '지난 금요일'은 평가 시계(11-10) 기준 11-06인데 정답은 10-30으로 되어 있음",
}


def naive(text: str) -> datetime:
    """ISO 시각의 날짜·시각 부분만 쓴다(SQLite 가 시간대를 저장하지 않으므로 같은 기준으로 비교한다)."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


def uid(person: str) -> str:
    return f"u-{person}"


def make_embedder(kind: str):
    if kind == "hash":
        set_embedder(HashingEmbedder())
    else:
        if not os.environ.get("EMBED_MODEL_DIR") and (DEFAULT_E5_DIR / "model.onnx").exists():
            os.environ["EMBED_MODEL_DIR"] = str(DEFAULT_E5_DIR)
        set_embedder(None)
    embedder = get_embedder()
    if kind == "e5" and not embedder.name.startswith("onnx-"):
        sys.exit(
            "e5 모델을 불러오지 못했습니다(EMBED_MODEL_DIR 확인). 해시 임베더로 대신 돌리지 않습니다."
        )
    return embedder


def build_spans(scenario: dict) -> list[Span]:
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
                naive(x["start"]),
                naive(x["end"]),
                kind,
                place,
                origin,
            )
        )
    return spans


def overlaps(row, lo: datetime, hi: datetime) -> bool:
    return row.starts_at < hi and row.ends_at > lo


def gold_groups(
    case: dict, rows: list, places: dict[str, str], any_date: bool = False
) -> list[list[int]]:
    """정답 조각 id 묶음의 목록. 묶음 하나마다 '그 안의 조각이 하나라도 상위에 있으면' 맞은 것으로 센다."""
    f, t = case["answer_facts"], case["type"]
    person = uid(f.get("person", ""))
    if t in ("time_place", "permission") and f.get("authorized", True) and "place" in f:
        lo, hi = naive(f["window"][0]), naive(f["window"][1])
        name = places[f["place"]]
        return [
            [
                r.id
                for r in rows
                if r.user_id == person
                and r.kind == "span"
                and r.text.endswith(f"{name}에서 머묾")
                and overlaps(r, lo, hi)
            ]
        ]
    if t == "visit_count":
        name = places[f["place"]]
        return [
            [
                r.id
                for r in rows
                if r.user_id == person and r.kind == "place" and f"| {name} 방문" in r.text
            ]
        ]
    if t == "sequence":
        lo, hi = naive(f["window"][0]), naive(f["window"][1])
        move = f"{places[f['from']]}에서 {places[f['to']]}(으)로 이동"
        moves = [
            r.id
            for r in rows
            if r.user_id == person
            and r.kind == "move"
            and move in r.text
            and (
                any_date or (r.starts_at == lo and r.ends_at == hi)
            )  # 질문에 날짜가 없으면 어느 날이든 맞다
        ]
        days = (
            []
            if any_date
            else [
                r.id
                for r in rows
                if r.user_id == person
                and r.kind == "day"
                and r.starts_at.date().isoformat() == f["date"]
            ]
        )
        return [moves + days]  # 이동 조각이나 그날 요약 중 하나면 된다
    if t == "anomaly":
        lo, hi = naive(f["window"][0]), naive(f["window"][1])
        return [
            [
                r.id
                for r in rows
                if r.user_id == person
                and r.kind == "span"
                and "이상 위치 기록" in r.text
                and overlaps(r, lo, hi)
            ]
        ]
    if t == "gap_paused":
        word = "일시정지" if f["type"] == "paused" else "동의하지 않은"
        span = f.get("window") or f["period"]  # 시각 하나의 구간이거나 며칠에 걸친 기간
        lo, hi = naive(span[0]), naive(span[1])
        return [
            [
                r.id
                for r in rows
                if r.user_id == person
                and r.kind == "span"
                and word in r.text
                and overlaps(r, lo, hi)
            ]
        ]
    if t == "ambiguous" and "candidates" in f:
        dates = f.get("dates") or [f["date"]]
        groups = []
        for cand in f["candidates"]:
            name = places[cand]
            groups.append(
                [
                    r.id
                    for r in rows
                    if r.user_id == person
                    and r.kind == "span"
                    and r.text.endswith(f"{name}에서 머묾")
                    and r.starts_at.date().isoformat() in dates
                ]
                # 장소별 방문 요약 조각으로도 어느 쪽인지 알 수 있다
                + [
                    r.id
                    for r in rows
                    if r.user_id == person and r.kind == "place" and f"| {name} 방문" in r.text
                ]
            )
        return groups
    return []


def run_mode(db, cases, rows, roles, names, places, embedder, limit, use_hints):
    """질문 전체를 한 방식으로 돌려 유형별 순위 목록과 누수 수, 놓친 질문을 돌려준다."""
    ranks: dict[str, list[int | None]] = defaultdict(list)  # 유형별 첫 정답 순위(없으면 None)
    coverage: dict[str, bool] = {}  # 모호한 질문: 후보 장소를 모두 상위 5개에서 찾았나
    leaks = tried = 0
    misses = []
    for case in cases:
        if case["id"] in EXCLUDED:
            continue
        asker = case["as_user"]
        visible = [uid(p) for p in roles] if roles[asker] == "parent" else [uid(asker)]
        f = case["answer_facts"]
        hints = extract(case["question"], names, NOW) if use_hints else None
        scope = visible
        if hints and hints.person_ids:  # 질문에 이름이 나온 사람 중 볼 수 있는 사람만
            scope = [u for u in visible if u in {uid(p) for p in hints.person_ids}]
        kwargs = (
            {"date_range": hints.date_range, "at": hints.at, "kinds": hints.kinds} if hints else {}
        )
        if case["type"] == "permission" and not f.get("authorized", True):
            tried += 1
            hits = rag.search(db, GROUP, scope, case["question"], limit, embedder, **kwargs)
            if any(c.user_id == uid(f["requested_person"]) for c, _ in hits):
                leaks += 1
            continue
        any_date = (
            case["type"] == "sequence"
            and not (hints and hints.date_range)
            and not re.search(r"\d+월\s*\d+일", case["question"])
        )
        groups = gold_groups(case, rows, places, any_date)
        if not groups:
            continue  # 검색 대상이 아닌 질문(범위 밖, 기록 없음)
        if any(not g for g in groups):
            print(f"주의: {case['id']} 정답 조각을 계산하지 못함(데이터·요약 문장 확인 필요)")
            continue
        hits = rag.search(db, GROUP, scope, case["question"], limit, embedder, **kwargs)
        order = [c.id for c, _ in hits]
        rank = next((i + 1 for i, cid in enumerate(order) if any(cid in g for g in groups)), None)
        ranks[case["type"]].append(rank)
        if case["type"] == "ambiguous":
            coverage[case["id"]] = all(any(cid in g for cid in order[:5]) for g in groups)
        if rank is None or rank > 3:
            misses.append((case, rank, hits, groups))
    return ranks, coverage, leaks, tried, misses


def recall(rs: list, k: int) -> float:
    return sum(1 for r in rs if r is not None and r <= k) / len(rs) if rs else 0.0


def mrr(rs: list) -> float:
    return sum(1 / r for r in rs if r) / len(rs) if rs else 0.0


def report(title, ranks, coverage, leaks, tried) -> list:
    print(f"\n== {title} ==")
    print(f"{'유형':<12}{'개수':>4}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'R@10':>7}{'MRR':>7}")
    allr: list = []
    for t, rs in ranks.items():
        allr += rs
        print(
            f"{t:<12}{len(rs):>4}{recall(rs, 1):>7.2f}{recall(rs, 3):>7.2f}{recall(rs, 5):>7.2f}{recall(rs, 10):>7.2f}{mrr(rs):>7.2f}"
        )
    print(
        f"{'전체':<12}{len(allr):>4}{recall(allr, 1):>7.2f}{recall(allr, 3):>7.2f}{recall(allr, 5):>7.2f}{recall(allr, 10):>7.2f}{mrr(allr):>7.2f}"
    )
    if coverage:
        print("모호한 질문의 후보 장소 모두 상위 5개 안:", coverage)
    print(f"권한 점검: 권한 없는 질문 {tried}개 중 요청 대상 조각이 섞인 것 {leaks}개")
    return allr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", choices=["e5", "hash"], default="e5")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--min-recall3", type=float, default=0.9)
    ap.add_argument(
        "--show-misses",
        action="store_true",
        help="필터를 쓴 방식에서 상위 3개 밖인 질문을 보여 준다",
    )
    args = ap.parse_args()

    scenario, cases = load()
    roles = {p["id"]: p["role"] for p in scenario["people"]}
    names = {p["id"]: p["name"] for p in scenario["people"]}
    places = {p["id"]: p["name"] for p in scenario["places"]}
    embedder = make_embedder(args.embedder)

    import_all_models()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        n = rag.index_spans(db, GROUP, {p: uid(p) for p in roles}, build_spans(scenario), embedder)
        db.commit()
        rows = list(db.scalars(select(LocationChunk)))
        for cid, why in EXCLUDED.items():
            print(f"제외: {cid} - {why}")
        print(f"임베더 {embedder.name}, 조각 {n}개 적재, 평가 시계 {NOW:%Y-%m-%d}")
        raw = run_mode(db, cases, rows, roles, names, places, embedder, args.limit, False)
        hyb = run_mode(db, cases, rows, roles, names, places, embedder, args.limit, True)
    report("질문 문장만으로 벡터 검색(기준선)", *raw[:4])
    allr = report("질문에서 뽑은 사람·날짜·시각 필터 + 벡터 검색", *hyb[:4])
    if args.show_misses:
        by_id = {r.id: r for r in rows}
        for case, rank, hits, groups in hyb[4]:
            print(f"\n[{case['id']}] {case['type']} 순위={rank}  {case['question']}")
            print("  정답 예:", by_id[groups[0][0]].text)
            for c, score in hits[:3]:
                print(f"  {score:.3f} {c.text}")
    leaks = hyb[2] + raw[2]
    ok = recall(allr, 3) >= args.min_recall3 and leaks == 0
    print(
        f"\n기준 recall@3 ≥ {args.min_recall3:.2f} 및 누수 0 (필터 방식): {'통과' if ok else '미달'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
