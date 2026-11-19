"""찰칵 흔한 사진 자동 보충 시험: 가짜 Pixabay·가짜 AI 만 쓴다(네트워크·AI 호출 없음)."""

import io
import logging
import random
import threading
from datetime import UTC, datetime

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_group.models import User
from app.features.play import photo_rec as rec
from app.features.play import photo_rec_auto as auto
from app.features.play import photo_rec_auto_ai as auto_ai
from app.features.play import photo_rec_pixabay as pix
from app.features.play import photo_rec_store as store
from app.features.play.models import PlayPhotoRec
from app.features.play.photo_rec_pool import pool_rows
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

NOW = datetime(2026, 11, 20, 1, 0, tzinfo=UTC)  # 한국 시간 11/20 10시


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _hit(i: int, tags: str = "pizza, food") -> dict:
    return {
        "id": i,
        "tags": tags,
        "user": f"user{i}",
        "pageURL": f"https://pixabay.com/photos/x-{i}/",
        "largeImageURL": f"https://pixabay.com/img/{i}.jpg",
    }


class FakeFetch:
    """검색어마다 같은 후보 목록을 돌려주는 가짜 Pixabay."""

    def __init__(self, hits: list[dict], fail_download: set[int] | None = None):
        self.hits = hits
        self.fail_download = fail_download or set()
        self.searches: list[str] = []
        self.downloads: list[int] = []

    def search(self, q: str) -> list[dict]:
        self.searches.append(q)
        return list(self.hits)

    def download(self, hit: dict) -> bytes:
        self.downloads.append(hit["id"])
        if hit["id"] in self.fail_download:
            raise httpx.ConnectError("boom")
        return _jpeg()


def _good(**kw) -> auto_ai.AutoQuestion:
    fields = dict(
        usable=True,
        question="무슨 음식일까요?",
        options=["피자", "햄버거"],
        answer_index=0,
        box_x=0.4,
        box_y=0.6,
        tokens=10,
    )
    fields.update(kw)
    return auto_ai.AutoQuestion(**fields)


def _script(*verdicts):
    """호출 순서대로 verdict(AutoQuestion 이면 돌려주고 예외면 던진다)를 쓰는 가짜 ask. 다 쓰면 좋은 질문."""
    queue = list(verdicts)

    def ask(_jpeg: bytes):
        v = queue.pop(0) if queue else _good()
        if isinstance(v, Exception):
            raise v
        return v

    return ask


def _ask_ok(_jpeg: bytes) -> auto_ai.AutoQuestion:
    return _good()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "pixabay_api_key", "test-key")
    monkeypatch.setattr(settings, "photo_rec_auto_per_day", 3)
    monkeypatch.setattr(settings, "photo_rec_auto_max_attempts", 3)


def _run(fetch, ask=_ask_ok, now=NOW):
    with SessionLocal() as db:
        return auto.run_daily(db, now, fetch=fetch, ask=ask, rng=random.Random(1))


def _rows() -> list[PlayPhotoRec]:
    with SessionLocal() as db:
        return list(db.scalars(select(PlayPhotoRec).order_by(PlayPhotoRec.id)))


def _usable() -> list[PlayPhotoRec]:
    return [r for r in _rows() if r.usable]


def test_fills_target_in_one_attempt(client):
    result = _run(FakeFetch([_hit(i) for i in range(1, 9)]))
    assert len(_usable()) == 3 and result.added == 3 and result.attempts == 1


def test_second_attempt_fills_shortage(client):
    fail = [auto_ai.Rejected("x")] * auto.CANDIDATES_PER_ATTEMPT
    result = _run(FakeFetch([_hit(i) for i in range(1, 40)]), ask=_script(*fail))
    assert result.attempts == 2 and result.added == 3
    assert len(_usable()) == 3


def test_second_attempt_asks_only_for_missing(client):
    n = auto.CANDIDATES_PER_ATTEMPT
    verdicts = [_good()] + [auto_ai.Rejected("x")] * (n - 1)  # 첫 시도: 1장 성공
    result = _run(FakeFetch([_hit(i) for i in range(1, 40)]), ask=_script(*verdicts))
    assert result.attempts == 2 and result.added == 3
    assert len(_usable()) == 3


def test_gives_up_after_three_attempts_and_logs(client, caplog):
    def never(_jpeg):
        raise auto_ai.Rejected("x")

    with caplog.at_level(logging.WARNING):
        result = _run(FakeFetch([_hit(i) for i in range(1, 80)]), ask=never)
    assert result.attempts == 3 and result.added == 0
    assert not _usable()
    assert "photo rec auto" in caplog.text


def test_partial_when_one_attempt_budget_left(client, monkeypatch):
    monkeypatch.setattr(settings, "photo_rec_auto_max_attempts", 1)
    n = auto.CANDIDATES_PER_ATTEMPT
    verdicts = [_good(), _good()] + [auto_ai.Rejected("x")] * n
    result = _run(FakeFetch([_hit(i) for i in range(1, 40)]), ask=_script(*verdicts))
    assert result.attempts == 1 and result.added == 2 and len(_usable()) == 2


def test_nothing_to_do_when_already_three_today(client):
    _run(FakeFetch([_hit(i) for i in range(1, 9)]))
    fetch = FakeFetch([_hit(i) for i in range(100, 110)])
    result = _run(fetch)
    assert result.added == 0 and result.attempts == 0 and fetch.searches == []
    assert len(_usable()) == 3


def test_previous_day_rows_do_not_count(client):
    _run(FakeFetch([_hit(i) for i in range(1, 9)]))
    next_day = datetime(2026, 11, 21, 1, 0, tzinfo=UTC)
    result = _run(FakeFetch([_hit(i) for i in range(100, 110)]), now=next_day)
    assert result.added == 3


def test_same_pixabay_id_not_reused(client):
    _run(FakeFetch([_hit(i) for i in range(1, 4)]))
    with SessionLocal() as db:  # 오늘 행을 열흘 전으로 돌려 다시 채우게 한다
        for r in db.scalars(select(PlayPhotoRec)):
            r.created_at = datetime(2026, 11, 10, tzinfo=UTC)
        db.commit()
    fetch = FakeFetch([_hit(i) for i in range(1, 7)])  # 1~3 은 이미 풀에 있음
    _run(fetch)
    assert set(fetch.downloads) == {4, 5, 6}
    ids = [r.external_id for r in _rows()]
    assert len(ids) == len(set(ids)) == 6


def test_unusable_and_rejected_become_tombstones_not_retried(client):
    ask = _script(_good(usable=False), auto_ai.Rejected("금지어"))
    fetch = FakeFetch([_hit(i) for i in range(1, 9)])
    _run(fetch, ask=ask)
    rows = _rows()
    dead = [r for r in rows if not r.usable]
    assert len(_usable()) == 3 and len(dead) == 2
    assert all(r.image is None and r.source == store.SOURCE_AUTO for r in dead)
    assert len(fetch.downloads) == len(set(fetch.downloads))
    with SessionLocal() as db:
        assert not {r.id for r in dead} & {r.id for r in pool_rows(db, set())}


def test_download_or_ai_outage_skips_candidate_without_tombstone(client):
    fetch = FakeFetch([_hit(i) for i in range(1, 9)], fail_download={1})
    ask = _script(llm.LLMUnavailable("down"))  # 두 번째 후보(2)에서 AI 장애
    _run(fetch, ask=ask)
    rows = _rows()
    assert len(_usable()) == 3
    assert {r.external_id for r in rows}.isdisjoint({"1", "2"})


def test_bad_tag_candidates_filtered(client):
    hits = [_hit(1, "selfie, pizza"), _hit(2, "snake"), _hit(3, "beer, glass"), _hit(4, "pizza")]
    fetch = FakeFetch(hits)
    _run(fetch)
    assert set(fetch.downloads) == {4}


def test_saved_row_fields(client):
    _run(FakeFetch([_hit(7)]))
    row = _usable()[0]
    assert row.id == "auto7" and row.source == store.SOURCE_AUTO
    assert row.group_id is None and row.attachment_id is None
    assert row.prompt_version == "auto-v1" == auto_ai.PROMPT_VERSION
    assert row.image and row.image[:2] == b"\xff\xd8"
    assert row.external_id == "7" and row.credit_user == "user7"
    assert row.credit_url == "https://pixabay.com/photos/x-7/"
    assert row.license == pix.LICENSE and row.search_query
    assert row.kind == store.KIND_CONTENT and row.zoom == 8 and row.answer == "10"
    assert (row.question, row.options) == ("무슨 음식일까요?", ["피자", "햄버거"])


def test_auto_rows_in_pool_and_recommended(client, family):
    a, _, _ = family
    _run(FakeFetch([_hit(i) for i in range(1, 4)]))
    with SessionLocal() as db:
        assert {r.id for r in pool_rows(db, set())} == {"auto1", "auto2", "auto3"}
    me = client.get("/family-group/me", headers=a).json()["id"]
    gid = client.get("/family-group/groups/me", headers=a).json()["id"]
    with SessionLocal() as db:
        out = rec.recommend(db, db.get(User, me), gid)
    assert out["state"] == "ok"
    assert {i["id"] for i in out["items"]} == {"auto1", "auto2", "auto3"}


def test_no_key_skips_quietly_with_log(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "pixabay_api_key", "")
    with caplog.at_level(logging.INFO), SessionLocal() as db:
        result = auto.run_daily(db, NOW)
    assert result.skipped == "no_key" and result.added == 0
    assert "photo rec auto" in caplog.text


def test_no_llm_key_skips(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with SessionLocal() as db:
        result = auto.run_daily(db, NOW, fetch=FakeFetch([_hit(1)]))
    assert result.skipped == "no_llm"


def test_start_respects_flag(monkeypatch):
    monkeypatch.setattr(auto, "_started", threading.Event())
    started = []

    class _T:
        def __init__(self, *a, **k):
            started.append(k)

        def start(self):
            pass

    monkeypatch.setattr(auto.threading, "Thread", _T)
    monkeypatch.setattr(settings, "photo_rec_auto_enabled", False)
    auto.start()
    assert started == []
    monkeypatch.setattr(settings, "photo_rec_auto_enabled", True)
    auto.start()
    auto.start()  # 두 번 불러도 한 번만
    assert len(started) == 1


def test_is_due_after_hour_once_per_day():
    def kst(h: int) -> datetime:  # 한국 시간 11/20 h시
        return datetime(2026, 11, 20, tzinfo=UTC).replace(hour=0) + (
            __import__("datetime").timedelta(hours=h - 9)
        )

    assert auto.is_due(kst(3), 4, None) is False
    assert auto.is_due(kst(4), 4, None) is True
    assert auto.is_due(kst(15), 4, None) is True
    assert auto.is_due(kst(15), 4, "2026-11-20") is False
    assert auto.is_due(kst(15), 4, "2026-11-19") is True


def test_logs_never_contain_key(client, caplog):
    def boom(_j):
        raise RuntimeError("https://x/?key=test-key")

    with caplog.at_level(logging.DEBUG):
        _run(FakeFetch([_hit(i) for i in range(1, 5)]), ask=boom)
    assert "test-key" not in caplog.text


# ---- Pixabay 클라이언트 ----


def test_pixabay_search_params_and_cache():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"hits": [_hit(1)]})

    c = pix.PixabayClient("k", httpx.Client(transport=httpx.MockTransport(handler)), gap=0)
    assert c.search("pizza")[0]["id"] == 1
    c.search("pizza")  # 24시간 캐시
    assert len(seen) == 1
    assert seen[0]["safesearch"] == "true" and seen[0]["q"] == "pizza" and seen[0]["key"] == "k"


def test_pixabay_download_resizes_to_jpeg():
    big = io.BytesIO()
    Image.new("RGB", (2000, 1000), (1, 2, 3)).save(big, "PNG")

    def handler(request):
        return httpx.Response(200, content=big.getvalue())

    c = pix.PixabayClient("k", httpx.Client(transport=httpx.MockTransport(handler)), gap=0)
    im = Image.open(io.BytesIO(c.download(_hit(1))))
    assert im.format == "JPEG" and max(im.size) == 1280


def test_pixabay_error_has_no_key():
    def handler(request):
        return httpx.Response(500)

    c = pix.PixabayClient("secret-key", httpx.Client(transport=httpx.MockTransport(handler)), gap=0)
    with pytest.raises(pix.PixabayError) as e:
        c.search("pizza")
    assert "secret-key" not in str(e.value)


def test_pixabay_query_list_and_filter():
    assert len(pix.QUERIES) >= 60 and all(len(q) <= 60 for _, q in pix.QUERIES)
    queries = {q for _, q in pix.QUERIES}
    assert not queries & {
        "balloons",
        "train",
        "umbrella",
        "pencils",
        "alarm clock",
        "sushi",
        "sneakers",
    }  # 사용자가 뺀 소재
    assert {"classroom", "bedroom", "cookies", "freesia", "lily", "rose of sharon"} <= queries
    assert pix.is_clean(_hit(1, "pizza, food")) and not pix.is_clean(_hit(1, "Selfie, pizza"))
    assert pix.is_clean(
        _hit(1, "woman, library, book")
    )  # 사람이 함께 찍혀도 되고 책 태그도 허용(사용자 11/19)


# ---- 공개 사진용 AI 질문 ----


def _raw(**kw):
    raw = dict(
        usable=True,
        question="무슨 음식일까요?",
        options=["피자", "햄버거"],
        answer_index=0,
        box_x=0.5,
        box_y=0.5,
    )
    raw.update(kw)
    return raw


def _fake_llm(monkeypatch, raw):
    calls = []

    def fake(prompt, schema, **kw):
        calls.append(kw)
        return llm.JsonResult(data=raw, input_tokens=5, output_tokens=7, model="m")

    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    return calls


def test_make_question_ok_single_call_no_family_info(monkeypatch):
    calls = _fake_llm(monkeypatch, _raw())
    q = auto_ai.make_question(_jpeg())
    assert q.usable and q.options == ["피자", "햄버거"] and q.tokens == 12
    assert len(calls) == 1 and calls[0]["images"]


def test_make_question_unusable(monkeypatch):
    _fake_llm(monkeypatch, _raw(usable=False, question="", options=[], answer_index=0))
    assert auto_ai.make_question(_jpeg()).usable is False


@pytest.mark.parametrize(
    "bad",
    [
        _raw(question="한식일까요?"),
        _raw(question="이 음식이 어울릴까요?"),
        _raw(question="무슨 색일까요?", options=["빨강", "파랑"]),
        _raw(question="무슨 꽃일까요?", options=["국화", "장미"]),
        _raw(question="무슨 꽃일까요?", options=["할미꽃", "장미"]),
        _raw(question="무슨 꽃일까요?", options=["장미", "난초"]),  # 허용 목록 밖
        _raw(question="무슨 동물일까요?", options=["뱀", "고양이"]),
        _raw(question="무슨 음식일까요?", options=["맥주", "피자"]),
        _raw(options=["아주 맛있는 이탈리아 피자", "햄버거"]),  # 보기가 한두 단어를 넘음
        _raw(options=["피자", "피자"]),
        _raw(answer_index=5),
    ],
)
def test_make_question_rejects_bad(monkeypatch, bad):
    _fake_llm(monkeypatch, bad)
    with pytest.raises(auto_ai.Rejected):
        auto_ai.make_question(_jpeg())


@pytest.mark.parametrize(
    "good",
    [
        _raw(),
        _raw(question="무슨 과일일까요?", options=["사과", "배"]),
        _raw(question="무슨 꽃일까요?", options=["장미", "튤립", "벚꽃"]),
        _raw(question="무슨 동물일까요?", options=["다람쥐", "토끼"]),
        _raw(question="어디일까요?", options=["공원", "바다"]),
        _raw(question="어느 계절 같아요?", options=["봄", "가을"]),
        _raw(question="무엇일까요?", options=["우산", "가방"]),
    ],
)
def test_make_question_accepts_good(monkeypatch, good):
    _fake_llm(monkeypatch, good)
    assert auto_ai.make_question(_jpeg()).usable


def test_prompt_mentions_rules():
    p = auto_ai.SYSTEM + auto_ai.prompt()
    for word in ("뱀", "국화", "글자", "색"):
        assert word in p


def test_one_photo_per_search_query_per_run(client):
    """같은 검색어에서는 한 번에 한 장만 받는다(같은 소재 3장이 몰리지 않게)."""
    fetch = FakeFetch([_hit(i) for i in range(1, 30)])
    result = _run(fetch)
    assert result.added == 3
    assert len(fetch.searches) == len(set(fetch.searches)) == 3


def test_httpx_request_log_is_silenced_so_key_is_not_logged():
    import logging

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
