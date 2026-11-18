"""평가 프로세스 안에서만 합성 id 를 '전화번호로 오인되지 않는' 값으로 만든다. 운영 코드는 바꾸지 않는다.

배경: 앱은 id 를 `uuid.uuid4().hex[:12]`(12자리 hex)로 만든다. 이 값이 `0` 으로 시작하고 숫자가 9개 이상 이어지면(예: `0212345678ab`) 전화번호 규칙이
PHONE 으로 탐지한다. 합성 월드를 사례·반복마다 새로 만들기 때문에 전송 본문 점검(preflight 4번)이 id 하나당 약 0.09% 확률로 간헐 실패했다.
첫 글자만 피해서는 부족할 수 있어(숫자만 이어지는 긴 구간 자체가 계좌·번호 규칙의 재료다), id 안의 '숫자만 이어지는 구간'을
`MAX_DIGIT_RUN` 이하로 제한한다.

방식: 켜 있는 동안 `app.` 모듈이 쓰는 `uuid` 이름을 같은 모듈처럼 동작하는 껍데기로 바꾼다. `uuid4()` 만 다르다 — 진짜 `uuid4()` 를
뽑아 숫자 구간 제한을 어기면 버리고 다시 뽑는다(걸러낸 값은 여전히 무작위 uuid4 이므로 형식·유일성·예측 불가능성이 그대로다).
시계(`clock.frozen_clock`)와 같은 방식이며 끝나면 원래 모듈로 되돌린다. PHONE 탐지 규칙·차단 기준은 건드리지 않는다.
"""

import re
import sys
import uuid as _real_uuid
from collections.abc import Iterator
from contextlib import contextmanager

MAX_DIGIT_RUN = 6  # 숫자만 이어지는 구간의 최대 길이(전화·계좌·주민번호 규칙은 모두 이보다 긴 숫자 구간이 필요하다)
_DIGIT_RUN = re.compile(rf"\d{{{MAX_DIGIT_RUN + 1},}}")
_MAX_TRIES = 1000
_active = False


def is_safe(hex_text: str) -> bool:
    """`hex_text` 에 숫자만 이어지는 구간이 `MAX_DIGIT_RUN` 보다 길게 없는가."""
    return _DIGIT_RUN.search(hex_text) is None


def safe_uuid4() -> _real_uuid.UUID:
    """숫자 연속 구간이 짧은 진짜 uuid4. 걸러내기만 하므로 값 자체는 무작위 uuid4 다."""
    for _ in range(_MAX_TRIES):
        value = _real_uuid.uuid4()
        if is_safe(value.hex):
            return value
    raise RuntimeError("숫자 연속 구간이 짧은 uuid4 를 만들지 못했다")


class _UuidShim:
    """`uuid` 모듈처럼 쓰이되 `uuid4` 만 `safe_uuid4` 다. 나머지(`UUID`, `uuid5` …)는 진짜 모듈 그대로다."""

    uuid4 = staticmethod(safe_uuid4)

    def __getattr__(self, name: str):
        return getattr(_real_uuid, name)


@contextmanager
def safe_ids(prefix: str = "app.") -> Iterator[None]:
    """켜 있는 동안 `app.` 모듈의 `uuid` 를 껍데기로 바꾼다(끝나면 되돌린다). 겹쳐 열 수 없다."""
    global _active
    if _active:
        raise RuntimeError("합성 id 안전 모드는 겹쳐 열 수 없다")
    import app.main  # noqa: F401  모든 기능 모듈을 먼저 불러온다(켠 뒤에 처음 불러오는 모듈이 빠지지 않게)

    shim = _UuidShim()
    patched: list[object] = []
    known = set(sys.modules)
    for name, module in list(sys.modules.items()):
        if (
            name.startswith(prefix)
            and module is not None
            and getattr(module, "uuid", None) is _real_uuid
        ):
            patched.append(module)
            module.uuid = shim
    _active = True
    try:
        yield
        late = sorted(
            n
            for n, m in sys.modules.items()
            if n.startswith(prefix)
            and n not in known
            and m is not None
            and getattr(m, "uuid", None) is _real_uuid
        )
        if late:
            raise RuntimeError(f"안전 모드를 켠 뒤에 불러온 모듈이 진짜 uuid 를 쓴다: {late}")
    finally:
        _active = False
        for module in patched:
            module.uuid = _real_uuid
