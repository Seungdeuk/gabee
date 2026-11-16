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

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.shared.llm import transport

from .cost import PRICES, BudgetExceeded, Ledger

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


def _strict_usage(payload: object, model: str) -> tuple[int, int, str]:
    """실호출 응답의 (입력 토큰, 출력 토큰, 모델)을 엄격하게 읽는다. 사용량이 없거나(누락·빈 값·객체 아님)·값이 정수가 아니거나 음수이거나·입력 토큰이 0 이거나·
    응답 모델이 단가표에 없으면 `ValueError`(확정 비용을 알 수 없다). 상태를 바꾸지 않는다."""
    if not isinstance(payload, dict):
        raise ValueError("응답이 객체가 아니다")
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        raise ValueError("사용량이 없다")
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        if key in raw or key in ("input_tokens", "output_tokens"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"사용량 값이 비정상이다: {key}")
    tokens_in, tokens_out = transport.usage_of(payload)
    if tokens_in <= 0:
        raise ValueError("입력 토큰이 0 이다")
    used = str(payload.get("model") or model)
    if used not in PRICES:
        raise ValueError("응답 모델이 단가표에 없다")
    return tokens_in, tokens_out, used


def estimate_input_tokens(body: dict, chars_per_token: int = 1) -> int:
    text = (
        repr(body.get("messages", "")) + repr(body.get("system", "")) + repr(body.get("tools", ""))
    )
    return len(text) // chars_per_token + OVERHEAD_TOKENS


@contextmanager
def retries_off() -> Iterator[None]:
    """실호출 세션 동안 전송 재시도를 끈다(운영 코드는 그대로, 평가 계층에서 `retry=False` 로 바꿔 부른다).

    앱의 탭 Agent(`agent._post`)와 `doc_ai` 는 `post_messages(retry=True)` 로 불러 429·5xx·연결 오류에 한 번 더 부른다. 재시도로 서버가 처리한 앞선 시도는 측정기가
    비용을 기록하지 못하므로, 논리 호출 1회 = 전송 1회로 만들어 기록을 정확하게 한다. 영향: 일시적인 오류가 나면 그 사례는 재시도 없이 오류로 끝난다.
    전송 함수가 `retry` 인자(또는 **kwargs)를 받지 않으면(시험의 가짜) 그대로 둔다. 끝나면 반드시 원래 함수로 되돌린다."""
    inner = transport.post_messages
    params = inspect.signature(inner).parameters
    accepts = "retry" in params or any(p.kind is p.VAR_KEYWORD for p in params.values())

    def no_retry(body: dict, **kwargs):
        if accepts:
            kwargs["retry"] = False
        return inner(body, **kwargs)

    transport.post_messages = no_retry if accepts else inner
    try:
        yield
    finally:
        transport.post_messages = inner


@contextmanager
def meter_llm_calls(
    ledger: Ledger | None = None,
    case_id: str = "",
    repeat: int = 0,
    record_failures: bool = False,
) -> Iterator[UsageMeter]:
    """`record_failures`(실호출 전용): 전송이 예외로 끝나 응답을 못 받은 호출도 서버가 과금했을 수 있으므로 최악 비용(입력 추정 + `max_tokens` 출력)으로
    기록장에 더하고 `unconfirmed` 로 표시한다. 가짜 모드는 켜지 않는다(대본 바닥남은 비용이 없다)."""
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
            if ledger is not None and record_failures:
                try:  # 사용량을 모르는 실패: 보수적으로 기록한다(기록이 상한을 넘겨도 원래 예외를 그대로 올린다)
                    ledger.record(
                        case_id,
                        repeat,
                        model,
                        estimate_input_tokens(body),
                        int(body["max_tokens"]),
                        unconfirmed=True,
                    )
                except (BudgetExceeded, ValueError, KeyError):
                    pass
            raise
        if ledger is not None and record_failures:
            return settle_real(body, model, payload)
        tokens_in, tokens_out = transport.usage_of(payload)
        used = str(payload.get("model") or model)
        meter.calls.append(CallRecord(used, tokens_in, tokens_out, True))
        if ledger is not None:
            try:
                ledger.record(case_id, repeat, used, tokens_in, tokens_out)
            except (BudgetExceeded, ValueError) as e:
                raise RunHalted(f"호출 뒤에 멈춘다: {e}") from e
        return payload

    def settle_real(body: dict, model: str, payload: object):
        """실호출: 응답을 받은 뒤의 모든 경로(사용량·모델 추출·검증·기록)를 하나의 구역으로 묶는다. 확정 비용을 기록하지 못했거나 사용량이 없음·비정상·응답 모델이
        단가표에 없으면 요청 모델과 사전 계산한 최악 비용(입력 추정 + max_tokens)을 `unconfirmed` 로 정확히 한 번 기록한다. 확정 기록에 성공한 뒤의 예외는 다시 기록하지 않는다."""
        assert ledger is not None
        before = len(ledger.usages)
        appended = False
        try:
            tokens_in, tokens_out, used = _strict_usage(payload, model)
            meter.calls.append(CallRecord(used, tokens_in, tokens_out, True))
            appended = True
            ledger.record(case_id, repeat, used, tokens_in, tokens_out)
            return payload
        except (
            BudgetExceeded
        ) as e:  # 기록은 이미 더해졌다(더한 뒤에 상한을 확인한다): 다시 기록하지 않고 멈춘다
            raise RunHalted(f"호출 뒤에 멈춘다: {e}") from e
        except Exception:
            if len(ledger.usages) > before:
                raise  # 확정 기록 뒤의 예외: 이중 기록하지 않는다
            if appended:
                meter.calls.pop()
        # 확정 비용을 기록하지 못했다: 최악 비용을 한 번 기록한다(응답은 앱에 그대로 돌려준다)
        meter.calls.append(CallRecord(model, 0, 0, True))
        try:
            ledger.record(
                case_id,
                repeat,
                model,
                estimate_input_tokens(body),
                int(body["max_tokens"]),
                unconfirmed=True,
            )
        except BudgetExceeded as e:
            raise RunHalted(f"호출 뒤에 멈춘다: {e}") from e
        return payload

    transport.post_messages = counted
    try:
        yield meter
    finally:
        transport.post_messages = real
