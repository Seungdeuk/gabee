"""평가용 가짜 가족 데이터. 테스트(pytest)와 실제 LLM 평가(run.py)가 같은 데이터를 쓴다."""

from fastapi.testclient import TestClient


def seed(client: TestClient, a: dict, b: dict) -> None:
    """a=지민, b=수진 헤더. 2026-10 지출 3건, 지민만 위치 공유 동의, 식단 기록 2건."""
    for title, amount, headers in (("진료비", 30000, a), ("약", 10000, b), ("장보기", 20000, a)):
        r = client.post(
            "/billing/expenses",
            json={"title": title, "amount": amount, "date": "2026-10-12"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
    client.post(
        "/billing/subscriptions",
        json={"kind": "ott", "name": "넷플릭스", "monthly_fee": 17000, "billing_day": 15},
        headers=a,
    )
    assert (
        client.put("/care/location/consent", json={"consent": True}, headers=a).status_code == 200
    )
    for date, meal, menu in (("2026-10-20", "breakfast", "죽"), ("2026-10-20", "lunch", "비빔밥")):
        r = client.put("/care/meal-log", json={"date": date, "meal": meal, "menu": menu}, headers=a)
        assert r.status_code == 200, r.text
