"""실제 모델 호출의 활성화 구조(E7a). 기본은 항상 차단이고, 사용자가 승인한 그 실행 한 번에만 허가(grant)를 연다.

이 모듈은 `app` 을 불러오지 않는다(CLI 가 환경을 정하기 전에 불러야 해서). 순수한 규칙과 허가 보관만 한다.

## 허가가 열리는 조건(`issue_grant`) - 하나라도 틀리면 `RealGateRefused`
1. 환경변수 `GABEE_EVAL_ALLOW_REAL_LLM` 이 정확히 "1" (다른 값·빈 값 거부)
2. 승인 금액이 0 보다 큰 유한한 금액
3. 분할이 legacy·dev 중 하나(val·test·all 의 실제 호출은 이번 단계에서 금지)
4. 명시한 사례 id 목록이 비어 있지 않고 모두 실제 존재한다("전체"는 없다)
5. 사례 수가 `MAX_REAL_CASES` 이하, 반복이 `MAX_REAL_REPEAT` 이하
6. **`preflight.run_preflight` 가 실제로 발급한** 일회용 기록이 있고(직접 만든 기록·이미 쓴 기록은 거부) 같은 실행(id·금액·분할·사례·사례 내용 해시·반복)을 가리킨다

## 허가의 수명
- **`issue_grant` 가 발급한 허가만** `real_grant_scope`·`check_run`·네트워크 진입점(`require_active`)이 인정한다(직접 만든 `RealGrant` 는 거부).
- 상태: 발급(issued) -> 실행 중(running, `check_run` 이 한 번만 성공) -> 소진(spent, `finish`). 소진된 허가는 비활성이라 `require_active`·`real_grant_scope` 가 거부한다.
- `ContextVar` 에 담긴다: 허가를 연 컨텍스트에서만 보이고 `threading.Thread` 로 새로 만든 스레드는 물려받지 않는다. `TestClient` 가 sync 엔드포인트를 돌리는
  스레드풀에서는 보이고 async 핸들러·포털 스레드에서는 안 보일 수 있다(서버 쪽에서 허가를 확인하는 곳은 없어 영향 없다. 확인은 러너 진입·세션·네트워크 개방에서 한다).
- `real_grant_scope(grant)` 로만 열고, 정상·예외·KeyboardInterrupt 어떤 종료에서도 해제한다. 중첩해서 열면 거부한다.
- 프로세스 전역 상태에는 활성 허가가 남지 않는다(발급 기록 레지스트리는 모듈 내부에 있고 소진·사용 시 지운다).

못 막는 것(문서 `docs/features/agent-eval.md` E7a): 같은 프로세스의 코드가 이 모듈의 내부 상태(레지스트리·`_mint_preflight`)를 **의도적으로** 건드리거나 `httpx` 를 직접 부르거나
환경변수·상수를 일부러 바꾸는 것. `network.block_network` 가 활성 허가 없이는 `REAL_HOSTS` 를 열지 않아 허가 없는 연결은 파이썬 수준에서 막힌다.
"""

import os
import secrets
import threading
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ENV_NAME = "GABEE_EVAL_ALLOW_REAL_LLM"  # 이 문서가 정한 이름(고정). 값은 정확히 "1" 이어야 한다
ALLOWED_SPLITS = ("legacy", "dev")  # val·test·all 의 실제 호출은 이번 단계에서 금지한다
# 이번 단계의 실제 호출 사례 수 상한: 첫 실제 연결 시험(1건)과 대표 개발셋(9건)을 넉넉히 덮고, 실수로 큰 묶음을 돌려 예산을 쓰는 것을 막는다.
# 늘리려면 이 상수를 고치는 별도 변경(리뷰)이 필요하다.
MAX_REAL_CASES = 10
# 이번 단계의 반복 상한: 첫 베이스라인 전 연결·대표 사례 확인은 각 1회가 계획이고, 같은 사례를 여러 번 돌려 비용을 키우는 실수를 막으려고 3회까지만 허용한다.
MAX_REAL_REPEAT = 3
REAL_HOSTS = ("api.anthropic.com",)  # 허가가 활성일 때 열리는 외부 호스트는 이것 하나뿐이다
MODES = ("fake", "real")


class RealGateRefused(RuntimeError):
    """실제 모델 호출을 허가할 수 없다(어떤 조건이 부족한지만 적고 키·환경변수 값은 적지 않는다)."""


def is_fake(mode: object) -> bool:
    """가짜 모드인가. 정확히 "fake" 만 가짜이고 그 밖의 모든 값(오타·None 포함)은 실제로 취급해 허가를 요구한다. 모드 판정은 이 함수 한 곳에서 한다."""
    return mode == "fake"


@dataclass(frozen=True)
class PreflightRecord:
    """사전 점검을 모두 통과했다는 일회용 기록. `_mint_preflight` 가 발급한 것만 `issue_grant` 가 받는다."""

    run_id: str
    approve_usd: Decimal
    split: str
    case_ids: frozenset[str]
    worst_case_usd: Decimal
    content_hash: str = ""
    repeat: int = 1
    _nonce: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class RealGrant:
    """이 실행 한 번에만 유효한 실제 호출 허가. `issue_grant` 가 발급한 것만 인정된다."""

    approved_usd: Decimal
    case_ids: frozenset[str]
    split: str
    run_id: str
    issued_at: datetime
    env_confirmed: bool
    results_root: Path | None = None
    content_hash: str = ""
    repeat: int = 1
    _nonce: str = field(default="", repr=False, compare=False)
    _state: list[str] = field(default_factory=lambda: ["issued"], compare=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)

    @property
    def consumed(self) -> bool:
        return self._state[0] != "issued"

    @property
    def spent(self) -> bool:
        return self._state[0] == "spent"

    def consume(self) -> None:
        """발급 -> 실행 중. 한 번만 성공한다(승인은 한 번의 실행에만 유효하다)."""
        with self._lock:
            if self._state[0] != "issued":
                raise RealGateRefused(
                    "이 허가는 이미 한 번 쓰였다(승인은 한 번의 실행에만 유효하다)"
                )
            self._state[0] = "running"


_registry_lock = threading.Lock()
_RECORDS: dict[str, PreflightRecord] = {}  # 발급된 사전 점검 기록(쓰면 지운다)
_GRANTS: dict[str, RealGrant] = {}  # 발급된 허가(소진되면 지운다)
_active: ContextVar[RealGrant | None] = ContextVar("agent_eval_real_grant", default=None)


def _mint_preflight(
    run_id: str,
    approve_usd: Decimal,
    split: str,
    case_ids: frozenset[str],
    worst_case_usd: Decimal,
    content_hash: str,
    repeat: int = 1,
) -> PreflightRecord:
    """사전 점검 통과 기록을 발급한다. `preflight.run_preflight` 가 모든 점검을 통과했을 때만 부른다(시험은 도우미로 부른다)."""
    nonce = secrets.token_hex(16)
    record = PreflightRecord(
        run_id, approve_usd, split, case_ids, worst_case_usd, content_hash, repeat, nonce
    )
    with _registry_lock:
        _RECORDS[nonce] = record
    return record


def _take_record(record: PreflightRecord | None) -> None:
    """발급된 기록인지 확인하고 원자적으로 소진한다(같은 기록으로 두 번째 허가는 거부)."""
    with _registry_lock:
        if record is None or not record._nonce or _RECORDS.get(record._nonce) is not record:
            raise RealGateRefused(
                "사전 점검(preflight)이 발급한 통과 기록이 없다(직접 만든 기록·이미 쓴 기록은 거부)"
            )
        del _RECORDS[record._nonce]


def _issued(grant: RealGrant | None) -> bool:
    """`issue_grant` 가 발급했고 아직 소진되지 않았는가."""
    if grant is None or not grant._nonce:
        return False
    with _registry_lock:
        return _GRANTS.get(grant._nonce) is grant and not grant.spent


def real_grant() -> RealGrant | None:
    """현재 컨텍스트의 활성 허가(없으면 None=기본 차단)."""
    return _active.get()


def parse_approve(raw: object) -> Decimal:
    """승인 금액을 0 보다 큰 유한한 Decimal 로 바꾼다. 아니면 `RealGateRefused`."""
    try:
        if isinstance(raw, bool):
            raise ValueError
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise RealGateRefused("승인 금액은 0 보다 큰 유한한 금액이어야 한다") from None
    if not value.is_finite() or value <= 0:
        raise RealGateRefused("승인 금액은 0 보다 큰 유한한 금액이어야 한다")
    return value


def env_allows(environ: Mapping[str, str] | None = None) -> bool:
    return (environ if environ is not None else os.environ).get(ENV_NAME) == "1"


def check_request(
    *,
    approve_usd: object,
    split: str,
    case_ids: Collection[str],
    repeat: int = 1,
    require_env: bool = True,
    environ: Mapping[str, str] | None = None,
) -> Decimal:
    """허가 조건 중 사전에 알 수 있는 것(환경변수·금액·분할·사례 목록 모양·반복)만 검사한다. 통과하면 승인 금액을 돌려준다.
    `require_env=False` 는 사전 점검(실호출이 아님)용이다. 사례가 실제로 있는지와 사전 점검 통과는 `issue_grant` 가 본다."""
    problems: list[str] = []
    if require_env and not env_allows(environ):
        problems.append(f'환경변수 {ENV_NAME} 이 "1" 이 아니다')
    try:
        approve = parse_approve(approve_usd)
    except RealGateRefused as e:
        problems.append(str(e))
        approve = Decimal(0)
    if split not in ALLOWED_SPLITS:
        problems.append(
            f"실제 호출을 허용하는 분할은 {'·'.join(ALLOWED_SPLITS)} 뿐이다(받은 값: {split})"
        )
    ids = list(case_ids)
    if not ids:
        problems.append("명시적 --case 목록이 필요하다(전체 실행은 허용하지 않는다)")
    elif len(set(ids)) != len(ids):
        problems.append("사례 id 가 겹친다")
    elif len(ids) > MAX_REAL_CASES:
        problems.append(f"실제 호출 사례는 {MAX_REAL_CASES}건 이하여야 한다(받은 수: {len(ids)})")
    if (
        not isinstance(repeat, int)
        or isinstance(repeat, bool)
        or not 1 <= repeat <= MAX_REAL_REPEAT
    ):
        problems.append(f"실제 호출의 반복은 1~{MAX_REAL_REPEAT} 이어야 한다(받은 값: {repeat})")
    if problems:
        raise RealGateRefused("; ".join(problems))
    return approve


def issue_grant(
    *,
    approve_usd: object,
    split: str,
    case_ids: Collection[str],
    known_ids: Collection[str],
    run_id: str,
    preflight: PreflightRecord | None,
    content_hash: str,
    repeat: int = 1,
    results_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> RealGrant:
    """조건을 모두 검사해 허가를 만든다(아직 활성은 아니다: `real_grant_scope` 로 연다). 통과하면 사전 점검 기록을 소진한다."""
    approve = check_request(
        approve_usd=approve_usd, split=split, case_ids=case_ids, repeat=repeat, environ=environ
    )
    ids = frozenset(case_ids)
    unknown = sorted(ids - set(known_ids))
    if unknown:
        raise RealGateRefused(f"존재하지 않는 사례 id: {unknown}")
    if preflight is None:
        raise RealGateRefused("사전 점검(preflight) 통과 기록이 없다")
    if (
        preflight.run_id != run_id
        or preflight.approve_usd != approve
        or preflight.split != split
        or preflight.case_ids != ids
        or preflight.content_hash != content_hash
        or preflight.repeat != repeat
    ):
        raise RealGateRefused("사전 점검 기록이 이 실행(id·금액·분할·사례·사례 내용·반복)과 다르다")
    _take_record(preflight)
    nonce = secrets.token_hex(16)
    grant = RealGrant(
        approved_usd=approve,
        case_ids=ids,
        split=split,
        run_id=run_id,
        issued_at=now or datetime.now(UTC),
        env_confirmed=True,
        results_root=results_root.resolve() if results_root is not None else None,
        content_hash=content_hash,
        repeat=repeat,
        _nonce=nonce,
    )
    with _registry_lock:
        _GRANTS[nonce] = grant
    return grant


@contextmanager
def real_grant_scope(grant: RealGrant) -> Iterator[RealGrant]:
    """허가를 이 컨텍스트에서만 활성으로 한다. 어떤 종료에서도 해제한다. 이미 열려 있으면 거부(중첩 금지)."""
    if not _issued(grant):
        raise RealGateRefused(
            "발급된 허가가 아니거나 이미 소진된 허가다(직접 만든 허가는 인정하지 않는다)"
        )
    if _active.get() is not None:
        raise RealGateRefused("이미 실제 호출 허가가 열려 있다(겹쳐 열지 않는다)")
    token = _active.set(grant)
    try:
        yield grant
    finally:
        _active.reset(token)


def check_run(
    grant: RealGrant | None,
    *,
    approved_usd: Decimal | None,
    run_id: str,
    splits: Collection[str],
    case_ids: Collection[str],
    results_root: Path | None,
    content_hash: str,
    repeats: int,
) -> RealGrant:
    """실행기가 실제 모드를 시작하기 전에 부른다: 활성 허가가 이 실행과 맞는지 확인하고 허가를 실행 중으로 바꾼다(1회용)."""
    if grant is None:
        raise RealGateRefused(
            f"실제 모델 호출은 기본으로 꺼져 있다: 활성 허가가 없다(CLI 에서 환경변수 {ENV_NAME}=1, --real, --approve-usd, --case 로만 연다)"
        )
    if not _issued(grant):
        raise RealGateRefused("발급된 허가가 아니거나 이미 소진된 허가다")
    if grant.consumed:
        raise RealGateRefused("이 허가는 이미 한 번 쓰였다(승인은 한 번의 실행에만 유효하다)")
    problems: list[str] = []
    if approved_usd != grant.approved_usd:
        problems.append("승인 금액이 허가와 다르다")
    if run_id != grant.run_id:
        problems.append("실행 id 가 허가와 다르다")
    if set(splits) != {grant.split} or grant.split not in ALLOWED_SPLITS:
        problems.append("분할이 허가와 다르거나 허용하지 않는 분할이다")
    ids = set(case_ids)
    if not ids or not ids <= grant.case_ids:
        problems.append("실행할 사례가 허가한 사례 목록 밖이다")
    if content_hash != grant.content_hash:
        problems.append("사례 내용이 허가한 내용과 다르다(내용 해시 불일치)")
    if repeats != grant.repeat:
        problems.append("반복 수가 허가와 다르다")
    if grant.results_root is not None and (
        results_root is None or results_root.resolve() != grant.results_root
    ):
        problems.append("결과 폴더가 허가와 다르다")
    if problems:
        raise RealGateRefused("; ".join(problems))
    grant.consume()
    return grant


def finish(grant: RealGrant) -> None:
    """실행이 끝났다(정상·예외 모두): 허가를 소진하고 레지스트리에서 지운다. 소진된 허가는 어떤 문도 열지 못한다."""
    with grant._lock:
        grant._state[0] = "spent"
    with _registry_lock:
        _GRANTS.pop(grant._nonce, None)


def require_active() -> RealGrant:
    """발급된 허가가 활성이고 소진되지 않았을 때만 통과한다(네트워크 허용 호스트·세션을 열기 전에 부른다)."""
    grant = real_grant()
    if grant is None:
        raise RealGateRefused("허가 없이는 외부 호스트를 열지 않는다")
    if not _issued(grant):
        raise RealGateRefused("소진됐거나 발급되지 않은 허가로는 외부 호스트를 열지 않는다")
    return grant
