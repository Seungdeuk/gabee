"""추억 후보 그룹화 합성 평가(PR5, 개발용). **정답 라벨이 있는 합성 가족 타임라인**으로 `grouping.group_photos` 의 묶음 정확도를 잰다.

주의: 정답은 합성 데이터를 만들 때 정한 이벤트 번호라서 실제 가족 이벤트에 대한 정확도가 아니다(실제 사진·SigLIP2 임베딩 분포와 다르다). 알고리즘의 구조적 약점(다른 연도·같은 날 다른
장면·batch_id·날짜 누락·중복)을 잡아내는 회귀 점검용이고, 기존 SigLIP2 PoC 의 주제별 묶음은 정답으로 쓰지 않았다. 실제 사진 평가는 독립 라벨 데이터가 생긴 뒤 별도로 한다.

사용법(apps/api 에서): python scripts/grouping_synthetic_eval.py [타임라인 수] [난수 시드]
"""

import math
import random
import sys
from datetime import UTC, datetime, timedelta
from itertools import combinations

from app.features.family_memory import grouping as g

DIM = 32


def _unit(vec):
    n = math.sqrt(sum(v * v for v in vec))
    return tuple(v / n for v in vec)


def _topic(rng):
    return _unit([rng.gauss(0, 1) for _ in range(DIM)])


def _near(base, rng, noise):
    return tuple(v + rng.gauss(0, noise / math.sqrt(DIM)) for v in base)


def make_timeline(rng: random.Random, tid: int, noise: float):
    """가족 한 곳의 합성 타임라인: (사진 목록, {attachment_id: 정답 이벤트}). 이벤트 사이 간격과 장면 중복을 일부러 어렵게 만든다.
    같은 장면이 여러 이벤트·연도에 반복되고, 같은 날 다른 이벤트가 있고, 하룻밤 지나 이어지는 이벤트(같은 이벤트)도 있다."""
    topics = [_topic(rng) for _ in range(4)]  # 가족이 자주 찍는 장면
    photos, truth = [], {}
    clock = datetime(2022, 1, 1, 9, 0, tzinfo=UTC)
    event_no, last_topic = -1, topics[0]
    for _ in range(rng.randint(5, 8)):
        kind = rng.choice(["same_day_next", "days_later", "next_year", "overnight"])
        if kind == "same_day_next":
            clock += timedelta(hours=rng.uniform(3, 6))  # 같은 날 다른 이벤트(다른 장면)
            topic = next(t for t in topics if t != last_topic)
        elif kind == "overnight":
            clock += timedelta(
                hours=rng.uniform(12, 24)
            )  # 하룻밤 뒤 이어지는 같은 이벤트(같은 장면)
            topic = last_topic
        elif kind == "days_later":
            clock += timedelta(days=rng.uniform(3, 30))
            topic = topics[rng.randrange(4)]
        else:
            clock += timedelta(days=rng.uniform(340, 400))  # 다른 연도, 같은 장면일 수 있다
            topic = topics[rng.randrange(4)]
        if kind != "overnight" or event_no < 0:
            event_no += 1
        last_topic = topic
        n = rng.randint(4, 9)
        batch = f"b{tid:03d}{event_no:03d}{rng.randrange(99):02d}" if rng.random() < 0.6 else None
        start = clock
        for i in range(n):
            pid = f"t{tid:03d}e{event_no:02d}p{rng.randrange(10**6):06d}"
            when = start + timedelta(minutes=rng.uniform(0, 90))
            undated = rng.random() < 0.08
            photos.append(
                g.PhotoFeatures(
                    attachment_id=pid,
                    group_id=f"fam{tid:03d}",
                    uploader_id="u1",
                    uploaded_at=datetime(
                        2025, 1, 1, tzinfo=UTC
                    ),  # 업로드는 한꺼번에: 근거로 쓰지 않는다
                    taken_at=None if undated else when,
                    batch_id=batch,
                    embedding=_near(topic, rng, noise),
                    content_hash=f"dup{tid}-{event_no}"
                    if (i == 1 and rng.random() < 0.5)
                    else None,
                    sharpness=rng.uniform(0.2, 1.0),
                    exposure=rng.uniform(0.3, 1.0),
                )
            )
            truth[pid] = (tid, event_no)
        clock = start + timedelta(minutes=90)
    return photos, truth


def evaluate(timelines: int, seed: int, noise: float, cfg: g.GroupingConfig | None = None) -> dict:
    rng = random.Random(seed)
    tp = fp = fn = 0
    cross_event_groups = groups_total = events_total = events_recovered = 0
    for tid in range(timelines):
        photos, truth = make_timeline(rng, tid, noise)
        candidates = g.group_photos(photos, cfg)
        grouped = {a: i for i, c in enumerate(candidates) for a in c.attachment_ids}
        for c in candidates:
            groups_total += 1
            if len({truth[a] for a in c.attachment_ids}) > 1:
                cross_event_groups += 1
        by_event: dict[tuple, list[str]] = {}
        for pid, ev in truth.items():
            by_event.setdefault(ev, []).append(pid)
        events_total += len(by_event)
        for members in by_event.values():
            best = max(
                (sum(1 for m in members if grouped.get(m) == i) for i in set(grouped.values())),
                default=0,
            )
            if best >= max(3, math.ceil(0.7 * len(members))):
                events_recovered += 1
        for a, b in combinations(sorted(truth), 2):
            same = truth[a] == truth[b]
            together = a in grouped and b in grouped and grouped[a] == grouped[b]
            tp += same and together
            fp += (not same) and together
            fn += same and not together
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "noise": noise,
        "pair_precision": round(precision, 4),
        "pair_recall": round(recall, 4),
        "pair_f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0,
        "groups": groups_total,
        "cross_event_group_rate": round(cross_event_groups / groups_total, 4)
        if groups_total
        else 0,
        "event_recovery": round(events_recovered / events_total, 4),
    }


def main() -> int:
    timelines = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20241101
    print(f"합성 타임라인 {timelines}개 · 시드 {seed} · 알고리즘 {g.ALGORITHM_VERSION}")
    print("--- 기본 설정, 이미지 잡음 수준별(같은 장면 사진 사이 유사도가 낮아질수록 어렵다)")
    for noise in (0.3, 0.5, 0.8):
        print(evaluate(timelines, seed, noise))
    print("--- 민감도(잡음 0.5): 설정을 바꾸면 결과가 얼마나 변하는가")
    base = g.GroupingConfig()
    for label, cfg in {
        "기본": base,
        "gap_hours=4": g.GroupingConfig(gap_hours=4.0),
        "gap_hours=12": g.GroupingConfig(gap_hours=12.0),
        "split_cos=0.55": g.GroupingConfig(split_cos=0.55),
        "split_cos=0.85": g.GroupingConfig(split_cos=0.85),
        "bridge 끔(bridge_hours=0)": g.GroupingConfig(bridge_hours=0.0),
        "min_unique_photos=2": g.GroupingConfig(min_unique_photos=2),
    }.items():
        print(label, evaluate(timelines, seed, 0.5, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
