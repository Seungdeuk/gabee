"""L2 실행기의 명령줄: `python -m evals.agent_eval.run`(apps/api 에서).

    기본(--dry-run)  사례 수·반복·추정 토큰·추정 비용을 출력하고 끝낸다. 모델도 네트워크도 부르지 않는다.
    --fake           가짜 모델로 전체를 실행한다(시험·시연). 실제 호출 없음.
    --real           실제 모델(현재 꺼져 있어 항상 거부한다. E7 에서 안전장치를 다시 점검한 뒤 켠다). 켜진 뒤에는 `--approve-usd <금액>` 이 함께 있어야만 시작하고, 추정 비용이 승인 금액보다 크면 거부한다.

실행 중 누적 비용이 승인 금액과 `cost` 의 상한 중 작은 쪽에 닿으면 다음 호출 전에 중단한다. 실제 모델의 키는 서버 `settings` 에서만 읽고 출력·저장하지
않는다. 이 파일은 `app` 을 불러오지 않는다(환경변수를 정한 뒤에 `runner` 를 불러와야 해서 `main` 안에서 늦게 불러온다).

분할(`--split legacy|dev|val|test|all`)
- legacy: 기존 52건(`adapter`). dev·val: `--dev-file`·`--val-file`(사례 JSON 목록). 사례 파일이 없으면 시작하지 않는다.
- val: `--purpose`(baseline|final|candidate)와 `--run-id` 가 있어야 한다. test: 추가로 `--split-file`·`--candidate`(git 해시)가 필요하고 `runs_guard` 가 이력 파일을
  읽기 전에 예약한다(목적마다 한 번뿐). 예약을 소모하지 않도록 test 는 `--real` 로만 돌리고(`--fake` 거부, `--dry-run` 은 허용하되 예약하지 않고 사례 개수만 센다).
- all: 모든 분할(legacy·dev·val·test)을 분할별 실행(`<run-id>-<분할>`)으로 돌린다. val·test 조건을 모두 충족해야 한다.
- `--case` 로 사례를 고르는 것은 legacy·dev 만 된다(val·test 는 분할 전체를 한 번에 예약한다).

종료 코드: 0 성공 / 1 실패·관찰 누락·오류가 있다 / 2 인자 오류(argparse) / 3 조합·승인 거부 / 4 추정 비용이 승인 금액이나 예산 상한을 넘는다 /
5 분할 접근 거부(조건 부족, 예약 실패) / 6 개인정보 엔진을 쓸 수 없다 / 7 예산 상한에 닿아 중단 / 8 허용하지 않은 DB·폴더.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import adapter, estimate, runs_guard, store, switches
from .cost import BASELINE_RUN_SCOPES, OTHER_RUN_SCOPES, BudgetExceeded, Ledger, Scope
from .schema import Case

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS = EVAL_DIR / "results"
DEFAULT_FAKE_RESULTS = (
    DEFAULT_RESULTS / "_fake"
)  # opening_spent 가 읽지 않는 깊이(실제 누적에 섞이지 않는다)
DEFAULT_RUNS_FILE = EVAL_DIR / "test_runs.json"
SPLITS = ("legacy", "dev", "val", "test", "all")
ALL_SPLITS = ("legacy", "dev", "val", "test")
OK, FAILED, USAGE, REFUSED, OVER_BUDGET, ACCESS, PRIVACY, HALTED, UNSAFE = 0, 1, 2, 3, 4, 5, 6, 7, 8
_HEX = re.compile(r"[0-9a-f]{7,64}")
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,40}[a-z0-9])?")


class Refusal(Exception):  # noqa: N818  종료 코드가 붙은 거부
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


# 실제 모델 호출 스위치는 `switches.REAL_ENABLED`(기본 꺼짐)다. 추정 가정만으로는 승인 금액을 넘는 지출을 막았다고 말할 수 없다(런타임 상한이 마지막 방어선일 뿐).
# 추정 가정의 하한(기본값). 사용자가 낮춰 추정을 줄이지 못하게 올리기만 허용한다.
DEFAULT_CALLS_PER_CASE, DEFAULT_TOKENS_IN, DEFAULT_TOKENS_OUT = 4, 8000, 500


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evals.agent_eval.run", description=__doc__.split("\n")[0]
    )
    p.add_argument("--dry-run", action="store_true", help="추정만 출력하고 끝낸다(기본)")
    p.add_argument("--fake", action="store_true", help="가짜 모델로 실행한다(실제 호출 없음)")
    p.add_argument("--real", action="store_true", help="실제 모델로 실행한다(--approve-usd 필요)")
    p.add_argument("--approve-usd", help="사용자가 승인한 비용 상한(USD). --real 에만 쓴다")
    p.add_argument("--split", choices=SPLITS, default="legacy")
    p.add_argument("--case", action="append", help="사례 id(여러 번 가능). legacy·dev 만")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--run-id", help="실행 id(소문자·숫자·_.-). val·test 는 필수")
    p.add_argument("--purpose", choices=("baseline", "final", "candidate"))
    p.add_argument("--stage", choices=("other", "baseline"), default="other")
    p.add_argument("--dev-file", type=Path, help="dev 사례 JSON(목록)")
    p.add_argument("--val-file", type=Path, help="val 사례 JSON(목록)")
    p.add_argument("--split-file", type=Path, help="test 사례 JSON(목록)")
    p.add_argument("--candidate", help="평가하는 코드의 git 해시(test)")
    p.add_argument("--runs-file", type=Path, default=DEFAULT_RUNS_FILE)
    p.add_argument("--results-dir", type=Path)
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument(
        "--calls-per-case",
        type=int,
        default=DEFAULT_CALLS_PER_CASE,
        help="추정 가정: 질문 하나가 모델을 부르는 최대 횟수(기본값보다 낮출 수 없다)",
    )
    p.add_argument(
        "--tokens-in",
        type=int,
        default=DEFAULT_TOKENS_IN,
        help="추정 가정: 호출당 입력 토큰(기본값보다 낮출 수 없다)",
    )
    p.add_argument(
        "--tokens-out",
        type=int,
        default=DEFAULT_TOKENS_OUT,
        help="추정 가정: 호출당 출력 토큰(기본값보다 낮출 수 없다)",
    )
    return p


@dataclass(frozen=True)
class Plan:
    mode: str  # dry-run | fake | real
    splits: tuple[str, ...]
    approve: Decimal | None
    run_id: str
    repeat: int
    case_filter: tuple[str, ...]


def _approve(raw: str | None) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise Refusal(REFUSED, "--approve-usd 는 0 보다 큰 유한한 금액이어야 한다") from None
    if not value.is_finite() or value <= 0:
        raise Refusal(REFUSED, "--approve-usd 는 0 보다 큰 유한한 금액이어야 한다")
    return value


def make_plan(args: argparse.Namespace, now: datetime | None = None) -> Plan:
    """인자의 조합을 검사한다. 규칙을 어기면 `Refusal`. 모델·네트워크·DB·사례 파일을 건드리지 않는다."""
    flags = [name for name in ("dry_run", "fake", "real") if getattr(args, name)]
    if len(flags) > 1:
        raise Refusal(
            REFUSED,
            f"--{flags[0].replace('_', '-')} 와 --{flags[1].replace('_', '-')} 는 함께 쓸 수 없다",
        )
    mode = flags[0].replace("_", "-") if flags else "dry-run"
    approve: Decimal | None = None
    if mode == "real":
        if not switches.REAL_ENABLED:
            raise Refusal(
                REFUSED,
                "--real 은 아직 꺼져 있다(E7 에서 비용 추정·승인·안전장치를 다시 점검한 뒤 켠다). --fake 나 --dry-run 만 쓴다",
            )
        if args.approve_usd is None:
            raise Refusal(REFUSED, "--real 은 --approve-usd <금액> 이 함께 있어야만 시작한다")
        approve = _approve(args.approve_usd)
    elif args.approve_usd is not None:
        raise Refusal(REFUSED, "--approve-usd 는 --real 에서만 쓴다")
    if args.repeat < 1:
        raise Refusal(USAGE, "--repeat 는 1 이상이어야 한다")
    if (
        args.calls_per_case < DEFAULT_CALLS_PER_CASE
        or args.tokens_in < DEFAULT_TOKENS_IN
        or args.tokens_out < DEFAULT_TOKENS_OUT
    ):
        raise Refusal(
            USAGE,
            f"추정 가정은 기본값({DEFAULT_CALLS_PER_CASE}회·{DEFAULT_TOKENS_IN}/{DEFAULT_TOKENS_OUT} 토큰)보다 낮출 수 없다",
        )
    splits = ALL_SPLITS if args.split == "all" else (args.split,)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"{mode}-{args.split}-{stamp}"
    if not _RUN_ID.fullmatch(run_id):
        raise Refusal(USAGE, "--run-id 는 소문자·숫자·_.- 만(42자 이하, 끝은 영숫자)")
    guarded = [s for s in splits if s in ("val", "test")]
    if guarded:
        if args.case:
            raise Refusal(
                ACCESS, "val·test 는 --case 로 고를 수 없다(분할 전체를 한 번에 예약한다)"
            )
        if not args.run_id or not args.purpose:
            raise Refusal(ACCESS, "val·test 분할은 --run-id 와 --purpose 를 밝혀야 돌린다")
    for split, path in (("dev", args.dev_file), ("val", args.val_file)):
        if split in splits and not path:
            raise Refusal(ACCESS, f"{split} 분할은 --{split}-file 이 필요하다")
    if "test" in splits:
        if mode != "real" and mode != "dry-run":
            raise Refusal(
                ACCESS, "test 분할은 --real 로만 돌린다(--fake 로 한 번뿐인 예약을 소모하지 않는다)"
            )
        if args.purpose not in runs_guard.PURPOSES:
            raise Refusal(ACCESS, f"test 분할의 목적은 {runs_guard.PURPOSES} 중 하나")
        if not args.split_file or not args.candidate or not _HEX.fullmatch(args.candidate):
            raise Refusal(ACCESS, "test 분할은 --split-file 과 --candidate(git 해시)가 필요하다")
    return Plan(mode, splits, approve, run_id, args.repeat, tuple(args.case or ()))


def _read_cases(path: Path, split: str) -> list[Case]:
    cases = [Case.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    if any(c.split != split for c in cases):
        raise Refusal(ACCESS, f"{path.name} 에 {split} 분할이 아닌 사례가 섞여 있다")
    return cases


def _filter(items: list, wanted: tuple[str, ...]) -> list:
    if not wanted:
        return items
    ids = {getattr(i, "case", i).id for i in items}
    unknown = sorted(set(wanted) - ids)
    if unknown:
        raise Refusal(USAGE, f"없는 사례 id: {unknown}")
    return [i for i in items if getattr(i, "case", i).id in wanted]


def count_cases(args: argparse.Namespace, plan: Plan, split: str) -> int:
    """추정에 쓸 사례 수. test 는 예약 전이라 내용을 읽지 않고 파일의 사례 개수만 센다."""
    if split == "legacy":
        return len(_filter(adapter.load_legacy_cases(), plan.case_filter))
    if split == "test":
        return len(json.loads(args.split_file.read_text(encoding="utf-8")))
    return len(_filter(_read_cases(getattr(args, f"{split}_file"), split), plan.case_filter))


def estimate_text(args: argparse.Namespace, plan: Plan, ledger: Ledger) -> tuple[Decimal, str]:
    """분할별 사례 수를 더해 추정한다. 상한을 넘으면 `BudgetExceeded`."""
    counts = {s: count_cases(args, plan, s) for s in plan.splits}
    total_cases = sum(counts.values())
    if total_cases < 1:
        raise Refusal(USAGE, "사례가 하나도 없다")
    cost, text = estimate.build_estimate(
        ledger,
        args.model,
        total_cases,
        plan.repeat,
        args.calls_per_case,
        args.tokens_in,
        args.tokens_out,
    )
    return cost, f"  분할별 사례 수: {counts}\n{text}"


def _estimate_ledger(args: argparse.Namespace, plan: Plan, root: Path) -> Ledger:
    """추정이 보는 기록장: 실제 모델 기준의 상한(RUN·누적). 누적은 이전 실행 기록에서 복원한다."""
    scopes = BASELINE_RUN_SCOPES if args.stage == "baseline" else OTHER_RUN_SCOPES
    spent = store.opening_spent(root, args.stage)
    opening = {s: spent[s.value] for s in scopes if s is not Scope.RUN}
    from .cost import CAPS

    caps = dict(CAPS)
    if plan.approve is not None:
        caps[Scope.RUN] = min(caps[Scope.RUN], plan.approve)
    return Ledger(scopes, opening=opening, caps=caps)


def prepare_environment(real: bool) -> tuple[Path | None, Callable[[], None]]:
    """앱을 불러오기 전에 임시 DB·폴더·안전한 환경변수를 정한다. 돌려주는 것: (정리할 임시 폴더, 정리 함수).

    이미 앱을 불러왔으면(시험) 설정이 가리키는 곳을 그대로 두고 `env.check_process_boundary` 가 막게 한다.
    `.env` 를 이 함수가 직접 읽지는 않지만 `Settings` 가 읽을 수 있다(환경변수가 `.env` 보다 우선하므로 외부로 나가는 설정은 여기서 비워 덮고, 남은 경로는 `env.check_process_boundary` 가 막는다).
    """
    if "app.shared.config" in sys.modules:
        return None, lambda: None
    tmp = Path(tempfile.mkdtemp(prefix="gabee-eval-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/eval.db"
    os.environ["DATA_DIR"] = str(tmp)
    os.environ["JWT_SECRET"] = "eval-only-jwt-secret-not-for-production-0123456789"
    os.environ["SUBSCRIPTION_API_ENABLED"] = "true"
    for name in (
        "MAIL_BACKEND",
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "TYPESAFE_API_KEY",
    ):
        os.environ[name] = ""
    for name in (
        "INGEST_LLM_OCR",
        "INGEST_LLM_MASK",
        "PHOTO_JUDGE_LLM",
        "INGEST_REMINDERS",
        "PUSH_ENABLED",
    ):
        os.environ[name] = "false"
    if real:  # 기존 실행기(tab_agents/run.py)와 같다: 실제 폴더의 모델을 쓰고 NER 은 필수
        models = EVAL_DIR.parents[1] / "data" / "models"
        os.environ["PRIVACY_NER_MODEL_DIR"] = str(models / "ner")
        os.environ["EMBED_MODEL_DIR"] = str(models / "e5-small-ft")
        os.environ["PRIVACY_NER_MODE"] = "required"
    else:
        os.environ["ANTHROPIC_API_KEY"] = ""
        os.environ["PRIVACY_NER_MODE"] = "off"
        os.environ["PRIVACY_NER_MODEL_DIR"] = ""

    def cleanup() -> None:
        try:
            from app.shared import db

            db.engine.dispose()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return tmp, cleanup


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=EVAL_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "0000000"
    return out if _HEX.fullmatch(out) else "0000000"


def _prompt_hash() -> str:
    from app.features.ai_assistant import agents

    return hashlib.sha256(
        (agents.PROMPT_NOTE + json.dumps(agents.tool_specs())).encode()
    ).hexdigest()


def _load(args: argparse.Namespace, plan: Plan, split: str, run_id: str) -> Any:
    if split == "legacy":
        return _filter(adapter.load_legacy_cases(), plan.case_filter)
    if split == "test":
        guarded, _ = runs_guard.load_test_cases(
            args.runs_file, args.split_file, run_id, args.purpose, args.candidate, date.today()
        )
        return guarded
    return _filter(_read_cases(getattr(args, f"{split}_file"), split), plan.case_filter)


def _execute(args: argparse.Namespace, plan: Plan, out: Callable[[str], None]) -> int:
    from . import runner  # app 을 불러오므로 환경 준비 뒤에 불러온다
    from .env import UnsafeEnvironment

    mode = "real" if plan.mode == "real" else "fake"
    if mode == "real" and not switches.REAL_ENABLED:  # make_plan 을 거치지 않은 호출도 막는다
        out("거부: --real 은 아직 꺼져 있다")
        return REFUSED
    results = args.results_dir or (DEFAULT_RESULTS if mode == "real" else DEFAULT_FAKE_RESULTS)
    if mode == "real":
        from app.shared.config import settings

        if settings.llm_model != args.model:
            out(
                f"거부: 모델은 서버 설정(ANTHROPIC_MODEL)으로 고른다. 설정은 {settings.llm_model}, 요청은 {args.model}"
            )
            return REFUSED
        if not settings.anthropic_api_key:  # 값은 출력하지 않는다(있는지만 본다)
            out("거부: 서버 설정에 ANTHROPIC_API_KEY 가 없어 실제 모델을 쓸 수 없다")
            return REFUSED
    exit_code = OK
    commit, phash = _git_commit(), _prompt_hash()
    command_spent = Decimal(0)  # 이 명령에서 앞선 분할이 쓴 금액(승인 금액은 명령 전체에서 하나다)
    for split in plan.splits:
        approve = plan.approve
        if mode == "real" and approve is not None:
            approve = approve - command_spent
            if approve <= 0:
                out(f"중단: 승인 금액을 앞선 분할이 다 써서 {split} 은 실행하지 않는다")
                return max(exit_code, HALTED)
        run_id = plan.run_id if len(plan.splits) == 1 else f"{plan.run_id}-{split}"
        spent = store.opening_spent(results, args.stage) if mode == "real" else None
        opening = (
            {
                s: spent[s.value]
                for s in (BASELINE_RUN_SCOPES if args.stage == "baseline" else OTHER_RUN_SCOPES)
                if s is not Scope.RUN
            }
            if spent
            else None
        )
        ledger = runner.default_ledger(mode, approve, opening, args.stage)
        options = runner.RunOptions(
            run_id=run_id,
            repeats=plan.repeat,
            mode=mode,
            stage=args.stage,
            model=args.model,
            purpose=args.purpose,
            approved_usd=approve,
            results_root=results,
            git_commit=commit,
            prompt_hash=phash,
        )
        try:
            source = _load(args, plan, split, run_id)
            report = runner.run_cases(source, options, ledger=ledger)
        except runner.RunnerRefused as e:
            out(f"거부: {e}")
            return ACCESS
        except runs_guard.TestRunsError as e:
            out(f"거부(분할 접근): {e}")
            return ACCESS
        except runner.RunnerAbort as e:
            out(f"중단: {e}")
            return PRIVACY
        except UnsafeEnvironment as e:
            out(f"거부(허용하지 않은 환경): {e}")
            return UNSAFE
        command_spent += report.ledger.total if report.ledger is not None else Decimal(0)
        for line in report.summary_lines():
            out(line)
        if report.run_dir:
            out(f"  결과 폴더: {report.run_dir}")
        if report.halted:
            return max(exit_code, HALTED)  # 예산 중단 뒤에는 남은 분할도 실행하지 않는다
        if not report.all_counted_passed:
            exit_code = max(exit_code, FAILED)
    return exit_code


def main(argv: Sequence[str] | None = None, out: Callable[[str], None] = print) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = make_plan(args)
        if plan.mode != "fake":  # 가짜 실행은 실제 지출이 없어 비용 추정·예산 상한을 보지 않는다
            ledger = _estimate_ledger(args, plan, args.results_dir or DEFAULT_RESULTS)
            cost, text = estimate_text(args, plan, ledger)
            out(text)
        if plan.mode == "dry-run":
            out("  --dry-run: 모델도 네트워크도 부르지 않았고 아무것도 저장하지 않았다.")
            return OK
        if plan.mode == "real":
            assert plan.approve is not None
            if cost > plan.approve:
                raise Refusal(
                    OVER_BUDGET,
                    f"추정 비용 {format(cost, 'f')} USD 가 승인 금액 {format(plan.approve, 'f')} USD 보다 크다",
                )
            out(
                f"  승인 금액 {format(plan.approve, 'f')} USD 이하로 실행한다. 누적이 상한에 닿으면 다음 호출 전에 멈춘다."
            )
    except Refusal as e:
        out(f"거부: {e.message}")
        return e.code
    except BudgetExceeded as e:
        out(f"거부: {e}")
        return OVER_BUDGET
    except (OSError, ValueError) as e:
        out(f"거부: 사례를 읽을 수 없다({type(e).__name__})")
        return ACCESS
    _, cleanup = prepare_environment(real=plan.mode == "real")
    try:
        return _execute(args, plan, out)
    finally:
        cleanup()
