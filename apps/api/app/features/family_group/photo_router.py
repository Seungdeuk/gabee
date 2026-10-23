"""프로필 사진(PR B) 엔드포인트. family_group 라우터에 포함되어 /family-group 아래로 열린다. 모두 로그인이 필요하다."""

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.shared.auth import current_user
from app.shared.db import get_db

from . import photo_service
from .models import User
from .photo_schemas import ProfilePhotoOut

router = APIRouter()


@router.post("/me/photo", response_model=ProfilePhotoOut)
def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfilePhotoOut:
    """내 프로필 사진을 올린다(multipart `file`). JPEG/PNG/WebP 2MB 이하, 서버가 512px 정사각형 JPEG 로 다시 만든다."""
    data = file.file.read(photo_service.MAX_BYTES + 1)  # 한도보다 1바이트만 더 읽어 초과를 안다
    return photo_service.upload_my_photo(db, user, data)


@router.delete("/me/photo", status_code=204)
def delete_photo(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """내 프로필 사진을 지운다(없어도 204)."""
    photo_service.delete_my_photo(db, user)
    return Response(status_code=204)


@router.get(
    "/users/{user_id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "프로필 사진(JPEG)"}},
)
def get_photo(
    user_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """같은 가족 구성원의 프로필 사진. 가족이 아니거나 사진이 없으면 404. ETag 로 다시 받기를 줄인다."""
    data, target = photo_service.photo_for_viewer(db, user, user_id)
    etag = f'"{photo_service.version_of(target)}"'
    headers = {
        "Cache-Control": photo_service.CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/jpeg", headers=headers)
