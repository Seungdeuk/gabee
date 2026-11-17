"""P+Amb 5시드가 48절 ambiguity_probe 전체(90개 부정 문장) + 특정 3사례에서 어떤지 확인."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaluate_r7_ablation as abl  # noqa: E402

MODELS = [
    ("R6+B", r"C:\Users\403\venvs\ner-runs\export\r6-candidate-s42", "c59b174ba126"),
    ("R7+B(참고)", r"C:\Users\403\venvs\ner-runs\export\r7-candidate-s42", "098cb439c7e4"),
]
for seed, fp in {7: "d38ba679c06d", 13: "91ee359461a5", 21: "b01dce5ebab0", 42: "32b849f80307", 99: "f7b508aaf7eb"}.items():
    MODELS.append((f"P+Amb-s{seed}", rf"C:\Users\403\venvs\ner-runs\export\r7abl-pamb-s{seed}", fp))

amb_rows = [json.loads(l) for l in abl.AMB.read_text(encoding="utf-8").splitlines() if l.strip()]
neg_rows = [r for r in amb_rows if not any(sp.get("kind") in ("PERSON", "PERSON_ALIAS") for sp in r.get("spans", []))]

out_lines = []
for key, model_dir, fp12 in MODELS:
    abl.ner.reset()
    abl.settings.privacy_ner_mode = "required"
    abl.settings.privacy_ner_model_dir = model_dir
    abl.settings.privacy_ner_threads = 2
    status = abl.ner.ner_status()
    assert status["fingerprint"][:12] == fp12, (key, status["fingerprint"][:12])
    flagged = 0
    for r in neg_rows:
        final = abl.ner.detect_with_ner(r["text"])
        if any(s.kind is abl.Kind.PERSON for s in final):
            flagged += 1
    specific = abl.check_specific_ambiguity(amb_rows)
    hits = [rid.split("-")[1] for rid, info in specific.items() if info["flagged"]]
    out_lines.append(f"{key}: 48절 전체 오탐 {flagged}/90 ({round(flagged/90*100,2)}%) | 특정3사례={hits}")

Path(sys.argv[1]).write_text("\n".join(out_lines), encoding="utf-8")
print("done")
