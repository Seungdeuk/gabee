"""R11 이미지 fail-closed 시험(컨테이너 안에서 실행, 합성 이름만). 인자: <case>.
각 케이스에서 required 모드의 가명화 입구(prepare_transcript)가 PrivacyUnavailable(503 privacy_unavailable)로 막히는지,
그리고 소켓 connect 시도(=외부 전송 시도)가 0 인지 센다. --network none 과 함께 쓴다."""

import json
import socket
import sys

attempts = {"n": 0}
_orig = socket.socket.connect


def counting_connect(self, *a, **k):
    attempts["n"] += 1
    return _orig(self, *a, **k)


socket.socket.connect = counting_connect

from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.gateway import Row, prepare_transcript  # noqa: E402
from app.shared.privacy.policy import ANALYSIS  # noqa: E402

case = sys.argv[1] if len(sys.argv) > 1 else "ok"
held = None
if case == "infer_exception":
    ner.ner_status()  # 엔진을 먼저 정상 로드한 뒤(워밍업 통과) 로드 이후 추론에서 예외를 낸다
    import onnxruntime as ort

    def boom(self, *a, **k):
        raise RuntimeError("synthetic inference failure")

    ort.InferenceSession.run = boom
elif case == "timeout":
    ner.TIME_BUDGET_SECONDS = 0.0
elif case == "concurrency_limit":
    ner.QUEUE_WAIT_SECONDS = 0.05
    cfg = ner._config()
    held = ner._semaphore(cfg.concurrency)
    for _ in range(cfg.concurrency):
        held.acquire()

out = {"case": case, "mode": ner.current_mode()}
try:
    out["status"] = ner.ner_status()
except Exception as e:  # noqa: BLE001
    out["status_error"] = type(e).__name__
rows = [Row(1, "정하율", "고은채한테 010-1234-5678 로 연락해 줘")]
try:
    with prepare_transcript(rows, [("정하율",), ("고은채",)], ANALYSIS) as prep:
        out["blocked"] = False
        out["leaked_raw"] = any(x in prep.lines[0].text for x in ("고은채", "010-1234-5678"))
except Exception as e:  # noqa: BLE001
    out["blocked"] = True
    out["exception"] = type(e).__name__
    out["status_code"] = getattr(e, "status_code", None)
    out["code"] = getattr(e, "code", None)
out["socket_connect_attempts"] = attempts["n"]
print(json.dumps(out, ensure_ascii=False))
