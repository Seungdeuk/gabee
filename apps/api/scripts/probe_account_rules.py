"""서비스 ACCOUNT 규칙 점검(연구용, 읽기 전용). 봉인 평가셋을 쓰지 않고 새로 쓴 가상 문장으로 현재 서비스 탐지·정책·게이트웨이 동작을 확인한다.

각 사례가 (1) 탐지되는지, (2) 점수가 block_min_score(0.7) 이상이라 BLOCK 되는지, (3) `apply`(가족 채팅 분석: 줄 통째 제외)와 `apply_values`(AI 어시스턴트: 값만 자리표시)
결과에서 원문 계좌번호가 남는지 출력한다. 모델 없이 규칙 계층만 쓴다(ACCOUNT 는 규칙만 만든다).
사용: python scripts/probe_account_rules.py [--json out.json]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.shared.privacy import policy as pol  # noqa: E402
from app.shared.privacy.ner import detect_with_ner  # noqa: E402
from app.shared.privacy.pseudonymizer import Pseudonymizer  # noqa: E402
from app.shared.privacy.types import Kind  # noqa: E402

# (이름, 문장, 계좌 값). 값은 문장 안에 그대로 있는 문자열이다. 전부 가상 번호.
CASES = [
    ("hyphen12+은행명", "국민은행 110-123-456789 로 보내줘", "110-123-456789"),
    ("hyphen13+은행명(농협)", "농협 351-0123-4567-83 입니다", "351-0123-4567-83"),
    ("hyphen+계좌단어", "계좌는 1002-345-678901 이야", "1002-345-678901"),
    ("hyphen+입금만", "내일까지 입금 부탁해 1002-345-678901", "1002-345-678901"),
    ("hyphen, 문맥 없음", "이 번호로 보내줘 110-123-456789", "110-123-456789"),
    ("붙임 13자리, 문맥 없음", "아래 번호야 1002123456789", "1002123456789"),
    ("붙임 13자리+계좌", "계좌 1002123456789", "1002123456789"),
    ("9자리(하이픈)+계좌", "계좌 123-456-789", "123-456-789"),
    ("11자리+은행", "신한은행 110-4512-3367", "110-4512-3367"),
    ("공백 구분+은행", "국민은행 110 123 456789", "110 123 456789"),
    ("엔대시 구분+은행", "국민은행 110–123–456789", "110–123–456789"),
    ("전각 숫자+은행", "국민은행 １１０-１２３-４５６７８９", "１１０-１２３-４５６７８９"),
    ("은행명이 번호 뒤", "110-123-456789 국민", "110-123-456789"),
    ("카카오뱅크 3333", "카카오뱅크 3333-01-1234567", "3333-01-1234567"),
    ("토스뱅크 12자리 붙임", "토스뱅크 100012345678 맞아?", "100012345678"),
    (
        "문맥이 20자보다 멀다",
        "계좌번호 알려달라고 하셔서 방금 확인해 보니까 말이야 110-123-456789",
        "110-123-456789",
    ),
    ("주문번호 근처", "주문번호 계좌 110-123-456789", "110-123-456789"),
    ("15자리", "국민은행 110123456789012", "110123456789012"),
    ("두 계좌 한 문장", "국민 110-123-456789 그리고 농협 351-0123-4567-83", "110-123-456789"),
]
POLICY = pol.ASSISTANT


def run():
    out = []
    for name, text, val in CASES:
        spans = detect_with_ner(text, ())
        acc = [s for s in spans if s.kind is Kind.ACCOUNT]
        blocked_score = [round(s.score, 2) for s in acc if s.score >= POLICY.block_min_score]
        covers = any(
            s.start <= text.index(val) and s.end >= text.index(val) + len(val) for s in acc
        )
        with Pseudonymizer() as pz:
            a = pz.apply(text, POLICY)
        with Pseudonymizer() as pz:
            b = pz.apply_values(text, POLICY)
        digits = "".join(ch for ch in val if ch.isdigit())
        out.append(
            {
                "case": name,
                "detected": bool(acc),
                "covers_value": covers,
                "scores": [round(s.score, 2) for s in acc],
                "block_grade": bool(blocked_score),
                "apply_blocked_line": a.blocked,
                "apply_raw_value_leaks": digits in "".join(ch for ch in a.text if ch.isdigit())
                if not a.blocked
                else False,
                "apply_values_raw_value_leaks": digits
                in "".join(ch for ch in b.text if ch.isdigit()),
            }
        )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    res = run()
    for r in res:
        print(
            f"{r['case']:24s} detected={r['detected']!s:5} scores={r['scores']} block={r['block_grade']!s:5} apply_leak={r['apply_raw_value_leaks']!s:5} values_leak={r['apply_values_raw_value_leaks']}"
        )
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
