"""merge play_draw_stock and family_memory_consent

두 리비전이 같은 부모(9c4e7a2b1d63)에서 갈라져 release/1.3 의 head 가 둘이 됐다.
- c4e81a7d3f26 play_draw_stock (#459): 테이블 `play_draw_stock` + 인덱스 하나 추가
- f5b1c8d4e2a7 family_memory_consent (#452): 테이블 `family_memory_settings`·`member_memory_consents`·`photo_analysis_exclusions` + 인덱스 하나 추가
둘 다 새 테이블만 만드는 expand 변경이고 서로 같은 테이블·컬럼·인덱스·제약을 건드리지 않아 순서에 의존하지 않는다.
이미 한쪽(또는 양쪽)이 적용된 DB 의 이력을 바꾸지 않으려고 두 리비전의 down_revision 은 그대로 두고, 둘을 합치는 빈 리비전만 추가한다
(스키마 변경 없음, 파괴적 변경 없음). 한쪽만 적용된 DB 는 `alembic upgrade head` 때 남은 쪽을 적용한 뒤 이 리비전에 도달한다.
downgrade 도 아무것도 하지 않는다(각 리비전의 downgrade 가 각자 테이블을 지운다).

Revision ID: 639d80e653b4
Revises: c4e81a7d3f26, f5b1c8d4e2a7
Create Date: 2026-11-19 10:37:15.011070

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "639d80e653b4"
down_revision: str | Sequence[str] | None = ("c4e81a7d3f26", "f5b1c8d4e2a7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema(합치기만 한다. 스키마 변경 없음)."""


def downgrade() -> None:
    """Downgrade schema(합치기만 한다. 스키마 변경 없음)."""
