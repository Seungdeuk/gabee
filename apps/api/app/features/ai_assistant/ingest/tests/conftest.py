import pytest

from app.features.ai_assistant.ingest import doc_classifier


@pytest.fixture(autouse=True)
def no_real_doc_classifier():
    """서버 PC 에 분류기 파일이 있어도 테스트는 '분류기 없음'에서 시작한다(필요한 테스트가 직접 끼운다)."""
    doc_classifier.set_classifier(None)
    yield
    doc_classifier.reset()
