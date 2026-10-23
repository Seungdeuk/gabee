"""회원가입 입력값 규칙(아이디·이메일·비밀번호·이름)과 정규화. 규칙을 바꾸면 docs/requirements/family-group.md 도 고친다.

규칙 위반은 `ApiError(400, <code>, <한국어 메시지>)` 로 알린다(공통 에러 형식 {"code","message"}).
"""

import re

from app.shared.errors import ApiError

LOGIN_ID_MIN, LOGIN_ID_MAX = 4, 32  # users.login_id 는 String(32)
PASSWORD_MIN, PASSWORD_MAX = 8, 128  # 상한은 해시 비용을 이용한 요청 부풀리기를 막는다
EMAIL_MAX = 255  # users.email 은 String(255)
NAME_MAX = 40

_LOGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# 실무적인 이메일 검사: 한 개의 @, 공백 없음, 도메인에 점. (RFC 전체 구현이 아니라 오타·명백한 오류를 거른다)
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
# 시스템·운영용으로 보여 사칭에 쓰일 수 있는 아이디
RESERVED_LOGIN_IDS = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "system",
        "support",
        "gabee",
        "null",
        "undefined",
        "anonymous",
    }
)


def normalize_login_id(raw: str) -> str:
    """아이디는 대소문자를 구분하지 않는다 — 앞뒤 공백을 지우고 소문자로 저장한다."""
    login_id = raw.strip().lower()
    if not LOGIN_ID_MIN <= len(login_id) <= LOGIN_ID_MAX:
        raise ApiError(
            400, "invalid_login_id", f"아이디는 {LOGIN_ID_MIN}~{LOGIN_ID_MAX}자로 입력해 주세요"
        )
    if not _LOGIN_ID_RE.match(login_id):
        raise ApiError(
            400,
            "invalid_login_id",
            "아이디는 영문 소문자로 시작하고 영문 소문자·숫자·밑줄(_)만 쓸 수 있어요",
        )
    if login_id in RESERVED_LOGIN_IDS:
        raise ApiError(400, "invalid_login_id", "사용할 수 없는 아이디예요")
    return login_id


def normalize_email(raw: str) -> str:
    """이메일은 앞뒤 공백을 지우고 소문자로 저장한다(대소문자만 다른 중복 가입을 막는다)."""
    email = raw.strip().lower()
    if len(email) > EMAIL_MAX or not _EMAIL_RE.match(email) or ".." in email:
        raise ApiError(400, "invalid_email", "이메일 형식이 올바르지 않아요")
    local = email.split("@", 1)[0]
    if len(local) > 64:
        raise ApiError(400, "invalid_email", "이메일 형식이 올바르지 않아요")
    return email


def validate_password(password: str, login_id: str, email: str) -> None:
    """길이 8~128, 문자(영문·한글 등)와 숫자를 모두 포함, 아이디·이메일 아이디와 같거나 담고 있지 않아야 한다.
    비밀번호는 공백을 포함해 입력 그대로 쓴다(정규화·trim 하지 않는다)."""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ApiError(
            400, "weak_password", f"비밀번호는 {PASSWORD_MIN}~{PASSWORD_MAX}자로 입력해 주세요"
        )
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ApiError(400, "weak_password", "비밀번호에는 문자와 숫자가 모두 들어가야 해요")
    lowered = password.lower()
    email_local = email.split("@", 1)[0]
    if login_id in lowered or (len(email_local) >= 4 and email_local in lowered):
        raise ApiError(400, "weak_password", "비밀번호에 아이디나 이메일 아이디를 넣을 수 없어요")


def normalize_name(raw: str) -> str:
    name = " ".join(raw.split())  # 앞뒤·연속 공백 정리
    if not 1 <= len(name) <= NAME_MAX:
        raise ApiError(400, "invalid_name", f"이름은 1~{NAME_MAX}자로 입력해 주세요")
    return name
