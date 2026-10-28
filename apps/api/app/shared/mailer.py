"""메일 발송. 표준 라이브러리(smtplib)만 쓰고 별도 서비스·의존성을 추가하지 않는다.

- `MAIL_BACKEND=smtp` + `SMTP_*`: 실제 발송.
- `MAIL_BACKEND=console`: 개발 전용 — 메일 내용(토큰 포함)을 서버 로그에 남긴다. 로컬 SQLite 나 DEBUG=true 에서만 켜진다.
- 그 외(기본): 설정 없음. 이 경우 `ensure_mail_configured()` 가 503 `mail_not_configured` 를 내고 어떤 것도 "발송했다"고 처리하지 않는다.
테스트는 `set_mailer()` 로 가짜 발송기를 끼운다.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from functools import cache
from pathlib import Path
from typing import Protocol

from .config import settings
from .errors import ApiError

log = logging.getLogger(__name__)

MASCOT_CID = "gabee-mascot"  # HTML 의 <img src="cid:gabee-mascot"> 와 짝이다
_MASCOT_PATH = Path(__file__).parent / "assets" / "gabee-mascot.png"


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str  # 글자만 있는 본문(HTML 을 못 보는 메일 앱용)
    html: str | None = (
        None  # 있으면 HTML 본문도 함께 보낸다. cid:gabee-mascot 이미지는 메일에 내장된다
    )


@cache
def _mascot_png() -> bytes | None:
    """메일에 내장할 마스코트. 파일이 없으면 이미지만 빠지고 메일은 나간다."""
    try:
        return _MASCOT_PATH.read_bytes()
    except OSError:
        log.warning("메일용 마스코트 이미지를 읽지 못했다: %s", _MASCOT_PATH.name)
        return None


def _build_message(mail: Mail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, mail.to, mail.subject
    msg.set_content(mail.body)
    if mail.html is not None:
        msg.add_alternative(mail.html, subtype="html")
        image = _mascot_png() if f"cid:{MASCOT_CID}" in mail.html else None
        if image is not None:
            # inline + 파일명 없음: filename 이 있으면 attachment 로 붙어 메일 앱이 본문 이미지로 연결하지 않고 첨부로 보여 준다
            msg.get_payload()[1].add_related(
                image, "image", "png", cid=f"<{MASCOT_CID}>", disposition="inline"
            )
    return msg


class MailSendError(Exception):
    """발송 시도가 실패했다(SMTP 오류 등)."""


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpMailer:
    def send(self, mail: Mail) -> None:
        msg = _build_message(mail)
        try:
            if settings.smtp_security == "ssl":
                client = smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                )  # fmt: skip
            else:
                client = smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
                )
            with client:
                if settings.smtp_security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password)
                client.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            # 비밀번호·수신자·본문은 로그에 남기지 않는다
            log.error("메일 발송 실패: %s", type(exc).__name__)
            raise MailSendError(type(exc).__name__) from exc


class ConsoleMailer:
    def send(self, mail: Mail) -> None:
        log.warning("[개발용 메일 출력] to=%s subject=%s\n%s", mail.to, mail.subject, mail.body)


_override: Mailer | None = None


def set_mailer(mailer: Mailer | None) -> None:
    """테스트용: 가짜 발송기를 끼우거나(None 이면 해제) 한다."""
    global _override
    _override = mailer


def _dev_allowed() -> bool:
    return settings.debug or settings.database_url.startswith("sqlite")


def get_mailer() -> Mailer | None:
    """쓸 수 있는 발송기, 설정이 없거나 안전하지 않으면 None."""
    if _override is not None:
        return _override
    if settings.mail_backend == "smtp":
        if settings.smtp_host and settings.smtp_from:
            return SmtpMailer()
        return None
    if settings.mail_backend == "console" and _dev_allowed():
        return ConsoleMailer()
    return None


def ensure_mail_configured() -> Mailer:
    mailer = get_mailer()
    if mailer is None:
        raise ApiError(503, "mail_not_configured", "메일 발송이 아직 설정되지 않았어요")
    return mailer
