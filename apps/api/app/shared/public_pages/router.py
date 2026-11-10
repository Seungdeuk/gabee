"""공개 안내 페이지 라우터: `/`(서비스 소개), `/privacy`(개인정보처리방침), `/terms`(서비스 약관).

구글 로그인 동의 화면 등 외부 서비스가 요구하는 공개 주소용이다. 로그인·DB 없이 고정 HTML 을 돌려주며,
API 명세(openapi.json)에는 넣지 않는다.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.shared.public_pages import pages

router = APIRouter(include_in_schema=False)

KAKAO_APP_RETURN = (
    "gabee://kakao"  # 앱이 받는 주소(app.json scheme). 돌아갈 곳은 항상 이 주소로 고정한다
)
_KAKAO_FORWARD = ("code", "state", "error", "error_description")  # 앱에 넘기는 값은 이 네 가지뿐
_KAKAO_MAX_LEN = 2048

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


@router.get("/auth/kakao/callback")
def kakao_callback(request: Request) -> Response:
    """카카오 로그인 중계: 카카오는 사용자 지정 앱 주소(gabee://)를 Redirect URI 로 받지 않아서,
    https 주소(이 경로)로 돌려받은 인증 코드를 앱 주소로 그대로 넘겨 준다.

    돌아갈 곳은 `gabee://kakao` 로 고정이고(열린 리다이렉트 없음), 코드와 state 는 서버가 저장·검증하지 않는다.
    코드는 앱의 PKCE 검증값(code_verifier) 없이는 토큰으로 바꿀 수 없다. 로그인 실패(`error`)도 앱에 그대로 넘긴다.
    응답은 302 이다(브라우저는 302 의 본문을 그리지 않으니 본문은 리다이렉트를 따르지 않는 클라이언트용이다).
    실기기에서 외부 앱 주소 이동이 막혀 빈 화면이 되면 200 + 이동 버튼 페이지로 바꾼다.
    """
    query = request.query_params
    params = {
        k: query[k] for k in _KAKAO_FORWARD if query.get(k) and len(query[k]) <= _KAKAO_MAX_LEN
    }  # 너무 긴 값은 버린다
    target = KAKAO_APP_RETURN + (f"?{urlencode(params)}" if params else "")
    headers = {
        **_HEADERS,
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",  # 주소의 인증 코드가 다른 사이트로 새지 않게
        "Location": target,
    }
    return HTMLResponse(pages.kakao_return(target), status_code=302, headers=headers)
