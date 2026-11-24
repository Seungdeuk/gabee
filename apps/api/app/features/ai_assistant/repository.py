from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Photo


def count_stale_received(db: Session, before: datetime) -> int:
    """`before` 이전에 만들어졌는데 아직 `received`(읽는 중) 인 업로드 수. 읽기만 한다(상태를 바꾸지 않는다)."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(Photo)
            .where(Photo.status == "received", Photo.created_at <= before)
        )
        or 0
    )


def add(db: Session, photo: Photo) -> Photo:
    db.add(photo)
    db.commit()
    return photo


def get_photo(db: Session, group_id: str, photo_id: str) -> Photo | None:
    return db.scalar(select(Photo).where(Photo.id == photo_id, Photo.group_id == group_id))


def set_status(db: Session, photo_id: str, status: str) -> None:
    photo = db.get(Photo, photo_id)
    if photo is not None:
        photo.status = status
        db.commit()


def delete_photo(db: Session, photo_id: str) -> None:
    photo = db.get(Photo, photo_id)
    if photo is not None:
        db.delete(photo)
        db.commit()


def review_ids(db: Session, group_id: str) -> set[str]:
    """확인이 필요한 채로 저장된 파일 id (knowledge 기록 id 와 같다)."""
    return set(
        db.scalars(
            select(Photo.id).where(Photo.group_id == group_id, Photo.status == "needs_review")
        )
    )


def list_photos(db: Session, group_id: str) -> list[Photo]:
    return list(
        db.scalars(
            select(Photo).where(Photo.group_id == group_id).order_by(Photo.created_at.desc())
        )
    )
