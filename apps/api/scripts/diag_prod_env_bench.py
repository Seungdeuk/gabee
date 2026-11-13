"""운영과 Python·onnxruntime 버전을 맞춘 격리 가상환경에서 R1 모델의 로딩·지연·메모리를 재는 스크립트(33절 실행).

진짜 Docker/운영 서버는 아니다(이 PC에서 Docker 데몬을 쓸 수 없어 실행 못 했다 - 32절에 차단 요인으로
기록됨). 대신 `py -3.12`로 만든 별도 venv에 `pyproject.toml` 그대로 설치해서 Python 버전과 onnxruntime
버전만큼은 운영(Dockerfile의 `python:3.12-slim`)과 정확히 맞춘 상태에서 측정한다.

사용: (Python 3.12 가상환경에서) python diag_prod_env_bench.py <모델 폴더>
"""

import argparse
import gc
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        return -1.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model_dir")
    ap.add_argument("--n", type=int, default=300, help="측정할 메시지 수")
    a = ap.parse_args()

    import onnxruntime

    print("Python:", sys.version.split()[0])
    print("onnxruntime:", onnxruntime.__version__)
    print("providers:", onnxruntime.get_available_providers())

    from app.shared.config import settings
    from app.shared.privacy import ner
    from app.shared.privacy.gateway import Row, prepare_transcript
    from app.shared.privacy.policy import ANALYSIS

    mem_before = _rss_mb()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = a.model_dir
    settings.privacy_ner_threads = 2

    t0 = time.perf_counter()
    ner.reset()
    load_ms = (time.perf_counter() - t0) * 1000
    status = ner.ner_status()
    if not status["active"]:
        raise SystemExit(f"NER 엔진을 쓸 수 없다: {a.model_dir}")
    print(f"\n로딩: {load_ms:.1f}ms, 지문={status['fingerprint']}")

    gc.collect()
    mem_after_load = _rss_mb()
    print(f"메모리: 로딩 전 {mem_before:.1f}MB -> 로딩 후 {mem_after_load:.1f}MB")

    base = "오늘 저녁에 가족 모임 있는 거 다들 기억하고 있지 민수가 늦을 수도 있다고 하니까 먼저 식당 자리 잡아두자 번호는"
    rows = [Row(i, "", base + str(i) * 3) for i in range(a.n)]  # 전부 다른 텍스트(캐시 우회)

    with prepare_transcript(rows[:5], [], ANALYSIS) as _:
        pass  # 워밍업

    latencies_ms = []
    for r in rows:
        t0 = time.perf_counter()
        with prepare_transcript([r], [], ANALYSIS) as prep:
            _ = prep.lines[0].text
        latencies_ms.append((time.perf_counter() - t0) * 1000)

    latencies_ms.sort()
    n = len(latencies_ms)
    p50, p95, p99 = latencies_ms[n // 2], latencies_ms[int(n * 0.95)], latencies_ms[int(n * 0.99)]
    print(
        f"\n개별 호출 지연({n}건, 100자 내외): p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms "
        f"평균={statistics.mean(latencies_ms):.2f}ms"
    )

    gc.collect()
    print(f"메모리: 추론 {n}건 후 {_rss_mb():.1f}MB")


if __name__ == "__main__":
    main()
