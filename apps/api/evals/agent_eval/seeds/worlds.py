"""월드 이름(`w1`·`w2`)과 분할로 그 월드의 데이터 선언 모듈을 고른다.

- w1 = 개발(dev, 기존 정산 52건도 같은 월드) `data.py`, w2 = 검증(val) `data_w2.py`. w3(test)는 아직 만들지 않았다(`scenarios_meta.json` 의 `planned`): 고르려 하면 거부한다.
- 고르는 곳(채점·금지 문자열·월드 만들기)이 모두 이 함수를 거치므로 val 사례가 dev 월드의 값으로 채점되는 일이 없다. 기본값은 항상 w1 이라 dev 의 동작은 그대로다.
"""

from types import ModuleType

from . import data, data_w2

WORLD_DATA: dict[str, ModuleType] = {"w1": data, "w2": data_w2}
WORLD_OF_SPLIT = {"legacy": "w1", "dev": "w1", "val": "w2"}  # test(w3)는 아직 없다


def data_of(world: str = "w1") -> ModuleType:
    """월드 이름의 데이터 선언 모듈."""
    try:
        return WORLD_DATA[world]
    except KeyError:
        raise ValueError(f"아직 만들지 않은 월드다: {world}") from None


def data_of_split(split: str) -> ModuleType:
    """분할(legacy·dev·val)의 월드 데이터 선언 모듈. test 는 월드(w3)가 없어 거부한다."""
    try:
        return data_of(WORLD_OF_SPLIT[split])
    except KeyError:
        raise ValueError(f"월드가 없는 분할이다: {split}") from None
