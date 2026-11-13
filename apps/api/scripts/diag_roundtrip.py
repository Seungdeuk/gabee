"""소통·일정·주간뉴스 세 경로의 가명화->복원 왕복이 정상인지 보이는 진단 스크립트(33절 실행).

세 기능이 실제로 쓰는 호출 패턴(정책·API)을 그대로 재현한다. 새 합성 이름만 쓰고, v6 블라인드셋과는
무관하다. 실제 가족 대화를 쓰지 않는다.

사용: python diag_roundtrip.py <모델 폴더>
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.features.schedule.agent.chat import POLICY as SCHEDULE_POLICY  # noqa: E402
from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.freetext import new_session  # noqa: E402
from app.shared.privacy.gateway import Row, prepare_transcript, restore_json, restore_value  # noqa: E402
from app.shared.privacy.policy import ANALYSIS, ASSISTANT  # noqa: E402


def check_family_chat() -> None:
    members = [("정하율",), ("고은채", "은채")]
    rows = [
        Row(1, "정하율", "은채 생일 선물 뭐 사줄지 고민 중이야"),
        Row(2, "은채", "나는 책 받고 싶어"),
    ]
    with prepare_transcript(rows, members, ANALYSIS) as prep:
        fake_reply = (
            f"{prep.lines[0].speaker}님이 {prep.lines[1].speaker}님 선물을 고민하고 있어요."
        )
        restored = restore_value(prep, fake_reply, generalize_unknown=True, scrub=True)
    ok = (
        restored.value == "정하율님이 고은채님 선물을 고민하고 있어요."
        and not restored.unknown_tokens
    )
    print(f"[소통] {'OK' if ok else 'FAIL'} -> {restored.value!r}")


def check_schedule() -> None:
    members = [("박시우",), ("강태민",)]
    rows = [
        Row(
            1,
            "박시우",
            "태민이 다음주 화요일 저녁 7시에 치과 예약 좀 잡아줘, 전화번호는 010-1234-5678이야",
        )
    ]
    with prepare_transcript(rows, members, SCHEDULE_POLICY, speaker_tokens=False) as prep:
        memo = prep.lines[0].text
        struct = {"title": f"{memo.split()[0]} 치과 예약", "memo": memo}
        restored = restore_json(prep, struct)
    ok = (
        restored.value["title"] == "강태민이 치과 예약"
        and "010-1234-5678" in restored.value["memo"]
    )
    print(f"[일정] {'OK' if ok else 'FAIL'} -> {restored.value}")


def check_weekly_news() -> None:
    members = [("윤도윤",), ("임서아",)]
    sess = new_session(ASSISTANT, members)
    try:
        line = sess.prepare_text("도윤이랑 서아가 이번 주에 캠핑 다녀왔대요")
        restored = restore_value(
            sess, f"이번 주 가족 소식: {line}", generalize_unknown=True, scrub=True
        )
    finally:
        sess.close()
    ok = restored.value == "이번 주 가족 소식: 윤도윤이랑 임서아가 이번 주에 캠핑 다녀왔대요"
    print(f"[주간뉴스] {'OK' if ok else 'FAIL'} -> {restored.value!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model_dir")
    a = ap.parse_args()

    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = a.model_dir
    settings.privacy_ner_threads = 2
    ner.reset()
    status = ner.ner_status()
    if not status["active"]:
        raise SystemExit(f"NER 엔진을 쓸 수 없다: {a.model_dir}")
    print(f"모델: {Path(a.model_dir).name} (지문 {status['fingerprint']})")

    check_family_chat()
    check_schedule()
    check_weekly_news()


if __name__ == "__main__":
    main()
