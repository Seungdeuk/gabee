"""오류 메시지를 저장하기 전에 개인정보·식별자를 가린다.

규칙은 두 겹이다. ① 공용 개인정보 검출기(`app.shared.privacy.detect`)가 찾은 구간(전화·이메일·주민번호·카드·계좌·비밀 값·
주소·이름)을 가린다. ② 오류 메시지에 자주 섞이는 식별자(토큰, UUID, 12자리 이상 16진수 id, 주소의 쿼리, SQL 문과 파라미터,
`Key (...)=(...)` 값, 사용자 홈 경로)를 가린다.

탐지는 완전하지 않다(공용 검출기도 한국어 이름·주소를 놓칠 수 있다고 밝힌다). 그래서 길이를 제한하고, 검출기가 예외를 내면
메시지를 통째로 버린다. 원문을 어디에도 남기지 않는다: 이 함수의 반환값만 저장하고 로그에도 예외 클래스 이름만 쓴다.
"""

import logging
import re

from app.shared.privacy import detect

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 200
MAX_INPUT_LENGTH = 2000  # 검출기에 넘기는 길이의 상한(오류 메시지가 아주 길어도 느려지지 않게 한다)
MASK = "[가림]"
FAILED = "[메시지 가림 실패]"

# 먼저 잘라 내는 부분: SQLAlchemy 등이 메시지 뒤에 붙이는 SQL 문과 바인딩 값
_CUT_MARKERS = ("[SQL:", "[parameters:", "[Parameters:", "DETAIL:", "CONTEXT:")

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # 토큰류
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), MASK),  # JWT
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b(\s*[:=]\s*)\S+"
        ),
        r"\1\2" + MASK,
    ),
    # 식별자
    (
        re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
        MASK,
    ),  # UUID
    (
        re.compile(r"(?i)\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{12,}\b"),
        MASK,
    ),  # 12자 이상 16진수 id
    # 주소: 쿼리와 조각은 값이 섞이므로 떼어 낸다(경로 자체는 남긴다)
    (re.compile(r"(\bhttps?://[^\s?#]+)[?#]\S*"), r"\1"),
    # PostgreSQL 제약 위반 메시지: Key (email)=(a@b.c) already exists
    (re.compile(r"(?i)Key \(([^)]*)\)=\((.*?)\)"), r"Key (\1)=(" + MASK + ")"),
    # IPv4 주소: 요청한 사람의 IP 가 메시지에 섞일 수 있어 가린다(서버 쪽 주소도 함께 가려진다)
    (re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), MASK),
    # 사용자 홈 경로 (사용자 이름)
    (re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)[^\\/\s]+"), r"\1" + MASK),
    (re.compile(r"(/(?:home|Users)/)[^/\s]+"), r"\1" + MASK),
)


def _cut(text: str) -> str:
    cut = len(text)
    for marker in _CUT_MARKERS:
        i = text.find(marker)
        if i != -1:
            cut = min(cut, i)
    return text[:cut]


def _mask_detected(text: str) -> str:
    for span in sorted(detect(text), key=lambda s: s.start, reverse=True):
        text = text[: span.start] + MASK + text[span.end :]
    return text


def mask_message(message: object) -> str:
    """오류 메시지를 저장해도 되는 문자열로 바꾼다. 비어 있으면 빈 문자열, 가림에 실패하면 FAILED 를 돌려준다."""
    if message is None:
        return ""
    try:
        text = " ".join(str(message).split())[:MAX_INPUT_LENGTH]  # 줄바꿈·공백을 한 칸으로
        text = _cut(text).strip()
        if not text:
            return ""
        text = _mask_detected(text)
        for pattern, repl in _RULES:
            text = pattern.sub(repl, text)
        return text[:MAX_MESSAGE_LENGTH]
    except Exception as exc:  # 가림이 실패하면 원문을 남기느니 버린다
        logger.warning("ops error message masking failed: %s", type(exc).__name__)
        return FAILED
