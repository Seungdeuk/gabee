# NER 문체별 평가셋 v4 + 공통 검증 기준(로드맵 1단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 서비스 모델(KoELECTRA-small v2b, KLUE-NER 10%)과 AI-Hub 교체 실험 모델(v2b-aihub)을 **같은 새 문체별 평가셋**에서 동일 기준(Precision/Recall/F1, 문체별 이름 누출, 오탐률, CPU 지연)으로 비교하고, 그 결과를 `docs/security/NER_VALIDATION.md`와 비교 아티팩트에 반영한다. 로드맵 1단계("공통 검증 기준 확정")만 다룬다 — 재학습·모델 교체는 하지 않는다.

**Architecture:** 저장소 밖 `gabee-ner-evalset-v3`(488문장)는 2026-11-03에 두 모델을 이미 1회 평가해 "소비됨"으로 간주하기로 했으므로, 같은 생성 로직을 저장소 **안**에 다시 구현해(`apps/api/app/shared/privacy/eval/style_v4/`) 완전히 새 이름·새 문장으로 평가셋 v4를 만든다. 제외 집합은 학습 풀(`ml/ner/data/synth.py`) + `baseline_v2`(전체 분할) + 옛 v3(`evalset_v3.jsonl`, 이름만 참고, 재사용 아님) 세 곳의 이름을 모두 합친다. 평가 실행기(`apps/api/scripts/eval_style_set.py`)는 서비스 실제 경로(`detect_with_ner`)를 호출해 문체별 커버리지(full/partial/none)와 100자 기준 지연을 함께 낸다. 모델 파일 자체(`gabee-model-delivery/*`)는 그대로 저장소 밖에 둔다.

**Tech Stack:** Python(apps/api/.venv), onnxruntime/tokenizers/numpy(이미 선언된 의존성, 추가 없음), pytest.

**Spec:** 사용자 지시(이 대화의 로드맵 1~5단계, 평가 규칙, 제약 — 별도 문서 없음). 참고 선례: `C:\Users\403\Documents\gabee-ner-evalset-v3\{build_evalset_v3.py, evaluate_v3.py, README.md}`, `apps/api/app/shared/privacy/eval/baseline_v2/`, `apps/api/scripts/eval_integration.py`, `ml/ner/export/bench_onnx.py`.

## Global Constraints

- 서버에 torch를 새로 넣지 않는다. 평가는 `onnxruntime`/`tokenizers`/`numpy`만 쓴다(이미 선언됨, 새 의존성 추가 금지).
- 실제 가족 대화·개인 데이터는 쓰지 않는다. 평가셋 v4는 전부 합성.
- AI-Hub 원문·변환본·모델 가중치(`gabee-model-delivery/*`)는 Git에 올리지 않는다. 평가 **결과** 수치(json/csv, 개인정보 없음)는 저장소에 커밋해도 된다.
- 새 평가셋은 학습 풀·`baseline_v2`·`evalset_v3`의 이름(given name)·문장 틀(skeleton)과 하나라도 겹치면 생성이 **실패**해야 한다(assert → 0이 아닌 종료 코드).
- 브랜치는 `feature/seungdeuk-ner-improve`(이미 체크아웃됨)에서 계속한다. PR 생성·병합은 사용자가 요청할 때만.
- 공용 DB·개인 DB 접속 없음(이 작업은 DB를 쓰지 않는다).
- 새 코드(생성기·제외집합·평가기)는 각각 최소 테스트 1개.

## Review Focus

1. **제외 집합 불완전**: `baseline_v2`의 `train.jsonl`뿐 읽고 `val/test`를 빠뜻리면 그 분할의 이름이 v4에 다시 나올 수 있다 — 세 파일 모두 스캔하는지 테스트로 확인(Task 1).
2. **겹침 검사가 조용히 통과**: 이름이나 문장 틀이 실제로 겹쳤는데도 assert가 느슨해 그냥 파일이 써지면 "새 평가셋"이 아니게 된다 — 겹치는 사례를 강제로 주입해 `SystemExit`이 나는지 테스트(Task 2).
3. **PRIVACY_NER_MODE=off로 잘못 측정**: 환경변수를 안 맞추면 평가기가 조용히 규칙만 쓰고 "모델 성능"처럼 보고될 수 있다 — `ner_status().active`가 `True`인지 평가기가 확인하고, 아니면 에러로 멈추게 한다(Task 4).
4. **모델 지문 혼동**: 두 모델(v2b/v2b-aihub) 결과 파일에 어느 모델을 쟀는지 지문이 안 남으면 나중에 뒤섞인다 — `ner_status()["fingerprint"]`를 결과 json에 항상 기록(Task 4, 5).
5. **비인명 문장의 과마스킹 회귀를 못 봄**: v3에서 "하늘/바다/기쁨/초원" 과마스킹이 있었는데 v4가 비슷한 일반어를 안 포함하면 같은 문제를 재현 못 한다 — v4 비인명 문장에 그런 종류의 일반어를 포함시킨다(Task 2 작성 시 반영, 코드로 강제하는 테스트는 아님—작성 체크리스트).

---

### Task 1: 제외 집합 모듈

**Files:**
- Create: `apps/api/app/shared/privacy/eval/style_v4/exclusions.py`
- Test: `apps/api/app/shared/privacy/eval/style_v4/tests/test_exclusions.py`
- Create: `apps/api/app/shared/privacy/eval/style_v4/tests/__init__.py` (빈 파일, 패키지 인식용)

**Interfaces:**
- Produces: `collect_excluded_names(synth_path: Path, baseline_dirs: list[Path], extra_eval_paths: list[Path]) -> set[str]` — 학습 풀(`synth.py`의 `GIVEN1`/`GIVEN2` 정규식 추출, `build_evalset_v3.py`의 `training_given_names`와 같은 방식) + `baseline_dirs`의 모든 `*.jsonl`에서 `PERSON`/`PERSON_ALIAS` span 문자열 + `extra_eval_paths`의 모든 jsonl에서 같은 방식으로 뽑은 PERSON span 문자열을 합친 집합을 돌려준다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_collect_excluded_names_scans_all_baseline_splits_and_extra(tmp_path):
    synth = tmp_path / "synth.py"
    synth.write_text('GIVEN2 = ("가나다 라마바")\nGIVEN1 = list("사")\n', encoding="utf-8")
    base_dir = tmp_path / "baseline_v2"
    base_dir.mkdir()
    (base_dir / "train.jsonl").write_text(
        '{"text": "김철수님", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}\n', encoding="utf-8"
    )
    (base_dir / "val.jsonl").write_text(
        '{"text": "이영희씨", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}\n', encoding="utf-8"
    )
    (base_dir / "test.jsonl").write_text(
        '{"text": "박민수가", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}\n', encoding="utf-8"
    )
    v3 = tmp_path / "evalset_v3.jsonl"
    v3.write_text(
        '{"text": "최지은 대표", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}\n', encoding="utf-8"
    )

    excluded = collect_excluded_names(synth, [base_dir], [v3])

    assert "가나다" in excluded or "라마바" in excluded  # GIVEN2 토큰
    assert "사" in excluded  # GIVEN1
    assert "김철수" in excluded  # train
    assert "이영희" in excluded  # val — 빠지면 실패해야 하는 지점
    assert "박민수" in excluded  # test
    assert "최지은" in excluded  # v3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe -m pytest app/shared/privacy/eval/style_v4/tests/test_exclusions.py -v`
Expected: FAIL(`ModuleNotFoundError`/`ImportError`: `exclusions` 없음)

- [ ] **Step 3: `exclusions.py` 구현**

`build_evalset_v3.py:148-162`의 `training_given_names`를 거의 그대로 가져오되, `baseline_dirs`를 리스트로 받아 여러 폴더를 돌고, `extra_eval_paths`(옛 v3 jsonl 등 임의 경로)도 같은 방식으로 PERSON/PERSON_ALIAS span 문자열을 더한다. 파일이 없으면(`extra_eval_paths`가 존재하지 않는 경로) `FileNotFoundError`를 그대로 올린다(조용히 건너뛰지 않는다 — Review Focus 1).

- [ ] **Step 4: 테스트 통과 확인**

Run: 위와 같은 명령
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add apps/api/app/shared/privacy/eval/style_v4/exclusions.py apps/api/app/shared/privacy/eval/style_v4/tests/
git commit -m "feat: NER 평가셋 v4 제외 집합 모듈(학습풀+baseline_v2+v3 이름)"
```

---

### Task 2: 평가셋 v4 생성기

**Files:**
- Create: `apps/api/app/shared/privacy/eval/style_v4/build_evalset.py`
- Test: `apps/api/app/shared/privacy/eval/style_v4/tests/test_build_evalset.py`
- Create: `apps/api/app/shared/privacy/eval/style_v4/README.md`

**Interfaces:**
- Consumes: Task 1의 `collect_excluded_names`.
- Produces:
  - `SURNAMES: list[str]`, `GIVEN_CANDIDATES: list[str]` — `build_evalset_v3.py:18-27`과 동일한 이름 풀을 그대로 복사해 상수로 둔다(제외 집합이 넓어졌으니 실제 쓰이는 이름은 자동으로 줄어든다).
  - `TEMPLATES: dict[str, list[str]]` — 9개 문체(가족대화/배송수령/명단목록/공문안내/기사체/호칭조사/이름만/주소/비인명)별로 `build_evalset_v3.py`의 틀과 **글자 그대로 같지 않은** 새 문장 틀. 비인명 문장에는 "하늘/바다/기쁨/초원"처럼 과마스킹 이력이 있는 일반어 계열을 최소 4개 포함한다(Review Focus 5).
  - `assert_no_overlap(rows: list[dict], excluded_names: set[str], template_texts: set[str]) -> None` — 생성된 각 행의 PERSON span 문자열이 `excluded_names`에 있거나, 문장에서 이름을 뺀 "틀"(기존 `build_evalset_v3.py`와 같은 방식으로 정규화한 뼈대)이 `template_texts`(학습·baseline_v2·v3의 문장에서 뽑은 뼈대 집합, 같은 함수가 같이 계산)와 같으면 `SystemExit(1)`을 올린다. 메시지에 어떤 이름/틀이 겹쳤는지 적는다.
  - CLI `main()`: `--synth`, `--baseline`(nargs="*"), `--v3`, `--out`, `--seed`(기본 `20261112`), `--per-template`(기본 `7`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_assert_no_overlap_fails_on_shared_name():
    rows = [{"category": "가족대화", "text": "김철수가 왔어", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}]
    with pytest.raises(SystemExit):
        assert_no_overlap(rows, excluded_names={"김철수"}, template_texts=set())

def test_assert_no_overlap_passes_on_fresh_name():
    rows = [{"category": "가족대화", "text": "최유일이 왔어", "spans": [{"kind": "PERSON", "start": 0, "end": 3}]}]
    assert_no_overlap(rows, excluded_names={"김철수"}, template_texts=set())  # 예외 없이 통과
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe -m pytest app/shared/privacy/eval/style_v4/tests/test_build_evalset.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: `build_evalset.py` 구현**

`build_evalset_v3.py`의 `render`/`has_batchim`/`JOSA` 패턴(파일 전체 로직, `build_evalset_v3.py:123-145`)을 그대로 쓰고, `TEMPLATES`만 새로 쓴 문장으로 교체한다. `assert_no_overlap`은 Task 1의 제외 집합과, 별도로 계산한 "문장 틀 뼈대 집합"(학습 `synth.py`의 템플릿 문자열 + `baseline_v2` 전체 분할 + 옛 v3 jsonl의 문장을 이름 부분만 `{NAME}`로 바꾼 정규화 문자열)을 받아 비교한다. 겹치면 어떤 이름/어떤 틀인지 stderr에 적고 `SystemExit(1)`.

- [ ] **Step 4: 테스트 통과 확인**

Run: 위와 같은 명령
Expected: PASS

- [ ] **Step 5: README.md 작성**

v3의 `README.md` 구조(용도, 구성 표, 겹치지 않게 한 방법, 쓰는 법)를 따라 v4용으로 쓴다. "이 평가셋은 로드맵 1~4단계의 devset이고, 5단계 최종 독립 테스트에는 쓰지 않는다"를 명시한다.

- [ ] **Step 6: 커밋**

```bash
git add apps/api/app/shared/privacy/eval/style_v4/build_evalset.py apps/api/app/shared/privacy/eval/style_v4/tests/test_build_evalset.py apps/api/app/shared/privacy/eval/style_v4/README.md
git commit -m "feat: NER 평가셋 v4 생성기(문체 9종, 겹침 검사 포함)"
```

---

### Task 3: 평가셋 v4 생성 실행

**Files:**
- Create (실행 산출물): `apps/api/app/shared/privacy/eval/style_v4/evalset_v4.jsonl`

**Interfaces:**
- Consumes: Task 2의 `build_evalset.py` CLI.

- [ ] **Step 1: 생성 실행**

Run (저장소 루트에서, 워크트리 `C:\Users\403\Documents\gabee-ner`):
```
cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe app/shared/privacy/eval/style_v4/build_evalset.py \
  --synth ../../ml/ner/data/synth.py \
  --baseline app/shared/privacy/eval/baseline_v2 \
  --v3 "C:\Users\403\Documents\gabee-ner-evalset-v3\evalset_v3.jsonl" \
  --out app/shared/privacy/eval/style_v4/evalset_v4.jsonl
```
Expected: 종료 코드 0, stdout에 `sentences`·`by_category`·`excluded_names` 등 통계 json 출력(`build_evalset_v3.py:211`과 같은 형식).

- [ ] **Step 2: 분포 확인**

문장 수(목표: 488 전후, 문체 9종 × 설계한 틀 수 × `--per-template`)와 문체별 분포가 README에 적은 설계값과 일치하는지 눈으로 확인하고 README의 표를 실제 숫자로 채운다.

- [ ] **Step 3: 커밋**

```bash
git add apps/api/app/shared/privacy/eval/style_v4/evalset_v4.jsonl apps/api/app/shared/privacy/eval/style_v4/README.md
git commit -m "chore: NER 평가셋 v4 생성(합성 데이터만)"
```

---

### Task 4: 평가 실행기(`eval_style_set.py`)

**Files:**
- Create: `apps/api/scripts/eval_style_set.py`
- Test: `apps/api/tests/test_eval_style_set.py`

**Interfaces:**
- Consumes: `app.shared.privacy.ner.detect_with_ner`, `app.shared.privacy.ner.ner_status`, `app.shared.privacy.detectors.detect`.
- Produces:
  - `score_rows(rows: list[dict], predict: Callable[[str, tuple[str, ...]], list[Span]]) -> dict` — `evaluate_v3.py:23-47`의 full/partial/none·과마스킹 집계 로직을 그대로 가져와 함수로 분리한 것(카테고리별 `spans/full/partial/none/sentences/flagged`, `person_total`).
  - `measure_latency(rows: list[dict], predict: Callable[[str], Any], *, char_len: int = 100, n: int = 105) -> dict` — `ml/ner/export/bench_onnx.py:50-65`의 `make_texts`와 같은 방식으로 `rows`의 텍스트를 이어 붙여 100자 문장을 만들고, `predict`를 호출해 median/P95 ms를 돌려준다(`bench_onnx.py:68-75`의 `stats`와 같은 형식: `{"median_ms", "p95_ms", "n"}`).
  - CLI `main()`: `python eval_style_set.py <evalset.jsonl> <model_dir_or_off> <out.json>`. `model_dir_or_off`가 `off`면 `PRIVACY_NER_MODE=off`로 규칙만, 그 외는 `PRIVACY_NER_MODEL_DIR`에 넣고 `PRIVACY_NER_MODE=required`·`PRIVACY_NER_THREADS=2`로 설정한 뒤 `ner.ensure_ready()`를 부른다. **`ner.ner_status()["active"]`가 `False`이면 `SystemExit(1)`**(Review Focus 3). 결과 json에 `ner_status()`(지문 포함, Review Focus 4)와 `score_rows`·`measure_latency` 결과를 함께 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_score_rows_counts_full_partial_none():
    rows = [{"category": "가족대화", "text": "김철수가 왔어", "spans": [{"kind": "PERSON", "start": 0, "end": 3}], "known_names": []}]

    def predict_full(text, known):
        return [Span(Kind.PERSON, 0, 3, 0.9, "ner")]

    out = score_rows(rows, predict_full)
    assert out["categories"]["가족대화"]["full"] == 1
    assert out["categories"]["가족대화"]["none"] == 0

def test_eval_style_set_rejects_inactive_ner(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIVACY_NER_MODE", "off")
    evalset = tmp_path / "e.jsonl"
    evalset.write_text('{"text": "x", "spans": [], "known_names": [], "category": "비인명"}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(evalset), str(tmp_path / "missing-model-dir"), str(tmp_path / "out.json")])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_eval_style_set.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: `eval_style_set.py` 구현**

`evaluate_v3.py`(전체 49줄) + `bench_onnx.py`의 `make_texts`/`stats`를 가져와 하나의 스크립트로 합친다. `model_dir_or_off`가 `off`가 아닌데 모델 디렉터리가 없거나 `ner_status()["active"]`가 `False`면 `SystemExit(1)`로 멈춘다.

- [ ] **Step 4: 테스트 통과 확인**

Run: 위와 같은 명령(두 번째 테스트는 모델 디렉터리가 없어 required 모드 로드가 실패하는 경로로 `SystemExit`을 검증하므로 실제 ONNX 모델이 필요 없다).
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add apps/api/scripts/eval_style_set.py apps/api/tests/test_eval_style_set.py
git commit -m "feat: 문체별 평가셋 실행기(커버리지+100자 CPU 지연, 서비스 경로)"
```

---

### Task 5: 세 가지 방식 실행(규칙만 / KLUE10% / AIHub10%)

**Files:**
- Create (실행 산출물): `apps/api/app/shared/privacy/eval/style_v4/results/eval_off.json`, `eval_klue10.json`, `eval_aihub10.json`

**Interfaces:**
- Consumes: Task 4의 `eval_style_set.py` CLI, `gabee-model-delivery/ner-koelectra-small-v2b`(sha256 `46210943c45f...`), `gabee-model-delivery/ner-koelectra-small-v2b-aihub`(sha256 `901642391c50...`).

- [ ] **Step 1: 규칙만 실행**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe scripts/eval_style_set.py app/shared/privacy/eval/style_v4/evalset_v4.jsonl off app/shared/privacy/eval/style_v4/results/eval_off.json`
Expected: 종료 코드 0.

- [ ] **Step 2: KLUE10%(v2b) 실행**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe scripts/eval_style_set.py app/shared/privacy/eval/style_v4/evalset_v4.jsonl "C:\Users\403\Documents\gabee-model-delivery\ner-koelectra-small-v2b" app/shared/privacy/eval/style_v4/results/eval_klue10.json`
Expected: 종료 코드 0, 결과 json의 `ner_status.fingerprint`가 `46210943c45f`로 시작.

- [ ] **Step 3: AIHub10%(v2b-aihub) 실행**

Run: `cd apps/api && PYTHONPATH=. .venv/Scripts/python.exe scripts/eval_style_set.py app/shared/privacy/eval/style_v4/evalset_v4.jsonl "C:\Users\403\Documents\gabee-model-delivery\ner-koelectra-small-v2b-aihub" app/shared/privacy/eval/style_v4/results/eval_aihub10.json`
Expected: 종료 코드 0, `ner_status.fingerprint`가 `901642391c50`로 시작.

- [ ] **Step 4: 커밋**

```bash
git add apps/api/app/shared/privacy/eval/style_v4/results/
git commit -m "chore: 평가셋 v4 결과(규칙만/KLUE10%/AIHub10%)"
```

---

### Task 6: 문서 정정 + 공통 비교표

**Files:**
- Modify: `docs/security/NER_VALIDATION.md`(8절, 9절)

**Interfaces:**
- Consumes: Task 5의 세 결과 json, 기존 `docs/security/NER_VALIDATION.md` 8절(현재 "결정: KoELECTRA 구조 유지 + AI Hub 데이터 교체"로 돼 있음 — 조사에서 확인).

- [ ] **Step 1: 8절 정정**

"결정: KoELECTRA 구조 유지 + AI Hub 데이터 교체"를 "**보류**(2026-11-12 정정) — 이전(KLUE-NER 10%) 모델 유지. 근거: 문체별 평가셋에서 AI-Hub 교체 모델의 기사체 이름 누출이 늘었다(옛 v3: 0/56→12/56, v4 재확인: 아래 표)"로 바꾸고, 옛 결론이 좁은 평가셋(가족 대화 문체만)에 기반했다는 것을 한 줄로 남긴다.

- [ ] **Step 2: 공통 비교표 추가**

Task 5의 세 json(`eval_off/klue10/aihub10`)에서 문체별 full/partial/none, `person_total`, latency(`measure_latency`의 `e2e`/`median_ms`/`p95_ms`)를 표로 옮긴다. 출처는 "evalset v4(이 PR), 2026-11-12"로 명시하고, 과거 180문장·옛 v3 수치는 "참고(과거, 재사용 안 함)"로 구분해 같이 둔다.

- [ ] **Step 3: 9절(미완료 항목) 갱신**

로드맵 2~5단계를 항목으로 추가(아직 안 함으로 표시).

- [ ] **Step 4: 커밋**

```bash
git add docs/security/NER_VALIDATION.md
git commit -m "docs: AI-Hub 교체 결정 정정 + 평가셋 v4 공통 비교표"
```

---

### Task 7: 비교 아티팩트 발행

**Files:** 없음(저장소 파일 변경 없음, Artifact 도구로 발행).

**Interfaces:**
- Consumes: Task 5의 세 결과 json.

- [ ] **Step 1: 시각화 아티팩트 작성**

문체별 이름 누출(규칙만/KLUE10%/AIHub10% 막대), latency 비교, "기사체" 칸을 강조 표시한 표를 포함한 HTML 아티팩트를 `dataviz` 스킬 가이드에 따라 만든다.

- [ ] **Step 2: 발행**

Artifact 도구로 `publish`하고 링크를 사용자에게 보고한다.

---

## Self-Review 메모

- **스펙 커버리지**: 로드맵 1단계(공통 비교: Task 1-6), 비교 아티팩트 요구(Task 7) 모두 과업으로 연결됨. 2~5단계는 이 계획 범위 밖(별도 계획).
- **타입 일관성**: `collect_excluded_names`(Task1) → `assert_no_overlap`(Task2)이 받는 `excluded_names` 타입(`set[str]`) 일치. `score_rows`/`measure_latency`(Task4) 시그니처는 Task5의 CLI 사용과 일치.
- **비례**: 생성기·평가기 본문은 기존 v3 스크립트를 거의 그대로 옮기는 것이라 단계별로 "어디서 가져오는지"만 적었고 전체 로직을 다시 베끼지 않았다.
