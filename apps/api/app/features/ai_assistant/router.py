from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user, ensure_group_member
from app.shared.db import get_db
from app.shared.errors import not_found

from . import files, repository, service
from .knowledge.router import router as knowledge_router
from .models import Photo
from .schemas import ChatIn, ChatOut, DescriptionIn, FileOut, FileStatusOut, PhotoOut

router = APIRouter(prefix="/ai-assistant", tags=["ai-assistant"])
router.include_router(knowledge_router)  # /ai-assistant/knowledge/*


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, user=Depends(current_user), db: Session = Depends(get_db)) -> ChatOut:
    history = [t.model_dump() for t in body.history]
    group_id = user.active_group_id
    if group_id:  # 캐시값만 믿지 않고 실제 구성원인지 확인한다(아니면 403 not_member)
        ensure_group_member(db, user.id, group_id)
    return service.chat(
        db, group_id, user.id, body.message, history, user=user, audience=body.audience
    )


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


@router.post("/files", response_model=FileOut, status_code=201)
async def upload_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Photo:
    """사진·PDF·PPT·엑셀·워드 등 어떤 파일이든 받는다. 바로 `received` 로 응답하고 읽기·분류·저장은 뒤에서 한다."""
    data = await file.read(
        service.MAX_BYTES + 1
    )  # 25MB 를 넘는 파일을 통째로 메모리에 올리지 않는다
    photo = service.receive_file(
        db, group_id, user.id, file.filename or "file", file.content_type or "", data
    )
    background.add_task(files.process_file, photo.id, group_id, user.id, data, photo.filename)
    return photo


@router.get("/files/{file_id}", response_model=FileStatusOut)
def file_status(
    file_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> FileStatusOut:
    out = files.status(db, group_id, file_id)
    if out is None:
        raise not_found("파일")
    return out


@router.post("/files/{file_id}/description", response_model=FileStatusOut)
def file_description(
    file_id: str,
    body: DescriptionIn,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> FileStatusOut:
    """글자가 안 읽힌 사진에 한 줄 설명을 달거나 고친다. 다른 가족의 파일이면 404, 사진이 아니면 409."""
    out = files.set_description(db, group_id, file_id, body.text)
    if out is None:
        raise not_found("파일")
    return out


@router.get("/files/{file_id}/original")
def file_original(
    file_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """올린 원본 파일 그대로. 요청자의 가족 그룹이 맞을 때만 준다(다른 가족이면 없는 파일처럼 404)."""
    found = files.original(db, group_id, file_id)
    if found is None:
        raise not_found("원본 파일")
    data, filename, content_type = found
    # 이미지·PDF 말고는 브라우저가 열지 않고 내려받게 한다(올린 HTML 이 실행되지 않게)
    shown = (
        "inline"
        if content_type.startswith("image/") or content_type == "application/pdf"
        else "attachment"
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"{shown}; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/files/{file_id}/original/pages")
def file_original_pages(
    file_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> dict:
    """원본이 PDF 일 때 앱에서 쪽별로 보여 줄 쪽 수. PDF 가 아니거나 다른 가족의 파일이면 404."""
    count = files.original_pdf_pages(db, group_id, file_id)
    if count is None:
        raise not_found("원본 PDF")
    return {"count": count}


@router.get("/files/{file_id}/original/pages/{page}")
def file_original_page(
    file_id: str,
    page: int,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """원본 PDF 의 한 쪽(1부터)을 그림으로 돌려준다. 앱이 PDF 를 열 수 없어서 서버가 대신 그린다."""
    image = files.original_pdf_page(db, group_id, file_id, page)
    if image is None:
        raise not_found("원본 PDF 쪽")
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
