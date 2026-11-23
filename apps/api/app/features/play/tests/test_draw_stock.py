"""이게 뭐게 추천의 단어별 그림 저장소: 기간 제한 없이 재사용, 단어당 3종, 단어마다 따로."""

from datetime import UTC, datetime, timedelta

from app.features.play import draw_stock
from app.shared.db import SessionLocal

NOW = datetime(2026, 11, 18, 3, 0, tzinfo=UTC)
STROKES = [[[0, 0], [10, 10]], [[5, 5], [20, 5]], [[1, 1], [2, 200]]]


def add(db, word, days_ago):
    return draw_stock.add_variant(db, word, STROKES, NOW - timedelta(days=days_ago))


def test_stock_variants_keep_old_pictures(client):
    with SessionLocal() as db:
        old = add(db, "케이크", 100)
        fresh = add(db, "케이크", 29)
        assert [v.id for v in draw_stock.stock_variants(db, "케이크", NOW)] == [old.id, fresh.id]


def test_stock_variants_are_oldest_first_and_keep_strokes(client):
    with SessionLocal() as db:
        newer = add(db, "케이크", 1)
        older = add(db, "케이크", 5)
        got = draw_stock.stock_variants(db, "케이크", NOW)
        assert [v.id for v in got] == [older.id, newer.id]
        assert got[0].strokes == STROKES


def test_add_variant_replaces_oldest_when_full(client):
    with SessionLocal() as db:
        oldest = add(db, "케이크", 10)
        mid = add(db, "케이크", 5)
        new = add(db, "케이크", 2)
        assert len(draw_stock.stock_variants(db, "케이크", NOW)) == draw_stock.STOCK_MAX == 3
        latest = add(db, "케이크", 0)
        ids = [v.id for v in draw_stock.stock_variants(db, "케이크", NOW)]
        assert ids == [mid.id, new.id, latest.id]
        assert oldest.id not in ids


def test_add_variant_only_replaces_the_oldest_when_full(client):
    with SessionLocal() as db:
        oldest = add(db, "케이크", 40)
        second = add(db, "케이크", 35)
        third = add(db, "케이크", 33)
        fresh = add(
            db, "케이크", 0
        )  # 오래돼도 지우지 않고, 3종이 넘을 때만 가장 오래된 것이 대체된다
        ids = [v.id for v in draw_stock.stock_variants(db, "케이크", NOW)]
        assert ids == [second.id, third.id, fresh.id] and oldest.id not in ids


def test_other_words_are_separate(client):
    with SessionLocal() as db:
        cake = add(db, "케이크", 1)
        berry = add(db, "딸기", 1)
        assert [v.id for v in draw_stock.stock_variants(db, "케이크", NOW)] == [cake.id]
        assert [v.id for v in draw_stock.stock_variants(db, "딸기", NOW)] == [berry.id]
        assert draw_stock.stock_variants(db, "텐트", NOW) == []
