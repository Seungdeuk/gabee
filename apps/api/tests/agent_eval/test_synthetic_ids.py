"""합성 id 가 전화번호로 오인되는 문제(preflight 4번 간헐 실패)의 회귀 시험(L0). 가짜 모델·외부 호출은 없다.

원인: 앱의 id(`uuid4().hex[:12]`)가 `0` + 숫자 9개 이상으로 시작하면 전화번호 규칙이 PHONE 으로 탐지한다.
고침: 평가 프로세스 안에서만 id 의 '숫자만 이어지는 구간'을 제한한다(`evals/agent_eval/ids.py`). 운영 코드와 탐지 규칙은 그대로다.
"""

import re
import uuid

import pytest

from app.shared.privacy.ner import detect_with_ner
from evals.agent_eval import ids
from evals.agent_eval.clock import frozen_clock
from evals.agent_eval.seeds import build_world

PHONE_LIKE_IDS = ("0212345678ab", "01012345678a", "0312345678ab")
SHIPPED_PHONES = ("010-1234-5678", "02-123-4567", "01012345678", "031 234 5678", "+82 10-1234-5678")


def _kinds(text: str) -> set[str]:
    return {str(s.kind.value) for s in detect_with_ner(text)}


def _in_json(value: str) -> str:
    return f'{{"id": "{value}", "title": "치과"}}'


def test_the_reported_false_positive_still_reproduces_with_the_unchanged_detector():
    """탐지 규칙을 느슨하게 하지 않았다는 근거: 같은 id 모양은 여전히 PHONE 이다(고친 것은 id 쪽이다)."""
    for value in PHONE_LIKE_IDS:
        assert "PHONE" in _kinds(_in_json(value)), value


def test_real_phone_numbers_are_still_detected():
    for number in SHIPPED_PHONES:
        assert "PHONE" in _kinds(f"연락처 {number} 입니다"), number


def test_first_char_not_zero_would_pass_today_but_the_digit_run_limit_does_not_depend_on_it():
    """첫 글자만 0 이 아니게 해도 지금 규칙에서는 PHONE 이 안 나온다. 그래도 규칙이 바뀌면 깨지는 가정이라 숫자 구간 길이를 직접 제한한다."""
    for value in ("314159265358", "31415926535a", "912345678901"):
        assert "PHONE" not in _kinds(_in_json(value)), value
    assert not ids.is_safe("314159265358")  # 그래도 긴 숫자 구간은 걸러낸다


def test_is_safe_rejects_long_digit_runs_and_accepts_short_ones():
    assert not ids.is_safe("0212345678ab")
    assert not ids.is_safe("a1234567b")
    assert ids.is_safe("123456ab123456")
    assert ids.is_safe("abcdef" * 5)


def test_safe_uuid4_is_a_valid_random_uuid4_and_never_phone_like():
    seen = set()
    for _ in range(20000):
        value = ids.safe_uuid4()
        assert isinstance(value, uuid.UUID) and value.version == 4
        assert ids.is_safe(value.hex)
        assert not re.search(rf"\d{{{ids.MAX_DIGIT_RUN + 1},}}", value.hex)
        seen.add(value.hex[:12])
    assert len(seen) == 20000  # 12자리 id 의 유일성이 깨지지 않는다


def test_a_phone_like_draw_is_discarded_and_redrawn(monkeypatch):
    draws = iter([uuid.UUID(hex="0212345678ab" + "a" * 20), uuid.UUID(hex="abcdef" * 5 + "ab")])
    monkeypatch.setattr(ids._real_uuid, "uuid4", lambda: next(draws))
    assert ids.safe_uuid4().hex.startswith("abcdef")


def test_safe_ids_changes_only_app_modules_and_restores_them(client):
    from app.features.family_group import models as group_models

    assert group_models.uuid is uuid
    with ids.safe_ids():
        assert group_models.uuid is not uuid
        assert ids.is_safe(group_models._uid() + "x" * 20)
        assert uuid.uuid4().hex  # 진짜 uuid 모듈(앱 밖)은 그대로다
        assert uuid.uuid4 is not ids.safe_uuid4
        assert group_models.uuid.UUID is uuid.UUID  # 나머지 속성은 진짜 모듈로 전달된다
    assert group_models.uuid is uuid


def test_safe_ids_restores_after_an_error_and_refuses_nesting(client):
    from app.features.family_group import models as group_models

    with pytest.raises(ZeroDivisionError), ids.safe_ids():
        raise ZeroDivisionError
    assert group_models.uuid is uuid
    with ids.safe_ids(), pytest.raises(RuntimeError, match="겹쳐"), ids.safe_ids():
        pass


def test_production_id_code_is_untouched():
    from pathlib import Path

    import app.features.family_group.models as m

    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "uuid.uuid4().hex[:12]" in src  # 운영 id 생성 코드는 그대로다


def test_world_ids_are_safe_unique_and_still_referable(client):
    """합성 월드의 일정·지출·할 일·방 id 가 안전하고, 만든 id 로 다시 읽어 올 수 있다(참조 관계 유지)."""
    with frozen_clock(), ids.safe_ids():
        world = build_world(client)
        collected = [
            *world.events.values(),
            *world.expenses.values(),
            *world.todos.values(),
            *world.requests.values(),
            *world.habits.values(),
            *world.docs.values(),
            *world.rooms.values(),
        ]
        assert collected
        assert len(collected) == len(set(collected))
        for value in collected:
            assert ids.is_safe(value), value
            assert "PHONE" not in _kinds(_in_json(value)), value
        events = client.get("/schedule/events", headers=world.headers("지민"))
        assert events.status_code == 200
        some_event = world.events[("지민", "치과 진료")]
        assert some_event in events.text  # 만든 id 가 조회 결과에 그대로 나온다


def test_two_worlds_get_different_ids_through_the_same_path(client):
    """생성 경로는 같고(둘 다 safe_ids) 값은 매번 새로 뽑힌다 — 사전 점검과 실호출이 같은 규칙을 거친다."""
    from evals.agent_eval import env

    def build() -> list[str]:
        env.reset_case_state(
            __import__("pathlib").Path(
                __import__("app.shared.config", fromlist=["settings"]).settings.data_dir
            )
        )
        with frozen_clock(), ids.safe_ids():
            w = build_world(client)
            return sorted(w.events.values())

    first = build()
    second = build()
    assert all(ids.is_safe(v) for v in first + second)
    assert first != second
