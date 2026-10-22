"""비밀번호 해시(Argon2id). 비밀번호 원문은 저장·로그하지 않고, 이 모듈의 해시만 `users.password_hash` 에 둔다.

파라미터는 argon2-cffi 기본값(RFC 9106 의 저메모리 권장값: 메모리 64MiB, 반복 3, 병렬 4)이다.
검증에 성공했는데 파라미터가 옛날 값이면 `needs_rehash` 로 로그인 때 새 해시로 바꿀 수 있다.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # 기본 type=Argon2id


def hash_password(password: str) -> str:
    """비밀번호를 Argon2id 로 해시한다(솔트 자동 생성, `$argon2id$...` 형식)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """비밀번호가 해시와 맞으면 True. 형식이 깨진 해시도 False(예외를 밖으로 내보내지 않는다)."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """현재 파라미터와 달라서 다음 로그인 때 다시 해시해야 하면 True."""
    return _hasher.check_needs_rehash(password_hash)
