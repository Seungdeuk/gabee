"""채팅 사진 엔드포인트. family_chat 라우터에 포함되어 /family-chat/photos 아래로 열린다. 모두 로그인과 가족 구성원 확인이 필요하다."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import photo_check_service, photo_service
from .schemas import (
    LibrarySaveOut,
    LibraryStateOut,
    MessageOut,
    PhotoCheckIn,
    PhotoCheckOut,
    PhotoChecksOut,
)

router = APIRouter()


@router.get("/photos/checks/mine", response_model=PhotoChecksOut)
def my_photo_checks(
    limit: int = Query(30, ge=1, le=50),
    before: int | None = Query(None, ge=1),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PhotoChecksOut:
    """내가 가족 전체방에 올린 사진 중 확인이 필요한 것만(최신순): 애매(`unsure`)·판별 실패(`failed`)·올린 지 15분 넘게 판별되지 않은(`pending`) 사진.
    다른 가족이 올린 사진은 절대 섞이지 않고, 가족에게 새로 알리는 것도 없다(푸시 없음). `before` 는 이전 응답의 `next_before`. 조회에 실패하면
    빈 목록이 아니라 503. `pending` 을 일반 사진으로 보지 않는다: 15분은 "처리 지연" 표시 기준일 뿐이다."""
    return photo_check_service.review_list(db, user, group_id, limit, before)


@router.post("/photos/{attachment_id}/check", response_model=PhotoCheckOut)
def confirm_general_photo(
    attachment_id: str,
    body: PhotoCheckIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PhotoCheckOut:
    """업로더가 "일반 사진이에요"를 명시적으로 확인한다(가족 타임라인에 보이게 된다). 본문 `acknowledge` 는 반드시 true(아니면 422).
    업로더 본인이 가족 전체방에 올린 살아 있는 사진만(그 밖은 모두 404: 존재를 숨긴다). 문서로 판별·저장됐거나 문서함에 등록된 사진은 409
    `document_to_photo_blocked`(문서→일반 전환은 MVP 에서 막는다), 올린 지 15분 안 된 판별 대기는 409 `check_in_progress`, 문서함 등록 여부를
    확인하지 못하면 503. 같은 요청을 다시 보내도 결과는 같고(200) 이력은 한 줄만 남는다. 자동 판별은 이 확인을 덮어쓰지 못한다."""
    return photo_check_service.confirm_general(db, user, group_id, attachment_id)


@router.get("/photos/{attachment_id}/library", response_model=LibraryStateOut)
def photo_library_state(
    attachment_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LibraryStateOut:
    """사진이 가족 문서함에 등록됐는지(`registered`/`not_registered`). 방에 들어갈 수 있는 가족 누구나. 없는 사진·못 들어가는 방은 404, 1:1 방은 409.
    "문서로 저장"이 `queued` 만 답하므로 앱은 이것으로 결과를 확인한다. 확인하지 못하면 `not_registered`(성공으로 보이지 않게)이고,
    아직 없으면 `POST /photos/{id}/library` 를 다시 요청해 이어서 등록한다(같은 요청은 한 번만 등록된다)."""
    return photo_check_service.library_state(db, user, group_id, attachment_id)


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
