"""이미 토큰을 준 사람 이름만 같은 토큰으로 바꾸는 기능(도구 결과·오류 글용). 새 토큰을 만들거나 다른 개인정보를 건드리지 않는다."""

from app.shared.privacy import ASSISTANT, new_session
from app.shared.privacy.pseudonymizer import Pseudonymizer
from app.shared.privacy.types import Kind


def test_only_names_already_mapped_get_the_same_token():
    pz = Pseudonymizer()
    token = pz.token_for(Kind.PERSON, "이수진")
    before = pz.size
    out = pz.tokenize_mapped_names("이수진이 전화했고 김민수도 왔어")
    assert out == f"{token}이 전화했고 김민수도 왔어"  # 안 가린 이름(김민수)은 그대로
    assert pz.size == before  # 새 토큰을 만들지 않는다


def test_other_personal_data_is_left_alone():
    pz = Pseudonymizer()
    token = pz.token_for(Kind.PERSON, "이수진")
    text = "이수진 010-1234-5678 서울시 강남구 테헤란로 152"
    assert pz.tokenize_mapped_names(text) == f"{token} 010-1234-5678 서울시 강남구 테헤란로 152"


def test_display_name_aliases_share_the_representative_token():
    pz = Pseudonymizer()
    pz.set_aliases({"수진이": "이수진"})
    token = pz.token_for(Kind.PERSON, "이수진")
    assert pz.tokenize_mapped_names("수진이 왔어") == f"{token} 왔어"
    assert pz.tokenize_mapped_names("이수진 왔어") == f"{token} 왔어"


def test_token_shaped_text_is_neutralized_only_when_a_name_is_mapped():
    empty = Pseudonymizer()
    assert (
        empty.tokenize_mapped_names("메모 [PERSON_1]") == "메모 [PERSON_1]"
    )  # 대응표에 사람이 없으면 섞일 일이 없다
    pz = Pseudonymizer()
    token = pz.token_for(Kind.PERSON, "이수진")
    assert token == "[PERSON_1]"
    assert pz.tokenize_mapped_names("메모 [PERSON_1] 이수진") == "메모 ‹PERSON_1› [PERSON_1]"


def test_closed_pseudonymizer_changes_nothing():
    pz = Pseudonymizer()
    pz.token_for(Kind.PERSON, "이수진")
    pz.clear()
    assert pz.known_person_names() == ()
    assert pz.tokenize_mapped_names("이수진") == "이수진"


def test_session_json_only_touches_string_values():
    with new_session(ASSISTANT, [("이수진", "수진이"), ("박지민",)]) as session:
        token = session.prepare_text("수진이 왔어").split()[0]
        data = {
            "이수진": 5,
            "rows": [{"name": "이수진", "paid": 9000, "who": "박지민", "ok": True}],
        }
        out = session.tokenize_mapped_names_json(data)
        assert out["이수진"] == 5  # 키는 그대로
        assert out["rows"] == [{"name": token, "paid": 9000, "who": "박지민", "ok": True}]


def test_retokenize_values_hides_exactly_the_restored_values_even_when_glued():
    pz = Pseudonymizer()
    name = pz.token_for(Kind.PERSON, "이수진")
    short = pz.token_for(Kind.PERSON, "수진")
    addr = pz.token_for(Kind.ADDRESS, "서울시 강남구 테헤란로 152")
    before = pz.size
    text = "이수진택시 수진님 서울시 강남구 테헤란로 152 근처"
    out = pz.retokenize_values(text, [name, short, addr])
    assert (
        out == f"{name}택시 {short}님 {addr} 근처"
    )  # 긴 값부터 바꿔 '이수진' 이 '수진' 으로 잘리지 않는다
    assert pz.size == before  # 새 토큰을 만들지 않는다


def test_retokenize_values_ignores_unknown_tokens_and_values_not_requested():
    pz = Pseudonymizer()
    token = pz.token_for(Kind.PERSON, "이수진")
    pz.token_for(Kind.PERSON, "박지민")
    assert pz.retokenize_values("이수진 박지민", ["[PERSON_9]"]) == "이수진 박지민"
    assert (
        pz.retokenize_values("이수진 박지민", [token]) == f"{token} 박지민"
    )  # 복원하지 않은 값은 그대로
    pz.clear()
    assert pz.retokenize_values("이수진", [token]) == "이수진"


def test_tool_argument_restore_covers_person_and_address_but_never_phone():
    with new_session(ASSISTANT, [("이수진",)]) as session:
        masked = session.prepare_text("이수진 010-1234-5678 서울시 강남구 테헤란로 152")
        tokens = masked.split()
        person, phone = tokens[0], tokens[1]
        assert person.startswith("[PERSON_") and phone.startswith("[PHONE_")
        restored = session.restore_json({"name": person, "phone": phone}).value
        assert restored["name"] == "이수진"  # 이름은 도구 실행용으로 복원
        assert restored["phone"] == "(연락처)" and "1234" not in str(
            restored
        )  # 전화번호는 복원하지 않는다
