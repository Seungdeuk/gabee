"""공개 안내 페이지(서비스 소개·개인정보처리방침·서비스 약관)의 공통 HTML 틀.

로그인 없이 누구나 읽는 정적 페이지라 DB·사용자 입력을 쓰지 않는다. 본문은 이 패키지의 코드에 적은 고정 문구이고,
`html.escape` 를 거치지 않고 그대로 넣으므로 사용자 입력이나 외부 값을 본문에 섞지 않는다.
"""

import html

from app.shared.config import settings

SERVICE_NAME = "가비"

_STYLE = """
:root{--bg:#fffaf3;--card:#ffffff;--text:#3b2f27;--sub:#7a6a5e;--accent:#e8895c;--line:#eadfd3}
@media (prefers-color-scheme: dark){:root{--bg:#1f1a16;--card:#2a231e;--text:#f3ebe3;--sub:#b9a999;--accent:#f0a07a;--line:#3d332b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,"Noto Sans KR","Malgun Gothic",sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 20px 64px}
header.site{max-width:760px;margin:0 auto;padding:20px 20px 0;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header.site a{color:var(--sub);text-decoration:none;font-size:14px}
header.site a.brand{color:var(--accent);font-weight:700;font-size:20px}
h1{font-size:28px;margin:8px 0 4px}
h2{font-size:20px;margin:32px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
p,li{color:var(--text)}
.sub{color:var(--sub);font-size:14px;margin:0 0 24px}
ul,ol{padding-left:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin:16px 0}
table{width:100%;border-collapse:collapse;font-size:15px;margin:12px 0}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--card)}
footer{max-width:760px;margin:0 auto;padding:0 20px 40px;color:var(--sub);font-size:13px}
footer a{color:var(--sub)}
"""

_NAV = (
    ("/", "서비스 소개"),
    ("/privacy", "개인정보처리방침"),
    ("/terms", "서비스 약관"),
)


def contact_html() -> str:
    """문의 이메일 문구(설정 SUPPORT_EMAIL 이 있을 때만). 값은 운영자가 정한 설정이라 이스케이프해 넣는다.

    @returns: " · 문의 <a ...>이메일</a>" 또는 빈 문자열
    """
    email = html.escape(settings.support_email.strip(), quote=True)
    return f' · 문의 <a href="mailto:{email}">{email}</a>' if email else ""


def page(title: str, body: str) -> str:
    """공통 머리말·꼬리말로 감싼 완성된 HTML 문서.

    @param title: 브라우저 탭 제목(고정 문구)
    @param body: `<main>` 안에 들어갈 본문 HTML(고정 문구)
    @returns: HTML 문자열
    """
    nav = "".join(f'<a href="{href}">{label}</a>' for href, label in _NAV)
    contact = contact_html()
    return (
        "<!doctype html>"
        '<html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} · {SERVICE_NAME}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<header class="site"><a class="brand" href="/">{SERVICE_NAME}</a>{nav}</header>'
        f"<main>{body}</main>"
        f"<footer>© {SERVICE_NAME}{contact}</footer>"
        "</body></html>"
    )
