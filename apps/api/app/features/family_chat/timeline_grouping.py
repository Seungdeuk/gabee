"""가족 타임라인의 사진 묶기(순수 함수, DB·파일·모델을 부르지 않는다).

묶는 기준(이 파일의 상수는 개발용 소규모 점검으로 정했다: 정확도 평가가 아니다 — docs/features/family-chat.md 의 "타임라인 사진 분류·묶기"):
1. 같은 `batch_id`(앱이 한 번에 올린 묶음, 2장 이상)는 항상 한 묶음이다(기존 동작). **업로드 묶음의 사진은 유사 묶기에 쓰지 않는다**:
   업로드 묶음은 묶음끼리만, 유사 묶음은 업로드 묶음에 속하지 않은(단독으로 올린) 사진끼리만 만든다. 둘을 이어 붙이면 내용이 다른 사진이 사슬로 합쳐진다.
2. 같은 날(한국 시간 기준 날짜)에 찍은(없으면 보낸) 사진끼리만 비교한다. 다른 날짜의 비슷한 장소는 절대 합치지 않는다.
3. 유사 묶음은 **묶음 안 모든 쌍**이 조건을 만족할 때만 만든다: 두 사진의 촬영 시각 차이가 `MAX_GAP` 이내이고 SigLIP2 이미지 임베딩의
   코사인 유사도가 `SIM_THRESHOLD` 이상. 쌍 하나만 비슷해서 이어 붙이는 사슬(A~B, B~C 이면 A·C 까지 합쳐지는 것)은 만들지 않는다.
4. 가장 비슷한 쌍부터 합치되, 묶음 크기가 `MAX_GROUP` 을 넘으면 더 합치지 않는다.
5. 임베딩이 없는 사진(분석 전·실패·직접 확인한 사진)과 합칠 상대가 없는 사진은 단독 카드다(**유사 사진이 없어도 보인다**).
6. **같은 사진은 하나만 보인다**(`duplicate_ids`): 같은 날 안에서 임베딩 코사인 유사도가 `DUP_THRESHOLD` 이상인 사진은 같은 사진으로 보고, 묶기 전에
   하나만 남기고 나머지는 타임라인 응답에서 뺀다(채팅·문서함·DB 의 사진은 그대로). 직접 확인·포함한 사진을 먼저 남기고, 그다음 먼저 올린 사진, 첨부 id 순이다.
   남긴 사진과 직접 비교해 기준을 넘는 사진만 뺀다(A~B, B~C 가 0.99 이상이어도 A~C 가 아니면 C 는 남는다).
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
MAX_GROUP = 40  # 한 묶음의 최대 사진 수(유사 묶음 기준)
DUP_THRESHOLD = 0.99  # 같은 사진으로 보는 기준(밝기만 바꾼 변형 0.998, 자르기·크기 줄이기 변형 0.95~0.98: 개발용 목업 확인이고 정확도 평가가 아니다)


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


def _day(value: datetime):
    return value.astimezone(KST).date()


def _similar_clusters(items: Sequence[GroupItem], indexes: list[int]) -> list[list[int]]:
    """같은 날 사진들(indexes, items 의 위치)을 완전 연결 방식으로 묶는다: 두 묶음은 서로의 모든 쌍이 조건을 만족할 때만 합쳐진다.
    결과는 크기 2 이상인 묶음들(각 묶음은 items 위치 목록). 입력 순서가 달라도 같은 결과가 나오게 동점은 첨부 id 로 정한다."""
    import numpy as np

    matrix = np.asarray([items[i].embedding for i in indexes], dtype=np.float32)
    sims = matrix @ matrix.T
    ids = [items[i].attachment_id for i in indexes]
    times = [items[i].display_at for i in indexes]
    count = len(indexes)
    ok = np.zeros((count, count), dtype=bool)  # 한 쌍이 조건을 만족하는가
    edges = []
    for a in range(count):
        for b in range(a + 1, count):
            if float(sims[a, b]) >= SIM_THRESHOLD and abs(times[a] - times[b]) <= MAX_GAP:
                ok[a, b] = ok[b, a] = True
                first, second = (a, b) if ids[a] <= ids[b] else (b, a)
                edges.append((float(sims[a, b]), first, second))
    edges.sort(
        key=lambda e: (-e[0], ids[e[1]], ids[e[2]])
    )  # 가장 비슷한 쌍부터, 같으면 id 순서로 고정
    owner = list(range(count))  # 각 사진이 속한 묶음 번호
    members: dict[int, list[int]] = {k: [k] for k in range(count)}
    for _, a, b in edges:
        ra, rb = owner[a], owner[b]
        if ra == rb:
            continue
        if len(members[ra]) + len(members[rb]) > MAX_GROUP:
            continue
        if not all(ok[x, y] for x in members[ra] for y in members[rb]):
            continue  # 쌍 하나만 비슷해서는 합치지 않는다(사슬 방지)
        for x in members[rb]:
            owner[x] = ra
        members[ra].extend(members.pop(rb))
    return [[indexes[k] for k in group] for group in members.values() if len(group) > 1]


def duplicate_ids(items: Sequence[GroupItem], preferred: set[str]) -> set[str]:
    """같은 사진(같은 날, 임베딩 코사인 >= DUP_THRESHOLD)이면 하나만 남기고 나머지의 attachment_id 를 돌려준다(타임라인에서 뺄 사진).
    남기는 순서: preferred(직접 확인·포함한 사진) → 먼저 올린 사진 → 첨부 id. 이미 남기기로 한 사진과 직접 비교해서 기준을 넘는 사진만 뺀다.
    임베딩이 없는 사진은 비교할 수 없으므로 빼지 않는다. 입력 순서가 달라도 결과는 같다."""
    import numpy as np

    by_day: dict[object, list[GroupItem]] = defaultdict(list)
    for item in items:
        if item.embedding is not None:
            by_day[_day(item.display_at)].append(item)
    hidden: set[str] = set()
    for day_items in by_day.values():
        if len(day_items) < 2:
            continue
        ordered = sorted(
            day_items,
            key=lambda it: (it.attachment_id not in preferred, it.display_at, it.attachment_id),
        )
        matrix = np.asarray([it.embedding for it in ordered], dtype=np.float32)
        sims = matrix @ matrix.T
        kept: list[int] = []
        for index, item in enumerate(ordered):
            if any(float(sims[index, k]) >= DUP_THRESHOLD for k in kept):
                hidden.add(item.attachment_id)
            else:
                kept.append(index)
    return hidden


def group_items(items: Sequence[GroupItem]) -> dict[str, GroupAssign]:
    """사진들을 묶는다. 결과는 attachment_id → GroupAssign."""
    by_batch: dict[str, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        if item.batch_id:
            by_batch[item.batch_id].append(i)
    out: dict[str, GroupAssign] = {}
    in_upload_batch: set[int] = set()
    for batch_id, indexes in by_batch.items():
        if len(indexes) < 2:
            continue  # 한 장짜리 업로드는 단독 사진으로 본다(유사 묶기에 쓸 수 있다)
        in_upload_batch.update(indexes)
        earliest = min(items[i].display_at for i in indexes)
        for i in indexes:
            out[items[i].attachment_id] = GroupAssign(batch_id, "batch", earliest)
    by_day: dict[object, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        if i not in in_upload_batch and item.embedding is not None:
            by_day[_day(item.display_at)].append(i)
    in_similar: set[int] = set()
    for indexes in by_day.values():
        if len(indexes) < 2:
            continue
        for group in _similar_clusters(items, indexes):
            earliest = min(items[i].display_at for i in group)
            smallest = min(items[i].attachment_id for i in group)
            key = "s_" + hashlib.sha1(smallest.encode()).hexdigest()[:12]
            for i in group:
                out[items[i].attachment_id] = GroupAssign(key, "similar", earliest)
            in_similar.update(group)
    for i, item in enumerate(items):
        if i not in in_upload_batch and i not in in_similar:
            out[item.attachment_id] = GroupAssign(item.batch_id, "single", item.display_at)
    return out
