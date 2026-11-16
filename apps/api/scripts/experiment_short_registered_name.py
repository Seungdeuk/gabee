"""우선순위 1 실험: "등록된 1음절 이름"에 한해 길이 제한 예외를 뒀을 때의 효과(읽기 전용 시뮬레이션).

**먼저 확인한 사실(코드 읽기만, 수정 없음)**: 1음절 이름은 **NER 쪽**(`merge_ner` 의
"PERSON 2글자 미만 버림")뿐 아니라 **규칙 쪽**(`detectors._detect_person_known` 의
`len(name) < 2 or name in KINSHIP_TERMS: continue`, L573)에도 똑같은 길이 제한이 있다. 즉
`known_names`에 1음절 이름을 등록해도(가장 확실하다고 알려진 완화책), **현재는 등록 자체가 무시된다.**

이 스크립트는 그 가설을 실제로 확인하고(기존 코드 그대로 호출), "길이 제한을 등록 이름에 한해서만
풀면 어떻게 되는지"를 `detectors.py`를 전혀 수정하지 않고 **별도 함수로 복제·실험**한다(`_is_hangul`·
`_name_end_ok`·`_PARTICLES`·`KINSHIP_TERMS`·`COMMON_WORD_ALIASES`·`SURNAMES`는 기존 모듈에서 그대로
가져와 쓴다 — 로직을 새로 짜지 않고 길이 조건 한 줄만 뺀 사본이다).

측정: (1) 기존 코드 그대로(규칙 단독·통합) — 등록해도 보호되는지, (2) 실험 함수 — PERSON 문맥 recall과
비PERSON 문맥 과마스킹(오탐) 비용을 함께 본다. `ner.py`·`detectors.py`·모델 파일·DB·설정은 전혀 수정하지
않았다. 외부 LLM 미호출.

사용: ``python scripts/experiment_short_registered_name.py <서비스 모델 폴더> <R1 모델 폴더>``
(모델 폴더는 통합 경로 확인용 — 규칙 단독 실험 자체는 모델이 필요 없다)
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import detectors, ner  # noqa: E402
from app.shared.privacy.types import Kind, Span  # noqa: E402

EXPECT_FP12 = {"service": "46210943c45f", "r1_s7": "c536eadeb5a1"}


def has_batchim(ch: str) -> bool:
    return (ord(ch) - 0xAC00) % 28 != 0


def josa(word: str) -> str:
    return word + ("이" if has_batchim(word[-1]) else "가")


# ---- 테스트 문장(1음절 이름 2개: "별"은 48절 진단셋과 동일 문장을 재사용, "봄"은 이번에 새로 지음) ----
TEST_WORDS = ["별", "봄"]
PERSON_SENTENCES = {
    "별": [
        "별이 오늘 피아노 학원 다녀왔대",
        "어제 별한테 전화했는데 안 받더라",
        "우리 반에서 별이 제일 웃겨",
    ],
    "봄": [
        "봄이 오늘 피아노 학원 다녀왔대",
        "어제 봄한테 전화했는데 안 받더라",
        "우리 반에서 봄이 제일 웃겨",
    ],
}
NONPERSON_SENTENCES = {
    "별": [
        "별이 밤하늘에 빛났다",
        "별을 보며 소원을 빌었다",
        "별이 유난히 반짝였다",
    ],
    "봄": [
        "봄이 되니 날씨가 포근하다",
        "봄에는 꽃이 활짝 핀다",
        "봄바람이 살랑살랑 불었다",
    ],
}


def trial_detect_person_known_no_minlen(text: str, known_names: tuple[str, ...]) -> list[Span]:
    """`detectors._detect_person_known` 의 사본 — "len(name) < 2" 조건만 뺐다(등록 이름 전용 예외 실험).
    나머지 로직(조사 경계 처리 `_name_end_ok`, 성+이름 3글자 별칭, 친족어 제외)은 전부 그대로다."""
    entries: dict[str, tuple[str, float]] = {}
    for raw in known_names:
        name = " ".join(str(raw).split())
        if name in detectors.KINSHIP_TERMS:  # 원래의 "or len(name) < 2" 를 뺀 것이 유일한 차이
            continue
        entries[name] = (name, 0.9 if len(name) >= 3 else 0.75)
    for name in list(entries):
        if len(name) == 3 and name[0] in detectors.SURNAMES and all(detectors._is_hangul(c) for c in name):
            alias = name[1:]
            if alias not in entries and alias not in detectors.KINSHIP_TERMS and alias not in detectors.COMMON_WORD_ALIASES:
                entries[alias] = (name, 0.8)
    spans = []
    for name in sorted(entries, key=len, reverse=True):
        canonical, score = entries[name]
        pattern = re.compile(rf"(?<![가-힣A-Za-z0-9]){re.escape(name)}")
        for m in pattern.finditer(text):
            if detectors._name_end_ok(text, m.end()):
                spans.append(Span(Kind.PERSON, m.start(), m.end(), score, "name_dict_trial", canonical))
    return spans


def baseline_rule(text: str, word: str) -> list[Span]:
    return detectors.detect(text, known_names=(word,))


def baseline_integrated(text: str, word: str) -> list:
    return ner.detect_with_ner(text, known_names=(word,))


def run() -> dict:
    out = {}
    for word in TEST_WORDS:
        person_results = []
        for text in PERSON_SENTENCES[word]:
            base_rule = baseline_rule(text, word)
            trial = trial_detect_person_known_no_minlen(text, (word,))
            exact_base = any(s.kind is Kind.PERSON and text[s.start : s.end] == word for s in base_rule)
            exact_trial = any(text[s.start : s.end] == word for s in trial)
            person_results.append(
                {"text": text, "baseline_rule_found": exact_base, "trial_found": exact_trial, "trial_spans": [(s.start, s.end, round(s.score, 3)) for s in trial]}
            )
        nonperson_results = []
        for text in NONPERSON_SENTENCES[word]:
            base_rule = baseline_rule(text, word)
            trial = trial_detect_person_known_no_minlen(text, (word,))
            base_flagged = any(s.kind is Kind.PERSON for s in base_rule)
            trial_flagged = bool(trial)
            nonperson_results.append(
                {"text": text, "baseline_rule_flagged": base_flagged, "trial_flagged": trial_flagged, "trial_spans": [(s.start, s.end, round(s.score, 3)) for s in trial]}
            )
        out[word] = {"person": person_results, "nonperson": nonperson_results}
    return out


def run_integrated_baseline(model_key: str, model_dir: str) -> dict:
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = model_dir
    settings.privacy_ner_threads = 2
    status = ner.ner_status()
    fp12 = status["fingerprint"][:12]
    if EXPECT_FP12.get(model_key) and fp12 != EXPECT_FP12[model_key]:
        raise SystemExit(f"[{model_key}] 지문 불일치: got {fp12}")
    ner._cache.clear()
    out = {}
    for word in TEST_WORDS:
        found = []
        for text in PERSON_SENTENCES[word]:
            spans = baseline_integrated(text, word)
            exact = any(s.kind is Kind.PERSON and text[s.start : s.end] == word for s in spans)
            found.append({"text": text, "integrated_found_with_registration": exact})
        out[word] = found
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("service_model_dir")
    ap.add_argument("r1_model_dir")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rule_result = run()
    integrated_result = {
        "service": run_integrated_baseline("service", args.service_model_dir),
        "r1_s7": run_integrated_baseline("r1_s7", args.r1_model_dir),
    }

    print("=== 규칙 단독: 등록해도 현재 코드로는 보호되는가? (기대: 전부 False) ===")
    for word, r in rule_result.items():
        print(f" {word} baseline_rule_found:", [p["baseline_rule_found"] for p in r["person"]])
    print("\n=== 실험(길이 제한 예외): PERSON 문맥 recall ===")
    for word, r in rule_result.items():
        print(f" {word} trial_found:", [p["trial_found"] for p in r["person"]])
    print("\n=== 실험(길이 제한 예외): 비PERSON 문맥 과마스킹(새로 생기는 오탐) ===")
    for word, r in rule_result.items():
        print(f" {word} trial_flagged(비인명):", [n["trial_flagged"] for n in r["nonperson"]], "| baseline(원래도 없었음):", [n["baseline_rule_flagged"] for n in r["nonperson"]])
    print("\n=== 통합 경로(실제 운영 함수 그대로)에서도 등록이 무시되는지 ===")
    for key, words in integrated_result.items():
        for word, items in words.items():
            print(f" [{key}] {word}:", [i["integrated_found_with_registration"] for i in items])

    out_path = args.out or (ROOT / "app" / "shared" / "privacy" / "eval" / "experiment_short_registered_name_results.json")
    out_path.write_text(json.dumps({"rule_experiment": rule_result, "integrated_baseline": integrated_result}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
