"""Pixabay 클라이언트의 서버 측 요청 위조(SSRF) 방어 시험(L0, 외부 호출·이름 풀이 없음).

서버는 Pixabay 응답 JSON 이 가리키는 주소(largeImageURL·pageURL)를 그대로 내려받는다. 그래서 허용 호스트(공식 문서의 pixabay.com·cdn.pixabay.com)만,
https 만, 리다이렉트는 매번 같은 검사를 거쳐서, 내부망·메타데이터 주소로는 요청이 나가지 않아야 하고 크기·화소 상한이 있어야 한다.
"""

import io
import socket

import httpx
import pytest
from PIL import Image

from app.features.play import photo_rec_auto as auto
from app.features.play import photo_rec_pixabay as pix

_PUBLIC = lambda _host: None  # noqa: E731  이름 풀이를 하지 않는다(공개 주소로 본다)

GOOD_IMAGE = "https://pixabay.com/get/ed6a99fd0a76647_1280.jpg"  # 공식 문서의 largeImageURL 형태
GOOD_CDN = "https://cdn.pixabay.com/photo/2013/10/15/09/12/flower-195893_150.jpg"


def _png(size=(40, 20)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(out, "PNG")
    return out.getvalue()


def _client(handler, **kwargs) -> pix.PixabayClient:
    kwargs.setdefault("resolver", _PUBLIC)
    return pix.PixabayClient(
        "secret-key", httpx.Client(transport=httpx.MockTransport(handler)), gap=0, **kwargs
    )


def _hit(url: str, **extra) -> dict:
    return {
        "id": 1,
        "tags": "pizza",
        "largeImageURL": url,
        "pageURL": "https://pixabay.com/photos/x-1/",
        **extra,
    }


# ---- 주소 검사 ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [GOOD_IMAGE, GOOD_CDN, "https://PIXABAY.com/get/x.jpg", "https://pixabay.com:443/get/x.jpg"],
)
def test_the_documented_pixabay_hosts_are_allowed(url):
    assert pix.check_url(url, pix.IMAGE_HOSTS) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://pixabay.com/get/x.jpg",  # https 가 아니다
        "ftp://pixabay.com/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "//pixabay.com/get/x.jpg",  # 스킴 없음
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
        "https://10.0.0.5/x",
        "https://192.168.0.1/x",
        "https://[::1]/x",
        "https://2130706433/x",  # 10진 정수 IP(127.0.0.1)
        "https://0x7f000001/x",  # 16진 IP
        "https://0177.0.0.1/x",  # 8진 IP
        "https://internal.corp/x",
        "https://evil.com/x",
        "https://pixabay.com.evil.com/x",  # 접미사 속임
        "https://evilpixabay.com/x",
        "https://sub.cdn.pixabay.com/x",  # 하위 도메인은 목록에 없다
        "https://cdn.pixabay.com.evil.com/x",
        "https://pixabay.com@evil.com/x",  # 사용자 정보 속임
        "https://evil.com@pixabay.com/x",
        "https://user:pw@pixabay.com/x",
        "https://evil.com\\@pixabay.com/x",  # 역슬래시 속임
        "https://pixabay.com:8080/x",
        "https://pixabay.com:444/x",
        "https://pixabay.com/x y",  # 공백
        "https://pixabay.com/x\r\nHost: evil.com",  # 줄바꿈 주입
        "https://pixabay.com/x\x00",
        "",
        None,
        123,
    ],
)
def test_everything_else_is_refused(url):
    with pytest.raises(pix.UnsafeUrl):
        pix.check_url(url, pix.IMAGE_HOSTS)


def test_the_search_api_host_list_is_only_the_api_host():
    assert pix.API_HOSTS == {"pixabay.com"} and pix.API == "https://pixabay.com/api/"
    pix.check_url(pix.API, pix.API_HOSTS)
    with pytest.raises(pix.UnsafeUrl):
        pix.check_url(GOOD_CDN, pix.API_HOSTS)  # 검색은 cdn 호스트로 가지 않는다


# ---- 요청이 나가기 전에 막힌다 ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1:8000/admin",
        "https://evil.com/x.jpg",
        "https://pixabay.com@evil.com/x.jpg",
        "file:///etc/passwd",
    ],
)
def test_a_bad_image_address_never_sends_a_request(bad):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=_png())

    with pytest.raises(pix.PixabayError) as err:
        _client(handler).download(_hit(bad))
    assert calls == []
    assert bad not in str(err.value) and "secret-key" not in str(
        err.value
    )  # 오류 글에 주소·키가 없다


def test_hits_with_an_address_outside_the_allowed_hosts_are_not_candidates():
    assert pix.is_clean(_hit(GOOD_IMAGE))
    assert not pix.is_clean(_hit("https://evil.com/x.jpg"))
    assert not pix.is_clean(_hit("http://pixabay.com/x.jpg"))
    assert not pix.is_clean(_hit("https://169.254.169.254/x"))


def test_the_default_client_does_not_follow_redirects_by_itself():
    assert pix.PixabayClient("k")._client.follow_redirects is False


# ---- 리다이렉트 ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/x",
        "https://evil.com/x.jpg",
        "https://pixabay.com@evil.com/x.jpg",
        "//evil.com/x.jpg",
        "http://pixabay.com/get/x.jpg",  # https → http 로 내리는 리다이렉트
    ],
)
def test_a_redirect_to_an_unsafe_address_is_refused_and_not_requested(location):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, content=_png())

    with pytest.raises(pix.PixabayError):
        _client(handler).download(_hit(GOOD_IMAGE))
    assert calls == [GOOD_IMAGE]  # 두 번째 요청은 나가지 않았다


def test_a_redirect_between_allowed_hosts_is_followed_and_the_key_is_never_sent():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "pixabay.com":
            return httpx.Response(302, headers={"location": GOOD_CDN})
        return httpx.Response(200, content=_png())

    image = Image.open(io.BytesIO(_client(handler).download(_hit(GOOD_IMAGE))))
    assert image.format == "JPEG"
    assert [r.url.host for r in calls] == ["pixabay.com", "cdn.pixabay.com"]
    assert all("secret-key" not in str(r.url) and "key" not in r.url.params for r in calls)
    assert all("authorization" not in r.headers for r in calls)


def test_a_redirect_loop_stops_after_the_limit():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(302, headers={"location": GOOD_IMAGE})

    with pytest.raises(pix.PixabayError):
        _client(handler).download(_hit(GOOD_IMAGE))
    assert len(calls) == pix.MAX_REDIRECTS + 1


def test_a_redirect_on_search_to_another_host_is_refused_so_the_key_is_not_leaked():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://evil.com/steal"})

    with pytest.raises(pix.PixabayError) as err:
        _client(handler).search("pizza")
    assert [r.url.host for r in calls] == [
        "pixabay.com"
    ]  # 키가 든 요청은 pixabay.com 으로 한 번뿐이다
    assert "secret-key" not in str(err.value) and "evil.com" not in str(err.value)


# ---- 내부망 이름 풀이 -----------------------------------------------------------------------------------------------------
def _fake_resolution(monkeypatch, *addresses):
    def fake(host, port, **_kw):
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in addresses
        ]

    monkeypatch.setattr(pix.socket, "getaddrinfo", fake)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_an_allowed_host_that_resolves_to_a_private_address_is_refused(monkeypatch, address):
    _fake_resolution(monkeypatch, address)
    with pytest.raises(pix.UnsafeUrl):
        pix.assert_public_host("pixabay.com")


def test_one_private_address_among_public_ones_is_enough_to_refuse(monkeypatch):
    _fake_resolution(monkeypatch, "8.8.8.8", "10.0.0.1")
    with pytest.raises(pix.UnsafeUrl):
        pix.assert_public_host("cdn.pixabay.com")


def test_public_addresses_pass_and_unresolvable_names_are_refused(monkeypatch):
    _fake_resolution(monkeypatch, "8.8.8.8", "2606:4700::1111")
    pix.assert_public_host("pixabay.com")

    def fail(*_a, **_k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(pix.socket, "getaddrinfo", fail)
    with pytest.raises(pix.UnsafeUrl):
        pix.assert_public_host("pixabay.com")


def test_a_private_resolution_stops_the_download_before_any_request(monkeypatch):
    _fake_resolution(monkeypatch, "127.0.0.1")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=_png())

    client = pix.PixabayClient(
        "k", httpx.Client(transport=httpx.MockTransport(handler)), gap=0
    )  # 기본 이름 풀이
    with pytest.raises(pix.PixabayError):
        client.download(_hit(GOOD_IMAGE))
    with pytest.raises(pix.PixabayError):
        client.search("pizza")
    assert calls == []


# ---- 크기·화소 상한 -------------------------------------------------------------------------------------------------------
def test_a_body_over_the_byte_limit_is_refused_while_streaming(monkeypatch):
    monkeypatch.setattr(pix, "MAX_DOWNLOAD_BYTES", 1000)
    read = []

    def stream():
        for _ in range(50):
            read.append(1)
            yield b"x" * 100

    def handler(request):
        return httpx.Response(200, content=stream())

    with pytest.raises(pix.PixabayError):
        _client(handler).download(_hit(GOOD_IMAGE))
    assert len(read) < 50  # 상한을 넘자 끝까지 읽지 않고 멈췄다


def test_a_declared_length_over_the_limit_is_refused_before_reading(monkeypatch):
    monkeypatch.setattr(pix, "MAX_DOWNLOAD_BYTES", 1000)

    def handler(request):
        return httpx.Response(200, headers={"content-length": "999999999"}, content=b"x")

    with pytest.raises(pix.PixabayError):
        _client(handler).download(_hit(GOOD_IMAGE))


def test_an_image_with_too_many_pixels_is_refused_even_if_the_file_is_small(monkeypatch):
    monkeypatch.setattr(pix, "MAX_IMAGE_PIXELS", 100)  # 40×20=800 화소는 상한(100)을 넘는다

    def handler(request):
        return httpx.Response(200, content=_png((40, 20)))

    with pytest.raises(pix.PixabayError):
        _client(handler).download(_hit(GOOD_IMAGE))


def test_a_search_response_over_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(pix, "MAX_SEARCH_BYTES", 100)

    def handler(request):
        return httpx.Response(200, content=b'{"hits": []}' + b" " * 500)

    with pytest.raises(pix.PixabayError):
        _client(handler).search("pizza")


def test_a_normal_download_still_works_and_resizes():
    def handler(request):
        assert request.url.host == "pixabay.com" and "key" not in request.url.params
        return httpx.Response(200, content=_png((2000, 1000)))

    image = Image.open(io.BytesIO(_client(handler).download(_hit(GOOD_IMAGE))))
    assert image.format == "JPEG" and max(image.size) == 1280


# ---- 저장되는 출처 링크 ---------------------------------------------------------------------------------------------------
def test_the_stored_credit_link_is_only_a_pixabay_https_address():
    assert (
        pix.clean_credit_url("https://pixabay.com/photos/hamburger-494706/")
        == "https://pixabay.com/photos/hamburger-494706/"
    )
    for bad in ("javascript:alert(1)", "http://pixabay.com/x", "https://evil.com/x", "", None):
        assert pix.clean_credit_url(bad) is None
    safe = auto._credit(_hit(GOOD_IMAGE), "pizza")
    assert safe["credit_url"] == "https://pixabay.com/photos/x-1/"
    evil = auto._credit(_hit(GOOD_IMAGE, pageURL="https://evil.com/phish"), "pizza")
    assert evil["credit_url"] is None
