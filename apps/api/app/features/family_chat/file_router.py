"""채팅 문서 파일 엔드포인트. family_chat 라우터에 포함되어 /family-chat/files 아래로 열린다. 모두 로그인과 가족 구성원 확인이 필요하다."""

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import file_service
from .schemas import MessageOut

router = APIRouter()


@router.post("/files", response_model=MessageOut, status_code=201)
def send_file(
    file: UploadFile = File(...),
    room_id: str | None = Form(None, max_length=32),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """문서 파일 메시지를 보낸다(multipart `file`, 선택 `room_id`). 문서류(pdf, doc/docx, xls/xlsx, ppt/pptx, hwp/hwpx, txt, csv) 20MB 이하. AI 를 부르지 않는다."""
    return file_service.send_file(db, user, group_id, file.file, file.filename, room_id)


@router.get(
    "/files/{attachment_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "채팅 문서 파일"}},
)
def get_file(
    attachment_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> FileResponse:
    """방에 들어갈 수 있는 사람만 받을 수 있다. 없는 파일·못 들어가는 방은 모두 404. 항상 내려받기(attachment)로만 내려간다."""
    path, attachment = file_service.file_for_viewer(db, user, group_id, attachment_id)
    return FileResponse(  # 스트리밍이라 20MB 를 통째로 메모리에 올리지 않는다
        path,
        media_type=file_service.media_type(attachment),
        headers=file_service.download_headers(attachment),
    )
