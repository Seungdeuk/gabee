"""위치 점을 하루 이동 기록(구간)으로 묶는다. 규칙만 쓰고 DB·LLM·네트워크를 쓰지 않는다.

- 머묾(stay): 반경 STAY_RADIUS_M 안에 MIN_STAY 이상 머문 점 묶음. 처음 점을 기준으로 반경을 재서 천천히 번지지 않게 한다.
- 이동(move): 머묾과 머묾 사이(또는 머묾 앞뒤)에 이어진 점.
- 기록 없음(no_record): 점 사이가 MAX_GAP 을 넘게 비었거나 하루의 앞뒤가 비어 있는 시간. 앞 위치에 계속 있었다고 이어 붙이지 않는다.
  여행 모드·동의 없음·앱이 꺼진 시간·신호 없음을 서버는 구분할 수 없어(일시정지 이력을 남기지 않는다) 모두 기록 없음이다.
- 평소 구역 밖(anomaly): 이름 없는 곳에서 MIN_STAY 이상 머물렀는데 활동 구역 밖인 머묾.
- 정확도가 MAX_ACCURACY_M 보다 나쁜 점은 버린다(튀는 점이 가짜 이동을 만들지 않게).
장소 이름은 사용자가 붙인 곳(KnownPlace)과 겹칠 때만 붙인다. 이름이 없으면 place 는 None 이다."""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

STAY_RADIUS_M = 150.0
TRIM_RADIUS_M = 90.0  # 머묾의 앞뒤에서 중심과 이보다 먼 점은 이동하는 점으로 본다
MIN_STAY = timedelta(minutes=10)
MAX_GAP = timedelta(minutes=5)
MAX_ACCURACY_M = 100.0
MIN_RUN = timedelta(minutes=2)  # 이보다 짧게 끊겨 있는 점 묶음은 잡음으로 보고 기록 없음에 합친다
FREQUENT_MIN_VISITS = 3  # 이름 없는 곳을 '자주 가는 곳' 후보로 보는 방문 횟수


@dataclass(frozen=True)
class Pt:
    t: datetime
    lat: float
    lng: float
    accuracy_m: float | None = None


@dataclass(frozen=True)
class KnownPlace:
    id: str
    name: str
    lat: float
    lng: float
    radius_m: float = STAY_RADIUS_M


@dataclass(frozen=True)
class ZoneRef:
    lat: float
    lng: float
    radius_m: float


@dataclass(frozen=True)
class Seg:
    kind: str  # stay | move | no_record | anomaly
    start: datetime
    end: datetime
    place: str | None = None  # 머문 곳 이름(이름이 붙은 곳만), 이동에서는 도착지
    origin: str | None = None  # 이동의 출발지 이름
    place_id: str | None = None
    lat: float | None = None  # 머문 곳의 중심. 서버 안에서만 쓰고 응답에는 싣지 않는다
    lng: float | None = None


def dist_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _runs(points: list[Pt]) -> list[list[Pt]]:
    """MAX_GAP 보다 길게 비지 않은 점 묶음으로 자른다."""
    out: list[list[Pt]] = []
    for p in points:
        if out and p.t - out[-1][-1].t <= MAX_GAP:
            out[-1].append(p)
        else:
            out.append([p])
    return out


def _stays(run: list[Pt]) -> list[tuple[int, int]]:
    """한 묶음 안의 머묾 구간을 점 번호 (처음, 끝)으로 돌려준다."""
    found: list[tuple[int, int]] = []
    i, n = 0, len(run)
    while i < n:
        # 지금까지 모인 점들의 평균에서 반경 안인 동안 번진다(처음 점 기준이면 도착 직후의 어긋난 점 때문에 머묾이 중간에 끊긴다)
        j, sum_lat, sum_lng = i, run[i].lat, run[i].lng
        while j + 1 < n:
            count = j - i + 1
            if (
                dist_m(run[j + 1].lat, run[j + 1].lng, sum_lat / count, sum_lng / count)
                > STAY_RADIUS_M
            ):
                break
            j += 1
            sum_lat += run[j].lat
            sum_lng += run[j].lng
        if run[j].t - run[i].t < MIN_STAY:
            i += 1
            continue
        # 도착하는 길과 떠나는 길의 점은 중심에서 멀어 머묾에서 뺀다(시작·끝 시각이 실제에 가깝게)
        lat = statistics.median(p.lat for p in run[i : j + 1])
        lng = statistics.median(p.lng for p in run[i : j + 1])
        a, b = i, j
        while a < b and dist_m(run[a].lat, run[a].lng, lat, lng) > TRIM_RADIUS_M:
            a += 1
        while b > a and dist_m(run[b].lat, run[b].lng, lat, lng) > TRIM_RADIUS_M:
            b -= 1
        if run[b].t - run[a].t >= MIN_STAY:
            found.append((a, b))
        i = j + 1
    return found


def match_place(lat: float, lng: float, places: list[KnownPlace]) -> KnownPlace | None:
    best: tuple[float, KnownPlace] | None = None
    for p in places:
        d = dist_m(lat, lng, p.lat, p.lng)
        if d <= p.radius_m and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def convert(
    points: list[Pt],
    places: list[KnownPlace] | None = None,
    zone: ZoneRef | None = None,
    window: tuple[datetime, datetime] | None = None,
) -> list[Seg]:
    """점들로 구간 목록을 만든다(시간순, 서로 겹치지 않음). window 를 주면 그 안만 돌려주고 앞뒤 빈 시간은 기록 없음으로 채운다."""
    places = places or []
    pts = sorted(
        (p for p in points if p.accuracy_m is None or p.accuracy_m <= MAX_ACCURACY_M),
        key=lambda p: p.t,
    )
    if window:
        pts = [p for p in pts if window[0] <= p.t < window[1]]
    runs = [r for r in _runs(pts) if r[-1].t - r[0].t >= MIN_RUN]

    segs: list[Seg] = []

    def add_gap(start: datetime, end: datetime) -> None:
        if end > start:
            segs.append(Seg("no_record", start, end))

    cursor = window[0] if window else None
    for run in runs:
        if cursor is not None:
            add_gap(cursor, run[0].t)
        segs.extend(_run_segments(run, places, zone))
        cursor = run[-1].t
    if window:
        add_gap(cursor if cursor is not None else window[0], window[1])
    return _name_moves(segs)


def _run_segments(run: list[Pt], places: list[KnownPlace], zone: ZoneRef | None) -> list[Seg]:
    out: list[Seg] = []
    pos = run[0].t
    for i, j in _stays(run):
        chunk = run[i : j + 1]
        lat = statistics.median(p.lat for p in chunk)
        lng = statistics.median(p.lng for p in chunk)
        if run[i].t > pos:
            out.append(Seg("move", pos, run[i].t))
        known = match_place(lat, lng, places)
        outside = (
            known is None
            and zone is not None
            and dist_m(lat, lng, zone.lat, zone.lng) > zone.radius_m
        )
        out.append(
            Seg(
                "anomaly" if outside else "stay",
                run[i].t,
                run[j].t,
                known.name if known else None,
                None,
                known.id if known else None,
                lat,
                lng,
            )
        )
        pos = run[j].t
    if run[-1].t > pos:
        out.append(Seg("move", pos, run[-1].t))
    return out


def _name_moves(segs: list[Seg]) -> list[Seg]:
    """이동의 출발지·도착지 이름을 앞뒤 머문 곳에서 가져온다(바로 이어진 머묾만)."""
    out = list(segs)
    for k, s in enumerate(out):
        if s.kind != "move":
            continue
        prev = (
            out[k - 1]
            if k > 0 and out[k - 1].end == s.start and out[k - 1].kind in ("stay", "anomaly")
            else None
        )
        nxt = (
            out[k + 1]
            if k + 1 < len(out)
            and out[k + 1].start == s.end
            and out[k + 1].kind in ("stay", "anomaly")
            else None
        )
        out[k] = Seg(
            "move", s.start, s.end, nxt.place if nxt else None, prev.place if prev else None
        )
    return out


@dataclass(frozen=True)
class Candidate:
    """이름 없는 곳 가운데 자주 머문 곳. 사용자가 이름을 붙일 수 있게 제안한다."""

    id: str
    lat: float
    lng: float
    visits: int
    last_seen: datetime


def frequent_unnamed(segs: list[Seg], min_visits: int = FREQUENT_MIN_VISITS) -> list[Candidate]:
    """이름 없는 머묾(평소 구역 밖 포함)을 가까운 것끼리 묶어 min_visits 번 이상 간 곳만 돌려준다(많이 간 순)."""
    clusters: list[dict] = []
    for s in segs:
        if s.kind not in ("stay", "anomaly") or s.place is not None or s.lat is None:
            continue
        for c in clusters:
            if dist_m(s.lat, s.lng, c["lat"], c["lng"]) <= STAY_RADIUS_M:
                c["n"] += 1
                c["last"] = max(c["last"], s.end)
                break
        else:
            clusters.append({"lat": s.lat, "lng": s.lng, "n": 1, "last": s.end})
    return [
        Candidate(candidate_id(c["lat"], c["lng"]), c["lat"], c["lng"], c["n"], c["last"])
        for c in sorted(clusters, key=lambda c: -c["n"])
        if c["n"] >= min_visits
    ]


def candidate_id(lat: float, lng: float) -> str:
    """후보 장소의 안정적인 id(좌표를 약 110m 격자로 뭉갠 값). 좌표 자체를 앱에 보내지 않고 이 id 로 이름을 붙이게 한다."""
    return f"c{round(lat * 1000)}_{round(lng * 1000)}"
