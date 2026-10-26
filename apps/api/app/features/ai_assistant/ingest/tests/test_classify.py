"""자동 분류 테스트. 진짜 분류기·Jev 는 쓰지 않는다 — 가짜를 끼워 받은 글자와 답을 확인한다."""

import io

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import classify as classify_module
from app.features.ai_assistant.ingest import doc_classifier
from app.features.ai_assistant.ingest.classify import classify
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.ingest.doc_classifier import Prediction
from app.features.ai_assistant.ingest.raw_store import LocalRawStore
from app.features.ai_assistant.ingest.service import ingest_file, preprocess
from app.shared.config import settings
from app.shared.llm.client import LLMUnavailable


@pytest.fixture(autouse=True)
def no_real_jev(monkeypatch):
    """개발자 .env 에 키가 있어도 테스트는 진짜 Jev 를 부르지 않는다."""
    monkeypatch.setattr(settings, "typesafe_api_key", "")


class FakeOcr:
    def __init__(self, lines):
        self.lines = [OcrLine(t, 0.95) for t in lines]

    def read(self, image):
        return self.lines


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(buf, "PNG")
    return buf.getvalue()


def text_result(text: str):
    return preprocess(text.encode("utf-8"), "a.txt")


NOTICE = """현장체험학습 안내
학부모님께
2026년 10월 15일(목) 3학년 현장체험학습을 국립중앙박물관으로 갑니다.
버스비 12,000원은 스쿨뱅킹으로 납부합니다.
참가 신청서를 2026. 10. 20.까지 담임선생님께 제출해 주세요.
담임 성명: 김영희 / 연락처 010-1234-5678
학생 주민등록번호 150101-3234567
"""


class FakeClassifier:
    """doc_classifier.predict 자리에 끼우는 가짜: 정해 둔 종류·확률을 돌려주고 받은 글을 적어 둔다."""

    def __init__(self, kind="학교 가정통신문", confidence=0.93):
        self.guess = Prediction(kind, confidence)
        self.texts = []

    def __call__(self, text):
        self.texts.append(text)
        return self.guess


@pytest.fixture
def fake_classifier(monkeypatch):
    def install(kind="학교 가정통신문", confidence=0.93):
        fake = FakeClassifier(kind, confidence)
        monkeypatch.setattr(doc_classifier, "predict", fake)
        return fake

    return install


def test_classifier_confident_answer_is_used_without_jev(fake_classifier):
    clf = fake_classifier("학교 가정통신문", 0.93)
    jev = FakeJev(error=True)
    c = classify(text_result(NOTICE), jev)
    assert (c.doc_type, c.by, c.route) == ("학교 가정통신문", "classifier", "document")
    assert c.confidence == 0.93 and c.tags == ["학교 가정통신문"] and not c.needs_review
    assert c.dates == ["2026-10-15", "2026-10-20"]  # 날짜·금액은 정규식이 찾는다
    assert [(a.label, a.value) for a in c.amounts] == [("버스비", 12000)]
    assert c.places == [] and c.fields == {}  # 장소·중요 칸은 분류기가 만들지 않는다
    assert jev.calls == []
    assert "3234567" not in clf.texts[0] and "010-1234-5678" not in clf.texts[0]  # 가린 글자만 간다


def test_classifier_threshold_is_inclusive_at_0_7(fake_classifier):
    fake_classifier("학교 가정통신문", 0.7)
    assert classify(text_result(NOTICE)).by == "classifier"


def test_unsure_classifier_without_jev_goes_to_review(fake_classifier):
    fake_classifier("학교 가정통신문", 0.69)
    c = classify(text_result(NOTICE))
    assert c.needs_review and c.route == "review" and c.by == "none" and c.doc_type == "기타 문서"


def test_unsure_classifier_with_jev_uses_jev(fake_classifier):
    fake_classifier("임대차 계약서", 0.4)
    jev = FakeJev(jev_answers())
    c = classify(text_result(NOTICE), jev)
    assert (c.doc_type, c.by) == ("학교 가정통신문", "jev") and len(jev.calls) == 1


def test_missing_classifier_files_do_not_break_classification():
    # conftest 가 분류기를 '없음'으로 고정한 상태 = 모델 파일이 없는 테스트·CI 환경
    assert doc_classifier.predict(NOTICE) is None
    assert classify(text_result(NOTICE)).needs_review
    c = classify(text_result(NOTICE), FakeJev(jev_answers()))
    assert c.by == "jev"


def test_jev_key_in_settings_is_used_when_classifier_is_unsure(monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "k")
    jev = FakeJev(jev_answers())
    monkeypatch.setattr(classify_module.jev_api, "ask", jev)
    assert classify(text_result(NOTICE)).by == "jev"


def test_ingest_passes_masked_text_and_no_filename_to_jev(tmp_path):
    jev = FakeJev(jev_answers())
    ingest_file(
        "g01", NOTICE.encode("utf-8"), "지민_가정통신문.txt", store=LocalRawStore(tmp_path), jev=jev
    )
    sent = repr(jev.calls[0])
    assert "현장체험학습" in sent and "3234567" not in sent and "지민" not in sent


def test_rules_skip_classifier_and_jev(fake_classifier):
    clf = fake_classifier()
    jev = FakeJev(error=True)
    receipt = classify(
        text_result("영수증\n카드 승인번호 12345678\n합계 15,800원\n2026-10-21"), jev
    )
    assert receipt.doc_type == "영수증" and receipt.by == "rule"
    assert [(a.label, a.value) for a in receipt.amounts] == [("합계", 15800)]
    assert receipt.dates == ["2026-10-21"]
    bill = classify(text_result("관리비 고지서\n납기일 2026.10.25\n청구금액 231,500원"), jev)
    assert bill.doc_type == "고지서" and bill.route == "document"
    assert clf.texts == [] and jev.calls == []  # 규칙으로 정해지면 분류기도 Jev 도 부르지 않는다


def test_prescription_never_reaches_classifier_or_jev(fake_classifier):
    clf = fake_classifier()
    jev = FakeJev(error=True)
    r = text_result("처방전\n환자명 홍길동\n타이레놀정 1일투여 3회 투약일수 5일\n용법: 식후 30분")
    assert r.privacy.sensitive == "prescription"
    c = classify(r, jev)
    assert c.doc_type == "처방전" and c.by == "rule" and clf.texts == [] and jev.calls == []


def test_photo_without_text_and_failed_file(fake_classifier):
    clf = fake_classifier()
    photo = preprocess(png(), "p.png", ocr=FakeOcr([]))
    assert classify(photo).route == "daily_share"
    assert classify(preprocess(b"", "x")) is None
    assert clf.texts == []


def test_ocr_garbage_on_a_photo_is_still_a_photo_without_text(fake_classifier):
    # 풍경 사진에서 OCR 이 "ak" 같은 찌꺼기를 읽어도 일상 메모 같은 짧은 글 종류로 끌려가면 안 된다
    clf = fake_classifier(kind="일상 메모", confidence=0.95)
    garbage = preprocess(png(), "p.png", ocr=FakeOcr(["ak", "-"]))
    c = classify(garbage)
    assert c.doc_type == "사진" and c.route == "daily_share" and c.by == "rule"
    assert clf.texts == []
    # 글자가 충분히 있는 사진은 그대로 분류기로 간다
    sign = preprocess(png(), "p.png", ocr=FakeOcr(["새봄초등학교 가정통신문", "현장체험학습 안내"]))
    assert classify(sign).by == "classifier" and len(clf.texts) == 1


class FakeJev:
    def __init__(self, answers=None, error=False):
        self.answers = answers or {}
        self.error = error
        self.calls = []

    def __call__(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise LLMUnavailable("꺼짐")
        return self.answers


def jev_answers(doc_type="학교 가정통신문", conf=0.93, is_doc=0.97, **extra):
    return {
        "doc_type": {"choice": doc_type, "confidence": conf, "probabilities": {}},
        "is_document": {"noul": is_doc},
        "domain": {"choice": "학교·교육", "confidence": 0.9},
        **extra,
    }


def test_jev_gets_masked_text_and_candidates_only(tmp_path):
    jev = FakeJev(
        jev_answers(
            deadline={"choice": "2026-10-20", "confidence": 0.88},
            main_amount={"choice": "버스비 12,000원", "confidence": 0.9},
        )
    )
    r = ingest_file(
        "g01",
        NOTICE.encode("utf-8"),
        "지민_가정통신문.txt",
        store=LocalRawStore(tmp_path),
        jev=jev,
    )
    state, questions = jev.calls[0]
    sent = repr(state) + repr(questions)
    assert "현장체험학습" in sent
    assert "3234567" not in sent and "지민" not in sent
    assert state["date_candidates"] == ["2026-10-15", "2026-10-20"]
    assert "버스비 12,000원" in state["amount_candidates"]
    assert set(questions["deadline"]["criteria"]) == {"2026-10-15", "2026-10-20", "없음"}
    c = r.classification
    assert (c.doc_type, c.by, c.route) == ("학교 가정통신문", "jev", "document")
    assert c.tags == ["학교 가정통신문", "학교·교육"]
    assert c.fields == {"기한": "2026-10-20", "주요 금액": "버스비 12,000원"}
    assert c.amounts[0].label == "버스비"


def test_jev_low_confidence_or_unsure_picks_are_not_trusted():
    jev = FakeJev(jev_answers(conf=0.4, deadline={"choice": "2026-10-20", "confidence": 0.3}))
    c = classify(text_result(NOTICE), jev)
    assert c.needs_review and c.route == "review" and "기한" not in c.fields


def test_jev_not_a_document_goes_to_daily_share():
    jev = FakeJev(jev_answers(doc_type="일상 메모", is_doc=0.1))
    c = classify(text_result("오늘 저녁은 김치찌개! 다들 일찍 와"), jev)
    assert c.route == "daily_share" and "deadline" not in jev.calls[0][1]


def test_jev_unknown_type_goes_to_review():
    for answers in (jev_answers(doc_type="none"), jev_answers(doc_type="교회 주보")):
        c = classify(text_result(NOTICE), FakeJev(answers))
        assert c.doc_type == "기타 문서" and c.needs_review and c.route == "review"
        assert c.by == "none"


def test_jev_failure_goes_to_review():
    for jev in (FakeJev(error=True), FakeJev({"doc_type": {}})):
        c = classify(text_result(NOTICE), jev)
        assert c.doc_type == "기타 문서" and c.needs_review and c.route == "review"


def test_rules_and_prescriptions_never_reach_jev():
    jev = FakeJev(error=True)
    classify(text_result("관리비 고지서\n납기일 2026.10.25\n청구금액 231,500원"), jev)
    classify(text_result("처방전\n환자명 홍길동\n타이레놀정 투약일수 5일\n용법: 식후"), jev)
    assert jev.calls == []
