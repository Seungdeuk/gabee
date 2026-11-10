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


def test_a_write_tool_moved_to_the_read_list_is_caught_by_the_name_cross_check(monkeypatch):
    monkeypatch.setitem(wt.WRITE_TOOLS, "main", wt.WRITE_TOOLS["main"] - {"remember"})
    monkeypatch.setitem(wt.READ_TOOLS, "main", wt.READ_TOOLS["main"] | {"remember"})
    with pytest.raises(ValueError, match="remember 은 이름으로는 write"):
        wt.verify_against_code()


def test_a_new_tool_with_an_unclassifiable_name_is_reported(monkeypatch):
    real = wt.real_tool_names()
    real["family_chat"]["all"] = real["family_chat"]["all"] | {"frobnicate"}
    monkeypatch.setattr(wt, "real_tool_names", lambda: real)
    monkeypatch.setitem(wt.READ_TOOLS, "family_chat", wt.READ_TOOLS["family_chat"] | {"frobnicate"})
    with pytest.raises(ValueError, match="분류할 수 없는 도구 frobnicate"):
        wt.verify_against_code()


def test_main_tool_assembly_in_rag_chat_has_not_changed_shape():
    """real_tool_names 가 옮겨 둔 메인의 도구 조합 식이 rag_chat.py 에서 바뀌면 알려 준다."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "app/features/ai_assistant/knowledge/rag_chat.py"
    src = path.read_text(encoding="utf-8")
    block = src[src.index("tools=tools.TOOL_SPECS") : src.index("run = tool_graph.Run(")]
    assert re.findall(r"tools\.\w+|agents\.tool_specs\(\)|_web_tool\(\)", block) == [
        "tools.TOOL_SPECS",
        "agents.tool_specs()",
        "tools.MEMORY_TOOL_SPECS",
        "tools.SHARE_TOOL_SPEC",
        "_web_tool()",
    ]
