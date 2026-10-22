"""글을 숫자 목록(벡터)으로 바꾸는 부분. 모델은 이 인터페이스 뒤에서 바꿔 끼운다.

모델 폴더(`model.onnx`, `tokenizer.json`)가 있으면 파인튜닝한 e5-small(ONNX int8)을 쓰고, 없으면 모델 파일이 필요 없는
`HashingEmbedder`(낱말·글자 조각 해시)를 쓴다. 폴더는 환경변수 `EMBED_MODEL_DIR`, 없으면 `<DATA_DIR>/models/e5-small-ft` 다.
모델 파일은 크기 때문에 저장소에 넣지 않고 서버 PC 에 둔다."""

import math
import os
import re
import zlib
from pathlib import Path
from typing import Protocol


class TextEmbedder(Protocol):
    name: str  # 저장된 벡터가 어느 모델 것인지 구분한다(모델을 바꾸면 다시 만들어야 한다)
    dim: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """낱말과 2·3글자 조각을 고정 길이 벡터로 해시한다. 같은 말이 들어 있는 글끼리 가깝게 나온다."""

    dim = 512

    def __init__(self) -> None:
        self.name = f"hashing-{self.dim}"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            self._add(vec, word, 1.0)
            for n in (2, 3):
                for i in range(len(word) - n + 1):
                    self._add(vec, word[i : i + n], 0.5)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _add(self, vec: list[float], gram: str, weight: float) -> None:
        h = zlib.crc32(gram.encode("utf-8"))
        vec[h % self.dim] += weight if (h >> 16) & 1 else -weight

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class OnnxE5Embedder:
    """파인튜닝한 multilingual-e5-small(ONNX int8). 글은 "passage: ", 질문은 "query: " 를 앞에 붙여 만든다."""

    dim = 384

    def __init__(self, model_dir: Path, max_length: int = 512, batch_size: int = 16) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self._batch = batch_size
        self.name = f"onnx-{model_dir.name}"
        self._session = ort.InferenceSession(
            str(model_dir / "model.onnx"), providers=["CPUExecutionProvider"]
        )
        self._tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tok.enable_truncation(max_length)
        self._tok.enable_padding(pad_id=self._tok.token_to_id("<pad>") or 1, pad_token="<pad>")

    def _encode(self, texts: list[str]) -> list[list[float]]:
        np = self._np
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            enc = self._tok.encode_batch(texts[i : i + self._batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            hidden = self._session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            pooled /= np.linalg.norm(pooled, axis=1, keepdims=True) + 1e-12
            out.extend(pooled.tolist())
        return out

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(["passage: " + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode(["query: " + text])[0]


_embedder: TextEmbedder | None = None


def get_embedder() -> TextEmbedder:
    global _embedder
    if _embedder is None:
        from app.shared.config import settings

        model_dir = Path(
            os.environ.get("EMBED_MODEL_DIR") or Path(settings.data_dir) / "models" / "e5-small-ft"
        )
        _embedder = HashingEmbedder()
        if (model_dir / "model.onnx").exists():
            try:
                _embedder = OnnxE5Embedder(model_dir)
            except ImportError:  # onnxruntime 등이 없으면 해시 방식으로 계속 쓴다
                pass
    return _embedder


def set_embedder(embedder: TextEmbedder | None) -> None:
    """테스트나 모델 교체용."""
    global _embedder
    _embedder = embedder


def cosine(a: list[float], b: list[float]) -> float:
    """두 벡터가 이미 길이 1로 맞춰져 있으면 내적이 코사인이다."""
    return sum(x * y for x, y in zip(a, b, strict=False))
