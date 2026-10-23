"""마이그레이션의 위험한 파이썬 코드 검사 — 마이그레이션은 DB 자격증명이 있는 프로세스에서 실행된다."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migration_risk as risk  # noqa: E402

NL = chr(10)


def source(*lines: str, doc: str = "x") -> str:
    head = ['"""' + doc + '"""', *lines, 'revision = "x1"', "def upgrade():", "    pass"]
    return NL.join(head) + NL


def blocked_codes(src: str) -> set[str]:
    return {f.code for f in risk.scan_source(src, "x1") if f.severity == "block"}


@pytest.mark.parametrize(
    "line",
    [
        "import os",
        "import subprocess",
        "import socket",
        "import shutil",
        "import urllib.request",
        "from pathlib import Path",
        "from . import helper",
        "import requests",
    ],
)
def test_imports_that_reach_files_network_or_processes_are_blocked(line):
    assert "unsafe-import" in blocked_codes(source(line))


def test_dynamic_code_and_python_internals_are_blocked():
    body = [
        'data = open("/etc/passwd").read()',
        'eval("1")',
        'exec("2")',
        '__import__("os")',
        "x = ().__class__.__bases__",
    ]
    src = (
        NL.join(['"""x"""', 'revision = "x1"', "def upgrade():", *("    " + b for b in body)]) + NL
    )
    found = blocked_codes(src)
    assert {"unsafe-call", "unsafe-introspection"} <= found


def test_schema_modules_are_allowed():
    src = source(
        "from collections.abc import Sequence",
        "import sqlalchemy as sa",
        "import pgvector.sqlalchemy",
        "from alembic import op",
    )
    assert risk.blocking(risk.scan_source(src, "x1")) == []


def test_reviewed_exception_is_only_a_warning_and_needs_its_own_marker():
    reviewed = source("import os", doc="x" + NL + NL + "unsafe-python-approved: PR #55")
    findings = risk.scan_source(reviewed, "x1")
    assert risk.blocking(findings) == [] and any(f.code == "unsafe-import" for f in findings)

    wrong_marker = source("import os", doc="x" + NL + NL + "destructive-approved: PR #55")
    assert "unsafe-import" in blocked_codes(wrong_marker)  # 파괴적 변경 승인으로는 넘길 수 없다


def test_unsafe_code_outside_upgrade_is_also_caught():
    src = NL.join(['"""x"""', "import os", 'revision = "x1"', "def helper():", "    return 1"]) + NL
    codes = blocked_codes(src)
    assert {"unsafe-import", "no-upgrade"} <= codes
