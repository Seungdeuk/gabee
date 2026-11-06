from sqlalchemy.orm import Session

from . import repository
from .schemas import NoticeList, NoticeOut


def latest(db: Session) -> NoticeList:
    return NoticeList(
        rows=[NoticeOut.model_validate(n, from_attributes=True) for n in repository.latest(db)]
    )
