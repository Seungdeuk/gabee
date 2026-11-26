"""실호출을 허용하는 합성 사례 파일의 **고정 목록**(코드에 정의된 항목만).

공식 dev 36건 외에 실호출 게이트가 받는 합성 사례 파일은 아래 두 곳뿐이다. 새 파일을 더하려면 이 목록을 코드로 고쳐 리뷰를 받아야 한다(설정·인자·환경변수로는 더할 수 없다).
- `gen`: 일반화 사례 5건(`cases_gen_isolation.json`, #523)
- `todo_routing`: 할 일 라우팅 회귀 사례 2건(`cases_todo_routing.json`): `s-todo-01-family-only-01`, `s-todo-02-tab-only-01`

항목마다 정확한 파일 경로, 고정값 파일 경로, 사례 id 허용 목록, 고정값 검사 함수를 가진다. 검증은 `runner` 가 한곳에서 하고(사전 점검 7번·`cli._execute`·러너의 허가 확인이 같은 함수를 쓴다),
HEAD 커밋과의 일치·고정값·코드 정의와의 정합·id 중복·경로↔id 짝을 모두 본다. val·test·all 분할은 여기서 열리지 않는다(`real_gate.ALLOWED_SPLITS` 가 그대로 막는다).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovedSet:
    key: str  # "gen" | "todo_routing"
    label: str  # 거부 메시지에 쓰는 이름(받침 없는 낱말로 끝나야 '가/는' 조사가 맞다)
    id_prefix: str  # 사례 id 의 앞부분(메시지용)
    path: Path
    pins_path: Path
    ids: frozenset[str]
    check_pins: Callable[[], list[str]]

    @property
    def file_name(self) -> str:
        return self.path.name


def all_sets() -> tuple[ApprovedSet, ...]:
    """허용된 합성 사례 파일 목록. 호출할 때마다 각 모듈의 현재 값을 읽는다(고정값 검사 함수는 호출 시점에 찾는다)."""
    from . import gen_cases, todo_routing_cases

    return (
        ApprovedSet(
            key="gen",
            label="일반화 사례",
            id_prefix="s-gen-",
            path=gen_cases.GEN_PATH,
            pins_path=gen_cases.PINS_PATH,
            ids=frozenset(spec[0] for spec in gen_cases.SPECS),
            check_pins=lambda: gen_cases.check_pins(),
        ),
        ApprovedSet(
            key="todo_routing",
            label="할 일 라우팅 회귀 사례",
            id_prefix="s-todo-",
            path=todo_routing_cases.PATH,
            pins_path=todo_routing_cases.PINS_PATH,
            ids=frozenset(spec[0] for spec in todo_routing_cases.SPECS),
            check_pins=lambda: todo_routing_cases.check_pins(),
        ),
    )


def set_of_id(case_id: str) -> ApprovedSet | None:
    for spec in all_sets():
        if case_id in spec.ids:
            return spec
    return None


def is_path_of(spec: ApprovedSet, path: object) -> bool:
    """이 경로가 허용된 파일의 정확한 경로인가(심볼릭·상대 경로는 풀어서 비교한다)."""
    if path is None:
        return False
    try:
        return Path(str(path)).resolve() == spec.path.resolve()
    except OSError:
        return False
