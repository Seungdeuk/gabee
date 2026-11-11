"""업로드 평가 공통 도구: 비용 계산, 중간 저장, 헤드리스 호출, 서비스 import 준비.

- 서비스(app/) 코드는 고치지 않고 그대로 불러 쓴다. 평가용 호출은 `claude -p` 헤드리스(구독)로만 하고 ANTHROPIC_API_KEY 는 빼서 부른다.
- 서비스 호출(OCR·가리기)만 API 키를 쓴다. 비용은 응답의 실제 토큰 수 × 단가로 센다.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
DATA = HERE / "data"

# 달러 / 100만 토큰 (입력, 출력). 모르는 모델이면 비용을 추정하지 않고 멈춘다.
PRICES = {"sonnet-5-5": (2.0, 10.0), "haiku-5-5": (0.10, 0.50)}


def price_of(model: str) -> tuple[float, float]:
    for key, price in PRICES.items():
        if key in model:
            return price
    raise SystemExit(f"단가를 모르는 모델이라 멈춥니다: {model}")


def cost_of(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = price_of(model)
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def prepare_service_import() -> None:
    """서비스 설정을 불러오기 전에 기본 DB 를 임시 SQLite 로 돌린다(공용·개인 DB 에 연결하지 않는다)."""
    tmp = tempfile.mkdtemp(prefix="gabee-upload-eval-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/unused.db"
    sys.path.insert(0, str(HERE.parents[1]))  # apps/api


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: object) -> None:
    """임시 파일에 쓰고 바꿔 끼운다(쓰다 멈춰도 이전 저장이 남는다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Budget:
    """누적 비용을 세고 상한에 닿으면 새 문항을 시작하지 못하게 한다."""

    def __init__(self, max_usd: float, spent: float = 0.0) -> None:
        self.max_usd = max_usd
        self.spent = spent
        self.lock = threading.Lock()

    def add(self, usd: float) -> None:
        with self.lock:
            self.spent += usd

    def exhausted(self) -> bool:
        with self.lock:
            return self.spent >= self.max_usd


_CLI_CWD = Path(tempfile.mkdtemp(prefix="gabee-upload-cli-"))  # 빈 폴더: 프로젝트 설정을 읽지 않게


def headless(
    system: str, user: str, model: str = "sonnet", timeout: int = 600
) -> tuple[str, float]:
    """Claude Code 헤드리스로 한 번 부른다. (응답 글, 환산 비용). API 키는 환경에서 뺀다."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run(
        [
            shutil.which("claude") or "claude",
            "-p",
            "--model",
            model,
            "--system-prompt",
            system,
            "--tools",
            "",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--output-format",
            "json",
            "--no-session-persistence",
        ],
        input=user,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_CLI_CWD,
        env=env,
        timeout=timeout,
    )
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise ValueError(f"헤드리스 오류: {out.get('subtype')}")
    return out.get("result", ""), float(out.get("total_cost_usd") or 0)
