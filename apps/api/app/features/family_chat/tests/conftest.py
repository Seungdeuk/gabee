"""이 폴더의 시험은 운영처럼 Claude 가리기가 켜진 상태를 기본으로 한다(가족 채팅 문서·사진은 가리기 없이는 등록되지 않는다). 가리기를 끄는 시험은 스스로 끈다."""

import pytest

from tests.helpers import chat_masking_like_service


@pytest.fixture(autouse=True)
def _chat_masking_on(monkeypatch):
    chat_masking_like_service(monkeypatch)
