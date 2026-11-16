"""검증(val)·테스트(test) 분할 파일이 개발·튜닝 쪽 코드에 실수로 읽히지 않게 하는 코드 장치(E5b-B).

막는 것: 호출자가 단계를 밝히지 않은 채 val·test 사례 파일을 읽는 코드 경로. 개발 루프(`dev`)는 `load_rows("dev")` 만 쓰면
다른 분할 파일은 열리지 않는다. 검증 단계는 `stage="validation"`, 최종(테스트) 단계는 `stage="final"` 을 명시해야 읽힌다.
막지 못하는 것(문서 `docs/features/agent-eval.md` "평가 데이터 노출 경로"): 사람이나 에이전트가 저장소 파일을 직접 여는 것,
PR diff, 모델이 질문을 그대로 되풀이한 답·도구 인자(`trajectories.jsonl`). 이 모듈은 접근 제어가 아니라 실수 방지 장치다.
실제 테스트 실행의 횟수 제한은 `runs_guard`(이력 파일 예약)가 따로 맡는다.
"""

import json
import re
from pathlib import Path
from typing import Any

# `scenarios` 는 `seeds`(앱을 불러온다)를 쓰므로 CLI 가 환경을 정하기 전에 불러오지 않게 `load_rows` 안에서 늦게 불러온다.
LISTED_SPLITS = ("dev", "val", "test")
STAGE_OF_SPLIT = {"val": "validation", "test": "final"}  # 분할 -> 읽어도 되는 단계 이름
OPEN_SPLITS = ("legacy", "dev")  # 개발 루프가 자유롭게 읽는 분할
_TOKEN = re.compile(r"(?:^|[^a-z0-9])(val|test)(?:$|[^a-z0-9])")
_NOT_CASES = ("test_runs",)  # 테스트 실행 이력 파일은 사례 파일이 아니다


class ExposureError(RuntimeError):
    """보호된 분할을 단계를 밝히지 않고 읽으려 했다."""


def require_stage(split: str, stage: str | None) -> None:
    """dev·legacy 는 단계 없이 읽는다. val 은 `validation`, test 는 `final` 을 명시해야 한다."""
    if split in OPEN_SPLITS:
        return
    want = STAGE_OF_SPLIT.get(split)
    if want is None:
        raise ExposureError(f"알 수 없는 분할: {split!r}")
    if stage != want:
        raise ExposureError(
            f"{split} 분할은 호출자가 단계({want!r})를 명시해야 읽는다(받은 값: {stage!r}). 개발·튜닝 코드는 읽지 않는다"
        )


def protected_split_of(path: Path | str) -> str | None:
    """파일 이름으로 본 보호 분할(val·test). 사례 파일이 아니면 None."""
    stem = Path(path).stem.lower()
    if stem.startswith(_NOT_CASES):
        return None
    found = _TOKEN.search(stem)
    return found.group(1) if found else None


def assert_open_path(path: Path | str) -> Path:
    """개발·튜닝 코드가 사례 파일을 열기 전에 부른다. val·test 로 보이는 파일이면 거부한다."""
    split = protected_split_of(path)
    if split is not None:
        raise ExposureError(
            f"{split} 분할로 보이는 파일은 단계를 밝히지 않고 열지 않는다: {Path(path).name}"
        )
    return Path(path)


def read_split_file(
    path: Path | str, split: str, *, stage: str | None = None
) -> list[dict[str, Any]]:
    """한 분할의 JSON 배열 파일을 읽는다. 단계 확인이 먼저고, 통과하기 전에는 파일을 열지 않는다."""
    require_stage(split, stage)
    rows = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(rows, list):
        raise ExposureError(f"{Path(path).name} 는 배열이어야 한다")
    wrong = sorted(
        {str(r.get("split")) for r in rows if isinstance(r, dict) and r.get("split") != split}
    )
    if wrong:
        raise ExposureError(f"{Path(path).name} 에 {split} 분할이 아닌 항목이 있다: {wrong}")
    return rows


def load_rows(
    split: str, *, stage: str | None = None, directory: Path | None = None
) -> list[dict[str, Any]]:
    """시나리오 목록(`scenarios.DATA_DIR`)에서 요청한 분할의 파일 하나만 읽는다(다른 분할 파일은 열지 않는다)."""
    from . import scenarios

    if split not in LISTED_SPLITS:
        raise ExposureError(f"목록에 없는 분할: {split!r}")
    require_stage(split, stage)
    return read_split_file(
        (directory or scenarios.DATA_DIR) / f"scenarios_{split}.json", split, stage=stage
    )


__all__ = [
    "OPEN_SPLITS",
    "STAGE_OF_SPLIT",
    "ExposureError",
    "assert_open_path",
    "load_rows",
    "protected_split_of",
    "read_split_file",
    "require_stage",
]
