"""실험 B — 병합 개선: R6 모델은 그대로 두고, **평가 환경에서만** BIO 디코딩 규칙을 완화해
PERSON/PERSON_ALIAS 를 같은 묶음으로 이어붙인 뒤(둘 다 `LABEL_TO_KIND`에서 Kind.PERSON으로
합류하므로 마스킹 결과는 같다) 기존 `merge_ner`(운영 코드, 미수정)에 그대로 넣어 최종 결과를
비교한다. `ner.py`/`detectors.py`는 import 만 하고 전혀 수정하지 않는다 — 디코딩만 이 스크립트
안에서 사본으로 바꾼다. 운영 모델 파일·DB·설정 미수정, 재학습 없음, 외부 LLM 미호출.

완화 규칙: 토큰 태그가 "I-PERSON" 또는 "I-PERSON_ALIAS"이고 현재 열린 구간의 라벨이
{PERSON, PERSON_ALIAS} 중 하나면 그대로 이어붙인다(기존은 라벨 문자열이 정확히 같아야만 이어짐).
병합된 구간의 최종 라벨은 "PERSON"으로 통일한다(어차피 Kind.PERSON으로 합류하므로 구분 의미 없음).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import detectors, ner  # noqa: E402
from app.shared.privacy.ner import NerSpan as NerSpanLike  # noqa: E402
from app.shared.privacy.types import Kind, Span  # noqa: E402

PERSON_GROUP = {"PERSON", "PERSON_ALIAS"}


class TokenInspector:
    def __init__(self, model_dir: str):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = Path(model_dir)
        self.tk = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tk.no_truncation()
        self.tk.no_padding()
        meta = json.loads((d / "labels.json").read_text(encoding="utf-8"))
        self.id2label = {int(k): v for k, v in meta["id2label"].items()}
        self.cls_id = int(meta["cls_token_id"])
        self.sep_id = int(meta["sep_token_id"])
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(d / "model.onnx"), so, providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.sess.get_inputs()}

    def token_predictions(self, text: str):
        import numpy as np

        if not text:
            return []
        enc = self.tk.encode(text)
        keep = [i for i, m in enumerate(enc.special_tokens_mask) if not m]
        ids = [enc.ids[i] for i in keep]
        offs = [enc.offsets[i] for i in keep]
        if not ids:
            return []
        seq = [self.cls_id, *ids, self.sep_id]
        input_ids = np.array([seq], dtype=np.int64)
        mask = np.ones_like(input_ids)
        feed = {"input_ids": input_ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        logits = self.sess.run(None, feed)[0][0][1:-1]
        shifted = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(shifted)
        probs /= probs.sum(axis=1, keepdims=True)
        pred = probs.argmax(axis=1)
        out = []
        for i in range(len(ids)):
            tag = self.id2label.get(int(pred[i]), "O")
            out.append((offs[i][0], offs[i][1], tag, float(probs[i, pred[i]])))
        return out


def decode_relaxed(token_preds):
    """기존 ner.py `_decode`와 같은 틀이지만, PERSON/PERSON_ALIAS 를 한 묶음으로 본다."""
    spans = []
    cur = None  # (group_or_label, start, end, [probs])

    def close():
        nonlocal cur
        if cur is None:
            return
        label, s, e, ps = cur
        cur = None
        spans.append((label, s, e, sum(ps) / len(ps)))

    for cs, ce, tag, p in token_preds:
        if tag == "O" or ce <= cs:
            close()
            continue
        prefix, _, label = tag.partition("-") if tag[:2] in ("B-", "I-") else ("I", "", tag)
        cur_group = cur[0] if cur else None
        same_group = label in PERSON_GROUP and cur_group in PERSON_GROUP
        continues = (prefix == "I") and cur is not None and (cur_group == label or same_group)
        if continues:
            merged_label = "PERSON" if same_group else label
            cur = (merged_label, cur[1], ce, [*cur[3], p])
        else:
            close()
            cur = (label, cs, ce, [p])
    close()
    return spans


def to_nerspans(relaxed, text):
    return [NerSpanLike(label, s, e, score) for label, s, e, score in relaxed]


def gold_span(row):
    for sp in row.get("spans", []):
        if sp.get("kind") in ("PERSON", "PERSON_ALIAS"):
            return sp["start"], sp["end"]
    return None


def covered(preds, g):
    cov = set()
    for s in preds:
        if s.kind is Kind.PERSON:
            cov.update(range(max(s.start, g[0]), min(s.end, g[1])))
    return cov


def eval_rows(rows, insp, known_names=()):
    tp = fp = fn = 0
    full_exp = part_exp = full_mask = 0
    neg_total = neg_flagged = 0
    full_cases = []
    for r in rows:
        text = r["text"]
        g = gold_span(r)
        token_preds = insp.token_predictions(text)
        relaxed_raw = decode_relaxed(token_preds)
        ner_spans = to_nerspans(relaxed_raw, text)
        rule = detectors.detect(text, known_names)
        final = ner.merge_ner(text, rule, ner_spans)
        final_person = [(s.start, s.end) for s in final if s.kind is Kind.PERSON]
        if g is not None:
            n = g[1] - g[0]
            exact = g in final_person
            tp += int(exact)
            fn += int(not exact)
            fp += sum(1 for p in final_person if p != g)
            leaked = n - len(covered(final, g))
            full = leaked >= n
            if full:
                full_exp += 1
                full_cases.append({"id": r["id"], "word": r.get("word"), "text": text})
            elif leaked > 0:
                part_exp += 1
            else:
                full_mask += 1
        else:
            neg_total += 1
            neg_flagged += int(bool(final_person))
    n_pos = full_exp + part_exp + full_mask
    p = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * rec / (p + rec)) if p and rec and (p + rec) else None
    return {
        "pos": n_pos, "neg": neg_total, "precision": p, "recall": rec, "f1": f1,
        "full_exposure": full_exp, "partial_exposure": part_exp, "fully_masked": full_mask,
        "full_exposure_rate": round(full_exp / n_pos, 4) if n_pos else None,
        "total_exposure_rate": round((full_exp + part_exp) / n_pos, 4) if n_pos else None,
        "nonperson_fpr": round(neg_flagged / neg_total, 4) if neg_total else None,
        "full_exposure_cases": full_cases,
    }


def load_rows(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--r6-candidate", required=True)
    ap.add_argument("--expect-fp12", default="c59b174ba126", help="모델 지문 검증(기본: R6 seed42)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    ROOT_EVAL = ROOT / "app" / "shared" / "privacy" / "eval"
    DATASETS = {
        "v12_locked": ROOT_EVAL / "style_v12_locked" / "v12_locked.jsonl",
        "v10_locked": ROOT_EVAL / "style_v10_locked" / "v10_locked.jsonl",
        "v11_locked": ROOT_EVAL / "style_v11_locked" / "v11_locked.jsonl",
        "v9_locked": ROOT_EVAL / "style_v9_locked" / "v9_locked.jsonl",
        "ambiguity_probe_48": ROOT_EVAL / "style_ambiguity_probe" / "ambiguity_probe.jsonl",
        "draft56": ROOT_EVAL / "step2_synth_draft" / "synth_draft.jsonl",
        "v8_independent": ROOT_EVAL / "style_v8_independent" / "v8_independent.jsonl",
        "r3_heldout": Path(r"C:\Users\403\venvs\ner-runs\data_r3_phrase\r3_heldout_eval.jsonl"),
        "r6_heldout": Path(r"C:\Users\403\venvs\ner-runs\data_r6_phrase\r6_heldout_eval.jsonl"),
    }

    # 모델 지문 확인(읽기 전용) 후, 이 스크립트 안에서만 다른 디코딩을 쓴다(ner.py 는 안 씀)
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = a.r6_candidate
    status = ner.ner_status()
    assert status["fingerprint"][:12] == a.expect_fp12, status["fingerprint"][:12]

    insp = TokenInspector(a.r6_candidate)

    out = {}
    for name, path in DATASETS.items():
        rows = load_rows(path)
        out[name] = eval_rows(rows, insp)

    for name, r in out.items():
        print(f"{name}: F1={r['f1']} full_exposure_rate={r['full_exposure_rate']} total_exposure_rate={r['total_exposure_rate']} fpr={r['nonperson_fpr']} (pos={r['pos']}, full={r['full_exposure']})")

    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {a.out}")


if __name__ == "__main__":
    main()
