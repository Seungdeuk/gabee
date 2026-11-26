"""가족 타임라인의 사진 묶기(순수 함수, DB·파일·모델을 부르지 않는다).

묶는 기준(이 파일의 상수는 개발용 소규모 점검으로 정했다: 정확도 평가가 아니다 — docs/features/family-chat.md 의 "타임라인 사진 분류·묶기"):
1. 같은 `batch_id`(앱이 한 번에 올린 묶음)는 항상 한 묶음이다(기존 동작).
2. 같은 날(한국 시간 기준 날짜)에 찍은(없으면 보낸) 사진끼리만 비교한다. 다른 날짜의 비슷한 장소는 절대 합치지 않는다.
3. 같은 날이어도 두 사진의 촬영 시각 차이가 `MAX_GAP` 이내이고 SigLIP2 이미지 임베딩의 코사인 유사도가 `SIM_THRESHOLD` 이상일 때만 이어 붙인다.
4. 가장 비슷한 쌍부터 이어 붙이되, 묶음 크기가 `MAX_GROUP` 을 넘으면 더 잇지 않는다(비슷한 사진이 사슬로 끝없이 이어지는 것을 막는다).
5. 임베딩이 없는 사진(분석 전·실패·직접 확인한 사진)과 이어 붙일 상대가 없는 사진은 단독 카드다(**유사 사진이 없어도 보인다**).
임베딩은 가족별로 따로 다룬다: 이 함수는 호출한 쪽이 넘긴 한 가족의 사진만 받는다."""

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
SIM_THRESHOLD = 0.88  # 서로 다른 장면 사진 쌍의 최댓값(0.876)보다 높게, 같은 사진의 변형(자르기·밝기·재압축)은 대부분 넘는 값: 오병합보다 분리를 택한다
MAX_GAP = timedelta(
    hours=4
)  # 같은 날이어도 이보다 멀리 떨어진 사진은 잇지 않는다(아침·저녁의 같은 장소)
MAX_GROUP = 40  # 한 묶음의 최대 사진 수(유사 이음 기준)


@dataclass(frozen=True)
class GroupItem:
    attachment_id: str
    display_at: datetime  # UTC, 촬영일(없으면 보낸 시각)
    batch_id: str | None
    embedding: tuple[float, ...] | None = None  # 정규화된 이미지 임베딩(없으면 이어 붙이지 않는다)


@dataclass(frozen=True)
class GroupAssign:
    key: str | None  # 앱이 묶음 카드를 만들 때 쓰는 번호(단독이고 원래 묶음 번호도 없으면 None)
    kind: str  # "single" | "batch" | "similar"
    display_at: datetime  # 묶음에서 가장 이른 시각(묶음은 한 자리에 모여 정렬된다)


class _Sets:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int, limit: int | None = None) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if limit is not None and self.size[ra] + self.size[rb] > limit:
            return False
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        return True


def _day(value: datetime):
    return value.astimezone(KST).date()


def group_items(items: Sequence[GroupItem]) -> dict[str, GroupAssign]:
    """사진들을 묶는다. 결과는 attachment_id → GroupAssign."""
    n = len(items)
    sets = _Sets(n)
    first_of_batch: dict[str, int] = {}
    for i, item in enumerate(items):
        if item.batch_id:
            if item.batch_id in first_of_batch:
                sets.union(first_of_batch[item.batch_id], i)
            else:
                first_of_batch[item.batch_id] = i
    similar_nodes: set[int] = set()
    by_day: dict[object, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        if item.embedding is not None:
            by_day[_day(item.display_at)].append(i)
    for indexes in by_day.values():
        if len(indexes) < 2:
            continue
        import numpy as np

        matrix = np.asarray([items[i].embedding for i in indexes], dtype=np.float32)
        sims = matrix @ matrix.T
        edges = []
        for a in range(len(indexes)):
            for b in range(a + 1, len(indexes)):
                score = float(sims[a, b])
                if (
                    score >= SIM_THRESHOLD
                    and abs(items[indexes[a]].display_at - items[indexes[b]].display_at) <= MAX_GAP
                ):
                    edges.append((score, indexes[a], indexes[b]))
        edges.sort(key=lambda e: (-e[0], e[1], e[2]))  # 가장 비슷한 쌍부터(같으면 입력 순서로 고정)
        for _, i, j in edges:
            if sets.union(i, j, MAX_GROUP):
                similar_nodes.update((i, j))
    members: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        members[sets.find(i)].append(i)
    out: dict[str, GroupAssign] = {}
    for indexes in members.values():
        earliest = min(items[i].display_at for i in indexes)
        if len(indexes) == 1:
            only = items[indexes[0]]
            out[only.attachment_id] = GroupAssign(only.batch_id, "single", earliest)
            continue
        if any(i in similar_nodes for i in indexes):
            smallest = min(items[i].attachment_id for i in indexes)
            key = "s_" + hashlib.sha1(smallest.encode()).hexdigest()[:12]
            kind = "similar"
        else:
            key = items[indexes[0]].batch_id
            kind = "batch"
        for i in indexes:
            out[items[i].attachment_id] = GroupAssign(key, kind, earliest)
    return out
