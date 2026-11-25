"""가족 그룹(또는 1:1 채팅방)의 데이터를 한꺼번에 지운다. 되돌릴 수 없다.
- 가족: 구성원이 소유자 혼자인 가족을 소유자가 나갈 때(`purge_group`).
- 1:1 방: 두 사람이 모두 방을 나갔을 때(`purge_room`).

지우는 대상은 모델 메타데이터에서 찾는다: 기준 열(`group_id`/`room_id`)이 있는 모든 테이블, 그 테이블을 외래 키로 가리키는 자식 테이블(손자까지),
마지막으로 기준 줄(`groups`/`chat_rooms`) 자체. 새 기능이 같은 열의 테이블을 추가해도 이 파일을 고치지 않아도 지워진다.
- 여러 열로 이뤄진 외래 키(예: 폭탄방 말 기록의 (play_id, round_no))는 열을 한 쌍으로 비교한다(열마다 따로 비교하면 다른 가족의 줄까지 지운다).
- 외래 키는 없지만 부모 id 열만 있는 테이블은 `VIRTUAL_CHILDREN` 에 적는다(예: 옛 용돈 사용 내역).
- `KEEP_TABLES`: 고객센터 문의는 운영자가 답한 기록이라 지우지 않고, 지워진 가족을 가리키지 않도록 `group_id` 만 비운다.

한 트랜잭션 안에서만 지우고 커밋은 부르는 쪽이 한다(중간에 실패하면 부르는 쪽이 롤백해 아무것도 지워지지 않는다).
디스크 파일(채팅 사진·문서, 앱이 올린 사진, 문서함 원본, 놀이터 그림·사진)은 DB 가 커밋된 뒤(`purge_files`) 지운다 — 파일 지우기가 실패해도 DB 는 되돌리지 않는다."""

import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Table, delete, inspect, or_, select, tuple_, update
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.db import Base

logger = logging.getLogger(__name__)

KEEP_TABLES = frozenset({"support_tickets"})
GROUP_TABLE = "groups"
ROOM_TABLE = "chat_rooms"
# 외래 키가 없지만 부모 id 를 담은 열이 있는 테이블: {테이블: (열, 부모 테이블)}
VIRTUAL_CHILDREN = {"allowance_uses": ("allowance_id", "allowances")}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CHAT_FILE = re.compile(r"^chat_files/[A-Za-z0-9_-]{1,64}\.[a-z0-9]{1,5}$")


def _parents(table: Table) -> list[tuple[list, Table, list]]:
    """이 테이블이 가리키는 부모들: (내 열들, 부모 테이블, 부모 열들). 외래 키 하나(여러 열 포함)가 한 항목이다."""
    found = []
    for constraint in {fk.constraint for fk in table.foreign_keys if fk.constraint is not None}:
        mine = [table.c[e.parent.name] for e in constraint.elements]
        theirs = [e.column for e in constraint.elements]
        found.append((mine, theirs[0].table, theirs))
    virtual = VIRTUAL_CHILDREN.get(table.name)
    if virtual:
        parent = Base.metadata.tables[virtual[1]]
        found.append(([table.c[virtual[0]]], parent, [parent.c.id]))
    return found


def _scoped_tables(column: str = "group_id", root: str = GROUP_TABLE) -> list[Table]:
    """지울 테이블들을 지우는 순서대로(자식이 먼저). 기준 줄 테이블(root)은 방 범위일 때만 목록의 맨 끝에 포함한다
    (가족 범위의 `groups` 줄은 `_delete_group_row` 가 따로 지운다)."""
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    scoped = {
        name
        for name, t in tables.items()
        if name not in KEEP_TABLES and name != root and column in t.c
    }
    if root == ROOM_TABLE:
        scoped.add(root)
    changed = True
    while changed:  # 범위 안 테이블을 가리키는 테이블도 범위에 넣는다(손자까지)
        changed = False
        for name, t in tables.items():
            if name in scoped or name in KEEP_TABLES or name == root:
                continue
            if any(parent.name in scoped for _, parent, _ in _parents(t)):
                scoped.add(name)
                changed = True
    ordered = [t for t in reversed(Base.metadata.sorted_tables) if t.name in scoped]
    # 외래 키가 없는 자식은 부모 줄이 남아 있을 때 먼저 지워야 부모를 가리키는 조건이 맞는다
    virtual = [t for t in ordered if t.name in VIRTUAL_CHILDREN]
    return virtual + [t for t in ordered if t.name not in VIRTUAL_CHILDREN]


def _condition(
    table: Table,
    key: str,
    scoped_names: set[str],
    column: str = "group_id",
    root: str | None = None,
):
    """이 가족(방)의 줄만 고르는 조건: 기준 열이 있으면 그것, 기준 줄 테이블이면 id, 없으면 범위 안 부모 테이블의 이 가족(방) 줄을 가리키는 것."""
    if column in table.c:
        return table.c[column] == key
    if root is not None and table.name == root:
        return table.c.id == key
    parts = []
    for mine, parent, theirs in _parents(table):
        if parent.name not in scoped_names:
            continue
        subquery = select(*theirs).where(_condition(parent, key, scoped_names, column, root))
        parts.append(mine[0].in_(subquery) if len(mine) == 1 else tuple_(*mine).in_(subquery))
    return or_(*parts)


def _delete_group_row(db: Session, group_id: str) -> None:
    groups = Base.metadata.tables[GROUP_TABLE]
    db.execute(delete(groups).where(groups.c.id == group_id))


def _detach_kept_tables(db: Session, group_id: str) -> None:
    """지우지 않는 테이블(고객센터 문의)이 지워질 가족을 가리키지 않도록 group_id 를 비운다."""
    for name in KEEP_TABLES:
        table = Base.metadata.tables.get(name)
        if table is not None and "group_id" in table.c:
            db.execute(update(table).where(table.c.group_id == group_id).values(group_id=None))


def _inside(base: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


def _attachment_paths(db: Session, where: Callable[[Table], object]) -> list[Path]:
    """조건에 맞는 채팅 첨부의 디스크 파일 경로(서버가 만든 이름 형태이고 보관 폴더 안일 때만)."""
    attachments = Base.metadata.tables.get("message_attachments")
    if attachments is None:
        return []
    base = Path(settings.data_dir)
    paths: list[Path] = []
    for attachment_id, kind, path in db.execute(
        select(attachments.c.id, attachments.c.kind, attachments.c.path).where(where(attachments))
    ):
        if not isinstance(attachment_id, str) or not _SAFE_ID.match(attachment_id):
            continue
        if kind == "image":
            paths += [
                base / "chat_photos" / f"{attachment_id}.jpg",
                base / "chat_photos" / f"{attachment_id}_t.jpg",
                # 타임라인 분석 결과(임베딩)·실패 기록: 사진에서 파생된 데이터라 사진과 함께 지운다
                base / "chat_photos" / f"{attachment_id}_sig.json",
                base / "chat_photos" / f"{attachment_id}_sigfail.json",
                base
                / "chat_photos"
                / f"{attachment_id}_sig.json.tmp",  # 쓰다 멈춘 임시 파일(임베딩이 들어 있을 수 있다)
                base / "chat_photos" / f"{attachment_id}_sigfail.json.tmp",
            ]
        elif (
            isinstance(path, str)
            and _CHAT_FILE.match(path)
            and path.startswith(f"chat_files/{attachment_id}.")
        ):
            paths.append(base / path)
    return [p for p in paths if _inside(base, p)]


def _file_paths(db: Session, group_id: str) -> list[Path]:
    """이 가족의 디스크 파일·폴더 경로(서버가 만든 이름 형태이고 보관 폴더 안일 때만). 폴더는 통째로 지운다."""
    if not _SAFE_ID.match(group_id):
        return []
    base = Path(settings.data_dir)
    paths = _attachment_paths(db, lambda t: t.c.group_id == group_id)

    photos = Base.metadata.tables.get("photos")
    if photos is not None:
        for (photo_id,) in db.execute(select(photos.c.id).where(photos.c.group_id == group_id)):
            if isinstance(photo_id, str) and _SAFE_ID.match(photo_id):
                paths += [base / "photos" / f"{photo_id}.jpg", base / "photos" / f"{photo_id}.png"]

    raw_root = Path(settings.raw_dir or base / "raw")
    paths += [
        raw_root / group_id,
        base / "play" / "drawings" / group_id,
        base / "play" / "photos" / group_id,
    ]
    return [p for p in paths if _inside(base, p) or _inside(raw_root, p)]


def _present(db: Session) -> set[str]:
    """이 DB 에 실제로 있는 테이블 이름. 코드가 DB 보다 먼저 배포돼 아직 만들어지지 않은 테이블은 지울 줄도 없으니 건너뛴다
    (건너뛰지 않으면 새 테이블 하나 때문에 가족 삭제·1:1 방 나가기가 500 이 된다)."""
    return set(inspect(db.connection()).get_table_names())


def purge_group(db: Session, group_id: str) -> list[Path]:
    """이 가족의 모든 데이터(DB 줄)를 지우고 지워야 할 디스크 파일·폴더 경로를 돌려준다. 커밋은 하지 않는다."""
    files = _file_paths(db, group_id)  # 줄이 지워지기 전에 모은다
    tables = _scoped_tables()
    names = {t.name for t in tables}
    _detach_kept_tables(db, group_id)
    present = _present(db)
    for table in tables:
        if table.name not in present:
            continue
        db.execute(
            delete(table)
            .where(_condition(table, group_id, names))
            .execution_options(synchronize_session=False)
        )
    _delete_group_row(db, group_id)
    return files


def purge_room(db: Session, room_id: str) -> list[Path]:
    """1:1 채팅방 하나의 모든 데이터(메시지·첨부·반응·고정·읽음·알림 설정 등과 방 줄)를 지우고 지워야 할 채팅 사진·문서 파일 경로를
    돌려준다. 커밋은 하지 않는다. 다른 방과 가족의 데이터는 건드리지 않는다."""
    files = _attachment_paths(db, lambda t: t.c.room_id == room_id)
    tables = _scoped_tables("room_id", ROOM_TABLE)
    names = {t.name for t in tables}
    present = _present(db)
    for table in tables:
        if table.name not in present:
            continue
        db.execute(
            delete(table)
            .where(_condition(table, room_id, names, "room_id", ROOM_TABLE))
            .execution_options(synchronize_session=False)
        )
    return files


def purge_files(paths: list[Path]) -> None:
    """DB 삭제가 커밋된 뒤 파일·폴더를 지운다. 이미 없거나 지우지 못해도 넘어간다(경로·이름은 로그에 남기지 않는다)."""
    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("group purge file failed error=%s", type(exc).__name__)
