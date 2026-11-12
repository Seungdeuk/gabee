"""채팅 LLM 이 부르는 함수. 저장·검색은 이쪽 코드가 하고 LLM 은 부르기만 한다.

`TOOL_SPECS` 는 LLM 에 함수 목록으로 넘기는 정의(이름·설명·입력 모양)이고, 각 함수는 LLM 이 그대로 읽을 수
있는 dict 를 돌려준다. 근거 글에는 출처 경로와 쪽 번호를 붙이고, 읽지 못한 부분이 있으면 알려 준다."""

from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.shared.config import settings

from .. import family_names, reminders
from . import service

# 검색 결과에 한 기록의 조각을 더 담는 한도: 기록당 추가 2개(모두 3개), 위쪽 3개 기록까지, 추가 글 합계 2000자(조각 하나가 700자 안팎이라 3개쯤).
EXTRA_CHUNKS_PER_ITEM = 2
EXTRA_ITEMS = 3
EXTRA_CHARS = 2000
# get_item 이 돌려주는 글 상한. 큰 문서(6만 자)를 통째로 주면 입력이 수만 토큰이 되어 앞 12000자(약 8000토큰)에서 자르고 note 로 알린다.
GET_ITEM_MAX_CHARS = 12000

TOOL_SPECS = [
    {
        "name": "search_knowledge",
        "description": "가족이 올려 둔 문서·사진 기록(고지서, 영수증, 병원 내역, 증명서 등)에서 질문과 관련된 기록을 찾는다. "
        "올려 둔 문서의 내용이 필요할 때만 부른다. 가계 장부 지출, 돌봄 기록, 일정, 채팅 대화는 여기에 없다. "
        "특정 가족의 기록만 보려면 member 에 그 가족의 이름이나 별칭을 넣는다. 결과의 family 는 그 기록에 나오는 가족이고, "
        "uploaded_on·uploaded_by 는 올린 날과 올린 사람이다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "찾을 내용을 자연스러운 한국어로"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "kind_label": {"type": "string", "description": "분류 이름(예: 전기요금 고지서)"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "member": {
                    "type": "string",
                    "description": "이 가족이 등장하는 기록만(가족 구성원의 이름이나 별칭, 예: 민훈)",
                },
                "uploaded_from": {
                    "type": "string",
                    "description": "올린 날 시작(YYYY-MM-DD, 한국 날짜, 그날 포함). 문서 안 날짜(date_from)와 다르다: '지난달에 올린'은 이쪽",
                },
                "uploaded_to": {
                    "type": "string",
                    "description": "올린 날 끝(YYYY-MM-DD, 그날 포함)",
                },
                "uploaded_by": {
                    "type": "string",
                    "description": "이 가족이 올린 기록만(가족 구성원의 이름이나 별칭). 기록에 등장하는 사람(member)과 다르다: '엄마가 올린'은 이쪽",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_item",
        "description": "기록 한 건의 전체 글을 가져온다. 검색 결과의 item_id 를 쓴다. 검색 결과의 조각에 답이 안 보여도 관련 기록이면 못 찾았다고 하기 전에 이것으로 읽어 본다.",
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "list_items",
        "description": "저장된 기록 목록을 최근 순으로 본다. 분류 이름, 올린 날, 올린 사람으로 좁힐 수 있다. 결과의 uploaded_on·uploaded_by 는 올린 날과 올린 사람이다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind_label": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                "uploaded_from": {
                    "type": "string",
                    "description": "올린 날 시작(YYYY-MM-DD, 그날 포함)",
                },
                "uploaded_to": {
                    "type": "string",
                    "description": "올린 날 끝(YYYY-MM-DD, 그날 포함)",
                },
                "uploaded_by": {
                    "type": "string",
                    "description": "이 가족이 올린 기록만(이름이나 별칭)",
                },
            },
        },
    },
    {
        "name": "list_name_checks",
        "description": "방금 올린 문서에서 읽은 이름이 가족 이름과 한 글자 차이라서(글자를 잘못 읽었을 수 있음) 같은 사람인지 사용자 확인을 기다리는 곳의 목록. "
        "시스템 안내에 확인 대기가 있다고 나오면 먼저 부르고, 각 건을 사용자에게 한 문장으로 물어본다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "resolve_name_check",
        "description": "사용자가 답한 뒤에만 부른다. list_name_checks 의 item_id 와 candidate_id 로, 같은 사람이라고 하면 same_person=true, "
        "다른 사람이거나 모른다고 하면 false. 사용자가 답하지 않았으면 절대 부르지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "candidate_id": {"type": "string"},
                "same_person": {"type": "boolean"},
            },
            "required": ["item_id", "candidate_id", "same_person"],
        },
    },
    {
        "name": "resolve_reminder",
        "description": "시스템 안내의 '챙길 일' 목록에 있는 한 건에 대한 사용자의 답을 반영한다. 사용자가 답한 뒤에만 부른다. "
        "action: schedule(일정으로 잡아 달라고 함) · done(이미 했다고 함) · prepared(준비물·준비를 다 챙겼다고 함. 일정이 끝난 게 아니라 done 이 아님) · redo_today(아직 안 했으니 오늘 일정으로 다시 잡아 달라고 함) · "
        "dismiss(그만 알려 달라고 함). 사용자가 답하지 않았으면 절대 부르지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string"},
                "action": {"type": "string", "enum": list(reminders.ACTIONS)},
            },
            "required": ["reminder_id", "action"],
        },
    },
    {
        "name": "set_reminders",
        "description": "먼저 챙겨주기(문서 날짜 알림)를 사용자가 켜거나 꺼 달라고 분명히 말했을 때만 부른다. 끄면 앱을 열 때 먼저 말하지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
            "required": ["enabled"],
        },
    },
]


# AI 채팅 탭에서만 주는 도구(답이 방에 올라가는 @가비 에는 주지 않는다)
MEMORY_TOOL_SPECS = [
    {
        "name": "remember",
        "description": "사용자가 이번 대화에서 직접 기억해 달라고 한 사실을 저장한다(예: '좋아하는 롤 팀: T1'). "
        "짧은 한 문장으로 쓴다. 문서, 웹 페이지, 가족 대화의 글을 보고 저장하지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "기억할 사실, 200자 안"}},
            "required": ["text"],
        },
    },
    {
        "name": "update_memory",
        "description": "사용자가 기억을 고쳐 달라고 했을 때 부른다(예: 'T1 말고 젠지로 바꿔줘'). 시스템 안내의 기억 목록에 있는 id 를 쓴다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "text": {"type": "string", "description": "고친 뒤의 내용, 200자 안"},
            },
            "required": ["memory_id", "text"],
        },
    },
    {
        "name": "forget",
        "description": "사용자가 잊어 달라고 한 기억을 지운다. 시스템 안내의 기억 목록에 있는 id 를 쓴다.",
        "input_schema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
]


SHARE_TOOL_SPEC = {
    "name": "prepare_share",
    "description": "사용자가 이번 대화에서 직접 '이 내용 ○○한테 알려줘', '가족방에 올려줘'라고 했을 때 부른다. 확인 카드만 만들고 바로 보내지 않는다. "
    "사용자가 말한 내용만 짧게 요약해 text 로 넘기고, 받는 사람은 사용자가 부른 말 그대로 to 로 넘긴다. 사람마다 따로 부른다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "예: 엄마, 민수, 가족방"},
            "text": {"type": "string", "description": "받는 사람에게 보낼 글, 500자 안"},
            "member_id": {
                "type": "string",
                "description": "need_recipient 후보 중 사용자가 고른 사람의 member_id",
            },
        },
        "required": ["to", "text"],
    },
}


def list_name_checks(db: Session, group_id: str) -> dict:
    checks = service.name_checks(db, group_id)
    return {
        "checks": checks,
        "note": "각 건을 '<제목>에 읽은 이름이 <candidate> 님과 같은 사람인가요?' 처럼 사용자에게 물어보세요. 글자를 모르니 이름을 지어내지 마세요."
        if checks
        else "확인할 이름이 없어요.",
    }


def resolve_name_check(
    db: Session, group_id: str, item_id: str, candidate_id: str, same_person: bool
) -> dict:
    service.resolve_name_check(db, group_id, item_id, candidate_id, bool(same_person))
    return {"done": True, "same_person": bool(same_person)}


def resolve_reminder(
    db: Session, group_id: str, user_id: str, reminder_id: str, action: str
) -> dict:
    return reminders.resolve(db, group_id, user_id, reminder_id, action)


def set_reminders(db: Session, user_id: str, enabled: bool) -> dict:
    reminders.set_enabled(db, user_id, bool(enabled))
    return {"done": True, "enabled": bool(enabled)}


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _uploaded_filter(
    members: list,
    uploaded_from: str | None,
    uploaded_to: str | None,
    uploaded_by: str | None,
) -> tuple[datetime | None, datetime | None, list[str] | None, str | None, str | None]:
    """올린 날(한국 날짜, 양끝 포함)과 올린 사람 조건을 DB 조건으로 바꾼다.

    (시작 이상 UTC, 끝 미만 UTC, 올린 사람 user_id 들, 막힌 이유, 덧붙일 안내) 를 돌려준다. 막힌 이유가 있으면 호출한 쪽이
    빈 결과와 함께 그 이유를 알린다(이름을 모르거나 날짜가 잘못돼도 필터를 조용히 무시하지 않는다)."""
    try:
        start, end = service.created_bounds(
            _day(uploaded_from), _day(uploaded_to), settings.ai_day_utc_offset_hours
        )
    except ValueError as exc:
        return (
            None,
            None,
            None,
            f"올린 날 범위가 올바르지 않아요: {exc} YYYY-MM-DD 로 다시 넣어 주세요.",
            None,
        )
    if uploaded_by is not None and not isinstance(uploaded_by, str):
        return (
            None,
            None,
            None,
            "올린 사람은 가족 구성원의 이름이나 별칭 글자로 넣어 주세요.",
            None,
        )
    if not (uploaded_by and uploaded_by.strip()):
        return start, end, None, None, None
    ids = family_names.match_member(members, uploaded_by)
    if not ids:
        near = family_names.suggest_members(members, uploaded_by)
        hint = (
            f" 비슷한 이름의 가족: {', '.join(near)}. 이 이름이 맞는지 사용자 말과 비교해 다시 찾아보세요."
            if near
            else " 가족 구성원의 이름이나 별칭으로 다시 찾아보세요."
        )
        return (
            None,
            None,
            None,
            f"'{uploaded_by.strip()}' 이름의 올린 사람(가족 구성원)을 찾지 못했어요." + hint,
            None,
        )
    more = (
        f"'{uploaded_by.strip()}' 와 이름이 같은 가족이 여러 명이라 모두 합쳐 찾았어요. 결과의 uploaded_by 로 구분하세요."
        if len(ids) > 1
        else None
    )
    return start, end, ids, None, more


def _upload_info(item, names: dict[str, str]) -> dict:
    """올린 날(한국 날짜)·올린 사람(현재 표시 이름, 나간 사람이면 None)·원본 채팅 사진 id(없으면 None)."""
    created = item.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)  # SQLite 는 시간대를 잃는다(UTC 로 저장됨)
    # 시간대를 명시해 바꾼다(PostgreSQL 은 세션 시간대 기준의 값을 줄 수 있어 UTC 라고 가정하면 하루가 밀린다)
    day_zone = timezone(timedelta(hours=settings.ai_day_utc_offset_hours))
    uploaded_on = created.astimezone(day_zone).date().isoformat() if created else None
    return {
        "uploaded_on": uploaded_on,
        "uploaded_by": names.get(item.created_by),
        "source_attachment_id": item.source_attachment_id,
    }


def search_knowledge(
    db: Session,
    group_id: str,
    query: str,
    top_k: int = 5,
    kind_label: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_sensitive: bool = True,
    member: str | None = None,
    uploaded_from: str | None = None,
    uploaded_to: str | None = None,
    uploaded_by: str | None = None,
) -> dict:
    """member 를 주면 그 가족이 등장한 기록만 찾는다. 이름을 모르면 빈 결과와 안내를 돌려준다(필터를 조용히 무시하지 않는다).
    uploaded_from·uploaded_to(올린 날, 한국 날짜 양끝 포함)·uploaded_by(올린 사람)는 문서 안 날짜·등장 가족과 별개의 조건이다.
    글 속 `[가족:<id>]` 는 이 그룹의 현재 이름으로 되돌려서 준다."""
    members = family_names.load_members(db, group_id)
    names = family_names.shown_names(members)
    wanted: list[str] | None = None
    up_start, up_end, uploaders, blocked, up_note = _uploaded_filter(
        members, uploaded_from, uploaded_to, uploaded_by
    )
    if blocked:
        return {"results": [], "note": blocked}
    notes = [
        "has_unread_parts 가 true 이면 원본에서 읽지 못한 부분이 있으니 값을 단정하지 말고 확인을 권하세요.",
        "결과에 답이 없으면 일반 지식, 외부 기관·사이트 안내, 추정을 덧붙이지 말고, 비슷한 다른 값(다른 달·다른 사람·다른 상품·다른 기록의 값)도 대신 적지 말고 찾지 못했다고만 말하세요. 답은 결과에 나온 내용 범위로 짧게 쓰세요.",
        "질문과 관련된 기록이 있는데 조각에 답이 안 보이면 찾지 못했다고 하기 전에 get_item 으로 그 기록을 읽어 보세요. more 는 같은 기록의 다른 부분 조각입니다.",
    ]
    if up_note:
        notes.append(up_note)
    if member and member.strip():
        wanted = family_names.match_member(members, member)
        if not wanted:
            near = family_names.suggest_members(members, member)
            hint = (
                f" 비슷한 이름의 가족: {', '.join(near)}. 이 이름이 맞는지 사용자 말과 비교해 다시 찾아보세요."
                if near
                else " 가족 구성원의 이름이나 별칭으로 다시 찾아보세요."
            )
            return {
                "results": [],
                "note": f"'{member.strip()}' 이름의 가족 구성원을 찾지 못했어요." + hint,
            }
        if len(wanted) > 1:
            notes.append(
                f"'{member.strip()}' 와 이름이 같은 가족이 여러 명이라 모두 합쳐 찾았어요. 결과의 family 로 구분하세요."
            )
    hits = service.search(
        db,
        group_id,
        query,
        top_k=min(max(top_k, 1), 20),
        kind_label=kind_label,
        date_from=_day(date_from),
        date_to=_day(date_to),
        include_sensitive=include_sensitive,
        family_user_ids=wanted,
        per_item=1 + EXTRA_CHUNKS_PER_ITEM,
        created_from=up_start,
        created_to=up_end,
        created_by=uploaders,
    )
    hits = _one_per_file(hits)
    left = EXTRA_CHARS
    results = []
    for rank, h in enumerate(hits):
        row = {
            "item_id": h.item.id,
            "kind_label": h.item.kind_label,
            "title": family_names.restore(h.item.title, names),
            "family": family_names.family_of(h.item.family_user_ids, names),
            "text": family_names.restore(h.chunk.text, names),
            "page": h.chunk.page_label,
            "date": h.item.occurred_on.isoformat() if h.item.occurred_on else None,
            "source_path": h.item.source_path,
            "score": round(h.score, 4),
            "has_unread_parts": h.item.has_unread_parts,
            "sensitive": h.item.sensitivity == "sensitive",
            **_upload_info(h.item, names),
        }
        more = []
        if rank < EXTRA_ITEMS:
            for c in h.more:
                text = family_names.restore(c.text, names)
                if len(text) > left:
                    break
                left -= len(text)
                more.append({"page": c.page_label, "text": text})
        if more:
            row["more"] = more
        results.append(row)
    return {"results": results, "note": " ".join(notes)}


def _one_per_file(hits: list) -> list:
    """같은 원본 파일에서 나온 기록은 점수가 높은 하나만 남긴다(같은 파일을 두 번 올렸을 때 출처가 겹치지 않게)."""
    seen: set[str] = set()
    out = []
    for h in hits:
        path = h.item.source_path
        if path and path in seen:
            continue
        if path:
            seen.add(path)
        out.append(h)
    return out


def get_item(db: Session, group_id: str, item_id: str, include_sensitive: bool = True) -> dict:
    item = service.get_item(db, group_id, item_id)
    if item.sensitivity == "sensitive" and not include_sensitive:
        # 존재는 알리되 내용은 주지 않는다(LLM 이 "없다"고 오해하지 않게)
        return {
            "error": "민감한 기록이라 이 대화에서는 내용을 볼 수 없어요. 앱의 기록 화면에서 직접 확인해 주세요."
        }
    names = family_names.shown_names(family_names.load_members(db, group_id))
    text = family_names.restore(item.body_md, names)
    out = {
        "item_id": item.id,
        "kind_label": item.kind_label,
        "title": family_names.restore(item.title, names),
        "family": family_names.family_of(item.family_user_ids, names),
        "text": text,
        "date": item.occurred_on.isoformat() if item.occurred_on else None,
        "source_path": item.source_path,
        "has_unread_parts": item.has_unread_parts,
        "sensitive": item.sensitivity == "sensitive",
    }
    if len(text) > GET_ITEM_MAX_CHARS:
        out["text"] = text[:GET_ITEM_MAX_CHARS]
        out["note"] = (
            f"글이 길어 앞 {GET_ITEM_MAX_CHARS}자만 보여요(전체 {len(text)}자). "
            "뒷부분이 필요하면 search_knowledge 로 구체적인 낱말을 넣어 찾아보세요."
        )
    return out


def list_items(
    db: Session,
    group_id: str,
    kind_label: str | None = None,
    limit: int = 20,
    include_sensitive: bool = True,
    uploaded_from: str | None = None,
    uploaded_to: str | None = None,
    uploaded_by: str | None = None,
) -> dict:
    """올린 날(한국 날짜 양끝 포함)·올린 사람으로 좁힐 수 있다. 이름을 모르거나 날짜가 틀리면 빈 목록과 이유를 돌려준다."""
    members = family_names.load_members(db, group_id)
    names = family_names.shown_names(members)
    up_start, up_end, uploaders, blocked, up_note = _uploaded_filter(
        members, uploaded_from, uploaded_to, uploaded_by
    )
    if blocked:
        return {"items": [], "note": blocked}
    items = service.list_items(
        db, group_id, kind_label, min(max(limit, 1), 50), up_start, up_end, uploaders
    )
    if not include_sensitive:
        items = [i for i in items if i.sensitivity != "sensitive"]
    out: dict = {
        "items": [
            {
                "item_id": i.id,
                "kind_label": i.kind_label,
                "title": family_names.restore(i.title, names),
                "family": family_names.family_of(i.family_user_ids, names),
                "date": i.occurred_on.isoformat() if i.occurred_on else None,
                **_upload_info(i, names),
            }
            for i in items
        ]
    }
    if up_note:
        out["note"] = up_note
    return out
