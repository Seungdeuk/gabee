import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_chat import assistant as family_assistant
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import bad_request
from app.shared.llm.agent_chat import to_out as to_proposal_out

from . import repository as repo
from .knowledge import rag_chat
from .models import Photo
from .schemas import ChatOut, ChatSource, ConfirmCardOut, WebSource

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
    room_id: str | None = None,
) -> ChatOut:
    """가족 그룹이 있으면 저장된 기록(knowledge)을 검색해서 근거로 답한다.

    외부 AI 는 가족 그룹이 AI 동의를 켠 경우에만, 쿨다운·하루 한도(ai_guard) 아래에서 부른다.
    그룹이 없으면 동의를 받을 가족이 없으니 외부 AI 를 부르지 않고 안내만 돌려준다.
    group_id 는 호출한 쪽(라우터)이 실제 구성원인지 확인한 값이어야 한다.
    `user` 가 있으면 정산·돌봄 탭 에이전트에게 물어 답할 수 있고, 에이전트가 제안한 쓰기는 `proposals` 로 돌려준다.

    TODO: 일정·지출·돌봄 기록도 검색 대상에 넣는다(원본의 capture/qa 참고)."""
    if not group_id:
        return ChatOut(reply=NO_GROUP_REPLY, source="fallback")
    # 1:1 방에서 부른 @가비: 참가자·상대 이탈을 AI 를 부르기 전에 확인한다(막히면 AI 호출·한도 없음)
    direct = (
        family_assistant.direct_room(db, user, group_id, room_id)
        if audience == "room" and room_id and user is not None
        else None
    )
    # 방에서 부른 @가비 에는 그 방의 최근 대화를 개인정보를 가린 채 맥락으로 붙인다("일정 잡아줘"가 무엇을 가리키는지 알도록).
    # 가명화는 동의·쿨다운·한도 확인을 통과한 뒤 관문 안에서 한다(막힐 요청은 대화를 가명화하지 않는다)
    factory = (
        (lambda: family_assistant.room_context(db, group_id, direct, user_id))
        if audience == "room"
        else None
    )
    r = rag_chat.ask_guarded(
        db,
        user_id,
        group_id,
        message,
        feature="assistant_chat",
        history=history,
        user=user,
        # 1:1 방이면 탭 에이전트에게 "direct" 로 알린다(일정 에이전트는 아직 1:1 을 다루지 않는다)
        audience="direct" if direct else audience,
        context_factory=factory,
        web=audience == "me",  # 방 대화가 검색어로 나가지 않게 AI 채팅 탭에서만 켠다
    )
    sources = [
        ChatSource(n=s["n"], title=s["title"], item_id=s["item_id"], source_path=s["source_path"])
        for s in r.sources
    ]
    out = ChatOut(
        reply=r.answer,
        source=r.source,
        sources=sources,
        web_sources=[WebSource(**s) for s in r.web_sources],
        proposals=to_proposal_out(r.proposals),
        confirm_cards=[ConfirmCardOut(**c) for c in r.confirmations],
    )
    if audience == "room":
        # 가족 채팅방에서 @가비 로 부른 AI 답은 가족 전체방에 공유하고 기록으로 남긴다. 서버가 직접 가비 이름으로 저장한다
        # (앱이 아무 글이나 가비 이름으로 올리는 입구는 없다). 아래 두 경우는 방에 올리지 않고 질문한 사람에게만 돌려준다.
        # 이전 앱이 visibility 만 보고 카드·안내를 버리지 않도록 이때는 visibility 를 private 으로 둔다.
        if out.confirm_cards or out.proposals:
            # 확인 버튼이 딸린 답은 버튼이 없는 다른 구성원에게 열린 질문으로 남고, 부탁 줄에는 받는 분·수락 현황이 들어 있다
            out.visibility, out.private_reasons = "private", ["확인 버튼이 필요한 제안"]
        elif r.source != "ai":
            # AI 를 못 써서 나온 기본 안내: 키가 없으면 동의·쿨다운·한도 검사(ai_guard)를 거치지 않아 마구 올라갈 수 있다
            out.visibility, out.private_reasons = (
                "private",
                ["AI 가 답하지 못해 기록 검색 결과만 있어요"],
            )
        else:
            out.visibility = "room"
            if out.reply.strip():
                out.posted_message_id = family_assistant.post_as_assistant(
                    db, group_id, out.reply, direct
                ).id
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
