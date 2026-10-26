"""문서 종류 분류기. e5 임베딩(384차원)에 글자 TF-IDF 를 이어 붙인 로지스틱 회귀를 numpy 만으로 계산한다.

학습은 `scripts/train_doc_classifier.py`(scikit-learn)가 하고, 여기서는 그 결과 파일을 읽어 같은 확률을 낸다.
폴더(`classes.json` `coef.npy` `intercept.npy` `vocab.json` `idf.npy` `config.json`)는 환경변수 `DOC_CLASSIFIER_DIR`,
없으면 `<DATA_DIR>/models/doc-classifier` 다. 모델 파일은 크기 때문에 저장소에 넣지 않고 서버 PC 에 둔다.

폴더나 e5 모델 파일이 없으면 `predict()` 는 None 을 돌려준다 — 호출한 쪽이 Jev → 사람 확인으로 넘어간다."""

import json
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Prediction:
    kind: str  # 가장 확률이 높은 종류
    confidence: float  # 그 종류의 확률(0~1)


class DocClassifier:
    def __init__(self, folder: Path) -> None:
        self.classes: list[str] = json.loads((folder / "classes.json").read_text(encoding="utf-8"))
        self.vocab: dict[str, int] = json.loads((folder / "vocab.json").read_text(encoding="utf-8"))
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        self.ngram_range: tuple[int, int] = (config["ngram_range"][0], config["ngram_range"][1])
        self.tfidf_weight: float = config["tfidf_weight"]
        self.threshold: float = config["threshold"]
        self.embed_dim: int = config["embed_dim"]
        self.max_chars: int = config["max_chars"]
        coef = np.load(folder / "coef.npy").astype(np.float64)
        self._coef_embed = coef[:, : self.embed_dim]  # 임베딩 칸
        self._coef_tfidf = np.ascontiguousarray(coef[:, self.embed_dim :].T)
        self._intercept = np.load(folder / "intercept.npy").astype(np.float64)
        self._idf = np.load(folder / "idf.npy").astype(np.float64)

    def _ngrams(self, text: str) -> list[str]:
        """scikit-learn 의 analyzer="char_wb" 와 같다: 소문자로 바꾸고, 공백으로 나눈 낱말을 앞뒤 공백으로 감싸 n글자씩 자른다."""
        lo, hi = self.ngram_range
        grams: list[str] = []
        for word in _WHITESPACE.sub(" ", text.lower()).split():
            w = f" {word} "
            for n in range(lo, hi + 1):
                offset = 0
                grams.append(w[offset : offset + n])
                while offset + n < len(w):
                    offset += 1
                    grams.append(w[offset : offset + n])
                if offset == 0:  # 낱말이 n글자보다 짧으면 한 번만 센다
                    break
        return grams

    def _tfidf(self, text: str) -> tuple[list[int], np.ndarray]:
        """sublinear tf(1+log tf) × idf 를 길이 1로 맞춘 값. (낱말 번호들, 값들)"""
        counts: dict[int, int] = {}
        for gram in self._ngrams(text):
            i = self.vocab.get(gram)
            if i is not None:
                counts[i] = counts.get(i, 0) + 1
        if not counts:
            return [], np.zeros(0)
        idx = list(counts)
        vals = np.array([(1.0 + math.log(counts[i])) * self._idf[i] for i in idx])
        return idx, vals / np.linalg.norm(vals)

    def probabilities(self, text: str, embedding) -> np.ndarray:
        """종류마다의 확률(self.classes 순서). embedding 은 길이 1로 맞춘 384차원 벡터."""
        emb = np.asarray(embedding, dtype=np.float64)
        logits = self._coef_embed @ emb + self._intercept
        idx, vals = self._tfidf(text[: self.max_chars])
        if idx:
            logits = logits + self.tfidf_weight * (vals @ self._coef_tfidf[idx])
        logits -= logits.max()
        p = np.exp(logits)
        return p / p.sum()

    def predict(self, text: str, embedding) -> Prediction:
        p = self.probabilities(text, embedding)
        best = int(p.argmax())
        return Prediction(self.classes[best], float(p[best]))


_lock = threading.Lock()
_loaded = False
_classifier: DocClassifier | None = None


def _folder() -> Path:
    from app.shared.config import settings

    return Path(
        os.environ.get("DOC_CLASSIFIER_DIR")
        or Path(settings.data_dir) / "models" / "doc-classifier"
    )


def get_classifier() -> DocClassifier | None:
    """분류기를 한 번만 읽는다(여러 스레드가 동시에 불러도 한 번). 파일이 없거나 깨졌으면 None."""
    global _loaded, _classifier
    if _loaded:
        return _classifier
    with _lock:
        if not _loaded:
            try:
                folder = _folder()
                _classifier = DocClassifier(folder) if (folder / "coef.npy").exists() else None
            except (OSError, ValueError, KeyError):  # 파일이 깨졌으면 분류기만 건너뛴다
                _classifier = None
            _loaded = True
    return _classifier


def set_classifier(classifier: DocClassifier | None) -> None:
    """테스트용: 분류기를 직접 끼운다(None 이면 '없음'으로 고정)."""
    global _loaded, _classifier
    with _lock:
        _classifier, _loaded = classifier, True


def reset() -> None:
    """테스트용: 다음 호출 때 파일에서 다시 읽는다."""
    global _loaded, _classifier
    with _lock:
        _classifier, _loaded = None, False


def predict(text: str) -> Prediction | None:
    """글의 종류와 확률. 분류기·e5 모델이 없거나 계산이 실패하면 None."""
    classifier = get_classifier()
    if classifier is None:
        return None
    try:
        from app.features.ai_assistant.knowledge.embedding import OnnxE5Embedder, get_embedder

        embedder = get_embedder()
        if not isinstance(embedder, OnnxE5Embedder) or embedder.dim != classifier.embed_dim:
            return None  # 해시 임베딩 등 다른 모델이면 학습 때와 벡터가 달라 쓸 수 없다
        text = text[: classifier.max_chars]
        return classifier.predict(text, embedder.embed_passages([text])[0])
    except Exception:  # noqa: BLE001 — 임베딩(ONNX) 쪽 어떤 오류도 업로드를 막지 않는다
        return None
