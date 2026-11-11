"""합성 데이터 안전성 시험(L0). 탐지 결과 0건만으로 안전하다고 보지 않고, 모든 값이 코드에 선언된 허구의 값인지 함께 본다."""

import pytest

from evals.agent_eval.clock import frozen_clock
from evals.agent_eval.seeds import build_world, data
from evals.agent_eval.seeds import inspect_world as look


@pytest.fixture
def clock():
    with frozen_clock():
        yield


def test_every_stored_text_is_one_of_the_values_declared_in_code(client, clock):
    """DB 에 저장되어 API 로 읽히는 모든 글(메시지·일정 제목·장소·할 일·부탁·습관)이 data.py 의 선언 안에 있다."""
    world = build_world(client)
    stored = look.stored_texts(client, world)
    assert stored, "읽힌 글이 없다"
    assert stored <= data.all_texts(), sorted(stored - data.all_texts())


def test_user_names_are_the_declared_fictional_names(client, clock):
    world = build_world(client)
    for name, member in world.members.items():
        me = look._get(client, "/family-group/me", member.headers).json()
        assert me["name"] == name and name in data.FICTIONAL_NAMES


def test_detections_in_the_declared_texts_are_only_the_declared_fictional_values(client, clock):
    """허구의 이름·번호는 탐지될 수 있다. 선언에 없는 값이 탐지되면 실제처럼 보이는 값이 섞인 것이다."""
    assert look.unexpected_detections(sorted(data.all_texts())) == []


def test_the_declared_sensitive_markers_are_really_detected(client, clock):
    """탐지기가 허구의 번호를 못 찾는다면 위 시험이 아무것도 보지 못한 것이므로, 표식이 실제로 탐지되는지 본다."""
    from app.shared.privacy.detectors import detect

    found = set()
    for text in data.all_texts():
        found |= {
            text[s.start : s.end] for s in detect(text, known_names=tuple(data.FICTIONAL_NAMES))
        }
    assert {data.PHONE_AB, data.ACCOUNT_AC} <= found  # 번호는 전화번호, 계좌는 계좌로 탐지된다
    assert found & data.FICTIONAL_NAMES  # 이름 사전(known_names)으로 허구의 이름도 탐지된다


def test_a_value_that_looks_real_but_is_not_declared_is_reported():
    """검사가 실제로 잡는지: 선언에 없는 전화번호·주민번호 모양은 문제로 나온다."""
    texts = ["내 번호는 010-1234-5678 이야", "오늘 점심은 김밥", f"비밀 {data.PHONE_AB}"]
    reported = look.unexpected_detections(texts)
    assert ("내 번호는 010-1234-5678 이야", "010-1234-5678") in reported
    assert all(text != f"비밀 {data.PHONE_AB}" for text, _ in reported)  # 선언한 번호는 통과


def test_declared_fictional_phone_numbers_use_a_reserved_non_working_pattern():
    """허구의 번호는 실제로 쓰일 수 없는 모양이다(0000 국번)."""
    assert data.PHONE_AB.startswith("010-0000-") and set(data.ACCOUNT_AC.replace("-", "")) == {"0"}


def test_no_declared_text_contains_an_email_url_or_long_digit_run_outside_the_markers():
    """선언 값에 이메일·주소·긴 숫자열이 없다(허구의 표식 번호만 예외)."""
    import re

    suspicious = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://|www\.|\d{7,}")
    for text in data.all_texts():
        cleaned = text.replace(data.PHONE_AB, "").replace(data.ACCOUNT_AC, "")
        assert not suspicious.search(cleaned), text


def test_the_rule_based_detector_cannot_find_undeclared_real_looking_names_so_it_is_only_a_secondary_signal():
    """사전에 없는 이름은 규칙 기반 탐지기(NER 꺼짐)가 못 찾는다. 그래서 합성 보장은 선언 집합 대조(위 첫 시험)가 맡는다."""
    assert look.unexpected_detections(["김철수 아저씨가 왔어", "홍길동에게 전화해"]) == []


def test_places_memos_units_and_group_names_are_checked_against_the_declaration_too(client, clock):
    """제목뿐 아니라 일정 장소·메모, 부탁 장소·메모, 습관 단위, 그룹 이름까지 선언 안에 있어야 한다."""
    world = build_world(client)
    stored = look.stored_texts(client, world)
    assert {
        "웃음치과",
        "선물은 미리 준비",
        "주말 전에",
        "잔",
        data.FAMILY_NAME,
        data.OTHER_FAMILY_NAME,
    } <= stored
    assert stored <= data.all_texts()
