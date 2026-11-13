"""단계 상한(step_limit) 계측이 실제 실행 경로(러너 -> 앱 -> 훅 -> 관찰)에서도 분리돼 나오는지(L0, 가짜 모델). 계측 코드는 고치지 않는다(#378)."""

from evals.agent_eval.fake_model import call, say
from tests.agent_eval.runner_support import new_case, run


def test_a_main_loop_that_hits_the_step_limit_is_observed_as_limit_and_forced_final():
    case = new_case("n-limit", expect={"outcome": {"can_answer": True}})
    # ask_* 는 직통 응답이라 메인이 다시 부르지 않는다. 문서 검색 도구로 메인 4단계를 채운다: 도구 3번 뒤 마지막 호출은 상한 때문에 도구 없이 최종 답
    searches = [call("search_knowledge", {"query": "보증서"}) for _ in range(3)]
    script = {"main": [*searches, say("찾아봤어요")]}
    report = run([case], scripts={"n-limit": script})
    (rec,) = report.records
    assert rec.status == "judged"
    obs = report.observations[("n-limit", 0)]
    assert obs.step_limit_reached is True and obs.forced_final is True
    assert rec.passed  # 상한에 닿은 것만으로 실패시키지 않는다


def test_a_normal_run_reports_neither_limit_nor_forced_final():
    from tests.agent_eval.runner_support import ask_billing_script

    case = new_case("n-ok", expect={"outcome": {"can_answer": True}})
    report = run([case], scripts={"n-ok": ask_billing_script()})
    obs = report.observations[("n-ok", 0)]
    assert obs.step_limit_reached is False and obs.forced_final is False
