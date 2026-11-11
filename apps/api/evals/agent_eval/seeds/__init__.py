"""평가용 합성 가족 월드(E4b-2). 데이터 선언은 `data.py`, 만드는 코드는 `world.py`, 검사용 조회는 `inspect_world.py`."""

from .world import World, build_legacy, build_world, enable_ai

__all__ = ["World", "build_legacy", "build_world", "enable_ai"]
