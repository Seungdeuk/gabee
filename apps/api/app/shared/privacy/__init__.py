"""외부 LLM 으로 보내는 대화의 개인정보를 줄이는 가명화 파이프라인(서버 기준, 요청 메모리 안에서만 동작).

E2EE 가 아니며 완전한 보호를 보장하지 않는다. 사용법은 docs/security/PRIVACY_PIPELINE_MODULE.md 참고.
"""

from .detectors import detect
from .gateway import Prepared, PreparedLine, Row, prepare_transcript, restore_json, restore_value
from .policy import ANALYSIS, REPLY, TOPICS, Action, Policy
from .pseudonymizer import MaskResult, Pseudonymizer, RestoreResult
from .types import Kind, Risk, Span

# 탐지·정책·토큰 규칙을 바꾸면 올린다. AI 결과 캐시 키에 들어가 규칙이 바뀐 뒤에는 옛 캐시(옛 토큰 번호)를 쓰지 않는다.
MODULE_VERSION = "1"

__all__ = [
    "MODULE_VERSION",
    "ANALYSIS",
    "REPLY",
    "TOPICS",
    "Action",
    "Kind",
    "MaskResult",
    "Policy",
    "Prepared",
    "PreparedLine",
    "Pseudonymizer",
    "RestoreResult",
    "Risk",
    "Row",
    "Span",
    "detect",
    "prepare_transcript",
    "restore_json",
    "restore_value",
]
