from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import repository, service
from .models import Photo
from .schemas import ChatIn, ChatOut, PhotoOut

router = APIRouter(prefix="/ai-assistant", tags=["ai-assistant"])


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, user=Depends(current_user)) -> ChatOut:
    return service.chat(body.message)


@router.post("/photos", response_model=PhotoOut, status_code=201)
async def upload_photo(
    file: UploadFile = File(...),
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Photo:
    data = await file.read()
    return service.save_photo(
        db, group_id, user.id, file.filename or "photo", file.content_type or "", data
    )


@router.get("/photos", response_model=list[PhotoOut])
def list_photos(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> list[Photo]:
    return repository.list_photos(db, group_id)
