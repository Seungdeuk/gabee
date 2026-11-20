"""R11 B군 한 런에서 파생 모델(B-old, B-new, C-SWA)을 만든다(추가 학습 없음). 사전 등록 NER_R11_PREREGISTRATION.md §3-4, §6.

- 입력: 런 폴더(`train_ner.py --save-every-epoch` 가 만든 `epoch_<k>/model.safetensors` 와 `best/`, `train_log.json`)
- `cands`: 에폭별 후보 폴더 `cand/ep<k>/best/` 와 가중치 평균 `cand/swa/best/` 를 만든다(ONNX 내보내기용 의사 런 폴더, `train_log.json` 복사 포함).
  가중치 평균 규칙(사전 고정): 마지막 학습 에폭 e 에 대해 θ = (θ_{e-2} + θ_{e-1} + θ_e)/3, 학습 에폭이 3 미만이면 있는 전 에폭, 모든 부동소수 텐서를 fp32 로 균일 산술평균,
  정수형 텐서는 마지막 에폭 값 복사.
- `select`: 에폭별 Validation(`r11_val`) 지표 JSON 으로 B-new 에폭을 고른다. 쌍 문맥 정확률 최대 → 정답 PERSON Exact Recall 최대 → 사람 문장 전체 노출률 최소 →
  baseline_val 겹침 F1 최대 → 더 이른 에폭. 단 사람 문장 전체 노출률이 그 런의 최저 에폭보다 1.0%p 넘게 나쁜 에폭은 자격 박탈. B-old 는 `train_log.json` 의 best_epoch.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

TOKENIZER_FILES = ["tokenizer.json", "tokenizer_config.json", "config.json"]
SWA_WINDOW = 3
SAFETY_PP = 0.010


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def average_state_dicts(sds):
    """부동소수 텐서는 fp32 균일 산술평균, 그 밖은 마지막 값."""
    import torch

    out = {}
    for k, last in sds[-1].items():
        if torch.is_floating_point(last):
            out[k] = (sum(sd[k].to(torch.float32) for sd in sds) / len(sds)).to(last.dtype)
        else:
            out[k] = last.clone()
    return out


def swa_epochs(stopped_epoch, available):
    """평균 대상 에폭: 마지막 학습 에폭 포함 최근 3개(없으면 있는 만큼)."""
    first = max(1, stopped_epoch - SWA_WINDOW + 1)
    eps = [e for e in range(first, stopped_epoch + 1) if e in available]
    return eps


def select_epoch(val_by_epoch, baseline_val_f1):
    """val_by_epoch: {epoch: {pair_context_accuracy, exact_recall, person_total_exposure}}, baseline_val_f1: {epoch: f1}."""
    min_exp = min(v["person_total_exposure"] for v in val_by_epoch.values())
    ok = {e: v for e, v in val_by_epoch.items() if v["person_total_exposure"] - min_exp <= SAFETY_PP + 1e-12}
    key = lambda e: (-ok[e]["pair_context_accuracy"], -ok[e]["exact_recall"], ok[e]["person_total_exposure"], -baseline_val_f1.get(e, 0.0), e)  # noqa: E731
    return sorted(ok, key=key)[0], sorted(set(val_by_epoch) - set(ok))


def cmd_cands(run_dir):
    from safetensors.torch import load_file, save_file

    run = Path(run_dir)
    tl = json.loads((run / "train_log.json").read_text(encoding="utf-8"))
    stopped = tl["stopped_epoch"]
    epochs = [e["epoch"] for e in tl["epochs"]]
    avail = {e for e in epochs if (run / f"epoch_{e}" / "model.safetensors").exists()}
    if avail != set(epochs):
        raise SystemExit(f"에폭 체크포인트 누락: {sorted(set(epochs) - avail)} (--save-every-epoch 가 꺼져 있었는지 확인, 임의 보완 금지)")
    # 저장 정합성: best/ 와 epoch_{best_epoch}/ 가중치가 같아야 한다
    if sha(run / "best" / "model.safetensors") != sha(run / f"epoch_{tl['best_epoch']}" / "model.safetensors"):
        raise SystemExit("best/ 와 epoch_<best_epoch>/ 가중치 해시 불일치: 저장 기능 정합성 실패, 중단")
    cand = run / "cand"
    info = {"epochs": epochs, "stopped_epoch": stopped, "best_epoch": tl["best_epoch"], "candidates": {}}

    def make(name, weights_path_or_sd):
        d = cand / name / "best"
        d.mkdir(parents=True, exist_ok=True)
        for f in TOKENIZER_FILES:
            shutil.copyfile(run / "best" / f, d / f)
        shutil.copyfile(run / "train_log.json", cand / name / "train_log.json")
        if isinstance(weights_path_or_sd, dict):
            save_file({k: v.contiguous() for k, v in weights_path_or_sd.items()}, str(d / "model.safetensors"), metadata={"format": "pt"})
        else:
            shutil.copyfile(weights_path_or_sd, d / "model.safetensors")
        return sha(d / "model.safetensors")

    for e in epochs:
        info["candidates"][f"ep{e}"] = {"weights_sha256": make(f"ep{e}", run / f"epoch_{e}" / "model.safetensors")}
    eps = swa_epochs(stopped, set(epochs))
    sds = [load_file(str(run / f"epoch_{e}" / "model.safetensors")) for e in eps]
    info["candidates"]["swa"] = {"weights_sha256": make("swa", average_state_dicts(sds)), "window_epochs": eps, "short_window": len(eps) < SWA_WINDOW}
    (run / "cand_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


def cmd_select(run_dir, val_json):
    run = Path(run_dir)
    tl = json.loads((run / "train_log.json").read_text(encoding="utf-8"))
    val = json.loads(Path(val_json).read_text(encoding="utf-8"))
    vb = {int(k[2:]): v for k, v in val.items() if k.startswith("ep")}
    f1 = {e["epoch"]: e["val_score"] for e in tl["epochs"]}
    new, excluded = select_epoch(vb, f1)
    sel = {"B_old_epoch": tl["best_epoch"], "B_new_epoch": new, "same_epoch": new == tl["best_epoch"], "excluded_by_safety": excluded,
           "val_by_epoch": {str(k): v for k, v in vb.items()}}
    (run / "selection.json").write_text(json.dumps(sel, indent=1), encoding="utf-8")
    print(json.dumps(sel, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cands")
    c.add_argument("--run-dir", required=True)
    s = sub.add_parser("select")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--val-json", required=True)
    a = ap.parse_args()
    cmd_cands(a.run_dir) if a.cmd == "cands" else cmd_select(a.run_dir, a.val_json)


if __name__ == "__main__":
    sys.exit(main())
