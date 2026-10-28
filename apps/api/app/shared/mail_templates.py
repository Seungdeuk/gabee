"""인증·재설정 메일의 HTML 본문. 마스코트는 mailer 가 cid 로 내장하고, 링크는 넣지 않는다(코드를 앱에 입력하는 방식)."""

from html import escape

from .mailer import MASCOT_CID


def code_mail_html(
    *, title: str, intro: str, code_label: str, code: str, ttl: str, notice: str
) -> str:
    """6자리 코드 메일. 모든 값은 escape 한다(코드는 숫자지만 습관적으로 같은 경로를 쓴다)."""
    e = escape
    return f"""<!doctype html>
<html lang="ko"><body style="margin:0;padding:0;background:#fffaf0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fffaf0;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:420px;background:#ffffff;border-radius:16px;padding:28px 24px;font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#4a3426;">
<tr><td align="center"><img src="cid:{MASCOT_CID}" width="96" height="96" alt="가비" style="display:block;border-radius:20px;"></td></tr>
<tr><td align="center" style="padding-top:16px;font-size:18px;font-weight:700;">{e(title)}</td></tr>
<tr><td align="center" style="padding-top:8px;font-size:14px;line-height:1.6;">{e(intro)}</td></tr>
<tr><td align="center" style="padding-top:20px;font-size:13px;color:#8a6f5a;">{e(code_label)}</td></tr>
<tr><td align="center" style="padding-top:6px;"><span style="display:inline-block;background:#fdf1d6;border-radius:12px;padding:12px 22px;font-size:32px;font-weight:700;letter-spacing:8px;color:#4a3426;">{e(code)}</span></td></tr>
<tr><td align="center" style="padding-top:14px;font-size:13px;color:#8a6f5a;">{e(ttl)} 안에 한 번만 쓸 수 있어요.</td></tr>
<tr><td align="center" style="padding-top:22px;font-size:12px;line-height:1.6;color:#a8917e;">{e(notice)}</td></tr>
</table>
</td></tr></table>
</body></html>"""
