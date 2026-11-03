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


def test_no_pending_placeholders_left(client):
    # 운영자가 정해야 하던 자리(시행일·보호책임자·마이크)를 모두 채웠다. 다시 비워 두고 공개하지 않게 한다
    for path in PAGES:
        text = client.get(path).text
        assert "확정 필요" not in text
        assert "<mark>" not in text


def test_key_values_are_shown(client):
    text = client.get("/privacy").text
    assert "2026년 11월 3일" in text
    assert "개인정보 보호책임자: 백승득" in text
    assert "온디바이스" in text


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


def test_contact_email_is_in_the_body_when_configured(client, monkeypatch):
    # 꼬리말만이 아니라 방침 9항·약관 11조 본문에도 주소가 있어야 한다(꼬리말을 못 봐도 연락할 수 있게)
    monkeypatch.setattr(settings, "support_email", "help@example.com")
    link = '<a href="mailto:help@example.com">help@example.com</a>'
    assert f"문의 이메일: {link}" in client.get("/privacy").text
    assert f"서비스에 대한 문의: {link}" in client.get("/terms").text


def test_contact_falls_back_without_email(client, monkeypatch):
    monkeypatch.setattr(settings, "support_email", "")
    assert "문의: 운영자에게 연락해 주세요." in client.get("/privacy").text
    assert "서비스에 대한 문의: 운영자에게 연락해 주세요." in client.get("/terms").text
