import json
import subprocess
from pathlib import Path

SC = Path(r"C:\Users\<user>\AppData\Local\Temp\claude\81d4ea6423f385fa\58fea5dc-3059-42a5-9d4f-5a126dc2262a\scratchpad")
H = SC / "s2b_ops"
OUT = H / "out"
DATA = Path(r"C:\Users\<user>\venvs\ner-runs\data_r11")
order = ["s0", "r11", "r11", "s0", "s0", "r11"]  # 사전 등록 교차 순서(g12 와 같음)
for i, who in enumerate(order, 1):
    if who == "s0":
        img, md = "gabee-api:s0-rollback-nonprod", "/srv/data/models/ner-koelectra-small-v2b"
    else:
        img, md = "gabee-api:r11-nonprod", "/srv/data/models/ner-koelectra-small-r11b-s21"
    out = OUT / f"run{i}_{who}.json"
    if out.exists():
        out.unlink()
    cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "2g",
           "-v", f"{H}:/check:ro", "-v", f"{DATA}:/data:ro", "-v", f"{OUT}:/out",
           "-e", "PRIVACY_NER_MODE=required", "-e", f"PRIVACY_NER_MODEL_DIR={md}", "-e", "PYTHONPATH=/srv",
           "--entrypoint", "python", img, "/check/s2b_ops_bench.py", "--sentences", "/data/r11_val.jsonl", "--out", f"/out/run{i}_{who}.json"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(i, who, "rc", p.returncode, (p.stdout or p.stderr)[-200:].replace("\n", " "), flush=True)
(H / "done.txt").write_text("done")
