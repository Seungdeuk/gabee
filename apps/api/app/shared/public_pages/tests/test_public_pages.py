"""공개 안내 페이지(/, /privacy, /terms) 시험: 로그인 없이 열리고, HTML 이며, API 명세에는 없다."""

import pytest

from app.main import app
from app.shared.config import settings

PAGES = {"/": "가비", "/privacy": "개인정보처리방침", "/terms": "서비스 약관"}


@pytest.mark.parametrize("path,word", PAGES.items())
def test_pages_open_without_login(client, path, word):
    res = client.get(path)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert word in res.text
    assert '<html lang="ko">' in res.text


def test_pages_are_not_in_openapi():
    paths = app.openapi()["paths"]
    assert not {"/", "/privacy", "/terms"} & set(paths)


def test_privacy_covers_key_disclosures(client):
    text = client.get("/privacy").text
    for needle in (
        "수집하는 개인정보",
        "보유·이용 기간",
        "Anthropic",
        "Supabase",
        "만 14세",
        "강민훈",
        "delete-account.html",
        "이용자의 권리",
        "문의처",
        "카카오",
        "IP 주소",
        "TypeSafe",
        "90일",
    ):
        assert needle in text


def test_pending_items_are_visibly_marked(client):
    # 운영자가 채워야 하는 자리는 반드시 <mark> 안에 있어야 눈에 띈다(공개 전에 모두 채워 이 표시가 사라지게 한다)
    for path in ("/privacy", "/terms"):
        text = client.get(path).text
        assert text.count("【확정 필요") == text.count("<mark>【확정 필요")


def test_contact_email_only_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "support_email", "")
    assert "mailto:" not in client.get("/privacy").text
    monkeypatch.setattr(settings, "support_email", 'help@example.com"><script>')
    text = client.get("/privacy").text
    assert "<script>" not in text
    assert "mailto:help@example.com&quot;&gt;&lt;script&gt;" in text


@pytest.mark.parametrize("path", PAGES)
def test_head_requests_work(client, path):
    # 외부 검증 도구가 HEAD 로 주소를 확인할 수 있다
    res = client.head(path)
    assert res.status_code == 200
    assert res.text == ""
