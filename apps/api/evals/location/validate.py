"""평가용 가짜 데이터(scenario.json)와 질문(cases.json)이 서로 맞는지 코드로 검사한다. LLM·DB·네트워크를 쓰지 않는다.

    cd apps/api && python -m evals.location.validate

다른 곳에서 만든 데이터는 날짜·요일·구간 계산이 틀리기 쉬워서, 평가 전에 정답(answer_facts)을 구간 데이터로 다시 계산해 대조한다.
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"
TYPES = {"stay", "move", "paused", "no_consent", "anomaly"}
NO_LOCATION = {"paused", "no_consent"}
CASE_TYPES = {
    "time_place": 6, "visit_count": 5, "sequence": 5, "anomaly": 4, "gap_paused": 4,
    "permission": 6, "out_of_scope": 4, "ambiguous": 3, "no_data": 3,
}  # fmt: skip


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text)


def load() -> tuple[dict, list[dict]]:
    scenario = json.loads((DATA / "scenario.json").read_text(encoding="utf-8"))
    cases = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
    return scenario, cases


def merged_stays(segments: list[dict], person: str) -> list[dict]:
    """같은 사람이 같은 장소에 끊김 없이 이어서 머문 구간(하루 경계·시간대별로 쪼개진 구간)을 한 번의 방문으로 합친다."""
    out: list[dict] = []
    for seg in sorted((s for s in segments if s["person"] == person), key=lambda s: s["start"]):
        if seg["type"] != "stay":
            continue
        if out and out[-1]["place"] == seg["place"] and out[-1]["end"] == seg["start"]:
            out[-1] = {**out[-1], "end": seg["end"]}
        else:
            out.append(dict(seg))
    return out


def check_scenario(s: dict) -> list[str]:
    errs: list[str] = []
    people = {p["id"] for p in s["people"]}
    places = {p["id"]: p for p in s["places"]}
    if len(places) != len(s["places"]):
        errs.append("places: id 중복")
    for seg in s["segments"]:
        where = f"{seg['person']} {seg['start']}"
        if seg["person"] not in people:
            errs.append(f"{where}: 없는 사람")
        if seg["type"] not in TYPES:
            errs.append(f"{where}: 알 수 없는 type {seg['type']}")
        if ts(seg["end"]) <= ts(seg["start"]):
            errs.append(f"{where}: 끝이 시작보다 빠르거나 같음")
        if seg["type"] == "stay" and seg.get("place") not in places:
            errs.append(f"{where}: stay 장소 없음 {seg.get('place')}")
        if seg["type"] == "move" and (seg.get("from") not in places or seg.get("to") not in places):
            errs.append(f"{where}: move 출발/도착 장소 없음")
        if seg["type"] == "anomaly" and ("lat" not in seg or "lng" not in seg):
            errs.append(f"{where}: anomaly 좌표 없음")
    for person in sorted(people):
        segs = sorted((x for x in s["segments"] if x["person"] == person), key=lambda x: x["start"])
        for prev, cur in zip(segs, segs[1:], strict=False):
            if prev["end"] != cur["start"]:
                kind = "겹침" if ts(prev["end"]) > ts(cur["start"]) else "빈 시간"
                errs.append(f"{person}: {kind} {prev['end']} → {cur['start']}")
            # 이동의 출발·도착이 앞뒤 구간의 장소와 이어지는지(순간이동 점검)
            if cur["type"] == "move" and prev["type"] == "stay" and cur["from"] != prev["place"]:
                errs.append(
                    f"{person}: 이동 출발({cur['from']})이 직전 머문 곳({prev['place']})과 다름 {cur['start']}"
                )
            if prev["type"] == "move" and cur["type"] == "stay" and prev["to"] != cur["place"]:
                errs.append(
                    f"{person}: 이동 도착({prev['to']})이 다음 머문 곳({cur['place']})과 다름 {cur['start']}"
                )
            if prev["type"] == "move" and cur["type"] == "move" and prev["to"] != cur["from"]:
                errs.append(f"{person}: 이어지는 이동의 장소가 다름 {cur['start']}")
            if "anomaly" in (prev["type"], cur["type"]):
                a, b = (prev, cur) if prev["type"] == "anomaly" else (cur, prev)
                if b["type"] == "stay":
                    errs.append(f"{person}: 이상 구간 바로 옆이 이동 없이 머문 곳 {a['start']}")
    return errs


def _question_time(question: str) -> tuple[int, int, int, int] | None:
    """질문에서 (월, 일, 시, 분)을 읽는다. 날짜나 시각이 없으면 None."""
    md = re.search(r"(\d+)월\s*(\d+)일", question)
    hm = re.search(r"(오전|오후|아침|새벽|저녁)?\s*(\d+)시(\s*반)?", question)
    if not (md and hm):
        return None
    hour = int(hm.group(2))
    if hm.group(1) in ("오후", "저녁") and hour < 12:
        hour += 12
    return int(md.group(1)), int(md.group(2)), hour, 30 if hm.group(3) else 0


def check_cases(s: dict, cases: list[dict]) -> list[str]:
    errs: list[str] = []
    segs = s["segments"]
    names = {p["id"]: p["name"] for p in s["places"]}
    roles = {p["id"]: p["role"] for p in s["people"]}
    ids = Counter(c["id"] for c in cases)
    errs += [f"{i}: 질문 id 중복" for i, n in ids.items() if n > 1]
    counts = Counter(c["type"] for c in cases)
    for t, n in CASE_TYPES.items():
        if counts.get(t, 0) != n:
            errs.append(f"유형 {t}: {counts.get(t, 0)}개(기대 {n}개)")

    def day_segments(person: str, day: str) -> list[dict]:
        return [x for x in segs if x["person"] == person and x["start"][:10] == day]

    for c in cases:
        cid, f, t = c["id"], c["answer_facts"], c["type"]
        if t in ("time_place", "permission") and f.get("authorized", True) and "place" in f:
            lo, hi = f["window"]
            hit = [
                m
                for m in merged_stays(segs, f["person"])
                if m["place"] == f["place"] and m["start"] <= lo and m["end"] >= hi
            ]
            if not hit:
                errs.append(f"{cid}: {f['person']}가 {lo}~{hi} 에 {f['place']} 에 머문 구간이 없음")
            elif f["place"] in names and names[f["place"]] not in c["must_contain"]:
                errs.append(f"{cid}: 정답 장소 이름({names[f['place']]})이 must_contain 에 없음")
            q = _question_time(c["question"])
            if q and hit:
                month, day, hour, minute = q
                when = datetime(2026, month, day, hour, minute, tzinfo=ts(lo).tzinfo)
                if not (ts(lo) <= when < ts(hi)):
                    errs.append(f"{cid}: 질문 시각 {when.isoformat()} 이 정답 구간 {lo}~{hi} 밖")
        if t == "visit_count":
            lo, hi = f["period"]
            n = sum(
                1
                for m in merged_stays(segs, f["person"])
                if m["place"] == f["place"] and lo <= m["start"] < hi
            )
            if n != f["count"]:
                errs.append(f"{cid}: 방문 횟수 {f['count']} ≠ 데이터에서 센 값 {n}")
            if f"{f['count']}번" not in c["must_contain"]:
                errs.append(f"{cid}: must_contain 에 '{f['count']}번' 이 없음")
        if t == "sequence":
            moves = [
                x
                for x in day_segments(f["person"], f["date"])
                if x["type"] == "move" and x["from"] == f["from"] and x["to"] == f["to"]
            ]
            if not any([x["start"], x["end"]] == f["window"] for x in moves):
                errs.append(
                    f"{cid}: {f['date']} {f['from']}→{f['to']} 이동이 window {f['window']} 와 맞지 않음"
                )
        if t in ("anomaly", "gap_paused"):
            kind = f.get("type")
            same = [x for x in segs if x["person"] == f["person"] and x["type"] == kind]
            if "window" in f:
                lo, hi = f["window"]
                if not any(x["start"] <= lo and x["end"] >= hi for x in same):
                    errs.append(f"{cid}: {kind} 구간이 {lo}~{hi} 를 덮지 않음")
            if "period" in f:
                lo, hi = f["period"]
                covered = sum(
                    (ts(min(x["end"], hi)) - ts(max(x["start"], lo))).total_seconds()
                    for x in same
                    if x["start"] < hi and x["end"] > lo
                )
                if covered != (ts(hi) - ts(lo)).total_seconds():
                    errs.append(f"{cid}: {kind} 구간이 기간 {lo}~{hi} 를 모두 덮지 않음")
        if t == "permission":
            allowed = (
                roles[c["as_user"]] == "parent"
                or f.get("person", f.get("requested_person")) == c["as_user"]
            )
            if allowed != f["authorized"]:
                errs.append(
                    f"{cid}: authorized={f['authorized']} 인데 {c['as_user']}({roles[c['as_user']]}) 규칙으로는 {allowed}"
                )
            if not f["authorized"] and c["tool_expected"] is not None:
                errs.append(f"{cid}: 권한 없음인데 tool_expected 가 {c['tool_expected']}")
        if t == "ambiguous" and "candidates" in f:
            dates = f.get("dates") or [f["date"]]  # 질문에 따라 date 한 개이거나 dates 여러 개
            for cand in f["candidates"]:
                if not any(
                    m["place"] == cand and m["start"][:10] in dates
                    for m in merged_stays(segs, f["person"])
                ):
                    errs.append(f"{cid}: 후보 {cand} 를 {dates} 에 방문한 기록이 없음")
        if t == "no_data":
            if day_segments(f["person"], f["date"]):
                errs.append(
                    f"{cid}: {f['date']} 에 {f['person']} 구간이 있음(기록이 없다고 했는데)"
                )
        for word in c["must_contain"]:
            if word in c["must_not_contain"]:
                errs.append(f"{cid}: '{word}' 가 must_contain 과 must_not_contain 에 모두 있음")
    return errs


def warnings(cases: list[dict]) -> list[str]:
    """정답 판정에 쓰기 어려운 기대 문구(설명문·제목 같은 낱말). 오류는 아니고 확인이 필요한 것."""
    out: list[str] = []
    for c in cases:
        for word in c["must_not_contain"]:
            if len(word) > 8 or word in ("실제 주소", "여행지 이름"):
                out.append(
                    f"{c['id']}: must_not_contain '{word}' 는 답변에 나올 말이 아니라서 검사가 의미 없음"
                )
        for word in c["must_contain"]:
            if word in (
                "이상 위치 기록",
                "위치 공유가 일시정지",
                "동의하지 않아",
                "위치 기록이 없어",
                "권한이 없어",
                "기록이 없어",
            ):
                out.append(
                    f"{c['id']}: must_contain '{word}' 는 정해진 문장이라 답변 문구와 맞춰야 함"
                )
    return out


def scenario_warnings(s: dict) -> list[str]:
    """이상 위치 구간의 앞뒤 이동이 이상 위치와 이어지지 않으면(도착지·출발지가 일반 장소) 순간이동처럼 보인다. 오류는 아니다."""
    out: list[str] = []
    for person in {x["person"] for x in s["segments"]}:
        segs = sorted((x for x in s["segments"] if x["person"] == person), key=lambda x: x["start"])
        for prev, cur, nxt in zip(segs, segs[1:], segs[2:], strict=False):
            if cur["type"] == "anomaly" and prev["type"] == "move" and nxt["type"] == "move":
                out.append(
                    f"{person}: 이상 위치({cur['lat']},{cur['lng']}) 앞 이동은 {prev['to']} 도착, 뒤 이동은 {nxt['from']} 출발이라 이상 위치와 이어지지 않음"
                )
    return out


def main() -> int:
    s, cases = load()
    errs = check_scenario(s) + check_cases(s, cases)
    warn = warnings(cases) + scenario_warnings(s)
    print(f"구간 {len(s['segments'])}개, 질문 {len(cases)}개")
    for e in errs:
        print("오류:", e)
    for w in warn:
        print("주의:", w)
    print(f"오류 {len(errs)}건, 주의 {len(warn)}건")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
