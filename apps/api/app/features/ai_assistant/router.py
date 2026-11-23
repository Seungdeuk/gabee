from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user, ensure_group_member
from app.shared.db import get_db
from app.shared.errors import bad_request, not_found
from app.shared.llm import agent_chat
from app.shared.llm.schemas import AgentConfirmOut

from . import files, library, memories, reminders, repository, service, sharing
from .knowledge import news_source  # noqa: F401  (import 하면 주간 뉴스의 문서함 재료 읽기가 등록된다)
from .knowledge.router import router as knowledge_router
from .models import Photo
from .schemas import (
    ChatIn,
    ChatOut,
    DescriptionIn,
    FileOut,
    FileStatusOut,
    MemoriesOut,
    MemoryDeletedOut,
    MemoryIn,
    MemoryOut,
    NudgeOut,
    NudgesOut,
    PhotoOut,
    ReminderSettingsIn,
    ReminderSettingsOut,
    ShareConfirmIn,
)

router = APIRouter(prefix="/ai-assistant", tags=["ai-assistant"])
router.include_router(knowledge_router)  # /ai-assistant/knowledge/*
library.register()  # 가족 채팅 문서를 문서함에 자동 등록하는 처리 함수를 채팅 쪽 통로(shared/chat_library)에 등록한다  # /ai-assistant/knowledge/*


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, user=Depends(current_user), db: Session = Depends(get_db)) -> ChatOut:
    history = [t.model_dump() for t in body.history]
    group_id = user.active_group_id
    if group_id:  # 캐시값만 믿지 않고 실제 구성원인지 확인한다(아니면 403 not_member)
        ensure_group_member(db, user.id, group_id)
    return service.chat(
        db,
        group_id,
        user.id,
        body.message,
        history,
        user=user,
        audience=body.audience,
        room_id=body.room_id,
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


@router.post("/reminders/nudges", response_model=NudgesOut)
def reminder_nudges(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> NudgesOut:
    """앱을 열 때 가비가 먼저 할 말. 한 번 돌려준 말은 다시 돌려주지 않는다(스위치가 꺼져 있으면 빈 목록)."""
    found = reminders.due_nudges(db, group_id, user.id)
    return NudgesOut(
        nudges=[NudgeOut(**{k: n[k] for k in ("id", "kind", "text")}) for n in found],
        message=reminders.compose(found),
    )


@router.post("/agent/confirm", response_model=AgentConfirmOut)
def confirm_share(
    body: ShareConfirmIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AgentConfirmOut:
    """사용자가 확인 카드를 눌렀을 때 대화 내용을 소통 채팅으로 보낸다. 토큰은 이 사용자·이 가족만, 한 번만 쓸 수 있다."""
    return agent_chat.confirm(db, group_id, user, body, sharing.TAB, sharing.execute)


@router.get("/memories", response_model=MemoriesOut)
def list_memories(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoriesOut:
    """가비의 기억: 내가 기억해 달라고 한 것 목록(본인 것만)."""
    rows = memories.list_for(db, group_id, user.id)
    return MemoriesOut(items=[MemoryOut.model_validate(r) for r in rows])


@router.delete("/memories", response_model=MemoryDeletedOut)
def forget_all_memories(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryDeletedOut:
    return MemoryDeletedOut(deleted=memories.forget_all(db, group_id, user.id))


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    body: MemoryIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryOut:
    """내 기억의 내용을 고친다."""
    try:
        row = memories.update(db, group_id, user.id, memory_id, body.text)
    except ValueError as e:
        raise bad_request("invalid_memory", str(e)) from None
    return MemoryOut.model_validate(row)


@router.delete("/memories/{memory_id}", response_model=MemoryDeletedOut)
def forget_memory(
    memory_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryDeletedOut:
    memories.forget(db, group_id, user.id, memory_id)
    return MemoryDeletedOut(deleted=1)


@router.get("/reminders/settings", response_model=ReminderSettingsOut)
def reminder_settings(
    user=Depends(current_user), db: Session = Depends(get_db)
) -> ReminderSettingsOut:
    return ReminderSettingsOut(enabled=reminders.is_enabled(db, user.id))


@router.put("/reminders/settings", response_model=ReminderSettingsOut)
def set_reminder_settings(
    body: ReminderSettingsIn, user=Depends(current_user), db: Session = Depends(get_db)
) -> ReminderSettingsOut:
    """먼저 챙겨주기를 켜거나 끈다(내 스위치)."""
    return ReminderSettingsOut(enabled=reminders.set_enabled(db, user.id, body.enabled))


@router.post("/files", response_model=FileOut, status_code=201)
async def upload_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Photo:
    """사진·PDF·PPT·엑셀·워드 등 어떤 파일이든 받는다. 바로 `received` 로 응답하고 읽기·분류·저장은 뒤에서 한다.
    **메인 AI 의 직접 업로드**라서 기존 정책 그대로 Claude 가 읽고·가리고·분류한다(가족 AI 동의 검사를 하지 않는다, 사용자 결정 2026-11-23). 처리 목적은 서버가
    `Purpose.MAIN_AI_DIRECT_UPLOAD` 로 정하며 요청 값으로 바꿀 수 없다. 가족 채팅방의 문서 자동 등록은 이 경로가 아니라 `library.py`(동의가 있을 때만 외부 전송)를 쓴다."""
    data = await file.read(
        service.MAX_BYTES + 1
    )  # 25MB 를 넘는 파일을 통째로 메모리에 올리지 않는다
    photo = service.receive_file(
        db, group_id, user.id, file.filename or "file", file.content_type or "", data
    )
    background.add_task(
        files.process_file,
        photo.id,
        group_id,
        user.id,
        data,
        photo.filename,
        purpose=files.Purpose.MAIN_AI_DIRECT_UPLOAD,
    )
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
