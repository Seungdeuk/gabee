"""NER 보강 어댑터 시험. 모델 파일 없이 가짜 세션 + 글자 단위 tokenizer 로 돌린다(CI 에서 통과해야 한다).

실모델 시험은 환경변수 GABEE_NER_TEST_MODEL_DIR 가 있을 때만 돈다(없으면 skip).
"""

import hashlib
import json
import logging
import os
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tokenizers import Regex, Tokenizer, models, pre_tokenizers

from app.shared.config import settings
from app.shared.errors import register_error_handlers
from app.shared.llm.agent import Tool, run_agent
from app.shared.privacy import (
    ANALYSIS,
    ASSISTANT,
    PrivacyUnavailable,
    detect,
    ner,
    new_session,
    prepare_json,
    prepare_text,
    prepare_transcript,
)
from app.shared.privacy.types import Kind

LABELS = {
    0: "O",
    1: "B-PERSON",
    2: "I-PERSON",
    3: "B-PERSON_ALIAS",
    4: "I-PERSON_ALIAS",
    5: "B-ADDRESS",
    6: "I-ADDRESS",
    7: "B-LOCATION",
    8: "I-LOCATION",
    9: "B-ORGANIZATION",
    10: "I-ORGANIZATION",
}
LABEL_ID = {v: k for k, v in LABELS.items()}


def make_tokenizer() -> Tokenizer:
    """글자 하나가 토큰 하나인 tokenizer(offset 은 글자 위치)."""
    chars = [chr(c) for c in range(0xAC00, 0xD7A4)] + [chr(c) for c in range(0x20, 0x7F)]
    vocab = {"[PAD]": 0, "[CLS]": 1, "[SEP]": 2, "[UNK]": 3}
    for ch in chars:
        vocab.setdefault(ch, len(vocab))
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Split(Regex("."), "isolated")
    return tok


class FakeSession:
    """창 안에서 targets({글자: 라벨}) 와 정확히 일치하는 부분에 BIO 를 붙이는 가짜 ONNX 세션."""

    def __init__(self, tok: Tokenizer, targets: dict[str, str], strength: float = 8.0):
        self.targets = targets
        self.strength = strength
        self.id2char = {i: (c if len(c) == 1 else "") for c, i in tok.get_vocab().items()}
        self.calls = 0
        self.rows = 0
        self.fail = False
        self.delay = 0.0
        self.lock = threading.Lock()

    def get_inputs(self):
        class _I:
            def __init__(self, name):
                self.name = name

        return [_I("input_ids"), _I("attention_mask"), _I("token_type_ids")]

    def run(self, _outputs, feed):
        with self.lock:
            self.calls += 1
            self.rows += feed["input_ids"].shape[0]
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("secret/path 내용")
        assert "token_type_ids" in feed
        ids, mask = feed["input_ids"], feed["attention_mask"]
        logits = np.zeros((*ids.shape, len(LABELS)), dtype=np.float32)
        logits[:, :, 0] = self.strength
        for r in range(ids.shape[0]):
            text = "".join(
                self.id2char.get(int(i), "?") if m else "\0"
                for i, m in zip(ids[r], mask[r], strict=True)
            )
            for target, label in self.targets.items():
                at = text.find(target)
                while at != -1:
                    for k in range(len(target)):
                        tag = ("B-" if k == 0 else "I-") + label
                        logits[r, at + k, :] = 0
                        logits[r, at + k, LABEL_ID[tag]] = self.strength
                    at = text.find(target, at + len(target))
        return [logits]


def make_engine(targets, strength=8.0, **kw):
    tok = make_tokenizer()
    session = FakeSession(tok, targets, strength)
    return ner.NerEngine(tok, session, LABELS, **kw), session


@pytest.fixture
def setup(monkeypatch):
    """setup(targets, mode=..., **engine_kwargs) -> (engine, session). 끝나면 설정·캐시·싱글턴을 되돌린다."""
    ner.reset()

    def install(targets, mode="auto", strength=8.0, **kw):
        engine, session = make_engine(targets, strength, **kw)
        monkeypatch.setattr(settings, "privacy_ner_mode", mode)
        monkeypatch.setattr(ner, "_load_engine", lambda cfg: engine)
        ner.reset()
        return engine, session

    yield install
    ner.reset()


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    # 개발 PC 의 data/models/ner 에 실제 모델이 있어도 이 파일의 시험은 명시한 설정만 쓴다
    monkeypatch.setattr(settings, "privacy_ner_mode", "auto")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(tmp_path / "no-model"))
    monkeypatch.setattr(settings, "privacy_ner_max_concurrency", 2)
    ner.reset()
    yield
    ner.reset()


# ---------- 엔진: BIO 디코딩·위치 매핑 ----------
def test_predict_basic_and_particle_kept():
    engine, _ = make_engine({"정채은이": "PERSON", "서울시 강남구": "ADDRESS"})
    text = "어제 정채은이 서울시 강남구 갔어"
    spans = engine.predict(text)
    assert [(s.label, text[s.start : s.end]) for s in spans] == [
        ("PERSON", "정채은이"),  # 조사 결합은 모델 출력 그대로
        ("ADDRESS", "서울시 강남구"),
    ]
    assert all(0.9 < s.score <= 1.0 for s in spans)  # softmax 확률 평균


def test_original_position_mapping_fullwidth_and_invisible():
    engine, _ = make_engine({"정채은": "PERSON"})
    text = "０１２ 정\u200b채\u200d은 님"  # 전각 숫자 + 보이지 않는 문자가 이름 안에 낀 글
    (span,) = engine.predict(text)
    assert text[span.start : span.end] == "정\u200b채\u200d은"  # 원문 위치(보이지 않는 문자 포함)
    # 앞쪽 보이지 않는 문자가 있어도 위치가 밀리지 않는다
    text2 = "\u200b\u200b안녕 정채은"
    (s2,) = engine.predict(text2)
    assert text2[s2.start : s2.end] == "정채은"


def test_span_edges_trim_whitespace():
    engine, _ = make_engine({" 정채은 ": "PERSON"})
    text = "a  정채은  b"
    (s,) = engine.predict(text)
    assert text[s.start : s.end] == "정채은"


def test_sliding_window_boundary():
    engine, session = make_engine({"정채은": "PERSON", "서울시 강남구": "ADDRESS"})
    # 첫 창(토큰 0~125) 끝에 걸치는 이름(124~126), 겹침 구간 안(100), 멀리(300)
    text = ["가"] * 400
    for pos, name in ((124, "정채은"), (100 - 7, "서울시 강남구"), (300, "정채은")):
        text[pos : pos + len(name)] = list(name)
    text = "".join(text)
    spans = engine.predict(text)
    got = sorted((text[s.start : s.end], s.start) for s in spans)
    assert got == [("서울시 강남구", 93), ("정채은", 124), ("정채은", 300)]
    assert session.rows >= 4  # 여러 창


def test_window_and_char_limits_flag_truncation():
    engine, _ = make_engine({"정채은": "PERSON"}, max_windows=2)
    text = "가" * 100 + "정채은" + "가" * 400 + "정채은"
    res = engine.analyze_many([text])[0]
    assert res.truncated
    assert [text[s.start : s.end] for s in res.spans] == ["정채은"]  # 뒤쪽은 보지 못했다
    engine2, _ = make_engine({"정채은": "PERSON"}, max_chars=50)
    res2 = engine2.analyze_many(["가" * 60 + "정채은"])[0]
    assert res2.truncated and res2.spans == ()


def test_predict_many_matches_predict_and_batches():
    engine, session = make_engine({"정채은": "PERSON"})
    texts = [f"{i} 정채은 {i}" for i in range(5)]
    many = engine.predict_many(texts)
    assert session.calls == 1 and session.rows == 5
    assert many == [engine.predict(t) for t in texts]


# ---------- 병합 ----------
def test_rule_spans_win_and_non_overlapping_ner_added(setup):
    setup({"010-1234-5678": "ADDRESS", "정채은": "PERSON", "서울시 강남구": "ADDRESS"})
    text = "연락 010-1234-5678 정채은 서울시 강남구"
    rule = detect(text)
    assert [(s.kind, text[s.start : s.end]) for s in rule] == [
        (Kind.PHONE, "010-1234-5678"),
        (Kind.ADDRESS, "서울시 강남구"),
    ]
    merged = ner.detect_with_ner(text)
    by_text = {text[s.start : s.end]: s for s in merged}
    assert by_text["010-1234-5678"].kind is Kind.PHONE  # NER 이 규칙 탐지를 바꾸지 못한다
    assert by_text["정채은"].kind is Kind.PERSON and by_text["정채은"].source == "ner"
    assert by_text["서울시 강남구"].source != "ner"  # 규칙(지역)과 겹치는 NER 구간은 버린다
    assert [s.start for s in merged] == sorted(s.start for s in merged)


def test_known_names_dictionary_still_wins(setup):
    setup({"김민수가": "PERSON"})
    text = "김민수가 왔다"
    spans = ner.detect_with_ner(text, ("김민수",))
    assert [(s.source, text[s.start : s.end]) for s in spans] == [("name_dict", "김민수")]


def test_label_mapping_excludes_location_and_org_and_kinship(setup):
    setup(
        {
            "경복궁": "LOCATION",
            "삼성전자": "ORGANIZATION",
            "민수": "PERSON_ALIAS",
            "엄마": "PERSON",
            "한강로 근처": "ADDRESS",
        }
    )
    text = "경복궁 삼성전자 민수 엄마 한강로 근처"
    spans = ner.detect_with_ner(text)
    got = {text[s.start : s.end]: s.kind for s in spans}
    assert got == {"민수": Kind.PERSON, "한강로 근처": Kind.ADDRESS}
    assert ner.LABEL_TO_KIND.keys() == {"PERSON", "PERSON_ALIAS", "ADDRESS"}


def test_ner_score_capped_below_block_threshold_and_message_not_blocked(setup):
    setup({"정채은": "PERSON"})
    text = "정채은 한테 전해줘"
    (s,) = ner.detect_with_ner(text)
    assert s.score <= ner.NER_MAX_SCORE < ANALYSIS.block_min_score
    prep = prepare_transcript([(1, "아빠", text)], [], ANALYSIS)
    assert prep.blocked_ids == []
    assert prep.lines[0].text.startswith("[PERSON_1]")
    # 낮은 점수(모델이 자신 없음)는 버린다
    setup({"정채은": "PERSON"}, strength=0.1)
    assert ner.detect_with_ner(text) == detect(text)


# ---------- 모드 ----------
SAMPLES = [
    "엄마 010-1234-5678 로 전화해줘",
    "서울시 강남구 테헤란로 152 에서 만나",
    "김치찌개 먹자 정채은 씨",
    "",
    "plain english text 12345",
]


def test_auto_without_model_equals_rules_and_warns_once(caplog):
    # 기본 설정(auto), 모델 폴더 없음: 동작이 규칙 단독과 같고 경고는 프로세스당 한 번
    caplog.set_level(logging.WARNING)
    for t in SAMPLES * 3:
        assert ner.detect_with_ner(t) == detect(t)
    warnings = [r for r in caplog.records if r.name == ner.log.name]
    assert len(warnings) == 1
    assert "정채은" not in caplog.text and "010-1234" not in caplog.text
    prep = prepare_transcript([(1, "엄마", SAMPLES[0])], [], ANALYSIS)
    assert prep.lines[0].text == "엄마 [PHONE_1] 로 전화해줘" or "[PHONE_1]" in prep.lines[0].text


def test_off_never_loads(monkeypatch, setup):
    engine, session = setup({"정채은": "PERSON"}, mode="off")
    called = []
    monkeypatch.setattr(ner, "_load_engine", lambda cfg: called.append(1) or engine)
    text = "정채은 안녕"
    assert ner.detect_with_ner(text) == detect(text)
    with ner.batch_scope([text]):
        assert ner.spans_for(text) is None
    prepare_text(text)[1].close()
    assert not called and session.calls == 0


def test_auto_load_failure_falls_back_and_hides_details(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)

    def boom(cfg):
        raise RuntimeError("C:/secret/dir 정채은")

    monkeypatch.setattr(ner, "_load_engine", boom)
    text = "정채은 씨 010-1234-5678"
    assert ner.detect_with_ner(text) == detect(text)
    assert ner.detect_with_ner(text) == detect(text)
    assert caplog.text.count("불러오지 못했다") == 1
    assert "secret" not in caplog.text and "정채은" not in caplog.text


def test_auto_inference_error_falls_back(setup, caplog):
    caplog.set_level(logging.WARNING)
    _, session = setup({"정채은": "PERSON"})
    session.fail = True
    text = "정채은 안녕"
    assert ner.detect_with_ner(text) == detect(text)
    assert caplog.text.count("추론에 실패") == 1
    assert "secret" not in caplog.text and "정채은" not in caplog.text


def test_auto_over_limit_uses_rules_for_excess_with_warning(setup, caplog):
    caplog.set_level(logging.WARNING)
    setup({"정채은": "PERSON"}, max_chars=50)
    text = "가" * 60 + " 정채은"
    assert ner.detect_with_ner(text) == detect(text)
    assert "상한" in caplog.text and "정채은" not in caplog.text


def test_required_unavailable_raises_everywhere(monkeypatch):
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(Path("nonexistent-ner-dir")))
    ner.reset()
    with pytest.raises(PrivacyUnavailable) as e:
        prepare_text("정채은 010-1234-5678")
    assert (e.value.status, e.value.code) == (503, "privacy_unavailable")
    with pytest.raises(PrivacyUnavailable):
        prepare_transcript([(1, "a", "x")], [], ANALYSIS)
    with pytest.raises(PrivacyUnavailable):
        prepare_json({"a": "b"})
    with pytest.raises(PrivacyUnavailable):
        prepare_text("")  # 입력이 비어도 엔진이 없으면 같은 결과(경계에서 확인)


@pytest.mark.parametrize("failure", ["load", "infer", "limit"])
def test_required_failures_return_503_common_format_without_external_call(
    setup, monkeypatch, failure
):
    engine, session = setup(
        {"정채은": "PERSON"}, mode="required", max_chars=40 if failure == "limit" else 8000
    )
    if failure == "load":

        def boom(cfg):
            raise RuntimeError("C:/secret/dir")

        monkeypatch.setattr(ner, "_load_engine", boom)
        ner.reset()
    if failure == "infer":
        session.fail = True
    text = "가" * 60 + " 정채은 010-1234-5678" if failure == "limit" else "정채은 010-1234-5678"
    sent: list[str] = []
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/ask")
    def ask():
        masked, sess = prepare_text(text)
        sent.append(masked)  # 외부 LLM 호출 자리
        sess.close()
        return {"ok": True}

    res = TestClient(app).post("/ask")
    assert res.status_code == 503
    assert res.json() == {
        "code": "privacy_unavailable",
        "message": "개인정보 보호 엔진을 사용할 수 없어 AI 요청을 보내지 않았어요",
    }
    assert "secret" not in res.text and "정채은" not in res.text and "010-1234" not in res.text
    assert sent == []  # 외부로 나갈 글이 만들어지지 않았다


def test_required_with_engine_works(setup):
    setup({"정채은": "PERSON"}, mode="required")
    out, sess = prepare_text("정채은 안녕")
    assert out == "[PERSON_1] 안녕"
    assert sess.restore_text(out).value == "정채은 안녕"
    sess.close()


def test_unknown_mode_is_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "privacy_ner_mode", "requried")
    assert ner.current_mode() == "required"


# ---------- 통합: 배치·캐시·동시성·로그 ----------
def test_prepare_transcript_runs_one_batch(setup):
    _, session = setup({"정채은": "PERSON", "서울시 강남구": "ADDRESS"})
    rows = [(i, "아빠", f"{i}번 메시지 정채은 이야기") for i in range(6)]
    rows.append((9, "아빠", "서울시 강남구 갈래"))
    rows.append((10, "아빠", "12345"))  # 한글 없는 줄은 모델에 넣지 않는다
    prep = prepare_transcript(rows, [], ANALYSIS)
    assert session.calls == 1 and session.rows == 7
    assert prep.lines[0].text == "0번 메시지 [PERSON_1] 이야기"
    assert prep.lines[6].text.startswith("[ADDR_1]") or "[ADDR_1]" in prep.lines[6].text
    assert prep.counts_by_kind["PERSON"] == 6
    prep.close()


def test_cache_reuse_and_lru_eviction(setup, monkeypatch):
    _, session = setup({"정채은": "PERSON"})
    monkeypatch.setattr(ner, "CACHE_SIZE", 2)
    ner.detect_with_ner("정채은 하나")
    ner.detect_with_ner("정채은 하나")
    assert session.calls == 1
    ner.detect_with_ner("정채은 둘")
    ner.detect_with_ner("정채은 셋")  # 가장 오래된 '하나' 가 밀려난다
    ner.detect_with_ner("정채은 하나")
    assert session.calls == 4
    assert len(ner._cache) <= 2
    # 키에 원문이 없다(해시)
    assert all("정채은" not in "".join(k) for k in ner._cache)


def test_no_hangul_text_skips_model(setup):
    _, session = setup({"정채은": "PERSON"})
    out, sess = prepare_json({"id": 1, "note": "abc 123", "n": "010-1234-5678"})
    assert session.calls == 0 and out["n"] != "010-1234-5678"
    sess.close()


def test_concurrent_prepare_text_keeps_per_request_mapping(setup):
    names = [f"{s}채은" for s in "김이박최정강조윤장임한오서신권황"]
    _, session = setup({n: "PERSON" for n in names})
    session.delay = 0.002
    errors: list[str] = []

    def work(i: int) -> None:
        name = names[i % len(names)]
        text = f"{'가' * (i % 7)} {name} 이야기 {i}번"
        masked, sess = prepare_text(text)
        with sess:
            if masked != f"{'가' * (i % 7)} [PERSON_1] 이야기 {i}번":
                errors.append(f"masked {i}")
            if sess.restore_text(masked).value != text:
                errors.append(f"restore {i}")

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(work, range(200)))
    assert errors == []


def test_concurrent_transcripts_do_not_leak_scope(setup):
    names = [f"{s}채은" for s in "김이박최정강"]
    setup({n: "PERSON" for n in names})

    def work(i: int) -> bool:
        rows = [
            (1, "아빠", f"{names[i % 6]} 안녕"),
            (2, "아빠", f"{names[(i + 1) % 6]} 반가워 {i}"),
        ]
        with prepare_transcript(rows, [], ANALYSIS) as prep:
            return [ln.text for ln in prep.lines] == ["[PERSON_1] 안녕", f"[PERSON_2] 반가워 {i}"]

    with ThreadPoolExecutor(12) as pool:
        assert all(pool.map(work, range(120)))


def test_logs_never_contain_text(setup, caplog):
    caplog.set_level(logging.DEBUG)
    _, session = setup({"정채은": "PERSON"})
    session.fail = True
    ner.detect_with_ner("정채은 010-1234-5678")
    prepare_transcript([(1, "a", "정채은 서울시 강남구")], [], ANALYSIS).close()
    assert "정채은" not in caplog.text and "010" not in caplog.text


def test_cache_key_reflects_ner_output_via_transcript_hash(setup, monkeypatch):
    """family_chat 의 AI 결과 캐시 키는 가명화된 줄의 해시를 포함한다: NER 로 가명화 결과가 달라지면 키가 달라진다."""
    rows = [(1, "아빠", "정채은 한테 전해줘")]
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    off_text = prepare_transcript(rows, [], ANALYSIS).lines[0].text
    setup({"정채은": "PERSON"})
    on_text = prepare_transcript(rows, [], ANALYSIS).lines[0].text
    assert off_text != on_text and on_text.startswith("[PERSON_1]")


def test_status_diagnostics_hide_paths(setup):
    setup({"정채은": "PERSON"})
    st = ner.ner_status()
    assert st["mode"] == "auto" and st["active"] is True
    assert set(st) == {"mode", "active", "fingerprint"}


def test_session_helper_still_closes_on_error(setup):
    _, session = setup({"정채은": "PERSON"}, mode="required")
    session.fail = True
    with pytest.raises(PrivacyUnavailable):
        prepare_text("정채은")
    with pytest.raises(PrivacyUnavailable), new_session(ASSISTANT) as s:
        s.prepare_text("정채은 또")


# ---------- 실모델(선택) ----------
REAL = os.environ.get("GABEE_NER_TEST_MODEL_DIR")


@pytest.mark.skipif(not REAL, reason="GABEE_NER_TEST_MODEL_DIR 가 없으면 건너뛴다")
def test_real_model_representative_sentences(monkeypatch):
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", REAL)
    monkeypatch.setattr(
        settings,
        "privacy_ner_model_file",
        os.environ.get("GABEE_NER_TEST_MODEL_FILE", "model.onnx"),
    )
    ner.reset()
    got = ner.detect_with_ner("내일 정채은이랑 서울시 강남구 테헤란로 152 근처에서 보자")
    values = {Kind.PERSON: [], Kind.ADDRESS: []}
    text = "내일 정채은이랑 서울시 강남구 테헤란로 152 근처에서 보자"
    for s in got:
        values.setdefault(s.kind, []).append(text[s.start : s.end])
    assert any("정채은" in v for v in values[Kind.PERSON])
    assert any("테헤란로" in v for v in values[Kind.ADDRESS])
    for neg in ("엄마한테 전화해줘", "운송장 번호 6012345678901 확인해줘"):
        assert not [s for s in ner.detect_with_ner(neg) if s.source == "ner"], neg
    ner.reset()


# ======================= 검토 반영(실서비스 보강) =======================
# ---------- prepare_json: 값마다가 아니라 한 번에 ----------
def test_prepare_json_infers_all_values_in_one_batch(setup):
    _, session = setup({"정채은": "PERSON"})
    data = {"items": [{"title": f"항목 {i}", "who": "정채은 님"} for i in range(300)], "n": 5}
    out, sess = prepare_json(data)
    assert session.rows == 301 and session.calls == -(
        -301 // ner.BATCH_SIZE
    )  # 값마다가 아니라 16창씩 묶어서
    assert out["items"][0]["who"] == "[PERSON_1] 님"
    sess.close()


def test_prepare_json_budget_auto_rules_only_for_excess_and_required_503(
    setup, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)
    _, session = setup({"정채은": "PERSON"})
    monkeypatch.setattr(ner, "BATCH_MAX_TEXTS", 3)
    data = [f"정채은 {i}번" for i in range(6)]
    out, sess = prepare_json(data)
    assert sum(t.startswith("[PERSON_1]") for t in out) == 3  # 예산 안의 글만 NER
    assert session.calls == 1
    assert "예산" in caplog.text and "정채은" not in caplog.text
    sess.close()
    setup({"정채은": "PERSON"}, mode="required")
    monkeypatch.setattr(ner, "BATCH_MAX_TEXTS", 3)
    with pytest.raises(PrivacyUnavailable):
        prepare_json(data)


def test_transcript_budget_uses_newest_lines_first(setup, monkeypatch):
    setup({"정채은": "PERSON"})
    monkeypatch.setattr(ner, "BATCH_MAX_TEXTS", 2)
    rows = [(i, "아빠", f"정채은 {i}번 줄") for i in range(5)]  # 마지막이 최신
    with prepare_transcript(rows, [], ANALYSIS) as prep:
        masked = [ln.text.startswith("[PERSON_1]") for ln in prep.lines]
    assert masked == [False, False, False, True, True]


# ---------- 에이전트 경로 fail-closed ----------
def test_new_session_required_blocks_before_any_external_call(monkeypatch):
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    ner.reset()
    posts: list[dict] = []
    with pytest.raises(PrivacyUnavailable):
        with new_session(ASSISTANT):  # 에이전트는 세션을 먼저 만든다
            run_agent("sys", [{"role": "user", "content": "q"}], [], post=posts.append)
    assert posts == []


def test_agent_tool_privacy_unavailable_is_not_swallowed(setup):
    _, session = setup({"정채은": "PERSON"}, mode="required")
    posts: list[dict] = []

    def post(body):
        posts.append(body)
        return {
            "content": [{"type": "tool_use", "id": "t1", "name": "look", "input": {}}],
            "usage": {},
        }

    sess = new_session(ASSISTANT)  # 이 시점엔 엔진이 정상
    session.fail = True  # 도구 실행 중에 추론이 실패한다
    tool = Tool("look", "d", {"type": "object"}, lambda a: sess.prepare_json({"x": "정채은"}))
    try:
        with pytest.raises(PrivacyUnavailable):
            run_agent("sys", [{"role": "user", "content": "q"}], [tool], post=post)
    finally:
        sess.close()
    assert len(posts) == 1  # 도구 결과를 모델로 돌려보내는 두 번째 호출은 없다


# ---------- 병합 확장 ----------
def test_wider_ner_address_widens_rule_spans(setup):
    setup({"부산 해운대구 우동 1234-5 101동 202호로": "ADDRESS"})
    text = "부산 해운대구 우동 1234-5 101동 202호로 보내"
    rule = detect(text)
    assert all(s.kind is Kind.ADDRESS for s in rule)
    merged = ner.detect_with_ner(text)
    assert [text[s.start : s.end] for s in merged] == ["부산 해운대구 우동 1234-5 101동 202호"]
    assert merged[0].score == max(s.score for s in rule)  # 규칙 점수 유지
    out, sess = prepare_text(text)
    assert out == "[ADDR_1]로 보내" and "우동" not in out and "1234" not in out
    sess.close()


def test_partial_overlap_adds_only_uncovered_pieces_and_keeps_rule_spans(setup):
    setup({"해운대구 우동 1234-5": "ADDRESS", "02-123-4567 앞": "ADDRESS"})
    text = "부산 해운대구 우동 1234-5 에서 02-123-4567 앞"
    rule = detect(text)
    merged = ner.detect_with_ner(text)
    for r in rule:  # 규칙 구간은 그대로 남는다
        assert r in merged
    got = [text[s.start : s.end] for s in merged]
    assert any("1234-5" in g for g in got)
    assert [s for s in merged if s.kind is Kind.PHONE] == [s for s in rule if s.kind is Kind.PHONE]
    spans = sorted((s.start, s.end) for s in merged)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))  # 겹치지 않는다


def test_high_confidence_rule_kinds_never_replaced(setup):
    setup({"010-1234-5678 으로": "PERSON", "900101-1234568": "ADDRESS"})
    text = "010-1234-5678 으로 보내, 주민 900101-1234568"
    rule = detect(text)
    merged = ner.detect_with_ner(text)
    for r in rule:
        assert r in merged


# ---------- NFC ----------
def test_nfd_hangul_is_recognised_and_positions_map_to_original(setup):
    engine, _ = make_engine({"정채은": "PERSON"})
    nfd = unicodedata.normalize("NFD", "어제 정채은 왔어")
    assert len(nfd) > len("어제 정채은 왔어")
    (span,) = engine.predict(nfd)
    assert nfd[span.start : span.end] == unicodedata.normalize("NFD", "정채은")
    assert ner._worth(nfd)
    setup({"정채은": "PERSON"})
    out, sess = prepare_text(nfd)
    assert "[PERSON_1]" in out and sess.restore_text(out).value == nfd
    sess.close()


# ---------- 동시 추론 수·시간 상한 ----------
def test_concurrency_limit_and_results_still_correct(setup):
    names = [f"{s}채은" for s in "김이박최정강조윤"]
    _, session = setup({n: "PERSON" for n in names})
    active = {"now": 0, "max": 0}
    real_run = session.run

    def run(outputs, feed):
        with session.lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        try:
            time.sleep(0.01)
            return real_run(outputs, feed)
        finally:
            with session.lock:
                active["now"] -= 1

    session.run = run
    bad: list[int] = []

    def work(i):
        text = f"{names[i % 8]} 안녕 {i}"
        out, sess = prepare_text(text)
        with sess:
            if out != f"[PERSON_1] 안녕 {i}":
                bad.append(i)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(work, range(80)))
    assert bad == [] and active["max"] <= 2


def test_queue_wait_timeout_auto_rules_only_required_503(setup, monkeypatch):
    setup({"정채은": "PERSON"})
    monkeypatch.setattr(ner, "QUEUE_WAIT_SECONDS", 0.05)
    text = "정채은 안녕"
    sem = ner._semaphore(2)
    sem.acquire()
    sem.acquire()  # 슬롯을 모두 점유
    try:
        assert ner.detect_with_ner(text) == detect(text)
        setup({"정채은": "PERSON"}, mode="required")
        monkeypatch.setattr(ner, "QUEUE_WAIT_SECONDS", 0.05)
        sem2 = ner._semaphore(2)
        sem2.acquire()
        sem2.acquire()
        try:
            with pytest.raises(PrivacyUnavailable):
                prepare_text(text)
        finally:
            sem2.release()
            sem2.release()
    finally:
        sem.release()
        sem.release()


def test_time_budget_exceeded(setup, monkeypatch):
    setup({"정채은": "PERSON"})
    monkeypatch.setattr(ner, "TIME_BUDGET_SECONDS", -1.0)
    text = "정채은 안녕"
    assert ner.detect_with_ner(text) == detect(text)
    setup({"정채은": "PERSON"}, mode="required")
    monkeypatch.setattr(ner, "TIME_BUDGET_SECONDS", -1.0)
    with pytest.raises(PrivacyUnavailable):
        prepare_text(text)


def test_burst_load_completes_with_correct_results(setup):
    names = [f"{s}채은" for s in "김이박최"]
    setup({n: "PERSON" for n in names})

    def work(i):
        rows = [
            (k, "아빠", f"{names[(i + k) % 4]} 이야기 {i}-{k} " + "가" * 200) for k in range(30)
        ]
        with prepare_transcript(rows, [], ANALYSIS) as prep:
            return all(ln.text.startswith("[PERSON_") for ln in prep.lines)

    t = time.perf_counter()
    with ThreadPoolExecutor(8) as pool:
        assert all(pool.map(work, range(16)))
    assert time.perf_counter() - t < 20


# ---------- 로드·무결성·미리 불러오기·로그 ----------
def write_model_dir(path, card_hashes=True, tamper=False):
    path.mkdir(parents=True, exist_ok=True)
    files = {"model.onnx": b"not-a-real-model", "tokenizer.json": b"{}", "labels.json": b"{}"}
    for name, data in files.items():
        (path / name).write_bytes(data)
    card = {"max_len": 128}
    if card_hashes:
        card["sha256"] = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
        if tamper:
            card["sha256"]["model.onnx"] = "0" * 64
    (path / "model_card.json").write_text(json.dumps(card), encoding="utf-8")


def test_integrity_mismatch_is_unavailable_auto_rules_required_503(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    d = tmp_path / "ner"
    write_model_dir(d, tamper=True)
    with pytest.raises(ner.ModelIntegrityError):
        ner.NerEngine.from_dir(d, "model.onnx", 1)
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(d))
    ner.reset()
    text = "정채은 씨 010-1234-5678"
    assert ner.detect_with_ner(text) == detect(text)
    assert "ModelIntegrityError" in caplog.text and str(d) not in caplog.text
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    ner.reset()
    with pytest.raises(PrivacyUnavailable):
        prepare_text(text)


def test_matching_hashes_pass_integrity_and_missing_hash_only_warns(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    d = tmp_path / "ner"
    write_model_dir(d)
    with pytest.raises(
        Exception
    ) as e:  # 가짜 모델 파일이라 이후 단계에서 실패하지만 무결성은 통과한다
        ner.NerEngine.from_dir(d, "model.onnx", 1)
    assert not isinstance(e.value, ner.ModelIntegrityError)
    d2 = tmp_path / "ner2"
    write_model_dir(d2, card_hashes=False)
    with pytest.raises(Exception) as e2:
        ner.NerEngine.from_dir(d2, "model.onnx", 1)
    assert not isinstance(e2.value, ner.ModelIntegrityError)
    assert "sha256 이 없어" in caplog.text


def test_preload_logs_fingerprint_without_path_and_never_raises(setup, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    setup({"정채은": "PERSON"}, fingerprint="abc123def456")
    t = ner.start_preload()
    assert t is not None
    t.join(5)
    assert ner.ner_status() == {"mode": "auto", "active": True, "fingerprint": "abc123def456"}
    assert "abc123def456" in caplog.text and "no-model" not in caplog.text
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    assert ner.start_preload() is None
    # 실패해도 예외 없이 로그만
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")

    def boom(cfg):
        raise RuntimeError("secret/dir")

    monkeypatch.setattr(ner, "_load_engine", boom)
    ner.reset()
    t = ner.start_preload()
    t.join(5)
    assert "secret" not in caplog.text and any(r.levelno >= logging.ERROR for r in caplog.records)


def test_auto_does_not_block_while_another_thread_loads(monkeypatch, setup):
    engine, _ = setup({"정채은": "PERSON"})
    started, release = threading.Event(), threading.Event()

    def slow_load(cfg):
        started.set()
        release.wait(5)
        return engine

    monkeypatch.setattr(ner, "_load_engine", slow_load)
    ner.reset()
    t = ner.start_preload()
    assert started.wait(5)
    text = "정채은 안녕"
    t0 = time.perf_counter()
    assert ner.detect_with_ner(text) == detect(text)  # 로드 중에는 기다리지 않고 규칙만
    assert time.perf_counter() - t0 < 1.0
    release.set()
    t.join(5)
    assert ner.detect_with_ner(text) != detect(text)


def test_lifespan_preload_hook_exists():
    import app.main as main

    assert main.privacy_ner is ner


@pytest.fixture
def real(monkeypatch):
    monkeypatch.setattr(settings, "privacy_ner_mode", "auto")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", REAL)
    monkeypatch.setattr(
        settings,
        "privacy_ner_model_file",
        os.environ.get("GABEE_NER_TEST_MODEL_FILE", "model.onnx"),
    )
    ner.reset()
    yield
    ner.reset()


@pytest.mark.skipif(not REAL, reason="GABEE_NER_TEST_MODEL_DIR 가 없으면 건너뛴다")
def test_real_prepare_json_many_small_strings_is_fast(real):
    """기존 성능 계약(test_freetext 의 같은 이름 시험)이 실모델 auto 에서도 지켜진다."""
    data = {
        "items": [{"title": f"항목 {i}", "who": "김민수", "amount": i * 100} for i in range(5000)]
    }
    ner.ner_status()  # 서버는 시작할 때 미리 불러온다(start_preload)
    sess = new_session(members=["김민수"])
    t = time.perf_counter()
    sess.prepare_json(data)
    assert time.perf_counter() - t < 3.0
    sess.close()


@pytest.mark.skipif(not REAL, reason="GABEE_NER_TEST_MODEL_DIR 가 없으면 건너뛴다")
def test_real_nfd_and_widening(real):
    nfd = unicodedata.normalize("NFD", "내일 정채은이랑 보자")
    out, sess = prepare_text(nfd)
    assert "정" not in unicodedata.normalize("NFC", out).replace("정말", "")
    sess.close()
    text = "부산 해운대구 우동 1234-5 101동 202호로 보내"
    out, sess = prepare_text(text)
    assert "우동" not in out and "1234" not in out
    sess.close()
