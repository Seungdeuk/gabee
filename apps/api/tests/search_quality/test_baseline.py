"""검색 품질 기준선·회귀 시험. 합성 월드에서 실제 `search_service.search` 결과를 지표와 미검출 원인으로 바꾼다(가짜 모델·외부 호출 없음).

기대 원인(`expected_cause`)은 결과를 보기 전에 사례에 고정했다. 기존 구현(글자 일치 AND, 최신순, 가족 전체방만)에 따른 예상 동작인지를 여기서 따로 판정한다.
알려진 한계(동의어·카드·맥락)는 통과로 바꾸지 않고 품질 지표에서 실제 미검출로 센다."""

import json

import pytest
from sqlalchemy import select

from app.features.family_chat import agent
from app.features.family_chat.models import Message
from app.shared.db import SessionLocal
from evals.search_quality import data, runner
from evals.search_quality.world import World


def test_every_case_follows_its_declared_cause_and_no_scope_violation_occurs(report):
    assert report["model_calls"] == 0
    assert report["expectation_mismatches"] == []
    assert report["security_violations"] == 0


def test_baseline_metrics_are_reproducible_numbers(report):
    ideal = report["query_sets"]["ideal"]
    assert ideal["all"]["cases"] == 18 and ideal["excluding_known_limitations"]["cases"] == 14
    # 전체 지표와 알려진 한계를 뺀 하위집단 지표는 따로 낸다(하위집단이 전체를 대체하지 않는다)
    assert ideal["all"]["hit"] == pytest.approx(13 / 18)
    assert ideal["excluding_known_limitations"]["hit"] == pytest.approx(13 / 14)
    assert ideal["all"]["mrr"] < ideal["excluding_known_limitations"]["mrr"]
    assert ideal["miss_causes"] == {
        "content_not_indexed": 1,
        "keyword_limitation": 4,
        "result_limit": 1,
    }
    assert ideal["hit_at_20_diagnostic"] == pytest.approx(
        14 / 18
    )  # 최대 limit 20 이면 q11 이 잡힌다(진단)
    assert ideal["no_answer"] == {"cases": 6, "correct_empty": 6, "nonempty": 0, "violations": 0}
    assert report["query_sets"]["no_history_diagnostic"]["miss_causes"] == {"context_needed": 1}
    assert report["ordering"].startswith("최신순")


def test_precision_uses_a_fixed_denominator_of_10_and_reports_returned_precision_separately(report):
    ideal = report["query_sets"]["ideal"]["all"]
    assert ideal["precision_at_k"] < ideal["precision_returned"]
    q01 = next(r for r in report["cases"] if r["case"] == "q01" and r["query_set"] == "ideal")
    assert (
        q01["retrieved"] == ["m02", "m01"] and q01["first_gold_rank"] == 2
    )  # 최신순이라 정답이 두 번째다
    assert q01["precision_at_k"] == pytest.approx(0.1) and q01[
        "precision_returned"
    ] == pytest.approx(0.5)
    assert q01["context_hits"] == 1  # 맥락 글은 정답으로 세지 않는다


def test_recency_order_pushes_the_oldest_gold_out_of_the_top_10_but_a_wider_limit_finds_it(report):
    q11 = next(r for r in report["cases"] if r["case"] == "q11" and r["query_set"] == "ideal")
    assert "m18" not in q11["retrieved"] and q11["cause"] == "result_limit"
    assert "m18" in q11["diagnostic"]["retrieved_at_20"]  # 도구 최대 limit(20)에서는 나온다
    assert q11["diagnostic"]["deep_count"] == 13


def test_synonyms_and_cards_and_missing_context_are_counted_as_real_misses(report):
    by = {(r["case"], r["query_set"]): r for r in report["cases"]}
    for cid in ("q07", "q08", "q09"):
        row = by[(cid, "ideal")]
        assert (
            row["hit"] == 0.0 and row["cause"] == "keyword_limitation" and row["known_limitation"]
        )
    q24 = by[("q24", "ideal")]
    assert q24["hit"] == 0.0 and q24["cause"] == "content_not_indexed"
    assert (
        by[("q23", "ideal")]["hit"] == 1.0
        and by[("q23", "no_history")]["cause"] == "context_needed"
    )


def test_naive_sentence_words_fail_by_query_selection_not_by_the_search_engine(report):
    naive = report["query_sets"]["naive"]
    assert naive["miss_causes"]["query_selection"] == 15
    assert naive["all"]["hit"] < report["query_sets"]["ideal"]["all"]["hit"]


def test_the_agent_scope_hides_other_rooms_even_though_the_ui_search_shows_a_member_1to1(report):
    probe = {p["case"]: p["ui_search_returns"] for p in report["ui_scope_probe"]}
    assert probe["q21"] == ["d01"]  # 내가 속한 1:1 은 화면 검색에 나온다
    assert (
        probe["q22"] == [] and probe["q20"] == [] and probe["q19"] == []
    )  # 구성원이 아닌 방·다른 가족·삭제글은 안 나온다
    for cid in ("q19", "q20", "q21", "q22"):
        rows = [r for r in report["cases"] if r["case"] == cid]
        assert all(
            r["retrieved"] == [] and r["violations"] == [] for r in rows
        )  # 에이전트 범위는 모두 비어 있다


def test_a_leak_into_a_private_room_would_be_counted_as_a_violation(built, monkeypatch):
    """검사에 이빨이 있는지: 에이전트 검색이 방 범위를 풀면(화면 검색처럼) 1:1 글이 나오고 위반으로 센다."""

    def leaky(self, words, limit=runner.DEFAULT_LIMIT):
        return self.ui_ids(words)

    monkeypatch.setattr(runner.Searcher, "agent_ids", leaky)
    out = runner.run(built, run_id="leak")
    assert out["security_violations"] >= 1
    assert any("d01" in r["violations"] for r in out["cases"])


def test_the_deleted_bait_is_really_searchable_in_the_db_and_the_api_deleted_text_is_gone(built):
    with SessionLocal() as db:
        flagged = db.get(Message, built.ids["m35"])
        api_deleted = db.get(Message, built.ids["m34"])
        assert (
            flagged.deleted_at is not None and "광교" in flagged.text
        )  # 삭제 필터가 없으면 걸린다
        assert api_deleted.deleted_at is not None and api_deleted.text == ""
        hits = db.scalars(select(Message.id).where(Message.text.ilike("%광교%"))).all()
        assert hits == [built.ids["m35"]]


def test_message_ids_follow_the_declared_time_order_and_dates_are_kst(built):
    order = [built.ids[m.key] for m in data.ordered()]
    assert order == sorted(order)
    with SessionLocal() as db:
        row = db.get(Message, built.ids["m01"])
        assert agent._local_time(row.created_at.isoformat()) == "2026-09-28 09:10"


def test_tool_output_matches_the_service_the_runner_calls(built):
    """운영 Tool 의 응답과 실행기가 쓰는 호출이 같은 결과를 내는지(개수·순서·내 글 표시·시각·has_more)."""
    from app.features.family_chat import ai_repository
    from app.features.family_group.models import User
    from app.shared.privacy import ASSISTANT, new_session

    with SessionLocal() as db:
        user = db.get(User, built.user_ids[data.REQUESTER])
        search = runner.Searcher(db, user, built)
        members = ai_repository.member_names(db, built.group_id)
        with new_session(ASSISTANT, members) as session:
            tool = next(
                t
                for t in agent.build_tools(db, built.group_id, user, session)
                if t.name == "search_messages"
            )
            for words in (
                ["치과"],
                ["캠핑", "준비물"],
                ["대청소"],
                ["집들이"],
                ["가족", "모임"],
                ["성적표"],
            ):
                got = tool.run({"query": " ".join(words), "limit": 10})
                ids = search.agent_ids(words)
                assert len(got["messages"]) == len(ids)
                rows = db.scalars(select(Message).where(Message.id.in_(ids))).all()
                by_id = {m.id: m for m in rows}
                assert [m["sent_at"] for m in got["messages"]] == [
                    agent._local_time(by_id[i].created_at.isoformat()) for i in ids
                ]
                assert [m["from_me"] for m in got["messages"]] == [
                    by_id[i].user_id == user.id for i in ids
                ]
                assert got["has_more"] == (len(search.deep_ids(words)) > 10)


def test_the_report_is_json_serializable_and_records_hashes_and_limits(report):
    text = json.dumps(report, ensure_ascii=False)
    assert report["limits"] == {"default": 10, "max": 20, "deep_diagnostic_only": 200}
    assert (
        len(report["dataset"]["cases_sha256"]) == 64
        and len(report["dataset"]["world_sha256"]) == 64
    )
    assert report["git_sha"] and "model_calls" in text


def test_a_world_with_missing_keys_is_refused():
    with pytest.raises(Exception, match="월드의 메시지 키"):
        runner.run(World())
