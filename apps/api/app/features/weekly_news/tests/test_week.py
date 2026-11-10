"""주 경계·허용 범위·생성 시점 시험. 시간은 모두 인자로 고정한다(KST = UTC+9)."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.features.weekly_news import week as week_mod
from app.features.weekly_news.week import (
    READY_HOUR,
    ready_to_generate,
    validate_week,
    week_end_of,
    week_start_of,
)
from app.shared.config import settings
from app.shared.errors import ApiError

# 2026-11-09 는 월요일이다.
MON = date(2026, 11, 9)
NEXT_MON = date(2026, 11, 16)


@pytest.fixture(autouse=True)
def _kst(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)


def utc(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


# ── week_start_of ─────────────────────────────────────────────


def test_sunday_2330_kst_is_still_that_weeks_monday():
    # 일요일 23:30 KST = UTC 일요일 14:30
    assert week_start_of(utc(2026, 11, 15, 14, 30)) == MON


def test_sunday_235959_kst_is_last_second_of_week():
    assert week_start_of(utc(2026, 11, 15, 14, 59, 59)) == MON


def test_monday_0000_kst_starts_new_week():
    # 월요일 00:00 KST = UTC 일요일 15:00 (UTC 로는 아직 일요일)
    assert week_start_of(utc(2026, 11, 15, 15, 0, 0)) == NEXT_MON


def test_monday_0010_kst_is_new_week():
    assert week_start_of(utc(2026, 11, 15, 15, 10)) == NEXT_MON


def test_utc_monday_morning_is_same_week_as_kst_monday():
    assert week_start_of(utc(2026, 11, 16, 0, 10)) == NEXT_MON


def test_monday_itself_and_midweek():
    assert week_start_of(utc(2026, 11, 9, 0, 0)) == MON  # 월 09:00 KST
    assert week_start_of(utc(2026, 11, 11, 12, 0)) == MON  # 수요일


def test_naive_datetime_is_treated_as_utc():
    assert week_start_of(datetime(2026, 11, 15, 15, 0)) == NEXT_MON
    assert week_start_of(datetime(2026, 11, 15, 14, 59)) == MON


def test_aware_non_utc_input_is_converted():
    kst = timezone(timedelta(hours=9))
    assert week_start_of(datetime(2026, 11, 16, 0, 10, tzinfo=kst)) == NEXT_MON
    assert week_start_of(datetime(2026, 11, 15, 23, 30, tzinfo=kst)) == MON
    # 같은 순간을 다른 시간대로 표현해도 결과가 같다
    pst = timezone(timedelta(hours=-8))
    assert week_start_of(datetime(2026, 11, 15, 7, 10, tzinfo=pst)) == NEXT_MON


def test_offset_setting_changes_boundary(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 0)
    # 오프셋 0 이면 UTC 일요일 15:00 은 아직 그 주
    assert week_start_of(utc(2026, 11, 15, 15, 0)) == MON
    assert week_start_of(utc(2026, 11, 16, 0, 0)) == NEXT_MON


def test_year_boundary():
    # 2026-12-28(월) 주는 2027-01-03(일)까지
    assert week_start_of(utc(2027, 1, 3, 14, 0)) == date(2026, 12, 28)
    assert week_start_of(utc(2027, 1, 3, 15, 0)) == date(2027, 1, 4)


def test_result_is_always_a_monday_date_not_datetime():
    got = week_start_of(utc(2026, 11, 13, 5, 0))
    assert got.weekday() == 0
    assert type(got) is date


# ── week_end_of ───────────────────────────────────────────────


def test_week_end_is_sunday():
    assert week_end_of(MON) == date(2026, 11, 15)
    assert week_end_of(MON).weekday() == 6


# ── validate_week ─────────────────────────────────────────────

NOW = utc(2026, 11, 11, 3, 0)  # 수요일 12:00 KST, 이번 주 = MON


def test_validate_current_week_ok():
    assert validate_week(MON, NOW) is None


def test_validate_not_monday_invalid():
    for offset in range(1, 7):
        with pytest.raises(ApiError) as e:
            validate_week(MON + timedelta(days=offset), NOW)
        assert (e.value.status, e.value.code) == (400, "invalid_week")


def test_validate_not_monday_in_past_invalid():
    with pytest.raises(ApiError) as e:
        validate_week(MON - timedelta(days=8), NOW)
    assert e.value.code == "invalid_week"


def test_validate_future_week_invalid():
    with pytest.raises(ApiError) as e:
        validate_week(NEXT_MON, NOW)
    assert (e.value.status, e.value.code) == (400, "invalid_week")


def test_validate_eight_weeks_ago_ok():
    assert validate_week(MON - timedelta(weeks=8), NOW) is None


def test_validate_nine_weeks_ago_invalid():
    with pytest.raises(ApiError) as e:
        validate_week(MON - timedelta(weeks=9), NOW)
    assert (e.value.status, e.value.code) == (400, "invalid_week")


def test_validate_all_weeks_in_range_ok():
    for n in range(0, 9):
        assert validate_week(MON - timedelta(weeks=n), NOW) is None


def test_validate_uses_kst_week_at_boundary():
    # 월요일 00:10 KST 에는 새 주(NEXT_MON)가 이번 주, 8주 전 기준도 한 주 밀린다
    now = utc(2026, 11, 15, 15, 10)
    assert validate_week(NEXT_MON, now) is None
    assert validate_week(NEXT_MON - timedelta(weeks=8), now) is None
    with pytest.raises(ApiError):
        validate_week(NEXT_MON - timedelta(weeks=9), now)
    # 직전 시각(일요일 23:59 KST)에는 NEXT_MON 이 아직 미래 주
    with pytest.raises(ApiError):
        validate_week(NEXT_MON, utc(2026, 11, 15, 14, 59))


def test_validate_datetime_or_non_date_is_400_not_typeerror():
    for bad in (datetime(2026, 11, 9), datetime(2026, 11, 9, tzinfo=UTC), "2026-11-09", None):
        with pytest.raises(ApiError) as e:
            validate_week(bad, NOW)
        assert (e.value.status, e.value.code) == (400, "invalid_week")


def test_ready_to_generate_datetime_is_false_not_typeerror():
    assert ready_to_generate(datetime(2026, 11, 2), NOW) is False


def test_validate_message_has_no_input_echo():
    with pytest.raises(ApiError) as e:
        validate_week(NEXT_MON, NOW)
    assert "2026" not in e.value.message


# ── ready_to_generate ─────────────────────────────────────────


def test_ready_hour_constant():
    assert READY_HOUR == 18


def test_this_week_not_ready_before_sunday_1800():
    # 일요일 17:59:59 KST = UTC 08:59:59
    assert ready_to_generate(MON, utc(2026, 11, 15, 8, 59, 59)) is False


def test_this_week_ready_at_sunday_1800():
    assert ready_to_generate(MON, utc(2026, 11, 15, 9, 0, 0)) is True


def test_this_week_ready_late_sunday():
    assert ready_to_generate(MON, utc(2026, 11, 15, 14, 59, 59)) is True


def test_this_week_not_ready_midweek_and_monday():
    assert ready_to_generate(MON, NOW) is False
    assert ready_to_generate(MON, utc(2026, 11, 8, 15, 1)) is False  # 월 00:01 KST
    assert ready_to_generate(MON, utc(2026, 11, 14, 14, 0)) is False  # 토 23:00 KST


def test_utc_clock_is_not_used_for_sunday_threshold():
    # UTC 일요일 18:00(= KST 월요일 03:00)은 이미 다음 주라 이 주(MON)는 지난 주 → 항상 가능
    assert ready_to_generate(MON, utc(2026, 11, 15, 18, 0)) is True
    # 같은 UTC 시각에 새 이번 주(NEXT_MON)는 아직 아니다
    assert ready_to_generate(NEXT_MON, utc(2026, 11, 15, 18, 0)) is False


def test_past_weeks_always_ready():
    for now in (NOW, utc(2026, 11, 15, 15, 10), utc(2026, 11, 9, 0, 0)):
        past = week_start_of(now) - timedelta(weeks=1)
        assert ready_to_generate(past, now) is True


def test_far_past_week_ready():
    assert ready_to_generate(MON - timedelta(weeks=8), NOW) is True


def test_future_week_never_ready():
    assert ready_to_generate(NEXT_MON, NOW) is False
    assert ready_to_generate(NEXT_MON, utc(2026, 11, 15, 14, 59)) is False


def test_non_monday_never_ready():
    assert ready_to_generate(MON + timedelta(days=2), utc(2026, 11, 15, 14, 0)) is False
    assert ready_to_generate(MON - timedelta(days=3), NOW) is False


def test_ready_hour_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(week_mod, "READY_HOUR", 20)
    assert ready_to_generate(MON, utc(2026, 11, 15, 9, 0)) is False  # 18:00 KST
    assert ready_to_generate(MON, utc(2026, 11, 15, 11, 0)) is True  # 20:00 KST


def test_ready_respects_offset_setting(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 0)
    # 오프셋 0: 일요일 18:00 UTC
    assert ready_to_generate(MON, utc(2026, 11, 15, 17, 59)) is False
    assert ready_to_generate(MON, utc(2026, 11, 15, 18, 0)) is True
