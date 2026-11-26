"""동의 없이 로컬 규칙으로만 가려 저장됐을 수 있는 채팅 문서가 @가비·메인 AI 도구(= 외부 AI 로 나가는 길)로 재노출되지 않는다.

규칙: 채팅 첨부에서 만든 기록(source_attachment_id 있음)은 가족 AI 동의가 마지막으로 켜진 시각 이후에 만든 것만 보인다. 동의가 꺼져 있거나 기록이 없으면
채팅 기록은 모두 빠진다. 채팅 첨부가 아닌 기록(메인 AI 직접 업로드·직접 작성)은 항상 보인다. 앱의 문서함 화면(사용자가 직접 보는 것)은 바꾸지 않는다.
시험 데이터는 모두 가짜다. 외부 서비스는 부르지 않는다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.features.ai_assistant.knowledge import tools
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.shared.ai_usage import AiGroupSetting
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

K = "/ai-assistant/knowledge/items"
T0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 가족 AI 동의가 켜진 시각


def _add(client, headers, title, created_at, chat_attachment=None):
    r = client.post(
        K,
        json={"kind_label": "가정통신문", "title": title, "body_md": f"# {title}\n준비물 안내"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]
    with SessionLocal() as db:
        db.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == item_id)
            .values(created_at=created_at, source_attachment_id=chat_attachment)
        )
        db.commit()
    return item_id


def _consent(group_id, enabled=True, at=T0):
    with SessionLocal() as db:
        row = db.get(AiGroupSetting, group_id)
        if row is None:
            db.add(AiGroupSetting(group_id=group_id, enabled=enabled, updated_at=at))
        else:
            row.enabled, row.updated_at = enabled, at
        db.commit()


def _seed(client, family):
    a, _, group = family
    ids = {
        "main_old": _add(client, a, "메인 업로드 옛것", T0 - timedelta(days=30)),
        "chat_old": _add(client, a, "채팅 문서 동의 전", T0 - timedelta(days=1), "att_old"),
        "chat_new": _add(client, a, "채팅 문서 동의 후", T0 + timedelta(days=1), "att_new"),
    }
    return group["id"], ids


def _found(db, gid):
    return (
        {r["item_id"] for r in tools.search_knowledge(db, gid, "준비물 안내", top_k=10)["results"]},
        {i["item_id"] for i in tools.list_items(db, gid)["items"]},
    )


def test_chat_documents_from_before_consent_are_hidden_from_the_ai_tools(client, family):
    gid, ids = _seed(client, family)
    _consent(gid)
    with SessionLocal() as db:
        searched, listed = _found(db, gid)
    expected = {ids["main_old"], ids["chat_new"]}
    assert searched == expected and listed == expected
    assert ids["chat_old"] not in searched | listed  # 이름·주소가 남아 있을 수 있는 옛 채팅 문서


def test_get_item_refuses_a_chat_document_from_before_consent(client, family):
    gid, ids = _seed(client, family)
    _consent(gid)
    with SessionLocal() as db:
        withheld = tools.get_item(db, gid, ids["chat_old"])
        assert "error" in withheld and "동의" in withheld["error"]
        assert "error" not in tools.get_item(db, gid, ids["chat_new"])
        assert "error" not in tools.get_item(db, gid, ids["main_old"])


def test_every_chat_document_is_hidden_while_consent_is_off_or_missing(client, family):
    gid, ids = _seed(client, family)
    for state in ("missing", "off"):
        if state == "off":
            _consent(gid, enabled=False)
        with SessionLocal() as db:
            searched, listed = _found(db, gid)
            assert searched == listed == {ids["main_old"]}, state  # 메인 AI 기록만
            assert "error" in tools.get_item(db, gid, ids["chat_new"]), state


def test_turning_consent_off_and_on_again_moves_the_cutoff_forward(client, family):
    gid, ids = _seed(client, family)
    _consent(gid, at=T0)
    _consent(gid, enabled=False, at=T0 + timedelta(days=2))
    _consent(
        gid, enabled=True, at=T0 + timedelta(days=3)
    )  # 다시 켠 시각이 새 기준: 그 전에 만든 채팅 문서는 보호 여부 불명
    with SessionLocal() as db:
        searched, listed = _found(db, gid)
    assert searched == listed == {ids["main_old"]}


def test_a_record_created_exactly_at_the_consent_time_is_visible(client, family):
    a, _, group = family
    item = _add(client, a, "동의와 같은 시각", T0, "att_tie")
    _consent(group["id"], at=T0)
    with SessionLocal() as db:
        assert item in {i["item_id"] for i in tools.list_items(db, group["id"])["items"]}


def test_the_app_document_screen_is_unchanged_and_still_lists_everything(client, family):
    a, _, group = family
    _, ids = _seed(client, family)
    _consent(group["id"])
    r = client.get(K, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["items"] if isinstance(body, dict) else body
    shown = {i.get("id") or i.get("item_id") for i in rows}
    assert (
        set(ids.values()) <= shown
    )  # 사용자가 직접 보는 화면은 그대로다(외부 AI 로 나가는 길만 막는다)


def test_saving_consent_again_while_it_is_on_does_not_move_the_cutoff(client, family):
    """이미 켜진 동의를 다시 저장(같은 값 PUT)해도 기준 시각이 바뀌지 않는다: 바뀌면 동의 아래 등록한 채팅 문서가 모두 사라진다(독립 리뷰 M2)."""
    from app.shared import ai_guard

    gid, ids = _seed(client, family)
    _consent(gid)
    with SessionLocal() as db:
        ai_guard.set_enabled(db, gid, "u", True)  # 같은 값 다시 저장
    with SessionLocal() as db:
        searched, listed = _found(db, gid)
    assert ids["chat_new"] in searched and ids["chat_new"] in listed


def test_turning_consent_off_and_on_moves_the_cutoff_to_the_new_consent(client, family):
    from app.shared import ai_guard

    gid, ids = _seed(client, family)
    _consent(gid)
    with SessionLocal() as db:
        ai_guard.set_enabled(db, gid, "u", False)
        ai_guard.set_enabled(db, gid, "u", True)  # 지금 다시 켰다: 그 전 채팅 문서는 뺀다
    with SessionLocal() as db:
        searched, listed = _found(db, gid)
    assert ids["chat_new"] not in searched | listed and ids["main_old"] in listed


def test_name_checks_do_not_show_chat_documents_from_before_consent(client, family):
    """이름 확인 도구도 제목·앞뒤 글을 외부 AI 에 보이므로 같은 기준으로 뺀다(독립 리뷰 M3)."""
    gid, ids = _seed(client, family)
    _consent(gid)
    with SessionLocal() as db:
        for key in ("chat_old", "chat_new"):
            item = db.get(KnowledgeItem, ids[key])
            item.body_md = item.body_md + "\n담임 [확인필요:u1] 선생님"
        db.commit()
    with SessionLocal() as db:
        shown = {c["item_id"] for c in tools.list_name_checks(db, gid)["checks"]}
    assert ids["chat_new"] in shown and ids["chat_old"] not in shown
