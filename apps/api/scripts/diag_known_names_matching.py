"""known_names 정확 일치 규칙(detectors.detect)의 경계 동작을 보이는 진단 스크립트(32절 실행).

모델과 무관한 규칙 레이어만 분리해서 확인한다(NER 미사용, detect()만 호출) - 등록 이름이
다른 이름의 일부로 우연히 들어간 경우 오탐이 없는지, 조사 체인·띄어쓰기가 어떻게 처리되는지
보여준다. v6 블라인드셋과 무관한 새 이름만 쓰고, 결과를 모델 선택에 쓰지 않는다.

사용: python diag_known_names_matching.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.shared.privacy.detectors import detect  # noqa: E402

CASES = [
    ("정확 일치", "김민수가 왔어", ("김민수",)),
    ("조사 1개(야)", "민수야", ("민수",)),
    ("조사 1개(한테)", "민수한테", ("민수",)),
    ("조사 체인(님께)", "민수님께", ("민수",)),
    ("조사 체인(한테도)", "민수한테도", ("민수",)),
    ("부분일치-앞(다른 이름 안에 포함)", "안민수가 왔어", ("민수",)),
    ("부분일치-뒤(다른 이름 안에 포함)", "민수철이 왔어", ("민수",)),
    ("부분일치(등록 전체가 다른 이름의 일부)", "김민수가 왔어", ("민수",)),
    ("띄어쓰기-본문에 공백 삽입", "김 민수가 왔어", ("김민수",)),
    ("띄어쓰기-등록 자체에 공백", "김민수가 왔어", ("김 민수",)),
]


def main() -> None:
    for label, text, known in CASES:
        spans = detect(text, known)
        hits = [(s.kind.name, text[s.start : s.end]) for s in spans]
        print(f"[{label}] {text!r} (등록:{known}) -> {hits}")


if __name__ == "__main__":
    main()
