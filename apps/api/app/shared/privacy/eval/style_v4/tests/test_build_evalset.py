import pytest

from app.shared.privacy.eval.style_v4.build_evalset import assert_no_overlap


def test_assert_no_overlap_fails_on_shared_name():
    rows = [
        {
            "category": "가족대화",
            "text": "김철수가 왔어",
            "spans": [{"kind": "PERSON", "start": 0, "end": 3}],
        }
    ]
    with pytest.raises(SystemExit):
        assert_no_overlap(rows, excluded_names={"김철수"}, template_texts=set())


def test_assert_no_overlap_passes_on_fresh_name():
    rows = [
        {
            "category": "가족대화",
            "text": "최유일이 왔어",
            "spans": [{"kind": "PERSON", "start": 0, "end": 3}],
        }
    ]
    assert_no_overlap(rows, excluded_names={"김철수"}, template_texts=set())  # 예외 없이 통과
