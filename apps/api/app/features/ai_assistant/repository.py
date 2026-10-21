from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Photo


def add(db: Session, photo: Photo) -> Photo:
    db.add(photo)
    db.commit()
    return photo


def list_photos(db: Session, group_id: str) -> list[Photo]:
    return list(
        db.scalars(
            select(Photo).where(Photo.group_id == group_id).order_by(Photo.created_at.desc())
        )
    )
