"""쓰기 도구 목록이 실제 코드와 맞는지 보는 시험(L0). 도구를 만들기만 하고 부르지 않는다."""

import pytest

from evals.agent_eval import write_tools as wt


def test_the_lists_match_the_tools_the_real_code_builds():
    wt.verify_against_code()  # 어긋나면 ValueError


def test_billing_write_tools_are_exactly_the_proposal_tools_of_the_real_builder():
    real = wt.real_tool_names()["billing"]
    assert wt.WRITE_TOOLS["billing"] == real["all"] - real["read_only"]
    assert all(name.startswith("propose_") for name in wt.WRITE_TOOLS["billing"])


def test_a_new_unclassified_real_tool_is_reported(monkeypatch):
    real = wt.real_tool_names()
    real["main"]["all"] = real["main"]["all"] | {"delete_everything"}
    monkeypatch.setattr(wt, "real_tool_names", lambda: real)
    with pytest.raises(ValueError, match="delete_everything"):
        wt.verify_against_code()


def test_a_listed_tool_that_no_longer_exists_and_a_misfiled_write_tool_are_reported(monkeypatch):
    real = wt.real_tool_names()
    real["billing"]["all"] = real["billing"]["all"] - {"propose_delete_expense"}
    monkeypatch.setattr(wt, "real_tool_names", lambda: real)
    with pytest.raises(ValueError, match="propose_delete_expense"):
        wt.verify_against_code()
    monkeypatch.undo()
    monkeypatch.setitem(
        wt.READ_TOOLS, "billing", wt.READ_TOOLS["billing"] | {"propose_add_expense"}
    )
    with pytest.raises(ValueError, match="읽기와 쓰기"):
        wt.verify_against_code()


def test_web_search_is_external_and_never_listed():
    everything = set().union(*wt.WRITE_TOOLS.values(), *wt.READ_TOOLS.values())
    assert wt.EXTERNAL_TOOLS.isdisjoint(everything)
    assert wt.is_write("billing", "propose_add_expense") and not wt.is_write(
        "billing", "list_expenses"
    )
    assert not wt.is_write("unknown_agent", "anything")
