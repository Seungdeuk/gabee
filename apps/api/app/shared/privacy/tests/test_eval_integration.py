"""통합 평가 스크립트(scripts/eval_integration.py)의 지표 계산 단위 시험(합성 입력)."""

import importlib.util
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(API_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "eval_integration_under_test", API_ROOT / "scripts" / "eval_integration.py"
)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_integration_under_test"] = ev
_spec.loader.exec_module(ev)


def _row(text, spans):
    return {
        "id": "t1",
        "text": text,
        "spans": [
            {"kind": k, "start": s, "end": e, "mask_default": md, "context_sensitive": False}
            for k, s, e, md in spans
        ],
        "known_names": [],
        "tags": ["x"],
        "template_id": "t",
        "split": "test",
    }


def test_exact_overlap_and_residual():
    row = _row("김민수 010-0000-1234", [("PERSON", 0, 3, True), ("PHONE_PERSONAL", 4, 17, True)])
    preds = [
        {"kind": "PERSON", "start": 0, "end": 2},
        {"kind": "PHONE_PERSONAL", "start": 4, "end": 17},
    ]
    rec = ev.score_row(row, preds)
    assert rec["counts"]["fine"]["exact"]["PERSON"]["tp"] == 0
    assert rec["counts"]["fine"]["overlap"]["PERSON"]["tp"] == 1
    assert rec["counts"]["fine"]["exact"]["PHONE_PERSONAL"]["tp"] == 1
    res = rec["residual"]
    assert (res["full"], res["partial"], res["none"], res["left_chars"]) == (1, 1, 0, 1)
    pol = ev.agg_policy([rec])
    assert pol["protect_recall"] == 1.0


def test_negative_sentence_fpr():
    neg = ev.score_row(_row("안녕", []), [{"kind": "LOCATION", "start": 0, "end": 2}])
    fpr = ev.agg_fpr([neg])
    assert fpr["fpr_any"] == 1.0 and fpr["fpr_excl_location_org"] == 0.0
