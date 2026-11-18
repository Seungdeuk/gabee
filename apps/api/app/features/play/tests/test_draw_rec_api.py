"""GET /play/draw/recommendations: 로그인한 가족에게 이게 뭐게 가비 추천을 돌려준다. 실제 AI 는 부르지 않는다."""

import pytest

from app.features.play import draw_rec
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.helpers import signup

PATH = "/play/draw/recommendations"
GOOD = {"strokes": [[[10, 10], [200, 10]], [[10, 20], [200, 20], [100, 100]], [[0, 0], [255, 255]]]}


@pytest.fixture(autouse=True)
def loose_limits():
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 100, 100), (draw_rec.FEATURE,))
    yield
    draw_rec.register_limits()


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def complete(prompt, schema, system=None, max_tokens=None, **kw):
        calls.append(prompt)
        return llm.JsonResult(data=GOOD, input_tokens=100, output_tokens=50, model="fake")

    monkeypatch.setattr(llm, "complete_json", complete)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return calls


def enable_ai(client, headers):
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers).status_code
        == 200
    )


def test_returns_five_drawings_for_a_family(client, family, fake):
    a, _, _ = family
    enable_ai(client, a)
    r = client.get(PATH, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ok"
    assert len(body["items"]) == draw_rec.ASK_COUNT == 5
    for item in body["items"]:
        assert set(item) == {"id", "source", "word", "alt_answers", "strokes"}
        assert item["source"] == "common"  # 가족 재료가 없으면 흔한 단어로 채운다
        assert 3 <= len(item["strokes"]) <= 12
    assert len({i["word"] for i in body["items"]}) == 5


def test_same_day_is_cached_for_the_family(client, family, fake):
    a, b, _ = family
    enable_ai(client, a)
    first = client.get(PATH, headers=a).json()
    used = len(fake)
    assert client.get(PATH, headers=b).json() == first  # 같은 가족은 누가 열어도 같은 묶음
    assert len(fake) == used


def test_ai_off_state_is_200(client, family, fake):
    a, _, _ = family
    r = client.get(PATH, headers=a)
    assert r.status_code == 200
    assert r.json() == {"state": "ai_off", "items": []}


def test_requires_login(client):
    assert client.get(PATH).status_code == 401


def test_user_without_family_group_is_rejected(client):
    lonely = signup(client, "혼자")
    r = client.get(PATH, headers=lonely)
    assert r.status_code == 400
    assert r.json()["code"] == "no_group"
