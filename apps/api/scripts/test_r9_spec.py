"""R9 공통 규격 호환성 시험(pytest 불필요). 모델·봉인 평가셋을 쓰지 않고, 이 파일 안의 합성 픽스처만 쓴다.

확인: (1) 픽스처가 검증기를 통과, (2) 규격 위반 변형이 기대한 오류 코드를 낸다, (3) 기존 평가 코드(evaluate_r8_new180.analyze/summarize)가 공통 형식을
그대로 읽고 정답=예측일 때 만점이 나온다, (4) 변환기가 학습 행을 올바르게 만들고 글자 BIO 왕복이 일치, (5) 매니페스트 SHA256 왕복.
실행: python scripts/test_r9_spec.py
"""

import copy
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "ml" / "ner" / "data"))

import validate_r9_evalset as V  # noqa: E402
import convert_common_to_train as C  # noqa: E402


def mk(rid, text, specs, category="messenger", neg=None, **extra):
    """specs: [(label, value)] 값이 문장에서 처음 나오는 위치(여러 번이면 순서대로 이어서 탐색)."""
    spans, pos = [], 0
    for label, value in specs:
        i = text.find(value, pos)
        assert i >= 0, (text, value)
        spans.append({"start": i, "end": i + len(value), "label": label, "mapped_kind": V.LABEL_TO_KIND[label], "value": value})
        pos = i + len(value)
    row = {"id": rid, "category": category, "text": text, "spans": spans, "is_negative": (not spans) if neg is None else neg, "source": "fixture_synthetic"}
    row.update(extra)
    return row


# ※ 이 문장들은 규격 시험용 가짜 픽스처이며 평가셋이 아니다.
FIXTURE = [
    mk("fx-001", "다온아 오늘 학원 끝나고 바로 와", [("PERSON", "다온")]),
    mk("fx-002", "지우 엄마가 간식 사 온대", [("PERSON_ALIAS", "지우 엄마")]),
    mk("fx-003", "서도윤이랑 한채원은 같은 반이야", [("PERSON", "서도윤"), ("PERSON", "한채원")]),
    mk("fx-004", "도윤이 집 주소는 서울시 마포구 월드컵로 12 이고 번호는 010-2345-6789 야", [("PERSON", "도윤"), ("ADDRESS", "서울시 마포구 월드컵로 12"), ("PHONE", "010-2345-6789")], category="mixed"),
    mk("fx-005", "자료는 sample.user@example.com 으로 보내 줘", [("EMAIL", "sample.user@example.com")], category="email"),
    mk("fx-006", "입금은 국민은행 123-45-678901 로 해 줘", [("ACCOUNT", "123-45-678901")], category="account"),
    mk("fx-007", "오늘 하늘 진짜 예쁘다", [], category="negative"),
    mk("fx-008", "내일 강남역에서 만나자", [], category="negative", context_entities=[{"start": 3, "end": 6, "label": "LOCATION", "value": "강남역"}]),
    mk("fx-009", "엄마가 장 봐 왔대", [], category="negative"),
    mk("fx-010", "봄 소풍 도시락은 각자 싸 오기로 했어", [], category="negative", exclude=True, exclude_reason="one_char_name_context_ambiguous"),
]
STRESS_FIXTURE = [
    mk("fs-001", "미르야 밥 먹자", [("PERSON", "미르")], primary_stress_type="A1", stress_types=["A1"], split_set="stress"),
    mk("fs-002", "서윤하준 둘이 같이 갔대", [("PERSON", "서윤"), ("PERSON", "하준")], primary_stress_type="C2", stress_types=["C2", "D3"], split_set="stress"),
    mk("fs-003", "바다 보러 가자", [], primary_stress_type="D1", split_set="stress"),
]


def write(rows, path):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def run_validator(rows, set_kind=None, extra=()):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.jsonl"
        write(rows, p)
        rep = Path(d) / "rep.json"
        buf = io.StringIO()
        with redirect_stdout(buf):
            V.main(["--data", str(p), "--report-out", str(rep), *(["--set-kind", set_kind] if set_kind else []), *extra])
        return json.loads(rep.read_text(encoding="utf-8")), buf.getvalue()


def codes(rep):
    return set(rep["errors"]) | set(rep["warnings"])


def test_fixture_passes():
    rep, out = run_validator(FIXTURE)
    assert not rep["errors"], rep["errors"]
    assert rep["info"]["rows_excluded"] == 1 and rep["info"]["person_spans"] == 5
    assert "하늘" not in out and "다온" not in out, "검증기 출력에 평가셋 원문이 들어갔다"
    rep2, out2 = run_validator(STRESS_FIXTURE, "stress")
    assert not rep2["errors"], rep2["errors"]


def test_violations_detected():
    base = copy.deepcopy(FIXTURE)
    cases = {}
    r = copy.deepcopy(base); r[0]["spans"][0]["start"] += 1; cases["SPAN_VALUE_MISMATCH"] = r
    r = copy.deepcopy(base); r[0]["spans"][0]["mapped_kind"] = "ADDRESS"; cases["MAPPED_KIND_MISMATCH"] = r
    r = copy.deepcopy(base); r[2]["spans"][1]["start"] = r[2]["spans"][0]["start"]; r[2]["spans"][1]["end"] = r[2]["spans"][0]["end"] + 1; r[2]["spans"][1]["value"] = r[2]["text"][r[2]["spans"][1]["start"]:r[2]["spans"][1]["end"]]; cases["SPAN_OVERLAP"] = r
    r = copy.deepcopy(base); r[1]["id"] = r[0]["id"]; cases["DUP_ID"] = r
    r = copy.deepcopy(base); r[8]["text"] = r[6]["text"]; cases["DUP_TEXT_EXACT"] = r
    r = copy.deepcopy(base); r[6]["spans"] = copy.deepcopy(r[0]["spans"]); cases["SPAN_VALUE_MISMATCH"] = r  # 음성 문장에 남의 span 을 붙임
    r = copy.deepcopy(base); r[0]["spans"][0]["label"] = "RRN"; r[0]["spans"][0]["mapped_kind"] = "RRN"; cases["LABEL_UNKNOWN_OR_FORBIDDEN"] = r
    r = copy.deepcopy(base); r[6]["is_negative"] = False; cases["NEGATIVE_FLAG_INCONSISTENT"] = r
    r = copy.deepcopy(base); r.append(mk("fx-011", "봄이한테 전화 왔어", [("PERSON", "봄")])); cases["ONE_CHAR_NAME_MUST_BE_EXCLUDED"] = r
    r = copy.deepcopy(base); del r[0]["is_negative"]; cases["SCHEMA_REQUIRED_FIELD"] = r
    r = copy.deepcopy(base); r[7]["context_entities"][0]["start"] = 0; cases["CONTEXT_ENTITY_INVALID"] = r
    r = copy.deepcopy(base); r[6]["context_entities"] = []; r[8]["text"] = "연락은 010-2222-3333 으로 해"; r[8]["spans"] = []; r[8]["is_negative"] = True; cases["NEGATIVE_HIDDEN_PHONE_PATTERN"] = r
    r = copy.deepcopy(base); r.append(mk("fx-012", "오늘 서도윤 못 봤어", [])); cases["UNLABELED_KNOWN_NAME_LEN3PLUS"] = r
    for code, rows in cases.items():
        rep, _ = run_validator(rows)
        assert code in codes(rep), (code, sorted(codes(rep)))
    # 제외 표시 행에 1글자 이름 span 이 있어도 오류가 아니다
    ex = copy.deepcopy(base); ex.append(mk("fx-013", "봄이 왔대", [("PERSON", "봄")], exclude=True, exclude_reason="one_char_name"))
    rep, _ = run_validator(ex)
    assert not rep["errors"], rep["errors"]


def test_reference_leak_detection():
    with tempfile.TemporaryDirectory() as d:
        refd = Path(d) / "ref"; refd.mkdir()
        leak = [{"text": FIXTURE[0]["text"], "spans": [{"label": "PERSON", "start": 0, "end": 2}]}]
        write(leak, refd / "train.jsonl")
        rep, _ = run_validator(FIXTURE, extra=["--reference-dir", str(refd)])
        assert "LEAK_SENTENCE_EQUALS_REFERENCE" in rep["errors"] and rep["info"]["reference"]["rows_with_name_seen_in_reference"] >= 1


def test_existing_eval_code_compat():
    import evaluate_r8_new180 as E
    rows = [r for r in FIXTURE if not r.get("exclude")]
    oracle = lambda r: [(s["mapped_kind"], s["start"], s["end"], 0.95) for s in r["spans"]]
    s = E.summarize(rows, E.analyze(oracle, rows))
    pf = s["person_family"]
    assert pf["exact"]["f1"] == 1.0 and pf["total_exposure_rate"] == 0 and pf["nonperson_fpr"] == 0
    assert s["protected_all_kinds"]["rate"] == 1.0 and s["account_block_policy"]["blocked"] == 1
    import r8_eval_lib as L
    assert L.gold_person(rows[1]) == [(0, 5)] and len(L.gold_person(rows[2])) == 2   # PERSON_ALIAS 는 PERSON 계열로 채점


def test_converter_and_bio():
    out = [C.convert_row(r) for r in FIXTURE]
    assert out[-1] is None, "제외 행은 변환하지 않는다"
    rows = [o for o in out if o]
    r4 = rows[3]
    assert [s["label"] for s in r4["spans"]] == ["PERSON", "ADDRESS"] and r4["rule_spans"][0]["kind"] == "PHONE"
    r8 = rows[7]
    assert r8["spans"][0]["label"] == "LOCATION", "context_entities 는 NER 라벨로 학습"
    assert rows[5]["spans"] == [] and rows[5]["rule_spans"][0]["kind"] == "ACCOUNT"
    for r in rows:
        assert bio_roundtrip(r)
    one = mk("fx-x", "봄이한테 전화", [("PERSON", "봄")])
    assert C.convert_row(one) is None, "1글자 이름 문장은 음성으로 바꾸지 않고 건너뛴다"


def bio_roundtrip(r):
    tags = C.char_bio(r["text"], r["spans"])
    back = C.bio_to_spans(tags)
    return [(s["label"], s["start"], s["end"]) for s in back] == [(s["label"], s["start"], s["end"]) for s in sorted(r["spans"], key=lambda x: x["start"])]


def test_manifest_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.jsonl"; write(FIXTURE, p)
        m = Path(d) / "m.json"
        V.main(["--data", str(p), "--manifest-out", str(m)])
        assert V.main(["--data", str(p), "--verify-manifest", str(m)]) == 0
        write(FIXTURE[:-1], p)
        assert V.main(["--data", str(p), "--verify-manifest", str(m)]) == 1


def test_tag_converter():
    import tag_to_r9_jsonl as T
    r = T.convert({"id": "t-1", "category": "mixed", "marked": "[[PERSON|다온]]아 [[ORGANIZATION|새봄학원]] 끝나고 [[PHONE|010-1111-2222]] 로 전화해", "primary_stress_type": "A1"})
    assert r["text"] == "다온아 새봄학원 끝나고 010-1111-2222 로 전화해"
    assert [s["label"] for s in r["spans"]] == ["PERSON", "PHONE"] and r["context_entities"][0]["label"] == "ORGANIZATION"
    assert all(r["text"][s["start"]:s["end"]] == s["value"] for s in r["spans"] + r["context_entities"])
    assert r["is_negative"] is False and r["primary_stress_type"] == "A1"
    neg = T.convert({"id": "t-2", "category": "negative", "marked": "오늘 날씨 좋다"})
    assert neg["is_negative"] is True and neg["spans"] == []
    for bad in ("[[PERSON|서아] 왔어", "[[RRN|123]] 왔어", "서아]] 왔어"):
        try:
            T.convert({"id": "t-3", "category": "x", "marked": bad}); raise AssertionError("오류가 나야 한다")
        except ValueError:
            pass
    rep, _ = run_validator([r, neg])
    assert not rep["errors"], rep["errors"]


def test_review_sample():
    rows = [mk(f"r-{i:03d}", f"테스트 문장 {i} 번째 입니다", [], category="negative") for i in range(60)]
    s = V.review_sample(rows, 10, 7)
    assert len(s["random_stratified_ids"]) >= 10 and "text" not in json.dumps(s)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("통과:", t.__name__)
    print(f"{len(tests)}개 시험 통과")
