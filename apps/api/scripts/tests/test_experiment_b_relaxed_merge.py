"""실험 B(병합 완화, `decode_relaxed`)의 단위 시험 — NER_VALIDATION.md 60~62절에서 실제로 확인한
토큰 패턴을 그대로 재현해 고정한다. 순수 함수라 ONNX·tokenizer 없이 토큰(start,end,tag,prob)
튜플을 직접 넣는다. 아직 운영 코드(`ner.py`)에는 적용되지 않은 **실험 중인 로직**의 시험이다
(채택 결정 전까지는 이 파일이 "현재 실험 구현이 의도대로 동작하는가"만 보장한다).

실행: 이 폴더는 `apps/api/pyproject.toml`의 기본 `testpaths = ["tests", "app"]`에 포함되지
않으므로 운영 CI가 자동으로 돌리지 않는다 — 수동으로 ``pytest apps/api/scripts/tests`` 로 돈다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_b_relaxed_merge import decode_relaxed  # noqa: E402


def test_same_label_continuation_still_merges_like_before():
    """기존 디코딩과 똑같이 동작해야 하는 기본 사례(라벨이 계속 같음)."""
    toks = [(0, 1, "B-PERSON", 0.9), (1, 2, "I-PERSON", 0.9), (2, 3, "I-PERSON", 0.9)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 3, 0.9)]


def test_merges_person_then_person_alias_adjacent_tokens():
    """60절 "부뚜막" 패턴: B-PERSON/I-PERSON_ALIAS/I-PERSON — 라벨 이름은 흔들리지만 전부 PERSON
    계열이라 완화 규칙으로 하나의 span 이 돼야 한다(원래 디코딩은 두 번째 토큰에서 끊긴다)."""
    toks = [(0, 1, "B-PERSON", 0.76), (1, 2, "I-PERSON_ALIAS", 0.49), (2, 3, "I-PERSON", 0.79)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 3, (0.76 + 0.49 + 0.79) / 3)]


def test_does_not_bridge_a_true_o_gap():
    """60절 "나룻배" 패턴: B-PERSON/O/I-PERSON — 가운데가 진짜 "O"면 완화 규칙도 못 잇는다(두 개의
    1토큰 조각으로 남는다 — merge_ner 의 길이<2 필터에 어차피 걸리는 것과 별개로, 디코딩 단계에서는
    이렇게 쪼개진다는 걸 고정한다)."""
    toks = [(0, 1, "B-PERSON", 0.83), (1, 2, "O", 0.36), (2, 3, "I-PERSON", 0.74)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 1, 0.83), ("PERSON", 2, 3, 0.74)]


def test_isolated_entity_token_between_o_tokens_stays_single_token():
    """60절 "책꽂이" 패턴: O/I-PERSON_ALIAS/O — 앞뒤가 전부 "O"면 가운데 1토큰만 남는다(이어붙일
    인접 PERSON 계열 토큰 자체가 없으므로 완화 규칙이 할 수 있는 게 없다)."""
    toks = [(0, 1, "O", 0.56), (1, 2, "I-PERSON_ALIAS", 0.52), (2, 3, "O", 0.97)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON_ALIAS", 1, 2, 0.52)]


def test_b_tag_always_starts_a_new_span_even_in_the_same_group():
    """인접 엔티티 안전성의 핵심: 두 번째 개체가 "I-"가 아니라 "B-"로 새로 시작하면, 같은 그룹
    (PERSON/PERSON_ALIAS)이라도 이어붙이지 않는다 — 62절에서 확인한 "서로 다른 두 사람이 각자
    B- 로 시작하면 합쳐지지 않는다"는 안전성이 이 조건에서 나온다. (두 span 모두 PERSON 계열
    연속 병합을 거쳤으므로 라벨은 둘 다 "PERSON"으로 통일되지만, 경계(0,2)/(2,4)는 분리된다.)"""
    toks = [(0, 1, "B-PERSON", 0.9), (1, 2, "I-PERSON", 0.9), (2, 3, "B-PERSON_ALIAS", 0.9), (3, 4, "I-PERSON_ALIAS", 0.9)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 2, 0.9), ("PERSON", 2, 4, 0.9)]


def test_does_not_merge_across_a_different_label_group():
    """PERSON 계열이 아닌 라벨(ORGANIZATION 등)은 완화 그룹에 안 들어가므로 이어붙지 않는다."""
    toks = [(0, 1, "B-PERSON", 0.9), (1, 2, "I-ORGANIZATION", 0.9)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 1, 0.9), ("ORGANIZATION", 1, 2, 0.9)]


def test_merged_score_is_the_average_like_original_decode():
    """병합된 구간의 점수는 기존 `ner.py` `_decode`와 같은 방식(토큰 확률의 평균)이어야 한다 —
    61절에서 본 "반디"(평균 0.45로 신뢰도 임계값에 걸림) 사례가 이 평균 계산에서 나온다."""
    toks = [(0, 1, "B-PERSON_ALIAS", 0.44), (1, 2, "I-PERSON", 0.46)]
    spans = decode_relaxed(toks)
    assert spans == [("PERSON", 0, 2, (0.44 + 0.46) / 2)]
