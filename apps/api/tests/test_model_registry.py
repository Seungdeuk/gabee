"""import_all_models() 가 app/features 아래 모든 models 모듈을 등록하는지 검사한다.

등록이 빠지면 alembic autogenerate 가 그 테이블을 "삭제 대상"으로 보고, 스키마 일치 검사도 그 테이블을 건너뛴다.
"""

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def test_every_feature_models_module_is_registered_by_import_all_models():
    expected = sorted(
        ".".join(path.relative_to(API_ROOT).with_suffix("").parts)
        for path in (API_ROOT / "app" / "features").rglob("models.py")
    )
    assert "app.features.ai_assistant.knowledge.models" in expected
    # `-I`(격리 모드)는 PYTHONPATH·현재 폴더를 sys.path 에 넣지 않는다. 이 체크아웃의 app 을 읽도록 경로를 직접 넣는다.
    # 안 그러면 가상환경에 편집 설치된 다른 체크아웃(worktree 에서 돌릴 때 메인 폴더)의 옛 코드를 읽어, 이 코드와 상관없이 실패하거나 통과한다.
    code = (
        f"import sys;sys.path.insert(0, {str(API_ROOT)!r});"
        "from app.shared.db import import_all_models;"
        "before=set(sys.modules);import_all_models();"
        f"missing=[m for m in {expected!r} if m not in sys.modules];print(missing)"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=API_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": str(API_ROOT), "DATABASE_URL": "sqlite:///:memory:", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip().splitlines()[-1] == "[]", out.stdout
