"""채팅 사진 엔드포인트. family_chat 라우터에 포함되어 /family-chat/photos 아래로 열린다. 모두 로그인과 가족 구성원 확인이 필요하다."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import photo_service
from .schemas import LibrarySaveOut, MessageOut

router = APIRouter()


@router.post("/photos", response_model=MessageOut, status_code=201)
def send_photo(
    file: UploadFile = File(...),
    room_id: str | None = Form(None, max_length=32),
    batch_id: str | None = Form(None, pattern=r"^[A-Za-z0-9_-]{8,32}$"),
    taken_at: str | None = Form(None, max_length=40),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """사진 메시지를 보낸다(multipart `file`, 선택 `room_id`, 선택 `batch_id`: 여러 장을 한 번에 올릴 때 장마다 같은 번호, 선택 `taken_at`: 앱이 읽은 촬영 시각(ISO 8601), 서버가 EXIF 에서 못 읽었을 때만 쓰고 40자 초과는 422, 형식이 틀리면 무시). JPEG/PNG/WebP 8MB 이하, 서버가 EXIF 를 지우고 다시 만든다(촬영 시각만 `taken_at` 으로 남기고 위치·기기 정보는 저장하지 않는다). 가족 전체방 사진은 보낸 뒤 서버가 뒤에서 문서 사진인지 판별해 문서면 가족 문서함에 자동 등록한다(`/photos/{id}/library` 참고)."""
    data = file.file.read(photo_service.MAX_BYTES + 1)  # 한도보다 1바이트만 더 읽어 초과를 안다
    return photo_service.send_photo(db, user, group_id, data, room_id, batch_id, taken_at)


@router.post("/photos/{attachment_id}/library", response_model=LibrarySaveOut)
def save_photo_to_library(
    attachment_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LibrarySaveOut:
    """가족 전체방에 올린 사진을 가족 공유 문서함에 직접 저장한다("문서로 저장"). 방에 들어갈 수 있는 가족 누구나 누를 수 있다.
    문서 사진 판별과 하루 상한을 건너뛰고, 글을 읽는 데는 시간이 걸려 바로 `queued` 로 답한다(이미 있으면 `already`). 1:1 방 사진은 409, 없는 사진·못 들어가는 방은 404, 너무 자주 누르면 429. `queued` 는 "저장을 시작했다"는 뜻이라, 읽지 못하면 직접 저장해도 문서함에 넣지 않는다(민감 문서도 넣고 민감 표시를 붙인다)."""
    return LibrarySaveOut(status=photo_service.save_to_library(db, user, group_id, attachment_id))


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
