"""문서 구성원별 읽음 기록: 상세를 열면 남고, 본인 것만 목록의 seen 으로 보인다."""

from sqlalchemy import func, select

from app.features.ai_assistant.knowledge.models import KnowledgeItemRead
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

K = "/ai-assistant/knowledge/items"


def _add(client, headers, title="문서"):
    r = client.post(
        K, json={"kind_label": "메모", "title": title, "body_md": f"# {title}"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seen(client, headers, item_id):
    r = client.get(K, headers=headers)
    assert r.status_code == 200, r.text
    return {i["id"]: i["seen"] for i in r.json()}[item_id]


def _rows(item_id=None):
    with SessionLocal() as db:
        q = select(func.count()).select_from(KnowledgeItemRead)
        if item_id:
            q = q.where(KnowledgeItemRead.item_id == item_id)
        return db.scalar(q)


def test_unread_until_detail_opened(client, family):
    jimin, sujin, _ = family
    item_id = _add(client, sujin)
    assert _seen(client, jimin, item_id) is False
    r = client.get(f"{K}/{item_id}", headers=jimin)
    assert r.status_code == 200
    assert r.json()["seen"] is True
    assert _seen(client, jimin, item_id) is True


def test_uploader_sees_own_from_start_without_row(client, family):
    _, sujin, _ = family
    item_id = _add(client, sujin)
    assert _seen(client, sujin, item_id) is True
    assert _rows(item_id) == 0


def test_reads_are_per_member(client, family):
    jimin, sujin, group = family
    third = signup(client, "민수", "child")
    join_family(client, jimin, group["invite_code"], third)
    item_id = _add(client, sujin)
    client.get(f"{K}/{item_id}", headers=jimin)  # 지민만 연다
    assert _seen(client, jimin, item_id) is True
    assert _seen(client, third, item_id) is False  # 다른 구성원(민수)의 읽음은 영향 없음
    assert _seen(client, sujin, item_id) is True  # 올린 사람은 처음부터 본 것
    jimin_id = client.get("/family-group/me", headers=jimin).json()["id"]
    with SessionLocal() as db:
        owners = list(
            db.scalars(
                select(KnowledgeItemRead.user_id).where(KnowledgeItemRead.item_id == item_id)
            )
        )
    assert owners == [jimin_id]  # 읽음 행은 지민 것 하나뿐


def test_patch_response_seen_matches_list(client, family):
    jimin, sujin, _ = family
    item_id = _add(client, sujin)
    r = client.patch(f"{K}/{item_id}", json={"title": "고침"}, headers=jimin)
    assert r.status_code == 200, r.text
    assert r.json()["seen"] is False  # 상세를 열지 않고 고친 사람은 아직 본 것이 아니다
    assert _seen(client, jimin, item_id) is False


def test_first_read_time_is_kept(client, family):
    jimin, sujin, _ = family
    item_id = _add(client, sujin)

    def read_at():
        with SessionLocal() as db:
            return db.scalar(
                select(KnowledgeItemRead.read_at).where(KnowledgeItemRead.item_id == item_id)
            )

    client.get(f"{K}/{item_id}", headers=jimin)
    first = read_at()
    client.get(f"{K}/{item_id}", headers=jimin)
    assert read_at() == first  # 두 번째로 열어도 처음 연 시각이 유지된다


def test_repeated_opens_keep_single_row(client, family):
    jimin, sujin, _ = family
    item_id = _add(client, sujin)
    for _i in range(3):
        assert client.get(f"{K}/{item_id}", headers=jimin).status_code == 200
    assert _rows(item_id) == 1


def test_other_family_detail_404_and_no_row(client, family, other_family):
    _, sujin, _ = family
    item_id = _add(client, sujin)
    assert client.get(f"{K}/{item_id}", headers=other_family).status_code == 404
    assert _rows() == 0


def test_delete_removes_reads(client, family):
    jimin, sujin, _ = family
    item_id = _add(client, sujin)
    client.get(f"{K}/{item_id}", headers=jimin)
    assert _rows(item_id) == 1
    assert client.delete(f"{K}/{item_id}", headers=sujin).status_code == 204
    assert _rows() == 0


def test_list_fields_order_and_filters_unchanged(client, family):
    jimin, sujin, _ = family
    ids = [_add(client, sujin, f"항목{i}") for i in range(3)]
    r = client.get(K, params={"limit": 2}, headers=jimin)
    assert r.status_code == 200
    body = r.json()
    assert [i["id"] for i in body] == [ids[2], ids[1]]
    assert {"id", "title", "kind_label", "needs_review", "needs_description", "seen"} <= set(
        body[0]
    )
    r = client.get(
        K, params={"created_from": "2000-01-01", "created_to": "2099-01-01"}, headers=jimin
    )
    assert len(r.json()) == 3
    r = client.get(K, params={"created_from": "2099-01-01"}, headers=jimin)
    assert r.json() == []
