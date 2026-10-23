"""자동 분류 테스트. 진짜 언어 모델은 쓰지 않는다 — 가짜 모델로 받은 글자와 답을 확인한다."""

import io

import pytest
from PIL import Image

from app.features.ai_assistant.ingest.classify import classify
from app.features.ai_assistant.ingest.converters import OcrLine
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


class FakeLlm:
    def __init__(self, answer=None, error=False):
        self.answer = answer or {}
        self.error = error
        self.prompts = []

    def __call__(self, prompt, system=None):
        self.prompts.append(prompt + (system or ""))
        if self.error:
            raise LLMUnavailable("꺼짐")
        return self.answer


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


def test_model_gets_text_with_rrn_masked_and_no_filename(tmp_path):
    llm = FakeLlm({"doc_type": "학교 가정통신문", "is_document": True, "confidence": 0.9})
    r = ingest_file(
        "g01",
        NOTICE.encode("utf-8"),
        "지민_가정통신문.txt",
        store=LocalRawStore(tmp_path),
        llm=llm,
    )
    sent = "".join(llm.prompts)
    assert "현장체험학습" in sent  # 분류에 필요한 내용은 간다
    assert "3234567" not in sent  # 주민등록번호는 어떤 문서든 가린다
    assert "010-1234-5678" not in sent  # 일반 문서도 연락처는 가려서 보낸다
    assert "지민" not in sent  # 파일 이름도 안 간다
    assert r.classification.doc_type == "학교 가정통신문"
    assert r.classification.by == "model" and r.classification.route == "document"


def test_model_answer_is_cleaned_and_remasked():
    llm = FakeLlm(
        {
            "doc_type": "학교 가정통신문",
            "is_document": True,
            "tags": ["학교", "현장체험학습", "학교", 3, None],
            "dates": ["2026-10-15", "2026. 10. 20.", "내일", "2026-13-01"],
            "amounts": [{"label": "버스비", "value": "12,000원"}, {"label": "x", "value": "몰라"}],
            "places": ["국립중앙박물관"],
            "fields": {"제출 기한": "2026-10-20", "학생 주민번호": "150101-3234567", "": "x"},
            "confidence": 0.92,
        }
    )
    c = classify(text_result(NOTICE), llm)
    assert c.tags == ["학교", "현장체험학습", "3"]
    assert c.dates == ["2026-10-15", "2026-10-20"]
    assert [(a.label, a.value) for a in c.amounts] == [("버스비", 12000)]
    assert c.places == ["국립중앙박물관"]
    assert c.fields["제출 기한"] == "2026-10-20"
    assert "3234567" not in c.fields["학생 주민번호"]  # 모델 답의 주민등록번호도 가린다
    assert "" not in c.fields


def test_low_confidence_or_dead_model_goes_to_review():
    low = classify(text_result(NOTICE), FakeLlm({"doc_type": "안내문", "confidence": 0.3}))
    assert low.needs_review and low.route == "review" and low.doc_type == "안내문"
    dead = classify(text_result(NOTICE), FakeLlm(error=True))
    assert dead.needs_review and dead.by == "none" and dead.doc_type == "기타 문서"
    empty = classify(text_result(NOTICE), FakeLlm({"confidence": "높음"}))
    assert empty.needs_review and empty.doc_type == "기타 문서"


def test_not_a_document_goes_to_daily_share():
    c = classify(
        text_result("오늘 저녁은 김치찌개! 다들 일찍 와"),
        FakeLlm({"doc_type": "가족 메모", "is_document": False, "confidence": 0.8}),
    )
    assert c.route == "daily_share" and c.doc_type == "가족 메모"


def test_rules_skip_the_model():
    llm = FakeLlm(error=True)
    receipt = classify(
        text_result("영수증\n카드 승인번호 12345678\n합계 15,800원\n2026-10-21"), llm
    )
    assert receipt.doc_type == "영수증" and receipt.by == "rule"
    assert [(a.label, a.value) for a in receipt.amounts] == [("합계", 15800)]
    assert receipt.dates == ["2026-10-21"]
    bill = classify(text_result("관리비 고지서\n납기일 2026.10.25\n청구금액 231,500원"), llm)
    assert bill.doc_type == "고지서" and bill.route == "document"
    assert llm.prompts == []  # 규칙으로 정해지면 모델을 부르지 않는다


def test_prescription_never_reaches_the_model():
    llm = FakeLlm(error=True)
    r = text_result("처방전\n환자명 홍길동\n타이레놀정 1일투여 3회 투약일수 5일\n용법: 식후 30분")
    assert r.privacy.sensitive == "prescription"
    c = classify(r, llm)
    assert c.doc_type == "처방전" and c.by == "rule" and llm.prompts == []


def test_photo_without_text_and_failed_file():
    llm = FakeLlm(error=True)
    photo = preprocess(png(), "p.png", ocr=FakeOcr([]))
    assert classify(photo, llm).route == "daily_share"
    assert classify(preprocess(b"", "x"), llm) is None
    assert llm.prompts == []


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
        llm=FakeLlm(error=True),
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
    c = classify(text_result(NOTICE), FakeLlm(error=True), jev)
    assert c.needs_review and c.route == "review" and "기한" not in c.fields


def test_jev_not_a_document_goes_to_daily_share():
    jev = FakeJev(jev_answers(doc_type="일상 메모", is_doc=0.1))
    c = classify(text_result("오늘 저녁은 김치찌개! 다들 일찍 와"), FakeLlm(error=True), jev)
    assert c.route == "daily_share" and "deadline" not in jev.calls[0][1]


def test_unknown_type_is_named_locally_and_reviewed():
    llm = FakeLlm({"doc_type": "교회 주보", "is_document": True, "confidence": 0.9})
    c = classify(text_result(NOTICE), llm, FakeJev(jev_answers(doc_type="none")))
    assert c.doc_type == "교회 주보" and c.by == "model" and c.needs_review


def test_jev_failure_falls_back_to_local():
    llm = FakeLlm({"doc_type": "학교 가정통신문", "is_document": True, "confidence": 0.9})
    c = classify(text_result(NOTICE), llm, FakeJev(error=True))
    assert c.by == "model" and c.doc_type == "학교 가정통신문"
    broken = classify(text_result(NOTICE), llm, FakeJev({"doc_type": {}}))
    assert broken.by == "model"


def test_rules_and_prescriptions_never_reach_jev():
    jev = FakeJev(error=True)
    classify(text_result("관리비 고지서\n납기일 2026.10.25\n청구금액 231,500원"), None, jev)
    classify(text_result("처방전\n환자명 홍길동\n타이레놀정 투약일수 5일\n용법: 식후"), None, jev)
    assert jev.calls == []
