"""검증셋 정답지·기준 사전 고정값(`data/cases_val.revisions.json`) 시험(L0).

val 정답지는 어떤 모델 출력도 보기 전에 확정했고, 그 시점의 해시를 `val_pins` 가 고정한다. 이 시험은 현재 파일·기준이 고정값과 같음을 본다:
val 사례 파일, 평가 기준 v2(`criteria_v2.py`·`cases_dev.v2.json`), 채점기 코드, `SCORER_VERSION`, 프롬프트 해시, 시나리오 목록·월드 w2 가 바뀌면 이 시험이 깨지고,
그때는 val 결과를 열기 전이라면 변경 이력을 새로 기록하고 열린 뒤라면 그 val 결과를 무효로 표시한다(소급 변경 금지).
"""

import json
import shutil

import pytest

from evals.agent_eval import cli, scenarios, scoring, val_cases, val_pins
from evals.agent_eval.clock import frozen_clock
from evals.agent_eval.dev_cases import case_sha256, file_sha256
from evals.agent_eval.seeds import build_world
from tests.agent_eval.world_support import world_digest


@pytest.fixture(scope="module")
def pins():
    return json.loads(val_pins.PINS_PATH.read_text("utf-8"))


def current(pins):
    """현재 파일에서 다시 계산한 고정값(프롬프트·커밋·월드 해시는 파일의 값을 그대로 넘겨 따로 시험한다)."""
    out = val_pins.build(
        prompt=pins["prompt_hash"],
        created_in_commit=pins["created_in_commit"],
        final_key_commit=pins["final_key_commit"],
        pinned_on_top_of=pins["pinned_on_top_of_commit"],
        agents=pins["agent_prompt_hashes"],
    )
    out["world_digests"] = pins["world_digests"]
    return out


def test_the_pins_file_equals_what_the_current_files_give(pins):
    assert current(pins) == pins
    assert val_pins.PINS_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n") == val_pins.render(
        pins
    )


def test_the_statement_says_the_key_was_fixed_before_any_model_output(pins):
    assert pins["frozen_before_any_model_output"] is True
    assert "어떤 모델 출력" in pins["note"] and "보기 전에 확정" in pins["note"]
    assert "소급해서 바꾸지 않는다" in pins["note"] and "실제 Claude 호출 0회" in pins["note"]
    for key in ("created_in_commit", "final_key_commit", "pinned_on_top_of_commit"):
        assert len(pins[key]) == 40 and pins[key] != "unknown", key
    assert pins["split"] == "val" and pins["world"] == "w2"


def test_every_case_hash_and_the_file_hash_match_the_val_file(pins):
    rows = json.loads(val_cases.CASES_VAL_PATH.read_text("utf-8"))
    assert pins["case_count"] == len(rows) == 18
    assert [(c["case_id"], c["case_sha256"]) for c in pins["cases"]] == [
        (r["id"], case_sha256(r)) for r in rows
    ]
    assert pins["cases_val_file_sha256"] == file_sha256(val_cases.CASES_VAL_PATH.read_bytes())
    assert len({c["case_sha256"] for c in pins["cases"]}) == 18
    # 파일은 빌더 결과이기도 하다(손으로 고친 파일이 아니다)
    assert pins["cases_val_file_sha256"] == file_sha256(
        val_cases.render(val_cases.build()).encode()
    )


def test_the_hash_ignores_line_endings_of_the_checkout(tmp_path):
    raw = val_cases.CASES_VAL_PATH.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    assert file_sha256(lf) == file_sha256(lf.replace(b"\n", b"\r\n"))


def test_the_criteria_v2_and_scorer_pins(pins):
    assert pins["scorer_version"] == scoring.SCORER_VERSION == 2
    crit = pins["criteria"]
    assert crit["name"] == "criteria v2" and crit["scorer_version"] == 2
    assert crit["criteria_v2_py_sha256"] == file_sha256(val_pins.CRITERIA_V2_PY.read_bytes())
    assert crit["cases_dev_v2_file_sha256"] == file_sha256(val_pins.CASES_DEV_V2_PATH.read_bytes())
    revisions = json.loads((val_pins.DATA_DIR / "cases_dev.v2.revisions.json").read_text("utf-8"))
    assert crit["cases_dev_v2_revisions_v2_dev_file_sha256"] == revisions["v2_dev_file_sha256"]
    assert (
        crit["cases_dev_v2_file_sha256"] == revisions["v2_dev_file_sha256"]
    )  # dev v2 사례 파일과 변경 기록이 일치한다


def test_the_pinned_prompt_hash_is_what_the_runner_computes_now(pins):
    """실행기가 manifest 에 적는 프롬프트 해시(`cli._prompt_hash`)가 고정값과 같다. dev 108 case-run 의 manifest 값(d658d8e1…)은 그대로 남기고,
    운영 프롬프트가 그 뒤 바뀌어 값이 다르면 그 사실과 이유(`prompt_change_note`)가 고정 파일에 있어야 한다(조용히 다른 값으로 바뀌지 못한다)."""
    assert cli._prompt_hash() == pins["prompt_hash"]
    assert pins["dev_manifest_prompt_hash_prefix"] == val_pins.DEV_MANIFEST_PROMPT_HASH_PREFIX
    assert pins["dev_manifest_prompt_hash"] == val_pins.DEV_MANIFEST_PROMPT_HASH
    assert pins["dev_manifest_prompt_hash"].startswith(pins["dev_manifest_prompt_hash_prefix"])
    assert len(pins["prompt_hash"]) == 64
    changed = pins["prompt_hash"] != pins["dev_manifest_prompt_hash"]
    assert pins["prompt_changed_since_dev108"] is changed
    assert bool(pins["prompt_change_note"]) is changed
    if changed:
        assert "#496" in pins["prompt_change_note"] and "dev 108" in pins["prompt_change_note"]


def test_the_pinned_agent_hashes_and_the_integrated_hash_are_what_the_code_gives_now(pins):
    """하위 Agent(가족 대화·정산·일정)까지 포함한 해시가 고정값과 같다. `main` 은 manifest 의 프롬프트 해시와 같은 값이고,
    통합 해시는 에이전트별 해시에서 다시 계산한 값과 같다(val 실모델 실행 전에 이 값들을 고정한다)."""
    from evals.agent_eval import agent_hashes

    now = agent_hashes.agent_hashes()
    assert pins["agent_prompt_hashes"] == now
    assert pins["agent_prompt_hashes"]["main"] == pins["prompt_hash"]
    assert pins["integrated_prompt_hash"] == agent_hashes.integrated_hash(now)
    assert tuple(pins["agent_prompt_hashes"]) == agent_hashes.AGENTS
    assert all(len(v) == 64 for v in pins["agent_prompt_hashes"].values())


def test_the_scenario_list_and_the_w2_world_status_are_pinned(pins):
    sc = pins["scenarios"]
    lst = scenarios.load_scenarios()
    lock = json.loads(scenarios.LOCK_PATH.read_text("utf-8"))["scenarios"]
    assert sc["scenario_list_sha256"] == scenarios.list_hash(lst) == lock["sha256"]
    assert (
        sc["per_split_val_sha256"] == lock["per_split"]["val"] == scenarios.split_hashes(lst)["val"]
    )
    assert sc["scenarios_val_file_sha256"] == file_sha256(
        (val_pins.DATA_DIR / "scenarios_val.json").read_bytes()
    )
    assert sc["val_world_status"] == "built"


def test_the_w2_world_digest_is_pinned(client, pins):
    with frozen_clock():
        digest = world_digest(client, build_world(client, world="w2"))
    assert digest == pins["world_digests"]["w2"]


# ---- 값이 바뀌면 깨진다(시험이 실제로 변경을 잡는다) --------------------------------------------------------------------------
def test_editing_a_case_changes_the_pins(pins, tmp_path, monkeypatch):
    edited = tmp_path / "cases_val.json"
    rows = json.loads(val_cases.CASES_VAL_PATH.read_text("utf-8"))
    rows[3]["expect"]["answer"]["contains"].append("추가한 문구")
    edited.write_text(val_cases.render(rows), encoding="utf-8", newline="\n")
    monkeypatch.setattr(val_cases, "CASES_VAL_PATH", edited)
    changed = current(pins)
    assert changed != pins
    assert changed["cases_val_file_sha256"] != pins["cases_val_file_sha256"]
    differing = [
        a["case_id"] for a, b in zip(changed["cases"], pins["cases"], strict=True) if a != b
    ]
    assert differing == [rows[3]["id"]]  # 어느 사례가 바뀌었는지 가려낸다


def test_editing_the_criteria_file_changes_the_pins(pins, tmp_path, monkeypatch):
    copy = tmp_path / "criteria_v2.py"
    shutil.copyfile(val_pins.CRITERIA_V2_PY, copy)
    copy.write_text(copy.read_text("utf-8") + "\n# 바꿈\n", encoding="utf-8")
    monkeypatch.setattr(val_pins, "CRITERIA_V2_PY", copy)
    changed = current(pins)
    assert changed["criteria"]["criteria_v2_py_sha256"] != pins["criteria"]["criteria_v2_py_sha256"]
    assert changed != pins


def test_changing_the_scorer_version_changes_the_pins(pins, monkeypatch):
    monkeypatch.setattr(scoring, "SCORER_VERSION", 3)
    assert current(pins) != pins
