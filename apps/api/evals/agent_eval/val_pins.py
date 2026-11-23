"""검증셋(val) 정답지·기준의 사전 고정값(`data/cases_val.revisions.json`)을 만들고 확인한다.

val 정답지는 **어떤 모델 출력도 보기 전에** 정했다(실제 모델·val 실행 0회, 가짜 모델만 썼다). 이 모듈은 그 시점의 정답지·기준을 해시로 고정한다: 사례별 `case_sha256`,
사례 파일의 LF 정규화 해시, 평가 기준 v2(`criteria_v2.py` 와 `cases_dev.v2.json` 의 LF 정규화 해시, 채점기 코드 해시, `SCORER_VERSION`), 프롬프트 해시(실행기가 manifest 에 적는 값),
시나리오 목록·잠금 해시. `test_val_pins.py` 가 현재 파일이 이 값과 같은지 보므로 val 사례 파일이나 기준이 바뀌면 시험이 깨지고, 그때는 변경 이력을 새로 기록한다
(val 결과를 본 뒤에는 정답지·기준을 소급해서 바꾸지 않는다. 바꾸면 그 val 결과는 무효로 표시한다).

`python -m evals.agent_eval.val_pins`(apps/api 에서)가 파일을 다시 쓴다. 앱을 불러오는 프롬프트 해시는 CLI 와 같은 환경 준비(`cli.prepare_environment`)를 거쳐 읽는다
(임시 DB·외부로 나가는 설정 비움, `.env` 를 직접 읽지 않는다).
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import agent_hashes, scenarios, scoring, val_cases
from .dev_cases import case_sha256, file_sha256
from .scenarios import DATA_DIR

PINS_PATH = DATA_DIR / "cases_val.revisions.json"
CRITERIA_V2_PY = Path(__file__).resolve().parent / "criteria_v2.py"
CASES_DEV_V2_PATH = DATA_DIR / "cases_dev.v2.json"
# 평가 기준 v2 PR 에서 dev 108 case-run 이 manifest 에 적은 프롬프트 해시의 앞부분. 현재 코드가 같은 값을 내는지 본다(전체 값은 아래 `prompt_hash`)
DEV_MANIFEST_PROMPT_HASH_PREFIX = "d658d8e1"
# dev 108 case-run 이 manifest 에 적은 전체 값. 기존 dev 결과·v2 재채점은 이 값에 묶여 있고 바꾸지 않는다.
DEV_MANIFEST_PROMPT_HASH = "d658d8e16968b5fd099ca3e9e340039ccd960118a0cd487ae02db26ff878b36d"
# 운영 프롬프트가 dev 108 이후 바뀌어 val 의 프롬프트 해시가 dev 값과 다르면 그 이유를 고정 파일에 남긴다.
PROMPT_CHANGE_NOTE = (
    "운영 일정 에이전트 프롬프트·도구 설명이 dev 108 case-run 이후 release/1.3 에서 바뀌어(#496 앱에이전트 수정·삭제 개선, #505 앱에이전트 정책 개선, #506 앱 에이전트 날짜 계산 방식 개선) "
    "프롬프트 해시가 dev 값(DEV_MANIFEST_PROMPT_HASH)과 다르다. dev 108 공식 결과·v2 재채점은 옛 해시에 묶인 그대로이고, "
    "val 은 이 새 해시의 프롬프트로만 돈다(dev 점수와 직접 비교하지 않는다)."
)
STATEMENT = (
    "이 정답지(cases_val.json)와 평가 기준 v2 는 어떤 모델 출력도 보기 전에 확정했다(val 사례에 대한 실제 모델의 출력은 한 번도 본 적이 없다). "
    "val 실행 0회, 실제 Claude 호출 0회로 만들고 가짜 모델과 직접 만든 관찰로만 시험했다. "
    "val 결과를 본 뒤에는 이 값들을 소급해서 바꾸지 않는다. 바뀌면 test_val_pins.py 가 실패하고, 그 val 결과는 무효로 표시한 뒤 변경 이력을 새로 기록한다."
)


def _sha_text_lf(path: Path) -> str:
    return file_sha256(path.read_bytes())


def prompt_hash() -> str:
    """실행기가 manifest 에 적는 프롬프트 해시(`cli._prompt_hash`). 앱을 불러오므로 환경 준비 뒤에만 부른다."""
    from . import cli

    return cli._prompt_hash()


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out or "unknown"


def build(
    *,
    prompt: str,
    created_in_commit: str,
    final_key_commit: str,
    pinned_on_top_of: str,
    agents: dict[str, str] | None = None,
) -> dict[str, Any]:
    """현재 파일들에서 계산한 고정값. 시험은 `prompt`·커밋 값은 파일의 것을 넘기고 나머지는 현재 파일에서 다시 계산한 것과 비교한다."""
    raw = Path(
        val_cases.CASES_VAL_PATH
    ).read_bytes()  # 디스크에 있는 파일 그대로 고정한다(빌더 결과가 아니라 정답지 파일)
    rows = json.loads(raw.decode("utf-8"))
    lst = scenarios.load_scenarios()
    lock = json.loads(scenarios.LOCK_PATH.read_text("utf-8"))["scenarios"]
    dev_v2_revisions = json.loads((DATA_DIR / "cases_dev.v2.revisions.json").read_text("utf-8"))
    return {
        "note": STATEMENT,
        "frozen_before_any_model_output": True,
        "created_in_commit": created_in_commit,  # 정답지 파일을 처음 커밋한 커밋
        "final_key_commit": final_key_commit,  # 현재 내용의 정답지 파일이 들어간 커밋(그 사이에 모델 출력은 한 번도 보지 않았다)
        "pinned_on_top_of_commit": pinned_on_top_of,
        "split": "val",
        "world": "w2",
        "case_count": len(rows),
        "cases_val_file_sha256": file_sha256(raw),
        "cases": [{"case_id": r["id"], "case_sha256": case_sha256(r)} for r in rows],
        "scorer_version": scoring.SCORER_VERSION,
        "criteria": {
            "name": "criteria v2",
            "criteria_v2_py_sha256": _sha_text_lf(CRITERIA_V2_PY),
            "cases_dev_v2_file_sha256": _sha_text_lf(CASES_DEV_V2_PATH),
            "cases_dev_v2_revisions_v2_dev_file_sha256": dev_v2_revisions["v2_dev_file_sha256"],
            "scoring_py_sha256": _sha_text_lf(Path(scoring.__file__)),
            "matchers_py_sha256": _sha_text_lf(Path(scoring.__file__).with_name("matchers.py")),
            "scorer_version": scoring.SCORER_VERSION,
        },
        "prompt_hash": prompt,
        "dev_manifest_prompt_hash_prefix": DEV_MANIFEST_PROMPT_HASH_PREFIX,
        "dev_manifest_prompt_hash": DEV_MANIFEST_PROMPT_HASH,
        "prompt_changed_since_dev108": prompt != DEV_MANIFEST_PROMPT_HASH,
        "prompt_change_note": PROMPT_CHANGE_NOTE if prompt != DEV_MANIFEST_PROMPT_HASH else "",
        # 하위 Agent(가족 대화·정산·일정)까지 포함한 해시. manifest 의 prompt_hash 는 메인만 본다(위 `main` 과 같은 값)
        "agent_prompt_hashes": agents if agents is not None else agent_hashes.agent_hashes(),
        "integrated_prompt_hash": agent_hashes.integrated_hash(agents),
        "scenarios": {
            "scenarios_val_file_sha256": _sha_text_lf(DATA_DIR / "scenarios_val.json"),
            "scenario_list_sha256": scenarios.list_hash(lst),
            "per_split_val_sha256": lock["per_split"]["val"],
            "val_world_status": lst.worlds["w2"].status,
        },
        "world_digests": {},
    }


def render(pins: dict[str, Any]) -> str:
    return json.dumps(pins, ensure_ascii=False, indent=1) + "\n"


def write(
    *,
    created_in_commit: str | None = None,
    final_key_commit: str | None = None,
    world_digest: str | None = None,
) -> dict[str, Any]:
    """파일을 다시 쓴다. `created_in_commit`·`final_key_commit` 은 사례 파일을 처음·마지막으로 커밋한 커밋(없으면 파일의 기존 값). 월드 해시(w2)는 DB 가 필요해 `world_support.world_digest` 로 잰 값을 넘긴다(없으면 기존 값 유지)."""
    from . import cli

    old = json.loads(PINS_PATH.read_text("utf-8")) if PINS_PATH.exists() else {}
    _, cleanup = cli.prepare_environment(real=False)
    try:
        pins = build(
            prompt=prompt_hash(),
            created_in_commit=created_in_commit or old.get("created_in_commit", _git_head()),
            final_key_commit=final_key_commit or old.get("final_key_commit", _git_head()),
            pinned_on_top_of=_git_head(),
        )
    finally:
        cleanup()
    digests = dict(old.get("world_digests", {}))
    if world_digest is not None:
        digests["w2"] = world_digest
    pins["world_digests"] = digests
    PINS_PATH.write_text(render(pins), encoding="utf-8", newline="\n")
    return pins


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = write()
    print(f"{result['case_count']}건의 고정값을 {PINS_PATH.name} 에 썼다")
