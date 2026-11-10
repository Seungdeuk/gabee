"""테스트 분할을 평가한 이력(`test_runs.json`)을 지키는 문지기. 사례마다 baseline 1회·final 1회를 넘기지 못하게 한다.

우회를 막는 설계
- 읽기 전에 예약한다: 사례 내용은 예약이 끝난 뒤에만 호출한 쪽에 돌려준다. 예약은 사례 id 가 아니라 분할 파일 전체에 대해
  한 번에 하고(일부만 예약되지 않는다), 이력 파일이 없거나 형식이 깨져 있으면 새로 만들지 않고 멈춘다(실패 시 닫힘).
- 상태는 사례마다 pending → started → done. `start_case` 가 사례를 시작으로 바꾼 뒤에만 실행한다. 중간에 끊겨 started 로
  남은 사례는 다시 돌리지 않고 호출한 쪽에 알린다(결과를 본 뒤 끊고 다시 돌리는 우회를 막는다). 이어서 돌릴 때는 같은
  run_id 의 pending 사례만 돌린다.
- 읽기-검사-쓰기는 파일 잠금 안에서 하고, 쓰기는 임시 파일에 다 쓴 뒤 교체한다. 여러 프로세스가 동시에 돌려도 한쪽만 예약된다.
- 이력은 사실 기록이라 지우지 않는다(같은 run_id 로 다시 예약할 수 없다). 파일 자체를 지우거나 되돌리는 것은 코드로 막을
  수 없으니 저장소에 커밋해서 git 이력으로 본다.
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
LIMIT = 1  # 사례마다 목적별 최대 횟수
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
            and set(run) == {"run_id", "purpose", "split_hash", "date", "cases"}
            and isinstance(run["run_id"], str)
            and _ID.fullmatch(run["run_id"])
            and run["purpose"] in PURPOSES
            and isinstance(run["split_hash"], str)
            and _HEX.fullmatch(run["split_hash"])
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


def reserve(
    path: Path, run_id: str, purpose: str, split_hash: str, case_ids: list[str], day: date
) -> None:
    """한 실행이 평가할 사례를 모두 예약한다. 하나라도 이미 한도라면 아무것도 예약하지 않고 멈춘다."""
    if purpose not in PURPOSES:
        raise TestRunsError(f"목적은 {PURPOSES} 중 하나")
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise TestRunsError("사례 id 가 비었거나 겹친다")
    with _locked(path):
        data = _load(path)
        if any(r["run_id"] == run_id for r in data["runs"]):
            raise TestRunsError(f"이미 있는 실행 id 다: {run_id}")
        used = {
            c: sum(1 for r in data["runs"] if r["purpose"] == purpose and c in r["cases"])
            for c in case_ids
        }
        over = sorted(c for c, n in used.items() if n >= LIMIT)
        if over:
            raise TestRunsError(f"{purpose} 평가 한도({LIMIT}회)를 넘는 사례: {over}")
        data["runs"].append(
            {
                "run_id": run_id,
                "purpose": purpose,
                "split_hash": split_hash,
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
    """실행의 사례별 상태. 이어서 돌릴 때 pending 만 돌리고, started 는 끊긴 사례로 알린다."""
    run = _get_run(path, run_id)
    if run is None:
        raise TestRunsError(f"없는 실행 id 다: {run_id}")
    return dict(run["cases"])


def load_test_cases(
    runs_path: Path,
    split_path: Path,
    run_id: str,
    purpose: str,
    day: date,
    parse: Callable[[bytes], list[Case]] | None = None,
) -> tuple[list[Case], str]:
    """테스트 분할 사례를 돌려준다. 이력 파일을 먼저 확인·예약하고, 예약이 끝나기 전에는 내용을 돌려주지 않는다.

    이미 있는 run_id 면 이어서 돌리는 것이라 새로 예약하지 않고 pending 사례만 돌려준다.
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
        reserve(runs_path, run_id, purpose, split_hash, ids, day)
        pending = set(ids)
    else:
        if existing["purpose"] != purpose or existing["split_hash"] != split_hash:
            raise TestRunsError("이어서 돌리려는 실행의 목적이나 분할 파일이 처음과 다르다")
        pending = {c for c, s in existing["cases"].items() if s == "pending"}
    return [c for c in cases if c.id in pending], split_hash


def _parse(raw: bytes) -> list[Case]:
    return [Case.model_validate(item) for item in json.loads(raw.decode("utf-8"))]
