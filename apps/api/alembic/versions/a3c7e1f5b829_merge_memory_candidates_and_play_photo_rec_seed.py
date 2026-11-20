"""merge memory_candidates and play_photo_rec_seed_credit

두 리비전이 서로 다른 부모에서 갈라져 release/1.3 의 head 가 둘이 됐다(CI 가 멈춘 동안 두 PR 이 각자 최신 head 를 확인하지 못했다).
- d1f4a8c6e293 memory_candidates (#481): 테이블 `memory_candidates`·`memory_candidate_photos` 추가(expand)
- e6a1b3c5d792 play_photo_rec_seed_credit (#493): `play_photo_rec` 시드 사진의 출처 칸만 채움(데이터 보강, 표 구조 변경 없음)
서로 다른 표를 다루고 순서에 의존하지 않는다.
이미 한쪽(또는 양쪽)이 적용된 DB 의 이력을 바꾸지 않으려고 두 리비전의 down_revision 은 그대로 두고, 둘을 합치는 빈 리비전만 추가한다
(스키마 변경 없음, 파괴적 변경 없음). 한쪽만 적용된 DB 는 `alembic upgrade head` 때 남은 쪽을 적용한 뒤 이 리비전에 도달한다.
downgrade 도 아무것도 하지 않는다(각 리비전의 downgrade 가 각자 변경을 되돌린다).

Revision ID: a3c7e1f5b829
Revises: d1f4a8c6e293, e6a1b3c5d792
Create Date: 2026-11-20 13:30:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a3c7e1f5b829"
down_revision: str | Sequence[str] | None = ("d1f4a8c6e293", "e6a1b3c5d792")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema(합치기만 한다. 스키마 변경 없음)."""


def downgrade() -> None:
    """Downgrade schema(합치기만 한다. 스키마 변경 없음)."""
