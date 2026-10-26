"""채팅 사진 엔드포인트. family_chat 라우터에 포함되어 /family-chat/photos 아래로 열린다. 모두 로그인과 가족 구성원 확인이 필요하다."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import photo_service
from .schemas import MessageOut

router = APIRouter()


@router.post("/photos", response_model=MessageOut, status_code=201)
def send_photo(
    file: UploadFile = File(...),
    room_id: str | None = Form(None, max_length=32),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """사진 메시지를 보낸다(multipart `file`, 선택 `room_id`). JPEG/PNG/WebP 8MB 이하, 서버가 EXIF 를 지우고 다시 만든다. AI 를 부르지 않는다."""
    data = file.file.read(photo_service.MAX_BYTES + 1)  # 한도보다 1바이트만 더 읽어 초과를 안다
    return photo_service.send_photo(db, user, group_id, data, room_id)


@router.get(
    "/photos/{attachment_id}",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "채팅 사진(JPEG)"}},
)
def get_photo(
    attachment_id: str,
    request: Request,
    size: Literal["full", "thumb"] = Query("full"),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """방에 들어갈 수 있는 사람만 볼 수 있다. 없는 사진·못 들어가는 방은 모두 404. 사진은 바뀌지 않아 오래 캐시한다."""
    data, etag = photo_service.photo_for_viewer(db, user, group_id, attachment_id, size == "thumb")
    headers = {
        "Cache-Control": photo_service.CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/jpeg", headers=headers)
