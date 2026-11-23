"""별도 워커 프로세스 진입점(`worker_main`) 시험: 웹 서버가 없는 새 인터프리터에서도 작업 표의 외래키 대상 모델이 모두 등록돼야 한다.

(실제 SigLIP2 E2E 에서 발견: 모델이 하나도 없는 새 프로세스는 첫 작업 선점에서 `NoReferencedTableError` 로 루프가 계속 실패했다.)"""

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[4]


def _run_fresh(code: str, tmp_path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        DATABASE_URL=f"sqlite:///{tmp_path / 'fresh.db'}",
        DATA_DIR=str(tmp_path),
        FAMILY_MEMORY_ENABLED="false",
        FAMILY_MEMORY_WORKER_ENABLED="false",
        FAMILY_MEMORY_ENCODER="off",
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_fresh_worker_process_can_resolve_the_job_table_foreign_keys(tmp_path):
    code = (
        "from app.features.family_memory import worker_main\n"
        "from app.shared.db import Base, engine\n"
        "rc = worker_main.main()\n"  # 스위치가 꺼져 있어 2 로 끝나지만, 그 전에 모델을 등록해야 한다
        "Base.metadata.create_all(engine)\n"  # 외래키 대상(message_attachments 등)이 없으면 여기서 실패
        "from sqlalchemy import inspect\n"
        "names = set(inspect(engine).get_table_names())\n"
        "assert {'family_memory_jobs', 'message_attachments'} <= names, names\n"
        "print('rc', rc)\n"
    )
    result = _run_fresh(code, tmp_path)
    assert result.returncode == 0, result.stderr[-1500:]
    assert "rc 2" in result.stdout  # 꺼진 상태 종료 코드는 그대로


def test_register_models_is_idempotent(tmp_path):
    code = (
        "from app.features.family_memory import worker_main\n"
        "worker_main.register_models()\n"
        "worker_main.register_models()\n"
        "print('ok')\n"
    )
    result = _run_fresh(code, tmp_path)
    assert result.returncode == 0, result.stderr[-1500:]
