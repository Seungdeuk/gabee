"""사진 한 장의 (문서 margin, 이미지 임베딩)을 구하는 통로. 가족 타임라인(family_chat)이 ai_assistant 의 내부 파일을 직접 import 하지 않고 쓰도록
ai_assistant 가 시작할 때 분석 함수를 등록한다(`shared/chat_library.py` 와 같은 방식). 외부 서비스 호출은 없다(로컬 ONNX 모델만).
분석 함수가 없거나 모델이 준비되지 않았으면 `FeaturesUnavailable` 이다: 타임라인은 그 사진을 자동 후보에서 빼고 실패로 적는다(문서·일반 사진을 확정하지 않는다)."""

from collections.abc import Callable

# bytes → (margin, 정규화된 임베딩). 실패하면 FeaturesUnavailable 을 던져도 되고 다른 예외를 던져도 된다(부르는 쪽이 종류 이름만 기록한다).
Analyzer = Callable[[bytes], tuple[float, list[float]]]
_analyzer: Analyzer | None = None


class FeaturesUnavailable(Exception):
    """분석 수단이 없거나 준비되지 않았다. 메시지는 종류 이름만(사진 내용 없음)."""


def register_analyzer(fn: Analyzer | None) -> None:
    """ai_assistant 가 시작할 때(또는 시험이) 분석 함수를 등록한다(None 이면 해제)."""
    global _analyzer
    _analyzer = fn


def analyze(data: bytes) -> tuple[float, list[float]]:
    """사진 바이트의 (margin, 임베딩). 분석 함수가 없으면 FeaturesUnavailable."""
    if _analyzer is None:
        raise FeaturesUnavailable("NoAnalyzer")
    return _analyzer(data)
