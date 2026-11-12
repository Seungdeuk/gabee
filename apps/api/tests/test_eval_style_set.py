import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.shared.privacy.types import Kind, Span  # noqa: E402
from eval_style_set import main, score_rows  # noqa: E402


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


def test_eval_style_set_rejects_inactive_ner(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIVACY_NER_MODE", "off")
    evalset = tmp_path / "e.jsonl"
    evalset.write_text(
        '{"text": "x", "spans": [], "known_names": [], "category": "비인명"}\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        main([str(evalset), str(tmp_path / "missing-model-dir"), str(tmp_path / "out.json")])
