"""검색 품질 시험 공용: 고정 시계 안에서 합성 월드를 만들고 보고서를 돌린다(가짜 모델·외부 호출 없음)."""

import pytest

from evals.agent_eval.clock import frozen_clock
from evals.search_quality import runner, world


@pytest.fixture
def clock():
    with frozen_clock():
        yield


@pytest.fixture
def built(client, clock):
    return world.build(client)


@pytest.fixture
def report(built):
    return runner.run(built, run_id="test")
