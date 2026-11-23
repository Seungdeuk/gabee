"""같은 호칭의 가족이 여럿일 때 저장된 이름으로 후보를 보여 주며 묻는 문구."""

from app.features.schedule.agent.members import Member, ask_text, same_call

ME = Member("me", "나", "", "")
A = Member("a", "김철수", "삼촌(아빠 동생)", "uncle")
B = Member("b", "이영호", "삼촌(엄마 오빠)", "uncle")
MOM = Member("m", "박영희", "엄마", "mom")
FALLBACK = "누구인지 알려 주세요"


def test_asks_with_the_saved_names():
    text = ask_text([ME, A, B, MOM], "치과 삼촌한테 공유해줘", "me", FALLBACK)
    assert (
        "삼촌(아빠 동생), 삼촌(엄마 오빠)" in text
        and "박영희" not in text
        and text.count("엄마") == 1
    )


def test_same_saved_name_is_told_apart_by_real_name():
    x, y = Member("x", "김철수", "삼촌", ""), Member("y", "이영호", "삼촌", "")
    text = ask_text([ME, x, y], "삼촌에게 공유해줘", "me", FALLBACK)
    assert "삼촌(김철수), 삼촌(이영호)" in text


def test_single_match_or_no_match_uses_fallback():
    assert ask_text([ME, A, MOM], "삼촌한테 공유해줘", "me", FALLBACK) == FALLBACK
    assert ask_text([ME, A, B], "내일 치과 등록해줘", "me", FALLBACK) == FALLBACK
    assert same_call([ME, A, B], "엄마한테 공유해줘", "me") == []
