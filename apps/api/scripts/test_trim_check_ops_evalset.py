"""평가셋 수량 맞춤·자동 품질 검증 도구 시험(합성 행, 모델 없음)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ops_evalset as chk  # noqa: E402
import trim_r11_evalset as tr  # noqa: E402

PERSON_TYPES = ("A1", "A3", "B1", "B2", "C1", "C2", "D3", "NEWNAME", "LONGNAME", "ORGLOC_MIX")
NO_PERSON = ("D2", "A3N", "GENERIC", "OTHER")


def make_rows(spare=1.1):
    rows = []
    for ty, n in tr.FINAL.items():
        for i in range(int(n * spare) + (1 if spare > 1 else 0)):
            name = f"가나{ty}{i:04d}"
            text = f"{ty} 문장 {i} 번째에서 {name} 이(가) 왔다" if ty in PERSON_TYPES else f"{ty} 음성 문장 {i} 번째 내용"
            r = {"id": f"{ty}-{i}", "text": text, "primary_stress_type": ty, "spans": []}
            if ty in PERSON_TYPES:
                s = text.index(name)
                r["spans"] = [{"start": s, "end": s + len(name), "kind": "PERSON"}]
            rows.append(r)
    for k in range(int(tr.PAIRS_FINAL * spare) + (1 if spare > 1 else 0)):
        w = f"단어{k // 3:03d}"
        person = f"쌍{k:04d} 사람 문장에서 {w}가 도착"
        s = person.index(w)
        rows.append({"id": f"P{k}-p", "text": person, "primary_stress_type": "D1P", "pair_id": f"pr{k}", "role": "person", "pair_word": w, "spans": [{"start": s, "end": s + len(w), "kind": "PERSON"}]})
        rows.append({"id": f"P{k}-n", "text": f"쌍{k:04d} 명사 문장 {w} 가격", "primary_stress_type": "D1", "pair_id": f"pr{k}", "role": "noun", "pair_word": w, "spans": []})
    return rows


def test_trim_reaches_exact_quotas_deterministically_and_keeps_pairs():
    rows = make_rows()
    kept, removed, errors = tr.trim(rows)
    assert errors == [] and len(kept) == 2350
    kept2, removed2, _ = tr.trim(list(reversed(rows)))
    assert {r["id"] for r in kept} == {r["id"] for r in kept2} and removed == removed2
    ids = {r["id"] for r in kept}
    for k in range(331):
        assert (f"P{k}-p" in ids) == (f"P{k}-n" in ids)
    assert sum(1 for r in kept if r["primary_stress_type"] == "D1P") == 300


def test_trim_removes_flagged_ids_first_and_stops_when_short():
    rows = make_rows()
    flagged = ["B1-0", "B1-1", "P0-p"]
    kept, removed, errors = tr.trim(rows, prefer_drop=flagged)
    ids = {r["id"] for r in kept}
    assert errors == [] and not ({"B1-0", "B1-1", "P0-p", "P0-n"} & ids)
    short = [r for r in rows if not (r["primary_stress_type"] == "OTHER" and int(r["id"].split("-")[1]) >= 40)]
    kept2, _, errors2 = tr.trim(short)
    assert kept2 == [] and any(e.startswith("OTHER") for e in errors2)


def test_check_marks_clean_set_sealable_by_automatic_checks_but_not_semantic(tmp_path):
    kept, _, _ = tr.trim(make_rows())
    data = tmp_path / "d.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    info, problems = chk.analyze(kept)
    assert problems == [] and info["pairs"] == 300
    rc = chk.main(["--data", str(data), "--out-dir", str(tmp_path / "out"), "--skip-validator"])
    rep = json.loads((tmp_path / "out" / "ops_evalset_check.json").read_text(encoding="utf-8"))
    assert rc == 0 and rep["sealable_by_automatic_checks"] and rep["S1600"]["available"] and rep["S1600"]["rows"] == 1600
    assert rep["human_review"] == "미실시" and "라벨 의미의 정확성" in rep["not_verified"][0]


def test_check_fails_on_wrong_counts_and_unknown_type(tmp_path):
    kept, _, _ = tr.trim(make_rows())
    bad = [r for r in kept if r["id"] != "B1-3"] + [{"id": "X-1", "text": "음성", "primary_stress_type": "XYZ", "spans": []}]
    info, problems = chk.analyze(bad)
    assert any("B1" in p for p in problems) and any("XYZ" in p for p in problems)


def test_name_role_leak_candidates_ignore_same_pair_noun_sentence():
    rows = [{"id": "a", "text": "민준이가 왔다", "primary_stress_type": "A1", "spans": [{"start": 0, "end": 2, "kind": "PERSON"}]},
            {"id": "b", "text": "민준 이름이 적힌 상자", "primary_stress_type": "GENERIC", "spans": []},
            {"id": "p1", "text": "도라지가 도착", "primary_stress_type": "D1P", "pair_id": "q", "role": "person", "pair_word": "도라지", "spans": [{"start": 0, "end": 3, "kind": "PERSON"}]},
            {"id": "n1", "text": "도라지 가격", "primary_stress_type": "D1", "pair_id": "q", "role": "noun", "pair_word": "도라지", "spans": []}]
    info, _ = chk.analyze(rows)
    assert info["name_role_leak_candidates"]["ids"] == ["b"]
