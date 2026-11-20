"""R11 B군 학습 직전 최종 점검(학습·추론 없음). 사전 등록 NER_R11_PREREGISTRATION.md §4-4, §10.

점검: (1) 사람 검수 집계 결과(`r11_review_summary.json`, verdict==pass 필요, 없으면 실패), (2) B군 9,915행·해시 정합성(조립 보고, r11_B_extra, R9F 복사본, 평가셋 해시, 데이터 매니페스트),
(3) A군(C10) 체크포인트·ONNX·데이터 해시, (4) 평가 코드·사전 등록 문서·고정 기준선 파일 해시 고정(`r11_code_pin.json`) 및 사전 등록 태그, (5) GPU·RAM·디스크 여유(실행기 사전 점검),
(6) 실행기 순차·중단 설정(드라이런 출력). 첫 GPU 실행의 `best/`==`epoch_best/` 해시 일치는 실행기 `cands` 단계가 자동 확인한다(불일치 시 중단).
사용: python r11_pretrain_check.py [--write-pin]   (--write-pin 은 사람 검수 통과 후 최종 고정 때만)
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = Path(r"C:\Users\403\venvs\ner-runs\data_r11")
V = REPO / "docs/security/r11_validation"
PIN = V / "r11_code_pin.json"
PIN_FILES = ["apps/api/scripts/r11_eval_lib.py", "apps/api/scripts/evaluate_r11_dev.py", "apps/api/scripts/evaluate_r11_val.py", "apps/api/scripts/aggregate_r11_baselines.py",
             "apps/api/scripts/select_r11.py", "apps/api/scripts/g12_r11.py", "apps/api/scripts/g12_latency.py", "ml/ner/train/g12_parity.py", "ml/ner/train/run_r11_B.py",
             "ml/ner/train/r11_derive.py", "ml/ner/train/train_ner.py", "ml/ner/train/build_r11_B.py", "docs/security/NER_R11_PREREGISTRATION.md",
             "docs/security/r11_validation/r11_reference_baselines.json", "docs/security/r11_validation/r11_recall_gate_fixed.json"]
REVIEW = DATA / "r11_review_summary.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()


def check_review():
    if not REVIEW.exists():
        return {"ok": False, "reason": "사람 검수 집계 결과 없음(r11_review_summary.json): 검수 미완료는 통과가 아니다"}
    d = json.loads(REVIEW.read_text(encoding="utf-8"))
    sets = d.get("sets", {})
    undec = sum(v.get("undecided", 0) for v in sets.values())
    return {"ok": d.get("verdict") == "pass" and undec == 0, "verdict": d.get("verdict"), "undecided_total": undec, "sets": {k: v.get("pass") for k, v in sets.items()}}


def check_data():
    rep = json.loads((DATA / "r11_B_assembly_report.json").read_text(encoding="utf-8"))
    man = {}
    for line in (V / "R11_DATA_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, n = line.split("  ", 1)
            man[n] = h
    mism = [n for n, h in man.items() if (DATA / n).exists() and sha(DATA / n) != h and not n.startswith("review/") and n != "r11_review_auto_report.json"]
    return {"ok": rep["rows"]["total"] == 9915 and rep["steps_per_epoch"] == 310 and sha(DATA / "r11_B_extra.jsonl") == rep["r11_B_extra_sha256"] and not mism
            and all(v["copy_identical"] for v in rep["r9f_files_copied"].values()) and rep["extra_sentences_equal_to_r11_val_dev"] == 0,
            "rows": rep["rows"], "steps_per_epoch": rep["steps_per_epoch"], "manifest_files_checked": len(man), "manifest_mismatch": mism}


def check_a_group():
    out = DATA / "a_group_integrity_recheck.json"
    subprocess.run([sys.executable, str(REPO / "ml/ner/analysis/r11_check_a_group.py"), "--manifest", str(REPO / "docs/security/r10_validation/r10_runs_manifest.json"), "--out", str(out)], check=True, capture_output=True)
    d = json.loads(out.read_text(encoding="utf-8"))
    return {"ok": bool(d["all_match"]), "n_runs": d["n_runs"]}


def check_pin(write):
    cur = {f: sha(REPO / f) for f in PIN_FILES}
    tag = git("rev-parse", "--verify", "-q", "refs/tags/r11-prereg-1.4^{commit}")
    dirty = [f for f in PIN_FILES if git("status", "--porcelain", "--", f)]
    res = {"git_head": git("rev-parse", "--short", "HEAD"), "prereg_tag_r11-prereg-1.4": tag[:8] or None, "uncommitted_pinned_files": dirty}
    if write:
        PIN.write_text(json.dumps({"git_head": res["git_head"], "prereg_tag": "r11-prereg-1.4", "files": cur}, indent=1), encoding="utf-8")
        res["pin_written"] = str(PIN)
        res["ok"] = bool(tag) and not dirty
        return res
    if not PIN.exists():
        return {**res, "ok": False, "reason": "코드 고정 파일(r11_code_pin.json) 없음: 사람 검수 통과 후 --write-pin 으로 고정"}
    pin = json.loads(PIN.read_text(encoding="utf-8"))["files"]
    diff = [f for f in PIN_FILES if pin.get(f) != cur[f]]
    return {**res, "ok": bool(tag) and not diff and not dirty, "changed_since_pin": diff}


def check_runner():
    out = subprocess.run([r"C:\Users\403\venvs\gabee-ner\Scripts\python.exe", str(HERE / "run_r11_B.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = out.stdout
    j = json.loads(txt[: txt.index("RUN ")]) if "RUN " in txt else {}
    seeds = [ln.split()[-1] for ln in txt.splitlines() if ln.startswith("RUN ")]
    return {"ok": bool(j.get("ok")) and seeds == [f"r11-B-s{s}" for s in (7, 13, 21, 42, 99)] and "드라이런" in txt, "failed_checks": j.get("failed_checks"), "seeds_in_order": seeds,
            "avail_ram_mb": j.get("avail_ram_mb"), "free_disk_gb": j.get("free_disk_gb"), "gpu": j.get("gpu")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-pin", action="store_true")
    a = ap.parse_args()
    rep = {"1_human_review": check_review(), "2_B_data_hashes": check_data(), "3_A_group_C10": check_a_group(), "4_code_and_prereg_pin": check_pin(a.write_pin), "5_6_runner_resources_sequence": check_runner()}
    rep["ALL_OK"] = all(v.get("ok") for v in rep.values())
    (DATA / "r11_pretrain_check_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["ALL_OK"] else 1


if __name__ == "__main__":
    sys.exit(main())
