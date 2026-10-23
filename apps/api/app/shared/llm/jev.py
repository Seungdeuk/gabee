"""TypeSafe Jev(System One) 호출 래퍼. 글을 만들지 않고, 정해진 보기 중 고르기(choice)·예/아니오(noul)
확률을 돌려준다. 키가 없거나 호출이 실패하면 LLMUnavailable 을 낸다.

보내는 쪽 책임: 개인정보를 가린 글자만 state 에 넣는다.
"""

import httpx

from app.shared.config import settings

from .client import LLMUnavailable

API_URL = "https://api.typesafe.ai/v1/systemone"


def available() -> bool:
    return bool(settings.typesafe_api_key)


def ask(state, questions: dict, timeout: float | None = None) -> dict:
    """questions: {이름: {"type": "choice"|"noul"|"score", "instructions": …, "criteria": …}}
    돌려주는 값: {이름: 답} — choice 는 choice·confidence·probabilities, noul 은 noul(0~1)."""
    if not available():
        raise LLMUnavailable("TYPESAFE_API_KEY 가 설정되지 않았어요")
    body = {"model": settings.jev_model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {settings.typesafe_api_key}"}
    try:
        res = httpx.post(
            API_URL, json=body, headers=headers, timeout=timeout or settings.jev_timeout
        )
        res.raise_for_status()
        answers = res.json()["answers"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        raise LLMUnavailable(f"Jev 호출에 실패했어요 ({type(e).__name__})") from None
    if not isinstance(answers, dict) or set(questions) - set(answers):
        raise LLMUnavailable("Jev 응답에 빠진 답이 있어요")
    return answers
