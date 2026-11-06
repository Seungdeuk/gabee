"""위치 점 → 구간 변환기(timeline.convert)를 평가용 가짜 데이터로 왕복 검증한다(LLM·DB·네트워크 없음).

    cd apps/api && python -m evals.location.run_timeline [--dropout 0.15] [--seed 7]

가짜 구간(data/scenario.json)에서 1분 간격 위치 점을 만들고(머묾은 장소 중심 둘레의 잔떨림, 이동은 두 장소 사이 직선, 이상 구간은 그 좌표,
일시정지·동의 없음은 점 없음), 변환기로 구간을 되돌려 원래 구간과 맞는지 비교한다. 기준: 장소 이름이 같고 시작·끝 시각이 ±10분 이내.

--dropout 은 점을 무작위로 뺀다(앱이 꺼졌거나 신호가 끊긴 상황). 이때는 정답과 똑같이 되돌리는 것이 목표가 아니라
'없는 시간을 있었다고 지어내지 않는지'(변환기가 머문 곳으로 보고한 시간 중 실제로는 다른 곳이거나 구간이 없던 분)를 본다.
실제 위치 데이터로는 평가하지 않는다.
"""

import argparse
import hashlib
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from app.features.location import timeline as tl
from app.features.location.service import compute_zone
from evals.location.validate import load

TOLERANCE = timedelta(minutes=10)
M_PER_DEG_LAT = 111320.0


def naive(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=None)


def jitter(person: str, minute: datetime, radius_m: float) -> tuple[float, float]:
    """같은 입력이면 항상 같은 잔떨림(위도·경도 오프셋, 도)."""
    h = hashlib.sha256(f"{person}|{minute.isoformat()}".encode()).digest()
    dx = (h[0] / 255 - 0.5) * 2 * radius_m
    dy = (h[1] / 255 - 0.5) * 2 * radius_m
    return dy / M_PER_DEG_LAT, dx / M_PER_DEG_LAT


def make_points(scenario: dict, person: str) -> list[tl.Pt]:
    places = {p["id"]: p for p in scenario["places"]}
    out: list[tl.Pt] = []
    for seg in sorted(
        (s for s in scenario["segments"] if s["person"] == person), key=lambda s: s["start"]
    ):
        start, end = naive(seg["start"]), naive(seg["end"])
        total = max(1, int((end - start).total_seconds() // 60))
        for k in range(total):
            t = start + timedelta(minutes=k)
            kind = seg["type"]
            if kind in ("paused", "no_consent"):
                break
            if kind == "stay":
                c = places[seg["place"]]
                lat, lng, r = c["lat"], c["lng"], 40
            elif kind == "anomaly":
                lat, lng, r = seg["lat"], seg["lng"], 40
            else:  # move: 두 장소 사이를 직선으로
                a, b = places[seg["from"]], places[seg["to"]]
                f = (k + 0.5) / total
                lat, lng, r = (
                    a["lat"] + (b["lat"] - a["lat"]) * f,
                    a["lng"] + (b["lng"] - a["lng"]) * f,
                    15,
                )
            dlat, dlng = jitter(person, t, r)
            out.append(tl.Pt(t, lat + dlat, lng + dlng, 10.0))
    return out


def drop_points(points: list[tl.Pt], rate: float, rng: random.Random) -> list[tl.Pt]:
    """점을 무작위로 빼고, 하루마다 20분 연속으로 비운다."""
    kept = [p for p in points if rng.random() >= rate]
    blanks: dict[str, datetime] = {}
    for p in kept:
        blanks.setdefault(
            p.t.date().isoformat(),
            p.t.replace(hour=12, minute=0, second=0) + timedelta(minutes=rng.randint(0, 120)),
        )
    return [
        p for p in kept if not any(b <= p.t < b + timedelta(minutes=20) for b in blanks.values())
    ]


def truth_at(truth: list[dict], t: datetime) -> dict | None:
    return next((s for s in truth if s["start"] <= t < s["end"]), None)


def merged_truth(scenario: dict, person: str, places: dict[str, str]) -> list[dict]:
    """같은 곳에 끊김 없이 이어진 구간을 합친 정답. kind 는 stay/move/anomaly/gap(일시정지·동의 없음)."""
    segs = sorted(
        (s for s in scenario["segments"] if s["person"] == person), key=lambda s: s["start"]
    )
    out: list[dict] = []
    for s in segs:
        kind = {"paused": "gap", "no_consent": "gap"}.get(s["type"], s["type"])
        place = places.get(s.get("place")) if kind == "stay" else None
        item = {"kind": kind, "place": place, "start": naive(s["start"]), "end": naive(s["end"])}
        if (
            out
            and out[-1]["kind"] == kind
            and out[-1]["place"] == place
            and out[-1]["end"] == item["start"]
            and kind in ("stay", "gap")
        ):
            out[-1]["end"] = item["end"]
        else:
            out.append(item)
    return out


def overlap_minutes(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds() / 60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dropout", type=float, default=0.0, help="무작위로 뺄 점의 비율(0 이면 깨끗한 왕복 검증)"
    )
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    scenario, _ = load()
    place_names = {p["id"]: p["name"] for p in scenario["places"]}
    known = [
        tl.KnownPlace(p["id"], p["name"], p["lat"], p["lng"], p["radius_m"])
        for p in scenario["places"]
    ]
    rng = random.Random(args.seed)

    totals: dict[str, float] = defaultdict(float)
    print(
        f"점 간격 1분, 정답 허용 오차 ±{int(TOLERANCE.total_seconds() // 60)}분, 점 빼기 {args.dropout:.0%}"
    )
    for person in (p["id"] for p in scenario["people"]):
        points = make_points(scenario, person)
        if args.dropout:
            points = drop_points(points, args.dropout, rng)
        zone_src = compute_zone(points)
        zone = tl.ZoneRef(zone_src[0], zone_src[1], zone_src[2])
        window = (
            min(p.t for p in points).replace(hour=0, minute=0),
            naive("2026-11-10T00:00:00+09:00"),
        )
        segs = tl.convert(points, known, zone, window)
        truth = merged_truth(scenario, person, place_names)

        gt_stays = [
            s for s in truth if s["kind"] == "stay" and s["end"] - s["start"] >= tl.MIN_STAY
        ]
        got = [s for s in segs if s.kind == "stay" and s.place]
        used: set[int] = set()
        matched = 0
        for g in gt_stays:
            for i, c in enumerate(got):
                if (
                    i not in used
                    and c.place == g["place"]
                    and abs(c.start - g["start"]) <= TOLERANCE
                    and abs(c.end - g["end"]) <= TOLERANCE
                ):
                    used.add(i)
                    matched += 1
                    break
        gt_anom = [s for s in truth if s["kind"] == "anomaly"]
        got_anom = [s for s in segs if s.kind == "anomaly"]
        anom_ok = sum(
            1
            for g in gt_anom
            if any(
                abs(c.start - g["start"]) <= TOLERANCE and abs(c.end - g["end"]) <= TOLERANCE
                for c in got_anom
            )
        )
        gt_gap = [s for s in truth if s["kind"] == "gap"]
        gap_total = sum((g["end"] - g["start"]).total_seconds() / 60 for g in gt_gap)
        gap_covered = sum(
            overlap_minutes(g["start"], g["end"], c.start, c.end)
            for g in gt_gap
            for c in segs
            if c.kind == "no_record"
        )
        # 지어낸 시간: 변환기가 머문 곳이라고 한 분 가운데 정답은 다른 곳이거나 구간이 없는 분(경계 오차는 빼고 센다)
        invented = 0.0
        for c in (s for s in segs if s.kind in ("stay", "anomaly")):
            t = c.start + TOLERANCE
            while t < c.end - TOLERANCE:
                at = truth_at(truth, t)
                ok = at is not None and (
                    (c.kind == "anomaly" and at["kind"] == "anomaly")
                    or (c.kind == "stay" and at["kind"] == "stay" and at["place"] == c.place)
                )
                invented += 0 if ok else 1
                t += timedelta(minutes=1)
        visits_truth: dict[str, int] = defaultdict(int)
        for g in gt_stays:
            visits_truth[g["place"]] += 1
        visits_got: dict[str, int] = defaultdict(int)
        for c in got:
            visits_got[c.place] += 1
        visit_diff = sum(
            abs(visits_truth[k] - visits_got.get(k, 0)) for k in set(visits_truth) | set(visits_got)
        )

        print(
            f"- {person}: 머묾 {matched}/{len(gt_stays)} 일치(변환 {len(got)}개), 이상 {anom_ok}/{len(gt_anom)}, "
            f"기록 없음 덮음 {gap_covered:.0f}/{gap_total:.0f}분, 방문 횟수 차이 {visit_diff}, 지어낸 시간 {invented:.0f}분"
        )
        totals["gt"] += len(gt_stays)
        totals["matched"] += matched
        totals["got"] += len(got)
        totals["anom"] += len(gt_anom)
        totals["anom_ok"] += anom_ok
        totals["gap"] += gap_total
        totals["gap_ok"] += gap_covered
        totals["visit_diff"] += visit_diff
        totals["invented"] += invented

    recall = totals["matched"] / totals["gt"]
    precision = totals["matched"] / totals["got"] if totals["got"] else 0.0
    gap_cov = totals["gap_ok"] / totals["gap"] if totals["gap"] else 1.0
    print(
        f"\n머묾 recall {recall:.2f}, precision {precision:.2f}, 이상 {int(totals['anom_ok'])}/{int(totals['anom'])}, "
        f"기록 없음 덮음 {gap_cov:.2f}, 방문 횟수 차이 합 {int(totals['visit_diff'])}, 지어낸 시간 합 {totals['invented']:.0f}분"
    )
    if args.dropout:
        ok = totals["invented"] <= 30  # 점이 빠져도 지어낸 시간이 거의 없어야 한다
        print(f"기준 지어낸 시간 ≤ 30분: {'통과' if ok else '미달'}")
    else:
        ok = (
            recall >= 0.95
            and precision >= 0.95
            and totals["visit_diff"] == 0
            and gap_cov >= 0.9
            and totals["anom_ok"] == totals["anom"]
        )
        print(
            f"기준 recall·precision ≥ 0.95, 방문 횟수 차이 0, 기록 없음 덮음 ≥ 0.9, 이상 전부: {'통과' if ok else '미달'}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
