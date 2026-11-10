"""테스트 분할을 평가한 이력(`test_runs.json`)을 지키는 문지기. 목적(baseline·final)마다 평가 실행은 단 한 번이다.

스펙은 "사례마다 baseline 1회·final 1회"이고, 1단계 테스트 사례는 baseline 과 final 에, 2·3단계에서 더한 사례는 final 에만 쓴다.
그래서 목적마다 실행을 하나로 제한하고 그 실행이 분할 전체를 예약한다(사례를 나눠 후보별로 돌리거나 사례 id 를 바꿔 한도를 되돌릴 수
없다). 1단계에서 끝내는 경우 이후 확장의 새 테스트 사례는 이력 파일을 사람이 고쳐서(커밋으로 남는다) 새로 연다.

우회를 막는 설계
- 읽기 전에 예약한다: 사례 내용은 예약이 끝난 뒤에만, 한 번만 반복할 수 있는 `GuardedCases` 로 돌려준다. 반복할 때 사례마다 먼저
  started 로 표시하고 내준다(`pending → started → done`). 이력 파일이 없거나 형식이 깨져 있으면 새로 만들지 않고 멈춘다(실패 시 닫힘).
- 끊겨 started 로 남은 사례는 결과가 저장되지 않았어도 다시 돌리지 않는다(결과를 본 뒤 끊고 다시 돌리는 우회를 막는다). 이어서 돌릴
  때는 같은 run_id 로, 목적·분할 파일·후보(git 해시)가 처음과 같아야 하고 pending 사례만 돌린다. 끊긴 사례는 보고서에서 평가하지 못한
  사례로 따로 적고 전후 비교에서 뺀다.
- 읽기-검사-쓰기는 파일 잠금 안에서 하고, 쓰기는 임시 파일에 다 쓴 뒤 교체한다. 쓰기 전에 읽을 때와 같은 형식을 검사한다.
- 이력은 사실 기록이라 지우지 않는다. 파일 자체를 지우거나 되돌리는 것은 코드로 막을 수 없으니 저장소에 커밋해서 git 이력으로 본다.
"""

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .schema import Case

PURPOSES = ("baseline", "final")
STATES = ("pending", "started", "done")
LOCK_TIMEOUT = 30.0
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{7,64}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")

if os.name == "nt":
    import msvcrt

    def _lock(handle) -> None:
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as e:
                if time.monotonic() > deadline:
                    raise TestRunsError("test_runs.json 잠금을 얻지 못했다") from e
                time.sleep(0.02)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)


class TestRunsError(RuntimeError):
    """이력 파일이 없거나 깨졌거나, 사례의 평가 횟수를 넘겼다."""

    __test__ = False  # pytest 가 시험 클래스로 오해하지 않게


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    if not path.exists():
        raise TestRunsError(f"이력 파일이 없다(새로 만들지 않는다): {path.name}")
    with open(path.with_name(path.name + ".lock"), "a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")  # 잠글 바이트
            handle.flush()
        _lock(handle)
        try:
            yield
        finally:
            _unlock(handle)


_FIELDS = {"run_id", "purpose", "split_hash", "candidate", "date", "cases"}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise TestRunsError("이력 파일을 읽을 수 없다") from e
    runs = data.get("runs") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(runs, list) or set(data) != {"version", "runs"}:
        raise TestRunsError("이력 파일 형식이 맞지 않는다")
    seen: set[str] = set()
    for run in runs:
        ok = (
            isinstance(run, dict)
            and set(run) == _FIELDS
            and isinstance(run["run_id"], str)
            and _ID.fullmatch(run["run_id"])
            and run["purpose"] in PURPOSES
            and isinstance(run["split_hash"], str)
            and _HEX.fullmatch(run["split_hash"])
            and isinstance(run["candidate"], str)
            and _HEX.fullmatch(run["candidate"])
            and isinstance(run["date"], str)
            and _DAY.fullmatch(run["date"])
            and isinstance(run["cases"], dict)
            and all(
                isinstance(k, str) and _ID.fullmatch(k) and v in STATES
                for k, v in run["cases"].items()
            )
            and run["run_id"] not in seen
        )
        if not ok:
            raise TestRunsError("이력 파일 형식이 맞지 않는다")
        seen.add(run["run_id"])
    return data


def _save(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".test_runs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:  # 편집기·백신이 파일을 잡고 있으면 교체가 거부된다(상태는 바뀌지 않았다)
        Path(tmp).unlink(missing_ok=True)
        raise TestRunsError("이력 파일을 쓰지 못했다(다른 프로그램이 열고 있을 수 있다)") from e
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def init_runs_file(path: Path) -> None:
    """빈 이력 파일을 만든다(처음 한 번만. 이미 있으면 거부한다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="") as f:
            f.write(json.dumps({"version": 1, "runs": []}, indent=2) + "\n")
    except FileExistsError as e:
        raise TestRunsError("이력 파일이 이미 있다(덮어쓰지 않는다)") from e


def _check_new(
    run_id: str, purpose: str, split_hash: str, candidate: str, case_ids: list[str]
) -> None:
    """저장하기 전에 읽을 때와 같은 형식을 검사한다(저장은 됐는데 읽을 수 없는 파일이 되지 않게)."""
    if purpose not in PURPOSES:
        raise TestRunsError(f"목적은 {PURPOSES} 중 하나")
    if not (_ID.fullmatch(run_id) and _HEX.fullmatch(split_hash) and _HEX.fullmatch(candidate)):
        raise TestRunsError("run_id·분할 해시·후보(git 해시) 형식이 맞지 않는다")
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise TestRunsError("사례 id 가 비었거나 겹친다")
    bad = [c for c in case_ids if not _ID.fullmatch(c)]
    if bad:
        raise TestRunsError(f"사례 id 형식이 맞지 않는다(영숫자와 _.:- 만, 64자 이하): {bad[:3]}")


def reserve(
    path: Path,
    run_id: str,
    purpose: str,
    split_hash: str,
    candidate: str,
    case_ids: list[str],
    day: date,
) -> None:
    """목적(baseline·final)마다 단 한 번, 분할 전체의 사례를 예약한다. 이미 그 목적의 실행이 있으면 멈춘다.

    목적마다 실행을 하나로 제한하므로 사례를 나눠 후보별로 돌리거나 사례 id 를 바꿔 한도를 되돌릴 수 없다.
    """
    _check_new(run_id, purpose, split_hash, candidate, case_ids)
    with _locked(path):
        data = _load(path)
        if any(r["run_id"] == run_id for r in data["runs"]):
            raise TestRunsError(f"이미 있는 실행 id 다: {run_id}")
        done = next((r["run_id"] for r in data["runs"] if r["purpose"] == purpose), None)
        if done is not None:
            raise TestRunsError(
                f"{purpose} 평가는 한 번뿐이다(이미 {done}). 이어서 돌리려면 같은 run_id 를 쓴다"
            )
        data["runs"].append(
            {
                "run_id": run_id,
                "purpose": purpose,
                "split_hash": split_hash,
                "candidate": candidate,
                "date": day.isoformat(),
                "cases": dict.fromkeys(case_ids, "pending"),
            }
        )
        _save(path, data)


def _move(path: Path, run_id: str, case_id: str, before: str, after: str) -> None:
    with _locked(path):
        data = _load(path)
        run = next((r for r in data["runs"] if r["run_id"] == run_id), None)
        if run is None or run["cases"].get(case_id) != before:
            raise TestRunsError(f"{run_id}/{case_id} 는 {before} 상태가 아니다")
        run["cases"][case_id] = after
        _save(path, data)


def start_case(path: Path, run_id: str, case_id: str) -> None:
    """사례 하나를 시작으로 표시한다. pending 이 아니면(이미 시작·완료) 거부한다."""
    _move(path, run_id, case_id, "pending", "started")


def finish_case(path: Path, run_id: str, case_id: str) -> None:
    _move(path, run_id, case_id, "started", "done")


def _get_run(path: Path, run_id: str) -> dict | None:
    with _locked(path):
        return next((r for r in _load(path)["runs"] if r["run_id"] == run_id), None)


def status(path: Path, run_id: str) -> dict[str, str]:
    """실행의 사례별 상태(started 는 끊긴 사례)."""
    run = _get_run(path, run_id)
    if run is None:
        raise TestRunsError(f"없는 실행 id 다: {run_id}")
    return dict(run["cases"])


class GuardedCases:
    """예약된 사례. 반복할 때 사례마다 먼저 시작으로 표시한 뒤 내주고, 소비자가 다음으로 넘어가면 완료로 표시한다.

    한 번만 반복할 수 있다(두 번째는 이미 시작한 사례라 거부된다). 도중에 끊기면 그 사례는 started 로 남는다.
    이어서 돌릴 때 끊겼던 사례의 id 는 `interrupted` 로 알려 준다(다시 돌리지 않는다).
    """

    def __init__(self, path: Path, run_id: str, cases: list[Case], interrupted: list[str]) -> None:
        self._path, self._run_id, self._cases = path, run_id, cases
        self.interrupted = interrupted

    def __len__(self) -> int:
        return len(self._cases)

    def ids(self) -> list[str]:
        return [c.id for c in self._cases]

    def __iter__(self) -> Iterator[Case]:
        for case in self._cases:
            start_case(self._path, self._run_id, case.id)
            yield case
            finish_case(self._path, self._run_id, case.id)


def load_test_cases(
    runs_path: Path,
    split_path: Path,
    run_id: str,
    purpose: str,
    candidate: str,
    day: date,
    parse: Callable[[bytes], list[Case]] | None = None,
) -> tuple[GuardedCases, str]:
    """테스트 분할 사례를 `GuardedCases` 로 돌려준다. 이력 파일을 먼저 확인·예약하고, 예약이 끝나기 전에는 내용을 돌려주지 않는다.

    `candidate` 는 평가하는 코드·후보의 git 해시다. 이미 있는 run_id 면 이어서 돌리는 것이라 목적·분할 파일·후보가 처음과 같아야 하고
    pending 사례만 돌려준다.
    """
    existing = _get_run(
        runs_path, run_id
    )  # 이력 파일이 없거나 깨졌으면 분할 파일을 열기 전에 멈춘다
    raw = split_path.read_bytes()
    split_hash = hashlib.sha256(raw).hexdigest()
    cases = (parse or _parse)(raw)
    if any(c.split != "test" for c in cases):
        raise TestRunsError("테스트 분할이 아닌 사례가 섞여 있다")
    ids = [c.id for c in cases]
    if existing is None:
        reserve(runs_path, run_id, purpose, split_hash, candidate, ids, day)
        states = dict.fromkeys(ids, "pending")
    else:
        same = (existing["purpose"], existing["split_hash"], existing["candidate"])
        if same != (purpose, split_hash, candidate):
            raise TestRunsError("이어서 돌리려는 실행의 목적·분할 파일·후보가 처음과 다르다")
        states = existing["cases"]
    pending = [c for c in cases if states.get(c.id) == "pending"]
    interrupted = sorted(c for c, s in states.items() if s == "started")
    return GuardedCases(runs_path, run_id, pending, interrupted), split_hash


def _parse(raw: bytes) -> list[Case]:
    return [Case.model_validate(item) for item in json.loads(raw.decode("utf-8"))]
