"""manifest 에 하위 Agent 까지 포함한 프롬프트 해시(`agent_prompt_hashes`·`integrated_prompt_hash`)를 적는 기능 시험(L0, 가짜 모델·외부 호출 없음).

실행기가 manifest 에 적는 `prompt_hash` 는 메인 어시스턴트만 해시한다. 소통·정산·일정 Agent 프롬프트가 바뀐 것은 그 값에 드러나지 않아,
manifest 에 Agent 별 해시와 통합 해시를 함께 적는다. 기존 `prompt_hash` 의 계산과 값, 이 키가 없는 과거 기록은 그대로 읽히고 다시 쓰지 않는다.
"""

import hashlib
import json

import pytest

from evals.agent_eval import agent_hashes, cli, rescore, store
from tests.agent_eval.test_scorer_v2 import _call, _case, _manifest, _obs, _score

MAIN = hashlib.sha256(b"main").hexdigest()


def _hashes(main=MAIN):
    """네 Agent 의 해시(`main` 은 manifest 의 prompt_hash 와 같아야 한다)와 통합 해시."""
    agents = {
        "main": main,
        "family_chat": hashlib.sha256(b"family_chat").hexdigest(),
        "billing": hashlib.sha256(b"billing").hexdigest(),
        "schedule": hashlib.sha256(b"schedule").hexdigest(),
    }
    return {
        "agent_prompt_hashes": agents,
        "integrated_prompt_hash": agent_hashes.integrated_hash(agents),
    }


def _run():
    case = _case({"tools": {"required": ["ask_schedule"]}})
    return __import__("evals.agent_eval.metrics", fromlist=["CaseRun"]).CaseRun(
        case,
        (_score(case, _obs("ok", _call("ask_schedule"))),),
        (_obs("ok", _call("ask_schedule")),),
    )


def _write(tmp_path, run_id="r1", **extra):
    manifest = _manifest(run_id=run_id, stage="other", prompt_hash=MAIN, **extra)
    manifest["run_id"] = run_id
    return store.write_run(tmp_path, manifest, [_run()], [], [("a", 1)])


# ---------- 저장 검증 ----------
def test_a_manifest_with_the_agent_hashes_is_written_as_given(tmp_path):
    out = _write(tmp_path, **_hashes())
    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    assert manifest["prompt_hash"] == MAIN  # 기존 값은 그대로
    assert manifest["agent_prompt_hashes"] == _hashes()["agent_prompt_hashes"]
    assert manifest["integrated_prompt_hash"] == _hashes()["integrated_prompt_hash"]


def test_a_manifest_without_the_new_keys_is_still_accepted_and_stays_without_them(tmp_path):
    """이 기능 이전의 기록과 같은 모양: 새 키가 없어도 쓰고 읽을 수 있고, 저절로 채워지지 않는다."""
    out = _write(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    assert "agent_prompt_hashes" not in manifest and "integrated_prompt_hash" not in manifest
    assert store.opening_spent(tmp_path, "other")["project"] == 0  # 읽기 쪽도 새 키 없이 동작


def test_old_and_new_manifests_can_sit_in_the_same_results_folder(tmp_path):
    _write(tmp_path, run_id="old-1")
    _write(tmp_path, run_id="new-1", **_hashes())
    assert store.opening_spent(tmp_path, "other")["project"] == 0
    assert store.read_opening(tmp_path, "other").spent["project"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"agent_prompt_hashes": _hashes()["agent_prompt_hashes"]},  # 통합 해시만 빠짐
        {"integrated_prompt_hash": _hashes()["integrated_prompt_hash"]},  # Agent 별 해시만 빠짐
    ],
)
def test_the_two_keys_are_all_or_nothing(tmp_path, bad):
    with pytest.raises(ValueError, match="모두 있거나 모두 없어야"):
        _write(tmp_path, **bad)


def test_the_main_hash_must_equal_the_existing_prompt_hash(tmp_path):
    other = _hashes(main=hashlib.sha256(b"someone else").hexdigest())
    with pytest.raises(ValueError, match="main"):
        _write(tmp_path, **other)


def test_the_integrated_hash_must_be_recomputable_from_the_agent_hashes(tmp_path):
    forged = {**_hashes(), "integrated_prompt_hash": hashlib.sha256(b"forged").hexdigest()}
    with pytest.raises(ValueError, match="integrated_prompt_hash"):
        _write(tmp_path, **forged)


@pytest.mark.parametrize("drop", ["main", "family_chat", "billing", "schedule"])
def test_every_agent_must_be_present(tmp_path, drop):
    hashes = _hashes()
    agents = {k: v for k, v in hashes["agent_prompt_hashes"].items() if k != drop}
    with pytest.raises(ValueError, match="형식"):
        _write(
            tmp_path,
            agent_prompt_hashes=agents,
            integrated_prompt_hash=hashes["integrated_prompt_hash"],
        )


def test_unknown_agents_and_malformed_values_are_refused(tmp_path):
    hashes = _hashes()
    extra_agent = {**hashes["agent_prompt_hashes"], "evil": hashlib.sha256(b"x").hexdigest()}
    with pytest.raises(ValueError, match="형식"):
        _write(
            tmp_path,
            agent_prompt_hashes=extra_agent,
            integrated_prompt_hash=hashes["integrated_prompt_hash"],
        )
    short = {**hashes["agent_prompt_hashes"], "billing": "abc1234"}
    with pytest.raises(ValueError, match="형식"):
        _write(
            tmp_path,
            run_id="r2",
            agent_prompt_hashes=short,
            integrated_prompt_hash=hashes["integrated_prompt_hash"],
        )
    with pytest.raises(ValueError, match="형식"):
        _write(
            tmp_path,
            run_id="r3",
            agent_prompt_hashes=hashes["agent_prompt_hashes"],
            integrated_prompt_hash="zz",
        )


# ---------- 실행기(가짜 모델) ----------
def _fake_run(tmp_path, run_id):
    lines: list[str] = []
    code = cli.main(
        [
            "--fake",
            "--case",
            "b-total",
            "--run-id",
            run_id,
            "--results-dir",
            str(tmp_path / "results"),
        ],
        out=lines.append,
    )
    assert code == 0, "\n".join(lines)
    return json.loads((tmp_path / "results" / run_id / "manifest.json").read_text("utf-8"))


def test_a_fake_run_records_the_hashes_of_all_four_agents(tmp_path):
    manifest = _fake_run(tmp_path, "fake-h1")
    expected = agent_hashes.agent_hashes()  # 같은 코드·고정 시계에서 다시 계산한 값
    assert manifest["agent_prompt_hashes"] == expected
    assert set(manifest["agent_prompt_hashes"]) == {"main", "family_chat", "billing", "schedule"}
    assert manifest["integrated_prompt_hash"] == agent_hashes.integrated_hash(expected)
    # 기존 prompt_hash 는 계산도 값도 그대로(메인 해시와 같다)
    assert manifest["prompt_hash"] == cli._prompt_hash() == expected["main"]


def test_two_runs_of_the_same_code_record_the_same_hashes(tmp_path):
    first, second = _fake_run(tmp_path, "fake-a"), _fake_run(tmp_path, "fake-b")
    for key in ("prompt_hash", "agent_prompt_hashes", "integrated_prompt_hash"):
        assert first[key] == second[key]


def test_the_manifest_records_exactly_what_agent_hashes_returns(tmp_path, monkeypatch):
    """manifest 의 값은 `agent_hashes.agent_hashes()`(날짜와 무관하게 고정 시계로 계산, `test_agent_hashes` 가 시험)를 그대로 옮긴 것이다."""
    real = agent_hashes.agent_hashes()
    stub = {**real, "billing": hashlib.sha256(b"stub").hexdigest()}
    monkeypatch.setattr(agent_hashes, "agent_hashes", lambda: stub)
    manifest = _fake_run(tmp_path, "fake-stub")
    assert manifest["agent_prompt_hashes"] == stub
    assert manifest["integrated_prompt_hash"] == agent_hashes.integrated_hash(stub)


def test_changing_only_the_communication_agent_prompt_changes_the_integrated_hash(
    tmp_path, monkeypatch
):
    from app.features.family_chat import agent as family_chat

    before = _fake_run(tmp_path, "fake-before")
    original = family_chat.system_prompt
    monkeypatch.setattr(family_chat, "system_prompt", lambda: original() + " 추가 문장")
    after = _fake_run(tmp_path, "fake-after")
    # 기존 manifest 의 prompt_hash 는 이 변화를 보지 못한다(그래서 통합 해시가 필요하다)
    assert before["prompt_hash"] == after["prompt_hash"]
    assert before["integrated_prompt_hash"] != after["integrated_prompt_hash"]
    changed = {
        k
        for k in before["agent_prompt_hashes"]
        if before["agent_prompt_hashes"][k] != after["agent_prompt_hashes"][k]
    }
    assert changed == {"family_chat"}


# ---------- 재채점 ----------
def _source(tmp_path, **extra):
    case = _case({"answer": {"contains": ["알 수 없"]}}, cid="iso")
    obs = _obs("알 수 없어요", _call("ask_family_chat"))
    from evals.agent_eval import metrics

    run = metrics.CaseRun(case, (_score(case, obs),), (obs,))
    manifest = _manifest(run_id="real-dev-1", prompt_hash=MAIN, **extra)
    return store.write_run(tmp_path / "src", manifest, [run], [], [("a", 1)]), case


def _judge(case, obs):
    from evals.agent_eval import scoring

    return scoring.score_case(case, obs, _no_security())


def _no_security():
    from tests.agent_eval.test_scorer_v2 import NONE

    return NONE


def test_a_rescore_carries_the_agent_hashes_of_a_source_that_has_them(tmp_path):
    src, case = _source(tmp_path, **_hashes())
    result = rescore.rescore(src, [case], label="same", judge=_judge)
    out = rescore.write(result, tmp_path / "out", git_commit="abc1234")
    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    assert manifest["agent_prompt_hashes"] == _hashes()["agent_prompt_hashes"]
    assert manifest["integrated_prompt_hash"] == _hashes()["integrated_prompt_hash"]


def test_a_rescore_of_an_old_source_without_the_keys_still_works_and_adds_none(tmp_path):
    src, case = _source(tmp_path)
    original = {p.name: p.read_bytes() for p in src.iterdir()}
    result = rescore.rescore(src, [case], label="same", judge=_judge)
    out = rescore.write(result, tmp_path / "out", git_commit="abc1234")
    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    assert "agent_prompt_hashes" not in manifest and "integrated_prompt_hash" not in manifest
    assert {p.name: p.read_bytes() for p in src.iterdir()} == original  # 원본은 바이트 그대로
