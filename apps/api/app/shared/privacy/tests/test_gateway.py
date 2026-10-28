"""gateway 흐름(합성 대화 -> 가명화 -> 가짜 LLM 응답 -> 복원), 평가 데이터셋 점검, 성능 스모크."""

import json
import time
from pathlib import Path

from app.shared.privacy import (
    ANALYSIS,
    REPLY,
    Kind,
    Row,
    detect,
    new_session,
    prepare_transcript,
    restore_json,
    restore_value,
)
from app.shared.privacy.policy import BLOCKED_PLACEHOLDER

NAMES = ["김민수", "이영희"]
ROWS = [
    (1, "김민수", "내일 저녁 6시에 강남역 앞 식당에서 보자. 내 번호는 010-1234-5678"),
    (2, "이영희", "민수야 좋아. 예약은 kim.test@example.com 으로 확인 메일 갈 거야"),
    (3, "김민수", "와이파이 비밀번호는 abcd1234 야"),
    (4, "이영희", "그럼 서울시 강남구 테헤란로 152 로 데리러 갈게"),
    (5, "김민수", "고마워 영희씨"),
]


def test_prepare_transcript_end_to_end():
    with prepare_transcript(ROWS, NAMES, ANALYSIS) as prep:
        sent = json.dumps([line.__dict__ for line in prep.lines], ensure_ascii=False)
        for secret in (
            "김민수",
            "이영희",
            "010-1234-5678",
            "kim.test@example.com",
            "abcd1234",
            "테헤란로",
        ):
            assert secret not in sent
        assert [line.id for line in prep.lines] == [1, 2, 3, 4, 5]
        assert prep.blocked_ids == [3] and prep.blocked_count == 1
        assert prep.lines[2].text == BLOCKED_PLACEHOLDER
        assert prep.counts_by_kind["PHONE"] == 1 and prep.counts_by_kind["SECRET"] == 1
        assert prep.lines[0].speaker == "[PERSON_1]" and prep.lines[1].speaker == "[PERSON_2]"

        # 가짜 LLM 응답: 토큰을 그대로 쓰고, 변형·지어낸 토큰도 섞는다
        fake = {
            "summary": "[PERSON_1]이 [PHONE_1] 로 연락하기로 함. 장소 [ADDR_1]",
            "todo_candidates": [{"title": "확인 메일", "assignee_name": "[PERSON_2]", "n": 3}],
            "extra": ["[PHONE_9]", "[phone_1]"],
        }
        out = restore_json(prep, fake)
        assert (
            out.value["summary"]
            == "김민수이 (연락처) 로 연락하기로 함. 장소 서울시 강남구 테헤란로 152"
        )
        assert out.value["todo_candidates"][0]["assignee_name"] == "이영희"
        assert out.value["todo_candidates"][0]["n"] == 3
        assert out.value["extra"] == ["[PHONE_9]", "[phone_1]"]
        assert out.unknown_tokens == ["[PHONE_9]", "[phone_1]"]
        assert out.generalized_tokens == ["[PHONE_1]"]  # ANALYSIS 는 PERSON·ADDRESS 만 복원한다
        assert restore_value(prep, "[EMAIL_1]").value == "(이메일)"
    assert prep.pseudonymizer.size == 0  # with 블록이 끝나면 대응표가 지워진다


def test_speaker_tokens_off_keeps_speaker_name_but_masks_text():
    prep = prepare_transcript(
        [Row(1, "김민수", "010-1234-5678 로 와")], NAMES, ANALYSIS, speaker_tokens=False
    )
    assert prep.lines[0].speaker == "김민수" and prep.lines[0].text == "[PHONE_1] 로 와"


def test_unknown_speaker_still_tokenized_and_text_mention_shares_token():
    prep = prepare_transcript(
        [(1, "박지후", "안녕"), (2, "김민수", "박지후한테 전화했어")], NAMES, REPLY
    )
    assert prep.lines[0].speaker == "[PERSON_1]"
    assert prep.lines[1].text == "[PERSON_1]한테 전화했어"


def test_dataset_is_well_formed_and_synthetic():
    path = Path(__file__).resolve().parents[1] / "eval" / "pii_eval.jsonl"
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) >= 250
    assert sum(1 for r in rows if not r["spans"]) >= 80
    per_kind = {}
    for r in rows:
        for s in r["spans"]:
            assert 0 <= s["start"] < s["end"] <= len(r["text"])
            per_kind[s["kind"]] = per_kind.get(s["kind"], 0) + 1
    assert all(per_kind.get(k.value, 0) >= 20 for k in Kind)


def test_detection_quality_floor_on_dataset():
    """성능이 크게 떨어지는 변경을 잡는 느슨한 하한(정확한 수치는 scripts/eval_pii.py 로 본다)."""
    path = Path(__file__).resolve().parents[1] / "eval" / "pii_eval.jsonl"
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    tp = gold = neg_hit = neg = 0
    for r in rows:
        pred = detect(r["text"], tuple(r["known_names"]))
        for g in r["spans"]:
            gold += 1
            if any(
                p.kind.value == g["kind"] and p.start < g["end"] and g["start"] < p.end
                for p in pred
            ):
                tp += 1
        if not r["spans"]:
            neg += 1
            neg_hit += bool(pred)
    assert tp / gold >= 0.85
    assert neg_hit / neg <= 0.10


def test_performance_smoke_200_lines_of_2000_chars():
    line = (
        "오늘 저녁에 모여서 이야기하자 010-1234-5678 로 연락해 줘 서울시 강남구 테헤란로 152 에서 김민수 만나기로 했어 "
        * 30
    )[:2000]
    rows = [(i, "김민수", line) for i in range(200)]
    start = time.perf_counter()
    with prepare_transcript(rows, NAMES, ANALYSIS) as prep:
        assert len(prep.lines) == 200
    assert time.perf_counter() - start < 15  # 느슨한 상한(보통 1~2초 안팎)


def test_luhn_fail_card_is_masked_not_blocked_in_transcript_and_free_text():
    # 오타 난 카드번호(Luhn 실패)도 가린다. 점수가 차단 임계값 미만이라 메시지는 통째로 빠지지 않는다.
    rows = [
        (1, "김민수", "카드번호 4512-4516-1112-0055 야"),
        (2, "이영희", "카드번호 4512451611120055 야"),
        (3, "김민수", "주문번호 4512451611120055 야"),
    ]
    with prepare_transcript(rows, NAMES, ANALYSIS) as prep:
        assert prep.lines[0].text == "카드번호 [CARD] 야"
        assert prep.lines[1].text == "카드번호 [CARD] 야"
        assert prep.lines[2].text == "주문번호 4512451611120055 야"  # 주문번호 문맥은 그대로
        assert prep.blocked_ids == [] and prep.counts_by_kind["CARD"] == 2
    with new_session(ANALYSIS) as sess:
        assert sess.prepare_text("카드번호 4512-4516-1112-0055") == "카드번호 [CARD]"
        assert sess.prepare_text("카드번호 4512451611120055") == "카드번호 [CARD]"
        assert sess.prepare_text("4512451611120055") == "4512451611120055"
