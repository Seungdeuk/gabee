"""시드 초안 스크립트: 후보마다 초안, 쓸 수 있는 것만 seed.json, 확인용 표·페이지(가짜 AI, 네트워크 없음)."""

import io
import json

from PIL import Image

from app.features.play.photo_rec_ai import ContentFailed, ContentResult
from app.shared.llm import client as llm
from scripts import draft_photo_seed as dps


def _write_candidates(folder, n=4):
    (folder / "img").mkdir()
    cands = []
    for i in range(1, n + 1):
        out = io.BytesIO()
        Image.new("RGB", (64, 48), (i * 40, 90, 120)).save(out, format="JPEG")
        (folder / "img" / f"{i:03d}.jpg").write_bytes(out.getvalue())
        cands.append(
            {
                "no": i,
                "pixabay_id": 1000 + i,
                "category": "food",
                "tags": "apple, <b>fruit</b>",
                "user": "kim",
                "page_url": f"https://pixabay.com/photos/x-{i}/",
                "license": "Pixabay Content License",
                "file": f"img/{i:03d}.jpg",
            }
        )
    (folder / "candidates.json").write_text(json.dumps(cands), encoding="utf-8")


def _result(usable=True):
    return ContentResult(
        usable=usable,
        question="무슨 과일일까요?" if usable else "",
        options=["사과", "배", "감"] if usable else [],
        answer_index=0,
        box_x=0.4,
        box_y=0.6,
        input_tokens=100,
        output_tokens=50,
        model="m",
    )


def test_run_writes_seed_review_and_html(tmp_path):
    _write_candidates(tmp_path)

    def ask(jpeg):
        ask.n += 1
        if ask.n == 2:
            return _result(usable=False)
        if ask.n == 3:
            raise ContentFailed("x", 2, 10, 5)
        if ask.n == 4:
            raise llm.LLMUnavailable("no key")
        return _result()

    ask.n = 0
    drafts = dps.run(tmp_path, workers=1, ask=ask)
    assert [d["status"] for d in drafts] == ["ok", "unusable", "failed", "failed"]
    assert drafts[2]["tokens"] == 15
    seed = json.loads((tmp_path / "seed.json").read_text(encoding="utf-8"))
    assert [s["key"] for s in seed] == ["001"]
    assert seed[0] == {
        "key": "001",
        "image": "img/001.jpg",
        "kind": 3,
        "question": "무슨 과일일까요?",
        "options": ["사과", "배", "감"],
        "answer_index": 0,
        "box_x": 0.4,
        "box_y": 0.6,
        "zoom": 8,
    }
    md = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "✔사과 / 배 / 감" in md and "제외 추천" in md and "AI 실패" in md
    page = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert "&lt;b&gt;fruit" in page and "<b>fruit</b>" not in page  # 태그는 이스케이프
    assert 'class="box"' in page and 'src="img/001.jpg"' in page


def test_run_with_prepared_answers_validates_like_the_server(tmp_path):
    _write_candidates(tmp_path, n=4)
    answers = {
        "001": {
            "usable": True,
            "question": "무슨 과일일까요?",
            "options": ["사과", "배"],
            "answer_index": 1,
            "box_x": 0.5,
            "box_y": 0.5,
        },
        "002": {"usable": False},  # 쓰지 말라는 답
        "003": {  # 규칙 위반: 질문 21자
            "usable": True,
            "question": "가" * 21,
            "options": ["a", "b"],
            "answer_index": 0,
            "box_x": 0.5,
            "box_y": 0.5,
        },
        # 004 는 항목 없음
    }
    drafts = dps.run(tmp_path, workers=1, answers=answers)
    assert [d["status"] for d in drafts] == ["ok", "unusable", "failed", "failed"]
    assert [s["key"] for s in json.loads((tmp_path / "seed.json").read_text(encoding="utf-8"))] == [
        "001"
    ]


def test_box_is_clamped_inside_photo(tmp_path):
    drafts = [
        {
            "no": 1,
            "category": "food",
            "file": "img/001.jpg",
            "status": "ok",
            "question": "q",
            "options": ["a", "b"],
            "answer_index": 1,
            "box_x": 1.0,
            "box_y": 0.0,
        }
    ]
    page = dps.review_html(drafts)
    assert "left:87.5%" in page and "top:0.0%" in page  # 8배라 상자 폭 12.5%, 사진 밖으로 안 나감
