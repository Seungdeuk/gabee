"""로컬 검사: CI(GitHub Actions)를 꺼 둔 동안 병합 전에 깨진 것을 잡는 유일한 관문이다.

  python scripts/check_local.py          빠른 검사(몇 분): 린트·포맷·Alembic head·시크릿 패턴·tests/ 폴더
  python scripts/check_local.py --full   전체 시험까지(30분 넘게 걸린다). 병합·배포 전에 한 번 돌린다

첫 실패에서 멈추고 종료 코드 1 을 돌려준다. 공용 DB 에는 연결하지 않는다(시험은 임시 SQLite 만 쓴다).
push 전에 자동으로 돌리려면 저장소 루트에서 한 번: git config core.hooksPath .githooks"""

import os
import subprocess
import sys
import time
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
PY = sys.executable
PYTEST = [PY, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "-W", "ignore"]
# 키·토큰 모양이 추적 파일에 들어갔는지(docs/legacy 는 제외)
SECRET_PATTERN = (
    r"sk-ant-[A-Za-z0-9_-]{10,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|"
    r"ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}"
)


def _secret_scan() -> int:
    found = subprocess.run(
        ["git", "grep", "-n", "-I", "-E", SECRET_PATTERN, "--", ".", ":!docs/legacy"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if found.stdout.strip():
        # 값은 출력하지 않고 위치만 보여 준다
        for line in found.stdout.splitlines():
            print("  ", line.split(":", 2)[0], line.split(":", 2)[1])
        return 1
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.splitlines()
    bad = [
        f
        for f in tracked
        if (Path(f).name.startswith(".env") and not f.endswith(".env.example"))
        or f.endswith(("env.yaml", ".keystore", ".jks"))
    ]
    for f in bad:
        print("   추적되면 안 되는 파일:", f)
    return 1 if bad else 0


def main() -> int:
    full = "--full" in sys.argv[1:]
    env = {**os.environ, "PYTHONPATH": str(API_ROOT)}
    steps: list[tuple[str, object]] = [
        ("ruff 린트", [PY, "-m", "ruff", "check", "."]),
        ("ruff 포맷", [PY, "-m", "ruff", "format", "--check", "."]),
        ("Alembic head 1개", [PY, "scripts/check_alembic_migrations.py", "heads"]),
        ("시크릿 패턴·추적 파일", _secret_scan),
        ("전체 시험" if full else "계약·보안 시험(tests/)", PYTEST + ([] if full else ["tests"])),
    ]
    for name, step in steps:
        started = time.monotonic()
        print(f"▶ {name}", flush=True)
        code = step() if callable(step) else subprocess.run(step, cwd=API_ROOT, env=env).returncode
        took = time.monotonic() - started
        if code != 0:
            print(f"✗ {name} 실패 ({took:.0f}초). 고친 뒤 다시 하세요.")
            return 1
        print(f"✓ {name} ({took:.0f}초)", flush=True)
    print(
        "모든 검사를 통과했어요."
        if full
        else "빠른 검사를 통과했어요. 병합 전에는 --full 도 돌려 주세요."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
