"""합성 장면의 **실제 SigLIP2 임베딩**을 고정 자료로 만든다(개발용). 이미 내려받은 로컬 모델만 쓰고 다운로드하지 않으며, 입력은 합성 장면뿐이다(가족 사진·운영 데이터 아님).
torch·transformers 가 있는 환경(예: 벤치마크 격리 venv, Python 3.12)에서 실행한다. API 가상환경에는 이 라이브러리가 없다.

사용법: python scripts/siglip2_scene_fixture.py <SigLIP2 스냅샷 폴더> <출력 json> [cpu|cuda|auto]
출력: {"model_id", "model_version", "dim", "photos": [{"scene", "variant", "signature", "embedding"}]}"""

import importlib.util
import json
import sys
from pathlib import Path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    snapshot, out_path = sys.argv[1], Path(sys.argv[2])
    device = sys.argv[3] if len(sys.argv) > 3 else "auto"
    root = Path(__file__).resolve().parents[1]
    enc_mod = _load(
        "family_memory_encoder", root / "app" / "features" / "family_memory" / "encoder.py"
    )
    scenes = _load("synthetic_scenes", root / "tests" / "synthetic_scenes.py")
    encoder = enc_mod.Siglip2Encoder(snapshot, device, False)
    encoder.load()
    photos = []
    for scene in scenes.SCENES:
        for variant in range(scenes.VARIANTS):
            data = scenes.jpeg_bytes(scene, variant)
            vec = encoder.encode(data)
            enc_mod.validate(vec, encoder.dim)
            photos.append(
                {
                    "scene": scene,
                    "variant": variant,
                    "signature": scenes.signature(data),
                    "embedding": [round(v, 6) for v in vec],
                }
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "model_id": encoder.model_id,
                "model_version": encoder.model_version,
                "dim": encoder.dim,
                "photos": photos,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    encoder.close()
    print(
        f"wrote {out_path} ({len(photos)} photos, dim {encoder.dim}, model {encoder.model_version[:8]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
