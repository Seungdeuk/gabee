"""채팅 LLM 이 부르는 함수. 저장·검색은 이쪽 코드가 하고 LLM 은 부르기만 한다.

`TOOL_SPECS` 는 LLM 에 함수 목록으로 넘기는 정의(이름·설명·입력 모양)이고, 각 함수는 LLM 이 그대로 읽을 수
있는 dict 를 돌려준다. 근거 글에는 출처 경로와 쪽 번호를 붙이고, 읽지 못한 부분이 있으면 알려 준다."""

from datetime import date

from sqlalchemy.orm import Session

from . import service

TOOL_SPECS = [
    {
        "name": "search_knowledge",
        "description": "가족이 저장한 기록(고지서, 영수증, 병원 내역, 증명서 등)에서 질문과 관련된 기록을 찾는다. "
        "답에 쓸 근거가 필요할 때 먼저 부른다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "찾을 내용을 자연스러운 한국어로"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "kind_label": {"type": "string", "description": "분류 이름(예: 전기요금 고지서)"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_item",
        "description": "기록 한 건의 전체 글을 가져온다. 검색 결과의 item_id 를 쓴다.",
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "list_items",
        "description": "저장된 기록 목록을 최근 순으로 본다. 분류 이름으로 좁힐 수 있다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind_label": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
        },
    },
]


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def search_knowledge(
    db: Session,
    group_id: str,
    query: str,
    top_k: int = 5,
    kind_label: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_sensitive: bool = True,
) -> dict:
    hits = service.search(
        db,
        group_id,
        query,
        top_k=min(max(top_k, 1), 20),
        kind_label=kind_label,
        date_from=_day(date_from),
        date_to=_day(date_to),
        include_sensitive=include_sensitive,
    )
    return {
        "results": [
            {
                "item_id": h.item.id,
                "kind_label": h.item.kind_label,
                "title": h.item.title,
                "text": h.chunk.text,
                "page": h.chunk.page_label,
                "date": h.item.occurred_on.isoformat() if h.item.occurred_on else None,
                "source_path": h.item.source_path,
                "score": round(h.score, 4),
                "has_unread_parts": h.item.has_unread_parts,
                "sensitive": h.item.sensitivity == "sensitive",
            }
            for h in hits
        ],
        "note": "has_unread_parts 가 true 이면 원본에서 읽지 못한 부분이 있으니 값을 단정하지 말고 확인을 권하세요.",
    }


def get_item(db: Session, group_id: str, item_id: str, include_sensitive: bool = True) -> dict:
    item = service.get_item(db, group_id, item_id)
    if item.sensitivity == "sensitive" and not include_sensitive:
        # 존재는 알리되 내용은 주지 않는다(LLM 이 "없다"고 오해하지 않게)
        return {
            "error": "민감한 기록이라 이 대화에서는 내용을 볼 수 없어요. 앱의 기록 화면에서 직접 확인해 주세요."
        }
    return {
        "item_id": item.id,
        "kind_label": item.kind_label,
        "title": item.title,
        "text": item.body_md,
        "date": item.occurred_on.isoformat() if item.occurred_on else None,
        "source_path": item.source_path,
        "has_unread_parts": item.has_unread_parts,
        "sensitive": item.sensitivity == "sensitive",
    }


def list_items(
    db: Session,
    group_id: str,
    kind_label: str | None = None,
    limit: int = 20,
    include_sensitive: bool = True,
) -> dict:
    items = service.list_items(db, group_id, kind_label, min(max(limit, 1), 50))
    if not include_sensitive:
        items = [i for i in items if i.sensitivity != "sensitive"]
    return {
        "items": [
            {
                "item_id": i.id,
                "kind_label": i.kind_label,
                "title": i.title,
                "date": i.occurred_on.isoformat() if i.occurred_on else None,
            }
            for i in items
        ]
    }
