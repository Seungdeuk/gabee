"""known_names 등록 여부가 가명화 결과를 어떻게 바꾸는지 보이는 진단 스크립트(31절 실행).

v6 블라인드셋과 겹치지 않는 새 이름만 쓴다. 최종 검증용이 아니라 개발·진단용이고, 결과를
모델 선택이나 추가 학습에 쓰지 않는다. 서비스 모델·R1 양쪽에 돌려 "등록하면 모델과 무관하게
막힌다"는 것과 "별칭 충돌 시 복원표가 한쪽으로만 고정된다"는 것을 직접 보여준다.

사용: python diag_known_names.py <모델 폴더 1> [<모델 폴더 2> ...]
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.gateway import Row, prepare_transcript  # noqa: E402
from app.shared.privacy.policy import ANALYSIS  # noqa: E402

CASES = [
    ("환급소", "환급소 오늘 늦게 끝난대"),  # ORGLOC_표면형류, 신규(진단 전용)
    ("윤슬", "윤슬 데리러 누가 갈까"),  # 일반 이름, 신규
    (
        "강이",
        "강이 오늘 유치원에서 노래 배웠대",
    ),  # 애칭(서강->강이), NER 단독으로는 놓치는 것으로 확인됨
]


def run(model_dir: str, label: str) -> None:
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = model_dir
    settings.privacy_ner_threads = 2
    ner.reset()
    status = ner.ner_status()
    if not status["active"]:
        raise SystemExit(f"NER 엔진을 쓸 수 없다: {model_dir}")
    print(f"\n==== 모델: {label} (지문 {status['fingerprint']}) ====")
    for name, text in CASES:
        with prepare_transcript([Row(1, "", text)], [], ANALYSIS) as prep:
            out_unreg = prep.lines[0].text
        with prepare_transcript([Row(1, "", text)], [(name,)], ANALYSIS) as prep:
            out_reg = prep.lines[0].text
        print(f"  {name!r:8} | 미등록: {out_unreg!r:40} | 등록: {out_reg!r}")

    text = "강이 오늘 유치원에서 노래 배웠대"
    with prepare_transcript([Row(1, "", text)], [("서강", "강이")], ANALYSIS) as prep:
        print(f"  별칭묶음(서강,강이) 등록 -> {prep.lines[0].text!r}")

    text2 = "민이가 오늘 숙제했대"
    with prepare_transcript(
        [Row(1, "", text2)], [("강민서", "민이"), ("황민규", "민이")], ANALYSIS
    ) as prep:
        print(f"  별칭 충돌(강민서/민이, 황민규/민이) -> {prep.lines[0].text!r}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model_dirs", nargs="+")
    a = ap.parse_args(argv)
    for d in a.model_dirs:
        run(d, Path(d).name)


if __name__ == "__main__":
    main()
