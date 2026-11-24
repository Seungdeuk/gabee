import hashlib
import json
import os
import random
import statistics as st
import sys
from pathlib import Path

H = Path(r"C:\Users\<user>\AppData\Local\Temp\claude\81d4ea6423f385fa\58fea5dc-3059-42a5-9d4f-5a126dc2262a\scratchpad\s2b_ops")
OUT = H / "out"
runs = {"s0": [], "r11": []}
for p in sorted(OUT.glob("run*_*.json")):
    who = p.stem.split("_")[1]
    runs[who].append(json.loads(p.read_text(encoding="utf-8")))


def med(vals):
    vals = [v for v in vals if v is not None]
    return round(st.median(vals), 2) if vals else None


def agg(path):
    out = {}
    for who, rs in runs.items():
        cur = []
        for r in rs:
            x = r
            for k in path:
                x = x[k]
            cur.append(x)
        out[who] = cur
    return out


summary = {"n_runs": {k: len(v) for k, v in runs.items()}, "conditions": runs["r11"][0]["conditions"]}
# load / single / rss
summary["load_s"] = {w: [r["load"]["first_ner_status_s"] for r in rs] for w, rs in runs.items()}
summary["rss_after_load_mb"] = {w: [r["load"]["rss_after_load_mb"] for r in rs] for w, rs in runs.items()}
summary["single_p50_ms"] = {w: [r["single"]["p50_ms"] for r in rs] for w, rs in runs.items()}
summary["single_p95_ms"] = {w: [r["single"]["p95_ms"] for r in rs] for w, rs in runs.items()}
summary["peak_rss_mb"] = {w: [r["final"]["peak_rss_mb"] for r in rs] for w, rs in runs.items()}
summary["model_size_mb"] = {w: rs[0]["final"]["model_size_mb"] for w, rs in runs.items()}
rows = []
for block in ("general", "intensive"):
    for key in runs["r11"][0][block]:
        row = {"block": block, "case": key}
        for who in runs:
            ms = [r[block][key] for r in runs[who]]
            for m in ("p50_ms", "p95_ms", "p99_ms", "throughput_rps", "http503", "n", "shed_over_80"):
                vals = [x.get(m) for x in ms]
                row[f"{who}_{m}"] = vals
        rows.append(row)
summary["load_cases"] = rows
# ratios (medians)
def ratio(a, b):
    return round(a / b, 3) if a and b else None


m = lambda d, w: st.median(d[w])
summary["ratios_r11_over_s0"] = {
    "single_p50": ratio(m(summary["single_p50_ms"], "r11"), m(summary["single_p50_ms"], "s0")),
    "single_p95": ratio(m(summary["single_p95_ms"], "r11"), m(summary["single_p95_ms"], "s0")),
    "rss_after_load": ratio(m(summary["rss_after_load_mb"], "r11"), m(summary["rss_after_load_mb"], "s0")),
    "peak_rss": ratio(m(summary["peak_rss_mb"], "r11"), m(summary["peak_rss_mb"], "s0")),
    "load_time": ratio(m(summary["load_s"], "r11"), m(summary["load_s"], "s0")),
    "model_size": ratio(summary["model_size_mb"]["r11"], summary["model_size_mb"]["s0"]),
}
case_ratios = {}
for row in rows:
    case_ratios[row["case"]] = {
        "p50": ratio(med(row["r11_p50_ms"]), med(row["s0_p50_ms"])),
        "p95": ratio(med(row["r11_p95_ms"]), med(row["s0_p95_ms"])),
        "throughput": ratio(med(row["r11_throughput_rps"]), med(row["s0_throughput_rps"])),
        "503_s0": sum(x or 0 for x in row["s0_http503"]),
        "503_r11": sum(x or 0 for x in row["r11_http503"]),
    }
summary["case_ratios_r11_over_s0"] = case_ratios

# 컨테이너 vs 호스트 일치(같은 모델, 같은 300문장)
if len(sys.argv) > 1 and sys.argv[1] == "parity":
    sys.path.insert(0, r"C:\Users\<user>\Documents\gabee-ner\apps\api")
    os.environ["PRIVACY_NER_MODE"] = "required"
    parity = {}
    for who, d in (("s0", r"C:\Users\<user>\venvs\ner-runs\service_v2b"), ("r11", r"C:\Users\<user>\venvs\ner-runs\r11\export\r11-B-s21-ep5")):
        os.environ["PRIVACY_NER_MODEL_DIR"] = d
        for mod in [m_ for m_ in list(sys.modules) if m_.startswith("app.")]:
            del sys.modules[mod]
        from app.shared.privacy import ner

        ner.reset()
        ner._cache_get = lambda key: None
        ner._cache_put = lambda key, value: None
        texts = [json.loads(x)["text"] for x in Path(r"C:\Users\<user>\venvs\ner-runs\data_r11\r11_val.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        texts = [t for t in texts if ner._worth(t)]
        fixed = random.Random(7).sample(texts, 300)
        hs = []
        for t in fixed:
            sp = ner.detect_with_ner(t, ())
            hs.append(hashlib.sha256(json.dumps([(s.start, s.end, s.kind.name) for s in sp]).encode()).hexdigest()[:12])
        cont = runs[who][0]["parity"]
        agree = sum(1 for a, b in zip(hs, cont) if a == b)
        allsame = all(r["parity"] == cont for r in runs[who])
        import onnxruntime as ort

        parity[who] = {"sentences": len(hs), "agree": agree, "agree_pct": round(100 * agree / len(hs), 2), "containers_identical_across_runs": allsame, "host_ort": ort.__version__}
    summary["container_vs_host_span_agreement"] = parity
(H / "s2b_ops_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k not in ("load_cases",)}, ensure_ascii=False, indent=1))
