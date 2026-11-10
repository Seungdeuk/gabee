"""대화 분석·답장·주제 추천은 요청한 사람 본인의 입장으로 만든다: 프롬프트에 누가 요청했는지 알리고, 결과는 사용자마다 따로
만든다(같은 대화여도 두 사람의 답장·주제가 다르다). 요약은 친근한 말투로 쓰도록 안내한다."""

# 다른 시험 파일의 fixture(fake·ready)를 가져다 쓴다(pytest 방식이라 F811 은 무시한다)
# ruff: noqa: F811
import re

import pytest

from app.features.family_chat import ai_service

from .test_ai_analysis import AI, analyze, enable, fake, ready, say  # noqa: F401

VIEWER = re.compile(r"요청한 사람[^\n]*")


def _viewer_line(fake):
    found = VIEWER.search(fake.calls[-1]["prompt"])
    assert found, fake.calls[-1]["prompt"]
    return found.group(0)


def test_analysis_tells_the_model_who_asked(client, ready, fake):
    a, b, _ = ready
    analyze(client, a)
    line_a = _viewer_line(fake)
    analyze(client, b)
    line_b = _viewer_line(fake)
    assert line_a != line_b  # 두 사람은 서로 다른 입장으로 요청한다


def test_each_user_gets_their_own_result_not_a_shared_cache(client, ready, fake):
    a, b, _ = ready
    analyze(client, a)
    analyze(client, a)  # 같은 사람은 저장된 결과를 다시 쓴다
    assert len(fake.calls) == 1
    analyze(client, b)  # 다른 사람은 자기 입장으로 새로 만든다
    assert len(fake.calls) == 2


@pytest.mark.parametrize("path", ["replies", "topics"])
def test_standalone_replies_and_topics_are_per_user_too(client, ready, fake, path):
    a, b, _ = ready
    client.post(f"{AI}/{path}", json={}, headers=a)
    first = _viewer_line(fake)
    client.post(f"{AI}/{path}", json={}, headers=b)
    assert _viewer_line(fake) != first
    assert len(fake.calls) == 2


def test_viewer_who_has_not_spoken_is_told_so(client, family, fake):
    a, b, _ = family
    enable(client, a)
    for i in range(3):
        say(client, b, f"혼자 한 이야기 {i}")  # a 는 한 마디도 안 했다
    analyze(client, a)
    assert "말한 적이 없" in _viewer_line(fake)


def test_prompt_asks_for_viewer_side_replies_and_friendly_summary():
    system = ai_service.ANALYSIS_SYSTEM
    assert "요청한 사람" in system and "친근" in system
    assert "요청한 사람" in ai_service.REPLIES_SYSTEM and "요청한 사람" in ai_service.TOPICS_SYSTEM
    assert ai_service.PROMPT_VERSION != "v4"  # 프롬프트가 바뀌면 오래된 캐시를 쓰지 않는다
