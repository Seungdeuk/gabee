"""찰칵! 탐정단 가비 추천의 흔한 사진 풀: 모든 가족이 같이 읽는 행(`group_id` 가 빔)에서 고른다.

- `pool_rows`: 쓸 수 있는 흔한 사진 행을 `id` 오름차순으로 읽는다(이 가족이 최근 보낸 것은 `exclude_ids` 로 뺀다).
- `pick_common`: 시드가 정해진 `rng` 로 중복 없이 고른다(같은 시드면 같은 결과).
"""

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PlayPhotoRec


def pool_rows(db: Session, exclude_ids: set[str]) -> list[PlayPhotoRec]:
    """흔한 사진(`group_id` 없음)이고 `usable` 인 행. `exclude_ids` 는 뺀다. `id` 오름차순."""
    stmt = (
        select(PlayPhotoRec)
        .where(PlayPhotoRec.group_id.is_(None), PlayPhotoRec.usable.is_(True))
        .order_by(PlayPhotoRec.id)
    )
    return [r for r in db.scalars(stmt) if r.id not in exclude_ids]


def pick_common(rows: list[PlayPhotoRec], n: int, rng: random.Random) -> list[PlayPhotoRec]:
    """중복 없이 최대 `n` 개. 행이 모자라면 있는 만큼 돌려준다."""
    return rng.sample(rows, min(n, len(rows)))
