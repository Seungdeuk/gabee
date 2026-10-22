"""구독·통신비 항목 관리: 추가·수정·삭제, 통신사·월 금액·결제일, 월 합계(할인은 반영하지 않음)."""

from sqlalchemy import select

from app.features.billing.models import SubscriptionItem
from app.shared.db import SessionLocal
from tests.helpers import signup


def _list(client, headers):
    return client.get("/billing/subscriptions", headers=headers).json()


def _add(client, headers, **body):
    return client.post("/billing/subscriptions", json=body, headers=headers)


def test_list_starts_empty_and_services_are_picked_from_the_catalog(client, family):
    a, _, _ = family
    data = _list(client, a)
    assert data["items"] == [] and data["monthly_total"] == 0 and data["discount_total"] == 0
    assert "예시, 실제 적용은 통신사에서 확인" in data["notice"]
    cat = client.get("/billing/subscriptions/catalog", headers=a).json()["items"]
    names = {(c["kind"], c["name"]) for c in cat}
    assert ("ott", "넷플릭스") in names and ("telecom", "가족 결합 할인") in names
    assert not any(c["added"] for c in cat)  # 아직 아무것도 고르지 않았다
    assert _add(client, a, kind="ott", name="넷플릭스").status_code == 201
    cat = client.get("/billing/subscriptions/catalog", headers=a).json()["items"]
    assert {c["name"]: c["added"] for c in cat if c["kind"] == "ott"}["넷플릭스"] is True
    assert [i["name"] for i in _list(client, a)["items"]] == ["넷플릭스"]  # 고른 것만 화면에 뜬다


def test_discount_is_entered_by_hand_and_list_price_is_fee_plus_discount(client, family):
    a, _, _ = family
    item = _add(
        client,
        a,
        kind="telecom",
        name="가족 결합 할인",
        carrier="skt",
        monthly_fee=55000,
        discount_amount=11000,
    ).json()
    assert item["monthly_fee"] == 55000 and item["discount_amount"] == 11000
    assert item["list_price"] == 66000  # 정가 = 청구 금액 + 할인 금액
    data = _list(client, a)
    assert data["monthly_total"] == 55000 and data["discount_total"] == 11000
    r = client.patch(
        f"/billing/subscriptions/{item['id']}", json={"discount_amount": 9000}, headers=a
    )
    assert r.json()["discount_amount"] == 9000 and r.json()["list_price"] == 64000
    assert r.json()["monthly_fee"] == 55000  # 보내지 않은 값은 그대로
    r = client.patch(
        f"/billing/subscriptions/{item['id']}", json={"discount_amount": None}, headers=a
    )
    assert r.json()["discount_amount"] is None and r.json()["list_price"] == 55000
    for bad in (-1, 10_000_001):
        assert _add(client, a, kind="ott", name="x", discount_amount=bad).status_code == 422


def test_add_ott_and_telecom_with_fee_day_and_carrier(client, family):
    a, _, _ = family
    ott = _add(client, a, kind="ott", name="  왓챠  ", monthly_fee=7900, billing_day=5)
    assert ott.status_code == 201
    o = ott.json()
    assert (
        o["name"],
        o["kind"],
        o["status"],
        o["monthly_fee"],
        o["billing_day"],
        o["carrier"],
    ) == ("왓챠", "ott", "check", 7900, 5, None)
    tel = _add(
        client,
        a,
        kind="telecom",
        name="우리 집 통신비",
        carrier="skt",
        monthly_fee=55000,
        billing_day=25,
    ).json()
    assert tel["carrier"] == "skt"

    data = _list(client, a)
    assert [i["name"] for i in data["items"]][-2:] == ["왓챠", "우리 집 통신비"]  # 끝에 추가된다
    assert data["monthly_total"] == 7900 + 55000  # 입력한 금액의 합(할인 미반영)


def test_add_validation(client, family):
    a, _, _ = family
    assert (
        _add(client, a, kind="ott", name="x", carrier="skt").json()["code"] == "invalid_carrier"
    )  # 통신사는 통신비만
    assert _add(client, a, kind="telecom", name="x", carrier="docomo").status_code == 422
    assert _add(client, a, kind="ott", name="x", monthly_fee=-1).status_code == 422
    assert _add(client, a, kind="ott", name="x", monthly_fee=10_000_001).status_code == 422
    assert _add(client, a, kind="ott", name="x", billing_day=0).status_code == 422
    assert _add(client, a, kind="ott", name="x", billing_day=32).status_code == 422
    assert _add(client, a, kind="ott", name="").status_code == 422
    assert _add(client, a, kind="ott", name="   ").json()["code"] == "invalid_name"
    assert _add(client, a, kind="video", name="x").status_code == 422
    assert len(_list(client, a)["items"]) == 0  # 실패한 요청은 아무것도 만들지 않는다


def test_patch_changes_only_the_sent_fields_and_null_clears(client, family):
    a, _, _ = family
    item = _add(
        client, a, kind="telecom", name="통신비", carrier="kt", monthly_fee=40000, billing_day=10
    ).json()
    url = f"/billing/subscriptions/{item['id']}"

    r = client.patch(url, json={"status": "active"}, headers=a).json()
    assert (r["status"], r["monthly_fee"], r["billing_day"], r["carrier"], r["name"]) == (
        "active",
        40000,
        10,
        "kt",
        "통신비",
    )
    r = client.patch(url, json={"monthly_fee": 38000, "name": "KT 통신비"}, headers=a).json()
    assert (r["monthly_fee"], r["name"], r["status"]) == (38000, "KT 통신비", "active")
    r = client.patch(
        url, json={"monthly_fee": None, "billing_day": None, "carrier": None}, headers=a
    ).json()
    assert (r["monthly_fee"], r["billing_day"], r["carrier"]) == (None, None, None)
    assert client.patch(url, json={}, headers=a).json()["code"] == "empty_patch"
    assert client.patch(url, json={"billing_day": 40}, headers=a).status_code == 422
    assert client.patch(url, json={"name": "  "}, headers=a).json()["code"] == "invalid_name"
    assert (
        client.patch("/billing/subscriptions/nope", json={"status": "check"}, headers=a).status_code
        == 404
    )


def test_carrier_can_only_be_set_on_telecom_items(client, family):
    a, _, _ = family
    ott = _add(client, a, kind="ott", name="티빙").json()
    r = client.patch(f"/billing/subscriptions/{ott['id']}", json={"carrier": "lgu"}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_carrier"
    tel = _add(client, a, kind="telecom", name="통신").json()
    assert (
        client.patch(
            f"/billing/subscriptions/{tel['id']}", json={"carrier": "lgu"}, headers=a
        ).json()["carrier"]
        == "lgu"
    )


def test_delete_is_soft_and_nothing_comes_back(client, family):
    a, _, _ = family
    extra = _add(client, a, kind="ott", name="지울 것", monthly_fee=1000).json()
    assert client.delete(f"/billing/subscriptions/{extra['id']}", headers=a).status_code == 204
    data = _list(client, a)
    assert extra["id"] not in [i["id"] for i in data["items"]] and data["monthly_total"] == 0
    assert (
        client.delete(f"/billing/subscriptions/{extra['id']}", headers=a).status_code == 404
    )  # 이미 삭제됨
    assert (
        client.patch(
            f"/billing/subscriptions/{extra['id']}", json={"status": "active"}, headers=a
        ).status_code
        == 404
    )
    with SessionLocal() as db:
        row = db.scalar(select(SubscriptionItem).where(SubscriptionItem.id == extra["id"]))
    assert row is not None and row.deleted_at is not None  # 행은 남는다

    for i in _list(client, a)["items"]:  # 전부 지워도 다시 만들어지지 않는다
        client.delete(f"/billing/subscriptions/{i['id']}", headers=a)
    data = _list(client, a)
    assert data["items"] == [] and data["monthly_total"] == 0 and data["discount_total"] == 0
    assert _add(client, a, kind="ott", name="새로 시작").status_code == 201
    assert len(_list(client, a)["items"]) == 1


def test_other_families_cannot_see_or_change_items(client, family):
    a, _, _ = family
    mine = _add(client, a, kind="ott", name="우리만", monthly_fee=9900).json()
    outsider = signup(client, "남의 집")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    theirs = _list(client, outsider)
    assert "우리만" not in [i["name"] for i in theirs["items"]] and theirs["monthly_total"] == 0
    assert (
        client.patch(
            f"/billing/subscriptions/{mine['id']}", json={"status": "active"}, headers=outsider
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/billing/subscriptions/{mine['id']}", headers=outsider).status_code == 404
    )
    assert [i for i in _list(client, a)["items"] if i["id"] == mine["id"]][0]["status"] == "check"


def test_item_limit(client, family):
    a, _, _ = family  # 처음엔 비어 있다
    for n in range(30):
        assert _add(client, a, kind="ott", name=f"항목{n}").status_code == 201
    r = _add(client, a, kind="ott", name="31번째")
    assert r.status_code == 400 and r.json()["code"] == "too_many"
