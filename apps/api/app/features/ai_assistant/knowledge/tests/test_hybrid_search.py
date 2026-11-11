"""문서 검색 섞기(임베딩 후보 + 글자 TF-IDF, RRF): 순서, 필터 유지, 설정 끔, 빈 결과, 조사가 붙은 낱말."""

import pytest

from app.features.ai_assistant.knowledge import hybrid, service
from app.features.ai_assistant.knowledge import repository as repo
from app.shared.config import settings
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")


def _add(client, headers, **kw):
    r = client.post("/ai-assistant/knowledge/items", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_fuse_order_lifts_the_record_that_shares_the_words():
    # 임베딩 순서는 A, B, C. 글자는 B 가 가장 겹치고 A 는 하나도 겹치지 않는다
    texts = ["오늘 날씨가 맑습니다", "배수필터 청소 방법과 주기", "필터 교체 안내"]
    order = hybrid.fuse_order("배수필터 청소", texts)
    assert order[0] == 1 and sorted(order) == [0, 1, 2]


def test_fuse_order_keeps_embedding_order_without_any_shared_text():
    assert hybrid.fuse_order("zzz", ["가나다", "라마바"]) == [0, 1]
    assert hybrid.fuse_order("", ["가나다"]) == [0]
    assert hybrid.fuse_order("질문", []) == []


def test_korean_particles_do_not_hide_a_word_match():
    texts = ["세탁기가 멈췄을 때", "냉장고 문이 열렸을 때"]
    scores = hybrid.tfidf_scores("세탁기를 어떻게 청소해요", texts)
    assert scores[0] > scores[1] == 0.0  # '세탁기를' 과 '세탁기가' 는 '세탁', '탁기' 묶음이 겹친다


def _embedding_order(monkeypatch, *title_parts):
    """임베딩 순서(점수는 그대로)를 title_parts 에 든 제목 순서로 바꾼다."""
    real = repo.search_chunks

    def search(*a, **k):
        rows = real(*a, **k)
        rows.sort(key=lambda r: next(i for i, t in enumerate(title_parts) if t in r[1].title))
        return rows

    monkeypatch.setattr(service.repo, "search_chunks", search)


@pytest.fixture
def docs(client, family):
    a, _, group = family
    _add(client, a, kind_label="고지서", title="전기요금", body_md="# 전기요금\n- 사용량 300kWh")
    _add(client, a, kind_label="고지서", title="가스요금", body_md="# 가스요금\n- 사용량 20㎥ 청소")
    _add(
        client,
        a,
        kind_label="설명서",
        title="세탁기 설명서",
        body_md="# 세탁기 설명서\n[p.1]\n배수필터는 한 달에 한 번 청소합니다.",
    )
    return a, group


def test_hybrid_reorders_embedding_candidates_and_keeps_embedding_score(docs, monkeypatch):
    _, group = docs
    _embedding_order(monkeypatch, "전기", "세탁기", "가스")
    with SessionLocal() as db:
        monkeypatch.setattr(settings, "chat_hybrid_search", True)
        mixed = service.search(db, group["id"], "배수필터 청소", top_k=3)
        monkeypatch.setattr(settings, "chat_hybrid_search", False)
        plain = service.search(db, group["id"], "배수필터 청소", top_k=3)
    assert mixed[0].item.title == "세탁기 설명서"
    assert {h.item.id for h in mixed} == {h.item.id for h in plain}
    by_id = {h.item.id: h.score for h in plain}
    assert all(abs(h.score - by_id[h.item.id]) < 1e-9 for h in mixed)  # 점수는 임베딩 코사인 그대로


def test_hybrid_off_is_the_old_score_order_and_skips_the_mixing(docs, monkeypatch):
    _, group = docs
    monkeypatch.setattr(settings, "chat_hybrid_search", False)
    monkeypatch.setattr(hybrid, "fuse_order", lambda *a, **k: pytest.fail("섞기를 부르면 안 된다"))
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수필터 청소", top_k=3)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_false_argument_overrides_the_setting(docs, monkeypatch):
    _, group = docs
    monkeypatch.setattr(settings, "chat_hybrid_search", True)
    monkeypatch.setattr(hybrid, "fuse_order", lambda *a, **k: pytest.fail("섞기를 부르면 안 된다"))
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수필터 청소", top_k=1, hybrid=False)
    assert len(hits) == 1


def test_filters_still_apply_when_mixing(docs, monkeypatch):
    _, group = docs
    _embedding_order(monkeypatch, "전기", "세탁기", "가스")
    with SessionLocal() as db:
        only_bills = service.search(db, group["id"], "배수필터 청소", top_k=5, kind_label="고지서")
        assert {h.item.kind_label for h in only_bills} == {"고지서"}
        none = service.search(db, group["id"], "배수필터", family_user_ids=[])
        assert none == []  # 가족 필터가 비면 결과 없음
        other = service.search(db, "다른그룹", "배수필터 청소")
        assert other == []


def test_sensitive_records_stay_hidden_when_excluded(client, family, monkeypatch):
    a, _, group = family
    _add(
        client,
        a,
        kind_label="처방전",
        title="엄마 처방전",
        body_md="# 엄마 처방전\n- 배수필터 약",
        sensitivity="sensitive",
    )
    _add(client, a, kind_label="고지서", title="수도", body_md="# 수도\n- 배수필터 요금")
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수필터", include_sensitive=False)
    assert [h.item.title for h in hits] == ["수도"]


def test_empty_index_and_per_item_chunks_with_mixing(client, family):
    a, _, group = family
    with SessionLocal() as db:
        assert service.search(db, group["id"], "아무거나") == []
    _add(
        client,
        a,
        kind_label="설명서",
        title="설명서",
        body_md="# 설명서\n"
        + "\n".join(
            f"[p.{n}]\n{n}쪽 {w} 안내 " + "내용이 이어집니다. " * 8
            for n, w in enumerate(["전원", "배수필터", "보증"], 1)
        ),
    )
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수필터", top_k=3, per_item=3)
    assert len(hits) == 1 and len(hits[0].more) == 2
    assert hits[0].chunk.page_label == "p.2"  # 낱말이 든 쪽이 대표 조각
