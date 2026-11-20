"""R11-G12 CPU 지연·메모리 측정(한 프로세스에서 모델 하나, 서비스 NER 경로 `detect_with_ner` 그대로). 서비스 코드·설정·운영 ONNX 를 수정하지 않는다.

측정 조건(고정, 결과 JSON 에 기록): ONNX Runtime CPU, 스레드 2(서비스 `privacy_ner_threads` 기본과 같게 프로세스 안에서만 지정), OMP/MKL 스레드 2,
문장 하나씩(배치 1), 워밍업 30문장 1회(측정 제외), 측정 문장 300개(`r11_val` 에서 시드 고정 무작위, 모든 모델 같은 목록)를 5번 반복,
반복마다 문장당 지연의 p50·p95·평균을 구하고 반복 사이 중앙값을 보고한다. 측정 전 시스템 CPU 사용률(3초)과 가용 RAM, RSS(측정 후), 모델 파일 크기를 기록한다.
사용: python scripts/g12_latency.py --onnx-dir DIR --out lat.json
"""

import argparse
import json
import os
import platform
import random
import statistics as st
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

R11_VAL = Path(r"C:\Users\403\venvs\ner-runs\data_r11\r11_val.jsonl")
N_WARM, N_MEASURE, N_REPEAT, THREADS, SEED = 30, 300, 5, 2, 20261127


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--onnx-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    import onnxruntime as ort
    import psutil
    import r8_eval_lib as lib
    from app.shared.privacy import ner

    texts = [json.loads(x)["text"] for x in R11_VAL.read_text(encoding="utf-8").splitlines() if x.strip()]
    rng = random.Random(SEED)
    pool = rng.sample(texts, N_WARM + N_MEASURE)
    warm, meas = pool[:N_WARM], pool[N_WARM:]
    cpu_before = psutil.cpu_percent(interval=3)
    avail_mb = round(psutil.virtual_memory().available / 2**20)
    lib.set_model(a.onnx_dir, None, threads=THREADS)
    for t in warm:  # 워밍업(세션 초기화·캐시), 측정 제외
        ner._cache.clear()
        ner.detect_with_ner(t, ())
    passes = []
    for _ in range(N_REPEAT):
        lat = []
        for t in meas:
            ner._cache.clear()  # 문장 캐시 영향 제거
            t0 = time.perf_counter()
            ner.detect_with_ner(t, ())
            lat.append((time.perf_counter() - t0) * 1000)
        passes.append({"p50_ms": pct(lat, 0.5), "p95_ms": pct(lat, 0.95), "mean_ms": sum(lat) / len(lat)})
    rss = psutil.Process().memory_info().rss / 2**20
    res = {"onnx_dir": str(a.onnx_dir), "model_size_mb": round((a.onnx_dir / "model.onnx").stat().st_size / 2**20, 3), "rss_mb_after": round(rss, 1),
           "p50_ms": st.median(p["p50_ms"] for p in passes), "p95_ms": st.median(p["p95_ms"] for p in passes), "mean_ms": st.median(p["mean_ms"] for p in passes),
           "passes": passes, "conditions": {"threads": THREADS, "warmup_sentences": N_WARM, "measured_sentences": N_MEASURE, "repeats": N_REPEAT, "batch": 1, "seed": SEED,
                                              "cache_cleared_each_sentence": True, "cpu_percent_before": cpu_before, "avail_ram_mb_before": avail_mb,
                                              "onnxruntime": ort.__version__, "python": platform.python_version(), "processor": platform.processor(), "cpu_count": os.cpu_count()}}
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("model_size_mb", "rss_mb_after", "p50_ms", "p95_ms", "mean_ms")}))


if __name__ == "__main__":
    main()
