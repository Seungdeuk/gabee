"""문서 분류기(numpy) 테스트. 학습 스크립트가 만든 작은 기준 파일(tests/data/doc_classifier)로 scikit-learn 과 같은 확률이 나오는지 확인한다.
scikit-learn 은 테스트에서 쓰지 않는다(기준 확률이 reference.json 에 들어 있다)."""

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from app.features.ai_assistant.ingest import doc_classifier
from app.features.ai_assistant.ingest.doc_classifier import DocClassifier

FIXTURE = Path(__file__).parent / "data" / "doc_classifier"
API_ROOT = Path(__file__).resolve().parents[5]
REAL_CLASSIFIER = API_ROOT / "data" / "models" / "doc-classifier"
REAL_EMBEDDER = API_ROOT / "data" / "models" / "e5-small-ft"


@pytest.fixture(scope="module")
def reference():
    return json.loads((FIXTURE / "reference.json").read_text(encoding="utf-8"))


def test_numpy_probabilities_match_sklearn_reference(reference):
    clf = DocClassifier(FIXTURE)
    assert clf.classes == reference["classes"]
    for case in reference["cases"]:
        got = clf.probabilities(case["text"], case["emb"])
        # 저장한 계수가 float32 라 소수 6~7자리까지만 같다
        np.testing.assert_allclose(got, case["proba"], atol=1e-5, err_msg=repr(case["text"]))
        assert abs(got.sum() - 1) < 1e-9


def test_predict_returns_the_top_class(reference):
    clf = DocClassifier(FIXTURE)
    case = reference["cases"][0]
    pred = clf.predict(case["text"], case["emb"])
    best = int(np.argmax(case["proba"]))
    assert pred.kind == reference["classes"][best]
    assert pred.confidence == pytest.approx(case["proba"][best], abs=1e-5)


def test_char_wb_ngrams_follow_sklearn_rules():
    clf = DocClassifier(FIXTURE)
    # 소문자화, 공백으로 나눈 낱말을 앞뒤 공백으로 감싸 2~4글자씩. 짧은 낱말("x" → " x ")은 n 마다 한 번만 센다
    assert clf._ngrams("AB  c") == [" a", "ab", "b ", " ab", "ab ", " ab ", " c", "c ", " c "]
    assert clf._ngrams("") == []


def test_text_without_known_ngrams_still_gives_probabilities(reference):
    clf = DocClassifier(FIXTURE)
    p = clf.probabilities("ㅋㅋㅋ", reference["cases"][0]["emb"])
    assert abs(p.sum() - 1) < 1e-9 and p.shape == (len(clf.classes),)


def test_missing_files_mean_no_classifier(monkeypatch, tmp_path):
    monkeypatch.setenv("DOC_CLASSIFIER_DIR", str(tmp_path / "없는 폴더"))
    doc_classifier.reset()
    assert doc_classifier.get_classifier() is None
    assert doc_classifier.predict("학부모님께 현장체험학습 안내") is None  # 서버가 죽지 않고 None


def test_broken_files_mean_no_classifier(monkeypatch, tmp_path):
    (tmp_path / "coef.npy").write_bytes(b"not numpy")
    monkeypatch.setenv("DOC_CLASSIFIER_DIR", str(tmp_path))
    doc_classifier.reset()
    assert doc_classifier.get_classifier() is None


def test_classifier_without_onnx_embedder_is_skipped(monkeypatch):
    from app.features.ai_assistant.knowledge import embedding

    doc_classifier.set_classifier(DocClassifier(FIXTURE))
    embedding.set_embedder(embedding.HashingEmbedder())  # e5 모델이 없을 때 쓰는 해시 임베딩
    try:
        assert doc_classifier.predict("안내문") is None
    finally:
        embedding.set_embedder(None)


def test_loads_once_even_with_many_threads(monkeypatch):
    monkeypatch.setenv("DOC_CLASSIFIER_DIR", str(FIXTURE))
    doc_classifier.reset()
    loads = []
    original = DocClassifier.__init__

    def counting_init(self, folder):
        loads.append(folder)
        original(self, folder)

    monkeypatch.setattr(DocClassifier, "__init__", counting_init)
    found = []
    threads = [
        threading.Thread(target=lambda: found.append(doc_classifier.get_classifier()))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1 and len({id(c) for c in found}) == 1 and found[0] is not None


# 실제 분류기·e5 모델 파일이 있는 서버 PC 에서만 도는 점검(CI 에는 파일이 없다)
@pytest.mark.skipif(
    not (REAL_CLASSIFIER / "coef.npy").exists() or not (REAL_EMBEDDER / "model.onnx").exists(),
    reason="서버 PC 분류기·모델 파일이 없는 환경",
)
def test_real_classifier_knows_common_documents_and_doubts_strange_ones():
    from app.features.ai_assistant.knowledge.embedding import OnnxE5Embedder

    clf = DocClassifier(REAL_CLASSIFIER)
    emb = OnnxE5Embedder(REAL_EMBEDDER)

    def ask(text):
        return clf.predict(text, emb.embed_passages([text])[0])

    wedding = ask(
        "청첩장\n저희 두 사람이 사랑과 믿음으로 결혼합니다. 바쁘시더라도 오셔서 축복해 주세요.\n"
        "2026년 11월 14일 토요일 오후 1시 신랑 김민수 신부 이서연 서울 웨딩홀 3층"
    )
    assert wedding.kind == "청첩장" and wedding.confidence >= 0.7
    notice = ask(
        "가정통신문\n학부모님께\n3학년 현장체험학습을 국립중앙박물관으로 갑니다. 참가 신청서를 담임선생님께 제출해 주세요."
    )
    assert notice.kind == "학교 가정통신문" and notice.confidence >= 0.7
    odd = ask("오늘 저녁은 김치찌개! 다들 일찍 와")
    assert odd.confidence < 0.7  # 학습한 어떤 종류도 아니면 확정하지 않는다
