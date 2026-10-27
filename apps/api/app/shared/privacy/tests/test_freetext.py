"""자유 글·JSON API(prepare_text / prepare_json / generalize_coordinates) 시험. 같은 탐지기를 쓰므로 탐지 성능은 기존과 같다."""

import copy
import json
import pickle
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.shared.privacy import (
    ANALYSIS,
    ASSISTANT,
    COORDINATE_KEYS,
    REPLY,
    PrivacySession,
    detect,
    generalize_coordinates,
    generalize_number,
    new_session,
    prepare_json,
    prepare_text,
    prepare_transcript,
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - start


# ---------- 자유 글 ----------
def test_free_text_masks_every_kind_but_keeps_sentence():
    text = (
        "김민수 010-1234-5678 로 연락. 이메일 kim.test@example.com\n"
        "주민번호 900101-1234568, 계좌 국민은행 110-123-456789, 카드 4540-1234-5678-9014.\n"
        "서울시 강남구 테헤란로 152 에서 만나요. 비번은 abcd1234"
    )
    out, sess = prepare_text(text, members=["김민수"])
    with sess:
        for secret in (
            "김민수",
            "010-1234-5678",
            "kim.test@example.com",
            "900101-1234568",
            "110-123-456789",
            "4540-1234-5678-9014",
            "테헤란로",
            "abcd1234",
        ):
            assert secret not in out
        assert "연락." in out and "만나요." in out  # 문장 나머지는 그대로
        assert out.count("\n") == 2  # 줄 구조 유지
        assert "[PERSON_1]" in out and "[PHONE_1]" in out and "[EMAIL_1]" in out
        assert "[RRN]" in out and "[SECRET]" in out
        assert sess.blocked_count >= 2  # 고위험은 메시지 통째가 아니라 값만 가렸다
        assert sess.counts_by_kind["PHONE"] == 1


def test_high_risk_replaces_value_not_whole_text():
    out, sess = prepare_text("제 주민번호는 900101-1234568 이고 내일 병원 가요")
    assert out == "제 주민번호는 [RRN] 이고 내일 병원 가요"
    assert sess.blocked_count == 1
    assert "민감정보가 있어 제외된" not in out


def test_low_score_high_risk_is_masked_but_not_counted_as_blocked():
    # 체크섬이 맞지 않는 주민번호(점수 0.6)도 값은 가리지만 blocked_count(0.7 이상)에는 넣지 않는다. high_risk_count 에는 센다
    assert [s.score for s in detect("주민 900101-1234567")] == [0.6]
    out, sess = prepare_text("주민 900101-1234567")
    assert out == "주민 [RRN]"
    assert sess.blocked_count == 0
    assert sess.counts_by_kind == {"RRN": 1}
    assert sess.high_risk_count == 1


def test_card_wins_over_account_when_overlapping():
    out, sess = prepare_text("계좌 4540-1234-5678-9014")
    assert out == "계좌 [CARD]"
    assert sess.high_risk_count == 1


def test_high_risk_count_sums_all_high_risk_kinds():
    out, sess = prepare_text(
        "주민 900101-1234568, 카드 4540-1234-5678-9014, 비번 abcd1234, 010-1111-2222"
    )
    expected = sum(sess.counts_by_kind.get(k, 0) for k in ("RRN", "CARD", "ACCOUNT", "SECRET"))
    assert sess.high_risk_count == expected == 3
    assert sess.blocked_count <= sess.high_risk_count


def test_josa_attached_names_with_member_dictionary():
    out, sess = prepare_text(
        "민수가 영희에게 전화했고 김민수는 영희의 오빠다",
        members=[("김민수", "민수"), "이영희", "영희"],
    )
    assert "민수" not in out and "영희" not in out
    assert out.count("[PERSON_1]") >= 2  # 별칭 '민수' 와 '김민수' 는 같은 토큰
    assert sess.restore_text(out).value.count("김민수") >= 2


def test_long_multiline_text_and_deterministic_numbering():
    chunk = "엄마가 010-2222-3333 으로 전화함. 김민수가 kim@example.com 보냄.\n"
    text = chunk * 300
    a, sa = prepare_text(text, members=["김민수"])
    b, sb = prepare_text(text, members=["김민수"])
    assert a == b  # 같은 입력이면 같은 토큰 번호
    assert a.count("[PHONE_1]") == 300 and "[PHONE_2]" not in a
    assert sa.counts_by_kind == sb.counts_by_kind
    sa.close()
    sb.close()


def test_token_numbers_follow_order_of_appearance():
    out, sess = prepare_text("010-1111-2222 와 010-3333-4444 그리고 다시 010-1111-2222")
    assert out == "[PHONE_1] 와 [PHONE_2] 그리고 다시 [PHONE_1]"
    sess.close()


def test_session_shared_across_pieces():
    s = new_session(members=["김민수"])
    a, _ = prepare_text("김민수 010-1111-2222", session=s)
    b, _ = prepare_text("다시 010-1111-2222 와 김민수", session=s)
    assert a == "[PERSON_1] [PHONE_1]" and b == "다시 [PHONE_1] 와 [PERSON_1]"
    j, _ = prepare_json({"owner": "김민수", "tel": "010-9999-8888"}, session=s)
    assert j == {"owner": "[PERSON_1]", "tel": "[PHONE_2]"}
    s.close()


def test_text_type_checked_and_closed_session_refuses():
    with pytest.raises(TypeError):
        prepare_text(123)  # type: ignore[arg-type]
    s = new_session()
    s.close()
    with pytest.raises(RuntimeError):
        prepare_text("010-1234-5678", session=s)


def test_user_typed_token_lookalike_is_neutralized():
    out, sess = prepare_text("[PHONE_1] 이 내 번호야, 010-1234-5678")
    assert out.startswith("‹PHONE_1›")
    restored = sess.restore_text("답: [PHONE_1] 입니다 ‹PHONE_1›").value
    assert "010-1234-5678" not in restored  # PHONE 은 ASSISTANT 에서 복원하지 않는다
    sess.close()


# ---------- JSON ----------
def test_json_nested_only_string_values_change():
    data = {
        "title": "김민수 병원비",
        "amount": 45000,
        "ratio": 0.5,
        "paid": True,
        "memo": None,
        "when": date(2026, 10, 26),
        "members": [
            {"name": "이영희", "phone": "010-1234-5678", "share": 22500},
            {"name": "김민수", "tags": ["a", ["중첩 010-5555-6666"]]},
        ],
        "meta": {"deep": {"addr": "서울시 강남구 테헤란로 152"}},
    }
    snapshot = copy.deepcopy(data)
    out, sess = prepare_json(data, members=["김민수", "이영희"])
    assert data == snapshot  # 원본은 그대로
    assert list(out) == list(data)  # 키와 순서 유지
    assert out["amount"] == 45000 and out["ratio"] == 0.5 and out["paid"] is True
    assert out["memo"] is None and out["when"] == date(2026, 10, 26)
    assert out["members"][0]["name"] == "[PERSON_2]" or out["members"][0]["name"] == "[PERSON_1]"
    dumped = json.dumps(out, ensure_ascii=False, default=str)
    for secret in ("김민수", "이영희", "010-1234-5678", "010-5555-6666", "테헤란로"):
        assert secret not in dumped
    assert out["members"][1]["tags"][1][0].startswith("중첩 [PHONE_")
    restored = sess.restore_json(out)
    assert restored.value["members"][0]["name"] == "이영희"
    assert restored.value["members"][0]["phone"] == "(연락처)"
    assert restored.value["meta"]["deep"]["addr"] == "서울시 강남구 테헤란로 152"
    sess.close()


def test_json_keys_kept_by_default_and_pseudonymized_on_request():
    out, s1 = prepare_json({"김민수": 5000}, members=["김민수"])
    assert out == {"김민수": 5000}  # 기본: 키 유지
    out2, s2 = prepare_json({"김민수": 5000}, members=["김민수"], pseudonymize_keys=True)
    assert out2 == {"[PERSON_1]": 5000}
    assert s2.restore_json(out2).value == {"김민수": 5000}
    s1.close()
    s2.close()


def test_json_unsupported_type_fails_closed_and_depth_limited():
    class Custom:
        pass

    with pytest.raises(TypeError):
        prepare_json({"x": Custom()})
    deep: dict = {}
    node = deep
    for _ in range(200):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(ValueError):
        prepare_json(deep)


def test_json_tuple_set_and_top_level_scalars():
    out, s = prepare_json(("010-1111-2222", {"a"}), policy=ASSISTANT)
    assert out[0] == "[PHONE_1]" and out[1] == {"a"}
    assert prepare_json(7)[0] == 7 and prepare_json(None)[0] is None
    s.close()


def test_number_modes():
    data = {"amount": 123456, "price": 4567.89, "n": 7, "ok": True, "d": Decimal("1999")}
    kept, _ = prepare_json(data)
    assert kept["amount"] == 123456 and kept["price"] == 4567.89
    rounded, _ = prepare_json(data, numbers="round")
    assert rounded["amount"] == 120000 and rounded["price"] == 4600.0
    assert rounded["n"] == 7 and rounded["ok"] is True and rounded["d"] == Decimal("2000")
    with pytest.raises(ValueError):
        prepare_json(data, numbers="bad")


def test_number_mode_from_policy():
    from app.shared.privacy import Policy

    coarse = Policy(
        "coarse",
        dict(ASSISTANT.actions),
        restore_kinds=ASSISTANT.restore_kinds,
        number_mode="round",
    )
    out, _ = prepare_json({"amount": 123456}, policy=coarse)
    assert out["amount"] == 120000
    with pytest.raises(ValueError):
        Policy("bad", number_mode="floor")


def test_generalize_number_edges():
    assert generalize_number(0) == 0
    assert generalize_number(99) == 99
    assert generalize_number(-123456) == -120000
    assert generalize_number(0.4567) == 0.46
    assert generalize_number(True) is True
    assert generalize_number(float("inf")) == float("inf")
    assert generalize_number(10**40) == 10**40  # Decimal 정밀도를 넘는 큰 수는 그대로
    assert generalize_number(10**20 + 5) == 10**20


# ---------- keys_to_drop / 좌표 ----------
def test_keys_to_drop_removes_key_and_value_at_any_depth_case_insensitive():
    data = {"id": 1, "Secret": "x", "items": [{"note": "a", "keep": "b", "SECRET": "z"}]}
    out, _ = prepare_json(data, keys_to_drop=["secret", "note"])
    assert out == {"id": 1, "items": [{"keep": "b"}]}


def test_coordinate_keys_generalized_by_default():
    data = {
        "place": "집",
        "lat": 37.566535,
        "lng": 126.977969,
        "nested": {"Latitude": 37.5, "lon": "127.0399"},
    }
    out, _ = prepare_json(data)
    assert out["lat"] == 37.56 and out["lng"] == 126.97
    assert out["nested"] == {"Latitude": 37.5, "lon": 127.03}
    assert "lat" in COORDINATE_KEYS


def test_coordinate_unparseable_values_become_none_and_drop_wins():
    out, _ = prepare_json({"lat": "abc", "lng": True, "lon": {"x": 1}, "latitude": None})
    assert out == {"lat": None, "lng": None, "lon": None, "latitude": None}
    out2, _ = prepare_json({"lat": 1.234, "lng": 2.345}, keys_to_drop=["lat"])
    assert out2 == {"lng": 2.34}
    out3, _ = prepare_json({"lat": 1.2345}, coordinate_keys=())
    assert out3 == {"lat": 1.2345}  # 좌표 규칙을 끌 수 있다
    out4, _ = prepare_json({"lat": 1.2345}, coordinate_precision=3)
    assert out4 == {"lat": 1.234}


@pytest.mark.parametrize(
    ("lat", "lng", "precision", "expected"),
    [
        (37.5665, 126.9780, 2, (37.56, 126.97)),
        (37.5665, 126.9780, 0, (37.0, 126.0)),
        (37.5665, 126.9780, 1, (37.5, 126.9)),
        (37.5665, 126.9780, 3, (37.566, 126.978)),
        (-33.8688, -151.2093, 2, (-33.86, -151.2)),  # 음수는 0 쪽으로 절삭
        (-0.004, 0.0, 2, (0.0, 0.0)),  # -0.0 정리
        (90, 180, 2, (90.0, 180.0)),  # 경계값
        (-90, -180, 2, (-90.0, -180.0)),
        (0.999, 0.999, 2, (0.99, 0.99)),  # 반올림이 아니라 절삭
    ],
)
def test_generalize_coordinates(lat, lng, precision, expected):
    got = generalize_coordinates(lat, lng, precision=precision)
    assert got == expected
    assert str(got[0]) != "-0.0"


@pytest.mark.parametrize(
    ("lat", "lng", "precision"),
    [
        (91, 0, 2),
        (0, 181, 2),
        (-90.01, 0, 2),
        (float("nan"), 0, 2),
        (float("inf"), 0, 2),
        ("abc", 0, 2),
        (True, 0, 2),
        (None, 0, 2),
        (0, 0, -1),
        (0, 0, 7),
        (0, 0, 1.5),
        (0, 0, True),
    ],
)
def test_generalize_coordinates_rejects_bad_input(lat, lng, precision):
    with pytest.raises(ValueError):
        generalize_coordinates(lat, lng, precision=precision)


def test_generalized_coordinates_are_coarser():
    lat, lng = generalize_coordinates(37.566535, 126.977969)
    assert abs(lat - 37.566535) < 0.01 and abs(lng - 126.977969) < 0.01
    assert (lat, lng) != (37.566535, 126.977969)


# ---------- 복원 ----------
def test_restore_follows_assistant_kinds_name_and_address_only():
    out, sess = prepare_text(
        "김민수 010-1234-5678 a@b.com 서울시 강남구 테헤란로 152", members=["김민수"]
    )
    resp = f"{out} 요약: [PERSON_1] 에게 [PHONE_1] 또는 [EMAIL_1] 로 연락, 장소 [ADDR_1]"
    r = sess.restore_text(resp)
    assert "김민수" in r.value and "테헤란로 152" in r.value
    assert "010-1234-5678" not in r.value and "a@b.com" not in r.value
    assert "(연락처)" in r.value and "(이메일)" in r.value
    assert set(r.generalized_tokens) == {"[PHONE_1]", "[EMAIL_1]"}
    sess.close()


def test_restore_with_analysis_policy_kinds_and_reply_policy():
    out, sess = prepare_text(
        "서울시 강남구 테헤란로 152 에서 김민수", policy=REPLY, members=["김민수"]
    )
    restored = sess.restore_text(out).value
    assert (
        "김민수" in restored and "테헤란로" not in restored and "(주소)" in restored
    )  # REPLY 는 사람만
    sess.close()
    out2, sess2 = prepare_text("서울시 강남구 테헤란로 152", policy=ANALYSIS)
    assert "테헤란로" in sess2.restore_text(out2).value
    sess2.close()


def test_restore_rejects_forged_double_and_foreign_tokens():
    out, sess = prepare_text("김민수 010-1234-5678", members=["김민수"])
    other_out, other = prepare_text("이영희 010-9999-8888", members=["이영희"])
    assert other_out == "[PERSON_1] [PHONE_1]" and out == other_out  # 번호가 같아도
    r = sess.restore_text("[PERSON_9] [person_1] [PERSON_ 1] [PERSON_01] 【PERSON_1】 [PERSON_1]")
    assert r.value == "[PERSON_9] [person_1] [PERSON_ 1] [PERSON_01] 【PERSON_1】 김민수"
    assert "[PERSON_9]" in r.unknown_tokens
    assert "이영희" not in r.value  # 다른 요청 객체의 값은 나오지 않는다
    # 이중 복원: 복원 결과를 다시 복원해도 값이 바뀌지 않는다
    again = sess.restore_text(r.value).value
    assert again == r.value
    # 복원 값이 토큰 모양이어도 다시 복원되지 않는다
    s2 = new_session(members=["[PERSON_2]"])
    o2, _ = prepare_text("[PERSON_2] 안녕", session=s2)
    assert s2.restore_text(o2).value.count("[PERSON_2]") == 0
    sess.close()
    other.close()
    s2.close()


def test_restore_after_close_restores_nothing_and_json_restore_works_with_helpers():
    out, sess = prepare_json({"who": "김민수"}, members=["김민수"])
    assert sess.restore_json({"x": "[PERSON_1]"}, scrub=True).value == {"x": "김민수"}
    sess.close()
    assert sess.restore_json({"x": "[PERSON_1]"}).value == {"x": "[PERSON_1]"}


def test_generalize_unknown_and_scrub():
    out, sess = prepare_text("주민번호 900101-1234568")
    assert sess.restore_text(out, scrub=True).value == "주민번호 (민감 정보)"
    assert sess.restore_text("[ADDR_3]", generalize_unknown=True).value == "(알 수 없는 항목)"
    sess.close()


# ---------- 누출 방지 ----------
def test_session_does_not_leak_through_repr_pickle_copy_or_logs(caplog):
    secret_name = "김민수"
    secret_phone = "010-1234-5678"
    with caplog.at_level("DEBUG"):
        out, sess = prepare_text(f"{secret_name} {secret_phone}", members=[secret_name])
        sess.restore_text(out)
    for rendered in (repr(sess), str(sess), f"{sess!r}", repr(sess.pseudonymizer)):
        assert secret_name not in rendered and secret_phone not in rendered
    for fn in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            fn(sess)
    assert secret_name not in caplog.text and secret_phone not in caplog.text
    assert "known_names" not in repr(sess)
    assert isinstance(sess, PrivacySession)
    sess.close()
    assert sess._known_names == () and sess.pseudonymizer.size == 0


# ---------- 성능(ReDoS 회귀) ----------
HOSTILE_TEXT = {
    "digits": "1" * 100_000,
    "dot": "a." * 50_000,
    "hyphen": "1-" * 50_000,
    "latin": "a" * 100_000,
    "spaces": " " * 100_000,
    "hangul": "가" * 100_000,
    "secret-kw": "비번 " * 30_000,
    "open-bracket": "[PHONE" + " " * 100_000,
    "many-open": "[[[[" * 25_000,
}


@pytest.mark.parametrize("name", list(HOSTILE_TEXT))
def test_prepare_text_is_fast_on_long_hostile_input(name):
    text = HOSTILE_TEXT[name]
    sess = new_session(members=["김민수"])
    assert timed(sess.prepare_text, text) < 1.5
    sess.close()


def test_prepare_text_is_linear_on_repeated_input():
    sess = new_session(members=["김민수"])
    small = timed(sess.prepare_text, "010-1234-5678 김민수 서울시 강남구 테헤란로 152 " * 400)
    large = timed(sess.prepare_text, "010-1234-5678 김민수 서울시 강남구 테헤란로 152 " * 4000)
    assert large < 3.0 and large < max(small, 0.02) * 40
    sess.close()


def test_prepare_json_many_small_strings_is_fast():
    data = {
        "items": [{"title": f"항목 {i}", "who": "김민수", "amount": i * 100} for i in range(5000)]
    }
    sess = new_session(members=["김민수"])
    assert timed(sess.prepare_json, data) < 3.0
    sess.close()


def test_small_text_call_is_millisecond_scale():
    sess = new_session(members=["김민수"])
    sess.prepare_text("warmup 010-1234-5678")
    runs = [
        timed(sess.prepare_text, "김민수 010-1234-5678 에게 서울시 강남구 테헤란로 152 보내줘")
        for _ in range(20)
    ]
    assert min(runs) < 0.02  # 기준보다 느슨한 상한(느린 CI 대비), 보통 1~3ms
    sess.close()


# ---------- 같은 탐지기 / 회귀 ----------
@pytest.mark.parametrize(
    ("fname", "max_leak"), [("pii_eval.jsonl", 0.05), ("pii_eval_holdout.jsonl", 0.28)]
)
def test_free_text_uses_same_detector_as_evaluation(fname, max_leak):
    rows = [
        json.loads(line)
        for line in (EVAL_DIR / fname).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    gold = leaked = 0
    for r in rows:
        names = tuple(r["known_names"])
        out, sess = prepare_text(r["text"], members=names)
        expected = [
            s for s in detect(r["text"], names) if ASSISTANT.action_for(s.kind).value != "KEEP"
        ]
        assert sum(sess.counts_by_kind.values()) == len(expected)  # 탐지 결과가 그대로 반영된다
        for g in r["spans"]:
            gold += 1
            if r["text"][g["start"] : g["end"]] in out:
                leaked += 1
        sess.close()
    # 같은 탐지기라 평가 문서의 재현율과 같은 수준: 실제 누출률 학습형 3.5%, 보조 25.5%(PERSON 포함)
    assert leaked / gold < max_leak


def test_prepare_transcript_unchanged_by_new_api():
    rows = [(1, "김민수", "주민번호 900101-1234568"), (2, "이영희", "010-1234-5678 로 연락")]
    with prepare_transcript(rows, ["김민수", "이영희"], ANALYSIS) as prep:
        assert prep.blocked_ids == [1]  # 줄 단위 BLOCK 은 여전히 메시지 통째 제외
        assert prep.lines[0].text.startswith("[민감정보")
        assert prep.lines[1].text == "[PHONE_1] 로 연락"
    with new_session(ANALYSIS) as sess:
        # 같은 정책이어도 자유 글 API 는 값만 가린다
        assert sess.prepare_text("주민번호 900101-1234568") == "주민번호 [RRN]"
