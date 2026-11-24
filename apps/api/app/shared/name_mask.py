"""관리자 화면에 보이는 사람·가족 이름과 아이디를 가린다(첫 글자만 보이고 나머지는 *).

관리자 API 응답 모델(service_admin/schemas.py)의 이름 칸이 응답으로 나갈 때 이 함수를 거친다.
서버에서 가려 보내므로 브라우저 개발자 도구로도 원래 값이 보이지 않는다(2026-11-24 사용자 결정).
"""

from typing import Annotated

from pydantic import PlainSerializer


def mask_first(value: str | None) -> str | None:
    """첫 글자만 남기고 나머지를 * 로 바꾼다. 빈 값은 그대로, "(가족 없음)" 처럼 괄호로 시작하는 안내 문구도 그대로 둔다.

    Args:
        value: 이름·아이디·가족 이름
    Returns:
        예: "김준하" → "김**", "jun123" → "j*****"
    """
    if not value or value.startswith("("):
        return value
    return value[0] + "*" * (len(value) - 1)


# 응답에 실을 때만 가린다(서버 안 계산·정렬은 원래 값으로 한다)
MaskedStr = Annotated[str, PlainSerializer(mask_first, return_type=str)]
MaskedOptStr = Annotated[str | None, PlainSerializer(mask_first, return_type=str | None)]
