"""S2b 운영 조건 측정(이미지 안에서 실행). 운영 설정: 1 vCPU·2GiB(--cpus 1 --memory 2g), PRIVACY_NER_MODE=required,
PRIVACY_NER_THREADS·MAX_CONCURRENCY 는 환경변수 없이 코드 기본값(2·2). 문장은 개발 검증셋 r11_val(봉인 평가셋 아님), 원문은 출력하지 않는다.

측정:
  load      : 모델 로딩 시간(처음 ner_status() 호출: 세션 생성·워밍업 포함)과 로딩 직후 RSS
  parity    : 같은 문장의 NER 구간 해시 목록(호스트 실행과 비교용)
  single    : 동시성 1 요청 지연(문장 1줄)
  general   : 일반 요청 — 도착률(rps)별 열린 루프, 문장 1줄, Cloud Run 요청 동시성 상한 80 모방(80 넘으면 shed)
  intensive : NER 집중 — 동시 요청 수(워커)별 닫힌 루프, 40줄(대화 분석형)·200줄(큰 분석형), 503(PrivacyUnavailable) 집계
"""

import argparse
import hashlib
import json
import os
import random
import statistics as st
import threading
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--sentences", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--quick", action="store_true")
a = ap.parse_args()

t_import0 = time.perf_counter()
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.pseudonymizer import detect_with_ner as _unused  # noqa: E402,F401
from app.shared.privacy.ner import PrivacyUnavailable, batch_scope, detect_with_ner  # noqa: E402

t_import = time.perf_counter() - t_import0


def rss_mb(key="VmRSS:"):
    with open("/proc/self/status") as f:
        for ln in f:
            if ln.startswith(key):
                return round(int(ln.split()[1]) / 1024, 1)
    return -1.0


texts = [json.loads(x)["text"] for x in a.sentences.read_text(encoding="utf-8").splitlines() if x.strip()]
texts = [t for t in texts if ner._worth(t)]
rng = random.Random(20261124)
res = {"status_before": None, "conditions": {}}

# 캐시를 끈다(같은 문장 반복으로 추론이 생략되지 않게)
ner._cache_get = lambda key: None
ner._cache_put = lambda key, value: None

t0 = time.perf_counter()
st0 = ner.ner_status()
load_s = time.perf_counter() - t0
res["load"] = {"import_s": round(t_import, 3), "first_ner_status_s": round(load_s, 3), "status": st0, "rss_after_load_mb": rss_mb()}
if not st0.get("active"):
    raise SystemExit("NER 엔진이 active 가 아니다: " + json.dumps(st0))
cfg = ner._config()
res["conditions"] = {"mode": cfg.mode, "threads": cfg.threads, "concurrency": cfg.concurrency, "cpu_count_visible": os.cpu_count(),
                     "queue_wait_s": ner.QUEUE_WAIT_SECONDS, "time_budget_s": ner.TIME_BUDGET_SECONDS}

# parity: 고정 300문장(시드 고정)의 구간 해시
fixed = random.Random(7).sample(texts, 300)
hs = []
for t in fixed:
    sp = detect_with_ner(t, ())
    hs.append(hashlib.sha256(json.dumps([(s.start, s.end, s.kind.name) for s in sp]).encode()).hexdigest()[:12])
res["parity"] = hs


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 2)


def one_request(lines):
    """실제 경로와 같게: batch_scope(미리 한 번에 추론) 안에서 줄마다 detect_with_ner."""
    t0 = time.perf_counter()
    status = "ok"
    try:
        with batch_scope(lines, newest_last=True):
            for ln in lines:
                detect_with_ner(ln, ())
    except PrivacyUnavailable:
        status = "503"
    except Exception as e:  # noqa: BLE001
        status = "err:" + type(e).__name__
    return (time.perf_counter() - t0) * 1000, status


def summarize(lat_ok, statuses, wall, extra=None):
    out = {"n": len(statuses), "ok": statuses.count("ok"), "http503": statuses.count("503"),
           "other_err": len([s for s in statuses if s.startswith("err")]),
           "p50_ms": pct(lat_ok, 0.5), "p95_ms": pct(lat_ok, 0.95), "p99_ms": pct(lat_ok, 0.99),
           "max_ms": round(max(lat_ok), 1) if lat_ok else None,
           "throughput_rps": round(len(statuses) / wall, 2), "rss_mb": rss_mb(), "peak_rss_mb": rss_mb("VmHWM:")}
    if extra:
        out.update(extra)
    return out


def pick(n):
    return [rng.choice(texts) for _ in range(n)]


# single: 1줄, 동시성 1
lat = []
for _ in range(20):
    detect_with_ner(rng.choice(texts), ())
for _ in range(300 if not a.quick else 40):
    ms, s = one_request(pick(1))
    lat.append(ms)
res["single"] = {"p50_ms": pct(lat, 0.5), "p95_ms": pct(lat, 0.95), "mean_ms": round(st.mean(lat), 2)}

DUR = 6 if a.quick else 20


def open_loop(rps, dur, lines=1, cap=80):
    lat_ok, statuses = [], []
    lock = threading.Lock()
    inflight = [0]
    shed = [0]
    ths = []

    def work():
        ms, s = one_request(pick(lines))
        with lock:
            statuses.append(s)
            if s == "ok":
                lat_ok.append(ms)
            inflight[0] -= 1

    t_start = time.perf_counter()
    nxt = t_start
    while True:
        now = time.perf_counter()
        if now - t_start >= dur:
            break
        if now >= nxt:
            nxt += rng.expovariate(rps)
            with lock:
                if inflight[0] >= cap:
                    shed[0] += 1
                    continue
                inflight[0] += 1
            th = threading.Thread(target=work)
            th.start()
            ths.append(th)
        else:
            time.sleep(min(0.002, nxt - now))
    for th in ths:
        th.join()
    return summarize(lat_ok, statuses, time.perf_counter() - t_start, {"shed_over_80": shed[0], "arrival_rps": rps})


def closed_loop(workers, dur, lines):
    lat_ok, statuses = [], []
    lock = threading.Lock()
    stop = time.perf_counter() + dur

    def worker():
        while time.perf_counter() < stop:
            ms, s = one_request(pick(lines))
            with lock:
                statuses.append(s)
                if s == "ok":
                    lat_ok.append(ms)

    t_start = time.perf_counter()
    ths = [threading.Thread(target=worker) for _ in range(workers)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    return summarize(lat_ok, statuses, time.perf_counter() - t_start, {"workers": workers, "lines": lines})


res["general"] = {}
for rps in ([5] if a.quick else [5, 10, 20]):
    res["general"][f"{rps}rps_1line"] = open_loop(rps, DUR)
res["intensive"] = {}
for workers, lines in ([(2, 40)] if a.quick else [(2, 40), (8, 40), (80, 40), (2, 200), (8, 200)]):
    res["intensive"][f"w{workers}_{lines}lines"] = closed_loop(workers, DUR, lines)
res["final"] = {"rss_mb": rss_mb(), "peak_rss_mb": rss_mb("VmHWM:"), "model_size_mb": round(os.path.getsize(os.path.join(os.environ["PRIVACY_NER_MODEL_DIR"], "model.onnx")) / 2**20, 3)}
import onnxruntime as ort  # noqa: E402

res["conditions"]["onnxruntime"] = ort.__version__
a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"load": res["load"], "single": res["single"], "final": res["final"]}, ensure_ascii=False))
