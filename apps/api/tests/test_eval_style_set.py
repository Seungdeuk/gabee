import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_style_set import main, ner_only_predict, score_rows  # noqa: E402

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.ner import NerResult, NerSpan  # noqa: E402
from app.shared.privacy.types import Kind, Span  # noqa: E402


class _StubEngine:
    """ner.ner_status()/detect_with_ner 가 쓰는 만큼만 구현한 가짜 엔진(모델 파일 불필요)."""

    fingerprint = "deadbeefcafe"
    max_chars = 10000

    def analyze_many(self, texts, deadline=None):
        return [NerResult((NerSpan("PERSON", 0, 2, 0.9),)) if t else NerResult(()) for t in texts]


def test_score_rows_counts_full_partial_none():
    rows = [
        {
            "category": "가족대화",
            "text": "김철수가 왔어",
            "spans": [{"kind": "PERSON", "start": 0, "end": 3}],
            "known_names": [],
        }
    ]

    def predict_full(text, known):
        return [Span(Kind.PERSON, 0, 3, 0.9, "ner")]

    out = score_rows(rows, predict_full)
    assert out["categories"]["가족대화"]["full"] == 1
    assert out["categories"]["가족대화"]["none"] == 0


def test_score_rows_counts_extra_false_positive_spans():
    """정답 구간과 전혀 겹치지 않는 예측 구간은(같은 문장에 추가로 나온 것) extra 로 센다."""
    rows = [
        {
            "category": "가족대화",
            "text": "김철수가 왔어",
            "spans": [{"kind": "PERSON", "start": 0, "end": 3}],
            "known_names": [],
        }
    ]

    def predict_with_fp(text, known):
        return [
            Span(Kind.PERSON, 0, 3, 0.9, "ner"),  # 정답과 일치
            Span(Kind.PERSON, 5, 6, 0.9, "ner"),  # "왔" — 정답과 안 겹침(과잉 예측)
        ]

    out = score_rows(rows, predict_with_fp)
    assert out["categories"]["가족대화"]["extra"] == 1


@pytest.fixture(autouse=True)
def _reset_ner_state():
    ner.reset()
    yield
    ner.reset()


def test_eval_style_set_rejects_inactive_ner(monkeypatch, tmp_path):
    # settings 는 import 시점에 한 번 만들어져 공유되므로, os.environ 이 아니라 settings 자체를 되돌려야
    # 테스트가 끝난 뒤 다른 시험에 영향을 주지 않는다(monkeypatch 가 "처음 본" 값으로 복원한다).
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", settings.privacy_ner_model_dir)
    monkeypatch.setattr(settings, "privacy_ner_threads", settings.privacy_ner_threads)
    evalset = tmp_path / "e.jsonl"
    evalset.write_text(
        '{"text": "x", "spans": [], "known_names": [], "category": "비인명"}\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        main([str(evalset), str(tmp_path / "missing-model-dir"), str(tmp_path / "out.json")])
    # required 모드로 바뀐 뒤에 막힌 것이어야 한다(꺼짐 상태로 그냥 지나간 게 아니라).
    assert settings.privacy_ner_mode == "required"


def test_ner_only_predict_ignores_rule_only_detections(monkeypatch):
    """로드맵 4단계: NER 단독은 규칙(known_names 사전)만으로 잡히는 것을 보면 안 된다."""
    monkeypatch.setattr(ner, "spans_for", lambda text: [])  # NER 은 아무것도 못 찾음
    spans = ner_only_predict("김철수가 왔어", ("김철수",))
    assert spans == []


def test_ner_only_predict_runs_ner_spans_through_merge_ner(monkeypatch):
    """NER 이 실제로 찾은 것은(규칙 없이도) 그대로 나온다 — detect_with_ner 와 같은 정리(merge_ner)를 거친다."""
    monkeypatch.setattr(ner, "spans_for", lambda text: [NerSpan("PERSON", 0, 3, 0.9)])
    spans = ner_only_predict("김철수가 왔어", ())
    assert len(spans) == 1
    assert spans[0].kind is Kind.PERSON
    assert (spans[0].start, spans[0].end) == (0, 3)


class _EmptyStubEngine:
    """NER 이 항상 아무것도 못 찾는 가짜 엔진(규칙만으로 잡히는지 보는 대조용)."""

    fingerprint = "emptyengine0"
    max_chars = 10000

    def analyze_many(self, texts, deadline=None):
        return [NerResult(()) for _ in texts]


def test_eval_style_set_ner_only_flag_bypasses_rule_matches(monkeypatch, tmp_path):
    """--ner-only 면 known_names 사전(규칙)만으로 잡히는 이름은 "none"(누출)으로 남아야 한다."""
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", settings.privacy_ner_model_dir)
    monkeypatch.setattr(settings, "privacy_ner_threads", settings.privacy_ner_threads)
    monkeypatch.setattr(ner, "_load_engine", lambda cfg: _EmptyStubEngine())
    evalset = tmp_path / "e.jsonl"
    evalset.write_text(
        '{"text": "김철수가 왔어", "spans": [{"kind": "PERSON", "start": 0, "end": 3}], '
        '"known_names": ["김철수"], "category": "가족대화"}\n',
        encoding="utf-8",
    )
    out_path = tmp_path / "out.json"
    main([str(evalset), str(tmp_path / "fake-model-dir"), str(out_path), "--ner-only"])

    import json

    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["categories"]["가족대화"]["full"] == 0
    assert out["categories"]["가족대화"]["none"] == 1


def test_eval_style_set_records_fingerprint_for_active_model(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", settings.privacy_ner_model_dir)
    monkeypatch.setattr(settings, "privacy_ner_threads", settings.privacy_ner_threads)
    monkeypatch.setattr(ner, "_load_engine", lambda cfg: _StubEngine())
    evalset = tmp_path / "e.jsonl"
    evalset.write_text(
        '{"text": "김철수가 왔어", "spans": [{"kind": "PERSON", "start": 0, "end": 3}], '
        '"known_names": [], "category": "가족대화"}\n',
        encoding="utf-8",
    )
    out_path = tmp_path / "out.json"
    main([str(evalset), str(tmp_path / "fake-model-dir"), str(out_path)])

    import json

    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["ner_status"]["mode"] == "required"
    assert out["ner_status"]["fingerprint"] == "deadbeefcafe"
    assert out["mode"] == "fake-model-dir"  # 전체 경로가 아니라 폴더 이름만 기록한다
