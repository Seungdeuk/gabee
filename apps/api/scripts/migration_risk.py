"""Alembic 리비전의 upgrade() 를 정적으로 검사해 자동 배포 전에 위험한 변경을 찾는다.

DB 연결 없이 AST 만 본다. 결과 심각도:
  block  파괴적(데이터 손실) 변경 또는 트랜잭션 밖에서 실행되는 변경. 리비전 docstring 에
         `destructive-approved: PR #<번호>` 가 있어야만 자동 적용을 허용한다(PR 리뷰에서 승인한 흔적).
  warn   기존 데이터와 충돌할 수 있는 제약 강화(NOT NULL/UNIQUE/FK). 자동 적용은 막지 않는다 —
         배포 전 "실제 백업을 복원한 임시 DB 에 먼저 적용"하는 리허설이 데이터 충돌을 잡는다.
"""

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

APPROVAL_RE = re.compile(r"^\s*destructive-approved:\s*PR\s*#\d+\b", re.IGNORECASE | re.MULTILINE)

UNSAFE_APPROVAL_RE = re.compile(
    r"^\s*unsafe-python-approved:\s*PR\s*#\d+\b", re.IGNORECASE | re.MULTILINE
)

# 마이그레이션은 DB 자격증명이 있는 프로세스에서 파이썬으로 실행된다. DB 스키마 변경에 필요한 모듈만 허용하고,
# 파일·네트워크·프로세스·동적 코드 실행으로 이어지는 코드는 막는다(리뷰된 예외는 unsafe-python-approved: PR #번호).
_ALLOWED_IMPORTS = {
    "__future__", "alembic", "sqlalchemy", "pgvector", "typing", "collections", "datetime",
    "decimal", "enum", "json", "uuid", "re", "math", "string", "itertools", "functools", "dataclasses",
}  # fmt: skip
_UNSAFE_CALLS = {"open", "eval", "exec", "compile", "__import__", "input", "breakpoint"}
_UNSAFE_ATTRS = {
    "__subclasses__",
    "__globals__",
    "__builtins__",
    "__code__",
    "__bases__",
    "__mro__",
}

_DESTRUCTIVE_CALLS = {"drop_table", "drop_column", "rename_table"}
_SQL_DESTRUCTIVE = re.compile(
    r"\b(DROP\s+(TABLE|COLUMN|SCHEMA|TYPE)|TRUNCATE|DELETE\s+FROM)\b", re.I
)
_SQL_NON_TRANSACTIONAL = re.compile(
    r"\bCONCURRENTLY\b|\bALTER\s+TYPE\b.*\bADD\s+VALUE\b", re.I | re.S
)
_CONSTRAINT_CALLS = {"create_unique_constraint", "create_foreign_key", "create_check_constraint"}


@dataclass(frozen=True)
class Finding:
    revision: str
    severity: str  # block | warn
    code: str
    message: str
    line: int

    def __str__(self) -> str:
        return f"[{self.severity}] {self.revision}:{self.line} {self.code} — {self.message}"


def _op_calls(node: ast.AST) -> Iterable[tuple[str, ast.Call]]:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "op"
        ):
            yield child.func.attr, child


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_const(node: ast.expr | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def _first_str(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _strings(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def _table_arg(call: ast.Call, call_name: str) -> str | None:
    # create_unique_constraint(name, table, cols) / create_foreign_key(name, source, ...) 는 2번째,
    # alter_column / add_column / create_index(name, table, ...) 도 아래 규칙으로 table 이름을 얻는다.
    index = 1 if call_name in _CONSTRAINT_CALLS | {"create_index"} else 0
    if len(call.args) > index and isinstance(call.args[index], ast.Constant):
        value = call.args[index].value
        return value if isinstance(value, str) else None
    return None


def _unsafe_python(
    tree: ast.AST, revision: str, approved: bool, extra_allowed: frozenset[str] = frozenset()
) -> list[Finding]:
    findings: list[Finding] = []
    allowed = _ALLOWED_IMPORTS | extra_allowed

    def add(code: str, message: str, node: ast.AST) -> None:
        severity = "warn" if approved else "block"
        suffix = " (unsafe-python-approved 표기로 허용)" if approved else ""
        findings.append(
            Finding(revision, severity, code, message + suffix, getattr(node, "lineno", 0))
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else ["(상대 import)"]
        else:
            names = []
        for name in names:
            if name.split(".")[0] not in allowed:
                add(
                    "unsafe-import",
                    f"허용되지 않은 import: {name} (파일·네트워크·프로세스 접근 가능)",
                    node,
                )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _UNSAFE_CALLS
        ):
            add("unsafe-call", f"위험한 내장 함수 호출: {node.func.id}()", node)
        if isinstance(node, ast.Attribute) and node.attr in _UNSAFE_ATTRS:
            add("unsafe-introspection", f"파이썬 내부 구조 접근: {node.attr}", node)
    return findings


def scan_source(source: str, revision: str) -> list[Finding]:
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree) or ""
    approved = bool(APPROVAL_RE.search(docstring))
    unsafe = _unsafe_python(tree, revision, bool(UNSAFE_APPROVAL_RE.search(docstring)))
    upgrade = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None
    )
    if upgrade is None:
        return [Finding(revision, "block", "no-upgrade", "upgrade() 함수가 없습니다", 1), *unsafe]

    calls = list(_op_calls(upgrade))
    created_here = {_first_str(c) for name, c in calls if name == "create_table"} - {None}
    findings: list[Finding] = []

    def add(severity: str, code: str, message: str, node: ast.AST) -> None:
        if severity == "block" and approved:
            severity, message = "warn", f"{message} (destructive-approved 표기로 허용)"
        findings.append(Finding(revision, severity, code, message, getattr(node, "lineno", 0)))

    for name, call in calls:
        if name in _DESTRUCTIVE_CALLS:
            add(
                "block",
                name,
                f"op.{name}: 데이터 또는 기존 앱 코드가 쓰는 객체를 삭제/이름 변경",
                call,
            )
        elif name == "alter_column":
            if _kwarg(call, "new_column_name") is not None:
                add("block", "rename-column", "컬럼 이름 변경: 기존 앱 코드와 호환되지 않음", call)
            if _kwarg(call, "type_") is not None:
                add("block", "alter-type", "컬럼 타입 변경: 데이터 변환/손실 위험", call)
            if (
                _is_const(_kwarg(call, "nullable"), False)
                and _table_arg(call, name) not in created_here
            ):
                add(
                    "warn",
                    "not-null",
                    "기존 컬럼 NOT NULL 강화: 기존 데이터·구 앱 코드와 충돌 가능",
                    call,
                )
        elif name == "add_column":
            column = call.args[1] if len(call.args) > 1 else None
            if (
                isinstance(column, ast.Call)
                and _is_const(_kwarg(column, "nullable"), False)
                and _kwarg(column, "server_default") is None
                and _table_arg(call, name) not in created_here
            ):
                add(
                    "warn",
                    "add-not-null",
                    "기본값 없는 NOT NULL 컬럼 추가: 기존 행/구 앱 코드와 충돌",
                    call,
                )
        elif name in _CONSTRAINT_CALLS or (
            name == "create_index" and _is_const(_kwarg(call, "unique"), True)
        ):
            if _table_arg(call, name) not in created_here:
                add(
                    "warn",
                    name,
                    "기존 테이블에 UNIQUE/FK/CHECK 추가: 기존 데이터와 충돌 가능",
                    call,
                )
        if name == "create_index" and _is_const(_kwarg(call, "postgresql_concurrently"), True):
            add(
                "block",
                "concurrently",
                "CONCURRENTLY 는 트랜잭션 밖에서 실행되어 원자적 롤백이 깨짐",
                call,
            )
        if name == "execute":
            for text in _strings(call):
                if _SQL_DESTRUCTIVE.search(text):
                    add("block", "destructive-sql", f"파괴적 SQL: {text.strip()[:60]}", call)
                if _SQL_NON_TRANSACTIONAL.search(text):
                    add(
                        "block",
                        "non-transactional-sql",
                        f"트랜잭션 밖 SQL: {text.strip()[:60]}",
                        call,
                    )

    for node in ast.walk(upgrade):
        if isinstance(node, ast.Attribute) and node.attr == "autocommit_block":
            add("block", "autocommit-block", "autocommit_block 은 원자적 롤백을 깨뜨림", node)
    return [*findings, *unsafe]


def unsafe_python(source: str, name: str, extra_allowed: Iterable[str] = ()) -> list[Finding]:
    """파일 전체(최상위 코드 포함)의 위험한 파이썬(block)만 찾는다. 리비전·모델 파일을 자격증명이 있는 프로세스가
    불러오기 *전에* 쓴다. 정적 검사라 모든 우회를 막지는 못한다(리뷰·CI 가 전제)."""
    tree = ast.parse(source)
    approved = bool(UNSAFE_APPROVAL_RE.search(ast.get_docstring(tree) or ""))
    return blocking(_unsafe_python(tree, name, approved, frozenset(extra_allowed)))


def scan_file(path: Path, revision: str) -> list[Finding]:
    return scan_source(path.read_text(encoding="utf-8"), revision)


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]
