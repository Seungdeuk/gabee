"""이게 뭐게 가비 추천: 그림 검증·프롬프트·생성, 추천 조립. 실제 AI 는 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

import pytest

from app.features.play import draw_rec
from app.shared.config import settings
from app.shared.llm import client as llm

LINE_A = [[10, 10], [200, 10]]
LINE_B = [[10, 20], [200, 20], [100, 100]]
LINE_C = [[0, 0], [255, 255]]
GOOD = {"strokes": [LINE_A, LINE_B, LINE_C]}


class SeqLLM:
    """부를 때마다 미리 정한 출력을 차례로 돌려주는 가짜 LLM."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens, **kw})
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


# ---------- 그림 검증 ----------
def test_validate_strokes_accepts_good_drawing():
    assert draw_rec.validate_strokes([LINE_A, LINE_B, LINE_C]) == [LINE_A, LINE_B, LINE_C]


def test_validate_strokes_rounds_float_coordinates():
    assert draw_rec.validate_strokes([[[0.4, 10.6], [200.5, 10]], LINE_B, LINE_C]) == [
        [[0, 11], [200, 10]],
        LINE_B,
        LINE_C,
    ]


@pytest.mark.parametrize(
    "bad",
    [
        [LINE_A, LINE_B],  # 선이 2개 이하
        [LINE_A] * 13,  # 선이 13개 이상
        [LINE_A, LINE_B, [[5, 5]]],  # 점이 1개인 선
        [LINE_A, LINE_B, [[i, i] for i in range(31)]],  # 점이 31개인 선
        [LINE_A, LINE_B, [[0, 0], [256, 10]]],  # 좌표가 256
        [LINE_A, LINE_B, [[0, 0], [10, -1]]],  # 좌표가 -1
        [LINE_A, LINE_B, [[0, 0], ["a", 10]]],  # 숫자가 아님
        [LINE_A, LINE_B, [[0, 0], [10]]],  # 점이 (x, y) 가 아님
        [LINE_A, LINE_B, "선"],  # 선이 목록이 아님
        "그림",  # 전체가 목록이 아님
        None,
    ],
)
def test_validate_strokes_rejects_bad_drawings(bad):
    assert draw_rec.validate_strokes(bad) is None


# ---------- 프롬프트 ----------
def test_draw_prompt_has_rules():
    p = draw_rec.draw_prompt("케이크")
    assert "케이크" in p
    assert "0~255" in p
    assert "손으로 삐뚤빼뚤" in p
    assert "글자" in p and "숫자" in p  # 글자·숫자를 넣지 말라는 문구
    assert "3~12" in p  # 선 개수


# ---------- 그림 만들기 ----------
def test_draw_word_returns_strokes_and_usage(seq):
    f = seq(GOOD)
    strokes, usage = draw_rec.draw_word("케이크")
    assert strokes == [LINE_A, LINE_B, LINE_C]
    assert (usage.calls, usage.input_tokens, usage.output_tokens, usage.model) == (
        1,
        100,
        50,
        "fake",
    )
    assert f.calls[0]["effort"] == "low"  # 생각을 줄여 부른다
    assert "케이크" in f.calls[0]["prompt"]


def test_draw_word_retries_once(seq):
    bad = {"strokes": [[[10, 10], [300, 10]], LINE_B, LINE_C]}  # 범위 밖 좌표
    f = seq(bad, GOOD)
    strokes, usage = draw_rec.draw_word("케이크")
    assert strokes == [LINE_A, LINE_B, LINE_C]
    assert len(f.calls) == 2
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (2, 200, 100)


def test_draw_word_fails_after_two_bad_outputs(seq):
    f = seq({"strokes": [LINE_A]}, {"strokes": []})
    with pytest.raises(draw_rec.DrawFailed) as info:
        draw_rec.draw_word("케이크")
    assert len(f.calls) == 2
    assert (info.value.calls, info.value.input_tokens, info.value.output_tokens) == (2, 200, 100)
    assert isinstance(info.value, ValueError)  # ai_guard 가 "잘못된 출력"으로 센다
