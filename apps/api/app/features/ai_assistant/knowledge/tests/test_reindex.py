"""임베딩 재색인(T12 PR-1): 모델 이름 예측, 배치·이어하기, 점검 스크립트. 외부 호출 없이 SQLite 에서 본다."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.features.ai_assistant.knowledge import embedding, service
from app.features.ai_assistant.knowledge import repository as repo
from app.features.ai_assistant.knowledge.embedding import OnnxE5Embedder
from app.features.ai_assistant.knowledge.models import KnowledgeChunk, KnowledgeItem
from app.shared.db import SessionLocal

SECRET_TEXT = "비밀본문-조각"
GROUP = "grp-secret-id-0001"


class FakeEmbedder:
    """호출 기록을 남기는 가짜 임베더. fail_on_call 번째 호출(1부터)에서 예외를 낸다."""

    dim = 3

    def __init__(self, name: str = "new-model", fail_on_call: int | None = None) -> None:
        self.name = name
        self.calls: list[int] = []
        self.fail_on_call = fail_on_call

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError(f"모델 오류 {SECRET_TEXT}")
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class FakeOnnx(OnnxE5Embedder):
    """isinstance(OnnxE5Embedder) 를 통과하는 가짜(실제 모델 파일 없이)."""

    dim = 384

    def __init__(self, name: str = "onnx-e5-small-ft", fail_on_call: int | None = None) -> None:
        self.name = name
        self.calls: list[int] = []
        self.fail_on_call = fail_on_call

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError(f"모델 오류 {SECRET_TEXT}")
        return [[1.0, 0.0, 0.0] for _ in texts]


def _seed(db, n: int, model: str = "old-model", group: str = GROUP, tag: str = "a") -> list[int]:
    """기록 n 개, 각 1조각. 조각 id 목록을 돌려준다."""
    ids = []
    for i in range(n):
        item = KnowledgeItem(
            group_id=group, created_by="u", kind_label="k", title=f"{tag}{i}", body_md="x"
        )
        db.add(item)
        db.flush()
        chunk = KnowledgeChunk(
            item_id=item.id,
            group_id=group,
            seq=0,
            text=f"{SECRET_TEXT}{tag}{i}",
            embedding=[0.0, 0.0, 1.0],
            embedding_model=model,
        )
        db.add(chunk)
        db.flush()
        ids.append(chunk.id)
    db.commit()
    return ids


def _models(db) -> dict[str, int]:
    rows = db.execute(
        select(KnowledgeChunk.embedding_model, func.count()).group_by(
            KnowledgeChunk.embedding_model
        )
    ).all()
    return {m: c for m, c in rows}


@pytest.fixture(autouse=True)
def _restore_embedder():
    old = embedding._embedder
    yield
    embedding.set_embedder(old)


# ---- expected_model_name ----


def test_expected_model_name_hashing_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBED_MODEL_DIR", str(tmp_path / "none"))
    embedding.set_embedder(None)
    assert embedding.expected_model_name() == "hashing-512"
    assert embedding.get_embedder().name == "hashing-512"


def test_expected_model_name_follows_folder_name(monkeypatch, tmp_path):
    folder = tmp_path / "my-model-v2"
    folder.mkdir()
    (folder / "model.onnx").write_bytes(b"x")
    monkeypatch.setenv("EMBED_MODEL_DIR", str(folder))
    assert embedding.expected_model_name() == "onnx-my-model-v2"

    # get_embedder 와 같은 폴더 결정을 쓰는지: 가짜 Onnx 임베더로 이름 규칙을 맞춰 본다
    class Fake(FakeOnnx):
        def __init__(self, model_dir: Path) -> None:
            super().__init__(f"onnx-{model_dir.name}")

    monkeypatch.setattr(embedding, "OnnxE5Embedder", Fake)
    embedding.set_embedder(None)
    assert embedding.get_embedder().name == embedding.expected_model_name()


def test_expected_model_name_default_folder(monkeypatch, tmp_path):
    from app.shared.config import settings

    monkeypatch.delenv("EMBED_MODEL_DIR", raising=False)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    assert embedding.expected_model_name() == "hashing-512"
    folder = tmp_path / "models" / "e5-small-ft"
    folder.mkdir(parents=True)
    (folder / "model.onnx").write_bytes(b"x")
    assert embedding.expected_model_name() == "onnx-e5-small-ft"


# ---- repository ----


def test_count_stale_and_keyset(client):
    with SessionLocal() as db:
        ids = _seed(db, 5) + _seed(db, 2, model="new-model", tag="b")
        _seed(db, 3, group="other", tag="c")
        assert repo.count_stale(db, "new-model") == 8
        assert repo.count_stale(db, "new-model", GROUP) == 5
        assert repo.count_stale(db, "old-model") == 2
        page = repo.stale_chunks(db, "new-model", GROUP, limit=2)
        assert [c.id for c in page] == ids[:2]
        nxt = repo.stale_chunks(db, "new-model", GROUP, after_id=page[-1].id, limit=10)
        assert [c.id for c in nxt] == ids[2:5]
        assert len(repo.stale_chunks(db, "new-model", GROUP)) == 5  # 기본 호출은 기존과 같다


def test_count_by_model_and_items(client):
    with SessionLocal() as db:
        _seed(db, 3)
        _seed(db, 1, model="new-model", tag="b")
        # 한 기록에 새 조각 + 옛 조각이 섞인 경우: 영향은 받지만 검색에서 완전히 빠지지는 않는다
        item = db.scalars(select(KnowledgeItem).where(KnowledgeItem.title == "b0")).one()
        db.add(
            KnowledgeChunk(
                item_id=item.id,
                group_id=GROUP,
                seq=1,
                text="mix",
                embedding=[0.0],
                embedding_model="old-model",
            )
        )
        db.commit()
        assert repo.count_by_model(db) == {"old-model": 4, "new-model": 1}
        assert repo.count_stale_items(db, "new-model") == 4
        assert repo.count_items_missing_model(db, "new-model") == 3


# ---- reindex ----


def test_reindex_batches_return_count_and_progress(client):
    with SessionLocal() as db:
        _seed(db, 7)
        emb = FakeEmbedder()
        embedding.set_embedder(emb)
        seen: list[tuple[int, int]] = []
        n = service.reindex(db, GROUP, batch_size=3, on_progress=lambda d, t: seen.append((d, t)))
        assert n == 7
        assert emb.calls == [3, 3, 1]
        assert seen == [(3, 7), (6, 7), (7, 7)]
        assert _models(db) == {"new-model": 7}
        row = db.scalars(select(KnowledgeChunk)).first()
        assert row.embedding == [1.0, 0.0, 0.0]


def test_reindex_without_batch_size_does_everything_at_once(client):
    with SessionLocal() as db:
        _seed(db, 5)
        emb = FakeEmbedder()
        embedding.set_embedder(emb)
        assert service.reindex(db) == 5
        assert emb.calls == [5]


def test_reindex_idempotent_when_nothing_stale(client):
    with SessionLocal() as db:
        _seed(db, 2, model="new-model")
        emb = FakeEmbedder()
        embedding.set_embedder(emb)
        assert service.reindex(db, batch_size=2) == 0
        assert emb.calls == []
        assert _models(db) == {"new-model": 2}


def test_reindex_failed_batch_keeps_earlier_and_resumes(client):
    with SessionLocal() as db:
        _seed(db, 7)
        emb = FakeEmbedder(fail_on_call=2)
        embedding.set_embedder(emb)
        with pytest.raises(RuntimeError):
            service.reindex(db, batch_size=3)
        assert _models(db) == {"new-model": 3, "old-model": 4}  # 앞 배치만 반영
        emb2 = FakeEmbedder()
        embedding.set_embedder(emb2)
        assert service.reindex(db, batch_size=3) == 4  # 남은 것만
        assert emb2.calls == [3, 1]
        assert _models(db) == {"new-model": 7}


def test_reindex_survives_chunks_deleted_midway(client):
    with SessionLocal() as db:
        ids = _seed(db, 6)

        class Deleting(FakeEmbedder):
            def embed_passages(self, texts):
                out = super().embed_passages(texts)
                if len(self.calls) == 1:  # 첫 배치를 임베딩하는 사이 다른 곳에서 한 조각이 지워졌다
                    with SessionLocal() as other:
                        other.query(KnowledgeChunk).filter(KnowledgeChunk.id == ids[1]).delete()
                        other.commit()
                return out

        embedding.set_embedder(Deleting())
        n = service.reindex(db, batch_size=3)
        assert n == 5  # 지워진 한 행은 0행 갱신으로 넘어간다
        assert _models(db) == {"new-model": 5}


def test_reindex_limit_and_bad_batch_size(client):
    with SessionLocal() as db:
        _seed(db, 5)
        embedding.set_embedder(FakeEmbedder())
        assert service.reindex(db, batch_size=2, limit=3) == 3
        assert _models(db) == {"new-model": 3, "old-model": 2}
        with pytest.raises(ValueError):
            service.reindex(db, batch_size=0)


# ---- 스크립트 ----


def _run(argv):
    from scripts.reindex_embeddings import main

    return main(argv)


def test_script_check_prints_counts_only(client, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("EMBED_MODEL_DIR", str(tmp_path / "none"))
    embedding.set_embedder(None)
    with SessionLocal() as db:
        _seed(db, 4, model="onnx-old-name")
        _seed(db, 2, model="hashing-512", tag="b")
    assert _run([]) == 0  # 기본은 --check
    out = capsys.readouterr().out
    assert "hashing-512: 2" in out and "onnx-old-name: 4" in out
    assert "현재 모델과 다른 조각: 4" in out and "영향받는 기록: 4" in out
    assert "의미 검색에서 완전히 빠진 기록: 4" in out
    assert SECRET_TEXT not in out and GROUP not in out
    with SessionLocal() as db:  # 읽기 전용
        assert _models(db) == {"onnx-old-name": 4, "hashing-512": 2}
        ids = [str(i) for i in db.scalars(select(KnowledgeItem.id))]
    assert not any(i in out for i in ids)


def test_script_apply_refuses_hashing_embedder(client, capsys):
    embedding.set_embedder(FakeEmbedder("hashing-512"))
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--apply", "--yes"]) == 1
    assert "ONNX" in capsys.readouterr().out
    with SessionLocal() as db:
        assert _models(db) == {"old-model": 2}


def _forbid_get_embedder(monkeypatch):
    def boom():
        raise AssertionError("get_embedder 를 부르면 안 돼요")

    monkeypatch.setattr(embedding, "get_embedder", boom)


def test_script_check_never_loads_the_model(client, capsys, monkeypatch):
    _forbid_get_embedder(monkeypatch)
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--check"]) == 0
    assert "현재 설정의 모델 이름" in capsys.readouterr().out


def test_script_apply_without_yes_exits_2_before_loading_model(client, capsys, monkeypatch):
    _forbid_get_embedder(monkeypatch)
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--apply"]) == 2
    assert "--yes" in capsys.readouterr().out
    with SessionLocal() as db:
        assert _models(db) == {"old-model": 2}


def test_script_apply_warns_to_match_server_settings(client, capsys):
    embedding.set_embedder(FakeOnnx())
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--apply", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "서버와 같은 설정에서 실행하는지 확인하세요" in out
    assert out.index("서버와 같은 설정") < out.index("reindex 2/2")  # 재계산 전에 경고한다


def test_script_warns_when_model_folder_missing_on_postgres_only():
    from scripts.reindex_embeddings import model_warnings

    assert any(
        "모델 폴더를 찾지 못했어요" in w for w in model_warnings("postgresql", "hashing-512")
    )
    assert model_warnings("postgresql", "onnx-e5-small-ft") == []
    assert model_warnings("sqlite", "hashing-512") == []  # SQLite 는 해시 임베더도 정상


def test_script_check_has_no_folder_warning_on_sqlite(client, capsys):
    assert _run(["--check"]) == 0  # 시험 환경은 모델 폴더가 없지만 SQLite 라 경고하지 않는다
    assert "모델 폴더를 찾지 못했어요" not in capsys.readouterr().out


def test_script_apply_runs_with_progress_and_is_idempotent(client, capsys):
    embedding.set_embedder(FakeOnnx())
    with SessionLocal() as db:
        _seed(db, 5)
    assert _run(["--apply", "--yes", "--batch-size", "2"]) == 0
    out = capsys.readouterr().out
    assert "reindex 2/5 (40%)" in out and "reindex 5/5 (100%)" in out
    assert SECRET_TEXT not in out and GROUP not in out
    with SessionLocal() as db:
        assert _models(db) == {"onnx-e5-small-ft": 5}
    assert _run(["--apply", "--yes"]) == 0  # 다시 실행해도 할 일이 없다
    assert "다시 만들 조각이 없어요" in capsys.readouterr().out


def test_script_apply_limit_and_group(client, capsys):
    embedding.set_embedder(FakeOnnx())
    with SessionLocal() as db:
        _seed(db, 4)
        _seed(db, 2, group="other", tag="b")
    assert _run(["--apply", "--yes", "--group-id", GROUP, "--limit", "3"]) == 0
    capsys.readouterr()
    with SessionLocal() as db:
        assert _models(db) == {"onnx-e5-small-ft": 3, "old-model": 3}


def test_script_failure_prints_class_name_only(client, capsys):
    embedding.set_embedder(FakeOnnx(fail_on_call=2))
    with SessionLocal() as db:
        _seed(db, 5)
    assert _run(["--apply", "--yes", "--batch-size", "2"]) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert "RuntimeError" in text
    assert SECRET_TEXT not in text and "모델 오류" not in text and GROUP not in text
    with SessionLocal() as db:
        assert _models(db) == {"onnx-e5-small-ft": 2, "old-model": 3}  # 앞 배치는 유지
