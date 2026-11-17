"""가명화 파이프라인 실사용 중심 점검(2026-11-17 요청) — 읽기 전용, 실제 Claude API 호출 없음.

family_chat 경로가 실제로 쓰는 `gateway.prepare_transcript`(ANALYSIS 정책)를 그대로 호출해 "외부 LLM에
보내지는 최종 문자열"을 직접 확인한다. 이름·별명은 전부 가상 데이터다. 운영 모델·운영 코드는 전혀
수정하지 않는다(이 스크립트는 기존 공개 API만 호출).

두 조건을 비교한다:
  A) 규칙+가족 이름 사전만(NER 꺼짐, privacy_ner_mode="off") — 이것만으로도 등록된 이름은 보호되는지
  B) 규칙+가족 이름 사전+NER(R6 모델, 운영 merge_ner 그대로, 실험 B 아님) — 미등록 이름·중의성 문맥은
     어떻게 되는지

가상 가족: 민준(실명, 등록), 서연(실명, 등록), 하은(실명, 등록), 지호(실명, 등록),
도윤(실명)+별명"도도"(GroupMember.display_name 흉내), 훈(1글자 실명, 등록) — 전부 가상.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.gateway import Row, prepare_transcript, restore_value  # noqa: E402
from app.shared.privacy.policy import ANALYSIS  # noqa: E402

# (대표이름, [등록된 다른 표기(별명 등)])  - family_chat/ai_repository.member_names() 가 주는 모양과 동일
MEMBERS = [
    ("민준",),
    ("서연",),
    ("하은",),
    ("지호",),
    ("도윤", "도도"),  # 실명 + 등록된 별명(display_name)
    ("훈",),  # 1글자 실명(등록됨) - 1글자 보호 여부 확인용
]

SENTENCES = [
    "민준이 오늘 학교 갔어?",
    "서연이한테 연락해 줘.",
    "하은이랑 주말에 만나기로 했어.",
    "엄마가 지호 데리러 간대.",
    "보라색 가방 챙겨줘.",  # "보라"는 미등록 - 일반명사 과잉가명화 점검
    "사랑이가 오늘 유치원 갔어.",  # "사랑"도 미등록 - 중의성 점검
    "도도 숙제 다 했대?",  # 등록된 별명(display_name) 단독 사용
    "훈이 밥 먹었어?",  # 1글자 등록 이름 + 조사
    "민준이형지호형이 같이 놀았대.",  # 무공백 별명 둘(회귀 스트레스, 참고용)
]


def run_once(label: str, mode: str, model_dir: str | None) -> None:
    ner.reset()
    settings.privacy_ner_mode = mode
    settings.privacy_ner_model_dir = model_dir or ""
    settings.privacy_ner_threads = 2

    rows = [Row(i, "testuser", text) for i, text in enumerate(SENTENCES)]
    prep = prepare_transcript(rows, MEMBERS, ANALYSIS, speaker_tokens=True)

    print(f"\n================ {label} ================")
    for r, line in zip(SENTENCES, prep.lines, strict=False):
        flag = " <= 원문 그대로(이름 없음 or 비탐지)" if line.text == r else ""
        print(f"[{line.id}] 원문: {r}")
        print(f"     최종 전송 문자열: {line.text}{flag}")
    print(f"counts_by_kind(가린 개수): {prep.counts_by_kind}")
    print(f"blocked_ids: {prep.blocked_ids}")

    # 외부 LLM 호출은 하지 않는다 - 모델이 쓴 척하는 가짜 응답으로 복원만 확인한다 (restore 왕복 검증)
    fake_model_answer = f"오늘 {prep.lines[0].speaker}가 학교에 갔다고 알려왔어요."
    restored = restore_value(prep, fake_model_answer)
    print(f"[복원 테스트] 모델 응답(토큰 상태): {fake_model_answer}")
    print(f"[복원 테스트] 사용자에게 보여줄 최종 문자열: {restored.value}")

    prep.close()


def test_fail_closed() -> None:
    """required 모드에서 모델을 못 쓰면 외부 호출 전에 막히는지(ner.ensure_ready 가 503 성격 예외를 던지는지)."""
    print("\n================ Fail-closed 점검 (privacy_ner_mode=required, 모델 경로 고의로 깨뜸) ================")
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = r"C:\존재하지않는\경로"
    try:
        rows = [Row(0, "testuser", "민준이 오늘 학교 갔어?")]
        prepare_transcript(rows, MEMBERS, ANALYSIS, speaker_tokens=True)
        print("경고: 예외가 발생하지 않음 - fail-closed 미동작 가능성(직접 확인 필요)")
    except Exception as e:  # noqa: BLE001
        print(f"확인됨: 외부 호출 전에 예외로 막힘 -> {type(e).__module__}.{type(e).__name__}: {e}")


def main() -> None:
    run_once("A) 규칙+가족이름사전만 (NER 꺼짐)", "off", None)
    run_once(
        "B) 규칙+가족이름사전+NER(R6 모델, 운영 merge_ner)",
        "required",
        r"C:\Users\403\venvs\ner-runs\export\r6-candidate-s42",
    )
    test_fail_closed()


if __name__ == "__main__":
    main()
