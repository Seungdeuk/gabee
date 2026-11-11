"""평가 중 모든 Anthropic Messages 호출의 횟수·토큰을 세고 예산을 지킨다. 운영 코드는 바꾸지 않는다.

앱의 Anthropic 호출(도구 루프의 탭 Agent·메인, 일정 분류 같은 구조화 출력 `client.complete_json`)은 마지막에 `transport.post_messages` 를
지난다. 평가가 켜 둔 동안 그 함수를 감싸서 호출마다 (모델, 입력·출력 토큰)을 기록한다. E3 훅의 `llm_calls`·토큰은 도구 루프만 세므로, 비용
기록(`cost.Ledger`)과 관찰 결과의 호출 수·토큰은 이 측정기를 기준으로 삼는다.

예산: `ledger` 를 주면 호출 직전에 이번 호출의 최악 비용(입력 추정 + `max_tokens` 만큼의 출력)이 남은 예산을 넘는지 확인하고, 호출이 끝나는 즉시
실제 사용량을 기록장에 더한다(사례가 끝난 뒤에 몰아서 더하지 않으므로 한 사례 안의 여러 호출이 누적된다). 상한 초과와 단가를 모르는 모델은
`RunHalted`(BaseException)로 멈춘다. 앱 코드가 `except Exception`·`except ValueError` 로 삼켜 규칙 기반 답으로 넘어가는 것을 막으려고 일부러
Exception 이 아니다. 실행기는 사례 반복에서 `RunHalted` 를 잡아 실행을 멈추고 기록을 저장한다.

한계: 입력 토큰은 요청 글자 수(한글은 글자당 1토큰으로 보수적으로)에 서버가 붙이는 숨은 시스템 프롬프트 몫(`OVERHEAD_TOKENS`)을 더해 추정한다. `post=` 로 이
함수를 건너뛰는 호출, 이 함수를 쓰지 않는 호출(`shared/llm/jev.py`, `doc_ai.py` 의 직접 httpx)과 웹 검색 사용량은 세지 않는다(평가는 웹 검색을 끈다). 이 함수는
프로세스 전체에서 바뀌므로 측정 중에 다른 스레드가 하는 호출도 센다. 한 번의 `post_messages`(재시도 켜짐)는 한 호출로 센다.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.shared.llm import transport

from .cost import BudgetExceeded, Ledger

OVERHEAD_TOKENS = 1500  # 도구가 있을 때 서버가 붙이는 숨은 시스템 프롬프트 등의 여유


class RunHalted(BaseException):  # noqa: N818  앱의 except Exception 이 삼키지 못하게 BaseException
    """예산을 넘거나 단가를 모르는 모델이라 평가를 멈춘다."""


@dataclass(frozen=True)
class CallRecord:
    model: str
    tokens_in: int
    tokens_out: int
    ok: bool  # 응답을 받았는가(실패한 호출은 토큰 0)


@dataclass
class UsageMeter:
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def tokens_in(self) -> int:
        return sum(c.tokens_in for c in self.calls)

    @property
    def tokens_out(self) -> int:
        return sum(c.tokens_out for c in self.calls)


def estimate_input_tokens(body: dict, chars_per_token: int = 1) -> int:
    text = (
        repr(body.get("messages", "")) + repr(body.get("system", "")) + repr(body.get("tools", ""))
    )
    return len(text) // chars_per_token + OVERHEAD_TOKENS


@contextmanager
def meter_llm_calls(
    ledger: Ledger | None = None, case_id: str = "", repeat: int = 0
) -> Iterator[UsageMeter]:
    meter = UsageMeter()
    real = transport.post_messages

    def counted(body: dict, **kwargs) -> dict:
        model = str(body.get("model", ""))
        if ledger is not None:
            try:
                ledger.check_call(model, estimate_input_tokens(body), int(body["max_tokens"]))
            except (BudgetExceeded, ValueError, KeyError) as e:
                raise RunHalted(f"호출 전에 멈춘다: {e}") from e
        try:
            payload = real(body, **kwargs)
        except BaseException:
            meter.calls.append(CallRecord(model, 0, 0, False))
            raise
        tokens_in, tokens_out = transport.usage_of(payload)
        used = str(payload.get("model") or model)
        meter.calls.append(CallRecord(used, tokens_in, tokens_out, True))
        if ledger is not None:
            try:
                ledger.record(case_id, repeat, used, tokens_in, tokens_out)
            except (BudgetExceeded, ValueError) as e:
                raise RunHalted(f"호출 뒤에 멈춘다: {e}") from e
        return payload

    transport.post_messages = counted
    try:
        yield meter
    finally:
        transport.post_messages = real
