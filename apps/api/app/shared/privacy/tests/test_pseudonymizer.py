"""정책·가명화기·복원 시험 (합성 값만 사용)."""

import copy
import logging
import pickle

import pytest

from app.shared.privacy import ANALYSIS, REPLY, TOPICS, Action, Kind, Policy, Pseudonymizer
from app.shared.privacy.policy import BLOCKED_PLACEHOLDER

PHONE = "010-1234-5678"
EMAIL = "kim.test@example.com"


def test_policy_table():
    for policy in (ANALYSIS, REPLY, TOPICS):
        for kind in (Kind.PHONE, Kind.EMAIL, Kind.ADDRESS, Kind.PERSON):
            assert policy.action_for(kind) is Action.MASK
        for kind in (Kind.ACCOUNT, Kind.SECRET, Kind.RRN, Kind.CARD):
            assert policy.action_for(kind) is Action.BLOCK
    assert Policy("empty").action_for(Kind.PHONE) is Action.KEEP


def test_mask_and_consistency_numbering_by_appearance():
    with Pseudonymizer() as pz:
        r = pz.apply(f"전화 {PHONE} 또는 02-345-6789, 다시 {PHONE}, 메일 {EMAIL}", ANALYSIS)
    assert r.text == "전화 [PHONE_1] 또는 [PHONE_2], 다시 [PHONE_1], 메일 [EMAIL_1]"
    assert r.counts_by_kind == {"PHONE": 3, "EMAIL": 1}
    assert not r.blocked


def test_same_phone_different_formatting_same_token():
    pz = Pseudonymizer()
    a = pz.apply("010-1234-5678", ANALYSIS).text
    b = pz.apply("01012345678", ANALYSIS).text
    assert a == b == "[PHONE_1]"


def test_person_alias_shares_token_and_restores_canonical():
    pz = Pseudonymizer()
    r = pz.apply("김민수가 말했고 민수야 안녕", ANALYSIS, ("김민수",))
    assert r.text == "[PERSON_1]가 말했고 [PERSON_1]야 안녕"
    assert pz.restore("[PERSON_1]").text == "김민수"


def test_block_replaces_whole_message():
    pz = Pseudonymizer()
    r = pz.apply(f"비번 abcd1234 이고 전화는 {PHONE}", ANALYSIS)
    assert r.blocked and r.text == BLOCKED_PLACEHOLDER
    assert r.counts_by_kind == {"SECRET": 1, "PHONE": 1}
    assert pz.size == 0  # 차단된 메시지의 값은 대응표에 들어가지 않는다


def test_block_kinds_never_stored_even_if_masked():
    policy = Policy("mask-all", {k: Action.MASK for k in Kind})
    pz = Pseudonymizer()
    r = pz.apply("비번 abcd1234 야", policy)
    assert r.text == "비번 [SECRET] 야" and pz.size == 0
    assert pz.restore("[SECRET]").text == "[SECRET]"


def test_restore_only_tokens_made_by_this_request():
    pz = Pseudonymizer()
    pz.apply(f"{PHONE}", ANALYSIS)
    out = pz.restore(
        "번호 [PHONE_1] 그리고 [PHONE_9] 와 [phone_1] 와 [PHONE_ 1] 와 [PHONE_01] 와 [ PHONE_1 ]"
    )
    assert out.text.startswith(f"번호 {PHONE} 그리고 [PHONE_9]")
    assert out.text.count(PHONE) == 1  # 변형 토큰은 복원하지 않는다
    assert out.restored_tokens == ["[PHONE_1]"]
    assert out.unknown_tokens == [
        "[PHONE_9]",
        "[phone_1]",
        "[PHONE_ 1]",
        "[PHONE_01]",
        "[ PHONE_1 ]",
    ]


def test_other_request_tokens_not_restored():
    a, b = Pseudonymizer(), Pseudonymizer()
    a.apply(PHONE, ANALYSIS)
    assert b.restore("[PHONE_1]").unknown_tokens == ["[PHONE_1]"]


def test_user_written_token_lookalike_is_neutralized():
    pz = Pseudonymizer()
    r = pz.apply(f"[PHONE_1] 라고 쓰고 진짜는 {PHONE}", ANALYSIS)
    # 사용자가 쓴 [PHONE_1] 은 토큰이 아니게 바뀌고, 진짜 번호만 [PHONE_1] 이 된다
    assert r.text.count("[PHONE_1]") == 1 and "‹PHONE_1›" in r.text
    assert pz.restore(r.text).text == f"‹PHONE_1› 라고 쓰고 진짜는 {PHONE}"


def test_clear_and_exit_remove_mapping_even_on_exception():
    pz = Pseudonymizer()
    pz.apply(PHONE, ANALYSIS)
    assert pz.size == 1
    pz.clear()
    assert pz.size == 0
    assert pz.restore("[PHONE_1]").unknown_tokens == ["[PHONE_1]"]
    with pytest.raises(RuntimeError):
        pz.apply(PHONE, ANALYSIS)
    holder = Pseudonymizer()
    with pytest.raises(ValueError):
        with holder as pz2:
            pz2.apply(PHONE, ANALYSIS)
            raise ValueError("boom")
    assert holder.size == 0


def test_repr_and_str_do_not_expose_values():
    pz = Pseudonymizer()
    pz.apply(f"{PHONE} {EMAIL} 김민수", ANALYSIS, ("김민수",))
    for text in (repr(pz), str(pz), f"{pz}", f"{[pz]}"):
        assert PHONE not in text and EMAIL not in text and "김민수" not in text


def test_pickle_and_copy_are_rejected():
    pz = Pseudonymizer()
    pz.apply(PHONE, ANALYSIS)
    with pytest.raises(TypeError):
        pickle.dumps(pz)
    with pytest.raises(TypeError):
        copy.copy(pz)
    with pytest.raises(TypeError):
        copy.deepcopy(pz)


def test_no_original_values_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with Pseudonymizer() as pz:
        r = pz.apply(f"{PHONE} {EMAIL} 비번 abcd1234", ANALYSIS)
        pz.apply(f"{PHONE} {EMAIL}", ANALYSIS)
        pz.restore("[PHONE_1] [EMAIL_1]")
    assert r.blocked
    assert PHONE not in caplog.text and EMAIL not in caplog.text and "abcd1234" not in caplog.text
    assert caplog.records == []


def test_none_and_empty_text():
    pz = Pseudonymizer()
    assert pz.apply("", ANALYSIS).text == ""
    assert pz.restore("").text == ""
