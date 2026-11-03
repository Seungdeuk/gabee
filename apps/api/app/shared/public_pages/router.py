"""공개 안내 페이지 라우터: `/`(서비스 소개), `/privacy`(개인정보처리방침), `/terms`(서비스 약관).

구글 로그인 동의 화면 등 외부 서비스가 요구하는 공개 주소용이다. 로그인·DB 없이 고정 HTML 을 돌려주며,
API 명세(openapi.json)에는 넣지 않는다.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.shared.public_pages import pages

router = APIRouter(include_in_schema=False)

# 내용이 가끔 바뀌는 문서라 짧게만 캐시한다
_HEADERS = {
    "Cache-Control": "public, max-age=300",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
}


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home() -> HTMLResponse:
    """서비스 소개 페이지."""
    return HTMLResponse(pages.home(), headers=_HEADERS)


@router.api_route("/privacy", methods=["GET", "HEAD"], response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    """개인정보처리방침."""
    return HTMLResponse(pages.privacy(), headers=_HEADERS)


@router.api_route("/terms", methods=["GET", "HEAD"], response_class=HTMLResponse)
def terms() -> HTMLResponse:
    """서비스 약관."""
    return HTMLResponse(pages.terms(), headers=_HEADERS)
