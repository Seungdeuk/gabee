"""AI 비서 고위험 입력 사전 차단(임시 방어).

팀원이 AI 비서(ai-assistant)를 가명화 게이트웨이에 연결하기 전까지, 주민등록번호·카드·계좌번호·비밀번호(인증번호)가 든
입력이 외부 LLM 으로 나가지 않게 라우터 앞에서 400 sensitive_content 로 거절한다. 전화·이메일·이름·주소·도구 결과는 막지 못한다
(docs/security/LLM_EGRESS_TEMP_GUARDS.md). 거절 응답·로그에는 탐지된 값을 절대 넣지 않는다.

- 의존성(`high_risk_guard`)을 main.py 의 AI 비서 라우터 등록에 붙인다(팀원 라우터 파일은 건드리지 않는다).
- 인증이 먼저다: 이 의존성이 current_user 에 의존해, 인증 실패는 기존처럼 401 이 되고 400 으로 바뀌지 않는다.
- 본문은 FastAPI 가 이미 읽어 Request 에 캐시해 둔 것을 재사용한다(await request.body()). 라우터의 Pydantic 파싱에 영향 없음.
- 본문이 상한을 넘으면 413 payload_too_large 로 거절한다(건너뛰면 패딩으로 우회된다).
- 본문이 JSON 이 아니거나 모양이 예상과 다르면 검사를 건너뛴다(라우터의 검증이 422 를 준다).
"""

import json

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.errors import ApiError, bad_request
from app.shared.privacy import detect
from app.shared.privacy.types import Kind

# 이 점수 이상의 후보가 있으면 거절한다. 메인 채팅은 가명화가 없어 낮은 점수도 원문이 나가므로 일정 에이전트의 0.7 보다 낮춘다.
# 근거(오탐 0 / 재현율)는 docs/security/LLM_EGRESS_TEMP_GUARDS.md 의 측정표.
MIN_SCORE = 0.45
BLOCKED_KINDS = frozenset({Kind.RRN, Kind.CARD, Kind.ACCOUNT, Kind.SECRET})
# 대상 경로에서 이보다 큰 본문은 검사하지 않고 413 payload_too_large 로 거절한다(건너뛰고 통과시키면 공백·모르는 필드로
# 부풀려 우회할 수 있다). 정상 요청의 최대치(문자열 4000자 x 11개: 한글 JSON 약 135KB, \uXXXX 이스케이프 약 270KB)보다 충분히 크다.
MAX_SCAN_BYTES = 512 * 1024
# 앱이 쓰지 않는 문서 직접 입력은 본문 길이 제한이 없어 더 크게 허용한다.
MAX_SCAN_BYTES_ITEMS = 2 * 1024 * 1024
MESSAGE = "주민등록번호·카드·계좌번호·비밀번호는 AI 비서에 입력하지 마세요"

# 가드가 붙는 기능(main.py 가 사용). care·billing 은 질문을 mask_text 로 가리지만 RRN·카드뿐이라 계좌·비밀번호는 그대로 나간다.
GUARDED_FEATURES = frozenset({"ai_assistant", "billing"})
# 대상 (POST, 경로) -> (사용자 입력 문자열 필드, 본문 상한). PATCH /knowledge/items/{id} 는 앱이 쓰는 경로라 넣지 않았다(한계로 문서화).
_TARGETS: dict[str, tuple[tuple[str, ...], int]] = {
    "/ai-assistant/chat": (("message", "history"), MAX_SCAN_BYTES),
    "/ai-assistant/knowledge/ask": (("question",), MAX_SCAN_BYTES),
    "/ai-assistant/knowledge/items": (("title", "body_md"), MAX_SCAN_BYTES_ITEMS),
    "/billing/agent/chat": (("message", "history"), MAX_SCAN_BYTES),
}


def _texts(data: object, fields: tuple[str, ...]) -> list[str]:
    """본문에서 검사할 사용자 입력 문자열을 꺼낸다. 모양이 다르면 빈 목록."""
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for f in fields:
        v = data.get(f)
        if isinstance(v, str):
            out.append(v)
        elif f == "history" and isinstance(v, list):
            out += [t["text"] for t in v if isinstance(t, dict) and isinstance(t.get("text"), str)]
    return out


def has_high_risk(text: str) -> bool:
    """text 에 RRN·CARD·ACCOUNT·SECRET 후보가 임계값 이상으로 있는지."""
    return any(s.kind in BLOCKED_KINDS and s.score >= MIN_SCORE for s in detect(text))


def _scan(raw: bytes, fields: tuple[str, ...]) -> bool:
    try:
        data = json.loads(raw)
    except ValueError:
        return False  # JSON 이 아니면 라우터의 검증(422)에 맡긴다
    return any(has_high_risk(t) for t in _texts(data, fields))


async def high_risk_guard(request: Request, _user: User = Depends(current_user)) -> None:
    """대상 POST 요청의 사용자 입력에 고위험 값이 있으면 400, 본문이 상한을 넘으면 413. 인증은 먼저 통과해야 한다.
    탐지는 이벤트 루프를 막지 않게 스레드풀에서 돌린다(긴 문자열도 전체를 검사해 우회 여지를 만들지 않는다)."""
    target = _TARGETS.get(request.url.path.rstrip("/"))
    if request.method != "POST" or target is None:
        return
    fields, limit = target
    raw = await request.body()
    if len(raw) > limit:
        raise ApiError(413, "payload_too_large", "요청이 너무 커요")
    if raw and await run_in_threadpool(_scan, raw, fields):
        raise bad_request("sensitive_content", MESSAGE)
