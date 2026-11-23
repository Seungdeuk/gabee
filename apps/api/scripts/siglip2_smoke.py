"""SigLIP2 인코더 실제 추론 확인(개발용, PR4). **이미 내려받은 로컬 모델 파일만** 쓰고 다운로드하지 않으며, 입력은 합성 이미지뿐이다(가족 사진·운영 데이터 아님).

torch·transformers 가 있는 환경(예: 벤치마크 격리 venv)에서 실행한다. API 의 가상환경에는 이 라이브러리가 없다. `encoder.py` 는 파일 경로로 직접 불러오므로
`app` 패키지(DB·설정)가 필요 없다.

사용법:
    python scripts/siglip2_smoke.py <SigLIP2 스냅샷 폴더> [cpu|cuda|auto] [fp16] [개수]
"""

import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image


def _load_encoder_module():
    path = Path(__file__).resolve().parents[1] / "app" / "features" / "family_memory" / "encoder.py"
    spec = importlib.util.spec_from_file_location("family_memory_encoder", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["family_memory_encoder"] = module  # dataclass·Protocol 이 모듈 이름을 찾는다
    spec.loader.exec_module(module)
    return module


def _synthetic_jpeg(seed: int, size: int = 640) -> bytes:
    import io

    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (size // 16, size // 16, 3), dtype=np.uint8)
    image = Image.fromarray(base).resize((size, size), Image.Resampling.BICUBIC)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    device = args[1] if len(args) > 1 else "auto"
    fp16 = "fp16" in args[2:]
    count = next((int(a) for a in args[2:] if a.isdigit()), 20)
    enc_mod = _load_encoder_module()
    encoder = enc_mod.Siglip2Encoder(path, device, fp16)
    started = time.perf_counter()
    encoder.load()
    load_s = time.perf_counter() - started
    images = [_synthetic_jpeg(i) for i in range(count)]
    for data in images[:3]:  # 워밍업
        encoder.encode(data)
    timings, vectors = [], []
    for data in images:
        t = time.perf_counter()
        vectors.append(encoder.encode(data))
        timings.append((time.perf_counter() - t) * 1000)
    again = encoder.encode(images[0])
    norms = [math.sqrt(sum(v * v for v in vec)) for vec in vectors]
    diff = max(abs(a - b) for a, b in zip(vectors[0], again, strict=True))
    for vec in vectors:
        enc_mod.validate(vec, encoder.dim)
    cos = [float(np.dot(vectors[0], vectors[i])) for i in range(1, min(count, 6))]
    peak_gpu = None
    try:
        import torch

        if torch.cuda.is_available() and encoder._device == "cuda":
            peak_gpu = int(torch.cuda.max_memory_allocated() / 1e6)
    except Exception:  # noqa: BLE001
        pass
    result = {
        "model_id": encoder.model_id,
        "model_version": encoder.model_version,
        "device": encoder._device,
        "fp16": fp16,
        "dim": len(vectors[0]),
        "images": count,
        "load_s": round(load_s, 2),
        "ms_per_image_median": round(statistics.median(timings), 1),
        "ms_per_image_p95": round(sorted(timings)[int(0.95 * (len(timings) - 1))], 1),
        "norm_min": round(min(norms), 6),
        "norm_max": round(max(norms), 6),
        "repeat_max_abs_diff": diff,
        "cosine_vs_first_distinct_inputs": [round(c, 3) for c in cos],
        "resources": encoder.resources(),
        "gpu_peak_alloc_mb": peak_gpu,
    }
    encoder.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
