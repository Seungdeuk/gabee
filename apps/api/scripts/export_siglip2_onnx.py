"""SigLIP2 이미지 인코더를 ONNX 로 바꾸고 문장 14개의 텍스트 임베딩을 미리 계산한다(사진·문서 단계형 판별용, `ingest/siglip_margin.py`).

사용: `python scripts/export_siglip2_onnx.py <SigLIP2 스냅샷 폴더> <출력 폴더>` — torch·transformers·onnx 가 있는 개발 PC 환경에서만 돌린다(서버 이미지에는 필요 없다).
이미 내려받은 `google/siglip2-base-patch16-224` 체크포인트만 쓰고(HF 오프라인) 다운로드·학습은 하지 않는다. 출력(저장소에 올리지 않는다):
- `siglip2_vision.onnx`: 비전 타워 + 풀링 헤드. 입력 `pixel_values`(N,3,224,224), 출력 L2 정규화된 이미지 임베딩(N,768)
- `head.json`: 같은 체크포인트·문장·전처리로 계산한 정규화 텍스트 임베딩 14×768, `logit_scale`, `logit_bias`
- `SHA256SUMS.json`: 두 파일의 SHA-256(배포·무결성 확인용)
문장 14개는 `siglip_margin.py` 의 것과 같아야 하며, 서버는 로드할 때 일치를 확인한다."""

import hashlib
import json
import os
import sys

DOC_PROMPTS = [
    "a photo of a paper document",
    "a photo of a printed form with a table",
    "a photo of a receipt",
    "a photo of an ID card",
    "a photo of a page of text",
    "a scanned document",
]
PHOTO_PROMPTS = [
    "a photo of a landscape",
    "a photo of food on a plate",
    "a photo of people outdoors",
    "a photo of a menu board",
    "a photo of street signs",
    "a photo of a poster",
    "a photo of a book cover",
    "a photo of a family",
]


def main(snapshot: str, out_dir: str) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    from transformers import AutoModel, AutoProcessor

    os.makedirs(out_dir, exist_ok=True)
    model = AutoModel.from_pretrained(snapshot, local_files_only=True).eval()
    processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)

    class ImageEncoder(torch.nn.Module):
        def __init__(self, inner: torch.nn.Module) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
            out = self.inner.get_image_features(pixel_values=pixel_values)
            out = out if torch.is_tensor(out) else out.pooler_output
            return torch.nn.functional.normalize(out, dim=-1)

    model_path = os.path.join(out_dir, "siglip2_vision.onnx")
    with torch.no_grad():
        torch.onnx.export(
            ImageEncoder(model).eval(),
            (torch.randn(1, 3, 224, 224),),
            model_path,
            input_names=["pixel_values"],
            output_names=["image_embeds"],
            dynamic_axes={"pixel_values": {0: "batch"}, "image_embeds": {0: "batch"}},
            opset_version=17,
            dynamo=False,
        )
        tokens = processor(
            text=DOC_PROMPTS + PHOTO_PROMPTS,
            padding="max_length",
            max_length=64,
            return_tensors="pt",
        )
        text = model.get_text_features(input_ids=tokens["input_ids"])
        text = text if torch.is_tensor(text) else text.pooler_output
        text = torch.nn.functional.normalize(text, dim=-1)
    head = {
        "checkpoint": "google/siglip2-base-patch16-224",
        "snapshot": os.path.basename(os.path.normpath(snapshot)),
        "doc_prompts": DOC_PROMPTS,
        "photo_prompts": PHOTO_PROMPTS,
        "text_embeds": text.tolist(),
        "logit_scale": float(model.logit_scale),
        "logit_bias": float(model.logit_bias),
        "image_size": 224,
        "mean": [0.5, 0.5, 0.5],
        "std": [0.5, 0.5, 0.5],
        "resize": "squash 224x224 BILINEAR",
    }
    head_path = os.path.join(out_dir, "head.json")
    with open(head_path, "w", encoding="utf-8") as fh:
        json.dump(head, fh)
    sums = {}
    for path in (model_path, head_path):
        with open(path, "rb") as fh:
            sums[os.path.basename(path)] = {
                "sha256": hashlib.sha256(fh.read()).hexdigest(),
                "bytes": os.path.getsize(path),
            }
    with open(os.path.join(out_dir, "SHA256SUMS.json"), "w", encoding="utf-8") as fh:
        json.dump(sums, fh, indent=1)
    print(json.dumps(sums, indent=1))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
