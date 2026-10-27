import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_chat import assistant as family_assistant
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import bad_request
from app.shared.llm.agent_chat import to_out as to_proposal_out

from . import repository as repo
from . import room_visibility
from .knowledge import rag_chat
from .models import Photo
from .schemas import ChatOut, ChatSource, ConfirmCardOut

NO_GROUP_REPLY = (
    "가족 그룹에 먼저 참여하면 가비가 가족의 기록을 바탕으로 도와드릴 수 있어요. "
    "더보기(⋮)의 가족 그룹에서 그룹을 만들거나 초대 코드로 참여해 주세요."
)
ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 25 * 1024 * 1024


def chat(
    db: Session,
    group_id: str | None,
    user_id: str,
    message: str,
    history: list[dict] | None = None,
    user: User | None = None,
    audience: str = "me",
) -> ChatOut:
    """가족 그룹이 있으면 저장된 기록(knowledge)을 검색해서 근거로 답한다.

    외부 AI 는 가족 그룹이 AI 동의를 켠 경우에만, 쿨다운·하루 한도(ai_guard) 아래에서 부른다.
    그룹이 없으면 동의를 받을 가족이 없으니 외부 AI 를 부르지 않고 안내만 돌려준다.
    group_id 는 호출한 쪽(라우터)이 실제 구성원인지 확인한 값이어야 한다.
    `user` 가 있으면 정산·돌봄 탭 에이전트에게 물어 답할 수 있고, 에이전트가 제안한 쓰기는 `proposals` 로 돌려준다.

    TODO: 일정·지출·돌봄 기록도 검색 대상에 넣는다(원본의 capture/qa 참고)."""
    if not group_id:
        return ChatOut(reply=NO_GROUP_REPLY, source="fallback")
    r = rag_chat.ask_guarded(
        db, user_id, group_id, message, feature="assistant_chat", history=history, user=user
    )
    sources = [
        ChatSource(n=s["n"], title=s["title"], item_id=s["item_id"], source_path=s["source_path"])
        for s in r.sources
    ]
    out = ChatOut(
        reply=r.answer,
        source=r.source,
        sources=sources,
        proposals=to_proposal_out(r.proposals),
        confirm_cards=[ConfirmCardOut(**c) for c in r.confirmations],
    )
    if audience == "room":
        judged = room_visibility.judge(
            r.tool_calls, r.used_sensitive, bool(r.proposals) or bool(r.confirmations)
        )
        if (
            r.source != "ai"
        ):  # AI 가 아닌 기본 안내·검색 결과는 어떤 기록이 섞였는지 알 수 없어 방에 올리지 않는다
            judged.add("AI 가 답하지 못해 기록 검색 결과만 있어요")
        if any(turn.get("private") for turn in history or []):
            # 앞서 질문한 사람에게만 보였던 개인용 답이 맥락에 있으면, 도구를 안 쓴 짧은 후속 답에도 그 내용이 섞일 수 있다
            judged.add("앞서 개인 정보가 있는 답이 있었어요")
        out.visibility, out.private_reasons = judged.visibility, judged.reasons
        if out.visibility == room_visibility.ROOM and out.reply.strip():
            # 방에 올려도 되는 답은 서버가 직접 가비 이름으로 저장한다(앱이 아무 글이나 가비 이름으로 올리는 입구는 없다)
            out.posted_message_id = family_assistant.post_as_assistant(db, group_id, out.reply).id
    return out


def save_photo(
    db: Session, group_id: str, user_id: str, filename: str, content_type: str, data: bytes
) -> Photo:
    if content_type not in ALLOWED_TYPES:
        raise bad_request("unsupported_type", "JPEG 또는 PNG 사진만 올릴 수 있어요")
    if not data:
        raise bad_request("empty_file", "사진 데이터가 비어 있어요")
    if len(data) > MAX_BYTES:
        raise bad_request("too_large", "사진이 너무 커요(25MB 이하)")
    photo_id = uuid.uuid4().hex[:12]
    folder = Path(settings.data_dir) / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{photo_id}{'.png' if content_type == 'image/png' else '.jpg'}").write_bytes(data)
    return repo.add(
        db,
        Photo(
            id=photo_id,
            group_id=group_id,
            uploaded_by=user_id,
            filename=Path(filename or "photo").name[:200],
            content_type=content_type,
            size=len(data),
        ),
    )


def receive_file(
    db: Session, group_id: str, user_id: str, filename: str, content_type: str, data: bytes
) -> Photo:
    """어떤 종류의 파일이든 받아서 기록(`received`)만 남긴다. 읽고 분류하는 일은 `files.process_file` 이 뒤에서 한다."""
    if not data:
        raise bad_request("empty_file", "파일이 비어 있어요")
    if len(data) > MAX_BYTES:
        raise bad_request("too_large", "파일이 너무 커요(25MB 이하)")
    return repo.add(
        db,
        Photo(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            uploaded_by=user_id,
            filename=Path(filename or "file").name[:200],
            content_type=(content_type or "application/octet-stream")[:60],
            size=len(data),
        ),
    )
