"""확정된 시나리오 목록 72건의 시험(L0). 목록·잠금 파일만 읽고 LLM·DB·네트워크는 쓰지 않는다."""

import copy
import json
from collections import Counter

import pytest

from evals.agent_eval import scenarios as sc
from evals.agent_eval.case_files import (
    check_distribution,
    check_scenarios_overlap,
)
from evals.agent_eval.seeds import data as seed_data


@pytest.fixture(scope="module")
def raw():
    return sc.load_raw()


@pytest.fixture(scope="module")
def lst():
    return sc.load_scenarios()


@pytest.fixture(scope="module")
def lock():
    return json.loads(sc.LOCK_PATH.read_text("utf-8"))


def test_counts_by_split_and_topic(lst):
    assert len(lst.scenarios) == 72
    assert Counter(s.split for s in lst.scenarios) == {"dev": 36, "val": 18, "test": 18}
    by = Counter((s.topic, s.split) for s in lst.scenarios)
    for i, topic in enumerate(sc.TOPICS):
        want = (3, 2, 1) if i < 6 else (3, 1, 2)
        assert [by[(topic, sp)] for sp in ("dev", "val", "test")] == list(want), topic
    check_distribution(lst)


def test_category_counts_follow_topics(lst):
    cats = Counter(s.category for s in lst.scenarios)
    assert cats == {"A": 6, "B": 6, "C": 6, "D": 30, "E": 6, "F": 6, "G": 6, "H": 6}


def test_world_rules(lst):
    assert lst.worlds["w1"].status == "built"
    assert lst.worlds["w2"].status == lst.worlds["w3"].status == "planned"
    assert {s.world_id for s in lst.scenarios if s.split == "dev"} == {"w1"}
    assert {s.world_id for s in lst.scenarios if s.split == "val"} == {"w2"}
    assert {s.world_id for s in lst.scenarios if s.split == "test"} == {"w3"}


def test_unique_ids_and_signatures(lst):
    ids = [s.id for s in lst.scenarios] + [u.id for u in lst.unsupported]
    assert len(set(ids)) == len(ids)
    keys = {
        (
            sc.normalize(s.question_signature),
            s.setup_hint.audience,
            s.setup_hint.room,
            s.setup_hint.as_user,
        )
        for s in lst.scenarios
    }
    assert len(keys) == 72
    assert len({sc.normalize(s.question_signature) for s in lst.scenarios}) == 72
    check_scenarios_overlap(lst)


def test_unsupported_list(lst):
    assert 6 <= len(lst.unsupported) <= 8
    assert all(
        u.reason and any(t.startswith("schedule.") for t in u.blocked_tools)
        for u in lst.unsupported
    )
    signatures = {sc.normalize(s.question_signature) for s in lst.scenarios}
    assert not any(sc.normalize(u.question_signature) in signatures for u in lst.unsupported)


def test_security_scenarios_name_private_user(lst):
    """개발셋 leak·injection 시나리오의 노리는 표식은 질문자가 모르는 비공개 값이고 질문에 들어 있지 않다."""
    dev_targets = [s for s in lst.scenarios if s.split == "dev" and s.risk in {"leak", "injection"}]
    assert len(dev_targets) == 8
    for s in dev_targets:
        user = s.setup_hint.as_user or seed_data.FAMILY_USERS[0]
        assert s.private_targets, s.id
        for t in s.private_targets:
            assert t in seed_data.forbidden_strings(user), (s.id, t)
            assert sc.normalize(t) not in sc.normalize(s.question_signature), (s.id, t)
    assert not [s.id for s in lst.scenarios if s.split != "dev" and s.private_targets]


def test_lock_matches_and_history(lst, lock):
    sc.verify_lock(lst, lock)
    section = lock["scenarios"]
    assert section["count"] == 72
    assert section["sha256"] == sc.list_hash(lst)
    assert set(section["per_split"]) == {"dev", "val", "test"}
    assert section["history"][0]["from"] is None
    assert section["history"][-1]["to"] == section["sha256"]


def test_changed_list_breaks_lock(raw, lock):
    changed = copy.deepcopy(raw)
    changed["scenarios"][0]["purpose"] += " 수정"
    with pytest.raises(sc.ScenarioError, match="잠금 파일"):
        sc.verify_lock(sc.parse_list(changed), lock)


def test_history_chain_must_connect(lst, lock):
    broken = copy.deepcopy(lock)
    broken["scenarios"]["history"].append(
        {"at": "2026-11-13", "reason": "x", "from": "0" * 64, "to": broken["scenarios"]["sha256"]}
    )
    with pytest.raises(sc.ScenarioError, match="이어지지"):
        sc.verify_lock(lst, broken)
    wrong_tail = copy.deepcopy(lock)
    wrong_tail["scenarios"]["history"][-1]["to"] = "1" * 64
    with pytest.raises(sc.ScenarioError, match="마지막 to"):
        sc.verify_lock(lst, wrong_tail)


def test_history_with_reason_passes(lst, lock):
    ok = copy.deepcopy(lock)
    sec = ok["scenarios"]
    sec["history"].insert(0, {"at": "2026-11-11", "reason": "초안", "from": None, "to": "2" * 64})
    sec["history"][1]["from"] = "2" * 64
    sc.verify_lock(lst, ok)


def test_hashes_are_stable_and_split_scoped(lst, raw):
    assert sc.list_hash(lst) == sc.list_hash(sc.parse_list(copy.deepcopy(raw)))
    changed = copy.deepcopy(raw)
    victim = next(s for s in changed["scenarios"] if s["split"] == "test")
    victim["purpose"] += " 수정"
    before, after = sc.split_hashes(lst), sc.split_hashes(sc.parse_list(changed))
    assert before["dev"] == after["dev"] and before["val"] == after["val"]
    assert before["test"] != after["test"]
    assert sc.canonical({"b": 1, "a": "가"}) == '{"a":"가","b":1}'.encode()


def test_malformed_list_is_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["scenarios"][0]["category"] = "H"
    with pytest.raises(sc.ScenarioError, match="범주"):
        sc.parse_list(bad)
    bad = copy.deepcopy(raw)
    bad["scenarios"][1]["world_id"] = "w2"
    with pytest.raises(sc.ScenarioError, match="월드"):
        sc.parse_list(bad)
    bad = copy.deepcopy(raw)
    bad["scenarios"][1]["id"] = bad["scenarios"][0]["id"]
    with pytest.raises(sc.ScenarioError, match="겹친다"):
        sc.parse_list(bad)
    bad = copy.deepcopy(raw)
    bad["scenarios"][2]["question_signature"] = bad["scenarios"][0]["question_signature"] + "?"
    bad["scenarios"][2]["setup_hint"] = bad["scenarios"][0]["setup_hint"]
    with pytest.raises(sc.ScenarioError, match="중복"):
        sc.parse_list(bad)


def test_val_test_need_variant_note(raw):
    bad = copy.deepcopy(raw)
    victim = next(s for s in bad["scenarios"] if s["split"] == "val")
    victim["expected_behavior"] = "도구를 부른다."
    with pytest.raises(sc.ScenarioError, match="변형 월드"):
        sc.parse_list(bad)


def test_seed_extension_scenarios_are_tagged(lst):
    tagged = [s for s in lst.scenarios if sc.SEED_EXTENSION_TAG in s.expected_behavior]
    assert tagged
    assert all(s.split == "dev" for s in tagged)  # val·test 는 변형 월드 가정으로 쓴다
    assert sum(s.topic == "doc_search" for s in tagged) == 3
