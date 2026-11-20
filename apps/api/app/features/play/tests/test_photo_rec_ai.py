"""탐정단 사진 추천의 내용 질문: 검증·프롬프트·재시도·한도. 실제 AI 는 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

import pytest

from app.features.play import photo_rec_ai
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.llm import client as llm

GOOD = {
    "usable": True,
    "question": "식탁 위에 무엇이 있을까요?",
    "options": ["케이크", "라면", "피자"],
    "answer_index": 0,
    "box_x": 0.4,
    "box_y": 0.6,
}
JPEG = b"\xff\xd8fake-jpeg"


class SeqLLM:
    """부를 때마다 미리 정한 출력을 차례로 돌려주는 가짜 LLM."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append(
            {"prompt": prompt, "schema": schema, "system": system, "max_tokens": max_tokens, **kw}
        )
        return llm.JsonResult(
            data=self.outputs.pop(0), input_tokens=100, output_tokens=50, model="fake"
        )


@pytest.fixture
def seq(monkeypatch):
    def make(*outputs):
        f = SeqLLM(*outputs)
        monkeypatch.setattr(llm, "complete_json", f)
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        return f

    return make


# ---------- 검증 ----------
def test_validate_content_accepts_good():
    assert photo_rec_ai.validate_content(GOOD) == GOOD


def test_validate_content_unusable_passes_without_question():
    got = photo_rec_ai.validate_content({"usable": False})
    assert got is not None and got["usable"] is False


@pytest.mark.parametrize(
    "patch",
    [
        {"question": "가" * 21},  # 질문 21자
        {"question": ""},  # 질문 없음
        {"options": ["케이크"], "answer_index": 0},  # 보기 1개
        {"options": ["a", "b", "c", "d", "e"]},  # 보기 5개
        {"options": ["케이크", "케이크", "피자"]},  # 같은 보기
        {"options": ["케이크", "", "피자"]},  # 빈 보기
        {"options": ["케이크", "나" * 21, "피자"]},  # 보기 21자
        {"answer_index": 3},  # 정답 위치가 범위 밖
        {"answer_index": -1},
        {"answer_index": True},  # 불리언은 숫자가 아님
        {"box_x": 1.2},
        {"box_y": -0.1},
        {"box_x": "0.5"},
        {"usable": "yes"},
    ],
)
def test_validate_content_rules(patch):
    assert photo_rec_ai.validate_content({**GOOD, **patch}) is None


@pytest.mark.parametrize("bad", [None, "질문", [GOOD], 3])
def test_validate_content_rejects_non_dict(bad):
    assert photo_rec_ai.validate_content(bad) is None


# ---------- 호출·재시도 ----------
def test_content_question_returns_result_and_sends_one_image(seq):
    f = seq(GOOD)
    result = photo_rec_ai.content_question(JPEG)
    assert result.usable is True
    assert result.question == GOOD["question"]
    assert result.options == GOOD["options"]
    assert result.answer_index == 0
    assert (result.box_x, result.box_y) == (0.4, 0.6)
    assert (result.input_tokens, result.output_tokens, result.model) == (100, 50, "fake")
    assert len(f.calls) == 1
    assert f.calls[0]["images"] == [JPEG]
    assert f.calls[0]["max_tokens"] == photo_rec_ai.MAX_TOKENS
    assert f.calls[0]["effort"] == photo_rec_ai.EFFORT
    assert f.calls[0]["timeout"] == photo_rec_ai.TIMEOUT


def test_content_question_unusable_photo(seq):
    seq({"usable": False})
    result = photo_rec_ai.content_question(JPEG)
    assert result.usable is False


def test_content_question_retries_once(seq):
    f = seq({**GOOD, "box_x": 2}, GOOD)
    result = photo_rec_ai.content_question(JPEG)
    assert result.question == GOOD["question"]
    assert len(f.calls) == 2
    # 다시 시도한 호출의 토큰까지 합쳐서 돌려준다
    assert (result.input_tokens, result.output_tokens) == (200, 100)


def test_content_question_fails_after_two_bad_answers(seq):
    f = seq({**GOOD, "box_x": 2}, {**GOOD, "options": ["a"]})
    with pytest.raises(photo_rec_ai.ContentFailed) as err:
        photo_rec_ai.content_question(JPEG)
    assert len(f.calls) == 2
    assert err.value.calls == 2
    assert (err.value.input_tokens, err.value.output_tokens) == (200, 100)


def test_content_question_propagates_llm_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise llm.LLMUnavailable("x")

    monkeypatch.setattr(llm, "complete_json", boom)
    with pytest.raises(llm.LLMUnavailable):
        photo_rec_ai.content_question(JPEG)


# ---------- 프롬프트 ----------
def test_prompt_rules(seq):
    f = seq(GOOD)
    photo_rec_ai.content_question(JPEG)
    call = f.calls[0]
    text = call["system"] + call["prompt"]
    assert "사람 얼굴이 크게" in text and "글자·서류" in text and "usable=false" in text
    assert "20자" in text
    assert "2~4개" in text
    assert "box_x" in text and "box_y" in text
    assert "가족" not in call["prompt"]  # 가족 이름·일정 같은 정보는 요청에 없다
    assert len(call["images"]) == 1  # 사진 한 장만
    assert call["schema"] is photo_rec_ai.SCHEMA
    assert call["schema"]["additionalProperties"] is False


# ---------- 한도 ----------
def test_limits_registered():
    limits, features = ai_guard._BUCKETS[photo_rec_ai.FEATURE]
    assert photo_rec_ai.FEATURE == "play_photo_rec"
    assert features == (photo_rec_ai.FEATURE,)
    assert limits.cooldown_seconds == settings.ai_play_photo_rec_cooldown_seconds == 5
    assert limits.per_user_per_day == settings.ai_play_photo_rec_max_calls_per_user_per_day == 3
    assert limits.per_group_per_day == settings.ai_play_photo_rec_max_calls_per_group_per_day == 5
