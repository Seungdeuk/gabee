"""가족 그룹의 데이터를 한꺼번에 지운다(구성원이 소유자 혼자인 가족을 소유자가 나갈 때). 되돌릴 수 없다.

지우는 대상은 모델 메타데이터에서 찾는다: `group_id` 열이 있는 모든 테이블, 그 테이블을 외래 키로 가리키는 자식 테이블(손자까지),
마지막으로 `groups` 줄 자체. 새 기능이 `group_id` 테이블을 추가해도 이 파일을 고치지 않아도 지워진다.
예외(`KEEP_TABLES`): 고객센터 문의는 운영자가 답한 기록이라 가족과 함께 지우지 않는다(`group_id` 는 외래 키가 아니다).

한 트랜잭션 안에서만 지우고 커밋은 부르는 쪽이 한다(중간에 실패하면 부르는 쪽이 롤백해 아무것도 지워지지 않는다).
디스크의 채팅 사진·문서 파일은 DB 가 지워진 뒤(`purge_files`) 부르는 쪽이 지운다 — 파일 지우기가 실패해도 DB 는 되돌리지 않는다."""

import logging
from pathlib import Path

from sqlalchemy import Table, delete, or_, select
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.db import Base

logger = logging.getLogger(__name__)

KEEP_TABLES = frozenset({"support_tickets"})
GROUP_TABLE = "groups"
SAFE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


def _scoped_tables() -> list[Table]:
    """지울 테이블들을 지우는 순서대로(자식이 먼저)."""
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    scoped = {
        name
        for name, t in tables.items()
        if name not in KEEP_TABLES and name != GROUP_TABLE and "group_id" in t.c
    }
    changed = True
    while changed:  # 범위 안 테이블을 외래 키로 가리키는 테이블도 범위에 넣는다(손자까지)
        changed = False
        for name, t in tables.items():
            if name in scoped or name in KEEP_TABLES or name == GROUP_TABLE:
                continue
            if any(fk.column.table.name in scoped for fk in t.foreign_keys):
                scoped.add(name)
                changed = True
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name in scoped]


def _condition(table: Table, group_id: str, scoped_names: set[str]):
    """이 가족의 줄만 고르는 조건: group_id 가 있으면 그것, 없으면 범위 안 부모 테이블의 이 가족 줄을 가리키는 것."""
    if "group_id" in table.c:
        return table.c.group_id == group_id
    parts = []
    for fk in table.foreign_keys:
        parent = fk.column.table
        if parent.name in scoped_names:
            parts.append(
                table.c[fk.parent.name].in_(
                    select(fk.column).where(_condition(parent, group_id, scoped_names))
                )
            )
    # 부모가 둘 이상이면 하나라도 이 가족이면 이 가족 줄이다(같은 가족 안에서만 이어져 있다)
    return or_(*parts)


def _delete_group_row(db: Session, group_id: str) -> None:
    db.execute(
        delete(Base.metadata.tables[GROUP_TABLE]).where(
            Base.metadata.tables[GROUP_TABLE].c.id == group_id
        )
    )


def _file_paths(db: Session, group_id: str) -> list[Path]:
    """이 가족의 채팅 첨부 파일 경로(서버가 만든 이름 형태일 때만)."""
    table = Base.metadata.tables.get("message_attachments")
    if table is None:
        return []
    base = Path(settings.data_dir)
    paths: list[Path] = []
    for attachment_id, kind, path in db.execute(
        select(table.c.id, table.c.kind, table.c.path).where(table.c.group_id == group_id)
    ):
        if not attachment_id or not set(attachment_id) <= SAFE_NAME_CHARS:
            continue
        if kind == "image":
            paths += [
                base / "chat_photos" / f"{attachment_id}.jpg",
                base / "chat_photos" / f"{attachment_id}_t.jpg",
            ]
        elif (
            isinstance(path, str)
            and path.startswith(f"chat_files/{attachment_id}")
            and set(path) <= SAFE_NAME_CHARS | {"/"}
            and ".." not in path
        ):
            paths.append(base / path)
    return paths


def purge_group(db: Session, group_id: str) -> list[Path]:
    """이 가족의 모든 데이터(DB 줄)를 지우고 지워야 할 디스크 파일 경로를 돌려준다. 커밋은 하지 않는다."""
    files = _file_paths(db, group_id)  # 줄이 지워지기 전에 모은다
    tables = _scoped_tables()
    names = {t.name for t in tables}
    for table in tables:
        db.execute(
            delete(table)
            .where(_condition(table, group_id, names))
            .execution_options(synchronize_session=False)
        )
    _delete_group_row(db, group_id)
    return files


def purge_files(paths: list[Path]) -> None:
    """DB 삭제가 커밋된 뒤 파일을 지운다. 이미 없거나 지우지 못해도 넘어간다(경로·이름은 로그에 남기지 않는다)."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("group purge file failed error=%s", type(exc).__name__)
