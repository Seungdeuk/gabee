"""이 폴더의 시험은 운영처럼 Claude 가리기가 켜져 있고(가족 채팅 문서·사진은 가리기 없이는 등록되지 않는다) 가족 AI 동의가 켜진 가족을
기본으로 한다(가족 채팅 목적의 외부 전송은 동의가 있을 때만 일어난다). 가리기를 끄거나 동의 동작을 확인하는 시험은 스스로 바꾼다."""

import pytest

from tests.helpers import chat_masking_like_service, family_ai_consent_like_service


@pytest.fixture(autouse=True)
def _chat_masking_on(monkeypatch):
    chat_masking_like_service(monkeypatch)


@pytest.fixture(autouse=True)
def _family_ai_consent_on(monkeypatch):
    family_ai_consent_like_service(monkeypatch)
